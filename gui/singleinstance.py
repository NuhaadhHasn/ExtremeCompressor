"""I5: one window, however many processes Explorer starts.

A right-click on five selected files runs the verb five times: five processes, each given one path.
The first becomes the window and listens on a per-user local pipe; the others write what they
were given to it and exit; the window queues the lot as one batch (:class:`IntakeBatcher`).

**Why a mutex, not the pipe, decides who is the window.** The obvious design - "whoever can
``listen`` is the window" - is wrong on Windows: a second process's ``QLocalServer.listen`` on a
name another process already holds *succeeds* (Qt makes another pipe instance), so five processes
started together would each think they were first and open five windows. A first version of this
module did exactly that, and a test with real processes caught it. A named mutex is created by
exactly one process, so that one is the window; the others connect and forward, and if that fails
(the winner is still starting) they retry for a few seconds and then run on their own rather than
drop the user's files.

**The pipe is not trusted.** It is limited to the current user, and :func:`excmp.intake.from_wire`
still believes nothing it reads.
"""

from __future__ import annotations

import ctypes
import getpass
import re
import sys
import time
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from excmp.intake import MAX_WIRE_BYTES, Intake, from_wire, to_wire


def default_name() -> str:
    """One pipe per Windows user: two users on a shared machine must not hand each other files."""
    try:
        user = getpass.getuser()
    except Exception:                                    # noqa: BLE001
        user = "user"
    return "ExtremeCompressor-intake-v1-" + re.sub(r"[^A-Za-z0-9_-]", "_", user)


_ERROR_ALREADY_EXISTS = 183
_NO_LOCK = object()                                      # a platform with no mutex: listen decides


def _try_lock(name: str):
    """Take the per-user "I am the window" lock. A handle if this process now holds it, ``None``
    if another process does. Held until the handle is closed (at the latest, process exit - so a
    window that crashes frees it)."""
    if sys.platform != "win32":
        return _NO_LOCK
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, 0, f"Local\\{name}-lock")
        if not handle:
            return _NO_LOCK                              # cannot decide: be a window, not nothing
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return (kernel32, handle)
    except Exception:                                    # noqa: BLE001
        return _NO_LOCK


class IntakeServer(QObject):
    """Listens for what second processes forward. Emits ``received`` once per valid message."""

    received = Signal(object)                            # an excmp.intake.Intake

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or default_name()
        self._lock = None
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        # Never ``removeServer``: on Windows a name in use is a live window, and stealing it
        # would orphan that window's pipe.
        return self._server.listen(self._name)

    def hold(self, lock) -> None:
        self._lock = lock

    def close(self) -> None:
        self._server.close()
        lock, self._lock = self._lock, None
        if isinstance(lock, tuple):
            lock[0].CloseHandle(lock[1])

    def _accept(self) -> None:
        while True:
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            state = {"buf": bytearray(), "done": False}
            sock.readyRead.connect(lambda s=sock, st=state: self._read(s, st))
            sock.disconnected.connect(lambda s=sock, st=state: self._finish(s, st))
            # A second process writes and exits within milliseconds, so by the time this runs
            # the data may be here and the peer already gone: no signal would follow. Look now.
            self._read(sock, state)
            if sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                self._finish(sock, state)

    def _read(self, sock: QLocalSocket, state: dict) -> None:
        if state["done"]:
            return
        buf = state["buf"]
        buf += sock.readAll().data()
        if len(buf) > MAX_WIRE_BYTES:                    # not one of ours: stop listening to it
            state["done"] = True
            buf.clear()
            sock.abort()
            return
        self._deliver(state)                             # a complete message needs no goodbye

    def _finish(self, sock: QLocalSocket, state: dict) -> None:
        if not state["done"]:
            state["buf"] += sock.readAll().data()
            self._deliver(state)
        state["done"] = True
        sock.deleteLater()

    def _deliver(self, state: dict) -> None:
        if state["done"] or not state["buf"] or len(state["buf"]) > MAX_WIRE_BYTES:
            return
        intake = from_wire(bytes(state["buf"]))
        if intake is not None:
            state["done"] = True                         # exactly once per connection
            self.received.emit(intake)


def forward(name: str, intake: Intake, timeout_ms: int = 400) -> bool:
    """Hand ``intake`` to the instance listening on ``name``. True if it was written."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(to_wire(intake))
    ok = sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout_ms)
    return bool(ok)


def acquire(server: IntakeServer, intake: Intake | None, *, deadline_s: float = 30.0,
            step_ms: int = 80) -> bool:
    """True: this process is the window (or runs alone). False: its files were handed to the
    running window and it should exit.

    ``deadline_s`` is generous on purpose: a window that cannot take a message (a big archive
    being opened, a slow start on two cores, a 100-file selection) is BUSY, not gone, and a
    secondary that gave up after 4 s opened a window of its own - five windows for five files in
    the I5 review. A crashed window frees its lock at once and is taken over without waiting."""
    def become_the_window(lock) -> bool:
        server.hold(lock)
        server.listen()           # if the pipe is somehow unavailable we are still the window
        return True

    lock = _try_lock(server._name)
    if lock is not None:
        return become_the_window(lock)
    if intake is None:                                   # a second plain launch: its own window
        return True
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if forward(server._name, intake):
            return False
        lock = _try_lock(server._name)                   # the running one went away meanwhile
        if lock is not None:
            return become_the_window(lock)
        QThread.msleep(step_ms)
    return True                                          # never drop the user's files silently


class IntakeBatcher(QObject):
    """Joins ``compress`` intakes that arrive within ``window_ms`` of each other into one.

    Five processes deliver five paths over a few hundred milliseconds; analysing five times, each
    run cancelling the last, helps nobody. An archive is acted on at once.
    """

    def __init__(self, handler: Callable[[Intake], None], window_ms: int = 350,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._paths: list = []
        self._seen: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(window_ms)
        self._timer.timeout.connect(self._flush)

    def push(self, intake: Intake) -> None:
        if intake.action != "compress":
            self._handler(intake)
            return
        for path in intake.paths:
            key = str(path).lower()
            if key not in self._seen:
                self._seen.add(key)
                self._paths.append(path)
        self._timer.start()                              # each arrival restarts the window

    def _flush(self) -> None:
        paths, self._paths, self._seen = self._paths, [], set()
        if paths:
            self._handler(Intake("compress", tuple(paths)))
