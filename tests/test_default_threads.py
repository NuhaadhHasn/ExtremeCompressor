"""Default threads: one per physical core, measured, not "whatever the tool picks".

CLAUDE.md said "Default threads is 2, not 4"; the code said 0, which every
stage passed through as "tool's choice". For 7-Zip that meant every logical
processor - 4 on the 2-core i7-3540M target - and measured on 2026-10-01 with
the exact switches SevenZipStage builds (`-mx9 -mqs`), every archive restored
and SHA-256 compared:

    input                                switch      archive        peak RAM    time
    645 MB installers (3 LZMA2 blocks)   none        635,994,583 B  5,549 MiB   176 s
                                         -mmt4       635,994,583 B  5,738 MiB   183 s
                                         -mmt2       635,110,280 B  2,702 MiB   309 s
                                         -mmt1       635,108,251 B  2,695 MiB   629 s
    Silesia 212 MB (1 block)             none         48,680,741 B  2,089 MiB   143 s
                                         -mmt2        48,680,741 B  2,088 MiB   114 s
                                         -mmt4        48,680,741 B  2,089 MiB   173 s

On a multi-block input two threads is 0.14% smaller than the old default at
under half its peak RAM, and 1.75x slower. On a single block the bytes and
RAM are identical and two threads is the fastest. -mmt1 is 2,029 B smaller
still, in 645 MB, for twice the time again. So "auto" now gives 7-Zip one
thread per physical core, which is also what zpaqfranz does with no switch.
Fast's zstd runs in-process at its own default and is not affected.
Measured on the i5-7200U (2 cores / 4 threads), the target since
2026-10-01.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp import ram
from excmp.stages.base import StageContext


def _seven_cmd(tmp_path, monkeypatch, threads):
    import excmp.stages.sevenzip as smod
    seen = {}

    def fake_run(cmd, ctx, stage_id, parse_line=None, cwd=None):
        seen["cmd"] = cmd
        Path(cmd[-2]).write_bytes(b"7z")

    monkeypatch.setattr(smod, "run_tool", fake_run)
    monkeypatch.setattr(smod.SevenZipStage, "_exe", lambda self: "C:/7z.exe")
    src = tmp_path / "in.bin"
    src.write_bytes(b"data")
    ctx = StageContext(temp_dir=tmp_path / "tmp", threads=threads)
    smod.SevenZipStage().compress(src, tmp_path / "o.7z", ctx)
    return seen["cmd"]


def test_auto_threads_give_7zip_one_thread_per_physical_core(tmp_path, monkeypatch):
    cmd = _seven_cmd(tmp_path, monkeypatch, 0)
    assert f"-mmt{ram.physical_cores()}" in cmd, cmd


def test_an_explicit_thread_count_still_wins(tmp_path, monkeypatch):
    cmd = _seven_cmd(tmp_path, monkeypatch, 4)
    assert "-mmt4" in cmd
    assert f"-mmt{ram.physical_cores()}" not in cmd or ram.physical_cores() == 4


def test_the_lzma2_ram_cell_quotes_the_threads_that_will_run():
    """Normal's RAM cell computed LZMA2 at os.cpu_count() threads - the
    4-thread figure. With auto meaning physical cores it must quote the
    figure for those."""
    from excmp.planner import Profile
    from gui.format import fmt_size
    from gui.suggest import _ram_words
    big = 1 << 30
    want = fmt_size(ram.lzma2_compress_ram(
        ram.effective_dict(ram.lzma2_default_dict(9), big), ram.physical_cores()))
    assert _ram_words(Profile.NORMAL, None, big) == want


def test_the_ram_cell_follows_the_worker_threads_setting():
    """The job runs `advanced or settings` threads; the cell must quote that
    count too, not physical cores, when the user has set one."""
    from excmp.planner import Profile
    from gui.format import fmt_size
    from gui.suggest import _ram_words
    big = 1 << 30
    want = fmt_size(ram.lzma2_compress_ram(
        ram.effective_dict(ram.lzma2_default_dict(9), big), 4))
    assert _ram_words(Profile.NORMAL, None, big, threads=4) == want


def test_the_advanced_ram_note_falls_back_to_the_settings_threads(qtbot):
    """The job runs `advanced or settings` threads, so with Advanced on auto
    and Settings at 4, the note must quote 4 threads, not physical cores."""
    from gui.mainwindow import MainWindow
    from gui.format import fmt_size
    win = MainWindow()
    qtbot.addWidget(win)
    try:
        win.advanced_panel.threads.setValue(0)
        index = win.advanced_panel.dict_size.findData("64m")
        win.advanced_panel.dict_size.setCurrentIndex(index)
        # Changed AFTER the dictionary was picked, with no manual refresh: the
        # note has to follow both spinboxes by itself.
        win.settings_tab.threads.setValue(4)
        want = fmt_size(ram.lzma2_compress_ram(64 << 20, 4))
        assert want in win.advanced_panel.ram_note.text(), win.advanced_panel.ram_note.text()
        win.advanced_panel.threads.setValue(1)
        want = fmt_size(ram.lzma2_compress_ram(64 << 20, 1))
        assert want in win.advanced_panel.ram_note.text(), win.advanced_panel.ram_note.text()
    finally:
        win.queue.shutdown()


def test_the_recommendation_counts_physical_cores():
    """The big-job sentence used to say "on 4 cores" on a 2-core laptop."""
    from gui.suggest import recommend_profile
    from types import SimpleNamespace
    import excmp.ram as ram_mod
    summary = SimpleNamespace(floor_store_fraction=0.0, total_bytes=40 * 1024**3,
                              floor_pipeline_fraction=0.5, tools={"precomp": True})
    # Pinned rather than read from the host: 3 differs from os.cpu_count() on
    # the target and satisfies the big-job branch's `cores <= 4` everywhere.
    original = ram_mod.physical_cores
    ram_mod.physical_cores = lambda: 3
    try:
        _profile, reason = recommend_profile(summary)
    finally:
        ram_mod.physical_cores = original
    assert "on 3 cores" in reason, reason


def test_physical_cores_is_two_on_the_target_laptops():
    """Pinned only where it was measured: the i5-7200U (target since
    2026-10-01) and the i7-3540M before it, both 2 cores / 4 threads."""
    name = _cpu_name()
    if "7200U" not in name and "3540M" not in name:
        pytest.skip(f"not a measured target machine: {name!r}")
    assert ram.physical_cores() == 2


def _cpu_name() -> str:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(key, "ProcessorNameString")[0]
    except (OSError, ImportError):     # ImportError: winreg is Windows-only
        return ""



# ---------------------------------------------------------------------------
# Auto must not out-run the machine's memory
# ---------------------------------------------------------------------------
#
# Passing an explicit -mmt switches off 7-Zip's own rule (its manual: memory
# use is fitted "by changing the number of working threads, if the number of
# threads was not specified"). Harmless on the 2-core target; on a 6-core 8 GB
# machine a forced -mmt6 at the mx9 dictionary would want ~9 GB. So auto is
# capped at the app's RAM budget, and a user's own -mmt / -mmemuse is left in
# charge with no forced switch.

def test_auto_threads_are_capped_by_the_ram_budget(monkeypatch):
    monkeypatch.setattr(ram, "physical_cores", lambda: 6)
    monkeypatch.setattr(ram, "total_ram_bytes", lambda default=0: 8 << 30)
    n = ram.lzma2_auto_threads(256 << 20, 9)
    assert 1 <= n < 6
    assert ram.lzma2_compress_ram(256 << 20, n, 9) <= (8 << 30) * ram._RAM_BUDGET


def test_auto_threads_on_the_target_are_two():
    assert ram.lzma2_auto_threads(256 << 20, 9, total_ram=16 << 30, cores=2) == 2


def test_a_users_own_thread_or_memory_switch_is_left_in_charge(tmp_path, monkeypatch):
    import excmp.stages.sevenzip as smod
    seen = {}

    def fake_run(cmd, ctx, stage_id, parse_line=None, cwd=None):
        seen["cmd"] = cmd
        Path(cmd[-2]).write_bytes(b"7z")

    monkeypatch.setattr(smod, "run_tool", fake_run)
    monkeypatch.setattr(smod.SevenZipStage, "_exe", lambda self: "C:/7z.exe")
    src = tmp_path / "in.bin"
    src.write_bytes(b"data")
    for extra in (["-mmemuse=4g"], ["-mmt3"]):
        ctx = StageContext(temp_dir=tmp_path / "tmp", threads=0)
        smod.SevenZipStage(extra_args=extra).compress(src, tmp_path / "o.7z", ctx)
        forced = [a for a in seen["cmd"] if a.startswith("-mmt") and a not in extra]
        assert forced == [], seen["cmd"]
