# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ExtremeCompressor (E3). UNBUILT: see packaging/README.md.

--onedir, never --onefile: a one-file build re-extracts the whole bundle to a temp folder on every
launch and trips antivirus and SmartScreen. Two programs share one folder:

    ExtremeCompressor.exe   the window (no console)        from run_gui.py
    excmp.exe               the console tool               from packaging/entry_cli.py
                            (the installer runs `excmp.exe shell install` to add the Explorer menu)

The exclude list is the roadmap's, MINUS the two modules the code now uses: QtSvg (the icons) and
QtNetwork (I5's single-instance pipe). tests/test_e3_packaging_files.py reads the real imports and
fails if this list ever names a module the code needs. Never UPX (it increases detections).
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller

EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtDBus",
    "tkinter",          # only the superseded main.py prototype uses it
]

def _par2_binaries():
    """par2.exe (par2cmdline-turbo's wheel) is a plain executable, not an import, so PyInstaller does
    not find it. excmp/recovery.py looks for it at <bundle>/par2/binaries/par2.exe."""
    import importlib.util
    spec = importlib.util.find_spec("par2")
    folders = list(spec.submodule_search_locations or ()) if spec else []
    found = [(str(Path(f) / "binaries" / "par2.exe"), "par2/binaries")
             for f in folders if (Path(f) / "binaries" / "par2.exe").exists()]
    if not found:
        raise SystemExit("par2.exe not found: pip install -r requirements.txt first")
    return found


#: Big or useless files PyInstaller's Qt hook collects anyway (measured 122 MB -> 71 MB on disk).
DROP_FILES = ["opengl32sw.dll", "qdirect2d.dll"]


def _keep(entry):
    name = entry[0].replace("\\", "/").lower()
    return Path(name).name not in DROP_FILES and "/translations/" not in "/" + name


def _analysis(script):
    a = Analysis(  # noqa: F821
        [str(script)], pathex=[str(ROOT)],
        binaries=_par2_binaries(),
        datas=[(str(ROOT / "assets"), "assets")],
        hiddenimports=[], excludes=EXCLUDES, noarchive=False)
    a.binaries = [b for b in a.binaries if _keep(b)]
    a.datas = [d for d in a.datas if _keep(d)]
    return a


a_gui = _analysis(ROOT / "run_gui.py")
a_cli = _analysis(ROOT / "packaging" / "entry_cli.py")
MERGE((a_gui, "ExtremeCompressor", "ExtremeCompressor"), (a_cli, "excmp", "excmp"))  # noqa: F821

pyz_gui = PYZ(a_gui.pure)  # noqa: F821
exe_gui = EXE(  # noqa: F821
    pyz_gui, a_gui.scripts, [], exclude_binaries=True,
    name="ExtremeCompressor", console=False, upx=False)

pyz_cli = PYZ(a_cli.pure)  # noqa: F821
exe_cli = EXE(  # noqa: F821
    pyz_cli, a_cli.scripts, [], exclude_binaries=True,
    name="excmp", console=True, upx=False)

coll = COLLECT(  # noqa: F821
    exe_gui, a_gui.binaries, a_gui.datas,
    exe_cli, a_cli.binaries, a_cli.datas,
    strip=False, upx=False, name="ExtremeCompressor")
