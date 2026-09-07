"""K5: a read-only file must not strand a scratch directory.

Found on 2026-09-06 by listing the temp directory after the K1 end-to-end run
and noticing two folders that should not have been there. Each held the same
11 files:

    excmp-verify-i05n75qg/restore/.../rn_first_app/.git/objects/18/1f3cee...
        attrs = ReadOnly, Archive

Git writes loose objects **read-only**, and `shutil.rmtree(ignore_errors=True)`
cannot delete a read-only file on Windows - it swallows the error and walks
away. So every compress or extract of a tree containing a `.git`, or any
read-only file at all, left debris behind on every single run, and
`ignore_errors` guaranteed nobody was ever told.

Why 945 tests were green over it: D3 already asserts temp is clean, and D2
already round-trips read-only attributes. Neither crosses the two. That is the
shape of this defect class - each half tested, the intersection not - and it is
the same shape as K1's own (a check that models something other than the
artifact it protects).
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from excmp.tempclean import rmtree_force


def _readonly_tree(root: Path) -> Path:
    """A tree shaped like the one that caused this: read-only leaves nested
    under ordinary directories, the way git stores loose objects."""
    objects = root / ".git" / "objects" / "18"
    objects.mkdir(parents=True)
    for name in ("1f3cee3bafb30959cbd27842deebe42f818240", "deadbeef"):
        f = objects / name
        f.write_bytes(b"x" * 309)
        os.chmod(f, stat.S_IREAD)
    (root / "normal.txt").write_text("writable", encoding="utf-8")
    return root


def test_the_stdlib_really_does_leave_a_read_only_file_behind(tmp_path):
    """Pin the premise, not just the fix.

    If a future Python makes `rmtree(ignore_errors=True)` handle read-only
    files, this test fails and tells us the workaround is obsolete - which is
    a better outcome than carrying it forever for a reason nobody can check.
    """
    victim = _readonly_tree(tmp_path / "stdlib")
    shutil.rmtree(victim, ignore_errors=True)
    assert victim.exists(), (
        "shutil.rmtree(ignore_errors=True) removed a read-only file - the "
        "premise of K5 no longer holds and rmtree_force may be unnecessary")


def test_rmtree_force_removes_a_read_only_tree(tmp_path):
    victim = _readonly_tree(tmp_path / "scratch")
    rmtree_force(victim)
    assert not victim.exists()


def test_rmtree_force_is_silent_about_a_directory_that_is_not_there(tmp_path):
    """Every call site is in a `finally:` or a cleanup path, so it runs on the
    failure path too - where the directory may never have been created."""
    rmtree_force(tmp_path / "never-existed")


def test_rmtree_force_removes_a_read_only_directory(tmp_path):
    """Not just files: a read-only *directory* blocks the unlink of its
    children on Windows, which is a different errno and a different fix."""
    d = tmp_path / "scratch" / "locked"
    d.mkdir(parents=True)
    (d / "inner.txt").write_text("x", encoding="utf-8")
    os.chmod(d, stat.S_IREAD | stat.S_IEXEC)
    rmtree_force(tmp_path / "scratch")
    assert not (tmp_path / "scratch").exists()


def test_a_compress_of_a_git_tree_leaves_temp_clean(tmp_path):
    """The end-to-end shape, at unit speed. This is the assertion the original
    defect would have failed: not "does rmtree work", but "after a real job,
    is temp empty".

    D3 makes this assertion already; what it never had was a read-only file in
    the fixture.
    """
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = _readonly_tree(tmp_path / "src")
    (src / "notes.txt").write_text("the quick brown fox\n" * 500, encoding="utf-8")
    temp = tmp_path / "temp"
    temp.mkdir()

    engine.compress([src], tmp_path / "out.excmp", Profile.FAST,
                    StageContext(temp_dir=temp))

    leftovers = sorted(p.name for p in temp.iterdir())
    assert leftovers == [], f"compress left {leftovers} behind in temp"


def test_an_extract_of_a_git_tree_leaves_temp_clean(tmp_path):
    """The other half, and the one the real run actually tripped: the leaked
    directories were named `excmp-verify-*`, i.e. the restore side."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = _readonly_tree(tmp_path / "src")
    (src / "notes.txt").write_text("lorem ipsum\n" * 500, encoding="utf-8")
    archive = tmp_path / "out.excmp"
    temp = tmp_path / "temp"
    temp.mkdir()
    engine.compress([src], archive, Profile.FAST, StageContext(temp_dir=temp))

    engine.extract(archive, tmp_path / "restored", StageContext(temp_dir=temp))

    leftovers = sorted(p.name for p in temp.iterdir())
    assert leftovers == [], f"extract left {leftovers} behind in temp"
