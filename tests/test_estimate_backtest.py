"""J8: score the estimator against a recorded real run instead of trusting it.

An estimator nobody backtested is a guess with a progress bar. This file replays
the 721 MB corpus from ``docs/benchmarks/2026-08-01-real-programs-folder.md``
through the analyzer, planner and estimator, and checks the prediction against
what that run actually measured.

Honest caveat, and the reason this file is not the whole of J8: those numbers are
the set the shipped rates were *calibrated on*, so this is an in-sample check.
It is a regression guard - it catches the day someone changes the model and
quietly breaks the fit - not evidence the estimator generalises. The
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

CORPUS = Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
              r"\0No Need To Check\Programs")

# The exact subset the run used, with the sizes it was measured at. A size
# mismatch means the file changed underneath us and the comparison is void.
FILES = {
    "R-4.5.1-win.exe": 90_111_968,
    "Windows-KB890830-x64-V5.129.exe": 76_629_432,
    "lghub_installer.exe": 58_146_712,
    "DB.Browser.for.SQLite-v3.13.0-win64.msi": 19_783_680,
    "Winxvideo.AI.3.5.0.0.w64.rar": 212_734_622,
    "Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip": 263_670_338,
}
TOTAL = sum(FILES.values())          # 721,076,752

# profile -> (measured saved fraction, measured compress seconds)
MEASURED = {
    Profile.NORMAL: (0.0280, 62.4),
    Profile.EXTREME: (0.0297, 166.3),
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


def _corpus_ready() -> bool:
    return all((CORPUS / name).is_file()
               and (CORPUS / name).stat().st_size == size
               for name, size in FILES.items())


pytestmark = pytest.mark.skipif(
    not _corpus_ready(),
    reason="the 2026-08-01 benchmark corpus is not present at its recorded sizes")


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
