"""Progress mapping and formatting - pure logic, no Qt widgets."""

import pytest

from gui.format import fmt_duration, fmt_eta, fmt_percent, fmt_size
from gui.progress import (PIPELINE_CEILING, TREE_CAPABLE, ChainProgress,
                          EtaEstimator, expected_chain)


def test_tree_capable_matches_the_engine():
    """If the engine ever learns a new tree-capable stage, this fails loudly
    instead of the GUI silently mispredicting every chain."""
    from excmp.engine import _TREE_CAPABLE

    assert TREE_CAPABLE == _TREE_CAPABLE


@pytest.mark.parametrize("stages, expected", [
    (["zstd"], ["zstd"]),                     # single tree-capable stage: no tar
    (["sevenzip"], ["sevenzip"]),
    (["precomp", "sevenzip"], ["tar", "precomp", "sevenzip"]),
    (["precomp", "srep", "sevenzip"], ["tar", "precomp", "srep", "sevenzip"]),
    ([], []),
])
def test_expected_chain(stages, expected):
    assert expected_chain(stages) == expected


def test_expected_chain_does_not_double_tar():
    assert expected_chain(["tar", "sevenzip"]) == ["tar", "sevenzip"]


def test_progress_is_monotonic_and_weighted():
    chain = ChainProgress(["tar", "precomp", "srep", "sevenzip"])
    seen = [chain.update("tar", 100.0)]
    for pct in (0, 25, 50, 75, 100):
        seen.append(chain.update("precomp", pct))
    for pct in (0, 50, 100):
        seen.append(chain.update("srep", pct))
    for pct in (0, 50, 100):
        seen.append(chain.update("sevenzip", pct))

    assert seen == sorted(seen), "progress went backwards"
    assert seen[0] == pytest.approx(5 / 100 * PIPELINE_CEILING)
    # Never claims completion while the container write is still to come.
    assert seen[-1] == pytest.approx(PIPELINE_CEILING)
    assert chain.finish() == 100.0


def test_out_of_order_reports_do_not_rewind():
    chain = ChainProgress(["tar", "precomp", "sevenzip"])
    chain.update("sevenzip", 50.0)
    high = chain.value
    assert chain.update("precomp", 10.0) == high


def test_skipped_stage_banks_its_weight():
    """A StageSkip means that stage never reports; jumping straight to the
    next one must count the skipped weight as done, not stall."""
    chain = ChainProgress(["tar", "precomp", "srep", "sevenzip"])
    chain.update("tar", 100.0)
    value = chain.update("sevenzip", 0.0)
    assert value == pytest.approx((5 + 35 + 20) / 100 * PIPELINE_CEILING)


def test_unexpected_stage_is_absorbed():
    chain = ChainProgress(["zstd"])
    chain.update("zstd", 50.0)
    assert chain.update("mystery", 100.0) >= chain.value
    assert "mystery" in chain.chain


def test_eta_stays_quiet_until_it_knows_something():
    eta = EtaEstimator(warmup_s=6.0, min_fraction=0.03)
    assert eta.update(0.01, 30.0) is None       # too little progress
    assert eta.update(0.5, 1.0) is None         # too little time
    assert eta.update(0.5, 20.0) == pytest.approx(20.0, rel=0.01)


def test_eta_smooths_a_lurch():
    eta = EtaEstimator(alpha=0.25, warmup_s=0.0, min_fraction=0.0)
    eta.update(0.5, 100.0)                      # steady state: 100s left
    smoothed = eta.update(0.9, 100.0)           # sudden speed-up
    assert 11.0 < smoothed < 100.0              # moved, but did not teleport


def test_eta_is_zero_when_complete():
    assert EtaEstimator(warmup_s=0.0, min_fraction=0.0).update(1.0, 10.0) == 0.0


@pytest.mark.parametrize("value, expected", [
    (0, "0 B"), (512, "512 B"), (1536, "1.5 KB"),
    (5 * 1024**2, "5.0 MB"), (3 * 1024**3, "3.0 GB"),
])
def test_fmt_size(value, expected):
    assert fmt_size(value) == expected


@pytest.mark.parametrize("value, expected", [
    (None, "estimating…"), (4, "a few seconds"), (42, "~50s"),
    (90, "~2 min"), (3600, "~1 h"), (5400, "~1 h 30 min"),
])
def test_fmt_eta(value, expected):
    assert fmt_eta(value) == expected


def test_fmt_helpers():
    assert fmt_percent(0.7243) == "72%"
    assert fmt_duration(8.53) == "8.5s"
    assert fmt_duration(184) == "3m 04s"
    assert fmt_duration(3720) == "1h 02m"
