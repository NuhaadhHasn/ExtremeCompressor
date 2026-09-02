"""G9 — store identical files once, restore them everywhere.

**The measurement that caused this** (benchmarks/2026-09-02): on a corpus that
was 49% exact duplicates, Extreme saved 5.22% and Insane 5.21%. Neither
compressor could see the duplication, because the duplicated files were
high-entropy and so were routed to ``store`` — copied verbatim into the
container, correctly, and therefore never entering the pipeline where every
deduplicator lives. We wrote both copies in full.

The fix costs nothing we were not already paying for: a SHA-256 per file *is*
the ledger. Two entries with the same hash are the same bytes by definition,
so one copy goes in the zip and the other entries carry a ``same_as`` pointer.

**Nothing about extraction changes for the user.** Every file is written out
at its own path, at full size. A game whose data folder and mods folder hold
the same pak gets both back; three games sharing a file each get their own.
And ``verify_restore`` re-hashes the *restored file on disk*, so if a copy
were ever not written, the archive fails its own gate and is never published.

The hostile cases below are the reason this file exists. A ``same_as`` is a
pointer inside an archive we may not have written, so it is exactly the kind
of field a malicious archive would aim at.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from excmp.manifest import (MANIFEST_NAME, STORED_PREFIX, ContainerError,
                            Manifest, extract_stored, write_container)


def _ledger(**files: bytes) -> dict[str, dict]:
    return {name: {"size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest(),
                   "route": "store"}
            for name, data in files.items()}


def _manifest(ledger: dict[str, dict]) -> Manifest:
    return Manifest.new(profile="normal", stages=[], inputs=ledger,
                        payload_name=None)


def _sources(tmp_path: Path, **files: bytes) -> dict[str, Path]:
    out = {}
    for name, data in files.items():
        p = tmp_path / "src" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        out[name] = p
    return out


# ---------------------------------------------------------------------------
# The saving
# ---------------------------------------------------------------------------

def test_identical_files_are_stored_once(tmp_path):
    blob = b"the same bytes, twice" * 5000
    files = {"a/one.bin": blob, "b/two.bin": blob}
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(_ledger(**files)),
                    stored_files=_sources(tmp_path, **files))

    with zipfile.ZipFile(archive) as zf:
        stored = [n for n in zf.namelist() if n.startswith(STORED_PREFIX)]
    assert len(stored) == 1, f"both copies were written: {stored}"
    # And the archive is genuinely smaller than the two inputs.
    assert archive.stat().st_size < len(blob) * 1.5


def test_both_files_come_back(tmp_path):
    """The question that matters: a game with the same file in two folders
    must get both of them back."""
    blob = b"shared game asset" * 4000
    files = {"game/data/x.pak": blob, "game/mods/x.pak": blob}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))

    out = tmp_path / "out"
    written = extract_stored(archive, out, ledger)
    assert len(written) == 2
    for name in files:
        got = out / name
        assert got.is_file(), f"{name} was not restored"
        assert got.read_bytes() == blob


def test_three_way_duplication_restores_all_three(tmp_path):
    """Three games sharing one file: none of them loses it."""
    blob = b"a runtime dll" * 3000
    files = {f"game{i}/bin/rt.dll": blob for i in (1, 2, 3)}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))
    with zipfile.ZipFile(archive) as zf:
        assert len([n for n in zf.namelist() if n.startswith(STORED_PREFIX)]) == 1

    out = tmp_path / "out"
    extract_stored(archive, out, ledger)
    for name in files:
        assert (out / name).read_bytes() == blob


def test_different_files_are_untouched(tmp_path):
    files = {"a.bin": b"alpha" * 1000, "b.bin": b"bravo" * 1000}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))
    with zipfile.ZipFile(archive) as zf:
        assert len([n for n in zf.namelist() if n.startswith(STORED_PREFIX)]) == 2
    out = tmp_path / "out"
    extract_stored(archive, out, ledger)
    assert (out / "a.bin").read_bytes() == files["a.bin"]
    assert (out / "b.bin").read_bytes() == files["b.bin"]


def test_same_size_different_bytes_is_not_a_duplicate(tmp_path):
    """Size is not identity. Only the hash decides."""
    files = {"a.bin": b"A" * 4096, "b.bin": b"B" * 4096}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))
    out = tmp_path / "out"
    extract_stored(archive, out, ledger)
    assert (out / "a.bin").read_bytes() == b"A" * 4096
    assert (out / "b.bin").read_bytes() == b"B" * 4096


def test_empty_files_do_not_confuse_it(tmp_path):
    files = {"e1": b"", "e2": b"", "real.bin": b"x" * 100}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))
    out = tmp_path / "out"
    extract_stored(archive, out, ledger)
    assert (out / "e1").read_bytes() == b""
    assert (out / "e2").read_bytes() == b""
    assert (out / "real.bin").read_bytes() == b"x" * 100


# ---------------------------------------------------------------------------
# Hostile archives - a `same_as` is a pointer we did not necessarily write
# ---------------------------------------------------------------------------

def _handmade(tmp_path: Path, ledger: dict[str, dict],
              entries: dict[str, bytes]) -> Path:
    archive = tmp_path / "hostile.excmp"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(MANIFEST_NAME, _manifest(ledger).to_json())
        for name, data in entries.items():
            zf.writestr(STORED_PREFIX + name, data)
    return archive


def test_a_same_as_cycle_is_refused(tmp_path):
    """Two entries pointing at each other, with no real bytes anywhere. A
    reader that follows pointers without a hop limit loops forever."""
    blob = b"z" * 64
    ledger = _ledger(**{"a": blob, "b": blob})
    ledger["a"]["same_as"] = "b"
    ledger["b"]["same_as"] = "a"
    archive = _handmade(tmp_path, ledger, {})
    with pytest.raises(ContainerError):
        extract_stored(archive, tmp_path / "out", ledger)


def test_a_same_as_chain_is_refused(tmp_path):
    """One hop only. `c -> b -> a` is refused even though it terminates:
    allowing chains means allowing a reader to be walked, and there is no
    reason for a writer of ours to ever emit one."""
    blob = b"z" * 64
    ledger = _ledger(**{"a": blob, "b": blob, "c": blob})
    ledger["b"]["same_as"] = "a"
    ledger["c"]["same_as"] = "b"
    archive = _handmade(tmp_path, ledger, {"a": blob})
    with pytest.raises(ContainerError):
        extract_stored(archive, tmp_path / "out", ledger)


def test_a_same_as_pointing_outside_the_ledger_is_refused(tmp_path):
    blob = b"z" * 64
    ledger = _ledger(**{"a": blob})
    ledger["a"]["same_as"] = "not-in-the-ledger"
    archive = _handmade(tmp_path, ledger, {})
    with pytest.raises(ContainerError):
        extract_stored(archive, tmp_path / "out", ledger)


def test_a_same_as_whose_hash_disagrees_is_refused(tmp_path):
    """The pointer claims "same bytes as a", but the ledger's own hashes say
    otherwise. Trusting the pointer over the hash would let an archive serve
    one file's contents under another file's name and hash."""
    ledger = _ledger(**{"a": b"A" * 64, "b": b"B" * 64})
    ledger["b"]["same_as"] = "a"          # hashes differ - a lie
    archive = _handmade(tmp_path, ledger, {"a": b"A" * 64})
    with pytest.raises(ContainerError):
        extract_stored(archive, tmp_path / "out", ledger)


def test_a_same_as_traversal_target_is_refused(tmp_path):
    blob = b"z" * 64
    ledger = _ledger(**{"a": blob})
    ledger["a"]["same_as"] = "../../outside.txt"
    archive = _handmade(tmp_path, ledger, {})
    with pytest.raises(Exception):
        extract_stored(archive, tmp_path / "out", ledger)


def test_a_same_as_with_no_bytes_anywhere_is_refused(tmp_path):
    """Points at a real ledger entry that has no zip member either."""
    blob = b"z" * 64
    ledger = _ledger(**{"a": blob, "b": blob})
    ledger["b"]["same_as"] = "a"
    archive = _handmade(tmp_path, ledger, {})   # no stored/a
    with pytest.raises(ContainerError):
        extract_stored(archive, tmp_path / "out", ledger)


# ---------------------------------------------------------------------------
# Selective extract (G2) still works
# ---------------------------------------------------------------------------

def test_extracting_only_the_duplicate_still_produces_the_file(tmp_path):
    """The duplicate's bytes live under the *other* file's name. Asking for
    just the duplicate must still work - the source is read from the zip, not
    from whatever happens to have been written to disk."""
    blob = b"shared" * 2000
    files = {"first.bin": blob, "second.bin": blob}
    ledger = _ledger(**files)
    archive = tmp_path / "d.excmp"
    write_container(archive, _manifest(ledger),
                    stored_files=_sources(tmp_path, **files))

    out = tmp_path / "out"
    written = extract_stored(archive, out, ledger, only={"second.bin"})
    assert [p.name for p in written] == ["second.bin"]
    assert (out / "second.bin").read_bytes() == blob
    assert not (out / "first.bin").exists()
