"""E3 review: an uninstall while the window is open left every file behind and removed the
uninstall entry (a silent uninstall returned 0). Inno Setup's `AppMutex` makes both Setup and the
uninstaller see a running copy; this is the mutex the window holds for it."""

from __future__ import annotations

import ctypes
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a Windows named mutex")


def _open(name: str) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenMutexW(0x00100000, 0, name)         # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(handle)
    return bool(handle)


def test_marking_the_window_as_running_makes_a_named_mutex_another_process_can_see():
    from gui import singleinstance as si
    assert si.mark_running() is True
    assert _open(si.RUNNING_MUTEX)
    assert si.mark_running() is True                         # asking twice is harmless


def test_the_installer_watches_the_same_mutex():
    from gui import singleinstance as si
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r"^\s*RunningMutex = '([^']+)';", iss, re.M)
    assert m and m.group(1) == si.RUNNING_MUTEX
    assert not re.search(r"^AppMutex=", iss, re.M)             # the directive checks once, at once
    assert "InitializeSetup" in iss and "InitializeUninstall" in iss and "Sleep(250)" in iss


def test_the_window_marks_itself_running_at_start_up():
    import inspect
    import gui.app as app
    assert "mark_running" in inspect.getsource(app.main)


def test_releasing_the_marker_hides_the_mutex_and_marking_again_restores_it():
    """The update hand-off: the window lets go of the mutex BEFORE it starts the installer. A
    silent Setup checks `AppMutex` once, ~0.5 s in, and exits 1 if a window still holds it - which
    is what happened when the window closed itself only after launching the installer."""
    from gui import singleinstance as si
    assert si.mark_running() is True
    assert si.release_running() is True
    assert not _open(si.RUNNING_MUTEX)
    assert si.release_running() is False                      # nothing left to release
    assert si.mark_running() is True and _open(si.RUNNING_MUTEX)
