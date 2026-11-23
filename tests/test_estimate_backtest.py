"""J8: score the estimator against a recorded real run instead of trusting it.

An estimator nobody backtested is a guess with a progress bar. This file replays
the 721 MB corpus through the analyzer, planner and estimator, and checks the
prediction against what a real run measured.

The reference run is the POST-B11/D9 one (chain is precomp->sevenzip, and the
measured time includes the pre-publish restore+verify the user now always waits
for). The original srep-chain run in
``docs/benchmarks/2026-08-01-real-programs-folder.md`` measured a workflow that
no longer exists and stays as history only.

Honest caveat, and the reason this file is not the whole of J8: these numbers
are the set the shipped rates were *calibrated on*, so this is an in-sample
check. It is a regression guard - it catches the day someone changes the model
and quietly breaks the fit - not evidence the estimator generalises. The
out-of-sample evidence lives in
``docs/benchmarks/2026-08-01-estimator-backtest.md``.

Skipped unless the corpus is present, so the suite still runs on a machine that
has never seen this external drive.
"""

from pathlib import Path

import pytest

from excmp.analyzer import analyze_file
from excmp.estimate import estimate_size, estimate_time
from excmp.planner import Profile, plan as make_plan
from excmp.tools import find_tools
from corpus_paths import first_holding

# 2026-11-21: the owner deletes the original folders, so each corpus falls back to a
# SHA-256-verified copy under C:\excmp-bench\temp-copies (manifests sit beside them).
_PROGRAMS = (Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
              r"\0No Need To Check\Programs"),
             Path(r"C:\excmp-bench\temp-copies\Programs"))

# The exact subset the run used, with the sizes it was measured at. A size
# mismatch means the file changed underneath us and the comparison is void.
FILES = {
    "R-4.5.1-win.exe": 90_111_968,
    "Windows-KB890830-x64-V5.129.exe": 76_629_432,
    "lghub_installer.exe": 70_346_392,
    "DB.Browser.for.SQLite-v3.13.0-win64.msi": 19_783_680,
    "Winxvideo.AI.3.5.0.0.w64.rar": 212_734_622,
    "Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip": 263_670_338,
}
CORPUS = first_holding(_PROGRAMS, FILES)   # the original only while it still holds every file
TOTAL = sum(FILES.values())          # 733,276,432

# profile -> (measured saved fraction, measured total seconds including the
# D9 restore+verify gate).
#
# RE-BASELINED 2026-09-21. `lghub_installer.exe` was deleted from this live
# folder and re-downloaded, and the new build is 70,346,392 B against the
# 58,146,712 B that was measured - so the size gate did its job and refused
# the comparison rather than quietly scoring against different bytes.
#
# Re-measured rather than adjusted, because that file is load-bearing: at
# sample_ratio 0.4653 it is the ONLY compressible member of the corpus. The
# other five measure 0.82, 0.96, 0.97, 1.00, 1.00, so substituting anything
# else from the folder collapses the corpus's saving to ~0.1% and leaves the
# estimator scored on data where predicting "no change at all" would pass.
# (HandBrake, the nearest executable by size, measures 0.9942 and was tried:
# normal fell from 2.80% to 0.0905%.) The new build is the same shape as the
# old - ratio 0.4653 vs 0.4411, entropy 6.55 vs 6.51 - so the corpus keeps
# its character and only its numbers move.
#
# Post-B11 chain, six files, 733,276,432 B:
#   normal  707,893,728 B, 100.7s   (was 700,884,250 B / 103.8s over 721 MB)
#   extreme 706,559,396 B, 355.9s   (was 699,648,205 B / 254.3s over 721 MB)
#
# THE TIME IS A MEDIAN OF THREE, AND THE FIRST ONE IS THE TRAP. Normal ran
# 143.3s, then 80.9s, then 100.7s over byte-identical input producing a
# byte-identical archive - a 1.77x spread with nothing but the OS file cache
# moving. Reading all 733 MB of the corpus straight through takes **1.7s at
# 426 MB/s**, so the external drive is NOT the bottleneck once it is warm, and
# the cold first pass costs ~40%.
#
# Pinning 143.3 would have baked a cache state into the gate and reported the
# estimator as broken: it predicts 88.1s with a 64.4-135.6s band, which brackets
# both warm runs and misses only the cold one. The old 103.8s figure sits in the
# middle of the warm pair, which is the other reason to think 143.3 was the
# outlier rather than the truth.
#
# RE-MEASURED 2026-10-01, for two reasons at once. The target machine is now
# an i5-7200U (the 100.7 / 355.9 s pins above were i7-3540M numbers), and
# "auto" threads now passes 7-Zip one thread per physical core (2) instead
# of letting it take all 4 logical processors. Same six files, same
# measurement (engine.compress wall time, D9 included), three runs each,
# median pinned:
#   normal  707,893,728 B   100.3 / 70.1 / 91.0 s    -> 91.0
#   extreme 706,559,667 B   454.1 / 475.4 / 334.5 s  -> 454.1
# Normal's bytes are unchanged to within 1 B (rep 3: 707,893,727, the
# container is not byte-reproducible): its 160 MB piped share (153 MiB) is one
# 256 MiB LZMA2 block, so thread count cannot split it. Extreme pipes 444 MB
# (423 MiB), already past one block before Precomp expands anything, which is
# where 2 threads trades time for RAM; its whole archive differs from the
# 4-thread run by 271 B in 707 MB.
# Extreme's spread (1.42x) is wider than Normal's and is recorded, not hidden.
MEASURED = {
    Profile.NORMAL: (0.0346, 91.0),
    Profile.EXTREME: (0.0364, 454.1),
}

SIZE_TOLERANCE = 0.10   # +/-10% of the measured archive size
TIME_TOLERANCE = 0.40   # +/-40% of the measured compress time

# Precomp chains get a wider gate, and the reason is a finding rather than an
# excuse. Measured on two real corpora, the same chain ran at 2.642 MB/s when
# Precomp found nothing to expand and 0.842 MB/s when it did - a 3.1x spread
# between two regimes, with no cheap signal telling them apart beforehand. The
# shipped rate is the geometric mean, so it is ~76% high in the first regime and
# ~43% low in the second. Tightening this number would mean pretending to
# knowledge the probe does not have; J7's self-calibration is the real fix.
PRECOMP_TIME_TOLERANCE = 0.80


def _tolerance_for(profile: Profile) -> float:
    return PRECOMP_TIME_TOLERANCE if profile is Profile.EXTREME else TIME_TOLERANCE


def _corpus_gaps() -> list[str]:
    """Which pinned files are missing or the wrong size, by name.

    The generic "the corpus is not present" this used to say cost a session:
    the folder is live, one 58 MB installer had been deleted, and all eight
    tests below switched themselves off while the suite reported 1,271 passed.
    A skip nobody can act on is a skip nobody notices.
    """
    gaps = []
    for name, size in FILES.items():
        path = CORPUS / name
        if not path.is_file():
            gaps.append(f"{name} (missing)")
        elif path.stat().st_size != size:
            gaps.append(f"{name} ({path.stat().st_size:,} B, expected {size:,})")
    return gaps


_GAPS = _corpus_gaps()

pytestmark = pytest.mark.skipif(
    bool(_GAPS),
    reason="the 2026-08-01 benchmark corpus has changed: " + "; ".join(_GAPS))


@pytest.fixture(scope="module")
def infos():
    """Analyzing 6 files reads 3 MiB each off an external drive - do it once."""
    return [analyze_file(CORPUS / name) for name in FILES]


@pytest.fixture(scope="module")
def tools():
    return find_tools()


def test_the_corpus_is_the_one_that_was_measured(infos):
    assert sum(i.size for i in infos) == TOTAL


@pytest.mark.parametrize("profile", list(MEASURED))
def test_predicted_size_is_within_ten_percent(profile, infos, tools):
    measured_saved, _seconds = MEASURED[profile]
    measured_bytes = TOTAL * (1 - measured_saved)

    est = estimate_size(infos, make_plan(infos, profile, tools))
    error = (est.expected - measured_bytes) / measured_bytes

    assert abs(error) <= SIZE_TOLERANCE, (
        f"{profile.value}: predicted {est.expected:,} bytes, measured "
        f"{measured_bytes:,.0f} ({error:+.1%})")
    # A range that does not contain the answer is worse than no range.
    assert est.low <= measured_bytes <= est.high


@pytest.mark.parametrize("profile", list(MEASURED))
def test_a_precomp_chain_estimate_is_a_ceiling_and_admits_it(profile, infos, tools):
    """For Precomp chains ``expected`` assumes Precomp finds nothing, so it must
    never come out *under* the measured size - undershooting would be the
    estimator promising a win it cannot see and may not get."""
    measured_bytes = TOTAL * (1 - MEASURED[profile][0])
    est = estimate_size(infos, make_plan(infos, profile, tools))

    assert est.upper_bound is (profile is Profile.EXTREME)
    if est.upper_bound:
        assert est.expected >= measured_bytes


@pytest.mark.parametrize("profile", list(MEASURED))
def test_predicted_time_is_within_tolerance(profile, infos, tools):
    _saved, measured_seconds = MEASURED[profile]
    tolerance = _tolerance_for(profile)

    est = estimate_time(infos, make_plan(infos, profile, tools))
    error = (est.expected - measured_seconds) / measured_seconds

    assert abs(error) <= tolerance, (
        f"{profile.value}: predicted {est.expected:.1f}s, measured "
        f"{measured_seconds:.1f}s ({error:+.1%}, gate +/-{tolerance:.0%})")
    # The range is the part that must never miss, whatever the point estimate does.
    assert est.low <= measured_seconds <= est.high


def test_the_recorded_bad_trade_is_predicted_before_it_is_paid_for(infos, tools):
    """The one number that justifies Phase J: Extreme cost 2.7x Normal's time
    for 0.17 extra percentage points. The estimator has to see that coming.

    Only the *direction* is asserted, not the multiple. Getting 2.7x on the nose
    would need the estimator to know in advance that Precomp was going to find
    nothing in this corpus, which is exactly what it cannot know. What it must do
    is notice the trade is bad and say so - and never claim Extreme will save a
    lot here, because it did not.
    """
    normal = estimate_time(infos, make_plan(infos, Profile.NORMAL, tools))
    extreme = estimate_time(infos, make_plan(infos, Profile.EXTREME, tools))

    assert extreme.expected >= normal.expected * 2
    assert extreme.low <= MEASURED[Profile.EXTREME][1] <= extreme.high

    n_size = estimate_size(infos, make_plan(infos, Profile.NORMAL, tools))
    e_size = estimate_size(infos, make_plan(infos, Profile.EXTREME, tools))
    extra_points = e_size.saved_percent - n_size.saved_percent
    assert extra_points < 1.0, "Extreme must not be predicted a big win here"
