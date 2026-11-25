"""tools/release_sign.py makes what excmp/updater.py checks: the two ends of the update channel meet."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from excmp import updater

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("release_sign", ROOT / "tools" / "release_sign.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_what_the_tool_signs_the_updater_accepts(tool, tmp_path):
    key = tmp_path / "k"
    pub_hex = tool.keygen(key)
    installer = tmp_path / "ExtremeCompressor-0.2.0-setup.exe"
    installer.write_bytes(b"MZ" + b"installer" * 1000)
    sums = tool.write_sums(installer)
    sig = tool.sign_file(sums, key, expect_public=bytes.fromhex(pub_hex))
    updater.verify_signature(sums.read_bytes(), sig.read_text(encoding="ascii"), bytes.fromhex(pub_hex))
    table = updater.parse_sums(sums.read_text(encoding="ascii"))
    import hashlib
    assert table == {installer.name: hashlib.sha256(installer.read_bytes()).hexdigest()}


def test_the_tool_refuses_to_overwrite_a_key(tool, tmp_path):
    key = tmp_path / "k"
    tool.keygen(key)
    with pytest.raises(SystemExit):
        tool.keygen(key)


def test_a_missing_key_is_a_clear_exit_not_a_traceback(tool, tmp_path):
    with pytest.raises(SystemExit, match="keygen"):
        tool.load_key(tmp_path / "nope")


def test_the_key_in_the_app_is_the_one_the_owner_generated_and_is_not_the_placeholder():
    assert updater.PUBLIC_KEY != bytes(32)


def test_the_private_key_is_not_in_the_repo():
    """The private key lives under the home folder, never in a tracked path. Guard against a 64-hex file
    called *signing*key* appearing in the tree."""
    hits = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts
            and "signing" in p.name.lower() and "key" in p.name.lower() and p.suffix != ".py"]
    assert hits == []
    for p in (ROOT / "excmp" / "updater.py", ROOT / "tools" / "release_sign.py"):
        assert not re.search(r"private_key\s*=\s*bytes\.fromhex", p.read_text(encoding="utf-8"))


def test_a_key_that_is_not_the_apps_key_is_refused_before_a_release_is_made(tool, tmp_path):
    """The mistake that would otherwise ship a release every installed copy silently refuses."""
    key = tmp_path / "k"
    tool.keygen(key)
    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(b"x")
    with pytest.raises(SystemExit, match="PUBLIC_KEY"):
        tool.sign_file(sums, key)                          # checked against the key built into the app


@pytest.mark.parametrize("name", ["setup.exe", "ExtremeCompressor-setup.exe", "ExtremeCompressor-0.2.0.exe",
                                  "ExtremeCompressor-v0.2.0-setup.exe", "evil-0.2.0-setup.exe"])
def test_an_installer_the_app_would_not_look_for_is_refused(tool, tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    with pytest.raises(SystemExit, match="named"):
        tool.write_sums(f)
