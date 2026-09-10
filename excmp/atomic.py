"""D8: the last three feet between a verified archive and a durable one.

Every output in this program is written to a `.tmp` twin and renamed, and
since D9 the `.excmp` is fully restored and hash-compared before that rename.
This module closes what was still missing between the two.

**The flush.** `os.replace` publishes a *directory entry*. It says nothing
about whether the bytes it points at have reached the device: on Windows they
sit in the system cache until the filesystem chooses to write them, which can
be well after the job has reported success. `fsync` (FlushFileBuffers) before
the rename is the only thing that makes "done" mean "on the disk".

**The read-back.** Nothing re-read the artifact after writing it. The failure
that hides there is the short write - a volume that filled between the verify
and the publish - and it announces itself through no exit code and no
exception. Hashing the file back off the filesystem *after* the flush is what
turns it into a refusal.

**The rename.** `compress()` used to `unlink()` the destination and then
rename onto it. `os.replace` replaces an existing file atomically on both
Windows and POSIX, so that unlink bought nothing and opened a window in which
a user overwriting yesterday's archive had neither file. If the rename then
failed - and this is the one moment a whole job's worth of work is on the line
- the only copy was already gone.

**What this cannot do on Windows, stated rather than implied.** A POSIX
implementation would also `fsync` the *directory* so the rename itself is
durable; Windows has no handle you can open on a directory to flush, so the
rename's metadata durability is the filesystem's business. The file's contents
are flushed, which is the half that decides whether the archive is readable at
all.

**Identity instead of a second read.** After the rename we confirm the
destination *is* the file we hashed, by `(st_dev, st_ino, st_size)` rather than
by hashing it again - measured on this machine 2026-09-09: the Windows file ID
survives `os.replace` on the same volume. A rename cannot alter bytes, so this
is a complete check at no I/O cost, where a second hash of a multi-gigabyte
archive would be minutes. When that triple *disagrees* the file is re-hashed
before anything is refused, because `st_ino` is a real file index only on
NTFS - on the FAT32/exFAT a USB stick arrives formatted as it is synthesised,
and a false refusal would condemn a perfectly good archive.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

#: Matches `verify.hash_file`. Big enough that the syscall overhead vanishes,
#: small enough to stay off the large-object heap on the 2-core/16 GB target.
_CHUNK = 1 << 20


class PublishError(RuntimeError):
    """The artifact on disk is not the artifact we meant to publish."""


def fsync_file(path: Path) -> None:
    """Force this file's contents out of the OS cache onto the device.

    Opened read-write because that is what `FlushFileBuffers` requires on
    Windows; a read-only handle fails with access denied.
    """
    fd = os.open(str(path), os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def hash_and_size(path: Path) -> tuple[str, int]:
    """SHA-256 and byte count in one pass over the file."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _identity(path: Path) -> tuple[int, int, int]:
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_size)


def publish(tmp: Path, final: Path, *,
            expect_sha256: str | None = None) -> str:
    """Flush ``tmp``, read it back, and atomically become ``final``.

    Returns the SHA-256 of the published file - which every caller wants
    anyway, for the sidecar or for the history record, and which is now
    measured exactly once for the whole job.

    ``expect_sha256`` is the strong form: pass the digest of what you *meant*
    to write (streamed while writing it, or measured on the artifact a gate
    has already accepted) and a mismatch refuses the publish outright. Without
    it the read-back still proves the file is readable end to end and yields
    its digest, but it cannot know what the bytes should have been.

    When the read-back or the rename fails the `.tmp` is removed and **the
    destination is left exactly as it was** - an existing archive there is the
    user's previous copy, and being left with neither is the failure this
    module exists to prevent.

    The one refusal that cannot promise that is the identity check *after* a
    successful rename: by then a file has been published, and we can only say
    that we no longer know what it is. It is not deleted either, because
    whatever is at that path might be the user's previous archive and
    destroying it on a guess would be the worse of the two mistakes.
    """
    tmp, final = Path(tmp), Path(final)
    fsync_file(tmp)

    digest, size = hash_and_size(tmp)
    if expect_sha256 is not None and digest != expect_sha256:
        tmp.unlink(missing_ok=True)
        raise PublishError(
            f"{final.name} was not written as intended and has not been "
            f"published: expected SHA-256 {expect_sha256[:16]}..., the "
            f"{size:,} bytes actually on disk hash to {digest[:16]}... - "
            f"a truncated write is the usual cause, so check free space on "
            f"{final.parent}")

    before = _identity(tmp)
    # No unlink first. os.replace overwrites atomically; deleting the
    # destination would only widen the window in which neither file exists.
    os.replace(tmp, final)

    if _identity(final) != before:
        # The cheap check disagreed, so pay for the expensive one rather than
        # trusting it. `st_ino` is a real file index on NTFS and survives a
        # rename - measured - but it is a synthesised value on FAT32/exFAT,
        # which is exactly what an archive copied to a USB stick lands on. A
        # false refusal there would condemn a perfectly good archive, so the
        # content is the arbiter and the identity triple is only a way to
        # avoid reading it.
        confirmed, _ = hash_and_size(final)
        if confirmed != digest:
            raise PublishError(
                f"{final} is not the file that was just flushed and renamed "
                f"onto it: it hashes to {confirmed[:16]}..., not "
                f"{digest[:16]}... - something else wrote to that path "
                f"during the publish. Do not trust the file at that path")
    return digest


def atomic_write_bytes(target: Path, data: bytes) -> str:
    """Write ``data`` to ``target`` through a flushed, read-back `.tmp`.

    For the small records - sidecars, the calibration store, the history file
    - where the old copy is worth more than the new one. `write_text` onto the
    live path truncates it first, so an interruption mid-write leaves a
    half-file where a complete record used to be.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        return publish(tmp, target,
                       expect_sha256=hashlib.sha256(data).hexdigest())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(target: Path, text: str, *,
                      encoding: str = "utf-8") -> str:
    """As :func:`atomic_write_bytes`, encoding with LF line endings.

    The newline is not a style choice. Python translates `\\n` to CRLF on
    Windows by default, `sha256sum -c` then reads the trailing CR as part of
    the filename, and every line of the sidecar fails with "No such file or
    directory". Both sidecars in this codebase shipped broken on exactly that
    before 2026-09-02, so encoding here - rather than leaving it to each
    caller - is the point of routing them all through one function.
    """
    return atomic_write_bytes(target, text.encode(encoding))
