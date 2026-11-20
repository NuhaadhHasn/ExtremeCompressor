"""E3: the build inputs for a frozen, installable ExtremeCompressor.

These check the build INPUTS without running PyInstaller or Inno Setup (a real build is checked by
``packaging/smoke_test.py``, which needs one and writes the Explorer-menu keys, so it is not part of
the suite). It is the part that goes wrong silently:

* the roadmap's tuned exclude list names `QtSvg` and `QtNetwork`, but the app imports `QtSvg` for its
  icons and the I5 single-instance code imports `QtNetwork`: excluding them would give a build that
  dies at start-up. So the test reads the real imports and fails if the spec excludes a module the
  code uses;
* the spec never enables UPX (verified to *increase* antivirus detections, roadmap E4);
* both programs exist (the window and the console tool the installer runs), and the file paths the
  spec and the installer name exist.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

import excmp

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
SPEC = PKG / "ExtremeCompressor.spec"
ISS = PKG / "installer.iss"


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _literal(name: str):
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not assigned in {SPEC.name}")


def _qt_modules_imported() -> set[str]:
    """Every ``PySide6.QtXxx`` the code imports, by reading the imports (not by grepping text)."""
    found: set[str] = set()
    files = [*ROOT.joinpath("gui").rglob("*.py"), *ROOT.joinpath("excmp").rglob("*.py"),
             ROOT / "run_gui.py", PKG / "entry_cli.py"]
    for path in files:
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("PySide6."):
                    found.add(node.module.split(".")[1])
                elif node.module == "PySide6":
                    found.update(a.name for a in node.names if a.name.startswith("Qt"))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("PySide6."):
                        found.add(a.name.split(".")[1])
    return found


# -- the files exist and say what they should -----------------------------------

def test_the_build_inputs_exist():
    for p in (SPEC, ISS, PKG / "entry_cli.py", PKG / "build.cmd", PKG / "README.md", ROOT / "run_gui.py"):
        assert p.is_file(), p


def test_the_spec_is_valid_python():
    compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec")


def test_the_spec_does_not_exclude_a_qt_module_the_code_imports():
    """The roadmap's list, followed literally, would break the app (QtSvg, QtNetwork)."""
    excluded = {m.split(".")[1] for m in _literal("EXCLUDES") if m.startswith("PySide6.")}
    used = _qt_modules_imported()
    assert used, "the scan found no Qt imports at all: it is broken"
    assert not (excluded & used), f"excluded but imported: {sorted(excluded & used)}"


@pytest.mark.parametrize("module", ["QtQml", "QtQuick", "QtPdf", "QtOpenGL", "QtOpenGLWidgets", "QtDBus"])
def test_the_modules_the_app_never_uses_are_excluded(module):
    """The measured saving (122 MB -> 71 MB on disk) comes from these."""
    assert f"PySide6.{module}" in _literal("EXCLUDES")
    assert module not in _qt_modules_imported()


def test_the_spec_never_turns_upx_on():
    assert not re.search(r"upx\s*=\s*True", SPEC.read_text(encoding="utf-8"))


def test_the_spec_builds_a_folder_not_a_single_file():
    """--onefile re-extracts the whole bundle to temp on every launch and trips antivirus."""
    text = SPEC.read_text(encoding="utf-8")
    assert "COLLECT(" in text and "exclude_binaries=True" in text


def test_the_window_has_no_console_and_the_tool_has_one():
    text = SPEC.read_text(encoding="utf-8")
    assert re.search(r'name="ExtremeCompressor",[^)]*console=False', text, re.S)
    assert re.search(r'name="excmp",[^)]*console=True', text, re.S)


def test_the_unused_big_files_are_dropped():
    assert {"opengl32sw.dll", "qdirect2d.dll"} <= set(_literal("DROP_FILES"))


def test_the_assets_the_app_reads_are_bundled():
    assert (ROOT / "assets" / "icons").is_dir()
    assert '"assets"' in SPEC.read_text(encoding="utf-8")


# -- the installer script ---------------------------------------------------------

def _iss() -> str:
    return ISS.read_text(encoding="utf-8")


def test_the_installer_needs_no_administrator():
    assert re.search(r"^PrivilegesRequired=lowest$", _iss(), re.M)
    assert "{autopf}" in _iss()


def test_the_installer_has_a_stable_app_id():
    m = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}$", _iss(), re.M)
    assert m, "AppId must be a literal GUID: it is how a later installer finds this one"
    assert re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", m.group(1))


def test_the_installer_version_defaults_to_the_packages():
    assert f'#define AppVersion "{excmp.__version__}"' in _iss()


def test_the_menu_is_an_opt_in_task_and_is_removed_on_uninstall():
    text = _iss()
    run = re.search(r"\[Run\](.*?)(?=^\[)", text, re.S | re.M).group(1)
    assert re.search(r'excmp\.exe"; Parameters: "shell install".*Tasks: contextmenu', run)
    assert re.search(r'^\[UninstallRun\]\s*\nFilename: "\{app\}\\excmp\.exe"; Parameters: "shell uninstall"',
                     text, re.M)


def test_the_installer_ships_what_the_spec_builds():
    text = _iss()
    assert r"..\dist\ExtremeCompressor\*" in text
    assert "recursesubdirs" in text


def test_the_build_script_runs_both_tools_in_order():
    cmd = (PKG / "build.cmd").read_text(encoding="utf-8").lower()
    assert cmd.index("pyinstaller") < cmd.index("iscc")


# -- the console entry point is real ------------------------------------------------

def test_the_console_entry_point_runs_the_cli():
    out = subprocess.run([sys.executable, str(PKG / "entry_cli.py"), "--help"], capture_output=True,
                         text=True, timeout=60, cwd=str(ROOT))
    assert out.returncode == 0 and "shell" in out.stdout and "compress" in out.stdout
