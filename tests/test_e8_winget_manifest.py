"""E8: the winget manifest generator (tools/make_winget_manifest.py)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHA = "ab" * 32


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("make_winget_manifest", ROOT / "tools" / "make_winget_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_three_files_with_the_right_names_and_identity(tool):
    files = tool.render("0.2.0", SHA, "2026-11-25")
    assert sorted(files) == ["NuhaadhHasn.ExtremeCompressor.installer.yaml", "NuhaadhHasn.ExtremeCompressor.locale.en-US.yaml",
                             "NuhaadhHasn.ExtremeCompressor.yaml"]
    for text in files.values():
        assert "PackageIdentifier: NuhaadhHasn.ExtremeCompressor\n" in text and "PackageVersion: 0.2.0\n" in text
        assert "ManifestVersion: 1.9.0\n" in text


def test_the_installer_points_only_at_this_projects_release_with_an_uppercase_hash(tool):
    text = tool.render("0.2.0", SHA, "2026-11-25")["NuhaadhHasn.ExtremeCompressor.installer.yaml"]
    assert ("InstallerUrl: https://github.com/NuhaadhHasn/ExtremeCompressor/releases/download/v0.2.0/"
            "ExtremeCompressor-0.2.0-setup.exe\n") in text
    assert f"InstallerSha256: {SHA.upper()}\n" in text
    assert "InstallerType: inno\n" in text and "Scope: user\n" in text      # per user, like the installer


@pytest.mark.parametrize("version", ["", "v0.2.0", "0.2", "0.2.0-beta", "0.2.0\nEvil: yes", "1.2.3.4.5", "latest"])
def test_a_bad_version_is_refused(tool, version):
    if version == "0.2":
        assert tool.render(version, SHA, "2026-11-25")                       # two numbers are a valid version
        return
    with pytest.raises(tool.ManifestError):
        tool.render(version, SHA, "2026-11-25")


@pytest.mark.parametrize("sha", ["", "abc", "z" * 64, "a" * 63, "a" * 65, SHA + "\nEvil: yes"])
def test_a_bad_hash_is_refused(tool, sha):
    with pytest.raises(tool.ManifestError):
        tool.render("0.2.0", sha, "2026-11-25")


@pytest.mark.parametrize("date", ["", "yesterday", "2026-13-01", "2026-11-25\nx: y"])
def test_a_bad_date_is_refused(tool, date):
    with pytest.raises(tool.ManifestError):
        tool.render("0.2.0", SHA, date)


def test_the_hash_can_be_read_from_the_signed_sums_file(tool):
    sums = f"{SHA}  ExtremeCompressor-0.2.0-setup.exe\n"
    assert tool.sha_from_sums(sums, "0.2.0") == SHA
    with pytest.raises(tool.ManifestError):
        tool.sha_from_sums(sums, "0.3.0")                                    # a different version's installer


def test_write_puts_the_files_where_winget_pkgs_expects_them(tool, tmp_path):
    folder = tool.write(tmp_path, "0.2.0", SHA, "2026-11-25")
    assert folder == tmp_path / "manifests" / "n" / "NuhaadhHasn" / "ExtremeCompressor" / "0.2.0"
    assert len(list(folder.glob("*.yaml"))) == 3


def test_the_files_are_valid_yaml_with_the_expected_keys(tool, tmp_path):
    yaml = pytest.importorskip("yaml")
    folder = tool.write(tmp_path, "0.2.0", SHA, "2026-11-25")
    inst = yaml.safe_load((folder / "NuhaadhHasn.ExtremeCompressor.installer.yaml").read_text(encoding="utf-8"))
    assert inst["Installers"][0]["Architecture"] == "x64" and inst["InstallerType"] == "inno"
    loc = yaml.safe_load((folder / "NuhaadhHasn.ExtremeCompressor.locale.en-US.yaml").read_text(encoding="utf-8"))
    assert loc["License"] == "MIT" and loc["PackageName"] == "ExtremeCompressor" and "compression" in loc["Tags"]


@pytest.mark.skipif(shutil.which("winget") is None, reason="winget is not installed here")
def test_winget_itself_accepts_the_manifest(tool, tmp_path):
    folder = tool.write(tmp_path, "0.2.0", SHA, "2026-11-25")
    r = subprocess.run(["winget", "validate", "--manifest", str(folder)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_command_line_reports_errors_without_a_traceback(tool, tmp_path, capsys):
    assert tool.main(["--version", "nope", "--sha256", SHA, "--out", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
    assert tool.main(["--version", "0.2.0", "--sha256", SHA, "--out", str(tmp_path), "--date", "2026-11-25"]) == 0
