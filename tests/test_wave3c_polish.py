"""Wave 3c polish: the destination guess, and the first-run notice."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from excmp import engine                        # noqa: E402
from excmp.planner import Profile               # noqa: E402
from excmp.stages.base import StageContext      # noqa: E402
from gui.mainwindow import MainWindow           # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def _archive(tmp_path, names, stem="bundle"):
    src = tmp_path / "src"
    for name in names:
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("data " * 300, encoding="utf-8")
    out = tmp_path / f"{stem}.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


# ---------------------------------------------------------------------------
# The Ark autosubfolder heuristic
# ---------------------------------------------------------------------------

def test_an_archive_with_one_top_folder_extracts_beside_itself(window, tmp_path):
    """Ark's rule. Everything is already under one folder, so making another
    to hold it produces `bundle/src/...` - a wrapper nobody wanted."""
    archive = _archive(tmp_path, ["a.txt", "b.txt"])          # all under src/
    window.extract_tab.set_archive(archive)
    assert Path(window.extract_tab.dest_edit.text()) == archive.parent


def test_a_loose_archive_gets_a_folder_of_its_own(window, tmp_path):
    """The other half of the rule: several things at the top level would spray
    across the destination, so they get a folder named after the archive."""
    src = tmp_path / "loose"
    src.mkdir()
    (src / "one.txt").write_text("x" * 400, encoding="utf-8")
    (src / "two.txt").write_text("y" * 400, encoding="utf-8")
    archive = tmp_path / "loose.excmp"
    engine.compress([src / "one.txt", src / "two.txt"], archive, Profile.FAST,
                    StageContext(temp_dir=tmp_path / "t"))

    window.extract_tab.set_archive(archive)
    assert Path(window.extract_tab.dest_edit.text()) == archive.with_suffix("")


def test_a_foreign_archive_falls_back_to_its_own_folder(window, tmp_path):
    """No manifest means no way to look inside without extracting, so the
    safe guess is a folder of its own rather than spraying the destination."""
    archive = tmp_path / "theirs.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("b.txt", "there")
    window.extract_tab.set_archive(archive)
    assert Path(window.extract_tab.dest_edit.text()) == archive.with_suffix("")


def test_a_destination_the_user_typed_is_never_overwritten(window, tmp_path):
    archive = _archive(tmp_path, ["a.txt"])
    window.extract_tab.dest_edit.setText(str(tmp_path / "mine"))
    window.extract_tab.set_archive(archive)
    assert window.extract_tab.dest_edit.text() == str(tmp_path / "mine")


# ---------------------------------------------------------------------------
# I4: the first-run notice
# ---------------------------------------------------------------------------

def test_the_first_run_notice_appears_once(qtbot):
    """I4, on W2-9's Banner. It says what the app will and will not do to your
    files - which is worth exactly one showing, not one per launch."""
    first = MainWindow()
    qtbot.addWidget(first)
    assert first.banner.isVisibleTo(first)
    text = first.banner.text().lower()
    # (the notice now says "Your files are never changed", in plain words; it used to say "originals")
    assert "never" in text and ("files" in text or "original" in text or "input" in text)
    assert "dropping a folder" in text                      # and it now says what to do first
    first.close()
    first.queue.shutdown()

    second = MainWindow()
    qtbot.addWidget(second)
    try:
        assert not second.banner.isVisibleTo(second)
    finally:
        second.queue.shutdown()
