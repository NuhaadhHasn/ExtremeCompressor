"""Level/dictionary knobs, the RAM column, and the Parameters line.

The last item of research/23 §5, and the only one that was never glue:
`_stage_factory()` hard-coded `SevenZipStage(level=9, dict_size=None)`, and
`StageRecord.params` was always `{}` — so an archive could not say what
settings produced it, and no setting could be chosen.

Three things get pinned here.

**The RAM figure is the exact 7-Zip formula, not a multiplier.** doc 19 §3
backs it out of `CompressDialog.cpp:2942-3017`: per block thread
`size1 = hs*4 + dict*4 + dict*4(level>=5) + 2MB (+6MB at 2 threads)` plus a
`(dict + 64K)*1.5` window, and multi-block adds `chunk = dict*4` capped at
256 MiB. The "≈13×dict" shorthand is a *consequence*, not the rule, and the
source study says in bold to use the formula.

**Nobody gets to pick a dictionary that will not fit.** B9's cap: on the
16 GB / 2-core target, never past `-md=512m`.

**The Parameters line is an allowlist, not a filter.** It hands user text to
a subprocess argument list. There is no shell, so this is not injection —
but `-p` would put a password in the log, and `-o`/`-w`/`@` would redirect
output somewhere the engine does not know about, which breaks the atomic
publish and the verified restore that depend on knowing where the file went.
"""

from __future__ import annotations

import pytest

from excmp import ram


MIB = 1 << 20
GIB = 1 << 30


# ---------------------------------------------------------------------------
# The RAM estimator
# ---------------------------------------------------------------------------

def test_the_7zip_default_dictionary_is_the_modern_one():
    """mx9 became 256 MiB in 24.09 (C/LzmaEnc.c:76-81). Docs that still say
    64 MB are two generations stale, and the RAM figure moves 4x with it."""
    assert ram.lzma2_default_dict(9) == 256 * MIB
    assert ram.lzma2_default_dict(5) < ram.lzma2_default_dict(9)


def test_decompress_ram_is_dict_plus_two_megs():
    """CompressDialog.cpp:3016, exactly."""
    assert ram.lzma2_decompress_ram(64 * MIB) == 64 * MIB + 2 * MIB


@pytest.mark.parametrize("dict_mib", [16, 64, 192, 256])
def test_compress_ram_lands_near_the_13x_shorthand(dict_mib):
    """The formula is authoritative; the shorthand is a sanity check on it.
    Multi-block at 2 threads should land in the 10-16x band per doc 19 §3."""
    need = ram.lzma2_compress_ram(dict_mib * MIB, threads=2)
    ratio = need / (dict_mib * MIB)
    assert 10 <= ratio <= 16, f"{ratio:.1f}x for a {dict_mib} MiB dictionary"


def test_more_threads_costs_more_memory():
    """-mmt=N at mx9 gives N/2 block threads, and each one pays size1 + chunk.
    This is the whole reason the column exists on a 16 GB machine."""
    one = ram.lzma2_compress_ram(128 * MIB, threads=2)
    four = ram.lzma2_compress_ram(128 * MIB, threads=8)
    assert four > one


def test_a_single_thread_is_the_solid_case_and_is_cheaper():
    solid = ram.lzma2_compress_ram(128 * MIB, threads=1)
    multi = ram.lzma2_compress_ram(128 * MIB, threads=4)
    assert solid < multi


# ---------------------------------------------------------------------------
# B9's cap
# ---------------------------------------------------------------------------

def test_the_target_machine_is_capped_at_512m():
    """16 GB, 2 cores. B9's rule, and the reason it exists: mx9 MT LZMA2 can
    exceed RAM at ~13x dict per block thread."""
    assert ram.max_safe_dict(16 * 1024 * MIB, threads=2) == 512 * MIB


def test_a_small_machine_gets_a_smaller_cap():
    small = ram.max_safe_dict(4 * 1024 * MIB, threads=2)
    assert small < 512 * MIB
    # And whatever it picks must actually fit the budget it was given.
    assert ram.lzma2_compress_ram(small, threads=2) < 4 * 1024 * MIB


def test_the_cap_is_a_real_power_of_two_7zip_accepts():
    for total in (4, 8, 16, 32, 64):
        chosen = ram.max_safe_dict(total * 1024 * MIB, threads=2)
        assert chosen & (chosen - 1) == 0, f"{chosen} is not a power of two"
        assert chosen >= 16 * MIB


def test_fmt_dict_speaks_7zip():
    assert ram.fmt_dict(256 * MIB) == "256m"
    assert ram.fmt_dict(1024 * MIB) == "1g"


# ---------------------------------------------------------------------------
# The Parameters line
# ---------------------------------------------------------------------------

def test_ordinary_method_switches_are_allowed():
    assert ram.parse_extra_args("-mqs -myx=9") == ["-mqs", "-myx=9"]
    assert ram.parse_extra_args("") == []
    assert ram.parse_extra_args("   ") == []


@pytest.mark.parametrize("bad", [
    "-p hunter2",            # a password would land in the job log
    "-pSecret",
    "-oC:/somewhere",        # redirects output away from the atomic publish
    "-w/tmp/elsewhere",      # moves the work dir the engine sized for
    "@listfile.txt",         # a listfile changes what is even in the archive
    "-sfx",                  # an SFX stub is unsigned - Phase H, not a flag
    "--",                    # ends switch parsing; everything after is a path
    "notaswitch",
    "-mx=9 && calc",         # no shell here, but the intent is disqualifying
])
def test_dangerous_switches_are_refused_by_name(bad):
    with pytest.raises(ValueError) as excinfo:
        ram.parse_extra_args(bad)
    # The refusal has to say which token and why, or nobody can fix it.
    assert bad.split()[0][:3] in str(excinfo.value) or "allow" in str(excinfo.value).lower()


def test_a_password_switch_is_never_echoed_in_the_error():
    """PeaZip's redaction rule (doc 17 §4): the refusal must not repeat the
    secret it just refused."""
    with pytest.raises(ValueError) as excinfo:
        ram.parse_extra_args("-phunter2")
    assert "hunter2" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# The plumbing: options in, and a manifest that says what ran
# ---------------------------------------------------------------------------

from pathlib import Path                                  # noqa: E402

from excmp import engine                                  # noqa: E402
from excmp.planner import Profile                         # noqa: E402
from excmp.stages.base import StageContext                # noqa: E402
from excmp.stages.sevenzip import SevenZipStage           # noqa: E402
from excmp.tools import find_tools                        # noqa: E402

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7z.exe not installed")


def test_the_stage_builds_the_switches_it_was_given():
    stage = SevenZipStage(level=7, dict_size="64m", extra_args=["-mqs"])
    cmd = stage.build_compress_cmd(Path("in"), Path("out.7z"), threads=2,
                                   exe="7z.exe")
    assert "-mx7" in cmd
    assert "-md=64m" in cmd
    assert "-mqs" in cmd
    # The output path is ours, always - the Parameters line cannot reach it.
    assert str(Path("out.7z")) in cmd


def test_defaults_are_unchanged_when_nothing_is_chosen():
    cmd = SevenZipStage().build_compress_cmd(Path("in"), Path("out.7z"),
                                             threads=0, exe="7z.exe")
    assert "-mx9" in cmd
    assert not any(a.startswith("-md=") for a in cmd)


@needs_7z
def test_the_manifest_records_what_actually_ran(tmp_path):
    """`StageRecord.params` was always {}. An archive that cannot say which
    settings produced it cannot be reproduced, and "copy as command" would be
    guessing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("compress me. " * 3000, encoding="utf-8")
    out = tmp_path / "a.excmp"
    engine.compress([src], out, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"),
                    options=engine.StageOptions(level=5, dict_size="16m"))

    listing = engine.list_archive(out)
    assert listing.stages == ["sevenzip"]

    import zipfile

    from excmp.manifest import _read_manifest
    with zipfile.ZipFile(out) as zf:
        manifest = _read_manifest(zf, out)
    params = {r.stage: r.params for r in manifest.stages}
    assert params["sevenzip"]["level"] == 5
    assert params["sevenzip"]["dict"] == "16m"


@needs_7z
def test_a_smaller_dictionary_really_reaches_7zip(tmp_path):
    """Not just recorded - actually used. A knob that is written down but not
    applied is worse than no knob."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("compress me. " * 20000, encoding="utf-8")
    seen: list[list[str]] = []
    real = SevenZipStage.build_compress_cmd

    def spy(self, source, dest, threads, exe):
        cmd = real(self, source, dest, threads, exe)
        seen.append(cmd)
        return cmd

    SevenZipStage.build_compress_cmd = spy
    try:
        engine.compress([src], tmp_path / "a.excmp", Profile.NORMAL,
                        StageContext(temp_dir=tmp_path / "t"),
                        options=engine.StageOptions(dict_size="8m"))
    finally:
        SevenZipStage.build_compress_cmd = real
    assert seen and any("-md=8m" in cmd for cmd in seen)


def test_the_cli_takes_the_knobs(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    from excmp.cli import main as cli_main
    assert cli_main(["compress", str(src), "-o", str(tmp_path / "a.excmp"),
                     "-p", "fast", "--temp", str(tmp_path / "t"),
                     "--level", "3"]) == 0


def test_the_cli_refuses_a_dangerous_parameters_line(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    from excmp.cli import main as cli_main
    # --params=-x, not --params -x: every value starts with a dash, which
    # argparse would otherwise read as another option. The help says so.
    assert cli_main(["compress", str(src), "-o", str(tmp_path / "a.excmp"),
                     "-p", "fast", "--temp", str(tmp_path / "t"),
                     "--params=-oC:/elsewhere"]) == 1
    assert "not allowed" in capsys.readouterr().err.lower()


def test_a_good_parameters_line_reaches_the_archive(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    from excmp.cli import main as cli_main
    assert cli_main(["compress", str(src), "-o", str(tmp_path / "a.excmp"),
                     "-p", "fast", "--temp", str(tmp_path / "t"),
                     "--params=-mqs"]) == 0


# ---------------------------------------------------------------------------
# The GUI half
# ---------------------------------------------------------------------------

pytest.importorskip("pytestqt")

from gui.mainwindow import MainWindow      # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_the_dictionary_menu_stops_where_the_machine_does(window):
    """B9: a choice the machine cannot honour is a trap, not an option."""
    from gui.widgets.preset_cards import _parse_dict

    box = window.advanced_panel.dict_size
    offered = [box.itemData(i) for i in range(box.count()) if box.itemData(i)]
    assert offered, "no dictionary sizes offered at all"
    biggest = _parse_dict(offered[-1])
    assert biggest <= 512 * MIB, f"offered {offered[-1]} on a capped machine"
    # And every one of them fits the budget the cap was computed against.
    budget = ram.total_ram_bytes()
    assert ram.lzma2_compress_ram(biggest, threads=2) < budget


def test_the_chooser_shows_peak_ram_for_the_lzma2_profiles(window, qtbot, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("compress me. " * 3000, encoding="utf-8")
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])

    rows = {r.profile.value: r for r in window.compare_table.rows()}
    assert rows, "no estimate rows"
    # Fast is zstd: its window is a tenth of LZMA2's and never the thing that
    # runs a 16 GB laptop out of memory, so it says nothing rather than a
    # number nobody needs.
    spoken = rows["normal"].accessibleName().lower()
    assert "memory" in spoken, spoken


def test_a_refused_parameters_line_stops_the_job_in_the_banner(window, qtbot,
                                                               tmp_path):
    """Not three minutes into a chain with 7-Zip's own error message."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    window.queue.pause()
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])

    window.advanced_panel.params.setText("-oC:/elsewhere")
    window.start_compression()

    assert window.queue.jobs == [], "a refused line still queued a job"
    assert window.banner.isVisibleTo(window)
    assert "not allowed" in window.banner.text().lower()


def test_the_chosen_knobs_ride_on_the_job(window, qtbot, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    window.queue.pause()
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])

    window.advanced_panel.level.setValue(4)
    window.advanced_panel.params.setText("-mqs")
    window.start_compression()

    options = window.queue.jobs[0].options
    assert options.level == 4
    assert options.extra_args == ("-mqs",)


# ---------------------------------------------------------------------------
# The clamp that keeps the RAM figure truthful
# ---------------------------------------------------------------------------

def test_the_dictionary_is_clamped_to_the_input_like_7zip_does():
    """LZMA2 never allocates a dictionary bigger than the data (`reduceSize`
    in LzmaEnc, and CompressDialog does the same before showing its estimate).
    Without this the column quoted 6.0 GB for a 371 KB job - a number that is
    both false and frightening, in the panel whose whole job is neither."""
    assert ram.effective_dict(256 * MIB, 371 * 1024) < 2 * MIB
    # Big input: the chosen dictionary stands.
    assert ram.effective_dict(256 * MIB, 4 * GIB) == 256 * MIB
    # And it only ever rounds UP to a real power of two, never past the ask.
    got = ram.effective_dict(256 * MIB, 100 * MIB)
    assert got & (got - 1) == 0 and got <= 256 * MIB


def test_a_tiny_job_reports_a_tiny_footprint():
    big = ram.lzma2_compress_ram(ram.effective_dict(256 * MIB, 8 * GIB), threads=4)
    small = ram.lzma2_compress_ram(ram.effective_dict(256 * MIB, 300 * 1024),
                                   threads=4)
    assert small < big / 100, f"{small} vs {big}"


def test_the_chooser_ram_scales_with_the_input(window, qtbot, tmp_path):
    """The number on screen has to be about *this* job."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("small. " * 200, encoding="utf-8")
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])
    rows = {r.profile.value: r for r in window.compare_table.rows()}
    text = rows["normal"].accessibleName().lower()
    assert "gb of memory" not in text, text
