"""Queue lifecycle, cancel, pause and drop handling, driven through Qt."""

import random

import pytest

from excmp.planner import Profile
from excmp.tools import find_tools

pytest.importorskip("pytestqt")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl          # noqa: E402
from PySide6.QtGui import QDropEvent                              # noqa: E402

from gui.models import JobState                                   # noqa: E402
from gui.queue_manager import QueueManager                        # noqa: E402
from gui.widgets.dropzone import DropZone, paths_from_mime        # noqa: E402

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


def _tiny_tree(root, name="data"):
    root = root / name
    root.mkdir()
    (root / "text.txt").write_text("queue me. " * 3_000)
    (root / "blob.bin").write_bytes(bytes(random.Random(1).getrandbits(8)
                                          for _ in range(4_000)))
    return root


def _big_tree(root):
    root = root / "big"
    root.mkdir()
    # Large enough that 7-Zip at -mx9 is still running when the cancel lands.
    (root / "big.txt").write_text("cancel me mid-flight. " * 900_000)
    return root


@pytest.fixture
def manager(tmp_path, qtbot):
    mgr = QueueManager(temp_dir=tmp_path / "tmp", tools=find_tools())
    yield mgr
    mgr.shutdown()


# ---------------------------------------------------------------- lifecycle
@needs_7z
def test_two_jobs_run_one_at_a_time_and_both_finish(manager, tmp_path, qtbot):
    done: list[str] = []
    manager.jobDone.connect(lambda job_id, _r: done.append(job_id))

    a = manager.add_compress([_tiny_tree(tmp_path, "a")], tmp_path / "a.excmp",
                             Profile.NORMAL)
    b = manager.add_compress([_tiny_tree(tmp_path, "b")], tmp_path / "b.excmp",
                             Profile.NORMAL)

    qtbot.waitUntil(lambda: len(done) == 2, timeout=120_000)
    assert done == [a.id, b.id], "jobs finished out of order"
    assert a.state is JobState.DONE and b.state is JobState.DONE
    assert a.final_bytes > 0 and a.final_bytes < a.orig_bytes or a.orig_bytes == 0
    assert (tmp_path / "a.excmp").exists() and (tmp_path / "b.excmp").exists()
    assert not manager.is_busy


@needs_7z
def test_progress_is_monotonic_and_ends_at_100(manager, tmp_path, qtbot):
    seen: list[float] = []
    manager.jobProgress.connect(lambda _i, _s, pct, _e: seen.append(pct))
    job = manager.add_compress([_tiny_tree(tmp_path)], tmp_path / "p.excmp",
                               Profile.NORMAL)

    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=120_000)
    assert job.state is JobState.DONE
    assert seen, "no progress was ever reported"
    assert seen == sorted(seen), f"progress went backwards: {seen}"
    assert seen[-1] == 100.0


@needs_7z
def test_job_log_captures_tool_output(manager, tmp_path, qtbot):
    job = manager.add_compress([_tiny_tree(tmp_path)], tmp_path / "l.excmp",
                               Profile.NORMAL)
    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=120_000)
    assert any("7-Zip" in line for line in job.log)
    assert job.log[0].startswith("profile 'normal'")


# ------------------------------------------------------------------- cancel
@needs_7z
def test_cancelling_a_running_job_leaves_nothing_behind(manager, tmp_path, qtbot):
    out = tmp_path / "cancelled.excmp"
    job = manager.add_compress([_big_tree(tmp_path)], out, Profile.NORMAL)

    qtbot.waitUntil(lambda: job.state is JobState.RUNNING and job.percent > 0,
                    timeout=60_000)
    manager.cancel(job.id)
    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=60_000)

    assert job.state is JobState.CANCELLED
    assert not out.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert not manager.is_busy


def test_cancelling_a_queued_job_never_starts_it(manager, tmp_path, qtbot):
    manager.pause()
    job = manager.add_compress([_tiny_tree(tmp_path)], tmp_path / "q.excmp",
                               Profile.FAST)
    manager.cancel(job.id)
    assert job.state is JobState.CANCELLED
    manager.resume()
    qtbot.wait(300)
    assert not (tmp_path / "q.excmp").exists()


# -------------------------------------------------------------------- pause
def test_a_paused_queue_starts_nothing(manager, tmp_path, qtbot):
    manager.pause()
    a = manager.add_compress([_tiny_tree(tmp_path, "a")], tmp_path / "a.excmp",
                             Profile.FAST)
    b = manager.add_compress([_tiny_tree(tmp_path, "b")], tmp_path / "b.excmp",
                             Profile.FAST)

    qtbot.wait(500)
    assert a.state is JobState.QUEUED and b.state is JobState.QUEUED
    assert not manager.is_busy

    manager.resume()
    qtbot.waitUntil(lambda: a.state.is_terminal and b.state.is_terminal,
                    timeout=120_000)
    assert a.state is JobState.DONE and b.state is JobState.DONE


def test_pause_reports_its_state(manager, qtbot):
    changes: list[bool] = []
    manager.pausedChanged.connect(changes.append)
    manager.toggle_pause()
    manager.toggle_pause()
    assert changes == [True, False]
    assert not manager.is_paused


# ------------------------------------------------------------------ extract
@needs_7z
def test_compress_then_extract_verifies_every_hash(manager, tmp_path, qtbot):
    src = _tiny_tree(tmp_path)
    archive = tmp_path / "round.excmp"
    job = manager.add_compress([src], archive, Profile.NORMAL)
    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=120_000)
    assert job.state is JobState.DONE

    restore = manager.add_extract(archive, tmp_path / "restored")
    qtbot.waitUntil(lambda: restore.state.is_terminal, timeout=120_000)
    assert restore.state is JobState.DONE
    assert restore.result.verified == 2
    assert (tmp_path / "restored" / "data" / "text.txt").read_text() == \
           (src / "text.txt").read_text()


# --------------------------------------------------------------------- drop
def test_paths_from_mime_keeps_files_and_folders(tmp_path):
    folder = _tiny_tree(tmp_path)
    loose = tmp_path / "loose.txt"
    loose.write_text("hi")

    mime = QMimeData()
    mime.setUrls([
        QUrl.fromLocalFile(str(folder)),
        QUrl.fromLocalFile(str(loose)),
        QUrl.fromLocalFile(str(folder)),          # duplicate
        QUrl.fromLocalFile(str(tmp_path / "gone.txt")),   # does not exist
        QUrl("https://example.com/x.zip"),        # not a local path
    ])
    assert paths_from_mime(mime) == [folder, loose]


def test_dropping_a_file_and_a_folder_adds_both(tmp_path, qtbot):
    """HandBrake's most-reported intake bug, pinned down as a test."""
    zone = DropZone()
    qtbot.addWidget(zone)
    folder = _tiny_tree(tmp_path)
    loose = tmp_path / "note.txt"
    loose.write_text("hi")

    received: list[list] = []
    zone.pathsAdded.connect(received.append)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(loose))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dropEvent(event)

    assert received == [[folder, loose]]
    assert zone.property("dragActive") is False
