"""Fixes from the adversarial review of the bundled-tools change (2026-11-27): what a machine with ONLY the
bundled tools gets, as opposed to what this developer machine happens to have."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from excmp import engine, tools, toolfetch
from excmp.stages.base import StageContext

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))


# --- 1. RAR and friends with only the Extra 7za ----------------------------------------------------

def _only_extra(monkeypatch, name="7za.exe"):
    info = tools.ToolInfo("7z", f"C:/app/_internal/tools/bin/7z/26.06/{name}", "7-Zip (a) 26.06")
    monkeypatch.setattr(engine, "find_tools", lambda *a, **k: {"7z": info})
    return info


@pytest.mark.parametrize("suffix", ["rar", "iso", "msi", "wim", "lzh", "arj", "RAR"])
def test_7za_cannot_open_these_and_says_so(suffix):
    info = tools.ToolInfo("7z", "C:/x/7za.exe", "")
    assert tools.needs_full_7zip(Path(f"a.{suffix}"), info)


@pytest.mark.parametrize("suffix", ["7z", "zip", "tar", "gz", "tgz", "bz2", "xz", "zst", "cab", "excmp", "001", "docx"])
def test_7za_opens_these(suffix):
    assert not tools.needs_full_7zip(Path(f"a.{suffix}"), tools.ToolInfo("7z", "C:/x/7za.exe", ""))


def test_a_full_7zip_opens_everything():
    assert not tools.needs_full_7zip(Path("a.rar"), tools.ToolInfo("7z", "C:/Program Files/7-Zip/7z.exe", ""))
    assert not tools.needs_full_7zip(Path("a.rar"), None)


def test_listing_a_rar_without_a_full_7zip_is_a_clear_message_not_damage(monkeypatch, tmp_path):
    _only_extra(monkeypatch)
    rar = tmp_path / "x.rar"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\0" * 64)
    with pytest.raises(engine.ContainerError, match=r"full 7-Zip") as err:
        engine._list_foreign(rar, StageContext(temp_dir=tmp_path / "t"))
    assert "damaged" not in str(err.value)


def test_extracting_a_rar_without_a_full_7zip_is_a_clear_message(monkeypatch, tmp_path):
    _only_extra(monkeypatch)
    rar = tmp_path / "x.rar"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\0" * 64)
    with pytest.raises(Exception, match=r"full 7-Zip"):
        engine._extract_foreign(rar, tmp_path / "out", StageContext(temp_dir=tmp_path / "t"), None)


# --- 2. the VC++ runtime Precomp needs ---------------------------------------------------------------

def test_a_frozen_app_hands_its_runtime_folders_to_the_tools_it_starts(monkeypatch, tmp_path):
    from excmp import frozen
    base = tmp_path / "_internal"
    for sub in ("", "PySide6", "shiboken6", "empty"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "vcruntime140.dll").write_bytes(b"x")
    (base / "PySide6" / "msvcp140.dll").write_bytes(b"x")
    (base / "shiboken6" / "MSVCP140.dll").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(base), raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    frozen.prepare_environment()
    frozen.prepare_environment()                                   # twice is harmless
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == r"C:\Windows\System32"                      # appended: the system's own DLLs still win
    assert str(base) in parts and str(base / "PySide6") in parts and str(base / "shiboken6") in parts
    assert str(base / "empty") not in parts
    assert len(parts) == len(set(parts))


def test_a_source_checkout_leaves_the_path_alone(monkeypatch):
    from excmp import frozen
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("PATH", "A")
    frozen.prepare_environment()
    assert os.environ["PATH"] == "A"


@pytest.mark.parametrize("entry", ["packaging/entry_cli.py", "run_gui.py"])
def test_both_entry_points_prepare_the_environment(entry):
    text = (ROOT / entry).read_text(encoding="utf-8")
    assert "prepare_environment" in text
    assert text.index("prepare_environment()") < text.index("main()")


# --- 3. discovery -----------------------------------------------------------------------------------

def _disc(monkeypatch, tmp_path, *, banner, pinned, on_path=None, default=False):
    d = tmp_path / "7-Zip"
    d.mkdir(exist_ok=True)
    exe = d / "7z.exe"
    exe.write_bytes(b"x")
    monkeypatch.setitem(tools.CANDIDATES, "7z", [str(exe)] if default else [])
    monkeypatch.setattr(tools, "_pinned_tool", lambda n: "BUNDLED-7za" if (pinned and n == "7z") else None)
    monkeypatch.setattr(tools, "_probe_version", lambda n, p: banner)
    monkeypatch.setattr(tools.shutil, "which", lambda n: str(exe) if on_path else None)
    tools._SYSTEM_VERSION.clear()
    return str(exe)


def test_a_current_7zip_on_the_path_still_wins(monkeypatch, tmp_path):
    exe = _disc(monkeypatch, tmp_path, banner="7-Zip 26.02 (x64)", pinned=True, on_path=True)
    assert tools.find_tools()["7z"].path == exe


def test_an_old_7zip_on_the_path_loses_to_the_bundled_one(monkeypatch, tmp_path):
    _disc(monkeypatch, tmp_path, banner="7-Zip 24.09 (x64)", pinned=True, on_path=True)
    assert tools.find_tools()["7z"].path == "BUNDLED-7za"


def test_a_7zip_whose_version_cannot_be_read_loses_to_a_verified_bundled_copy(monkeypatch, tmp_path):
    _disc(monkeypatch, tmp_path, banner="", pinned=True, default=True)
    assert tools.find_tools()["7z"].path == "BUNDLED-7za"


def test_a_7zip_whose_version_cannot_be_read_is_used_when_nothing_is_bundled(monkeypatch, tmp_path):
    exe = _disc(monkeypatch, tmp_path, banner="", pinned=False, default=True)
    assert tools.find_tools()["7z"].path == exe


def test_the_bundled_folder_is_never_mistaken_for_a_system_copy(monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    exe = root / "7z" / "26.06" / "7za.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(root))
    monkeypatch.setitem(tools.CANDIDATES, "7z", [])
    monkeypatch.setattr(tools.shutil, "which", lambda n: str(exe))     # PATH happens to name the bundled exe
    monkeypatch.setattr(tools, "_probe_version", lambda n, p: "7-Zip (a) 26.06")
    assert tools._usable_system_copy("7z", []) is None


# --- 4. staging is checked again at build time ------------------------------------------------------

def test_the_staged_folder_is_verified_before_pyinstaller_trusts_it(tmp_path, monkeypatch):
    import stage_tools
    from dataclasses import replace
    import hashlib
    payload = b"MZ staged"
    spec = toolfetch.ToolSpec(
        name="fakecodec", version="1.0", url="https://example.invalid/x", sha256="0" * 64, size=1,
        exe_relpath="fakecodec.exe", license="MIT",
        exe_dir_sha256=(("fakecodec.exe", hashlib.sha256(payload).hexdigest()),))
    monkeypatch.setitem(toolfetch.TOOL_MANIFEST, "fakecodec", spec)
    exe = tmp_path / "bundled" / "fakecodec" / "1.0" / "fakecodec.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(payload)
    stage_tools.verify_staged(tmp_path / "bundled", ["fakecodec"])
    exe.write_bytes(b"stale from another commit")
    with pytest.raises(stage_tools.StageError):
        stage_tools.verify_staged(tmp_path / "bundled", ["fakecodec"])
    with pytest.raises(stage_tools.StageError, match="not found"):
        stage_tools.verify_staged(tmp_path / "nowhere", ["fakecodec"])


def test_the_spec_verifies_the_staged_folder_not_just_its_existence():
    spec = (ROOT / "packaging" / "ExtremeCompressor.spec").read_text(encoding="utf-8")
    assert "verify_staged" in spec


def test_the_smoke_test_checks_the_tools_inside_the_built_app():
    smoke = (ROOT / "packaging" / "smoke_test.py").read_text(encoding="utf-8")
    assert "tools\\bin" in smoke or "tools/bin" in smoke
    assert "insane" in smoke.lower()


# --- 5. `excmp tools` --------------------------------------------------------------------------------

def test_the_tools_command_lists_each_tool_and_where_it_came_from(capsys, monkeypatch, tmp_path):
    from excmp import cli
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(tmp_path / "bundle"))
    inside = tmp_path / "bundle" / "precomp" / "0.4.7" / "windows" / "precomp.exe"
    monkeypatch.setattr(cli, "find_tools", lambda *a, **k: {
        "precomp": tools.ToolInfo("precomp", str(inside), "0.4.7"),
        "7z": tools.ToolInfo("7z", "C:/Program Files/7-Zip/7z.exe", "7-Zip 26.02"),
        "srep": None})
    assert cli.main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "precomp" in out and "included with the app" in out
    assert "7-Zip 26.02" in out and "srep" in out and "not found" in out


# --- 6. the shipped texts ----------------------------------------------------------------------------

def test_the_zpaqfranz_credits_are_the_ones_of_the_pinned_release():
    """The first copy came from upstream's current branch (entries up to Mbed TLS, added in 65.x), not from tag 64.8."""
    text = (ROOT / "licenses" / "tools" / "zpaqfranz" / "COPYING.txt").read_text(encoding="utf-8", errors="replace")
    assert "Mbed TLS" not in text and "LZAV" not in text
    notes = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "Mbed TLS" not in notes and "LZAV" not in notes


def test_the_7zip_folder_carries_the_lgpl_text_its_licence_refers_to():
    text = (ROOT / "licenses" / "tools" / "7zip" / "COPYING.LGPL").read_text(encoding="utf-8", errors="replace")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text.upper()


def test_the_notices_do_not_overstate_what_7za_does():
    notes = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "reads and\nwrites 7z, zip, tar, gzip, bzip2, xz, zstd and cab" not in notes.replace("\r\n", "\n")
    assert "reads zstd and cab" in notes.replace("\r\n", "\n").replace("\n", " ")


def test_the_build_script_has_no_control_characters():
    raw = (ROOT / "packaging" / "build.cmd").read_bytes()
    assert not [b for b in raw if b < 32 and b not in (9, 10, 13)]
