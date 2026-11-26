"""Plain tar stage: turns a tree into the single file that byte-oriented
stages (precomp, srep) need as input. No compression here by design."""

from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path
from typing import Callable, Iterable

from .. import sharedread
from .base import Stage, StageContext, StageError

#: One source file for :func:`add_hashed`: where it is, and its archive name.
Entry = tuple[Path, str]
#: Called once per file that went in: ``(source, sha256, bytes)``.
OnAdded = Callable[[Path, str, int], None]
#: Called for a file that could not be opened; nothing of it was written.
OnUnreadable = Callable[[Path, OSError], None]

#: Read size for the copy into the tar. The bytes written do not depend on it.
_COPY_BUFFER = 1 << 20

#: The extensions for which CPython's ``os.stat(path)`` sets the execute bits
#: on Windows (``.bat``, ``.cmd``, ``.exe``, ``.com``).
_WINDOWS_EXECUTABLE = frozenset({".bat", ".cmd", ".exe", ".com"})


class SourceUnreadable(Exception):
    """A source file could not be opened. Nothing of it has been written, so
    the caller may leave it out and carry on (K3)."""

    def __init__(self, path: Path, exc: OSError):
        super().__init__(f"{path}: {exc}")
        self.path = Path(path)
        self.exc = exc


class SourceReadError(StageError):
    """A source file failed *while* it was being read into the tar.

    Its header and some of its bytes are already in the stream, so the stream
    cannot be kept. The engine starts the stage again without that file,
    which is the outcome K3 gives a file that cannot be opened: skipped,
    reported, and the rest of the job survives.
    """

    def __init__(self, path: Path, exc: OSError):
        super().__init__(f"{path}: could not be read ({exc})")
        self.path = Path(path)
        self.exc = exc


class _HashingReader:
    """Hashes exactly the bytes `tarfile` takes from the source file."""

    def __init__(self, fh, path: Path):
        self._fh = fh
        self._path = path
        self._hash = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        try:
            data = self._fh.read(size)
        except OSError as exc:
            raise SourceReadError(self._path, exc) from exc
        self._hash.update(data)
        self.count += len(data)
        return data

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def add_hashed(tar: tarfile.TarFile, path: Path, arcname: str) -> tuple[str, int]:
    """Add one file to ``tar`` and return the SHA-256 and size of the bytes
    that went in.

    The digest is taken from the very buffers handed to the tar writer, so it
    cannot describe anything but the archived bytes: there is one read of the
    file, not a hashing read followed by a copying read that might see a
    different file.

    **That one read is taken with writers denied** (`sharedread`), which is
    what makes it a state the file really had: nothing can rewrite the file
    in place while it is being read. When writers cannot be denied because
    another program already has the file open for writing, the file is read
    twice instead, as it was before there was a single read - hashed whole,
    then archived - and the job is refused if the two reads differ.

    The header is built from an ``fstat`` of the open handle, so the size in
    it is the size of the file being read. A file that turns out shorter than
    that raises (`tarfile` refuses a short member); a longer one contributes
    exactly the declared bytes, which are the ones hashed.

    Three failures, kept apart because they mean different things:

    * the file cannot be opened: :class:`SourceUnreadable`, raised before
      anything is written;
    * a read fails part-way: :class:`SourceReadError`;
    * writing the tar fails (a full disk): the ``OSError`` itself, untouched.
    """
    try:
        fh, how = sharedread.open_for_archive(path)
    except OSError as exc:
        raise SourceUnreadable(Path(path), exc) from exc
    first_read: str | None = None
    if how == sharedread.BUSY:
        # Nothing has been written yet, so a failure here is still a skip.
        try:
            with fh:
                first_read = _digest_of(fh)
            fh = open(path, "rb")
        except OSError as exc:
            raise SourceUnreadable(Path(path), exc) from exc
    with fh:
        try:
            info = tar.gettarinfo(arcname=arcname, fileobj=fh)
        except OSError as exc:
            raise SourceUnreadable(Path(path), exc) from exc
        if info is None or not info.isreg():
            raise StageError(f"tar: {arcname} is not a regular file")
        if os.name == "nt" and arcname[-4:].lower() in _WINDOWS_EXECUTABLE:
            # A stat by *name* marks these executable on Windows; the stat of
            # a handle cannot, having no name to look at. The staged tree was
            # stat-ed by name, so this keeps the header what it always was.
            info.mode |= 0o111
        reader = _HashingReader(fh, Path(path))
        try:
            tar.addfile(info, reader)
        except OSError as exc:
            if reader.count < info.size and exc.errno is None:
                # `tarfile` raises a bare OSError("unexpected end of data")
                # when the file gave fewer bytes than its header declares.
                raise StageError(
                    f"tar: {arcname} changed while it was being archived "
                    f"({reader.count} of {info.size} bytes read)") from exc
            raise
        if reader.count != info.size:      # tarfile enforces it; so do we
            raise StageError(f"tar: {arcname} was not archived completely")
        if first_read is not None and reader.hexdigest() != first_read:
            raise StageError(
                f"tar: {arcname} changed while it was being archived (another "
                f"program has it open for writing) - nothing was published")
        return reader.hexdigest(), info.size


def _digest_of(fh) -> str:
    digest = hashlib.sha256()
    while chunk := fh.read(_COPY_BUFFER):
        digest.update(chunk)
    return digest.hexdigest()


def add_all_hashed(tar: tarfile.TarFile, entries: Iterable[Entry],
                   ctx: StageContext, stage_id: str, on_added: OnAdded,
                   on_unreadable: OnUnreadable) -> None:
    """`add_hashed` over ``entries``, in the order given."""
    for path, arcname in entries:
        if ctx.cancel.is_set():
            raise StageError(f"{stage_id}: cancelled")
        try:
            digest, size = add_hashed(tar, path, arcname)
        except SourceUnreadable as skip:
            on_unreadable(skip.path, skip.exc)
            continue
        on_added(Path(path), digest, size)


class TarStage(Stage):
    id = "tar"

    def available(self) -> bool:
        return True

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        files = [p for p in ([src] if src.is_file() else sorted(src.rglob("*"))) if p.is_file()]
        with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT) as tar:
            for p in files:
                if ctx.cancel.is_set():
                    raise StageError(f"{self.id}: cancelled")
                arcname = p.name if src.is_file() else str(p.relative_to(src))
                tar.add(p, arcname=arcname, recursive=False)
        ctx.progress_cb(self.id, 100.0)
        return dst

    def compress_files(self, entries: list[Entry], dst: Path, ctx: StageContext,
                       on_added: OnAdded, on_unreadable: OnUnreadable,
                       total_bytes: int = 0) -> Path:
        """The same tar `compress` writes for a staged copy of ``entries``,
        read straight from the sources and hashed on the way (see
        :func:`add_hashed`). ``dereference`` stops `tarfile` turning a second
        hard link to one file into a link member with no bytes of its own."""
        dst = Path(dst)
        with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT, dereference=True,
                          copybufsize=_COPY_BUFFER) as tar:
            add_all_hashed(tar, entries, ctx, self.id, on_added, on_unreadable)
        ctx.progress_cb(self.id, 100.0)
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        with tarfile.open(src, "r") as tar:
            tar.extractall(dst, filter="data")
        ctx.progress_cb(self.id, 100.0)
        return dst
