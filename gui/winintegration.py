"""Windows shell niceties: taskbar progress and completion toasts.

Everything in here is optional and defensive. Qt 6 dropped
``QWinTaskbarButton``, so taskbar progress means talking to ``ITaskbarList3``
through COM, and toasts mean the ``Windows-Toasts`` package - two things that
can be absent, blocked by policy, or simply different on another Windows
build. None of that is allowed to stop an archiver from archiving, so every
entry point degrades to a silent no-op.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import HRESULT, c_int, c_ulonglong
from ctypes.wintypes import HWND
from pathlib import Path
from typing import Callable

APP_ID = "NuhaadhHasn.ExtremeCompressor"

# ITaskbarList3::SetProgressState flags
TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

try:  # pragma: no cover - platform glue
    import comtypes.client as _cc
    from comtypes import COMMETHOD, GUID, IUnknown

    class _ITaskbarList3(IUnknown):
        """Hand-declared vtable. Order matters: the methods below must appear
        exactly as ITaskbarList -> ITaskbarList2 -> ITaskbarList3 declare
        them, or the wrong slot gets called."""

        _iid_ = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")
        _methods_ = [
            COMMETHOD([], HRESULT, "HrInit"),
            COMMETHOD([], HRESULT, "AddTab", (["in"], HWND, "hwnd")),
            COMMETHOD([], HRESULT, "DeleteTab", (["in"], HWND, "hwnd")),
            COMMETHOD([], HRESULT, "ActivateTab", (["in"], HWND, "hwnd")),
            COMMETHOD([], HRESULT, "SetActiveAlt", (["in"], HWND, "hwnd")),
            COMMETHOD([], HRESULT, "MarkFullscreenWindow",
                      (["in"], HWND, "hwnd"), (["in"], c_int, "fFullscreen")),
            COMMETHOD([], HRESULT, "SetProgressValue",
                      (["in"], HWND, "hwnd"),
                      (["in"], c_ulonglong, "ullCompleted"),
                      (["in"], c_ulonglong, "ullTotal")),
            COMMETHOD([], HRESULT, "SetProgressState",
                      (["in"], HWND, "hwnd"), (["in"], c_int, "tbpFlags")),
        ]

    _CLSID_TASKBARLIST = GUID("{56FDF344-FD6D-11D0-958A-006097C9A090}")
except Exception:  # pragma: no cover - comtypes missing or not Windows
    _cc = None
    _ITaskbarList3 = None
    _CLSID_TASKBARLIST = None


def set_app_id(app_id: str = APP_ID) -> None:
    """Give the process an explicit AppUserModelID.

    Without one, Windows attributes the taskbar button and any toast to
    ``python.exe`` - the app looks like it belongs to somebody else.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


class TaskbarProgress:
    """Progress on the taskbar button, or nothing at all."""

    def __init__(self, hwnd: int | None = None) -> None:
        self._hwnd = HWND(hwnd) if hwnd else None
        self._impl = None
        if _cc is None or not self._hwnd:
            return
        try:
            self._impl = _cc.CreateObject(
                _CLSID_TASKBARLIST, interface=_ITaskbarList3)
            self._impl.HrInit()
        except Exception:
            self._impl = None

    @property
    def available(self) -> bool:
        return self._impl is not None

    def set_progress(self, percent: float) -> None:
        if self._impl is None:
            return
        try:
            self._impl.SetProgressState(self._hwnd, TBPF_NORMAL)
            self._impl.SetProgressValue(self._hwnd, int(max(0, min(100, percent))), 100)
        except Exception:
            self._impl = None

    def set_state(self, flag: int) -> None:
        if self._impl is None:
            return
        try:
            self._impl.SetProgressState(self._hwnd, flag)
        except Exception:
            self._impl = None

    def clear(self) -> None:
        self.set_state(TBPF_NOPROGRESS)


class Notifier:
    """Completion toast with an "Open folder" button, when possible."""

    def __init__(self, app_name: str = "ExtremeCompressor") -> None:
        self._toaster = None
        self._toast_cls = None
        self._button_cls = None
        try:  # pragma: no cover - depends on the Windows notification stack
            from windows_toasts import Toast, ToastButton, WindowsToaster

            self._toaster = WindowsToaster(app_name)
            self._toast_cls = Toast
            self._button_cls = ToastButton
        except Exception:
            self._toaster = None

    @property
    def available(self) -> bool:
        return self._toaster is not None

    def notify(self, title: str, body: str, open_path: Path | None = None,
               on_open: Callable[[Path], None] | None = None) -> bool:
        """Returns True if a toast was actually shown."""
        if self._toaster is None or self._toast_cls is None:
            return False
        try:
            toast = self._toast_cls()
            toast.text_fields = [title, body]
            if open_path is not None and self._button_cls is not None:
                toast.AddAction(self._button_cls("Open folder", "open"))

                def _activated(_args, path=Path(open_path)) -> None:
                    (on_open or open_in_explorer)(path)

                toast.on_activated = _activated
            self._toaster.show_toast(toast)
            return True
        except Exception:
            return False


def open_in_explorer(path: Path) -> None:
    """Reveal a file, or open a directory, in Explorer."""
    path = Path(path)
    try:
        if path.is_file():
            # /select, needs a single argument string, not a list
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", "explorer.exe", f'/select,"{path}"', None, 1)
        else:
            target = path if path.is_dir() else path.parent
            os.startfile(str(target))  # noqa: S606 - a user-chosen directory
    except Exception:
        pass
