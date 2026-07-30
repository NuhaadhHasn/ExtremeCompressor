"""Engine-level pause and cancel guarantees the GUI depends on.

No Qt here: these are properties of ``engine.compress`` itself, and they are
the reason the queue can offer Pause and Cancel without lying about either.
"""

import os
import threading
import time
import zlib

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")
needs_precomp = pytest.mark.skipif(find_tools()["precomp"] is None,
                                   reason="precomp not installed")


def _tree(root, kilobytes=400):
    root.mkdir()
    (root / "a.txt").write_text("pause and cancel are load-bearing. " * (kilobytes * 30))
    (root / "b.txt").write_text("second file so the tar stage has work. " * 5_000)
    return root


def _run_in_thread(fn):
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised by the caller
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


@needs_7z
def test_pause_holds_at_a_stage_boundary(tmp_path):
    src = _tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "held.excmp"
    ctx.pause.set()      # held before the very first stage runs

    thread, box = _run_in_thread(
        lambda: engine.compress([src], out, Profile.NORMAL, ctx))
    thread.join(timeout=1.5)
    assert thread.is_alive(), "compress ran straight through a set pause flag"
    assert not out.exists()

    ctx.pause.clear()
    thread.join(timeout=120)
    assert not thread.is_alive()
    assert "error" not in box, box.get("error")
    assert out.exists()


@needs_7z
def test_cancel_while_paused_still_cancels(tmp_path):
    """Cancel must win over pause, or the Cancel button would appear dead
    whenever the queue happened to be held."""
    src = _tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "cancelled.excmp"
    ctx.pause.set()

    thread, box = _run_in_thread(
        lambda: engine.compress([src], out, Profile.NORMAL, ctx))
    time.sleep(0.4)
    ctx.cancel.set()
    thread.join(timeout=60)

    assert not thread.is_alive()
    assert isinstance(box.get("error"), Exception)
    assert not out.exists()


@needs_7z
def test_cancel_leaves_no_partial_archive_or_temp_file(tmp_path):
    """The .tmp lives next to the user's output, outside the job temp dir -
    a failure between writing it and the atomic rename used to strand it."""
    src = _tree(tmp_path / "data", kilobytes=1200)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "out.excmp"

    def cancel_on_first_progress(_stage, _pct):
        ctx.cancel.set()

    ctx.progress_cb = cancel_on_first_progress
    with pytest.raises(Exception):
        engine.compress([src], out, Profile.NORMAL, ctx)

    assert not out.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert (src / "a.txt").exists(), "inputs must never be touched"


@needs_7z
@needs_precomp
def test_tools_do_not_litter_the_working_directory(tmp_path, monkeypatch):
    """Precomp writes ~temp########.dat scratch files into the *current*
    directory. Under the CLI that was the repo; under the GUI it would be
    wherever the app was launched from - the user's home, or a read-only
    Program Files. Every stage runs with cwd inside our own temp dir."""
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    src = tmp_path / "data"
    src.mkdir()
    body = b"".join(b"RECORD/%d/mesh" % i + b"\x00" * 32 for i in range(30_000))
    (src / "assets.pak").write_bytes(zlib.compress(body, 1))
    (src / "notes.txt").write_text("something compressible. " * 5_000)

    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "out.excmp", Profile.EXTREME, ctx)

    assert os.listdir(workdir) == [], f"tools littered the cwd: {os.listdir(workdir)}"


@needs_7z
def test_log_callback_receives_the_tools_own_output(tmp_path):
    src = _tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    lines: list[tuple[str, str]] = []
    ctx.log_cb = lambda stage, line: lines.append((stage, line))

    engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)

    assert lines, "no tool output was forwarded"
    assert {stage for stage, _ in lines} == {"sevenzip"}
    assert any("7-Zip" in line for _stage, line in lines)
