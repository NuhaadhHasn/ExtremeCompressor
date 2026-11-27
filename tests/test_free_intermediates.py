"""A chain's intermediate files are freed as soon as the next stage has consumed them.

Measured 2026-11-27 on 39 MB of Office/PDF files at Extreme (temp folder sampled every 0.2 s): the tar and Precomp's expanded
output (533 MB) stayed on disk until the job ended, and the pre-publish self-test (D9) then made its OWN expanded copy beside
them: a peak of 1,143 MB against the 346 MB the preflight had booked. On a drive with little free space that is a job that
passes the check and dies at the finish line. Only dedup's input used to be freed early; now every stage's is.

What must NOT change: a stage that steps aside (Precomp finding nothing) leaves its input in place for the next stage, and
every archive still restores byte-identical.
"""

from __future__ import annotations

import random
import zlib

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.stages.sevenzip import SevenZipStage
from excmp.tools import find_tools

_tools = find_tools()
needs_chain = pytest.mark.skipif(
    any(_tools[t] is None for t in ("7z", "precomp")), reason="7z+precomp required for the extreme chain")


def _gamey_tree(root):
    root.mkdir()
    rng = random.Random(42)
    base = bytes(rng.randrange(256) for _ in range(64_000))
    (root / "assets1.dat").write_bytes(zlib.compress(base * 3, level=9))
    (root / "assets2.dat").write_bytes(zlib.compress(base * 3, level=9))
    (root / "script.lua").write_text("function f()\n  return 42\nend\n" * 2_000)
    return root


def _tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _job_files(temp):
    """Files in the compress job's own folder (not an extract's or the standard path's)."""
    jobs = [p for p in temp.glob("excmp-*") if p.is_dir() and not p.name.startswith(("excmp-x-", "excmp-std-"))]
    return sorted(f.name for j in jobs for f in j.rglob("*") if f.is_file())


@needs_chain
def test_only_the_payload_is_left_when_the_self_test_starts(tmp_path, monkeypatch):
    src = _gamey_tree(tmp_path / "game")
    seen = {}
    real = engine._verify_before_publish

    def spy(tmp_out, ctx):
        seen["files"] = _job_files(tmp_path / "tmp")
        return real(tmp_out, ctx)
    monkeypatch.setattr(engine, "_verify_before_publish", spy)
    engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, StageContext(temp_dir=tmp_path / "tmp"))
    assert len(seen["files"]) == 1 and seen["files"][0].startswith("payload"), seen["files"]


@needs_chain
def test_the_tar_is_already_gone_when_the_last_stage_runs(tmp_path, monkeypatch):
    src = _gamey_tree(tmp_path / "game")
    seen = {}
    real = SevenZipStage.compress

    def spy(self, src_path, dst, ctx):
        seen["files"] = sorted(p.name for p in src_path.parent.iterdir() if p.is_file())
        seen["src"] = src_path.name
        return real(self, src_path, dst, ctx)
    monkeypatch.setattr(SevenZipStage, "compress", spy)
    engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, StageContext(temp_dir=tmp_path / "tmp"))
    assert seen["src"] in seen["files"]                    # what it is compressing is there...
    assert not any(n.endswith(".tar") for n in seen["files"]), seen["files"]   # ...and the tar before Precomp is not


@needs_chain
def test_a_stage_that_steps_aside_leaves_its_input_for_the_next(tmp_path):
    """Nothing here for Precomp to open: it skips, so 7-Zip must still find the tar, and the archive must restore."""
    src = tmp_path / "plain"
    src.mkdir()
    rng = random.Random(7)
    (src / "noise.bin").write_bytes(bytes(rng.randrange(256) for _ in range(50_000)))
    (src / "notes.txt").write_text("plain words, nothing to expand. " * 800)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "p.excmp", Profile.EXTREME, ctx)
    from excmp.manifest import read_container
    manifest, _payload = read_container(tmp_path / "p.excmp", tmp_path / "rc")
    assert "precomp" not in [s.stage for s in manifest.stages], \
        "Precomp must have stepped aside here, or this test proves nothing"
    out = tmp_path / "restore"
    engine.extract(tmp_path / "p.excmp", out, ctx)
    assert _tree_bytes(out / "plain") == _tree_bytes(src)


@needs_chain
def test_every_chain_still_restores_byte_identical(tmp_path):
    src = _gamey_tree(tmp_path / "game")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, ctx)
    out = tmp_path / "restore"
    engine.extract(tmp_path / "e.excmp", out, ctx)
    assert _tree_bytes(out / "game") == _tree_bytes(src)
    assert _job_files(tmp_path / "tmp") == []                # and nothing is left behind afterwards


@needs_chain
def test_a_file_that_cannot_be_freed_never_fails_the_job(tmp_path, monkeypatch):
    """Freeing an intermediate early is only a saving. If antivirus or a sync agent holds it open (no share-delete) the delete
    fails on Windows; that must not throw away a finished job (found by review: a raw PermissionError, no archive)."""
    from excmp.stages.precomp import PrecompStage

    src = _gamey_tree(tmp_path / "game")
    handles = []
    real = PrecompStage.compress

    def holding(self, src_path, dst, ctx):
        handles.append(open(src_path, "rb"))              # something keeps the tar open after the stage returns
        return real(self, src_path, dst, ctx)
    monkeypatch.setattr(PrecompStage, "compress", holding)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    try:
        engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, ctx)
    finally:
        for h in handles:
            h.close()
    out = tmp_path / "restore"
    engine.extract(tmp_path / "e.excmp", out, ctx)
    assert _tree_bytes(out / "game") == _tree_bytes(src)


def test_the_same_file_under_two_spellings_is_still_the_same_file(tmp_path):
    """The guard that stops a stage's own output being freed compares files, not path spellings."""
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    assert engine._same_file(f, tmp_path / "." / "a.bin")
    assert engine._same_file(f, f.parent.parent / f.parent.name / "A.BIN")          # Windows: case-insensitive
    (tmp_path / "b.bin").write_bytes(b"x")
    assert not engine._same_file(f, tmp_path / "b.bin")
    assert not engine._same_file(f, tmp_path / "missing.bin")
