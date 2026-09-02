"""G3 — splitting an archive into volumes, and joining it back.

Why pure-Python chunking rather than `7z -v`: an `.excmp` is not a bare `.7z`,
it is a zip container holding a manifest and a payload. Letting 7-Zip split it
would make the parts a 7-Zip format detail rather than ours, and joining would
then need 7-Zip present just to read our own archive.

The design is deliberately dull. Parts are `<archive>.001`, `<archive>.002`,
…, they concatenate to exactly the original bytes, and **nothing about the
container changes** — join first, then the ordinary reader runs, so every
guarantee the container already makes is untouched.

Per-part SHA-256 goes in a `.sha256` sidecar in `sha256sum` layout, the same
format G6 already uses for whole archives. It is a **convenience, not a
correctness requirement**: it exists so a failed transfer can say *which* part
is bad instead of "something is wrong". Joining works without it, and the
container's own manifest and the D9 restore are what actually decide whether
the data is good.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from excmp.volumes import (PART_SUFFIX_WIDTH, VolumeError, is_first_part,
                           join_parts, part_paths, split_file,
                           write_parts_sidecar)


def _make(tmp_path: Path, size: int, name: str = "a.excmp") -> Path:
    p = tmp_path / name
    # Deterministic but not compressible-looking, so a truncation is visible.
    p.write_bytes(bytes((i * 37 + 11) % 251 for i in range(size)))
    return p


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def test_a_file_splits_into_parts_that_rejoin_exactly(tmp_path):
    original = _make(tmp_path, 10_000)
    want = original.read_bytes()

    parts = split_file(original, part_size=3_000)
    assert len(parts) == 4          # 3000 + 3000 + 3000 + 1000
    assert [p.name for p in parts] == ["a.excmp.001", "a.excmp.002",
                                       "a.excmp.003", "a.excmp.004"]

    joined = join_parts(parts[0], tmp_path / "rejoined.excmp")
    assert joined.read_bytes() == want


def test_an_exact_multiple_does_not_produce_an_empty_tail(tmp_path):
    """9000 / 3000 is 3 parts, not 4. An empty `.004` would be a part whose
    absence later looks like a truncated set."""
    original = _make(tmp_path, 9_000)
    parts = split_file(original, part_size=3_000)
    assert len(parts) == 3
    assert all(p.stat().st_size == 3_000 for p in parts)


def test_a_file_smaller_than_one_part_still_makes_one_part(tmp_path):
    original = _make(tmp_path, 500)
    parts = split_file(original, part_size=10_000)
    assert len(parts) == 1
    assert join_parts(parts[0], tmp_path / "r.excmp").read_bytes() == original.read_bytes()


def test_an_empty_file_makes_exactly_one_empty_part(tmp_path):
    original = tmp_path / "empty.excmp"
    original.write_bytes(b"")
    parts = split_file(original, part_size=1000)
    assert len(parts) == 1
    assert join_parts(parts[0], tmp_path / "r.excmp").read_bytes() == b""


def test_the_original_is_left_alone(tmp_path):
    """Splitting is additive. Deleting the source would make a failed split
    unrecoverable, and inputs are never modified anywhere else either."""
    original = _make(tmp_path, 5_000)
    before = original.read_bytes()
    split_file(original, part_size=1_000)
    assert original.exists() and original.read_bytes() == before


def test_a_silly_part_size_is_refused(tmp_path):
    original = _make(tmp_path, 5_000)
    for bad in (0, -1):
        with pytest.raises(VolumeError):
            split_file(original, part_size=bad)


def test_more_parts_than_the_numbering_allows_is_refused(tmp_path):
    """999 parts is the limit of a three-digit suffix. Rolling over to `.1000`
    would sort wrongly beside `.100` and silently reorder the archive."""
    original = _make(tmp_path, 10_000)
    with pytest.raises(VolumeError, match="too many"):
        split_file(original, part_size=1)


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

def test_a_missing_middle_part_is_refused_by_name(tmp_path):
    """The failure a split archive actually has: one part did not finish
    downloading. Saying which one is the whole point."""
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    parts[1].unlink()
    with pytest.raises(VolumeError, match="002"):
        join_parts(parts[0], tmp_path / "r.excmp")


def test_a_missing_tail_part_is_refused(tmp_path):
    """Harder than a missing middle: the sequence just stops, which looks
    exactly like a complete set one part shorter. The sidecar is what tells
    them apart."""
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    write_parts_sidecar(parts)
    parts[-1].unlink()
    with pytest.raises(VolumeError):
        join_parts(parts[0], tmp_path / "r.excmp")


def test_joining_must_start_at_part_one(tmp_path):
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    with pytest.raises(VolumeError):
        join_parts(parts[2], tmp_path / "r.excmp")


def test_a_corrupted_part_is_named_when_the_sidecar_is_present(tmp_path):
    """Without the sidecar a corrupt part still fails - the container's own
    manifest catches it - but only as "this archive is broken". With it we can
    say which file to re-download."""
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    write_parts_sidecar(parts)
    parts[1].write_bytes(b"x" * parts[1].stat().st_size)

    with pytest.raises(VolumeError, match="002"):
        join_parts(parts[0], tmp_path / "r.excmp")


def test_joining_works_without_a_sidecar(tmp_path):
    """The sidecar is a convenience. Losing it must not cost you the archive."""
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    sidecar = Path(str(parts[0]).rsplit(".", 1)[0] + ".sha256")
    sidecar.unlink(missing_ok=True)
    joined = join_parts(parts[0], tmp_path / "r.excmp")
    assert joined.read_bytes() == original.read_bytes()


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def test_part_names_sort_in_join_order(tmp_path):
    """Zero-padded, so a plain lexical sort is also the right order - which is
    what every file manager, FTP listing and shell glob will use."""
    original = _make(tmp_path, 30_000)
    parts = split_file(original, part_size=3_000)
    assert [p.name for p in parts] == sorted(p.name for p in parts)


def test_is_first_part_recognises_only_the_first(tmp_path):
    assert is_first_part(Path("a.excmp.001"))
    assert not is_first_part(Path("a.excmp.002"))
    assert not is_first_part(Path("a.excmp"))
    assert not is_first_part(Path("a.excmp.00a"))


def test_part_paths_enumerates_what_is_on_disk(tmp_path):
    original = _make(tmp_path, 10_000)
    parts = split_file(original, part_size=3_000)
    assert part_paths(parts[0]) == parts


def test_the_suffix_width_is_three(tmp_path):
    assert PART_SUFFIX_WIDTH == 3


def test_the_sidecar_is_checkable_by_sha256sum(tmp_path):
    r"""LF line endings, not CRLF.

    A shipped bug until 2026-09-02: `Path.write_text` translates to CRLF on
    Windows, `sha256sum -c` then reads the trailing \r as part of the
    filename, and every line fails with "No such file or directory". A sidecar
    whose entire purpose is that one command has to survive it.
    """
    original = _make(tmp_path, 5_000)
    parts = split_file(original, part_size=2_000)
    sidecar = write_parts_sidecar(parts)
    raw = sidecar.read_bytes()
    assert b"\r\n" not in raw, "CRLF in the sidecar breaks `sha256sum -c`"
    # And the layout is what sha256sum expects: 64 hex, two spaces, bare name.
    for line in raw.decode().splitlines():
        digest, sep, name = line.partition("  ")
        assert sep == "  " and len(digest) == 64
        assert "/" not in name and "\\" not in name, "must be a bare filename"


def test_the_whole_archive_sidecar_is_also_lf(tmp_path):
    """The same fix in engine._write_sidecar (G6), pinned here because the two
    sidecars are the same promise in two places."""
    from excmp.engine import _write_sidecar

    target = tmp_path / "a.excmp"
    target.write_bytes(b"pretend archive")
    side = _write_sidecar(target)
    assert b"\r\n" not in side.read_bytes()
