"""E5: the update checker's side in the window - state, a background thread, and signals.

The network work is :mod:`excmp.updater` (Qt-free, tested against a real server). This class only runs it
off the GUI thread and says where it got to, so the Settings tab and the window can react:

    idle -> checking -> uptodate | available | error
    available -> downloading -> ready | error
    ready -> (the window starts the installer and closes)

Nothing here blocks the GUI, shows a modal dialog or touches the disk outside the temp folder.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, Signal

from excmp import updater

LAST_CHECK_KEY = "updates/last_check"
AUTO_KEY = "settings/update_check"


class _Signals(QObject):
    done = Signal(object)          # (kind, payload)


def _run(fn: Callable[[], object], kind: str, signals: _Signals) -> None:
    """Run ``fn`` on a DAEMON thread (a QThreadPool would keep the process alive until a stuck download ends)
    and report the outcome as a signal, which Qt delivers on the GUI thread."""
    try:
        result = (kind, fn(), None)
    except updater.Cancelled:
        return
    except updater.UpdateError as exc:
        result = (kind, None, str(exc))
    except Exception as exc:                                       # noqa: BLE001 - never let a thread die silently
        result = (kind, None, f"unexpected error: {type(exc).__name__}")
    try:
        signals.done.emit(result)
    except RuntimeError:                                           # the window is already gone
        pass


class UpdateController(QObject):
    stateChanged = Signal()
    available = Signal(object)         # an UpdateInfo, found by a check
    readyToLaunch = Signal(object)     # the verified installer's Path
    progress = Signal(int, int)

    def __init__(self, parent: QObject | None = None, *, check=updater.check_for_update,
                 download=updater.download_update, current: str | None = None,
                 dest: Path | None = None) -> None:
        super().__init__(parent)
        self._check, self._download = check, download
        self.current = current if current is not None else updater.__version__
        self._dest = dest
        self.state = "idle"
        self.message = ""
        self.info: updater.UpdateInfo | None = None
        self.installer: Path | None = None
        self._silent = False
        self._cancel = threading.Event()
        self._signals = _Signals(self)
        self._signals.done.connect(self._finished)

    # -- what the window calls ---------------------------------------------------------------------
    def check(self, silent: bool = False) -> bool:
        """Look for a newer release. ``silent``: a background check - no "up to date" or error text is
        wanted by the caller, only :attr:`available`. False if one is already running."""
        if self.state in ("checking", "downloading"):
            return False
        self._silent = silent
        self._set("checking", "" if silent else "Checking…")
        self._start(lambda: self._check(self.current, cancelled=self._cancel.is_set), "check")
        return True

    def install(self) -> bool:
        """Download and verify the release found by the last check, then announce :attr:`readyToLaunch`."""
        if self.state == "ready" and self.installer is not None:
            self.readyToLaunch.emit(self.installer)            # pressed again after a job finished
            return True
        if self.state != "available" or self.info is None:
            return False
        info = self.info
        dest = self._dest or Path(tempfile.gettempdir()) / "ExtremeCompressor-update"
        self._set("downloading", f"Downloading {info.version}…")

        def work():
            return self._download(info, dest, progress=lambda done, total: self.progress.emit(done, total),
                                  cancelled=self._cancel.is_set)
        self._start(work, "download")
        return True

    def cancel(self) -> None:
        """Stop whatever is running (the window is closing). The thread notices within one read."""
        self._cancel.set()

    def due(self) -> bool:
        return updater.due(QSettings().value(LAST_CHECK_KEY))

    # -- internals ---------------------------------------------------------------------------------
    def _start(self, fn: Callable[[], object], kind: str) -> None:
        threading.Thread(target=_run, args=(fn, kind, self._signals), daemon=True,
                         name=f"update-{kind}").start()

    def _set(self, state: str, message: str) -> None:
        self.state, self.message = state, message
        self.stateChanged.emit()

    def _finished(self, result) -> None:
        kind, payload, error = result
        if error is not None:
            self._set("error", "" if (self._silent and kind == "check") else error)
            return
        if kind == "check":
            QSettings().setValue(LAST_CHECK_KEY, time.time())      # only an answered check counts as a look
            if payload is None:
                self.info = None
                self._set("uptodate", "" if self._silent else f"You have the latest version ({self.current}).")
            else:
                self.info = payload
                self._set("available", f"Version {payload.version} is available.")
                self.available.emit(payload)
        else:
            self.installer = payload
            self._set("ready", f"Version {self.info.version if self.info else ''} is downloaded and verified.")
            self.readyToLaunch.emit(payload)
