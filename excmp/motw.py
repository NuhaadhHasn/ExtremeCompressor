"""F4 — carrying the Mark of the Web onto extracted files.

Windows attaches a ``Zone.Identifier`` alternate data stream to anything it
downloads, and SmartScreen, Office's Protected View and Defender all key off
it. **Extracting a downloaded archive does not carry that mark to the files
inside**, so an executable that arrived from the internet lands on disk
looking exactly like one the user wrote themselves. That gap is what
CVE-2025-0411 was about.

7-Zip's CLI leaves this **off** by default (``-snz`` turns it on). Ours is on,
because a downloaded archive is the ordinary case and the safe behaviour
should not be the one you have to know a switch for.

Three rules, each with a specific history behind it:

**Direct file I/O, never a shell.** PeaZip shipped a PowerShell-injection CVE
doing precisely this job by shelling out (research/17 §5). An alternate data
stream is reachable as ``open(path + ":Zone.Identifier")`` — about forty lines,
and no shell to inject into. A test asserts the word ``subprocess`` does not
appear in this file, because the filename here is attacker-controlled and a
shell would turn that into an execution primitive.

**Never trust a zone stored inside the archive.** A crafted archive can carry
its own ``Zone.Identifier`` for a member; on extraction the file arrives
already marked as *local*, which is a downgrade. :func:`propagate` always
overwrites. (``excmp.safepath`` separately refuses any member name containing
``:``, so this is the second lock on the same door.)

**Failing to write a mark is not a failure.** FAT32 and exFAT have no
alternate data streams at all. Extracting to a USB stick is not an error
condition, and a missing mark must never fail the extraction that produced the
files.
"""

from __future__ import annotations

from pathlib import Path

#: The stream Windows itself uses. Not configurable — every consumer of this
#: information (SmartScreen, Protected View, Defender) looks for this name.
ZONE_STREAM = "Zone.Identifier"

#: A real Zone.Identifier is a few hundred bytes: a section header, a ZoneId,
#: usually a HostUrl. Anything larger is not describing a zone, and reading it
#: whole is the sort of thing a hostile archive would like us to do. NanaZip
#: uses the same 32 KB cap (research/14 §5).
MAX_ZONE_BYTES = 32 * 1024

#: Zone 3 is "Internet". Written when we know the archive came from the web but
#: cannot recover the original host.
INTERNET_ZONE_MINIMAL = "[ZoneTransfer]\r\nZoneId=3\r\n"


def ads_path(target: Path) -> Path:
    """The alternate-data-stream path for a file's zone mark."""
    return Path(f"{target}:{ZONE_STREAM}")


def read_zone(target: Path) -> str | None:
    """The file's Zone.Identifier, or None if it has none.

    Never raises. A file with no stream, a filesystem with no streams at all,
    and a file that is not there produce the same answer — "no mark" — because
    all three mean the same thing to the caller.
    """
    try:
        with open(ads_path(target), "rb") as fh:
            raw = fh.read(MAX_ZONE_BYTES)
    except OSError:
        return None
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace")


def write_zone(target: Path, zone: str) -> None:
    """Attach ``zone`` to ``target``, replacing any existing mark.

    Raises OSError on a filesystem without streams; :func:`propagate` is what
    decides that is acceptable. Kept raising here so a caller that genuinely
    needs to know can find out.
    """
    data = zone.encode("utf-8")[:MAX_ZONE_BYTES]
    with open(ads_path(target), "wb") as fh:
        fh.write(data)


def propagate(archive: Path, out_dir: Path) -> int:
    """Copy the archive's zone onto every file extracted from it.

    Returns how many files were marked. Zero is a perfectly normal answer: the
    archive was not downloaded, or the destination filesystem has no streams.

    Never raises. This runs *after* a successful extraction, and a file that
    could not be marked is still a file the user correctly received — failing
    the whole job over a missing ADS would trade a real result for a cosmetic
    one.
    """
    archive, out_dir = Path(archive), Path(out_dir)
    zone = read_zone(archive)
    if not zone:
        # Not downloaded, or we cannot tell. Inventing a mark would be a claim
        # about provenance we have no basis for.
        return 0

    marked = 0
    for path in out_dir.rglob("*"):
        if not path.is_file():
            continue          # directories carry no mark of their own
        try:
            write_zone(path, zone)
        except OSError:
            continue          # no streams on this volume; not an error
        marked += 1
    return marked
