"""Hand-crafted hostile ``.excmp`` containers must be refused (D0.2, D0.3).

Before D0, ``extract_stored()`` built ``out_dir / rel`` straight from the zip
entry name and wrote it through a manual ``zf.open()`` loop -- which bypasses
``ZipFile.extract()``'s own sanitizer. A crafted archive wrote anywhere the
user could write.

Two conventions make these tests trustworthy:

* Every test asserts refusal **and** that nothing landed outside the
  destination. An exception alone proves nothing: the write may already have
  happened before the failure.
* ``out_dir`` is nested a few levels under ``tmp_path`` and every hostile name
  aims at a canary *inside* ``tmp_path``. So when a test is run against
  unpatched code it demonstrates the escape harmlessly, instead of trying to
  write to the drive root and "passing" on a permission error.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.manifest import (MANIFEST_NAME, ContainerError, Manifest,
                            extract_stored, read_container, write_container)
from excmp.safepath import UnsafePathError
from excmp.stages.base import StageContext
from excmp.verify import verify_restore

CANARY = "CANARY.txt"
PAYLOAD = b"pwned"


def _out_dir(tmp_path: Path) -> Path:
    """A destination deep enough that ``../..`` still lands inside tmp_path."""
    d = tmp_path / "deep" / "deeper" / "out"
    d.mkdir(parents=True)
    return d


def _manifest_dict(inputs=None, payload_name="") -> dict:
    return {
        "schema": 1,
        "created_utc": "2026-07-31T00:00:00+00:00",
        "profile": "normal",
        "stages": [],
        "inputs": inputs if inputs is not None else {},
        "payload_name": payload_name,
        "warnings": [],
        "routes": [],
    }


def _hostile_zip(arc: Path, entries, *, manifest=None, manifest_raw=None,
                 attrs=None) -> Path:
    """Write a zip with entry names taken *verbatim*.

    ``ZipInfo(filename=...)`` rewrites ``\\`` to ``/`` in its constructor on
    Windows, so a backslash name has to be assigned after construction --
    otherwise the test would silently exercise the forward-slash form.
    """
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        if manifest_raw is not None:
            zf.writestr(MANIFEST_NAME, manifest_raw)
        elif manifest is not None:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest))
        for name, data in entries:
            info = zipfile.ZipInfo("placeholder")
            info.filename = name
            info.compress_type = zipfile.ZIP_STORED
            if attrs is not None:
                info.external_attr = attrs
            zf.writestr(info, data)
    return arc


def _assert_nothing_escaped(tmp_path: Path, out_dir: Path) -> None:
    strays = [p for p in tmp_path.rglob(CANARY)]
    assert strays == [], f"hostile entry escaped to {strays}"
    assert [p for p in out_dir.rglob("*") if p.is_file()] == [], \
        "a rejected archive still left files in the destination"


# --- D0.1: path traversal and friends via extract_stored ----------------------

# Relative escapes: aimed at tmp_path/deep/CANARY.txt and tmp_path/CANARY.txt.
RELATIVE_ESCAPES = [
    f"stored/../../{CANARY}",
    f"stored/../../../{CANARY}",
    rf"stored/..\..\{CANARY}",
    f"stored/a/../../../{CANARY}",
]


@pytest.mark.parametrize("entry", RELATIVE_ESCAPES)
def test_extract_stored_refuses_traversal(tmp_path, entry):
    out = _out_dir(tmp_path)
    ledger = {CANARY: {"size": len(PAYLOAD), "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp", [(entry, PAYLOAD)],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(UnsafePathError):
        extract_stored(arc, out, ledger)
    _assert_nothing_escaped(tmp_path, out)


def test_extract_stored_refuses_absolute_path(tmp_path):
    """An absolute entry name with a drive letter -- pointed at our own tmp
    dir, so an unpatched run escapes here rather than to C:\\."""
    out = _out_dir(tmp_path)
    absolute = (tmp_path / CANARY).as_posix()          # e.g. C:/Users/.../CANARY.txt
    ledger = {CANARY: {"size": len(PAYLOAD), "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp", [(f"stored/{absolute}", PAYLOAD)],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(UnsafePathError):
        extract_stored(arc, out, ledger)
    _assert_nothing_escaped(tmp_path, out)


HOSTILE_NAMES = [
    f"x.txt:{CANARY}",          # NTFS alternate data stream
    f"x:Zone.Identifier:$DATA",  # ADS + the :$DATA suffix trick
    "NUL.txt",                   # reserved device name with an extension
    "COM1 .log",                 # reserved name behind a trailing space
    "CON",
    "name.",                     # trailing dot
    "name ",                     # trailing space
    "a\u202eb.txt",              # RLO -- 7-Zip does not sanitize this one
    "\u202egpj.exe",             # right-to-left extension spoof
    'a<b>c|d"e*f?g',             # Windows-illegal characters
    "a\x01b.txt",                # control character
    "a//b.txt",                  # empty path component
]


@pytest.mark.parametrize("rel", HOSTILE_NAMES)
def test_extract_stored_refuses_hostile_names(tmp_path, rel):
    out = _out_dir(tmp_path)
    ledger = {rel: {"size": len(PAYLOAD), "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp", [(f"stored/{rel}", PAYLOAD)],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(UnsafePathError):
        extract_stored(arc, out, ledger)


def test_extract_stored_refuses_symlink_entry(tmp_path):
    """A zip entry carrying symlink mode bits.

    Our writer only ever stores regular files, so a symlink entry is either
    corruption or an attempt to plant a link we would later follow.
    """
    out = _out_dir(tmp_path)
    ledger = {"link": {"size": 3, "sha256": "x", "route": "store"}}
    symlink_mode = (0o120777 << 16)
    arc = _hostile_zip(tmp_path / "evil.excmp", [("stored/link", b"../")],
                       manifest=_manifest_dict(ledger), attrs=symlink_mode)
    with pytest.raises(UnsafePathError):
        extract_stored(arc, out, ledger)


# --- D0.3: ledger-bounded extraction -----------------------------------------


def test_extract_stored_refuses_entry_absent_from_ledger(tmp_path):
    """The ledger is the archive's own declaration of what it contains. An
    entry nobody declared is a smuggled file -- and it could never verify."""
    out = _out_dir(tmp_path)
    ledger = {"declared.txt": {"size": 5, "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp",
                       [("stored/undeclared.txt", PAYLOAD)],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(ContainerError):
        extract_stored(arc, out, ledger)


def test_extract_stored_refuses_entry_bigger_than_declared(tmp_path):
    """Decompression-bomb defense: the ledger declares 5 bytes, the entry
    carries 1 MiB. The bound is enforced on the real stream, so a forged
    header cannot talk us into writing it."""
    out = _out_dir(tmp_path)
    ledger = {"lie.bin": {"size": 5, "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp",
                       [("stored/lie.bin", b"A" * (1 << 20))],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(ContainerError):
        extract_stored(arc, out, ledger)
    # the partial write must be cleaned up, not left as a truncated file
    assert [p for p in out.rglob("*") if p.is_file()] == []


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_extract_stored_refuses_duplicate_entry_names(tmp_path):
    """A zip may carry two entries with one name. Whichever we hash last,
    the other one already hit the disk -- so refuse the archive.

    (zipfile warns while *writing* the deliberate duplicate; that warning is
    the fixture doing its job, not a problem under test.)
    """
    out = _out_dir(tmp_path)
    ledger = {"dup.txt": {"size": 4, "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp",
                       [("stored/dup.txt", b"good"), ("stored/dup.txt", b"evil")],
                       manifest=_manifest_dict(ledger))
    with pytest.raises(ContainerError):
        extract_stored(arc, out, ledger)


def test_extract_stored_accepts_a_legitimate_archive(tmp_path):
    """Guard against over-strictness: the ordinary case must still work."""
    out = _out_dir(tmp_path)
    ledger = {
        "a.txt": {"size": 3, "sha256": "x", "route": "store"},
        "sub/b.txt": {"size": 4, "sha256": "x", "route": "store"},
    }
    arc = _hostile_zip(tmp_path / "good.excmp",
                       [("stored/a.txt", b"aaa"), ("stored/sub/b.txt", b"bbbb")],
                       manifest=_manifest_dict(ledger))
    written = extract_stored(arc, out, ledger)
    assert sorted(p.name for p in written) == ["a.txt", "b.txt"]
    assert (out / "a.txt").read_bytes() == b"aaa"
    assert (out / "sub" / "b.txt").read_bytes() == b"bbbb"


# --- read_container: payload_name and the manifest cap -----------------------


def test_read_container_refuses_hostile_payload_name(tmp_path):
    """``manifest.payload_name`` is attacker-controlled too. Joined naively it
    is an arbitrary-file-read primitive: ``extract_dir / 'C:/x'`` is ``C:/x``."""
    out = _out_dir(tmp_path)
    hostile = f"../../{CANARY}"
    arc = _hostile_zip(tmp_path / "evil.excmp", [(f"stored/keep.txt", b"ok")],
                       manifest=_manifest_dict({}, payload_name=hostile))
    with pytest.raises(UnsafePathError):
        read_container(arc, out)
    _assert_nothing_escaped(tmp_path, out)


def test_read_container_caps_manifest_size(tmp_path):
    """``manifest.json`` is parsed before anything is validated, so an
    unbounded ``json.loads`` is a cheap memory bomb. Cap it first."""
    out = _out_dir(tmp_path)
    huge = json.dumps({**_manifest_dict(), "warnings": ["A" * (9 << 20)]})
    arc = _hostile_zip(tmp_path / "evil.excmp", [], manifest_raw=huge)
    with pytest.raises(ContainerError):
        read_container(arc, out)


# --- verify_restore: untrusted ledger keys ----------------------------------


def test_verify_restore_refuses_hostile_ledger_key(tmp_path):
    """Read-only, but it still probes for arbitrary files by size and hash."""
    out = _out_dir(tmp_path)
    ledger = {f"../../{CANARY}": {"size": 5, "sha256": "x"}}
    with pytest.raises(UnsafePathError):
        verify_restore(out, ledger)


# --- write side: never create an archive we would refuse to read ------------


def test_write_container_refuses_hostile_stored_path(tmp_path):
    m = Manifest.new(profile="normal", stages=[], inputs={}, payload_name="")
    src = tmp_path / "src.txt"
    src.write_bytes(b"hi")
    with pytest.raises(UnsafePathError):
        write_container(tmp_path / "o.excmp", m, None, {f"../../{CANARY}": src})
    assert not (tmp_path / "o.excmp").exists()


def test_write_container_refuses_hostile_ledger_key(tmp_path):
    m = Manifest.new(profile="normal", stages=[],
                     inputs={"NUL.txt": {"size": 1, "sha256": "x"}},
                     payload_name="")
    with pytest.raises(UnsafePathError):
        write_container(tmp_path / "o.excmp", m, None, {})


# --- end to end through the engine ------------------------------------------


def test_engine_extract_refuses_hostile_archive(tmp_path):
    """The failure has to survive the whole call path, not just the helper."""
    out = _out_dir(tmp_path)
    ledger = {CANARY: {"size": len(PAYLOAD), "sha256": "x", "route": "store"}}
    arc = _hostile_zip(tmp_path / "evil.excmp",
                       [(f"stored/../../{CANARY}", PAYLOAD)],
                       manifest=_manifest_dict(ledger))
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    with pytest.raises((UnsafePathError, ContainerError)):
        engine.extract(arc, out, ctx)
    _assert_nothing_escaped(tmp_path, out)
