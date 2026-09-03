"""G3 — split an archive into volumes, and join it back.

Pure-Python chunking rather than ``7z -v``, because an ``.excmp`` is not a
bare ``.7z``: it is a zip container holding a manifest and a payload. Letting
7-Zip own the split would make the part format a 7-Zip detail rather than
ours, and joining would then need 7-Zip present just to read our own archive.

The design is deliberately dull, which is the point. Parts are
``<archive>.001``, ``.002``, …; they concatenate to exactly the original
bytes; and **nothing about the container changes**. Join first, then the
ordinary reader runs — so every guarantee the container already makes is
untouched, and a split archive is not a second format to reason about.

Per-part SHA-256 goes in a ``.sha256`` sidecar in ``sha256sum`` layout, the
same format G6 uses for whole archives, so ``sha256sum -c`` works on it with
no tool of ours. It is a **convenience, not a correctness requirement**: it
exists so a failed transfer can say *which* part to fetch again instead of
"this archive is broken". Joining works without it; the container's own
manifest and the D9 restore are what actually decide whether the data is good.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: ``.001`` … ``.999``. Zero-padded so a plain lexical sort is also the join
#: order — which is what every file manager, FTP listing and shell glob uses.
PART_SUFFIX_WIDTH = 3

#: With a 3-digit suffix. Rolling over to ``.1000`` would sort before ``.101``
#: and silently reorder the archive, so it is refused at split time instead.
MAX_PARTS = 999

_COPY_CHUNK = 1 << 20


class VolumeError(RuntimeError):
    """A split or join could not be completed. The message names the part."""


_UNITS = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}


def parse_size(text: str) -> int:
    """``"100m"`` -> 104857600. Accepts a bare number as bytes.

    Binary units, because that is what every archiver and every "4 GB FAT32
    limit" conversation means, and quietly using 10^9 would produce volumes
    that do not fit the thing they were sized for.
    """
    raw = str(text).strip().lower().replace("ib", "").replace("b", "")
    if not raw:
        raise VolumeError("no size given")
    unit = _UNITS.get(raw[-1:], 1)
    digits = raw[:-1] if unit != 1 else raw
    try:
        value = float(digits)
    except ValueError:
        raise VolumeError(
            f"could not read {text!r} as a size - try 100m, 4g or a plain "
            f"number of bytes") from None
    size = int(value * unit)
    if size <= 0:
        raise VolumeError(f"size must be positive, got {text!r}")
    return size


def _suffix(index: int) -> str:
    return str(index).zfill(PART_SUFFIX_WIDTH)


def is_first_part(path: Path) -> bool:
    return path.suffix == "." + _suffix(1)


def base_of(first_part: Path) -> Path:
    """``a.excmp.001`` -> ``a.excmp``."""
    return first_part.with_suffix("")


#: The volume digests go in `<archive>.volumes.sha256`, **not**
#: `<archive>.sha256`.
#:
#: The latter is G6's whole-archive transport sidecar, and using it here was a
#: silent collision: the CLI writes G6's file immediately after publication and
#: then splits, so `write_parts_sidecar` overwrote it. A user who asked for a
#: checksum of the archive got a checksum of its parts instead, with nothing
#: saying so. Both are useful and they describe different files, so they get
#: different names.
VOLUMES_SIDECAR_SUFFIX = ".volumes.sha256"


def sidecar_for(first_part: Path) -> Path:
    return Path(str(base_of(first_part)) + VOLUMES_SIDECAR_SUFFIX)


def part_paths(first_part: Path) -> list[Path]:
    """Every part present on disk, in join order.

    Scans to the **highest** number present rather than stopping at the first
    gap. Stopping early would make a missing middle volume indistinguishable
    from a set that simply ends there, and we would then cheerfully join a
    truncated archive; :func:`join_parts` needs to see the gap in order to
    name it.
    """
    base = base_of(first_part)
    present = {}
    for candidate in first_part.parent.glob(base.name + ".*"):
        tail = candidate.suffix.lstrip(".")
        if len(tail) == PART_SUFFIX_WIDTH and tail.isdigit():
            present[int(tail)] = candidate
    if not present:
        return []
    return [present[i] for i in range(1, max(present) + 1) if i in present]


def missing_parts(first_part: Path) -> list[str]:
    """Names of volumes that should be between the ones we can see."""
    base = base_of(first_part)
    present = set()
    for candidate in first_part.parent.glob(base.name + ".*"):
        tail = candidate.suffix.lstrip(".")
        if len(tail) == PART_SUFFIX_WIDTH and tail.isdigit():
            present.add(int(tail))
    if not present:
        return []
    return [f"{base.name}.{_suffix(i)}"
            for i in range(1, max(present) + 1) if i not in present]


def split_file(archive: Path, part_size: int) -> list[Path]:
    """Write ``archive`` out as numbered parts and return them.

    The source is **left in place**. Splitting is additive: deleting it here
    would make a failed split unrecoverable, and nothing else in this codebase
    modifies an input either.
    """
    archive = Path(archive)
    if part_size <= 0:
        raise VolumeError(f"part size must be positive, got {part_size}")
    total = archive.stat().st_size
    # An exact multiple must not produce a trailing empty part: a part whose
    # absence later would look identical to a truncated set.
    needed = max(1, -(-total // part_size))
    if needed > MAX_PARTS:
        raise VolumeError(
            f"too many parts: {archive.name} would need {needed} volumes at "
            f"{part_size} bytes, and the numbering stops at {MAX_PARTS}")

    parts: list[Path] = []
    try:
        with archive.open("rb") as src:
            for index in range(1, needed + 1):
                target = Path(str(archive) + "." + _suffix(index))
                remaining = part_size
                with target.open("wb") as dst:
                    while remaining:
                        chunk = src.read(min(_COPY_CHUNK, remaining))
                        if not chunk:
                            break
                        dst.write(chunk)
                        remaining -= len(chunk)
                parts.append(target)
    except BaseException:
        # A half-written volume set is worse than none: the parts look real.
        for stale in parts:
            stale.unlink(missing_ok=True)
        raise
    return parts


def write_parts_sidecar(parts: list[Path]) -> Path:
    """`sha256sum`-layout digests for every part, beside the first one.

    Names are bare filenames, not paths, so the file still verifies after the
    set is moved or downloaded into a different folder — the same reasoning as
    G6's whole-archive sidecar.
    """
    lines = []
    for part in parts:
        digest = hashlib.sha256()
        with part.open("rb") as fh:
            for block in iter(lambda: fh.read(_COPY_CHUNK), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {part.name}")
    target = sidecar_for(parts[0])
    # newline="\n" is load-bearing, not tidiness: without it Python translates
    # to CRLF on Windows, `sha256sum -c` reads the trailing \r as part of the
    # filename, and every line fails with "No such file or directory". A
    # sidecar whose whole purpose is that one command has to survive it.
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return target


def _expected_digests(first_part: Path) -> dict[str, str]:
    sidecar = sidecar_for(first_part)
    if not sidecar.exists():
        return {}
    out: dict[str, str] = {}
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if digest and name:
            out[name.strip()] = digest.strip()
    return out


def join_parts(first_part: Path, destination: Path) -> Path:
    """Concatenate a volume set back into one file.

    Refuses rather than guesses. A gap in the numbering, a part that does not
    match its recorded digest, or being handed anything other than ``.001``
    all raise :class:`VolumeError` naming the part at fault — because the
    thing that actually goes wrong with a split archive is one part failing to
    download, and "which one" is the only useful thing to say about it.
    """
    first_part, destination = Path(first_part), Path(destination)
    if not is_first_part(first_part):
        raise VolumeError(
            f"start from the first volume: expected a name ending "
            f"'.{_suffix(1)}', got {first_part.name!r}")

    parts = part_paths(first_part)
    if not parts:
        raise VolumeError(f"no volumes found beside {first_part.name}")

    # A hole in the numbering, checked before anything is read. This is the
    # case that needs no sidecar to detect: volume 3 exists, volume 2 does not,
    # so the set is provably incomplete whatever the sidecar says.
    gaps = missing_parts(first_part)
    if gaps:
        raise VolumeError(
            f"volume {gaps[0]} is missing; the archive is incomplete "
            f"({len(gaps)} of {len(parts) + len(gaps)} volumes absent)")

    expected = _expected_digests(first_part)
    if expected:
        # The sidecar knows how many there should be, which is the only way to
        # tell a complete set from one missing its tail.
        for name in expected:
            if not (first_part.parent / name).exists():
                raise VolumeError(
                    f"volume {name} is missing; the archive is incomplete")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as dst:
            for part in parts:
                digest = hashlib.sha256()
                with part.open("rb") as src:
                    for block in iter(lambda: src.read(_COPY_CHUNK), b""):
                        digest.update(block)
                        dst.write(block)
                want = expected.get(part.name)
                if want and digest.hexdigest() != want:
                    raise VolumeError(
                        f"volume {part.name} does not match its recorded "
                        f"SHA-256 - re-fetch that part")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination
