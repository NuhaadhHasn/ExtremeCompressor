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


def _pascal_function(iss: str, name: str) -> str:
    m = re.search(rf"^function {name}\(.*?^end;", iss, re.M | re.S)
    assert m, name
    return m.group(0)


def test_setup_and_uninstall_each_ask_only_their_own_silent_question():
    """Inno Setup raises a run-time error if Setup code calls `UninstallSilent` (or the uninstaller calls
    `WizardSilent`). The first 0.1.2 build asked both in one expression: the uninstaller crashed at start
    ("Cannot call WizardSilent function during Uninstall", exit 1), and an interactive Setup would have crashed
    on `UninstallSilent` the same way. Only a real uninstall found it, so it is pinned here."""
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    shared = _pascal_function(iss, "WindowGone")
    assert "WizardSilent" not in shared and "UninstallSilent" not in shared      # it is told, not left to ask
    setup = _pascal_function(iss, "InitializeSetup")
    uninstall = _pascal_function(iss, "InitializeUninstall")
    assert "WizardSilent" in setup and "UninstallSilent" not in setup
    assert "UninstallSilent" in uninstall and "WizardSilent" not in uninstall


def test_a_silent_run_never_waits_for_a_click():
    """`/SUPPRESSMSGBOXES` does not silence a box the script raises itself (seen on the first 0.1.2 build: a silent
    uninstall with the window open waited 20 s and then sat on "ExtremeCompressor is running" for ever, and the
    in-app update's Setup would have done the same). A silent run must answer "no" without showing anything."""
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    shared = _pascal_function(iss, "WindowGone")
    assert "MsgBox(" in shared, "the interactive refusal message is gone"
    assert re.search(r"if\s+\(?not Result\)?\s+and\s+\(?not Silent\)?\s+then\s+MsgBox\(", shared), \
        "MsgBox must only be shown when the run is not silent"


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
