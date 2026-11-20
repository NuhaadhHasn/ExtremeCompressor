"""B27: a hash-pinned tool that is missing (or fails its check) must not be replaced SILENTLY.

B25 pinned Precomp and made discovery prefer the verified copy, with the well-known Program Files
install as the fallback for a checkout that has not fetched it. That fallback was silent, so a
machine could run an unverified Precomp for months believing the pin was in force - or lose its
pinned copy to a failed digest check and never hear about it. One warning, once per process and per
tool, with the path that is used instead.
"""

from __future__ import annotations

import logging

import pytest

from excmp import tools


@pytest.fixture(autouse=True)
def _fresh_warnings(monkeypatch):
    monkeypatch.setattr(tools, "_UNPINNED_WARNED", set())


@pytest.fixture
def fake_precomp(tmp_path, monkeypatch):
    exe = tmp_path / "precomp.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [str(exe)])
    return exe


def _warnings(caplog):
    return [r for r in caplog.records if r.name == "excmp.tools" and r.levelno == logging.WARNING]


def test_the_fallback_is_announced_with_the_path_that_is_used(monkeypatch, caplog, fake_precomp):
    monkeypatch.setattr(tools, "_pinned_tool", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="excmp.tools"):
        found = tools.find_tools()
    assert found["precomp"].path == str(fake_precomp)
    got = _warnings(caplog)
    assert len(got) == 1
    text = got[0].getMessage()
    assert "precomp" in text and str(fake_precomp) in text and "pinned" in text


def test_it_is_said_once_not_on_every_discovery(monkeypatch, caplog, fake_precomp):
    """`find_tools` runs on every analysis; a warning per call would be noise nobody reads."""
    monkeypatch.setattr(tools, "_pinned_tool", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="excmp.tools"):
        tools.find_tools()
        tools.find_tools()
        tools.find_tools()
    assert len(_warnings(caplog)) == 1


def test_a_verified_pinned_copy_is_not_a_warning(monkeypatch, caplog, tmp_path, fake_precomp):
    pinned = tmp_path / "pinned" / "precomp.exe"
    pinned.parent.mkdir()
    pinned.write_bytes(b"MZ")
    monkeypatch.setattr(tools, "_pinned_tool", lambda name: str(pinned) if name == "precomp" else None)
    with caplog.at_level(logging.WARNING, logger="excmp.tools"):
        found = tools.find_tools()
    assert found["precomp"].path == str(pinned)
    assert _warnings(caplog) == []


def test_a_tool_that_is_simply_not_installed_is_not_a_warning(monkeypatch, caplog):
    """Nothing is being substituted for the pin, so there is nothing to announce."""
    monkeypatch.setattr(tools, "_pinned_tool", lambda name: None)
    monkeypatch.setitem(tools.CANDIDATES, "precomp", [r"C:\definitely\not\here\precomp.exe"])
    monkeypatch.setattr(tools, "APP_BIN", tools.Path(r"C:\definitely\not\here"))
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="excmp.tools"):
        found = tools.find_tools()
    assert found["precomp"] is None
    assert _warnings(caplog) == []


def test_an_unpinned_tool_found_the_ordinary_way_is_not_a_warning(monkeypatch, caplog, tmp_path):
    """7-Zip has no pin: its well-known install is not a fallback for anything."""
    exe = tmp_path / "7z.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(tools, "_pinned_tool", lambda name: None)
    monkeypatch.setitem(tools.CANDIDATES, "7z", [str(exe)])
    with caplog.at_level(logging.WARNING, logger="excmp.tools"):
        found = tools.find_tools()
    assert found["7z"].path == str(exe)
    assert not any("7z" in r.getMessage() for r in _warnings(caplog))
