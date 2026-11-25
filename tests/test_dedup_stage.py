"""B31 - the long-range block dedup stage in front of 7-Zip at Extreme.

**The measurement that caused this** (2026-11-25, i5-7200U, the owner's design
folder): ``Backup_of_menu card.cdr`` and ``menu card.cdr`` are two versions of
one CorelDRAW file. Precomp expands the pair to 652 MB, and 7-Zip's LZMA2 can
find a repeat only inside its 256 MiB dictionary, so it compressed both copies
in full. SREP did this job until B11 took it out for failing a restore; this
stage is its replacement, in Python, with every chunk hashed on the way back.

What is pinned here:

* the chunker cuts by content, whatever the read size and wherever the data
  sits in the stream;
* the stage costs nothing where it cannot help: a stream inside the codec's
  window is not even opened, and one with no far repeats leaves no file and
  no stage record;
* the on-disk form restores byte for byte, and refuses every damaged or
  dishonest file *before* it writes what that file says;
* an archive without a dedup stage - every archive made before B31 - extracts
  without this code running at all;
* any failure inside the stage falls back to the chain as it was.
"""

from __future__ import annotations

import hashlib
import random
import struct
import threading
from pathlib import Path

import pytest

from excmp import engine
from excmp.engine import StageOptions, _with_dedup
from excmp.planner import Profile
from excmp.stages import dedup
from excmp.stages.base import (QuietSkip, StageContext, StageError,
                               StageSkip)
from excmp.stages.dedup import (HEADER_SIZE, Chunker, DedupStage, restore,
                                scan, write)
from excmp.tools import find_tools

_tools = find_tools()
needs_chain = pytest.mark.skipif(
    any(_tools[t] is None for t in ("7z", "precomp")),
    reason="7z+precomp required for the Extreme chain")

KIB = 1024
WINDOW = 256 * KIB          # a small stand-in for LZMA2's 256 MiB dictionary
AVG = 2 * KIB


def _noise(n: int, seed: int) -> bytes:
    return random.Random(seed).randbytes(n)


def _cuts(data: bytes, block: int, avg: int = AVG) -> list[int]:
    chunker = Chunker(avg)
    out: list[int] = []
    joined = b""
    for at in range(0, len(data), block):
        part, lengths = chunker.feed(data[at:at + block])
        joined += part
        out += lengths
    part, lengths = chunker.feed(b"", final=True)
    joined += part
    out += lengths
    assert joined == data, "the chunker lost or reordered bytes"
    assert sum(out) == len(data)
    return out


def _digests(data: bytes, avg: int = AVG) -> list[bytes]:
    out, at = [], 0
    for n in _cuts(data, 1 << 20, avg):
        out.append(hashlib.sha256(data[at:at + n]).digest())
        at += n
    return out


# --- the chunker --------------------------------------------------------------

def test_cuts_do_not_depend_on_how_the_stream_is_read():
    data = _noise(600 * KIB, 1)
    whole = _cuts(data, len(data))
    for block in (1, 7 * KIB, 64 * KIB, 100_003):
        if block == 1:
            # one byte at a time is the hardest split; keep it affordable
            assert _cuts(data[:20 * KIB], 1) == _cuts(data[:20 * KIB], 20 * KIB)
            continue
        assert _cuts(data, block) == whole, block


def test_chunk_sizes_stay_inside_their_bounds():
    data = _noise(2 << 20, 2)
    chunker = Chunker(AVG)
    cuts = _cuts(data, 1 << 20)
    assert max(cuts) <= chunker.max
    assert min(cuts[:-1]) >= chunker.min
    mean = len(data) / len(cuts)
    assert AVG / 2 < mean < AVG * 2, mean


def test_the_same_data_at_a_different_offset_gets_the_same_chunks():
    """The whole point of content-defined cuts: a second copy is found even
    though nothing about its position lines up with the first."""
    body = _noise(400 * KIB, 3)
    plain = set(_digests(body))
    shifted = set(_digests(_noise(12_345, 4) + body))
    assert len(plain & shifted) > 0.95 * len(plain)


@pytest.mark.parametrize("data", [
    bytes(900 * KIB),                                # one byte repeated
    b"\x12\x34\x56" * (300 * KIB),                   # a period that does not divide 32
    b"abcdefg" * (128 * KIB),
    b"",
    b"x",
], ids=["zeros", "period3", "period7", "empty", "one-byte"])
def test_degenerate_streams_are_cut_and_are_not_slow(data):
    cuts = _cuts(data, 1 << 20)
    assert sum(cuts) == len(data)
    assert all(c <= Chunker(AVG).max for c in cuts)


def test_chunk_size_grows_with_the_stream_so_the_index_stays_bounded():
    assert dedup.chunk_size_for(100 << 20) == dedup.AVG_CHUNK
    for size in (1 << 30, 64 << 30, 1 << 40):
        assert size / dedup.chunk_size_for(size) <= dedup.MAX_CHUNKS


# --- scan / write / restore -------------------------------------------------

def _stream(tmp_path: Path, data: bytes, name: str = "s.pcf") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _far_repeat(seed: int = 5) -> bytes:
    """Two copies of 300 KiB with 400 KiB between them: further apart than
    WINDOW, so the stand-in codec cannot see the second from the first."""
    body = _noise(300 * KIB, seed)
    return body + _noise(400 * KIB, seed + 1) + body + _noise(50 * KIB, seed + 2)


def _packed(tmp_path: Path, data: bytes) -> tuple[Path, dedup.Scan]:
    src = _stream(tmp_path, data)
    found = scan(src, window=WINDOW, avg=AVG)
    return write(src, tmp_path / "s.dd", found), found


def test_a_far_repeat_is_found_and_restores_byte_for_byte(tmp_path):
    data = _far_repeat()
    packed, found = _packed(tmp_path, data)
    assert found.orig_size == len(data)
    assert found.far_bytes > 280 * KIB           # nearly the whole second copy
    assert packed.stat().st_size == found.output_size < len(data) - 270 * KIB
    out = tmp_path / "back"
    assert restore(packed, out) == len(data)
    assert out.read_bytes() == data


def test_a_near_repeat_is_not_counted_as_far(tmp_path):
    body = _noise(60 * KIB, 9)
    found = scan(_stream(tmp_path, body + body + _noise(10 * KIB, 10)),
                 window=WINDOW, avg=AVG)
    assert found.duplicate_bytes > 50 * KIB
    assert found.far_bytes == 0


def test_a_close_repeat_is_close_wherever_it_falls(tmp_path):
    """Distance is the whole rule. 7-Zip 26.02 (-mx9 -mmt2) was measured on
    160 MiB of random bytes written twice and gave 160.0 MiB: it found the
    repeat across the 256 MiB mark, so a window-sized boundary between two
    copies does not put the second out of its reach."""
    body = _noise(100 * KIB, 11)
    data = _noise(WINDOW - 110 * KIB, 12) + body + _noise(20 * KIB, 13) + body
    found = scan(_stream(tmp_path, data), window=WINDOW, avg=AVG)
    assert found.duplicate_bytes > 80 * KIB and found.far_bytes == 0


def test_it_is_the_nearest_earlier_copy_that_counts(tmp_path):
    """Three copies, the third close to the second: only the second is far."""
    body = _noise(100 * KIB, 15)
    data = body + _noise(WINDOW, 16) + body + _noise(20 * KIB, 17) + body
    found = scan(_stream(tmp_path, data), window=WINDOW, avg=AVG)
    assert 80 * KIB < found.far_bytes < 110 * KIB
    assert found.duplicate_bytes > 180 * KIB


def test_unique_data_has_nothing_to_remove(tmp_path):
    found = scan(_stream(tmp_path, _noise(700 * KIB, 14)), window=WINDOW, avg=AVG)
    assert found.duplicate_bytes == 0 and found.far_bytes == 0
    assert found.output_size > found.orig_size       # the index is pure cost


@pytest.mark.parametrize("data", [b"", b"q", bytes(3 << 20)],
                         ids=["empty", "one-byte", "zeros"])
def test_edge_streams_round_trip(tmp_path, data):
    packed, _found = _packed(tmp_path, data)
    out = tmp_path / "back"
    restore(packed, out)
    assert out.read_bytes() == data


# --- the reader trusts nothing ----------------------------------------------

def _refuses(path: Path, tmp_path: Path, match: str, **kw) -> None:
    out = tmp_path / "must-not-exist"
    with pytest.raises(StageError, match=match):
        restore(path, out, **kw)
    assert not out.exists(), "a refused stream left output behind"


def _flip(path: Path, offset: int) -> None:
    raw = bytearray(path.read_bytes())
    raw[offset] ^= 0x01
    path.write_bytes(raw)


def test_a_flipped_data_byte_is_caught_by_its_chunk_before_it_is_written(tmp_path):
    packed, _ = _packed(tmp_path, _far_repeat())
    _flip(packed, HEADER_SIZE + 5)                 # inside the very first chunk
    _refuses(packed, tmp_path, "chunk 0 does not match")


def test_a_flipped_index_byte_is_caught_before_the_index_is_used(tmp_path):
    packed, _ = _packed(tmp_path, _far_repeat())
    _flip(packed, packed.stat().st_size - 3)
    _refuses(packed, tmp_path, "index does not match its checksum")


def test_a_truncated_file_is_refused(tmp_path):
    packed, _ = _packed(tmp_path, _far_repeat())
    raw = packed.read_bytes()
    packed.write_bytes(raw[:-100])
    _refuses(packed, tmp_path, "do not add up to the file")
    packed.write_bytes(raw[:40])
    _refuses(packed, tmp_path, "too short for a header")


def test_wrong_signature_and_future_version_are_refused(tmp_path):
    packed, _ = _packed(tmp_path, _far_repeat())
    raw = packed.read_bytes()
    packed.write_bytes(b"NOTDEDUP" + raw[8:])
    _refuses(packed, tmp_path, "wrong signature")
    packed.write_bytes(raw[:8] + struct.pack("<I", 2) + raw[12:])
    _refuses(packed, tmp_path, "newer than this build")


def _forge(tmp_path: Path, chunks: list[bytes], runs: list[tuple[int, int]],
           orig_size: int, stream: bytes = b"") -> Path:
    """A well-formed file (valid checksums) that says whatever we like."""
    data = b"".join(chunks)
    index = b"".join(
        dedup._CHUNK_REC.pack(len(c), hashlib.blake2b(c, digest_size=16).digest())
        for c in chunks)
    index += b"".join(dedup._RUN_REC.pack(*r) for r in runs)
    header = dedup._HEADER.pack(
        dedup.MAGIC, dedup.FORMAT_VERSION, 0, orig_size, len(data), len(chunks),
        len(runs), len(index), hashlib.blake2b(stream, digest_size=32).digest(),
        hashlib.blake2b(index, digest_size=16).digest())
    path = tmp_path / "forged.dd"
    path.write_bytes(header + data + index)
    return path


def test_a_forged_file_that_is_honest_restores(tmp_path):
    a, b = b"A" * 100, b"B" * 50
    path = _forge(tmp_path, [a, b], [(0, 2), (0, 1)], 250, a + b + a)
    out = tmp_path / "ok"
    restore(path, out)
    assert out.read_bytes() == a + b + a


def test_a_bomb_is_refused_before_anything_is_written(tmp_path):
    """One chunk referenced a million times is a 1 KB file that asks for a
    gigabyte. The sizes are added up from the index first."""
    chunk = b"Z" * 1024
    bomb = _forge(tmp_path, [chunk], [(0, 1)] * 5000, 1024)
    _refuses(bomb, tmp_path, "more than the declared size")
    honest_about_it = _forge(tmp_path, [chunk], [(0, 1)] * 5000, 5000 * 1024)
    _refuses(honest_about_it, tmp_path, "beyond the", output_limit=64 * KIB)


def test_runs_outside_the_table_and_wrong_totals_are_refused(tmp_path):
    c = b"C" * 64
    _refuses(_forge(tmp_path, [c], [(0, 2)], 128), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(1, 1)], 64), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(0, 0)], 0), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(0, 1)], 65), tmp_path, "do not produce the declared size")
    _refuses(_forge(tmp_path, [c, b""], [(0, 2)], 64), tmp_path, "an empty chunk")


def test_right_chunks_in_the_wrong_order_fail_the_stream_checksum(tmp_path):
    a, b = b"A" * 100, b"B" * 100
    swapped = _forge(tmp_path, [a, b], [(1, 1), (0, 1)], 200, a + b)
    _refuses(swapped, tmp_path, "rebuilt stream does not match")


# --- the stage: steps aside unless it helps ---------------------------------

def _ctx(tmp_path: Path) -> tuple[StageContext, list]:
    events: list = []
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    ctx.progress_cb = lambda stage, pct: events.append((stage, pct))
    return ctx, events


def _stage() -> DedupStage:
    return DedupStage(window=WINDOW, avg_chunk=AVG)


def test_a_stream_inside_the_window_is_not_even_read(tmp_path, monkeypatch):
    src = _stream(tmp_path, _noise(WINDOW, 20))
    monkeypatch.setattr(dedup, "scan", lambda *a, **k: pytest.fail("it was read"))
    ctx, events = _ctx(tmp_path)
    with pytest.raises(QuietSkip):
        _stage().compress(src, tmp_path / "o.dd", ctx)
    assert events == [] and not (tmp_path / "o.dd").exists()


def test_unique_data_is_skipped_quietly_and_leaves_nothing(tmp_path):
    src = _stream(tmp_path, _noise(3 * WINDOW, 21))
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(QuietSkip):
        _stage().compress(src, tmp_path / "o.dd", ctx)
    assert not (tmp_path / "o.dd").exists()
    assert src.read_bytes() == _noise(3 * WINDOW, 21), "the input was touched"


def test_far_repeats_under_two_percent_are_not_worth_a_stage(tmp_path):
    body = _noise(8 * KIB, 22)                       # ~1% of the stream
    data = body + _noise(3 * WINDOW, 23) + body
    with pytest.raises(QuietSkip):
        _stage().compress(_stream(tmp_path, data), tmp_path / "o.dd", _ctx(tmp_path)[0])


def test_far_repeats_are_removed_and_the_stage_round_trips(tmp_path):
    data = _far_repeat(30)
    src = _stream(tmp_path, data)
    ctx, events = _ctx(tmp_path)
    stage = _stage()
    packed = stage.compress(src, tmp_path / "o.dd", ctx)
    assert packed.stat().st_size < len(data) - 270 * KIB
    assert events[-1] == ("dedup", 100.0)
    assert [p for _, p in events] == sorted(p for _, p in events), "progress went back"
    assert stage.record_params() == {"format": 1, "window": WINDOW}
    back = stage.extract(packed, tmp_path / "x", ctx)
    assert back.read_bytes() == data
    assert src.read_bytes() == data


def test_extract_honours_the_engines_output_limit(tmp_path):
    packed, _ = _packed(tmp_path, _far_repeat(31))
    ctx, _ = _ctx(tmp_path)
    ctx.output_limit = 100 * KIB
    with pytest.raises(StageError, match="beyond the"):
        _stage().extract(packed, tmp_path / "x", ctx)
    assert list((tmp_path / "x").iterdir()) == []


@pytest.mark.parametrize("failure", ["write-raises", "write-corrupts", "disk-full"])
def test_any_failure_falls_back_to_the_chain_without_the_stage(tmp_path, monkeypatch,
                                                               failure):
    """A loud StageSkip, never an error: the engine then runs the chain every
    earlier release ran, and tells the user why this step was left out."""
    real_write = dedup.write
    if failure == "write-raises":
        def bad(*a, **k):
            raise OSError(28, "No space left on device")
    elif failure == "write-corrupts":
        def bad(src, dst, found, *a, **k):
            real_write(src, dst, found)
            _flip(Path(dst), HEADER_SIZE + 9)
            return dst
    else:
        bad = real_write
        monkeypatch.setattr(dedup.shutil, "disk_usage",
                            lambda p: type("U", (), {"free": 1024})())
    monkeypatch.setattr(dedup, "write", bad)
    src = _stream(tmp_path, _far_repeat(32))
    with pytest.raises(StageSkip) as caught:
        _stage().compress(src, tmp_path / "o.dd", _ctx(tmp_path)[0])
    assert not isinstance(caught.value, QuietSkip), "a failure must be reported"
    assert not (tmp_path / "o.dd").exists()


def test_cancel_is_a_cancel_not_a_skip(tmp_path):
    src = _stream(tmp_path, _far_repeat(33))
    ctx, _ = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(StageError, match="cancelled"):
        _stage().compress(src, tmp_path / "o.dd", ctx)


# --- the engine ---------------------------------------------------------------

def test_the_stage_is_offered_only_before_7zip_on_a_precomp_chain():
    assert _with_dedup(["tar", "precomp", "sevenzip"]) == \
        ["tar", "precomp", "dedup", "sevenzip"]
    for chain in (["sevenzip"], ["zstd"], ["tar", "precomp", "zpaqfranz"],
                  ["tar", "precomp", "dedup", "sevenzip"], ["tar", "precomp", "zstd"]):
        assert _with_dedup(chain) == chain


def test_the_planner_still_plans_the_chain_everything_else_keys_on():
    """Rates, calibration and the comparison table are keyed on
    'precomp+sevenzip'. The stage is the engine's, not the plan's."""
    from excmp.planner import _CHAINS
    assert _CHAINS["extreme"] == [("precomp", "precomp"), ("sevenzip", "7z")]
    assert "dedup" in engine._stage_factory()
    assert engine._PAYLOAD_EXT["dedup"] == ".dd"


def test_the_window_is_the_dictionary_7zip_will_run_with():
    reg = engine._stage_factory()
    assert reg["dedup"].window == 256 << 20                  # -mx9's default
    assert engine._stage_factory(StageOptions(dict_size="64m"))["dedup"].window == 64 << 20
    assert engine._stage_factory(
        StageOptions(extra_args=("-md=32m",)))["dedup"].window == 32 << 20


_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _texty(n: int, seed: int) -> bytes:
    """6 bits per byte: compressible enough to be piped, random enough that
    7-Zip cannot shrink a copy it cannot see."""
    return bytes(_ALPHABET[b & 63] for b in _noise(n, seed))


def _versions_tree(root: Path) -> Path:
    """Two 'versions' of one 3 MB file, 3 MB of other data between them in
    the tar: with a 1 MiB dictionary, out of 7-Zip's reach."""
    root.mkdir()
    body = _texty(3 << 20, 40)
    (root / "a_v1.dat").write_bytes(body)
    (root / "m_other.dat").write_bytes(_texty(3 << 20, 41))
    (root / "z_v2.dat").write_bytes(body[:1 << 20] + b"edited" + body[1 << 20:])
    return root


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


SMALL_DICT = StageOptions(dict_size="1m")


@needs_chain
def test_extreme_dedups_what_the_dictionary_cannot_reach(tmp_path, monkeypatch):
    from excmp.manifest import read_container
    src = _versions_tree(tmp_path / "proj")
    events: list = []
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    ctx.progress_cb = lambda stage, pct: events.append(stage)

    with_stage = engine.compress([src], tmp_path / "with.excmp", Profile.EXTREME,
                                 ctx, options=SMALL_DICT)
    manifest, _ = read_container(tmp_path / "with.excmp", tmp_path / "peek")
    stages = [s.stage for s in manifest.stages]
    assert stages[-2:] == ["dedup", "sevenzip"], stages
    record = manifest.stages[-2]
    assert record.params == {"format": 1, "window": 1 << 20}
    assert record.tool_name == "python" and record.input_bytes > 9 << 20
    assert "dedup" in events and not any("dedup" in w for w in with_stage.warnings)

    # The same job with the stage switched off: what every release before
    # B31 would have written.
    monkeypatch.setattr(engine, "_with_dedup", lambda chain: list(chain))
    without = engine.compress([src], tmp_path / "without.excmp", Profile.EXTREME,
                              ctx, options=SMALL_DICT)
    assert with_stage.final_bytes < without.final_bytes - (2 << 20)

    # The ledger gate ran on both (compress would have raised); and the
    # public restore gives the same bytes back.
    out = tmp_path / "restore"
    result = engine.extract(tmp_path / "with.excmp", out, ctx)
    assert result.verified == 3
    assert _tree_bytes(out / "proj") == _tree_bytes(src)
    assert engine.verify_archive(tmp_path / "with.excmp", ctx).ok


@needs_chain
def test_an_archive_from_before_b31_extracts_without_this_code(tmp_path, monkeypatch):
    """Backward compatibility, stated as strongly as it can be: an archive
    with no dedup record never calls the stage, in either direction."""
    from excmp.manifest import read_container
    src = _versions_tree(tmp_path / "proj")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    monkeypatch.setattr(engine, "_with_dedup", lambda chain: list(chain))
    engine.compress([src], tmp_path / "old.excmp", Profile.EXTREME, ctx,
                    options=SMALL_DICT)
    monkeypatch.undo()
    manifest, _ = read_container(tmp_path / "old.excmp", tmp_path / "peek")
    assert "dedup" not in [s.stage for s in manifest.stages]

    def boom(*a, **k):
        raise AssertionError("the dedup stage ran on an archive without one")
    monkeypatch.setattr(DedupStage, "extract", boom)
    monkeypatch.setattr(dedup, "restore", boom)
    out = tmp_path / "restore"
    assert engine.extract(tmp_path / "old.excmp", out, ctx).verified == 3
    assert _tree_bytes(out / "proj") == _tree_bytes(src)


@needs_chain
def test_a_small_extreme_job_is_exactly_what_it_was(tmp_path):
    """No stage record, no warning, no progress event, no log line the user
    sees as news: unique or small data pays nothing."""
    from excmp.manifest import read_container
    src = tmp_path / "small"
    src.mkdir()
    (src / "a.txt").write_bytes(_texty(200 * KIB, 50))
    (src / "b.txt").write_bytes(_texty(200 * KIB, 50))       # a near repeat
    events: list = []
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    ctx.progress_cb = lambda stage, pct: events.append(stage)
    result = engine.compress([src], tmp_path / "s.excmp", Profile.EXTREME, ctx)
    manifest, _ = read_container(tmp_path / "s.excmp", tmp_path / "peek")
    assert "dedup" not in [s.stage for s in manifest.stages]
    assert "dedup" not in events
    assert not any("dedup" in w for w in result.warnings)


@needs_chain
def test_a_failing_stage_costs_the_job_nothing_but_a_note(tmp_path, monkeypatch):
    from excmp.manifest import read_container

    def bad(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(dedup, "write", bad)
    src = _versions_tree(tmp_path / "proj")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    result = engine.compress([src], tmp_path / "f.excmp", Profile.EXTREME, ctx,
                             options=SMALL_DICT)
    manifest, _ = read_container(tmp_path / "f.excmp", tmp_path / "peek")
    assert "dedup" not in [s.stage for s in manifest.stages]
    assert any("dedup" in w and "compressed without it" in w for w in result.warnings)
    out = tmp_path / "restore"
    engine.extract(tmp_path / "f.excmp", out, ctx)
    assert _tree_bytes(out / "proj") == _tree_bytes(src)


@needs_chain
def test_a_dedup_stream_that_lies_cannot_get_past_the_engine(tmp_path, monkeypatch):
    """If the stage's own checks were all bypassed and it wrote the wrong
    bytes back, the SHA-256 ledger gate still refuses to publish."""
    from excmp.verify import VerifyError
    real = dedup.restore

    def lying(src, dst, *a, **k):
        size = real(src, dst, *a, **k)
        if dst is not None:
            raw = bytearray(Path(dst).read_bytes())
            raw[len(raw) // 2] ^= 0x01
            Path(dst).write_bytes(raw)
        return size
    monkeypatch.setattr(dedup, "restore", lying)
    src = _versions_tree(tmp_path / "proj")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    with pytest.raises(VerifyError):
        engine.compress([src], tmp_path / "bad.excmp", Profile.EXTREME, ctx,
                        options=SMALL_DICT)
    assert not (tmp_path / "bad.excmp").exists(), "an unverified archive was published"
    assert not (tmp_path / "bad.excmp.tmp").exists()


# --- the progress bar ---------------------------------------------------------

def test_the_bar_places_the_stage_before_the_final_codec():
    """Appended after 7-Zip, every 7-Zip report would read as a late one from
    a stage already left, and the bar would stop for the longest stage."""
    from gui.progress import ChainProgress
    chain = ChainProgress(["tar", "precomp", "sevenzip"])
    chain.update("tar", 100.0)
    chain.update("precomp", 100.0)
    before = chain.update("dedup", 50.0)
    assert chain.chain == ["tar", "precomp", "dedup", "sevenzip"]
    chain.update("dedup", 100.0)
    assert chain.update("sevenzip", 50.0) > before
    assert chain.update("sevenzip", 100.0) > chain.update("sevenzip", 50.0) - 1e-9


# --- the estimate -------------------------------------------------------------

def test_the_estimate_bills_the_scan_only_where_it_can_run():
    from excmp.estimate import DEDUP_SCAN_RATE, dedup_seconds
    big = 1 << 30
    assert dedup_seconds(big, ["precomp", "sevenzip"]) == pytest.approx(big / DEDUP_SCAN_RATE)
    assert dedup_seconds(200 << 20, ["precomp", "sevenzip"]) == 0.0     # inside the window
    assert dedup_seconds(big, ["sevenzip"]) == 0.0
    assert dedup_seconds(big, ["precomp", "zpaqfranz"]) == 0.0
    assert dedup_seconds(big, []) == 0.0
