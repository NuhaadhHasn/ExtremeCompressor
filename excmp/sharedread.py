"""Open a source file for the one read that both archives and hashes it.

A digest taken from the same read that fills the archive proves that the
archive holds what was read. It does not prove that what was read was ever a
state of the file: a program rewriting the file in place, at the same size,
while that read runs leaves half old bytes and half new ones, and the digest
agrees with them. Reading every file twice (hash, then copy) is what used to
catch that, because the two reads disagreed; one read cannot disagree with
itself. (Review, 2026-11-26: a 48 MiB file rewritten by another thread was
published torn at Fast.)

So the single read is only taken under a guarantee that makes it sound: the
file is opened with **writers denied** - ``FILE_SHARE_READ`` and nothing
else - and Windows then refuses every attempt to open it for writing until
the handle is closed. Other readers are not affected.

:func:`open_for_archive` returns the open file and one of three words:

``STABLE``
    Writers are denied for the life of the handle. One read is enough.
``BUSY``
    Somebody already has the file open for writing, so they cannot be denied.
    The file is readable, and the caller must go the old way for it: hash it
    by one read and archive it by a second, so a change between the two
    refuses the job as it always did.
``PLAIN``
    There are no share modes to ask for (not Windows), or the Win32 call
    itself could not be made. An ordinary open, read once, as before this
    module existed.

A file that cannot be opened for reading at all raises the ``OSError`` a
plain ``open`` raises, so the caller's locked-file handling (K3) sees exactly
what it always saw.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import BinaryIO

STABLE = "stable"
BUSY = "busy"
PLAIN = "plain"

_WINDOWS = sys.platform == "win32"

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_ERROR_SHARING_VIOLATION = 32

_kernel32 = None


class _Refused(Exception):
    """CreateFileW said no; ``code`` is GetLastError."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _open_denying_writers(path: str) -> BinaryIO:
    """``path`` open for reading with ``FILE_SHARE_READ`` only.

    Raises :class:`_Refused` when Windows declines, and anything else when
    the call could not be made at all.
    """
    global _kernel32
    import ctypes
    import msvcrt
    from ctypes import wintypes

    if _kernel32 is None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        _kernel32 = k32
    k32 = _kernel32
    handle = k32.CreateFileW(path, _GENERIC_READ, _FILE_SHARE_READ, None,
                             _OPEN_EXISTING,
                             _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_SEQUENTIAL_SCAN,
                             None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise _Refused(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        k32.CloseHandle(handle)
        raise
    try:
        return open(fd, "rb")           # closing it closes the handle
    except BaseException:
        os.close(fd)
        raise


def open_for_archive(path: Path) -> tuple[BinaryIO, str]:
    """Open ``path`` for reading and say how far one read of it can be
    trusted: ``(file, STABLE | BUSY | PLAIN)``. See the module docstring.

    Raises the ``OSError`` of a plain ``open`` when the file cannot be read.
    """
    name = os.fspath(path)
    if not _WINDOWS:
        return open(name, "rb"), PLAIN
    try:
        return _open_denying_writers(name), STABLE
    except _Refused:
        # Refused for a reason that belongs to the file. Whatever the reason
        # - a writer has it open (sharing violation), or a path form this
        # call does not take - an ordinary open is the judge of whether it
        # can be read: if it cannot, that error is the caller's to handle;
        # if it can, writers were NOT denied, and the caller reads it twice.
        return open(name, "rb"), BUSY
    except Exception:                               # noqa: BLE001
        # The call could not be made at all. Not the file's fault, and not a
        # reason to stop archiving: an ordinary open, as before.
        return open(name, "rb"), PLAIN
