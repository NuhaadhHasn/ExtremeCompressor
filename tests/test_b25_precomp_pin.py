"""B25: Precomp is a pinned tool, and the pinned copy is the one that runs.

Until now Precomp (and SREP) were found only under ``C:\\Program Files``: no
hash, no version floor, and a cleanup of that folder would have removed the tool
that Extreme and Insane both depend on. Precomp v0.4.7 is the last upstream
release (2019-02-22) and its asset has no GitHub digest, so the pin is anchored
the way the flac one is: the digests below were taken on 2026-11-18 from the
release's own ``precomp.zip`` *and* matched against the copy that has sat in
Program Files since 2019, which this project did not download - two parties
that agree, rather than a hash of our own download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp import toolfetch, tools

ZIP_SHA256 = "fcd308310135cdc1ae25b45288bcc5201f9cabf5a9e707cfb33b0f99c548de0b"
ZIP_SIZE = 2_300_841

#: windows/ of the 0.4.7 asset, measured 2026-11-18.
WINDOWS_DIR = {
    "precomf.exe": "725dbe8d138a10cdbb25ac3e3ad8b72b2517647d733e9138ceedffe374f3b6e8",
    "precomf32.exe": "677075cbf90037d3f07f7dda0281d544b97d6ccec159a83f48186cd9ecc4832c",
    "precomp.exe": "aabca1ee4eebc1e6ddcee5cb0b654c1c82c26daa1dbcb63f6e5279852826515d",
    "precomp32.exe": "427f9982197d72e95c26daeb403ddf1d70c62d13ce930ce26c443989ecd1f775",
}


# -- the manifest ---------------------------------------------------------------

def test_precomp_is_pinned_to_the_measured_release():
    spec = toolfetch.TOOL_MANIFEST["precomp"]
    assert spec.version == "0.4.7"
    assert spec.url == ("https://github.com/schnaader/precomp-cpp/releases/"
                        "download/v0.4.7/precomp.zip")
    assert spec.sha256 == ZIP_SHA256
    assert spec.size == ZIP_SIZE
    assert spec.exe_relpath == "windows/precomp.exe"
    assert spec.min_version == "0.4.7"
    assert not spec.raw


def test_every_file_beside_precomp_exe_is_pinned():
    """The directory digest is what keeps a planted DLL out: all four files of
    the folder, no more and no fewer."""
    spec = toolfetch.TOOL_MANIFEST["precomp"]
    assert dict(spec.exe_dir_sha256) == WINDOWS_DIR


def test_the_pinned_exe_is_the_one_in_program_files():
    """The second party. Skipped where the old install is not present."""
    old = Path(r"C:\Program Files\precomp\windows\precomp.exe")
    if not old.is_file():
        pytest.skip("no Program Files precomp on this machine")
    assert toolfetch._sha256_of(old) == WINDOWS_DIR["precomp.exe"]


# -- discovery ------------------------------------------------------------------

def _fake_exe(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"MZ")
    return path


def test_a_verified_pinned_precomp_beats_program_files(tmp_path, monkeypatch):
    pinned = _fake_exe(tmp_path, "pinned.exe")
    legacy = _fake_exe(tmp_path, "legacy.exe")
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [str(legacy)])
    monkeypatch.setattr(tools, "_pinned_tool",
                        lambda n: str(pinned) if n == "precomp" else None)
    assert tools.find_tools()["precomp"].path == str(pinned)


def test_program_files_is_the_fallback_when_nothing_is_pinned_yet(tmp_path, monkeypatch):
    legacy = _fake_exe(tmp_path, "legacy.exe")
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [str(legacy)])
    monkeypatch.setattr(tools, "_pinned_tool", lambda n: None)
    assert tools.find_tools()["precomp"].path == str(legacy)


def test_a_pinned_install_that_fails_verification_is_not_used(tmp_path, monkeypatch):
    """`installed_path` answers None for a tree that no longer hashes to the
    pin; discovery must then fall through, not trust the directory."""
    legacy = _fake_exe(tmp_path, "legacy.exe")
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [str(legacy)])
    monkeypatch.setattr(toolfetch, "installed_path", lambda spec: None)
    assert tools.find_tools()["precomp"].path == str(legacy)
