"""B10: the two codecs that need no executable, and stop claiming they do.

B10 said two things: use the `lepton-jpeg-python` **wheel** rather than an exe
(Microsoft ships none), and "drop zstd.exe from any tool manifest — the
`zstandard` wheel already embeds libzstd in-process".

Checked on 2026-09-09, the first half was done and the second was **not**:

- `excmp/jpeg.py` imports `lepton_jpeg_python` and calls `compress_bytes` /
  `decompress_bytes` in-process, with a bit-exactness self-check. Lepton is
  named nowhere in the tool table. Correct, and worth pinning so nobody
  helpfully adds a `lepton.exe` row.
- `excmp/stages/zstdstage.py` imports `zstandard` and its `available()` is
  literally `return True  # pure pip dependency`. But `zstd` was still a row in
  `tools.CANDIDATES`, so `find_tools()` reported it, and the Settings tab
  printed **"zstd — not installed"** for a codec that is installed, in-process,
  and used by the whole Fast profile. That reads as a degraded install and
  invites a pointless download.

**The fix is a qualifier, not a deletion**, following the `LEGACY_ONLY`
precedent already in `tools.py`. Deleting the row would leave `zstd` as a
stage id in the planner, the estimator and the progress model with no entry
anywhere explaining why it has no binary; a row that explains itself is worth
more than an absent one. `set(find_tools())` therefore keeps its shape, which
`tests/test_tools.py` has always pinned.
"""

from __future__ import annotations

import pytest

from excmp.tools import IN_PROCESS, LEGACY_ONLY, find_tools


def test_the_tool_table_still_lists_every_name_it_used_to():
    """The shape is a contract - the planner, estimator and progress model all
    speak these names."""
    assert set(find_tools()) >= {"7z", "precomp", "srep", "zpaqfranz",
                                 "ffmpeg", "ffprobe", "zstd"}


def test_zstd_is_declared_in_process():
    assert "zstd" in IN_PROCESS
    # And it is a different statement from "legacy", which means found,
    # runnable, and never chosen for a new archive.
    assert "zstd" not in LEGACY_ONLY


def test_the_things_that_really_are_external_are_not_declared_in_process():
    """A blanket claim would be worse than none: 7-Zip and precomp genuinely
    are executables, and saying otherwise would suppress the one message a
    user needs when they are absent."""
    assert IN_PROCESS.isdisjoint({"7z", "precomp", "srep", "zpaqfranz",
                                  "ffmpeg", "ffprobe", "qpdf", "flac"})


def test_the_zstd_stage_is_available_whatever_the_tool_table_says():
    from excmp.stages.zstdstage import ZstdStage

    assert ZstdStage().available() is True


def test_lepton_is_a_wheel_and_is_not_in_the_tool_table():
    """Pinned because the roadmap's own text once implied an exe, and adding
    a `lepton` row would produce exactly the "not installed" lie B10 exists to
    remove - for a codec that ships as a wheel and self-checks bit-exactness."""
    assert "lepton" not in find_tools()
    from excmp import jpeg

    assert isinstance(jpeg.available(), bool)


# --------------------------------------------------------------------------
# the user-visible half
# --------------------------------------------------------------------------

pytest.importorskip("pytestqt")


def test_the_settings_tab_does_not_call_an_in_process_codec_missing(qtbot):
    """The defect, at the surface where a user meets it."""
    from excmp.tools import ToolInfo
    from gui.widgets.settings_tab import SettingsTab

    tools = {
        "7z": ToolInfo(name="7z", path=r"C:\Program Files\7-Zip\7z.exe",
                       version="7-Zip 26.02"),
        "zstd": None,
        "ffmpeg": None,
    }
    tab = SettingsTab(tools, default_temp=__import__("pathlib").Path("."))
    qtbot.addWidget(tab)
    text = tab.tools_text()

    assert "zstd — not installed" not in text, text
    # It is still listed, and it says something true and useful instead.
    assert "zstd" in text
    zstd_line = next(line for line in text.splitlines() if line.startswith("zstd"))
    assert "no executable" in zstd_line.lower() or "in-process" in zstd_line.lower(), \
        zstd_line
    # ffmpeg really is an absent executable, and must still say so.
    assert "ffmpeg — not installed" in text, text


def test_the_status_strip_never_reports_an_in_process_codec_as_missing(qtbot):
    """`mainwindow` builds its "missing:" list from a hard-coded pair today.
    This asserts the *rule* rather than the pair, so adding zstd to that list
    later cannot reintroduce the lie."""
    from excmp.tools import IN_PROCESS

    import gui.mainwindow as mw
    source = __import__("inspect").getsource(mw.MainWindow._refresh_status
                                             if hasattr(mw.MainWindow, "_refresh_status")
                                             else mw.MainWindow)
    # Whatever names the strip treats as reportable-missing, none of them may
    # be a codec we ship in-process.
    for name in IN_PROCESS:
        assert f'"{name}", ' not in source or "IN_PROCESS" in source, (
            f"the status strip may report {name!r} as missing, but it ships "
            f"in-process")
