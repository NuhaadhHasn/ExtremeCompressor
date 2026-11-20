"""I5, the GUI half: Explorer starts ONE PROCESS PER SELECTED FILE, so the first becomes the
window and the rest hand their paths to it (``gui.singleinstance``); ``MainWindow.handle_intake``
then acts on what arrived.

Everything runs on a per-test pipe name, so a developer's running ExtremeCompressor is never
touched and parallel runs cannot meet.
"""

from __future__ import annotations


import uuid
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication                          # noqa: E402
from PySide6.QtNetwork import QLocalSocket                           # noqa: E402

from excmp import intake as I                                        # noqa: E402
from gui.mainwindow import MainWindow                                # noqa: E402
from gui.singleinstance import IntakeBatcher, IntakeServer, acquire, forward  # noqa: E402


@pytest.fixture
def name():
    return f"ExtremeCompressorTest-{uuid.uuid4().hex}"


@pytest.fixture
def server(qtbot, name):
    """The window that is already running: it holds the lock and listens."""
    srv = IntakeServer(name)
    assert acquire(srv, None) is True
    yield srv
    srv.close()


_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from excmp.intake import Intake
from gui.singleinstance import IntakeServer, acquire, forward
app = QCoreApplication([])
mode, name = sys.argv[2], sys.argv[3]
intake = Intake("compress", tuple(Path(p) for p in sys.argv[4:]))
if mode == "forward":
    sys.exit(0 if forward(name, intake) else 1)
if mode == "window":
    # A whole instance: become the window or hand over; the window stays up and reports.
    srv = IntakeServer(name)
    if not acquire(srv, intake):
        print("FORWARDED", flush=True)
        sys.exit(0)
    got = [str(p) for p in intake.paths]
    srv.received.connect(lambda i: got.extend(str(p) for p in i.paths))
    print("PRIMARY", flush=True)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(5000, app.quit)
    app.exec()
    print("GOT " + "|".join(sorted(got)), flush=True)
    sys.exit(0)
sys.exit(0 if not acquire(IntakeServer(name), intake) else 10)   # 0: handed over; 10: became window
'''
_REPO = Path(__file__).resolve().parent.parent


_SPAWNED: list = []


def _spawn(mode, name, *paths, capture=False):
    """A REAL second process. Two Qt endpoints in one process (or one thread each) do not behave
    like two processes - a first version of these tests failed for that reason while a probe with
    two real processes delivered every message - so the transport is tested the way it is used.

    The child gets no handle of pytest's: a child that inherits them keeps whatever pipes pytest's
    output (``| tail``, a CI log) open until it exits, which hung a run for minutes. The venv's
    ``python.exe`` is a launcher that starts the real interpreter, so a test that kills one must kill
    the tree - ``_reap`` does, for every child, afterwards."""
    import subprocess
    import sys
    proc = subprocess.Popen([sys.executable, "-I", "-c", _CHILD, str(_REPO), mode, name, *paths],
                            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else subprocess.DEVNULL, text=True)
    _SPAWNED.append(proc)
    return proc


def _kill_tree(proc) -> None:
    import subprocess
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(autouse=True)
def _reap():
    yield
    while _SPAWNED:
        proc = _SPAWNED.pop()
        if proc.poll() is None:
            _kill_tree(proc)
        try:
            proc.wait(10)
        except Exception:                                # noqa: BLE001
            pass
        if proc.stdout:
            proc.stdout.close()


_second_process = _spawn


# -- the server ----------------------------------------------------------------

def test_a_forwarded_intake_reaches_the_running_instance(qtbot, server, name):
    with qtbot.waitSignal(server.received, timeout=15000) as got:
        child = _second_process("forward", name, r"C:\a b\c.txt")
    assert got.args[0] == I.Intake("compress", (Path(r"C:\a b\c.txt"),))
    assert child.wait(15) == 0


def test_forward_to_nobody_says_so(qtbot, name):
    assert forward(name, I.Intake("compress", (Path(r"C:\x"),)), timeout_ms=150) is False


def test_garbage_on_the_pipe_is_dropped_not_obeyed(qtbot, server, name):
    for payload in (b"not json", b'{"action": "format-disk", "paths": ["C:\\\\a"]}', b"\xff" * 50):
        sock = QLocalSocket()
        sock.connectToServer(name)
        assert sock.waitForConnected(1000)
        sock.write(payload)
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
    with qtbot.assertNotEmitted(server.received, wait=400):
        pass


def test_an_oversized_message_is_cut_off(qtbot, server, name):
    sock = QLocalSocket()
    sock.connectToServer(name)
    assert sock.waitForConnected(1000)
    sock.write(b"x" * (I.MAX_WIRE_BYTES + 4096))
    sock.waitForBytesWritten(2000)
    sock.disconnectFromServer()
    with qtbot.assertNotEmitted(server.received, wait=500):
        pass


def test_several_files_each_from_its_own_process_all_arrive(qtbot, server, name):
    got = []
    server.received.connect(got.append)
    children = [_second_process("forward", name, rf"C:\f{i}.txt") for i in range(6)]
    qtbot.waitUntil(lambda: len(got) == 6, timeout=30000)
    assert {p.name for i in got for p in i.paths} == {f"f{i}.txt" for i in range(6)}
    assert [c.wait(15) for c in children] == [0] * 6


# -- becoming the window, or handing over --------------------------------------

def test_the_first_instance_becomes_the_window(qtbot, name):
    srv = IntakeServer(name)
    try:
        assert acquire(srv, I.Intake("compress", (Path(r"C:\a"),))) is True
    finally:
        srv.close()


def test_the_name_is_free_again_when_the_window_closes(qtbot, name):
    first = IntakeServer(name)
    assert acquire(first, None)
    first.close()
    second = IntakeServer(name)
    try:
        assert acquire(second, I.Intake("compress", (Path(r"C:\a"),)), deadline_s=0.3) is True
    finally:
        second.close()


def test_five_processes_started_together_make_exactly_one_window(qtbot, name):
    """The cold start Explorer produces: five verbs, five processes, no window yet. THIS is what a
    first version got wrong (every process could `listen`, so every one thought it was first)."""
    paths = [rf"C:\f{i}.txt" for i in range(5)]
    procs = [_spawn("window", name, p, capture=True) for p in paths]
    outs = [p.communicate(timeout=60)[0].split() for p in procs]
    primaries = [o for o in outs if o and o[0] == "PRIMARY"]
    assert len(primaries) == 1, outs
    assert sum(1 for o in outs if o and o[0] == "FORWARDED") == 4, outs
    assert "|".join(sorted(paths)) in " ".join(primaries[0]), primaries[0]


def test_a_window_that_dies_frees_its_name(qtbot, name):
    """A crash must not leave "a window is running" behind: the OS releases the mutex."""
    window = _spawn("window", name, r"C:\x.txt", capture=True)
    assert window.stdout.readline().strip() == "PRIMARY"
    _kill_tree(window)                                   # a crash, not a clean exit
    window.wait(10)
    second = IntakeServer(name)
    try:
        assert acquire(second, I.Intake("compress", (Path(r"C:\y.txt"),)), deadline_s=3) is True
    finally:
        second.close()


def test_a_second_instance_with_files_hands_them_over_and_exits(qtbot, server, name):
    with qtbot.waitSignal(server.received, timeout=15000) as got:
        child = _second_process("acquire", name, r"C:\second.txt")
    assert got.args[0] == I.Intake("compress", (Path(r"C:\second.txt"),))
    assert child.wait(15) == 0                # 0: "I handed it over, I should exit"


def test_a_second_plain_launch_just_opens_its_own_window(qtbot, server, name):
    """Nothing to hand over, so nothing is lost by running alongside."""
    second = IntakeServer(name)
    assert acquire(second, None, deadline_s=0.3) is True


def test_acquire_does_not_hang_forever_when_the_window_never_answers(qtbot, monkeypatch, name):
    """Another process holds the lock but never listens: after the deadline this one runs on its
    own, because dropping the user's files silently is the worse failure."""
    srv = IntakeServer(name)
    import gui.singleinstance as si
    monkeypatch.setattr(si, "_try_lock", lambda n: None)
    monkeypatch.setattr(si, "forward", lambda *a, **k: False)
    assert acquire(srv, I.Intake("compress", (Path(r"C:\a"),)), deadline_s=0.3, step_ms=20) is True


# -- batching -------------------------------------------------------------------

def test_files_arriving_one_by_one_are_queued_once(qtbot):
    calls = []
    b = IntakeBatcher(calls.append, window_ms=120)
    for i in range(5):
        b.push(I.Intake("compress", (Path(rf"C:\f{i}.txt"),)))
    b.push(I.Intake("compress", (Path(r"C:\F0.txt"),)))            # a duplicate, other case
    assert calls == []
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    assert [p.name for p in calls[0].paths] == [f"f{i}.txt" for i in range(5)]
    assert calls[0].action == "compress"


def test_an_archive_is_not_made_to_wait(qtbot):
    calls = []
    b = IntakeBatcher(calls.append, window_ms=500)
    b.push(I.Intake("extract", (Path(r"C:\a.excmp"),)))
    assert len(calls) == 1


def test_a_batch_after_a_pause_is_a_new_batch(qtbot):
    calls = []
    b = IntakeBatcher(calls.append, window_ms=60)
    b.push(I.Intake("compress", (Path(r"C:\a"),)))
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    b.push(I.Intake("compress", (Path(r"C:\b"),)))
    qtbot.waitUntil(lambda: len(calls) == 2, timeout=2000)
    assert [p.name for p in calls[1].paths] == ["b"]


# -- the window acts on it ------------------------------------------------------

@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_compress_queues_the_files_that_exist_on_the_compress_tab(qtbot, win, tmp_path, monkeypatch):
    real = tmp_path / "real.txt"
    real.write_text("x")
    folder = tmp_path / "folder"
    folder.mkdir()
    got = []
    monkeypatch.setattr(win, "add_paths", got.extend)
    win.tabs.setCurrentWidget(win.extract_tab)
    win.handle_intake(I.Intake("compress", (real, folder, tmp_path / "gone.txt")))
    assert got == [real, folder]
    assert win.tabs.currentWidget() is win._scroll


def test_a_missing_path_is_said_not_swallowed(qtbot, win, tmp_path, monkeypatch):
    monkeypatch.setattr(win, "add_paths", lambda p: pytest.fail("nothing to add"))
    win.handle_intake(I.Intake("compress", (tmp_path / "gone.txt",)))
    assert "gone.txt" in win.banner._text.text()


def test_extract_opens_the_archive_with_its_own_destination(qtbot, win, tmp_path):
    first, second = tmp_path / "one.excmp", tmp_path / "two.excmp"
    first.write_bytes(b"x")
    second.write_bytes(b"y")
    win.handle_intake(I.Intake("extract", (first,)))
    assert win.tabs.currentWidget() is win.extract_tab
    assert win.extract_tab.archive_edit.text() == str(first)
    assert win.extract_tab.dest_edit.text() == str(tmp_path / "one")
    # The next archive must not inherit the last one's destination.
    win.handle_intake(I.Intake("extract", (second,)))
    assert win.extract_tab.dest_edit.text() == str(tmp_path / "two")


def test_extract_here_starts_the_restore_through_the_same_door_as_the_button(qtbot, win, tmp_path):
    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    seen = []
    win.extract_tab.extractRequested.connect(lambda a, d: seen.append((Path(a), Path(d))))
    win.queue.add_extract = lambda a, d: None                       # no real job
    win.handle_intake(I.Intake("extract-here", (archive,)))
    assert seen == [(archive, tmp_path / "a")]


def test_extract_without_here_only_opens_the_tab(qtbot, win, tmp_path):
    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    seen = []
    win.extract_tab.extractRequested.connect(lambda a, d: seen.append(a))
    win.handle_intake(I.Intake("extract", (archive,)))
    assert seen == []


def test_verify_asks_for_the_restore_check(qtbot, win, tmp_path):
    archive = _make_archive(tmp_path)          # a real one: the Verify button refuses a fake
    seen = []
    win.extract_tab.verifyRequested.connect(lambda a: seen.append(Path(a)))
    win.start_verification = lambda a: None
    win.handle_intake(I.Intake("verify", (archive,)))
    assert seen == [archive]


def test_a_folder_is_not_an_archive(qtbot, win, tmp_path):
    folder = tmp_path / "f.excmp"
    folder.mkdir()
    win.handle_intake(I.Intake("extract", (folder,)))
    assert win.extract_tab.archive_edit.text() == ""


# -- the whole entry point ------------------------------------------------------

def test_main_hands_the_launch_arguments_to_the_window(qtbot, monkeypatch, tmp_path, name):
    """``python run_gui.py extract X.excmp`` - what the double-click verb runs - ends up in
    ``MainWindow.handle_intake`` once the window is up."""
    import gui.app as app_mod
    import gui.singleinstance as si
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(si, "default_name", lambda: name)
    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(MainWindow, "handle_intake", lambda self, i: seen.append(i))
    QTimer.singleShot(0, QCoreApplication.quit)        # leave the event loop as soon as it starts
    assert app_mod.main(["run_gui.py", "extract", str(archive)]) == 0
    assert seen == [I.Intake("extract", (archive,))]


def test_main_without_arguments_just_opens_the_window(qtbot, monkeypatch, name):
    import gui.app as app_mod
    import gui.singleinstance as si
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(si, "default_name", lambda: name)
    seen = []
    monkeypatch.setattr(MainWindow, "handle_intake", lambda self, i: seen.append(i))
    QTimer.singleShot(0, QCoreApplication.quit)
    assert app_mod.main(["run_gui.py"]) == 0
    assert seen == []


# -- the review of 854a203 (GUI half): each of these failed before the fix ------

def _make_archive(tmp_path, folder="dl", name="one"):
    """A real archive of ``src/proj/a.txt`` placed in ``tmp_path/<folder>``: one top-level folder,
    which is the case where "Extract here" suggests the archive's OWN folder."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext
    src = tmp_path / "src" / "proj"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.txt").write_text("hello")
    dl = tmp_path / folder
    dl.mkdir(exist_ok=True)
    arch = dl / f"{name}.excmp"
    engine.compress([src], arch, Profile("fast"), StageContext(temp_dir=tmp_path / "tmp"))
    return arch


def _extract_requests(win):
    seen = []
    win.extract_tab.extractRequested.connect(lambda a, d: seen.append((Path(a), Path(d))))
    win.queue.add_extract = lambda a, d: None                       # no real job
    return seen


def test_extract_here_never_overwrites_a_file_that_is_already_there(qtbot, win, tmp_path):
    """Review: one right-click on a downloaded archive put the user's edited a.txt back to its
    archived text - no prompt, no visible destination. Now a collision means a fresh folder."""
    archive = _make_archive(tmp_path)
    mine = archive.parent / "proj" / "a.txt"
    mine.parent.mkdir()
    mine.write_text("USER EDIT")
    seen = _extract_requests(win)
    win.handle_intake(I.Intake("extract-here", (archive,)))
    assert len(seen) == 1
    _, dest = seen[0]
    assert dest != archive.parent and not (dest / "proj" / "a.txt").exists()
    assert mine.read_text() == "USER EDIT"


def test_extract_here_uses_the_archives_own_folder_when_nothing_would_collide(qtbot, win, tmp_path):
    archive = _make_archive(tmp_path)
    seen = _extract_requests(win)
    win.handle_intake(I.Intake("extract-here", (archive,)))
    assert seen == [(archive, archive.parent)]


def test_extract_here_takes_the_next_free_folder_name(qtbot, win, tmp_path):
    archive = _make_archive(tmp_path)
    (archive.parent / "proj").mkdir()
    (archive.parent / "proj" / "a.txt").write_text("x")
    (archive.parent / "one").mkdir()
    (archive.parent / "one (2)").mkdir()
    seen = _extract_requests(win)
    win.handle_intake(I.Intake("extract-here", (archive,)))
    assert seen[0][1] == archive.parent / "one (3)"


def test_extract_here_on_an_unreadable_archive_still_does_not_write_into_the_folder(qtbot, win, tmp_path):
    junk = tmp_path / "junk.excmp"
    junk.write_bytes(b"not an archive")
    (tmp_path / "junk").mkdir()
    seen = _extract_requests(win)
    win.handle_intake(I.Intake("extract-here", (junk,)))
    assert all(dest != tmp_path for _, dest in seen)


def test_verify_asks_the_button_s_question_first(qtbot, win, tmp_path):
    """The Verify button is off for an archive with no SHA-256 ledger; the verb must not be able
    to queue a job the button would refuse."""
    import zipfile
    foreign = tmp_path / "x.zip"
    with zipfile.ZipFile(foreign, "w") as z:
        z.writestr("a.txt", "x")
    seen = []
    win.extract_tab.verifyRequested.connect(lambda a: seen.append(a))
    win.handle_intake(I.Intake("verify", (foreign,)))
    assert seen == []
    assert "verif" in win.banner._text.text().lower()


def test_extract_here_asks_the_buttons_question_first(qtbot, win, tmp_path):
    seen = _extract_requests(win)
    folder = tmp_path / "f.excmp"
    folder.write_bytes(b"x")
    win.extract_tab.dest_edit.setText("")
    win.extract_tab.set_archive(folder)
    win.extract_tab.dest_edit.setText("")                  # no destination: the button is off
    win.extract_tab.request_extract()
    assert seen == []


def test_a_failed_extract_does_not_leave_the_folder_it_made(tmp_path):
    """Review: junk.excmp -> a `junk/` folder appeared beside it, empty, and stayed."""
    from excmp import engine
    from excmp.stages.base import StageContext
    junk = tmp_path / "junk.excmp"
    junk.write_bytes(b"not an archive")
    out = tmp_path / "junk"
    with pytest.raises(Exception):
        engine.extract(junk, out, StageContext(temp_dir=tmp_path / "tmp"))
    assert not out.exists()


def test_a_failed_extract_leaves_a_folder_that_was_already_there(tmp_path):
    from excmp import engine
    from excmp.stages.base import StageContext
    junk = tmp_path / "junk.excmp"
    junk.write_bytes(b"not an archive")
    out = tmp_path / "junk"
    out.mkdir()
    with pytest.raises(Exception):
        engine.extract(junk, out, StageContext(temp_dir=tmp_path / "tmp"))
    assert out.is_dir()


# -- the mutations the first tests did not catch --------------------------------

def test_main_passes_a_forwarded_intake_on_to_the_window(qtbot, monkeypatch, name):
    """Delete `server.received.connect(batcher.push)` in main() and every other test still passed."""
    import gui.app as app_mod
    import gui.singleinstance as si
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(si, "default_name", lambda: name)
    seen = []
    monkeypatch.setattr(MainWindow, "handle_intake", lambda self, i: seen.append(i))
    QTimer.singleShot(300, lambda: _spawn("acquire", name, r"C:\late.txt"))   # a second process
    poll = QTimer()
    poll.timeout.connect(lambda: QCoreApplication.quit() if seen else None)
    poll.start(100)
    QTimer.singleShot(30_000, QCoreApplication.quit)                           # never hang
    assert app_mod.main(["run_gui.py"]) == 0
    assert seen == [I.Intake("compress", (Path(r"C:\late.txt"),))]


def test_acquire_takes_the_lock_when_the_running_window_goes_away(qtbot, monkeypatch, name):
    import gui.singleinstance as si
    handle = object()
    locks = iter([None, handle])
    monkeypatch.setattr(si, "_try_lock", lambda n: next(locks))
    monkeypatch.setattr(si, "forward", lambda *a, **k: False)
    srv = IntakeServer(name)
    try:
        assert acquire(srv, I.Intake("compress", (Path(r"C:\a"),)), deadline_s=2, step_ms=10) is True
        assert srv._lock is handle
    finally:
        srv.close()


def test_a_secondary_waits_long_enough_for_a_busy_window():
    """Review: a window busy for 6 s (a big archive, a slow start on 2 cores) made every waiting
    secondary give up after 4 s and open its own window - five windows for five files."""
    import inspect
    assert inspect.signature(acquire).parameters["deadline_s"].default >= 20


def test_the_window_is_brought_back_when_it_was_minimised(qtbot, win, tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(win, "add_paths", lambda p: None)
    win.show()
    win.showMinimized()
    if not win.isMinimized():
        pytest.skip("this Qt platform does not minimise")
    win.handle_intake(I.Intake("compress", (f,)))
    assert not win.isMinimized()
