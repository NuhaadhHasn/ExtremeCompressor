"""Defects found by auditing the K2/K4/K5 diff before it was committed.

Eight of them, each reproduced by *running* the code rather than reading it.
They are grouped here rather than scattered into the four feature files because
what they have in common is more instructive than what they touch: **every one
is a new code path that cannot fail safely.**

K2 added two restore-time passes and K4 changed a codec, and between them they
introduced a restore that reports failure after verifying every byte, an
`extract` that aborts on an integer, a count that says "4 files restored" beside
"2 hashes verified", a cleanup that reaches outside the directory it was told to
delete, and an estimator that now sits 18% outside its own range. None of those
were caught by 978 passing tests.
"""

from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.manifest import MANIFEST_NAME
from excmp.planner import Profile
from excmp.stages.base import StageContext


def _tree_with_empty_dirs(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "text.txt").write_text("the quick brown fox\n" * 2000, encoding="utf-8")
    (root / "rand.bin").write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))
    (root / "emptydir").mkdir()
    (root / "deep" / "empty" / "chain").mkdir(parents=True)
    return root


def _archive(tmp_path: Path) -> Path:
    src = _tree_with_empty_dirs(tmp_path / "src")
    arc = tmp_path / "out.excmp"
    engine.compress([src], arc, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    return arc


def _rewrite_manifest(archive: Path, mutate) -> Path:
    """Copy an archive, applying ``mutate`` to its parsed manifest."""
    out = archive.with_name(archive.stem + "-x" + archive.suffix)
    with zipfile.ZipFile(archive) as src:
        data = json.loads(src.read(MANIFEST_NAME).decode("utf-8"))
        mutate(data)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as dst:
            dst.writestr(MANIFEST_NAME, json.dumps(data))
            for info in src.infolist():
                if info.filename == MANIFEST_NAME:
                    continue
                dst.writestr(info, src.read(info.filename),
                             compress_type=info.compress_type)
    return out


# --------------------------------------------------------------------------
# K2's two restore-time passes must not be able to fail the restore
# --------------------------------------------------------------------------

def test_an_undeletable_empty_dir_does_not_fail_a_verified_restore(tmp_path):
    """CRITICAL. `_restore_empty_dirs` ran an unguarded
    `mkdir(parents=True)` at the very end of `extract` - after
    `extract_stored`, after `verify_restore`, after MOTW propagation. Any
    OSError there propagated out, so a restore whose **every byte verified
    byte-identical** was reported to the user as a failure: the CLI printed
    `error:` and exited 1, the GUI painted the tab red.

    No hostile archive is needed. An ordinary archive holding
    `src/deep/empty/chain`, restored into a destination that already has a
    *file* where a parent of that chain must go, is enough.

    The policy is already written down in `_apply_mtimes`' own docstring: a
    file whose bytes verified is a successful restore, and cosmetic metadata we
    could not apply does not undo that. An empty directory is cosmetic in
    exactly the same way.
    """
    arc = _archive(tmp_path)
    out = tmp_path / "restored"
    (out / "src").mkdir(parents=True)
    (out / "src" / "deep").write_text("in the way", encoding="utf-8")

    result = engine.extract(arc, out, StageContext(temp_dir=tmp_path / "t2"))

    assert result.verified == 2, "the payload must still restore and verify"
    assert (out / "src" / "text.txt").is_file()


def test_a_hostile_mtime_does_not_abort_a_finished_restore(tmp_path):
    """MAJOR. `mtime_ns` is archive-supplied and was range-checked only for
    `isinstance(int)` and `> 0`. `os.utime(ns=...)` raises **OverflowError**
    for a value beyond `time_t`, and OverflowError is an `ArithmeticError`, not
    an `OSError` - so `except OSError: continue` did not catch it and `extract`
    aborted with a raw traceback *after* the restore had completed and
    verified. Exactly what the docstring promises cannot happen.
    """
    arc = _archive(tmp_path)

    def blow_up(data):
        for meta in data["inputs"].values():
            meta["mtime_ns"] = 10 ** 30
    hostile = _rewrite_manifest(arc, blow_up)

    result = engine.extract(hostile, tmp_path / "out",
                            StageContext(temp_dir=tmp_path / "t2"))
    assert result.verified == 2


def test_a_boolean_mtime_is_not_treated_as_a_timestamp(tmp_path):
    """`True` is an `int` in Python, so `"mtime_ns": true` passed the guard and
    stamped the file to 1 nanosecond after the epoch. A bool is not a
    timestamp; leaving the restore-time mtime alone is the honest answer."""
    arc = _archive(tmp_path)

    def boolify(data):
        for meta in data["inputs"].values():
            meta["mtime_ns"] = True
    hostile = _rewrite_manifest(arc, boolify)

    out = tmp_path / "out"
    engine.extract(hostile, out, StageContext(temp_dir=tmp_path / "t2"))
    stamped = (out / "src" / "text.txt").stat().st_mtime_ns
    assert stamped > 10 ** 15, f"a bool was applied as a timestamp: {stamped}"


# --------------------------------------------------------------------------
# the count the user is shown
# --------------------------------------------------------------------------

def test_files_restored_counts_files_not_directories(tmp_path):
    """MAJOR, and a rendering bug of the kind that has bitten this project
    before. `restored += _restore_empty_dirs(...)` folded a *directory* count
    into a field that has always meant "ledger entries written back" and was
    equal to `verified` for every ledger-backed archive.

    A 2-file tree with 2 empty directories reported `files_restored=4,
    verified=2`, and that number is rendered verbatim in four places - the GUI
    results hero ("Restored 4 files" beside "2 SHA-256 hashes verified"), the
    extract tab, the CLI, and the D9 self-test log.

    It also silently broke the invariant two existing tests assert; they passed
    only because neither fixture happened to contain an empty directory.
    """
    arc = _archive(tmp_path)
    out = tmp_path / "out"
    result = engine.extract(arc, out, StageContext(temp_dir=tmp_path / "t2"))

    on_disk = [p for p in out.rglob("*") if p.is_file()]
    assert result.files_restored == len(on_disk) == 2
    assert result.verified == result.files_restored
    # ...and the directories really were recreated; the count is what changed.
    assert (out / "src" / "emptydir").is_dir()
    assert (out / "src" / "deep" / "empty" / "chain").is_dir()


# --------------------------------------------------------------------------
# `dirs` is archive-supplied, so it is untrusted (D0)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    {"pwn/deep/whatever": 1, "another": 2},   # a dict iterates its keys
    "abc",                                    # a string iterates characters
    [123, None],                              # non-str members
])
def test_a_malformed_dirs_field_creates_nothing(tmp_path, value):
    """`for rel in dirs or []` iterated whatever JSON put in the field, and
    `from_json` does `cls(**data)` with no coercion. A dict created directories
    named after its keys; a bare string created `a/`, `b/`, `c/`. safepath
    still held - nothing escaped `out_dir` - so this was junk in the
    destination rather than a traversal, but it is archive-controlled
    filesystem writes with names that were never in any archive, plus a
    correspondingly inflated count."""
    arc = _archive(tmp_path)
    hostile = _rewrite_manifest(arc, lambda d: d.__setitem__("dirs", value))
    out = tmp_path / "out"
    try:
        engine.extract(hostile, out, StageContext(temp_dir=tmp_path / "t2"))
    except Exception:
        pass          # refusing is also an acceptable answer
    junk = {p.name for p in out.rglob("*") if p.is_dir()}
    for bad in ("pwn", "another", "a", "b", "c"):
        assert bad not in junk, f"created {bad!r} from a malformed dirs field"


# --------------------------------------------------------------------------
# K5's cleanup must stay inside the tree it was given
# --------------------------------------------------------------------------

def test_rmtree_force_never_touches_anything_outside_its_target(tmp_path):
    """`_onexc` walked *up*: on a failure it cleared the read-only bit on
    `os.path.dirname(path)` with no check that the parent was inside the tree
    being removed. For the outermost failure `path` **is** the root, so the
    parent is the root's container - and at eight of the eleven call sites that
    container is `ctx.temp_dir`, a path the user types into the GUI rather than
    anything this engine created.

    `shutil.rmtree(path, ignore_errors=True)` never touched anything outside
    `path`. Replacing it must not change that.
    """
    from excmp.tempclean import rmtree_force

    outer = tmp_path / "user-temp"
    job = outer / "job"
    job.mkdir(parents=True)
    victim = job / "held.bin"
    victim.write_bytes(b"x" * 100)
    os.chmod(outer, stat.S_IREAD | stat.S_IEXEC)
    before = os.stat(outer).st_mode

    handle = victim.open("rb")          # something still holds it open
    try:
        rmtree_force(job)               # must not raise, must not reach `outer`
        # Read it BEFORE restoring, or the comparison is against our own chmod.
        after = os.stat(outer).st_mode
    finally:
        handle.close()
        os.chmod(outer, before | stat.S_IWRITE)

    assert after == before, \
        "cleanup modified the directory it was NOT asked to delete"


# --------------------------------------------------------------------------
# K4's read ceiling
# --------------------------------------------------------------------------

def test_the_read_ceiling_is_never_above_what_zstd_accepts():
    """`max(DECOMPRESS_WINDOW_LOG, self.long_log or 0)` is unbounded upward,
    but 31 is zstd's hard maximum (`zstandard.WINDOWLOG_MAX`). Any larger
    `long_log` turned the ceiling into an invalid parameter and `extract`
    raised *"unable to set max window size: Parameter is out of bound"* - a
    ceiling that refuses to read anything at all, which is the exact opposite
    of what it is for.

    Latent rather than live (no production caller passes `long_log`), but this
    method exists to stop precisely this coupling from reappearing.
    """
    import zstandard
    from excmp.stages.zstdstage import ZstdStage

    for long_log in (20, 27, 31, 32, 63):
        wl = ZstdStage(long_log=long_log)._decompress_window_log()
        assert wl <= zstandard.WINDOWLOG_MAX, (long_log, wl)
        # It must still be usable, not merely small enough.
        zstandard.ZstdDecompressor(max_window_size=1 << wl)
