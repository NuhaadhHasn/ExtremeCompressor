"""Removing a scratch directory that contains read-only files (K5).

Every temp cleanup in this engine used ``shutil.rmtree(path, ignore_errors=True)``,
which on Windows **cannot delete a read-only file** and, because of the flag,
says nothing about it. Git writes loose objects read-only, so archiving or
restoring any tree containing a ``.git`` left a scratch directory behind on
every run - found 2026-09-06 by listing temp after a real 55,477-file job and
noticing two folders that should not have been there.

``ignore_errors`` is not the mistake by itself. Cleanup runs in ``finally:``
blocks, on the failure path, and after a cancel; raising there would replace a
useful error with a confusing one. The mistake is that "ignore errors" was
doing double duty as "handle the expected error", and the expected error had a
fix: clear the read-only bit and try once more.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def _make_writable(path: str) -> bool:
    """Clear the read-only bit. True if something might have changed."""
    try:
        mode = os.stat(path, follow_symlinks=False).st_mode
    except OSError:
        return False
    try:
        os.chmod(path, mode | stat.S_IWRITE | stat.S_IWUSR)
    except OSError:
        return False
    return True


def _within(root: str, candidate: str) -> bool:
    """Is ``candidate`` ``root`` itself or somewhere beneath it?"""
    try:
        return os.path.commonpath([os.path.abspath(root),
                                   os.path.abspath(candidate)]) == \
            os.path.abspath(root)
    except (OSError, ValueError):
        return False


def _onexc(func, path, _exc, root: str = "") -> None:
    """rmtree error hook: make the entry writable and retry the operation.

    Retries ``func`` rather than the whole walk, because rmtree calls this
    from inside its own recursion and expects to carry on. A read-only
    *directory* fails differently from a read-only file - the directory's own
    permission bits block the unlink of its children - so the same treatment
    is applied to whatever path was handed over, file or directory.

    ``root`` bounds the walk-up. Without it, a failure on the outermost entry
    made ``os.path.dirname(path)`` the root's *container*, and at eight of the
    eleven call sites that container is ``ctx.temp_dir`` - a path the user
    types into the GUI, not anything this engine created. So a job directory
    somebody still held a handle inside caused us to clear the read-only
    attribute on the user's own temp folder. `shutil.rmtree(ignore_errors=True)`
    never touched anything outside the tree it was given, and replacing it must
    not change that.

    Anything still failing after that is swallowed, which is the behaviour the
    call sites had before and still want: a scratch directory that cannot be
    removed must not turn a finished job into a failed one.
    """
    if not _make_writable(path):
        return
    try:
        func(path)
    except OSError:
        parent = os.path.dirname(path)
        # Only ever *inside* the tree we were asked to remove. The line is a
        # heuristic for read-only intermediate directories, which are always
        # inside it, so the guard costs nothing.
        if parent and root and _within(root, parent) and _make_writable(parent):
            try:
                func(path)
            except OSError:
                pass


def rmtree_force(path: str | Path) -> None:
    """Remove ``path`` and everything under it, read-only entries included.

    Never raises, so it is safe in a ``finally:``. A path that does not exist
    is not an error - most call sites run on the failure path too, where the
    directory may never have been created.
    """
    target = Path(path)
    if not target.exists():
        return
    # `onexc` replaced `onerror` in 3.12 and `onerror` warns there; this
    # project targets 3.11-3.13, so both spellings have to be supported.
    root = str(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=lambda f, p, exc: _onexc(f, p, exc, root))
    else:  # pragma: no cover - exercised on 3.11 only
        shutil.rmtree(target, onerror=lambda f, p, _e: _onexc(f, p, None, root))
    if target.exists():
        # One more pass. A tree deep in read-only directories can need the
        # parents cleared before the children become removable, and rmtree
        # walks top-down.
        for entry in sorted(target.rglob("*"), reverse=True):
            _make_writable(str(entry))
        _make_writable(str(target))
        shutil.rmtree(target, ignore_errors=True)
