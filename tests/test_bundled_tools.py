"""The installer carries the external tools, so an installed app has what a source checkout has and
never downloads anything (the first release had none of them: Insane could not run, and the tool
downloader did not even list zpaqfranz).

What is pinned here: which tools ship, that every one is hash-pinned and openly licensed, that the
staging step refuses a copy that does not match its pin, that discovery prefers a good system 7-Zip
(RAR support) and falls back to the bundled one, and that the build wires it all together."""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from excmp import toolfetch, tools

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

#: Open-source licences the project allows to be bundled (CLAUDE.md: the OSI rule is back in force).
OPEN = ("MIT", "Apache-2.0", "LGPL-2.1", "GPL-2.0", "GPL-3.0", "BSD-3-Clause")


def test_the_bundle_is_exactly_the_tools_the_engine_runs():
    assert set(toolfetch.BUNDLED) == {"7z", "precomp", "zpaqfranz", "flac", "balrogg"}
    for never in ("srep", "qpdf", "oodle", "xtool"):
        assert never not in toolfetch.BUNDLED       # not OSI / never invoked (87 MB)


@pytest.mark.parametrize("name", toolfetch.BUNDLED)
def test_every_bundled_tool_is_pinned_and_openly_licensed(name):
    spec = toolfetch.TOOL_MANIFEST[name]
    assert spec.exe_dir_sha256, "an unpinned tool cannot be verified, so it cannot ship"
    assert re.fullmatch(r"[0-9a-f]{64}", spec.sha256)
    assert any(tag in spec.license for tag in OPEN), spec.license
    assert "non-commercial" not in spec.license.lower()


@pytest.mark.parametrize("name,files", [
    ("7zip", ["License.txt"]), ("precomp", ["readme.txt", "LICENSE-Apache-2.0.txt"]),
    ("zpaqfranz", ["LICENSE.txt"]), ("flac", ["COPYING.GPL", "COPYING.Xiph"]),
    ("balrogg", ["COPYING.txt"])])
def test_every_bundled_tool_has_its_licence_text_in_the_repo(name, files):
    for f in files:
        text = (ROOT / "licenses" / "tools" / name / f).read_text(encoding="utf-8", errors="replace")
        assert len(text) > 500


def test_the_7zip_licence_we_ship_has_no_unrar_clause():
    """The bundled 7za.exe is the 'Extra' build: it holds no RAR code, so the unRAR restriction of the
    full 7-Zip does not apply (and the notices say this is why that build was chosen)."""
    text = (ROOT / "licenses" / "tools" / "7zip" / "License.txt").read_text(encoding="utf-8", errors="replace")
    assert "unrar" not in text.lower()


def test_the_notices_name_every_bundled_tool_as_bundled():
    notes = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    for heading in ("7-Zip", "Precomp", "zpaqfranz", "FLAC", "balrogg"):
        m = re.search(rf"^### {heading}\b.*$", notes, re.M)
        assert m, heading
        assert "bundled" in m.group(0).lower(), m.group(0)
    assert "licence NOT established" not in notes and "non-commercial" not in notes.lower()


def test_the_precomp_pin_no_longer_claims_a_non_commercial_licence():
    assert "Apache" in toolfetch.TOOL_MANIFEST["precomp"].license


# --- staging ---------------------------------------------------------------------------------

def _fake_spec(tmp_path: Path, name="fakecodec", payload=b"MZ fake exe"):
    """A spec whose source copy lives in tmp_path/<name>/1.0/ (the same nested layout the app reads)."""
    exe = tmp_path / "src" / name / "1.0" / "bin" / f"{name}.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(payload)
    return toolfetch.ToolSpec(
        name=name, version="1.0", url="https://example.invalid/x.zip", sha256="0" * 64, size=1,
        exe_relpath=f"bin/{name}.exe", license="MIT",
        exe_dir_sha256=((f"{name}.exe", hashlib.sha256(payload).hexdigest()),))


def test_staging_copies_a_verified_tool_and_it_verifies_at_the_destination(tmp_path, monkeypatch):
    import stage_tools
    spec = _fake_spec(tmp_path)
    monkeypatch.setitem(toolfetch.TOOL_MANIFEST, spec.name, spec)
    dest = tmp_path / "out"
    staged = stage_tools.stage([spec.name], source_root=tmp_path / "src", dest=dest)
    assert staged == [spec.name]
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(dest))
    assert toolfetch.verify_installed(spec)


def test_staging_refuses_a_copy_that_does_not_match_its_pin(tmp_path, monkeypatch):
    import stage_tools
    spec = _fake_spec(tmp_path)
    monkeypatch.setitem(toolfetch.TOOL_MANIFEST, spec.name, spec)
    (tmp_path / "src" / spec.name / "1.0" / "bin" / f"{spec.name}.exe").write_bytes(b"tampered")
    with pytest.raises(stage_tools.StageError, match="does not match"):
        stage_tools.stage([spec.name], source_root=tmp_path / "src", dest=tmp_path / "out")
    assert not (tmp_path / "out" / spec.name).exists()          # nothing half-staged


def test_staging_refuses_an_extra_file_beside_the_pinned_ones(tmp_path, monkeypatch):
    import stage_tools
    spec = _fake_spec(tmp_path)
    monkeypatch.setitem(toolfetch.TOOL_MANIFEST, spec.name, spec)
    (tmp_path / "src" / spec.name / "1.0" / "bin" / "version.dll").write_bytes(b"planted")
    with pytest.raises(stage_tools.StageError):
        stage_tools.stage([spec.name], source_root=tmp_path / "src", dest=tmp_path / "out")


def test_staging_a_missing_tool_says_how_to_get_it(tmp_path, monkeypatch):
    import stage_tools
    spec = _fake_spec(tmp_path)
    monkeypatch.setitem(toolfetch.TOOL_MANIFEST, spec.name, replace(spec, version="9.9"))
    with pytest.raises(stage_tools.StageError, match="not found"):
        stage_tools.stage([spec.name], source_root=tmp_path / "src", dest=tmp_path / "out")


# --- discovery -------------------------------------------------------------------------------

def _discovery(monkeypatch, tmp_path, *, system, system_banner, pinned):
    sysexe = tmp_path / "7-Zip" / "7z.exe"
    sysexe.parent.mkdir(parents=True, exist_ok=True)
    sysexe.write_bytes(b"x")
    monkeypatch.setitem(tools.CANDIDATES, "7z", [str(sysexe)] if system else [])
    monkeypatch.setattr(tools, "_pinned_tool", lambda n: "BUNDLED-7za" if (pinned and n == "7z") else None)
    monkeypatch.setattr(tools, "_probe_version", lambda n, p: system_banner if n == "7z" else "")
    monkeypatch.setattr(tools.shutil, "which", lambda n: None)
    return str(sysexe)


def test_a_current_system_7zip_wins_so_rar_still_opens(monkeypatch, tmp_path):
    sysexe = _discovery(monkeypatch, tmp_path, system=True, system_banner="7-Zip 26.02 (x64)", pinned=True)
    assert tools.find_tools()["7z"].path == sysexe


def test_an_old_system_7zip_loses_to_the_bundled_one(monkeypatch, tmp_path):
    _discovery(monkeypatch, tmp_path, system=True, system_banner="7-Zip 24.09 (x64)", pinned=True)
    assert tools.find_tools()["7z"].path == "BUNDLED-7za"


def test_without_a_system_7zip_the_bundled_one_is_used(monkeypatch, tmp_path):
    _discovery(monkeypatch, tmp_path, system=False, system_banner="", pinned=True)
    assert tools.find_tools()["7z"].path == "BUNDLED-7za"


def test_an_old_system_7zip_is_still_used_when_nothing_is_bundled(monkeypatch, tmp_path):
    sysexe = _discovery(monkeypatch, tmp_path, system=True, system_banner="7-Zip 24.09 (x64)", pinned=False)
    assert tools.find_tools()["7z"].path == sysexe              # the floor warning, not a refusal


def test_other_tools_still_prefer_their_pinned_copy(monkeypatch):
    monkeypatch.setattr(tools, "_pinned_tool", lambda n: f"PINNED-{n}" if n == "precomp" else None)
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [__file__])    # an existing 'system' file
    assert tools.find_tools()["precomp"].path == "PINNED-precomp"


# --- the real pins and the build wiring ----------------------------------------------------------

def test_zpaqfranz_is_pinned_to_the_build_every_measurement_used():
    spec = toolfetch.TOOL_MANIFEST["zpaqfranz"]
    assert spec.version == "64.8" and spec.raw and spec.size == 4_288_000
    assert spec.sha256 == "8c8320756bdd489d3f08e070f42d2680892598ee5befafd4880640b9276fa533"
    assert spec.license == "MIT"


def test_the_7zip_pin_is_the_extra_package_and_cannot_be_fetched_at_run_time(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(tmp_path))          # an empty root: nothing installed
    spec = toolfetch.TOOL_MANIFEST["7z"]
    assert spec.bundled_only and spec.exe_relpath == "7za.exe" and spec.version_tuple() >= (26, 2, 0, 1)
    with pytest.raises(toolfetch.FetchError, match="installer"):
        toolfetch.fetch_tool(spec)


def test_the_build_stages_the_tools_before_pyinstaller_and_ships_them():
    cmd = (ROOT / "packaging" / "build.cmd").read_text(encoding="utf-8")
    assert cmd.index("stage_tools.py") < cmd.index("-m PyInstaller")
    spec = (ROOT / "packaging" / "ExtremeCompressor.spec").read_text(encoding="utf-8")
    assert "bundled-tools" in spec and '"tools/bin"' in spec
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r'Source: "\.\.\\licenses\\\*"; DestDir: "\{app\}\\licenses"; Flags: [^\n]*recursesubdirs', iss)


@pytest.mark.skipif(not all((ROOT / "tools" / "bin" / n).is_dir() for n in toolfetch.BUNDLED),
                    reason="needs the developer tool folder (tools/bin)")
def test_staging_the_real_tool_folder_gives_five_runnable_verified_tools(tmp_path, monkeypatch):
    import subprocess

    import stage_tools
    dest = tmp_path / "bundled"
    assert stage_tools.stage(list(toolfetch.BUNDLED), source_root=ROOT / "tools" / "bin", dest=dest) \
        == list(toolfetch.BUNDLED)
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(dest))
    found = tools.find_tools(with_versions=True)
    for name in toolfetch.BUNDLED:
        assert toolfetch.installed_path(toolfetch.TOOL_MANIFEST[name]) is not None, name
        assert found[name] is not None and Path(found[name].path).is_relative_to(dest) or name == "7z", name
    out = subprocess.run([str(dest / "7z" / "26.06" / "7za.exe")], capture_output=True, text=True, timeout=30).stdout
    assert "26.06" in out


def test_the_tools_list_marks_the_copies_that_come_with_the_app(qtbot, monkeypatch, tmp_path):
    from gui.widgets.settings_tab import SettingsTab
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(tmp_path / "bundle"))
    inside = tmp_path / "bundle" / "7z" / "26.06" / "7za.exe"
    outside = tmp_path / "7-Zip" / "7z.exe"
    tab = SettingsTab({"7z": tools.ToolInfo("7z", str(inside), "7-Zip (a) 26.06"),
                       "precomp": tools.ToolInfo("precomp", str(outside), "0.4.7")}, Path("."), shell_supported=False)
    qtbot.addWidget(tab)
    lines = {ln.split()[0]: ln for ln in tab.tools_text().splitlines()}
    assert "included with the app" in lines["7z"]
    assert "included with the app" not in lines["precomp"]
