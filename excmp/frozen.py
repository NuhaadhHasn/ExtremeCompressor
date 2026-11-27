"""Run-time setup that only a frozen (PyInstaller) build needs.

The bundled Precomp is a C++ program that imports ``MSVCP140.dll`` and ``VCRUNTIME140.dll``. The frozen app carries
those (Qt's own copies sit in ``_internal\\PySide6``), but a tool started from a folder of its own finds only
the system's. The window works by accident, because PySide6 puts its folder on ``PATH`` and children inherit it;
``excmp.exe`` never imports PySide6, so on a machine without the Visual C++ redistributable Precomp could not even
start, and Extreme, Insane and the restore of any archive that used Precomp would fail.

So both entry points call :func:`prepare_environment` first: it APPENDS the folders that hold those runtime DLLs to
``PATH``. Appended, so a DLL the system has still wins and nothing here can shadow it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Looked for in each folder below; a folder is only added if it holds one.
_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll")
_SUBFOLDERS = ("", "PySide6", "shiboken6")


def prepare_environment() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).parent / "_internal")
    current = os.environ.get("PATH", "")
    have = {os.path.normcase(p) for p in current.split(os.pathsep) if p}
    add = []
    for sub in _SUBFOLDERS:
        folder = base / sub if sub else base
        try:
            present = {f.name.lower() for f in folder.iterdir() if f.is_file()}
        except OSError:
            continue
        if present & set(_RUNTIME_DLLS) and os.path.normcase(str(folder)) not in have:
            add.append(str(folder))
            have.add(os.path.normcase(str(folder)))
    if add:
        os.environ["PATH"] = os.pathsep.join([p for p in [current] if p] + add)
