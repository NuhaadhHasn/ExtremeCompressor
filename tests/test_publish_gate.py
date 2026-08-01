"""D9: the archive is fully restored and hash-verified BEFORE it is published.

Found the hard way (benchmarks/2026-08-01-estimator-backtest.md): the old
self-test only exercised the *last* stage's container layer, so a broken stage
underneath sailed through - srep64.exe failed its own decompression checksum at
extract time on an archive compress() had already reported as a success.

The product rule is "post-restore SHA-256 comparison is the acceptance gate for
every stage", and the tagline promises "verifies a byte-identical restore before
claiming success". These tests make that literal: if any stage of the chain -
or the container's stored-file path - cannot round-trip, no archive appears at
the output path. Not a warning; no file.
"""

import random
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.stages.zstdstage import ZstdStage
from excmp.tools import find_tools
from excmp.verify import VerifyError

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


def _tree(root):
    root.mkdir()
    (root / "doc.txt").write_text("verify me before you publish me. " * 5_000)
    (root / "blob.bin").write_bytes(bytes(random.Random(9).getrandbits(8)
                                          for _ in range(50_000)))
    return root


def _assert_nothing_published(out: Path) -> None:
    assert not out.exists(), "a bad archive was published"
    leftovers = list(out.parent.glob(f"{out.name}*"))
    assert leftovers == [], f"partial output left behind: {leftovers}"


def test_a_stage_that_corrupts_its_restore_blocks_publication(tmp_path, monkeypatch):
    """The exact shape of the SREP fault: compression succeeds, the tool exits
    happily, and only a real restore reveals the data comes back wrong."""
    src = _tree(tmp_path / "src")
    out = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    original = ZstdStage.extract

    def corrupting_extract(self, s, d, c):
        result = original(self, s, d, c)
        victim = next(p for p in sorted(result.rglob("*")) if p.is_file())
        victim.write_bytes(b"\x00" + victim.read_bytes()[1:])
        return result

    monkeypatch.setattr(ZstdStage, "extract", corrupting_extract)

    with pytest.raises(VerifyError):
        engine.compress([src], out, Profile.FAST, ctx)
    _assert_nothing_published(out)
    # The originals are untouched - the non-negotiable rule.
    assert (src / "doc.txt").read_text().startswith("verify me")


def test_a_payload_that_cannot_be_read_back_blocks_publication(tmp_path, monkeypatch):
    """A stage whose *output* is garbage: the write went fine, the exit code was
    zero, and the payload is unreadable. The gate has to catch this too."""
    src = _tree(tmp_path / "src")
    out = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    def garbage_compress(self, s, d, c):
        d.write_bytes(bytes(random.Random(1).getrandbits(8) for _ in range(8_000)))
        return d

    monkeypatch.setattr(ZstdStage, "compress", garbage_compress)

    with pytest.raises(Exception):
        engine.compress([src], out, Profile.FAST, ctx)
    _assert_nothing_published(out)


@needs_7z
def test_the_gate_runs_the_real_ledger_verification(tmp_path, monkeypatch):
    """Wiring check: the pre-publish gate must be the same verify_restore that
    guards extraction, not a lookalike. If it never runs, this fails."""
    src = _tree(tmp_path / "src")
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    calls = []
    real = engine.verify_restore

    def counting_verify(out_dir, ledger):
        calls.append(len(ledger))
        return real(out_dir, ledger)

    monkeypatch.setattr(engine, "verify_restore", counting_verify)
    engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)

    assert calls, "compress() published without running verify_restore"
    assert calls[0] == 2, "the gate must verify the FULL ledger, stored files included"


def test_store_only_archives_are_verified_too(tmp_path, monkeypatch):
    """No pipeline does not mean no risk: stored entries are written by our own
    container code, and the promise is byte-identical restore of everything."""
    root = tmp_path / "media"
    root.mkdir()
    (root / "clip.mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom" + bytes(random.Random(3).getrandbits(8)
                                            for _ in range(300_000)))
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    calls = []
    real = engine.verify_restore

    def counting_verify(out_dir, ledger):
        calls.append(len(ledger))
        return real(out_dir, ledger)

    monkeypatch.setattr(engine, "verify_restore", counting_verify)
    result = engine.compress([root], tmp_path / "out.excmp", Profile.FAST, ctx)

    assert calls and calls[0] == 1
    assert (tmp_path / "out.excmp").exists()
    assert result.final_bytes > 0


def test_a_good_archive_still_publishes_and_reports_the_verification(tmp_path):
    src = _tree(tmp_path / "src")
    out = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    lines = []
    ctx.log_cb = lambda stage, line: lines.append(f"[{stage}] {line}")

    engine.compress([src], out, Profile.FAST, ctx)

    assert out.exists()
    assert any("verif" in line.lower() for line in lines), (
        "the user was not told the restore was checked - the guarantee should "
        "be visible, not silent")
