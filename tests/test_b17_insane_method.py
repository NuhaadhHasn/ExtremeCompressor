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
import re
from pathlib import Path

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
    # 645 MB of distinct installers, tarred: three 256 MiB blocks, two busy
    (58, 2, 644_802_560, 4916),
    # slices of the installer .pcf: one block far below 256 MiB
    (58, 2, 1 << 20, 99.4),
    (58, 2, 4 << 20, 144.8),
    (58, 2, 16 << 20, 313.5),
    # out of sample for the line above: the whole installer .pcf, one block
    (58, 2, 62_482_862, 895),
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


def test_a_small_job_is_not_quoted_a_full_block():
    """Found by rendering the GUI, not by a test: the Insane row quoted
    **2.7 GB** of RAM for the qa_sweep's 371.5 KB job, because the model
    charged every job a full 256 MiB block. zpaq sizes its model to the
    block's real size - 1 MiB peaked at 99.4 MiB - which is the same lesson
    `effective_dict` taught the LZMA2 figure (a 371 KB job once shown 6 GB).
    Even with Precomp's 5x worst-case inflation it is a small number."""
    assert ram.zpaqfranz_compress_ram(58, 2, 371_500 * 5) < 200 * MIB


def test_m58s_second_thread_costs_less_than_its_first():
    """Measured: 2,761 MiB on one busy thread, 4,916 MiB on two. About 606 MiB
    of -m58's footprint is shared rather than per thread, so doubling the
    one-thread figure would over-read by 12%."""
    one = ram.zpaqfranz_compress_ram(58, 1, 1 << 30)
    two = ram.zpaqfranz_compress_ram(58, 2, 1 << 30)
    assert one < two < 2 * one


def test_m58_fits_the_ram_budget_at_the_default_thread_count():
    """The reason the probe stopped at 256 MiB blocks: two busy -m58 threads
    must fit the budget `max_safe_dict` already holds the machine to (55% of
    RAM), on the 16 GB target."""
    target = 16 * (1 << 30)
    assert ram.zpaqfranz_compress_ram(58, 2, 1 << 40) <= target * ram._RAM_BUDGET


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
        ram.ZPAQFRANZ_METHOD, ram.zpaqfranz_threads(0, ram.ZPAQFRANZ_METHOD),
        SILESIA))


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


# ---------------------------------------------------------------------------
# The estimator: Insane's rates were never measured, and its slope was -m4's
# ---------------------------------------------------------------------------
#
# Before B17, `_CODEC_RATE` and `_VERIFY_RATE` had no `precomp+zpaqfranz` key,
# so Insane's time came from `_FALLBACK_RATE` (2.5 MB/s) and
# `_FALLBACK_VERIFY_RATE` (15 MB/s). The Silesia job below measured 0.094 and
# 0.136 MB/s. For that job, the fallback predicted under two minutes against
# the 63.5 it took.

INSANE = ["precomp", "zpaqfranz"]
SILESIA_ORIG = 211_938_580
#: engine.compress, Profile.INSANE at -m58, 2026-09-27, 12/12 files verified.
SILESIA_M58 = 37_542_028
#: Wall time of that compress, which includes D9's full restore and hash.
SILESIA_M58_SECONDS = 3810.1
#: Bytes-weighted `sample_ratio_max` over Silesia: B8's anchor probe,
#: re-measured on this machine by the same run.
SILESIA_PROBE_MAX = 0.4047


def _silesia_like():
    from pathlib import Path
    from excmp.analyzer import Category, FileInfo
    return [FileInfo(path=Path("silesia.bin"), size=SILESIA_ORIG,
                     category=Category.BINARY, entropy_bps=5.0,
                     sample_ratio=0.3293, sample_ratio_max=SILESIA_PROBE_MAX)]


def _all_tools():
    from excmp.tools import ToolInfo
    return {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
            for n in ("7z", "precomp", "zpaqfranz")}


def test_insane_has_its_own_measured_rates():
    from excmp.estimate import (DEFAULT_RATES, _FALLBACK_RATE,
                                _FALLBACK_VERIFY_RATE)
    assert DEFAULT_RATES.rate_for(INSANE) != _FALLBACK_RATE
    assert DEFAULT_RATES.verify_rate_for(INSANE) != _FALLBACK_VERIFY_RATE


def test_the_silesia_m58_anchor_reproduces_through_the_slope():
    """The slope is fitted the way B8 fitted every other chain: through the
    Silesia anchor and the physical (1.0, 1.0) point."""
    from excmp.estimate import DEFAULT_RATES, codec_factor
    slope = DEFAULT_RATES.factor_for(INSANE)
    predicted = SILESIA_PROBE_MAX * codec_factor(slope, SILESIA_PROBE_MAX)
    measured = SILESIA_M58 / SILESIA_ORIG
    assert abs(predicted - measured) < 0.002, (predicted, measured)


def test_insanes_time_range_contains_the_measured_silesia_job():
    from excmp.estimate import estimate_time
    from excmp.planner import plan as make_plan
    infos = _silesia_like()
    the_plan = make_plan(infos, Profile.INSANE, _all_tools())
    assert the_plan.routes[0].stages == INSANE
    t = estimate_time(infos, the_plan)
    assert t.low <= SILESIA_M58_SECONDS <= t.high, (t, SILESIA_M58_SECONDS)
    # ...and not by being uselessly wide: the old fallback put the *expected*
    # figure at under 2% of the measured wait.
    assert t.expected >= SILESIA_M58_SECONDS / 3


#: The 13-file installer sample I6's `pick_sample` chose from the Programs
#: corpus, copied to C:\excmp-bench\b12\programs for B12 and reused here.
INSTALLER_SAMPLE = r"C:\excmp-bench\b12\programs"
INSTALLER_SAMPLE_BYTES = 55_733_142
#: engine.compress, Profile.INSANE at -m58, 2026-09-27, 13/13 verified.
INSTALLER_SAMPLE_M58 = 45_951_032


def _installer_sample_present() -> bool:
    import os
    from pathlib import Path
    root = Path(INSTALLER_SAMPLE)
    if not root.is_dir():
        return False
    files = [p for p in root.iterdir() if p.is_file()]
    return len(files) == 13 and sum(p.stat().st_size for p in files) == INSTALLER_SAMPLE_BYTES


@pytest.mark.skipif(not _installer_sample_present(),
                    reason="B12's installer sample is not on this machine at its recorded size")
def test_the_installer_run_lands_inside_insanes_size_range():
    """The second corpus, as a check rather than a fit: the slope came from
    Silesia alone, and the installer archive has to land inside the range it
    produces anyway. Measured 2026-09-27: expected 46,324,391, low 31,603,834,
    high 49,623,215, archive 45,951,032."""
    from pathlib import Path
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    from excmp.planner import plan as make_plan
    from excmp.tools import find_tools
    tools = find_tools()
    if tools.get("zpaqfranz") is None or tools.get("precomp") is None:
        pytest.skip("Insane's chain is not installed here")
    infos = analyze_tree(Path(INSTALLER_SAMPLE))
    est = estimate_size(infos, make_plan(infos, Profile.INSANE, tools))
    assert est.low <= INSTALLER_SAMPLE_M58 <= est.high, est



# ---------------------------------------------------------------------------
# From the adversarial review of the B17 diff
# ---------------------------------------------------------------------------

GIB16 = 16 * (1 << 30)


def test_threads_are_capped_to_what_fits_the_budget():
    """-m58 was justified as fitting the budget *at two threads*, but nothing
    enforced that: a user setting 8 worker threads would have run -t8, and a
    many-core machine's zpaqfranz default does the same on its own. At about
    2.1 GiB per busy thread, 8 threads is ~17 GB on a 16 GB machine."""
    cap = ram.zpaqfranz_threads(64, 58, GIB16)
    assert 1 <= cap < 8
    assert ram.zpaqfranz_compress_ram(58, cap, 1 << 40) <= GIB16 * ram._RAM_BUDGET
    assert ram.zpaqfranz_compress_ram(58, cap + 1, 1 << 40) > GIB16 * ram._RAM_BUDGET


def test_zero_threads_means_physical_cores_within_the_cap():
    assert ram.zpaqfranz_threads(0, 58, GIB16) == min(
        ram.physical_cores(), ram.zpaqfranz_threads(64, 58, GIB16))


def test_an_explicit_small_thread_count_is_honoured():
    assert ram.zpaqfranz_threads(1, 58, GIB16) == 1


def test_the_stage_always_passes_the_capped_thread_count(tmp_path, monkeypatch):
    """The stage resolves threads before building the command, so zpaqfranz
    never falls back to its own uncapped default."""
    import excmp.stages.zpaqfranz as zmod
    from excmp.stages.base import StageContext
    seen = {}

    def fake_run(cmd, ctx, stage_id, parse_line=None, cwd=None):
        seen["cmd"] = cmd
        Path(cmd[2]).write_bytes(b"x")

    monkeypatch.setattr(zmod, "run_tool", fake_run)
    monkeypatch.setattr(zmod.ZpaqfranzStage, "_exe", lambda self: "C:/z.exe")
    monkeypatch.setattr(zmod.ram, "total_ram_bytes", lambda default=0: GIB16)
    src = tmp_path / "in.tar"
    src.write_bytes(b"data")
    for asked in (0, 8):
        ctx = StageContext(temp_dir=tmp_path / "tmp", threads=asked)
        zmod.ZpaqfranzStage().compress(src, tmp_path / "o.zpaq", ctx)
        flags = [a for a in seen["cmd"] if re.fullmatch(r"-t\d+", a)]
        assert flags == [f"-t{ram.zpaqfranz_threads(asked, 58, GIB16)}"], seen["cmd"]


def test_low_memory_extract_reaches_zpaqfranz():
    """G7's `--low-memory` sets extract_threads=1. zpaqfranz never received
    it, and at -m58 each restoring thread holds ~2.7 GiB."""
    from pathlib import Path as _P
    from excmp.stages.zpaqfranz import ZpaqfranzStage
    cmd = ZpaqfranzStage().build_extract_cmd(_P("a.zpaq"), _P("out"), "C:/z.exe", threads=1)
    assert "-t1" in cmd
    assert not [a for a in ZpaqfranzStage().build_extract_cmd(
        _P("a.zpaq"), _P("out"), "C:/z.exe") if re.fullmatch(r"-t\d+", a)]


def test_a_failed_restore_does_not_leave_its_scratch_folder(tmp_path, monkeypatch):
    import excmp.stages.zpaqfranz as zmod
    from excmp.stages.base import StageContext, StageError

    def boom(cmd, ctx, stage_id, parse_line=None, cwd=None):
        (Path(cmd[cmd.index("-to") + 1]) / "partial.bin").write_bytes(b"half")
        raise StageError("zpaqfranz: exited with code 2")

    monkeypatch.setattr(zmod, "run_tool", boom)
    monkeypatch.setattr(zmod.ZpaqfranzStage, "_exe", lambda self: "C:/z.exe")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    with pytest.raises(StageError):
        zmod.ZpaqfranzStage().extract(tmp_path / "a.zpaq", tmp_path / "out", ctx)
    assert not list((tmp_path / "tmp").glob("zx-*")), "scratch left behind"


def test_a_pre_b17_calibration_entry_does_not_override_the_measured_rate(tmp_path):
    """J7 keys learned rates by chain. An Insane rate learned at -m4 would
    replace the measured -m58 rate outright, and it is several times too
    fast. Entries are now stamped with the zpaq method; unstamped ones are
    pre-B17 and are dropped."""
    import json
    from excmp import calibrate
    from excmp.estimate import DEFAULT_RATES
    store = tmp_path / "cal.json"
    store.write_text(json.dumps({"chains": {
        "precomp+zpaqfranz": {"rate": 400000.0, "samples": 3}}}), encoding="utf-8")
    rates = calibrate.blended_rates(path=store)
    assert rates.rate_for(INSANE) == DEFAULT_RATES.rate_for(INSANE)


def test_a_new_insane_sample_is_stamped_and_kept(tmp_path):
    from excmp import calibrate
    store = tmp_path / "cal.json"
    calibrate.record(INSANE, 64 << 20, (64 << 20) / 0.1e6, path=store)
    cal = calibrate.load(store)
    assert "precomp+zpaqfranz" in cal.chains
    assert cal.chains["precomp+zpaqfranz"].zpaq_method == ram.ZPAQFRANZ_METHOD


def test_the_ram_cell_counts_only_piped_bytes():
    """Stored files never reach zpaqfranz, so they cannot add blocks."""
    from gui.suggest import _ram_words
    small_piped = _ram_words(Profile.INSANE, None, 10 << 30,
                             stages=INSANE, inflation=5, piped_bytes=1 << 20)
    assert small_piped == _ram_words(Profile.INSANE, None, 1 << 20,
                                     stages=INSANE, inflation=5)



# ---------------------------------------------------------------------------
# Second round of review findings
# ---------------------------------------------------------------------------

def _stored_video_plus_text():
    from excmp.analyzer import Category, FileInfo
    return [
        FileInfo(path=Path("v.mp4"), size=2_000_000_000, category=Category.VIDEO,
                 entropy_bps=7.99, sample_ratio=0.99, sample_ratio_max=0.99),
        FileInfo(path=Path("notes.txt"), size=20_000_000, category=Category.TEXT,
                 entropy_bps=4.0, sample_ratio=0.3, sample_ratio_max=0.35),
    ]


def test_stored_bytes_restore_at_disk_speed_not_at_the_chains_rate():
    """D9 restores stored files with a zip copy, not through the chain. With
    Insane's measured 0.1 MB/s verify rate applied to them, a 2 GB stored
    video beside 20 MB of text was estimated at over four hours."""
    from excmp.estimate import estimate_time
    from excmp.planner import plan as make_plan
    infos = _stored_video_plus_text()
    t = estimate_time(infos, make_plan(infos, Profile.INSANE, _all_tools()))
    assert t.expected < 30 * 60, t


def test_a_stored_file_does_not_lower_the_quoted_ram():
    """Precomp's inflation was averaged over every file, stored ones
    included, then applied to the piped bytes only - so adding a stored
    video made zpaqfranz's quoted peak smaller."""
    from excmp.analyzer import Category, FileInfo
    from gui.suggest import profile_comparison, summarize
    from excmp.planner import plan as make_plan
    png = FileInfo(path=Path("shot.png"), size=10_000_000, category=Category.IMAGE,
                   entropy_bps=7.95, sample_ratio=0.99, sample_ratio_max=0.99)
    alone = [png]
    with_video = [png, _stored_video_plus_text()[0]]

    def insane_ram(infos):
        rows = profile_comparison(infos, _all_tools(), summarize(infos, make_plan(infos, Profile.INSANE, _all_tools())))
        return next(r for r in rows if r.profile is Profile.INSANE).ram_text

    assert insane_ram(alone) == insane_ram(with_video)


@pytest.fixture
def target_machine(monkeypatch):
    """The target's cores and RAM, pinned. The thread cap scales with the
    host's memory, so on a smaller CI runner (first seen 2026-10-01) zpaqfranz
    is held to one thread and figures these tests compare collapse into one.
    That is the cap working; the tests are about the target machine."""
    monkeypatch.setattr(ram, "physical_cores", lambda: 2)
    monkeypatch.setattr(ram, "total_ram_bytes", lambda default=0: 16 << 30)


def test_the_ram_cell_follows_the_thread_setting(target_machine):
    """The stage runs `zpaqfranz_threads(setting)`; the cell must quote the
    same count, or a user who asked for 3 threads is shown a 2-thread peak."""
    from gui.suggest import profile_comparison, summarize
    from excmp.planner import plan as make_plan
    infos = _silesia_like() * 1
    rows = profile_comparison(infos, _all_tools(), summarize(infos, make_plan(infos, Profile.INSANE, _all_tools())), zpaq_threads=1)
    one = next(r for r in rows if r.profile is Profile.INSANE).ram_text
    rows = profile_comparison(infos, _all_tools(), summarize(infos, make_plan(infos, Profile.INSANE, _all_tools())), zpaq_threads=3)
    three = next(r for r in rows if r.profile is Profile.INSANE).ram_text
    assert one != three


def test_insanes_ram_is_a_range_when_precomp_might_expand_nothing(target_machine):
    """On Silesia Precomp found nothing and zpaqfranz got one block (2.7 GB);
    the worst case is Precomp inflating ~5x into two busy blocks (4.8 GB).
    Showing only 4.8 GB overstated the anchor corpus by 78%, so the cell's
    second line carries both ends."""
    from gui.suggest import fmt_size, profile_comparison, summarize
    from excmp.planner import plan as make_plan
    infos = _silesia_like()
    rows = profile_comparison(infos, _all_tools(), summarize(infos, make_plan(infos, Profile.INSANE, _all_tools())))
    row = next(r for r in rows if r.profile is Profile.INSANE)
    t = ram.zpaqfranz_threads(0, ram.ZPAQFRANZ_METHOD)
    lo = fmt_size(ram.zpaqfranz_compress_ram(ram.ZPAQFRANZ_METHOD, t, SILESIA_ORIG))
    hi = fmt_size(ram.zpaqfranz_compress_ram(ram.ZPAQFRANZ_METHOD, t, SILESIA_ORIG * 5))
    assert lo != hi
    assert row.ram_text == hi
    assert lo in row.ram_range and hi in row.ram_range



def test_on_a_small_machine_the_cell_quotes_one_thread(monkeypatch):
    """The other half of the cap: with little RAM, -m58 runs one thread, and
    the cell must quote the one-thread figure rather than the target's."""
    from gui.suggest import fmt_size, profile_comparison, summarize
    from excmp.planner import plan as make_plan
    monkeypatch.setattr(ram, "physical_cores", lambda: 2)
    monkeypatch.setattr(ram, "total_ram_bytes", lambda default=0: 7 << 30)
    infos = _silesia_like()
    rows = profile_comparison(infos, _all_tools(),
                              summarize(infos, make_plan(infos, Profile.INSANE, _all_tools())))
    row = next(r for r in rows if r.profile is Profile.INSANE)
    assert row.ram_text == fmt_size(ram.zpaqfranz_compress_ram(58, 1, SILESIA_ORIG * 5))
