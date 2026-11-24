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
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Signal

from excmp import updater

LAST_CHECK_KEY = "updates/last_check"
AUTO_KEY = "settings/update_check"


class _Signals(QObject):
    done = Signal(object)          # (kind, payload)


class _Call(QRunnable):
    def __init__(self, fn: Callable[[], object], kind: str, signals: _Signals) -> None:
        super().__init__()
        self._fn, self._kind, self._signals = fn, kind, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = (self._kind, self._fn(), None)
        except updater.UpdateError as exc:
            result = (self._kind, None, str(exc))
        except Exception as exc:                                   # noqa: BLE001 - never let a thread die silently
            result = (self._kind, None, f"unexpected error: {exc}")
        self._signals.done.emit(result)


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
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
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
        QSettings().setValue(LAST_CHECK_KEY, time.time())
        self._pool.start(_Call(lambda: self._check(self.current), "check", self._signals))
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
            return self._download(info, dest, progress=lambda done, total: self.progress.emit(done, total))
        self._pool.start(_Call(work, "download", self._signals))
        return True

    def due(self) -> bool:
        return updater.due(QSettings().value(LAST_CHECK_KEY))

    # -- internals ---------------------------------------------------------------------------------
    def _set(self, state: str, message: str) -> None:
        self.state, self.message = state, message
        self.stateChanged.emit()

    def _finished(self, result) -> None:
        kind, payload, error = result
        if error is not None:
            self._set("error", "" if (self._silent and kind == "check") else error)
            return
        if kind == "check":
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
