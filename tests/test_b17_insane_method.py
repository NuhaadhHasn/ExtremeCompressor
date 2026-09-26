"""B17 — Insane at zpaqfranz -m58, and the RAM figure that has to come with it.

The method change itself is pinned in `test_zpaqfranz.py`. This file pins
what the change exposed. The comparison table's peak-RAM cell for Insane has
always been computed with 7-Zip's LZMA2 formula, because `_ram_words` knew
only Fast and "everything else". For a Silesia-sized job (212 MB) at the
default thread count that printed **7,084 MiB**. On a comparable 237 MB input,
zpaqfranz actually peaked at **1,819 MiB at -m5** and **2,761 MiB at -m58**.
The number had nothing to do with the stage that runs, and it was shown
beside the profile the owner has just made the one for "smallest".

Every constant tested here is a measurement: bare zpaqfranz v64.8j,
`PeakWorkingSetSize` read from the exited process handle, on B12's two .pcf
intermediates (docs/benchmarks/2026-09-23-b12-lolz-vs-zpaqfranz.md).
"""

from __future__ import annotations

import os

import pytest

from excmp import ram
from excmp.planner import Profile

MIB = 1 << 20


# ---------------------------------------------------------------------------
# The model, pinned to what was measured
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, threads, input_bytes, measured_mib", [
    # installers .pcf: 62,482,862 B, one 64 MiB block
    (4, 2, 62_482_862, 441),
    (4, 1, 62_482_862, 442),
    (5, 2, 62_482_862, 895),
    # deflate .pcf: 236,958,376 B, four blocks
    (4, 2, 236_958_376, 915),
    (4, 1, 236_958_376, 421),
    (5, 2, 236_958_376, 1819),
    # block-size probe, same .pcf: 128 MiB blocks -> two; 256 MiB -> one
    (57, 2, 236_958_376, 2903),
    (58, 2, 236_958_376, 2761),
])
def test_the_model_lands_on_every_measured_peak(method, threads, input_bytes,
                                                measured_mib):
    """Within 10% of the measured peak, and never below it by more than 5%.

    A RAM figure that under-states is the dangerous direction - it is what a
    user sizes the rest of their machine against - so the tolerance is
    lopsided on purpose.
    """
    got = ram.zpaqfranz_compress_ram(method, threads, input_bytes) / MIB
    assert measured_mib * 0.95 <= got <= measured_mib * 1.10, (
        f"-m{method} -t{threads} on {input_bytes:,} B: model {got:.0f} MiB, "
        f"measured {measured_mib} MiB")


def test_threads_beyond_the_block_count_cost_nothing():
    """zpaqfranz compresses independent 64 MiB blocks, one per thread. A
    one-block input cannot use a second thread, and -t1/-t2 measured within
    1 MiB of each other on it (442 vs 441)."""
    one_block = 50 * MIB
    assert (ram.zpaqfranz_compress_ram(5, 8, one_block)
            == ram.zpaqfranz_compress_ram(5, 1, one_block))


def test_m5_costs_about_twice_m4():
    """Measured 2.0x on both corpora (895/441 and 1819/915)."""
    big = 1 << 30
    ratio = (ram.zpaqfranz_compress_ram(5, 2, big)
             / ram.zpaqfranz_compress_ram(4, 2, big))
    assert 1.8 <= ratio <= 2.2


def test_an_unmeasured_method_is_refused_rather_than_guessed():
    """-m1..-m3, and blocks bigger than 256 MiB, have never been measured here.
    Returning a neighbour's figure for them would be a number nobody took."""
    for method in (3, 56, 59):
        with pytest.raises(ValueError):
            ram.zpaqfranz_compress_ram(method, 2, 1 << 30)


def test_a_bigger_block_needs_a_bigger_input_to_use_a_second_thread():
    """-m58's 256 MiB blocks mean a 237 MB input is one block - which is why
    the probe measured it on one thread - while -m5 splits it four ways."""
    pcf = 236_958_376
    assert ram.zpaqfranz_compress_ram(58, 2, pcf) == ram.zpaqfranz_compress_ram(58, 1, pcf)
    assert ram.zpaqfranz_compress_ram(5, 2, pcf) == 2 * ram.zpaqfranz_compress_ram(5, 1, pcf)


def test_physical_cores_is_a_sane_count():
    """zpaqfranz's own default thread count on this laptop is 2 (`2T` with no
    switch, `4T` only with -ht) on 4 logical processors: it counts physical
    cores. The helper has to be answerable on any machine, CI included."""
    n = ram.physical_cores()
    assert 1 <= n <= (os.cpu_count() or n)


# ---------------------------------------------------------------------------
# The comparison table cell
# ---------------------------------------------------------------------------

SILESIA = 211_938_580


def test_insane_no_longer_quotes_the_lzma2_figure():
    """The defect this file exists for: LZMA2's 7,084 MiB printed for a
    zpaqfranz stage whose own model says something else entirely."""
    from gui.suggest import _ram_words
    from excmp.ram import effective_dict, lzma2_compress_ram, lzma2_default_dict
    from gui.suggest import fmt_size

    lzma2 = fmt_size(lzma2_compress_ram(
        effective_dict(lzma2_default_dict(9), SILESIA), os.cpu_count() or 2))
    text = _ram_words(Profile.INSANE, None, SILESIA,
                      stages=["precomp", "zpaqfranz"])
    assert text != lzma2
    assert text == fmt_size(ram.zpaqfranz_compress_ram(
        ram.ZPAQFRANZ_METHOD, ram.physical_cores(), SILESIA))


def test_insane_without_zpaqfranz_still_quotes_lzma2():
    """With zpaqfranz missing, Insane falls back to 7-Zip, and then the LZMA2
    figure is the right one. The fix must follow the chain, not the name."""
    from gui.suggest import _ram_words
    text_insane = _ram_words(Profile.INSANE, 2, SILESIA,
                             stages=["precomp", "sevenzip"])
    text_extreme = _ram_words(Profile.EXTREME, 2, SILESIA,
                              stages=["precomp", "sevenzip"])
    assert text_insane == text_extreme


def test_the_ram_module_and_the_stage_agree_on_the_method():
    """The cell quotes -m5 because the stage runs -m5. If one moves without the
    other, the table describes a job that is not the one that runs."""
    from excmp.stages.zpaqfranz import DEFAULT_METHOD
    assert ram.ZPAQFRANZ_METHOD == DEFAULT_METHOD
