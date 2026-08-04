"""The estimator: predicted output size and predicted time (J1/J2), and the
properties that make those predictions honest rather than decorative (J8).

The load-bearing property is the first test in this file: bytes that get stored
are copied verbatim, so their contribution to the size estimate is not a
prediction at all - it is arithmetic, and it must be exact. Everything else in
here is about not lying in the other direction: ranges that actually bracket,
no profile ever predicted to inflate data, and the "not worth it" flag firing on
the real corpus that motivated the whole phase.

Rates are keyed by the *resolved chain*, not the profile name. That matters:
when Precomp is missing, Extreme degrades to the same stages Fast runs, and its
estimate must then equal Fast's rather than promising something the machine
cannot deliver.
"""

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import (DEFAULT_RATES, Rates, compare_profiles,
                            estimate_size, estimate_time)
from excmp.planner import Profile, plan as make_plan

ALL_TOOLS = {"7z": object(), "precomp": object(), "srep": object()}
NO_TOOLS: dict[str, object] = {}

SEVENZIP = ["sevenzip"]

# The 2026-08-01 corpus, size-for-size, with the sample ratios measured off the
# real files. Keeping the real numbers here means the always-run tests exercise
# the same shape the corpus-gated backtest does.
# (name, size, category, entropy, mean ratio, max ratio)
REAL_CORPUS = [
    ("R-4.5.1-win.exe", 90_111_968, Category.EXECUTABLE, 7.78, 0.8231, 1.0000),
    ("Windows-KB890830-x64-V5.129.exe", 76_629_432, Category.EXECUTABLE, 7.93, 0.9594, 1.0000),
    ("lghub_installer.exe", 58_146_712, Category.EXECUTABLE, 6.51, 0.4411, 0.7772),
    ("DB.Browser.msi", 19_783_680, Category.BINARY, 7.99, 0.9690, 1.0000),
    ("Winxvideo.rar", 212_734_622, Category.COMPRESSED_ARCHIVE, 8.00, 1.0000, 1.0000),
    ("Wondershare.zip", 263_670_338, Category.COMPRESSED_ARCHIVE, 8.00, 1.0000, 1.0000),
]
REAL_TOTAL = 721_076_752


def _info(name, size, category=Category.BINARY, entropy=4.0,
          mean=0.5, mx=None, zlib_stream=False) -> FileInfo:
    return FileInfo(path=Path(name), size=size, category=category,
                    entropy_bps=entropy, zlib_stream=zlib_stream,
                    sample_ratio=mean, sample_ratio_max=mean if mx is None else mx)


def _real_infos() -> list[FileInfo]:
    return [_info(n, s, c, e, mean, mx) for n, s, c, e, mean, mx in REAL_CORPUS]


def _plan_for(infos, profile, tools=ALL_TOOLS):
    return make_plan(infos, profile, tools)


# ---------------------------------------------------------------------------
# The exactness guarantee
# ---------------------------------------------------------------------------

def test_stored_bytes_are_exact_not_estimated():
    """Media is copied verbatim, so a store-only plan has no uncertainty in
    its payload at all - low, expected and high must agree apart from the
    container overhead, and every byte must be accounted for."""
    infos = [_info(f"clip{i}.mp4", 10_000_000, Category.VIDEO, 7.99, mean=0.99)
             for i in range(5)]
    est = estimate_size(infos, _plan_for(infos, Profile.NORMAL))

    assert est.piped_bytes == 0
    assert est.stored_bytes == 50_000_000
    assert est.low == est.expected == est.high
    assert est.expected == est.stored_bytes + est.overhead_bytes


@pytest.mark.parametrize("profile", list(Profile))
def test_store_route_contributes_its_exact_size_under_every_profile(profile):
    """Property: whatever the profile does with the rest, the stored portion of
    the estimate is always exactly the sum of those files' sizes."""
    infos = _real_infos()
    the_plan = _plan_for(infos, profile)
    est = estimate_size(infos, the_plan)

    stored = {f for r in the_plan.routes if r.action == "store" for f in r.files}
    assert est.stored_bytes == sum(i.size for i in infos if i.path in stored)
    assert est.stored_bytes + est.piped_bytes == REAL_TOTAL


# ---------------------------------------------------------------------------
# Ranges, never false precision
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", list(Profile))
def test_size_range_is_ordered_and_never_predicts_inflation(profile):
    infos = _real_infos()
    est = estimate_size(infos, _plan_for(infos, profile))
    assert est.low <= est.expected <= est.high
    # The chain can never make the payload bigger than storing it verbatim.
    assert est.high <= est.stored_bytes + est.piped_bytes + est.overhead_bytes


@pytest.mark.parametrize("profile", list(Profile))
def test_time_range_is_ordered_and_positive(profile):
    infos = _real_infos()
    est = estimate_time(infos, _plan_for(infos, profile))
    assert 0 < est.low <= est.expected <= est.high


def test_a_uniform_file_gets_no_sampling_penalty():
    """When head, middle and tail agree, the samples are representative and the
    estimate is just ratio x codec factor - no correction, no widened range."""
    infos = [_info("uniform.bin", 100_000_000, entropy=3.0, mean=0.30, mx=0.30)]
    est = estimate_size(infos, _plan_for(infos, Profile.NORMAL))
    want = 100_000_000 * 0.30 * DEFAULT_RATES.factor_for(SEVENZIP)
    assert est.low == est.expected
    assert est.expected == pytest.approx(want + est.overhead_bytes, rel=0.01)


def test_a_precomp_chain_reaches_much_lower_on_the_optimistic_end():
    """Found by measurement, not by reasoning: on a real installer whose probe
    said 0.96 (near-incompressible), Precomp opened the deflate streams inside
    and the archive came out 41% smaller. The probe cannot see that, so the low
    bound has to leave room for it - a range that excludes the truth is worse
    than no range at all."""
    installer = _info("driver.exe", 136_899_248, Category.EXECUTABLE, 7.52,
                      mean=0.7471, mx=0.9648)
    normal = estimate_size([installer], _plan_for([installer], Profile.NORMAL))
    extreme = estimate_size([installer], _plan_for([installer], Profile.EXTREME))

    assert extreme.low < normal.low
    assert extreme.low <= 136_899_248 * 0.35
    # The measured outcome has to fall inside the Extreme range.
    assert extreme.low <= 95_678_980 <= extreme.high


def test_only_precomp_chains_are_flagged_as_upper_bounds():
    infos = _real_infos()
    assert not estimate_size(infos, _plan_for(infos, Profile.NORMAL)).upper_bound
    assert not estimate_size(infos, _plan_for(infos, Profile.FAST)).upper_bound
    assert estimate_size(infos, _plan_for(infos, Profile.EXTREME)).upper_bound
    # Nothing piped means nothing for Precomp to surprise us with.
    media = [_info("clip.mp4", 10_000_000, Category.VIDEO, 7.99, mean=0.99)]
    assert not estimate_size(media, _plan_for(media, Profile.EXTREME)).upper_bound


def test_the_precomp_time_range_spans_both_of_its_regimes():
    """Measured on the precomp->7z chain: 2.642 MB/s when Precomp finds nothing
    to expand, 0.891 MB/s when it does. One rate cannot serve both, so the
    window the spread opens around the shipped rate has to hold them."""
    chain = ["precomp", "sevenzip"]
    rate = DEFAULT_RATES.rate_for(chain)
    spread = DEFAULT_RATES.spread_for(chain)
    assert rate / spread <= 0.891e6, "the working regime falls out of the range"
    assert rate * spread >= 2.642e6, "the no-op regime falls out of the range"


def test_the_least_compressible_sample_drives_the_estimate():
    """A compressible stub in front of an incompressible payload is the shape of
    every installer. Averaging the samples predicts a win that never arrives, so
    the expected value follows the *worst* sample and the mean becomes the
    optimistic bound."""
    stub = _info("installer.exe", 100_000_000, Category.EXECUTABLE, 6.5,
                 mean=0.44, mx=0.78)
    est = estimate_size([stub], _plan_for([stub], Profile.NORMAL))

    factor = DEFAULT_RATES.factor_for(SEVENZIP)
    assert est.expected == pytest.approx(100_000_000 * 0.78 * factor
                                         + est.overhead_bytes, rel=0.01)
    assert est.low == pytest.approx(100_000_000 * 0.44 * factor
                                    + est.overhead_bytes, rel=0.01)
    assert est.low < est.expected


# ---------------------------------------------------------------------------
# The two-rate time model
# ---------------------------------------------------------------------------

def test_stored_bytes_are_io_bound_and_piped_bytes_are_codec_bound():
    """A single MB/s figure would mispredict on any mix but the one it was
    measured on. Stored bytes cost a disk copy; piped bytes cost the codec.
    And since D9, EVERY byte costs a third thing: the pre-publish self-test
    restores the whole archive, so the wait the user is being promised must
    include it or the estimate is systematically low."""
    stored_only = [_info("clip.mp4", 400_000_000, Category.VIDEO, 7.99, mean=0.99)]
    piped_only = [_info("data.bin", 400_000_000, entropy=3.0, mean=0.4)]

    io_time = estimate_time(stored_only, _plan_for(stored_only, Profile.NORMAL))
    codec_time = estimate_time(piped_only, _plan_for(piped_only, Profile.NORMAL))

    # Both jobs pay the D9 self-test, each at its own chain's restore speed:
    # a store-only archive verifies as a copy + hash (io-bound), a 7-Zip one
    # replays LZMA2 decode.
    io_expected = (400_000_000 / DEFAULT_RATES.io_rate          # copy in
                   + 400_000_000 / DEFAULT_RATES.io_rate)       # verify back
    codec_expected = (400_000_000 / DEFAULT_RATES.rate_for(SEVENZIP)
                      + 400_000_000 / DEFAULT_RATES.verify_rate_for(SEVENZIP))
    assert io_time.expected == pytest.approx(io_expected, rel=0.01)
    assert codec_time.expected == pytest.approx(codec_expected, rel=0.01)
    assert codec_time.expected > io_time.expected * 5


def test_extreme_costs_more_time_than_normal_on_the_real_corpus():
    """Not because its codec is slower - measured, both run about 2.6 MB/s - but
    because Precomp's override routes 2.9x more bytes into the chain."""
    infos = _real_infos()
    normal = estimate_time(infos, _plan_for(infos, Profile.NORMAL))
    extreme = estimate_time(infos, _plan_for(infos, Profile.EXTREME))
    assert extreme.expected > normal.expected * 2


def test_rates_are_injectable_for_self_calibration():
    """J7 will replace the shipped prior with rates measured on this machine.
    The estimator must take them as an argument, not read a global."""
    infos = [_info("data.bin", 100_000_000, entropy=3.0, mean=0.4)]
    the_plan = _plan_for(infos, Profile.NORMAL)
    key = Rates.chain_key(SEVENZIP)
    rate = DEFAULT_RATES.codec[key]
    slow = Rates(codec={**DEFAULT_RATES.codec, key: rate / 4})

    # Quartering the codec rate must add exactly the extra codec seconds; the
    # io and verify terms are untouched by it.
    delta = (estimate_time(infos, the_plan, slow).expected
             - estimate_time(infos, the_plan).expected)
    assert delta == pytest.approx(3 * 100_000_000 / rate, rel=0.01)


# ---------------------------------------------------------------------------
# compare_profiles and the "not worth it" flag
# ---------------------------------------------------------------------------

def test_compare_covers_every_profile_and_reports_its_plan_warnings():
    infos = _real_infos()
    rows = compare_profiles(infos, ALL_TOOLS)
    assert [r.profile for r in rows] == list(Profile)
    insane = next(r for r in rows if r.profile is Profile.INSANE)
    assert any("zpaqfranz" in w for w in insane.warnings)


def test_not_worth_it_fires_on_the_corpus_that_motivated_the_phase():
    """The measured fact behind Phase J: on this corpus Extreme cost 2.7x the
    time of Normal for 0.17 extra percentage points. The table has to say so
    before the user pays for it."""
    infos = _real_infos()
    rows = {r.profile: r for r in compare_profiles(infos, ALL_TOOLS)}
    extreme = rows[Profile.EXTREME]

    assert extreme.not_worth_it
    assert extreme.beaten_by is Profile.NORMAL
    assert extreme.time_multiple >= 2.0
    assert extreme.extra_points < 1.0


def test_not_worth_it_stays_quiet_when_the_extra_time_buys_something():
    """Deflate-wrapped data is what the full chain exists for: Precomp opens
    streams Normal has to shelve, so the extra hours are earned."""
    infos = [_info(f"pak{i}.pak", 200_000_000, Category.BINARY, 7.99,
                   mean=1.0, mx=1.0, zlib_stream=True) for i in range(3)]
    rows = {r.profile: r for r in compare_profiles(infos, ALL_TOOLS)}
    assert not rows[Profile.EXTREME].not_worth_it


def test_the_flag_always_points_at_a_genuinely_cheaper_profile():
    """'Not worth it' means a *faster* profile gets you nearly the same archive.
    So the fastest row can never carry the flag, and every flag must name a row
    that really is quicker."""
    infos = _real_infos()
    rows = compare_profiles(infos, ALL_TOOLS)
    fastest = min(rows, key=lambda r: r.time.expected)
    assert not fastest.not_worth_it

    for row in rows:
        if row.beaten_by is None:
            continue
        beaten = next(r for r in rows if r.profile is row.beaten_by)
        assert beaten.time.expected < row.time.expected
        assert row.time_multiple == pytest.approx(
            row.time.expected / beaten.time.expected, rel=0.01)


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------

def test_no_files_estimates_nothing_without_dividing_by_zero():
    the_plan = make_plan([], Profile.NORMAL, ALL_TOOLS)
    size = estimate_size([], the_plan)
    time = estimate_time([], the_plan)
    assert size.expected == size.low == size.high == 0
    assert size.saved_fraction == 0.0
    assert time.expected == 0.0
    assert compare_profiles([], ALL_TOOLS) == []


def test_zero_byte_files_do_not_break_the_ratio():
    infos = [_info("empty.txt", 0, Category.TEXT, 0.0, mean=1.0)]
    est = estimate_size(infos, _plan_for(infos, Profile.NORMAL))
    assert est.saved_fraction == 0.0


def test_a_degraded_chain_is_estimated_as_what_it_will_actually_run():
    """With no tools installed every profile falls back to zstd, so every row
    must predict the same size. Anything else would let Extreme keep promising
    a ratio the missing Precomp was going to deliver."""
    infos = _real_infos()
    rows = compare_profiles(infos, NO_TOOLS)
    assert len({r.size.expected for r in rows}) == 1
    assert len({r.time.expected for r in rows}) == 1
