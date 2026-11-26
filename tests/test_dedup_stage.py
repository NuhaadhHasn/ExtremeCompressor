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
    a, b = b"A" * 1000, b"B" * 600
    path = _forge(tmp_path, [a, b], [(0, 2), (0, 1)], 2600, a + b + a)
    out = tmp_path / "ok"
    restore(path, out)
    assert out.read_bytes() == a + b + a


def test_a_bomb_is_refused_before_anything_is_written(tmp_path):
    """One chunk referenced a million times is a 1 KB file that asks for a
    gigabyte. The sizes are added up from the index first."""
    chunk = b"Z" * 1024
    bomb = _forge(tmp_path, [chunk], [(0, 1)] * 4, 2048)
    _refuses(bomb, tmp_path, "more than the declared size")
    honest_about_it = _forge(tmp_path, [chunk], [(0, 1)] * 5000, 5000 * 1024)
    _refuses(honest_about_it, tmp_path, "beyond the", output_limit=64 * KIB)


def test_runs_outside_the_table_and_wrong_totals_are_refused(tmp_path):
    c = b"C" * 640
    _refuses(_forge(tmp_path, [c], [(0, 2)], 1280), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(1, 1)], 640), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(0, 0)], 640), tmp_path, "outside the chunk table")
    _refuses(_forge(tmp_path, [c], [(0, 1)], 641), tmp_path, "do not produce the declared size")
    _refuses(_forge(tmp_path, [c, b""], [(0, 2)], 640), tmp_path, "an empty chunk")


def test_right_chunks_in_the_wrong_order_fail_the_stream_checksum(tmp_path):
    a, b = b"A" * 600, b"B" * 600
    swapped = _forge(tmp_path, [a, b], [(1, 1), (0, 1)], 1200, a + b)
    _refuses(swapped, tmp_path, "rebuilt stream does not match")


# --- review 2026-11-26: a valid-looking file must not be able to cost much -----
#
# An adversarial review found no input that restores a wrong stream, but three
# ways for a small or honest-looking file to cost a lot. Each test below failed
# on the code as reviewed.

def _lying_header(tmp_path: Path, **over) -> Path:
    """A header alone, saying what we like, on a file too small to back it."""
    fields = dict(orig=1 << 20, data=1 << 20, chunks=1, runs=1, index=28)
    fields.update(over)
    header = dedup._HEADER.pack(
        dedup.MAGIC, dedup.FORMAT_VERSION, 0, fields["orig"], fields["data"],
        fields["chunks"], fields["runs"], fields["index"], bytes(32), bytes(16))
    path = tmp_path / "lying.dd"
    path.write_bytes(header)
    return path


def test_a_run_bomb_is_refused_before_its_index_is_read(tmp_path):
    """One 1-byte chunk and N runs of (0, 1) with an honest stream digest was
    a valid file: 3,000,000 runs took 39 s and 247 MiB to restore 3 MB, and
    nothing bounded N. No writer can produce more runs than the stream has
    minimum-size chunks, so the header alone condemns it."""
    import time
    import tracemalloc
    n = 300_000
    bomb = _forge(tmp_path, [b"A"], [(0, 1)] * n, n, b"A" * n)
    tracemalloc.start()
    began = time.perf_counter()
    try:
        _refuses(bomb, tmp_path, "more runs than")
    finally:
        _now, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert time.perf_counter() - began < 1.0
    assert peak < 256 * KIB, f"{peak} bytes: the index was read before it was refused"


def test_more_chunks_than_the_stream_could_be_cut_into_is_refused(tmp_path):
    _refuses(_lying_header(tmp_path, orig=5120, data=5120, chunks=12, runs=1,
                           index=12 * 20 + 8), tmp_path, "more chunks than")


def test_an_index_larger_than_any_writer_makes_is_refused_unread(tmp_path):
    """The writer's worst case is 2^21 chunks (2^19 nominal, every one at the
    quarter-size minimum), 28 bytes each: under 64 MiB."""
    assert (1 << 21) * 28 <= dedup.MAX_INDEX_BYTES
    huge = dedup.MAX_INDEX_BYTES + 28
    _refuses(_lying_header(tmp_path, orig=1 << 40, data=1 << 40, chunks=huge // 28,
                           runs=0, index=huge), tmp_path, "index is larger")


def test_a_legal_file_with_a_run_per_chunk_at_the_bound_restores(tmp_path):
    """The most fragmented stream a writer can make: every chunk the minimum
    size and every one its own run. Exactly at the bound, and accepted."""
    a, b = b"A" * dedup.MIN_LEGAL_CHUNK, b"B" * dedup.MIN_LEGAL_CHUNK
    n = 4000
    runs = [(i & 1, 1) for i in range(n)]
    stream = (a + b) * (n // 2)
    path = _forge(tmp_path, [a, b], runs, len(stream), stream)
    out = tmp_path / "ok"
    assert restore(path, out) == len(stream)
    assert out.read_bytes() == stream


def test_a_short_chunk_is_legal_only_as_the_end_of_the_stream(tmp_path):
    """Every cut but the last is at least the minimum chunk, so a short chunk
    that is referenced anywhere else was not written by this code - and it
    is what a run bomb is made of."""
    a, tail = b"A" * 600, b"t" * 7
    ok = _forge(tmp_path, [a, tail], [(0, 2)], 607, a + tail)
    restore(ok, tmp_path / "ok")
    assert (tmp_path / "ok").read_bytes() == a + tail
    _refuses(_forge(tmp_path, [tail, a], [(0, 2)], 607, tail + a), tmp_path,
             "short chunk")
    _refuses(_forge(tmp_path, [a, tail], [(1, 1), (0, 2)], 614, tail + a + tail),
             tmp_path, "short chunk")


def test_a_maximal_legitimate_file_still_restores(tmp_path):
    """2^19 unique chunks, the most the writer aims for: the caps above must
    not be anywhere near a real file."""
    count, size = dedup.MAX_CHUNKS, dedup.MIN_LEGAL_CHUNK
    rng = random.Random(77)
    data = b"".join(rng.randbytes(1 << 20) for _ in range(count * size >> 20))
    view = memoryview(data)
    index = b"".join(
        dedup._CHUNK_REC.pack(size, hashlib.blake2b(view[i * size:(i + 1) * size],
                                                    digest_size=16).digest())
        for i in range(count)) + dedup._RUN_REC.pack(0, count)
    header = dedup._HEADER.pack(
        dedup.MAGIC, dedup.FORMAT_VERSION, 0, len(data), len(data), count, 1,
        len(index), hashlib.blake2b(data, digest_size=32).digest(),
        hashlib.blake2b(index, digest_size=16).digest())
    path = tmp_path / "max.dd"
    with open(path, "wb") as f:
        f.write(header)
        f.write(data)
        f.write(index)
    assert restore(path, None) == len(data)


def test_a_chunk_nobody_refers_to_is_refused(tmp_path):
    """Canonical files only: bytes the stream never uses are not the writer's."""
    a, b = b"A" * 600, b"B" * 600
    _refuses(_forge(tmp_path, [a, b], [(0, 1)], 600, a), tmp_path, "never used")


def test_a_chunk_longer_than_the_writer_can_cut_is_refused(tmp_path):
    index = (dedup._CHUNK_REC.pack(dedup.MAX_LEGAL_CHUNK + 1, bytes(16))
             + dedup._RUN_REC.pack(0, 1))
    data = b"x" * 4096
    header = dedup._HEADER.pack(
        dedup.MAGIC, dedup.FORMAT_VERSION, 0, 4096, 4096, 1, 1, len(index), bytes(32),
        hashlib.blake2b(index, digest_size=16).digest())
    path = tmp_path / "long.dd"
    path.write_bytes(header + data + index)
    _refuses(path, tmp_path, "longer than any chunk")


def test_a_large_chunk_is_checked_and_written_in_slices(tmp_path, monkeypatch):
    """One chunk used to be one read whatever its length: a 300 MB chunk of
    zeros peaked at 590 MiB. It is hashed in buffer-sized slices, and only
    then read again and written."""
    import tracemalloc
    monkeypatch.setattr(dedup, "_READ", 64 * KIB)
    big = _noise(1 << 20, 60)
    path = _forge(tmp_path, [big], [(0, 1)], len(big), big)
    out = tmp_path / "big"
    tracemalloc.start()
    try:
        restore(path, out)
    finally:
        _now, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert out.read_bytes() == big
    assert peak < 400 * KIB, f"{peak} bytes held for a 1 MiB chunk with 64 KiB buffers"
    _flip(path, HEADER_SIZE + 900_000)             # deep inside the one chunk
    _refuses(path, tmp_path, "chunk 0 does not match")


def test_cancel_reaches_the_validation_of_the_index(tmp_path):
    a = b"A" * 600
    path = _forge(tmp_path, [a], [(0, 1)] * 3, 1800, a * 3)
    calls = []

    def cancelled() -> bool:
        calls.append(1)
        return True
    with pytest.raises(StageError, match="cancelled"):
        restore(path, tmp_path / "never", cancelled=cancelled)
    assert not (tmp_path / "never").exists()
    assert len(calls) == 1, "it was first asked only once output had been opened"


# Cut lengths (SHA-256 of them, packed) on seeded streams, taken from the code
# BEFORE the search was given an end bound. The bound must change how fast the
# cuts are found, never where they fall.
_GOLDEN_CUTS = {
    ("random", 2048): "d4fbb7b6ec323ab4",
    ("zeros", 2048): "1fe21dcb072294ba",
    ("ff", 2048): "a65a862c1da249e6",
    ("two-symbol", 2048): "f04ba3b118e73489",
    ("mixed", 2048): "0e0f0df9616a8063",
    ("period32", 2048): "f04ba3b118e73489",
    ("random", 8192): "49030a118c41dd89",
    ("zeros", 8192): "ba81a1b779e8e074",
    ("ff", 8192): "67427da2a82a52d5",
    ("two-symbol", 8192): "77cf337bb7c6215a",
    ("mixed", 8192): "dfddbd404eab501d",
    ("period32", 8192): "77cf337bb7c6215a",
}


def _golden_streams():
    r = random.Random(2026)
    yield "random", r.randbytes(3 << 20)
    yield "zeros", bytes(3 << 20)
    yield "ff", b"\xff" * (2 << 20)
    yield "two-symbol", bytes(r.choice(b"ab") for _ in range(1 << 20))
    yield "mixed", b"".join(
        r.choice([r.randbytes(r.randrange(1, 200_000)), bytes(r.randrange(1, 300_000)),
                  b"abc" * r.randrange(1, 50_000),
                  bytes([r.randrange(256)]) * r.randrange(1, 100_000)])
        for _ in range(40))
    yield "period32", bytes(range(32)) * (1 << 15)


def test_the_cuts_are_the_ones_the_first_version_made():
    for name, data in _golden_streams():
        for avg in (2048, 8192):
            cuts = _cuts(data, 1 << 20, avg)
            got = hashlib.sha256(struct.pack("<%dI" % len(cuts), *cuts)).hexdigest()[:16]
            assert got == _GOLDEN_CUTS[name, avg], (name, avg)
            # and the same whatever the read size, with the bounded search
            assert _cuts(data, 300_007, avg) == cuts, (name, avg)


def test_data_with_no_candidates_is_not_slower_than_data_with_them():
    """Zeros ran at 5 MB/s against 33 for ordinary data: with no candidate to
    find, every chunk's search ran to the end of the 16 MiB lane buffer. Now
    it stops at the chunk's own limit. A ratio, so a slow machine passes."""
    import time

    def seconds(data: bytes) -> float:
        best = 1e9
        for _ in range(2):
            chunker = Chunker(dedup.AVG_CHUNK)
            began = time.perf_counter()
            chunker.feed(data)
            chunker.feed(b"", final=True)
            best = min(best, time.perf_counter() - began)
        return best

    ordinary = seconds(_noise(8 << 20, 70))
    for name, data in (("zeros", bytes(8 << 20)),
                       ("two-symbol", bytes(random.Random(71).choice(b"ab")
                                            for _ in range(1 << 20)) * 8)):
        assert seconds(data) < 3 * ordinary + 0.3, name


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
    assert engine._stage_factory(
        StageOptions(extra_args=("-m0=lzma2:d=64m:fb=273",)))["dedup"].window == 64 << 20
    assert engine._stage_factory(StageOptions(dict_size="26"))["dedup"].window == 1 << 26


@pytest.mark.parametrize("bad", ["64mb", "abc", "1.5g", "m", "-5m"])
def test_a_dictionary_this_code_cannot_read_does_not_break_the_job(bad):
    """The window is worked out for every compress, Fast and Insane included,
    where no 7-Zip runs at all. An unreadable size is 7-Zip's to refuse (or
    nobody's); here it means the default window."""
    reg = engine._stage_factory(StageOptions(dict_size=bad))
    assert reg["dedup"].window == 256 << 20
    reg = engine._stage_factory(StageOptions(extra_args=(f"-md={bad}",)))
    assert reg["dedup"].window == 256 << 20


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
    assert manifest.schema == 3, "an old build must refuse this before extracting"
    assert record.tool_name == "python" and record.input_bytes > 9 << 20
    assert "dedup" in events and not any("dedup" in w for w in with_stage.warnings)
    assert with_stage.deduped_bytes > 2 << 20

    # The same job with the stage switched off: what every release before
    # B31 would have written.
    monkeypatch.setattr(engine, "_with_dedup", lambda chain: list(chain))
    without = engine.compress([src], tmp_path / "without.excmp", Profile.EXTREME,
                              ctx, options=SMALL_DICT)
    assert with_stage.final_bytes < without.final_bytes - (2 << 20)
    assert without.deduped_bytes == 0

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
    assert manifest.schema == 2, "an archive without the stage stays readable by 0.1.0"

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


# --- calibration --------------------------------------------------------------

def _calibrated(tmp_path, monkeypatch, piped: int, elapsed: float, deduped: int):
    pytest.importorskip("PySide6")
    from types import SimpleNamespace

    from excmp.analyzer import Category, FileInfo
    from excmp.planner import plan
    from excmp.tools import ToolInfo
    from gui.models import Job
    from gui.queue_manager import CompressWorker
    from gui.suggest import strongest_profile, summarize

    tools = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
             for n in ("7z", "precomp")}
    infos = [FileInfo(path=Path("a.dat"), size=piped, category=Category.TEXT,
                      entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)]
    summary = summarize(infos, plan(infos, Profile.EXTREME, tools), tools,
                        reference_plan=plan(infos, strongest_profile(tools), tools))

    class _Rec:
        def emit(self, *a):
            pass

    signals = SimpleNamespace(progress=_Rec(), log=_Rec(), started=_Rec(), done=_Rec(),
                              failed=_Rec(), cancelled=_Rec())
    job = Job(inputs=[tmp_path], out_path=tmp_path / "o.excmp",
              profile=Profile.EXTREME, summary=summary)
    recorded: list = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    result = SimpleNamespace(
        piped_bytes=piped, final_bytes=1, orig_bytes=2, elapsed_s=elapsed,
        deduped_bytes=deduped,
        routes=[{"action": "pipeline", "stages": ["precomp", "sevenzip"]}])
    CompressWorker(job, signals, tmp_path, tools={})._calibrate(result)
    return recorded


def test_a_job_the_stage_shortened_teaches_the_estimator_nothing(tmp_path, monkeypatch):
    """7-Zip was handed half the piped bytes: learned as the chain's rate,
    the next job with no repeats would be promised half its real time."""
    assert _calibrated(tmp_path, monkeypatch, 600 << 20, 300.0, 300 << 20) == []


def test_a_job_it_only_scanned_teaches_the_rate_without_the_scan(tmp_path, monkeypatch):
    from excmp.estimate import dedup_seconds, job_fixed_seconds
    piped = 600 << 20
    stages = ["precomp", "sevenzip"]
    recorded = _calibrated(tmp_path, monkeypatch, piped, 500.0, 0)
    assert len(recorded) == 1
    assert recorded[0]["elapsed_s"] == pytest.approx(
        500.0 - job_fixed_seconds(stages) - dedup_seconds(piped, stages))
    assert dedup_seconds(piped, stages) > 0


# --- the estimate -------------------------------------------------------------

def test_the_estimate_bills_the_scan_only_where_it_can_run():
    from excmp.estimate import DEDUP_SCAN_RATE, dedup_seconds
    big = 1 << 30
    assert dedup_seconds(big, ["precomp", "sevenzip"]) == pytest.approx(big / DEDUP_SCAN_RATE)
    assert dedup_seconds(200 << 20, ["precomp", "sevenzip"]) == 0.0     # inside the window
    assert dedup_seconds(big, ["sevenzip"]) == 0.0
    assert dedup_seconds(big, ["precomp", "zpaqfranz"]) == 0.0
    assert dedup_seconds(big, []) == 0.0


def test_the_estimate_uses_the_window_the_stage_will_use():
    """A job with a 64 MiB dictionary is scanned from 64 MiB up, not 256."""
    from excmp.estimate import DEDUP_SCAN_RATE, dedup_seconds
    chain = ["precomp", "sevenzip"]
    job = 200 << 20
    assert dedup_seconds(job, chain) == 0.0
    assert dedup_seconds(job, chain, window=64 << 20) == pytest.approx(job / DEDUP_SCAN_RATE)
    assert engine.dedup_window(StageOptions(dict_size="64m")) == 64 << 20
    assert engine.dedup_window(None) == 256 << 20


def test_only_an_archive_with_the_stage_gets_the_newer_schema():
    """0.1.0 reads schema 2 and has no dedup stage. Given schema 3 it says
    'written by a newer version' at once, instead of running a whole 7-Zip
    extract and then failing on a stage it has never heard of. Everything
    without the stage is still written as 2."""
    from excmp.manifest import (MAX_SCHEMA_VERSION, SCHEMA_VERSION, ContainerError,
                                Manifest, StageRecord)
    plain = Manifest.new(profile="extreme", payload_name="p.7z", inputs={}, stages=[
        StageRecord("tar", "python", "", {}), StageRecord("sevenzip", "7z", "", {})])
    with_stage = Manifest.new(profile="extreme", payload_name="p.7z", inputs={}, stages=[
        StageRecord("tar", "python", "", {}),
        StageRecord("dedup", "python", "", {"format": 1, "window": 1}),
        StageRecord("sevenzip", "7z", "", {})])
    assert plain.schema == SCHEMA_VERSION == 2
    assert with_stage.schema == MAX_SCHEMA_VERSION == 3
    assert Manifest.from_json(with_stage.to_json()).schema == 3
    newer = with_stage.to_json().replace('"schema": 3', '"schema": 4').replace(
        '"schema":3', '"schema":4')
    assert newer != with_stage.to_json()
    with pytest.raises(ContainerError, match="newer version"):
        Manifest.from_json(newer)
