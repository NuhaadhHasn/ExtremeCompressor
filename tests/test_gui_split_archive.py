"""A split archive (``name.excmp.001``, ``.002`` ...) in the Extract tab.

Found by the user guide: choosing the first part restored and verified correctly, but the tab called it "not
created by ExtremeCompressor" and greyed Verify out (a part is a slice of the container, not a zip, so the
manifest check could not see it).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from excmp import engine                              # noqa: E402
from excmp.planner import Profile                     # noqa: E402
from excmp.stages.base import StageContext            # noqa: E402
from excmp.tools import find_tools                    # noqa: E402
from excmp.volumes import split_file, write_parts_sidecar   # noqa: E402
from gui.mainwindow import MainWindow                 # noqa: E402
from gui.models import JobState                       # noqa: E402

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None, reason="7z.exe not installed")


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def parts(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("alpha " * 20_000)
    (src / "b.bin").write_bytes(bytes((i * 31 + 7) % 256 for i in range(60_000)))
    arc = tmp_path / "split.excmp"
    engine.compress([src], arc, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    digests: dict[str, str] = {}
    made = split_file(arc, max(1, arc.stat().st_size // 3), digests)
    write_parts_sidecar(made, digests)
    arc.unlink()
    assert len(made) > 1
    return made


def _open(window, first, tmp_path):
    tab = window.extract_tab
    tab.set_archive(first)
    tab.dest_edit.setText(str(tmp_path / "out"))
    return tab


@needs_7z
def test_the_first_part_is_recognised_as_ours(window, parts, tmp_path):
    tab = _open(window, parts[0], tmp_path)
    assert tab.verify_button.isEnabled()
    text = tab.status.text().lower()
    assert "not created by" not in text and "part" in text and str(len(parts)) in text


@needs_7z
def test_a_missing_part_is_named_before_anything_runs(window, parts, tmp_path):
    parts[1].unlink()
    tab = _open(window, parts[0], tmp_path)
    assert parts[1].name in tab.status.text() or ".002" in tab.status.text()


@needs_7z
def test_verify_and_restore_work_from_the_first_part(window, parts, tmp_path, qtbot):
    tab = _open(window, parts[0], tmp_path)
    tab.verify_button.click()
    qtbot.waitUntil(lambda: window.queue.jobs and window.queue.jobs[-1].state.is_terminal, timeout=120_000)
    assert window.queue.jobs[-1].state is JobState.DONE, window.queue.jobs[-1].error
    tab.start_button.click()
    qtbot.waitUntil(lambda: len(window.queue.jobs) == 2 and window.queue.jobs[-1].state.is_terminal, timeout=120_000)
    assert window.queue.jobs[-1].state is JobState.DONE, window.queue.jobs[-1].error
    assert {p.name for p in (tmp_path / "out").rglob("*") if p.is_file()} == {"a.txt", "b.bin"}


@needs_7z
def test_somebody_elses_001_without_our_sidecar_stays_a_foreign_archive(window, tmp_path):
    other = tmp_path / "backup.7z.001"
    other.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 100)
    tab = window.extract_tab
    tab.set_archive(other)
    assert not tab.verify_button.isEnabled()
    assert "not created by" in tab.status.text().lower()
