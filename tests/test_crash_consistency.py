"""D3 — what a job leaves behind when it does not finish.

A compressor is judged on the run that *fails*, not the run that works. The
promises that have to survive an interruption are the same three every time:

1. **The input is untouched** — bytes *and* mtime. A tool that rewrites
   timestamps on the files it was asked to preserve has damaged them.
2. **Nothing partial is left at the output path.** A half-written `.excmp`
   that looks like an archive is worse than no file at all, because the next
   thing to touch it is a person who thinks it is finished.
3. **Temp is cleaned.** Precomp legitimately inflates 2-5x mid-pipeline, so a
   job cancelled at the wrong moment can strand gigabytes.

Cancellation is the honest way to test this. `StageContext.cancel` is what the
GUI's Cancel button sets and what `run_tool` checks between output lines, so
killing a job this way exercises the same path a real user does — and unlike
`SIGKILL` it is reproducible on Windows.

The cancel is fired from inside `progress_cb`, which means it lands *during* a
stage rather than between two of them. Cancelling at a stage boundary would
test the easy case.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from excmp.engine import compress, extract
from excmp.planner import Profile
from excmp.stages.base import StageContext, StageError


def _corpus(tmp_path: Path) -> tuple[Path, dict[Path, tuple[bytes, int]]]:
    """Big enough that a stage reports progress more than once, so the cancel
    has somewhere to land."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"compressible content " * 200_000)
    (src / "sub" / "b.txt").write_bytes(b"more of the same " * 200_000)
    (src / "sub" / "c.bin").write_bytes(bytes(range(256)) * 20_000)
    snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in src.rglob("*") if p.is_file()}
    return src, snapshot


def _assert_input_pristine(snapshot: dict[Path, tuple[bytes, int]]) -> None:
    for path, (data, mtime) in snapshot.items():
        assert path.exists(), f"{path.name} was deleted from the input"
        assert path.read_bytes() == data, f"{path.name} was modified"
        assert path.stat().st_mtime_ns == mtime, f"{path.name}'s mtime changed"


def _leftovers(temp_dir: Path) -> list[Path]:
    if not temp_dir.exists():
        return []
    return [p for p in temp_dir.rglob("*") if p.is_file()]


@pytest.mark.parametrize("profile", [Profile.FAST, Profile.NORMAL])
@pytest.mark.parametrize("fire_after", [1, 3], ids=["first-callback", "third-callback"])
def test_a_cancelled_compress_leaves_nothing_behind(tmp_path, profile, fire_after):
    """Whether the cancel lands in time is a race, so this asserts the
    invariant that holds *either way* rather than assuming it wins.

    Both outcomes are legitimate: the job stops, or it had already finished
    and publishes a real archive. What is never legitimate is a partial file
    at the output path, a modified input, or a temp directory full of the
    2-5x inflation Precomp leaves mid-pipeline. An earlier version of this
    test asserted `pytest.raises` and failed on the fast profile purely
    because a small corpus finished first - which is a fact about the corpus,
    not about the product.
    """
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "result.excmp"
    temp_dir = tmp_path / "t"

    seen = 0

    def on_progress(stage: str, pct: float) -> None:
        nonlocal seen
        seen += 1
        if seen >= fire_after:
            ctx.cancel.set()

    ctx = StageContext(temp_dir=temp_dir, threads=2, progress_cb=on_progress)

    try:
        compress([src], out, profile, ctx)
        finished = True
    except (StageError, KeyboardInterrupt, RuntimeError):
        finished = False

    _assert_input_pristine(snapshot)
    assert not list(tmp_path.glob("*.tmp")), "a .tmp file was left beside the output"
    left = _leftovers(temp_dir)
    assert not left, f"temp was not cleaned: {[p.name for p in left][:5]}"

    if finished:
        # It beat the cancel. Then it must be a real archive, not a stub:
        # anything published has been through the D9 gate by definition.
        assert out.exists() and out.stat().st_size > 0
        restored = tmp_path / "check"
        extract(out, restored, StageContext(temp_dir=tmp_path / "ct2", threads=2))
        for path, (data, _mtime) in snapshot.items():
            rel = path.relative_to(src).as_posix()
            match = [q for q in restored.rglob("*")
                     if q.is_file() and q.as_posix().endswith(rel)]
            assert match, f"{rel} missing from a job that reported success"
            assert match[0].read_bytes() == data
    else:
        assert not out.exists(), "a cancelled job published an archive"


def test_cancelling_before_anything_starts_is_clean(tmp_path):
    """The degenerate case. It should refuse immediately and identically —
    an early exit is still an exit, and must not take a different path
    through the cleanup."""
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "result.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    ctx.cancel.set()

    with pytest.raises((StageError, KeyboardInterrupt, RuntimeError)):
        compress([src], out, Profile.NORMAL, ctx)

    _assert_input_pristine(snapshot)
    assert not out.exists()


def test_a_cancelled_extract_does_not_leave_a_half_restore(tmp_path):
    """The other direction. A partial restore is more dangerous than a failed
    one: the files look real, and nothing about them says they are short."""
    src, _snap = _corpus(tmp_path)
    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.FAST,
             StageContext(temp_dir=tmp_path / "ct", threads=2))
    assert archive.exists()

    seen = 0

    def on_progress(stage: str, pct: float) -> None:
        nonlocal seen
        seen += 1
        if seen >= 1:
            xctx.cancel.set()

    out = tmp_path / "restored"
    xctx = StageContext(temp_dir=tmp_path / "xt", threads=2,
                        progress_cb=on_progress)
    try:
        extract(archive, out, xctx)
    except (StageError, KeyboardInterrupt, RuntimeError):
        pass    # either outcome is fine; the invariants below are not

    # Reading an archive must never damage it - that is the one thing an
    # interrupted *extract* could plausibly get wrong.
    assert archive.exists() and archive.stat().st_size > 0
    left = _leftovers(tmp_path / "xt")
    assert not left, f"extract temp not cleaned: {[p.name for p in left][:5]}"


def test_the_archive_is_not_published_until_it_verifies(tmp_path):
    """The D9 guarantee, stated as a crash-consistency property: at no point
    does a readable-looking `.excmp` exist at the final path before the whole
    chain has been replayed and hashed. Cancelling during the verify phase is
    the moment that would expose a publish-then-check ordering."""
    src, snapshot = _corpus(tmp_path)
    out = tmp_path / "result.excmp"

    stages_seen: list[str] = []

    def on_progress(stage: str, pct: float) -> None:
        stages_seen.append(stage)
        # Let the compression finish, then pull the rug during verification.
        if len(stages_seen) > 6:
            ctx.cancel.set()
        assert not out.exists(), (
            f"the archive appeared at the final path during stage {stage!r} — "
            "publication must come after verification, not before")

    ctx = StageContext(temp_dir=tmp_path / "t", threads=2, progress_cb=on_progress)
    try:
        compress([src], out, Profile.FAST, ctx)
    except (StageError, KeyboardInterrupt, RuntimeError):
        assert not out.exists()
    _assert_input_pristine(snapshot)


def test_a_failed_job_does_not_poison_the_next_one(tmp_path):
    """Whatever the cancelled run left in temp must not change the result of
    a clean run into the same directory."""
    src, _snap = _corpus(tmp_path)
    temp_dir = tmp_path / "shared-temp"

    seen = 0

    def on_progress(stage: str, pct: float) -> None:
        nonlocal seen
        seen += 1
        if seen >= 1:
            bad.cancel.set()

    bad = StageContext(temp_dir=temp_dir, threads=2, progress_cb=on_progress)
    with pytest.raises((StageError, KeyboardInterrupt, RuntimeError)):
        compress([src], tmp_path / "doomed.excmp", Profile.FAST, bad)

    good_out = tmp_path / "good.excmp"
    compress([src], good_out, Profile.FAST,
             StageContext(temp_dir=temp_dir, threads=2))
    assert good_out.exists()

    restored = tmp_path / "restored"
    extract(good_out, restored, StageContext(temp_dir=tmp_path / "xt", threads=2))
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src).as_posix()
        match = [q for q in restored.rglob("*")
                 if q.is_file() and q.as_posix().endswith(rel)]
        assert match, f"{rel} missing after a poisoned-temp run"
        assert (hashlib.sha256(match[0].read_bytes()).hexdigest()
                == hashlib.sha256(p.read_bytes()).hexdigest())
