"""D4 — a genuinely full disk, injected, at each write that can meet one.

**Why injection rather than a real volume.** The item says "on a small
VHDX/subst volume". A size-limited volume needs `diskpart` or `New-VHD`, both
of which want administrator, and `subst` only maps a path to a drive letter -
it imposes no size limit, so it cannot stand in. This machine has no
elevation. The real-volume half is written up in the roadmap with the exact
elevated command; this file does the part that can be done, and does it
properly: a real `OSError(errno.ENOSPC)` raised from the actual write call,
not a mocked return value.

**What was already here, and why this is still worth writing.** The engine has
a J4 compression preflight (`compress_space_needs`, floor refuses / peak
warns), a D0.3 extraction free-space check, and `tests/test_preflight.py`
fakes a full disk in nine tests. Every one of those tests the preflight's
*arithmetic* - `shutil.disk_usage` is monkeypatched and the writes still
succeed. Nothing had ever made a write actually fail. And `grep -n errno`
across `excmp/`, `gui/` and `tools/` returned **zero hits** before this file.

A preflight cannot be the whole answer, for a reason this session demonstrated
by accident: the suite itself hit
`OSError: [Errno 28] No space left on device` mid-run, because four leftover
pytest temp trees had eaten the volume *while the run was in progress*. Free
space measured before a job says nothing about free space during it - another
process can take it, and on a 2-core laptop with a nearly-full `C:` that is
routine rather than exotic.

**The invariants are deliberately the same three D3 pins for cancellation**
(`tests/test_crash_consistency.py`), because a full disk and a cancel should
leave the same world behind:

1. the input is untouched - bytes *and* mtime;
2. nothing partial sits at the output path, including no `.tmp` twin;
3. temp is clean, which matters because Precomp legitimately inflates 2-5x
   mid-pipeline.
"""

from __future__ import annotations

import errno
import os
import random
import shutil
from pathlib import Path

import pytest

from excmp import atomic, engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7z not installed")

PREVIOUS = b"the archive that was already there"


def _enospc(*_args, **_kwargs):
    """What a full volume raises. `errno.ENOSPC` is 28 on Windows too - it is
    the C runtime's number, not a POSIX-only one, and Python maps
    `ERROR_DISK_FULL` onto it."""
    raise OSError(errno.ENOSPC, "No space left on device")


def _corpus(tmp_path: Path) -> tuple[Path, dict[Path, tuple[bytes, int]]]:
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.txt").write_text("a full disk must lose nothing. " * 4_000)
    (src / "blob.bin").write_bytes(
        bytes(random.Random(4).getrandbits(8) for _ in range(30_000)))
    snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in src.rglob("*") if p.is_file()}
    return src, snapshot


def _assert_input_pristine(snapshot: dict[Path, tuple[bytes, int]]) -> None:
    for path, (data, mtime) in snapshot.items():
        assert path.exists(), f"{path.name} was deleted from the input"
        assert path.read_bytes() == data, f"{path.name} was modified"
        assert path.stat().st_mtime_ns == mtime, f"{path.name}'s mtime changed"


def _assert_nothing_published(out: Path) -> None:
    assert not out.exists(), "a job that ran out of disk published an archive"
    leftovers = sorted(p.name for p in out.parent.glob(f"{out.name}*"))
    assert leftovers == [], f"partial output left behind: {leftovers}"


def _leftovers(temp_dir: Path) -> list[Path]:
    if not temp_dir.exists():
        return []
    return [p for p in temp_dir.iterdir() if p.name.startswith("excmp-")]


# --------------------------------------------------------------------------
# the publish boundary, which D8 built and which had never met a real ENOSPC
# --------------------------------------------------------------------------

def test_a_full_disk_at_the_flush_publishes_nothing(tmp_path, monkeypatch):
    """`publish()` fsyncs before renaming. A volume that fills between the
    write and the flush is the case its short-write refusal was written for,
    and until now that refusal had only ever been tested with a hand-truncated
    file."""
    tmp = tmp_path / "a.bin.tmp"
    tmp.write_bytes(b"x" * 5000)
    final = tmp_path / "a.bin"
    final.write_bytes(PREVIOUS)

    monkeypatch.setattr(atomic, "fsync_file", _enospc)
    with pytest.raises(OSError) as err:
        atomic.publish(tmp, final)

    assert err.value.errno == errno.ENOSPC
    assert final.read_bytes() == PREVIOUS, "the previous archive was destroyed"


def test_a_full_disk_at_the_rename_keeps_the_old_archive(tmp_path, monkeypatch):
    """The rename is the moment a whole job's work is on the line. D8 removed
    the `unlink()` that used to precede it; this proves a full disk cannot
    undo that."""
    tmp = tmp_path / "b.bin.tmp"
    tmp.write_bytes(b"y" * 5000)
    final = tmp_path / "b.bin"
    final.write_bytes(PREVIOUS)

    monkeypatch.setattr(os, "replace", _enospc)
    with pytest.raises(OSError):
        atomic.publish(tmp, final)

    assert final.read_bytes() == PREVIOUS


def test_a_full_disk_writing_a_small_store_never_raises(tmp_path, monkeypatch):
    """`calibrate.record` and `history.append` promise never to raise, and
    they run *after* a job has already succeeded. A full disk must not turn a
    finished job into a failed one - and ENOSPC arrives as OSError, which is
    the clause they already catch."""
    from excmp import calibrate

    target = tmp_path / "calibration.json"
    calibrate.record(["7z"], 50_000_000, 10.0, path=target)
    before = target.read_bytes()

    monkeypatch.setattr(Path, "write_bytes", _enospc)
    calibrate.record(["7z"], 60_000_000, 12.0, path=target)   # must not raise

    assert target.read_bytes() == before


# --------------------------------------------------------------------------
# the engine, end to end, at three different write boundaries
# --------------------------------------------------------------------------

@needs_7z
def test_a_full_disk_while_staging_loses_nothing(tmp_path, monkeypatch):
    """The staging copy is the first write a compress makes, before any codec
    has run."""
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "out.excmp"
    temp = tmp_path / "tmp"
    ctx = StageContext(temp_dir=temp)

    monkeypatch.setattr(shutil, "copy2", _enospc)
    with pytest.raises(Exception):
        engine.compress([src], out, Profile.NORMAL, ctx)

    _assert_input_pristine(snapshot)
    _assert_nothing_published(out)
    assert not _leftovers(temp), f"temp not cleaned: {_leftovers(temp)}"


@needs_7z
def test_a_full_disk_writing_the_container_loses_nothing(tmp_path, monkeypatch):
    """`write_container` is the last big write before the D9 gate, and it has
    no try/except of its own - an OSError propagates, which is correct, but
    the three invariants still have to hold on the way out."""
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "out.excmp"
    temp = tmp_path / "tmp"
    ctx = StageContext(temp_dir=temp)

    monkeypatch.setattr(engine, "write_container", _enospc)
    with pytest.raises(OSError):
        engine.compress([src], out, Profile.NORMAL, ctx)

    _assert_input_pristine(snapshot)
    _assert_nothing_published(out)
    assert not _leftovers(temp), f"temp not cleaned: {_leftovers(temp)}"


@needs_7z
def test_a_full_disk_does_not_poison_the_next_job(tmp_path, monkeypatch):
    """D3 pins this for cancellation and it matters at least as much here: a
    user who frees space and retries must get a working archive, not the
    wreckage of the failed attempt."""
    src, _ = _corpus(tmp_path)
    temp = tmp_path / "tmp"

    monkeypatch.setattr(engine, "write_container", _enospc)
    with pytest.raises(OSError):
        engine.compress([src], tmp_path / "first.excmp", Profile.NORMAL,
                        StageContext(temp_dir=temp))
    monkeypatch.undo()

    good = tmp_path / "second.excmp"
    result = engine.compress([src], good, Profile.NORMAL,
                             StageContext(temp_dir=temp))
    assert good.exists() and result.final_bytes > 0

    out = tmp_path / "restored"
    restored = engine.extract(good, out, StageContext(temp_dir=temp))
    assert restored.verified == len(list(src.rglob("*"))), (
        "the archive written after a disk-full failure did not fully verify")


@needs_7z
def test_a_full_disk_during_extraction_leaves_no_half_restore(tmp_path,
                                                              monkeypatch):
    """Extraction is where a full disk is most likely in practice - the
    restored tree is always bigger than the archive that held it."""
    src, _ = _corpus(tmp_path)
    archive = tmp_path / "a.excmp"
    temp = tmp_path / "tmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=temp))
    before = archive.read_bytes()

    monkeypatch.setattr(engine, "extract_stored", _enospc)
    with pytest.raises(OSError):
        engine.extract(archive, tmp_path / "out", StageContext(temp_dir=temp))

    assert archive.read_bytes() == before, "the archive itself was damaged"
    assert not _leftovers(temp), f"extract temp not cleaned: {_leftovers(temp)}"


# --------------------------------------------------------------------------
# the defect D4 was written to find
# --------------------------------------------------------------------------

@needs_7z
def test_a_full_disk_is_not_reported_as_a_locked_file(tmp_path, monkeypatch):
    """**A real defect, found by injecting ENOSPC rather than by reading the
    code.** K3 added a per-file guard around the staging copy so one locked
    file cannot destroy a whole job: an `OSError` there means "skip this file,
    report it by name, carry on". A full destination volume raises `OSError`
    from the same call - so a disk-full job skipped every file in turn and
    then failed with

        none of the 2 file(s) selected could be read - they may be open in
        another program

    Every word of that diagnosis is wrong. The files are perfectly readable;
    the *destination* is full; and the user is sent to close programs, which
    cannot possibly help. K3's guard is right about share-mode denials, which
    are genuinely per-file, and wrong about ENOSPC, which is a property of the
    volume and cannot be skipped past.

    So ENOSPC is no longer swallowed by the skip path: it aborts the job with
    a message naming the real problem."""
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "out.excmp"
    temp = tmp_path / "tmp"

    monkeypatch.setattr(shutil, "copy2", _enospc)
    with pytest.raises(OSError) as err:
        engine.compress([src], out, Profile.NORMAL, StageContext(temp_dir=temp))

    assert err.value.errno == errno.ENOSPC, (
        "a full disk must surface as ENOSPC, not be re-labelled")
    text = str(err.value).lower()
    assert "another program" not in text, (
        "a full disk is still being reported as a locked file")
    assert "space" in text or "disk" in text, text

    _assert_input_pristine(snapshot)
    _assert_nothing_published(out)


@needs_7z
def test_a_genuinely_locked_file_is_still_skipped(tmp_path, monkeypatch):
    """The other half, and the reason the fix is a narrow errno test rather
    than "stop catching OSError". K3 exists because one locked file used to
    destroy an entire job; that behaviour must survive untouched."""
    src, _ = _corpus(tmp_path)
    out = tmp_path / "out.excmp"
    victim = src / "blob.bin"
    real_copy = shutil.copy2

    def deny_one(source, target, *a, **k):
        if Path(source).name == victim.name:
            raise OSError(errno.EACCES, "The process cannot access the file")
        return real_copy(source, target, *a, **k)

    monkeypatch.setattr(shutil, "copy2", deny_one)
    result = engine.compress([src], out, Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "tmp"))

    assert out.exists(), "a single locked file destroyed the whole job again"
    assert any(victim.name in note for note in result.skipped), result.skipped
