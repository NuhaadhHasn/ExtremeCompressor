"""F4 — carrying the Mark of the Web onto what we extract.

When Windows downloads a file it attaches a `Zone.Identifier` alternate data
stream saying where it came from. SmartScreen, Office's Protected View and
Defender all key off that mark. **Extract a downloaded archive and the mark
does not follow the files out** — so an executable that arrived from the
internet lands on disk looking exactly like one the user wrote themselves.

7-Zip's CLI default is *off* (`-snz` turns it on), which is why the CVE that
made this famous existed at all. Ours defaults to **on**: a downloaded archive
is the normal case, and the safe behaviour should not be the one you have to
know a switch for.

Three rules, each from a specific piece of history:

- **Direct ADS file I/O, never PowerShell.** PeaZip shipped a
  PowerShell-injection CVE doing exactly this job by shelling out
  (research/17 §5). `open(path + ":Zone.Identifier", "wb")` is about forty
  lines and has no shell to inject into.
- **Never trust a `Zone.Identifier` stored *inside* the archive.** That is
  CVE-2025-0411: a crafted archive carries its own mark, which overwrites the
  propagated one and downgrades the file to "local". Any archive member whose
  name contains `:` is refused by `safepath` already; this is the second lock
  on the same door.
- **Failing to write the mark is not a failure.** FAT32 and exFAT have no
  alternate data streams. A USB stick is not an error condition.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from excmp.motw import (ZONE_STREAM, ads_path, propagate, read_zone,
                        write_zone)

windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="alternate data streams are NTFS")

INTERNET_ZONE = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://example.invalid/a.zip\r\n"


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def test_the_stream_is_named_the_way_windows_names_it():
    assert ZONE_STREAM == "Zone.Identifier"


def test_the_ads_path_is_the_file_plus_the_stream():
    assert str(ads_path(Path("C:/x/a.exe"))).endswith("a.exe:Zone.Identifier")


# ---------------------------------------------------------------------------
# Reading and writing the mark
# ---------------------------------------------------------------------------

@windows_only
def test_a_mark_round_trips(tmp_path):
    target = tmp_path / "downloaded.zip"
    target.write_bytes(b"pretend archive")
    write_zone(target, INTERNET_ZONE)
    assert read_zone(target) == INTERNET_ZONE


@windows_only
def test_an_unmarked_file_reads_as_none(tmp_path):
    target = tmp_path / "local.txt"
    target.write_bytes(b"written here, not downloaded")
    assert read_zone(target) is None


def test_reading_a_missing_file_is_none_not_an_exception(tmp_path):
    assert read_zone(tmp_path / "nope") is None


@windows_only
def test_an_oversized_stream_is_truncated_rather_than_read_whole(tmp_path):
    """A Zone.Identifier is a few hundred bytes. An archive that ships a 2 GB
    one is not describing a zone, it is trying to make us read 2 GB."""
    from excmp.motw import MAX_ZONE_BYTES

    target = tmp_path / "big.bin"
    target.write_bytes(b"x")
    write_zone(target, "A" * (MAX_ZONE_BYTES * 3))
    got = read_zone(target)
    assert got is not None and len(got.encode("utf-8")) <= MAX_ZONE_BYTES


# ---------------------------------------------------------------------------
# Propagating onto extracted files
# ---------------------------------------------------------------------------

@windows_only
def test_the_mark_follows_the_files_out(tmp_path):
    archive = tmp_path / "from-the-web.excmp"
    archive.write_bytes(b"archive")
    write_zone(archive, INTERNET_ZONE)

    out = tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    (out / "a.exe").write_bytes(b"payload")
    (out / "sub" / "b.dll").write_bytes(b"payload")

    marked = propagate(archive, out)
    assert marked == 2
    assert read_zone(out / "a.exe") == INTERNET_ZONE
    assert read_zone(out / "sub" / "b.dll") == INTERNET_ZONE


@windows_only
def test_an_unmarked_archive_marks_nothing(tmp_path):
    """Compressing your own folder and extracting it must not invent a claim
    that the files came from the internet."""
    archive = tmp_path / "mine.excmp"
    archive.write_bytes(b"archive")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_bytes(b"local")

    assert propagate(archive, out) == 0
    assert read_zone(out / "a.txt") is None


@windows_only
def test_directories_are_skipped(tmp_path):
    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    write_zone(archive, INTERNET_ZONE)
    out = tmp_path / "out"
    (out / "empty_dir").mkdir(parents=True)
    assert propagate(archive, out) == 0


@windows_only
def test_a_zone_already_on_an_extracted_file_is_replaced_not_merged(tmp_path):
    """CVE-2025-0411 in one test.

    If an archive smuggles its own Zone.Identifier onto a member, the file
    lands already marked - as local. Propagation must overwrite that with the
    archive's real zone, not leave the attacker's value in place.
    """
    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    write_zone(archive, INTERNET_ZONE)

    out = tmp_path / "out"
    out.mkdir()
    smuggled = out / "evil.exe"
    smuggled.write_bytes(b"payload")
    write_zone(smuggled, "[ZoneTransfer]\r\nZoneId=0\r\n")   # "this is local"

    propagate(archive, out)
    assert read_zone(smuggled) == INTERNET_ZONE, "the smuggled zone survived"


def test_propagation_never_raises_on_a_filesystem_without_streams(tmp_path, monkeypatch):
    """FAT32 and exFAT have no ADS. A USB stick is not an error condition, and
    a failed mark must not fail the extraction that produced the files."""
    import excmp.motw as motw

    archive = tmp_path / "a.excmp"
    archive.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_bytes(b"content")

    monkeypatch.setattr(motw, "read_zone", lambda p: INTERNET_ZONE)

    def refuse(*a, **kw):
        raise OSError(1, "The request is not supported")

    monkeypatch.setattr(motw, "write_zone", refuse)
    assert propagate(archive, out) == 0      # reported, not raised


def test_propagating_from_a_missing_archive_is_harmless(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert propagate(tmp_path / "gone.excmp", out) == 0


# ---------------------------------------------------------------------------
# The rule that is not about correctness but about how the job is done
# ---------------------------------------------------------------------------

def test_no_shell_is_ever_used_to_write_a_mark():
    """PeaZip shipped a PowerShell-injection CVE doing exactly this job by
    shelling out. This module must have no subprocess in it at all - the
    filename is attacker-controlled, and a shell would make that an execution
    primitive."""
    import ast

    tree = ast.parse(Path("excmp/motw.py").read_text(encoding="utf-8"))

    # Parse rather than grep: the module docstring explains *why* subprocess is
    # absent, and a substring check flagged that prose as the violation. The
    # question is what the code does, so ask the code.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in {"subprocess", "os"}, (
                    f"motw.py imports {alias.name} - this job is file I/O only")
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in {"subprocess"}, (
                f"motw.py imports from {node.module}")
        elif isinstance(node, ast.Call):
            target = ast.unparse(node.func)
            for forbidden in ("system", "popen", "Popen", "exec", "run"):
                assert not target.endswith(forbidden), (
                    f"motw.py calls {target}() - no process may be spawned here")
