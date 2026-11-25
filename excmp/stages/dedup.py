"""Long-range block dedup: the job SREP had in the chain until B11 (B31).

**The gap.** Extreme's final codec is 7-Zip LZMA2, and LZMA2 only finds a
repeat inside its dictionary: 256 MiB at ``-mx9``. Two versions of one
design file that Precomp expands to ~326 MB each therefore reach 7-Zip 326 MB
apart, and it compresses both copies in full. (Numbers and corpora:
``docs/benchmarks/2026-11-25-dedup-stage.md``.)

**What this stage does.** It cuts the stream into content-defined chunks,
keeps the first copy of each chunk and replaces every later copy with a
reference, and hands 7-Zip the unique bytes plus a small index. Restoring
copies the chunks back in their original order.

**It is opportunistic.** It runs only where it can matter and steps aside
(:class:`~excmp.stages.base.QuietSkip`) everywhere else:

* a stream no larger than the codec's window is not even read, because the
  codec already sees every repeat in it;
* a larger stream is scanned (read once, nothing written), and unless the
  repeats the codec cannot reach come to at least :data:`MIN_SAVING` of it,
  the stage is skipped and the chain runs exactly as before;
* any error at all - a full temp disk, a self-check mismatch - also skips
  it, with a note, and the chain runs exactly as before.

**Integrity.** Nothing here is trusted on the way back. The index is hashed
and checked before it is parsed into offsets, every chunk is hashed
(BLAKE2b-128) and compared *before* its bytes are written, the sizes must
add up to the recorded total before the first byte is written, and the whole
rebuilt stream is hashed (BLAKE2b-256) and compared at the end. The stage
also restores its own output once, in memory, before it reports success.
And after all of that the engine's SHA-256 ledger gate still restores the
whole archive and compares every file, as it does for every stage.

**The chunker is not part of the format.** Where the cuts fall decides only
how much is saved. The file records chunk lengths, so a reader never
re-chunks, and the cut rule can change without a format bump.

On-disk layout, version 1, little-endian::

    header  104 bytes
        8   magic  b"EXCMPDD1"
        4   u32    version (1)
        4   u32    flags (0)
        8   u64    orig_size      bytes of the stream this restores to
        8   u64    data_size      bytes in the data section
        8   u64    chunk_count    unique chunks
        8   u64    run_count
        8   u64    index_size
        32  bytes  BLAKE2b-256 of the original stream
        16  bytes  BLAKE2b-128 of the index section
    data    the unique chunks, first copies, in the order first seen
    index   chunk_count x (u32 length, 16-byte BLAKE2b-128 of the chunk)
            run_count   x (u32 first_chunk, u32 count)

A run says "write chunks first..first+count-1". Unique data is one long run,
and so is a second copy of something already seen, so the index stays small:
20 bytes per unique chunk plus 8 per run.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
import zlib
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from .base import QuietSkip, Stage, StageContext, StageError, StageSkip

MIB = 1 << 20

MAGIC = b"EXCMPDD1"
FORMAT_VERSION = 1
_HEADER = struct.Struct("<8sIIQQQQQ32s16s")
HEADER_SIZE = _HEADER.size          # 104
_CHUNK_REC = struct.Struct("<I16s")
_RUN_REC = struct.Struct("<II")

#: The stage is skipped unless the repeats the codec cannot reach are at
#: least this share of the stream.
MIN_SAVING = 0.02

#: LZMA2's dictionary at ``-mx9`` (`excmp.ram._DEFAULT_DICT`), the default
#: reach of the codec this stage runs in front of.
DEFAULT_WINDOW = 256 * MIB

#: Average chunk, and the bound that keeps the index in memory small: the
#: average doubles until the stream is at most this many chunks.
AVG_CHUNK = 8 * 1024
MAX_CHUNKS = 1 << 19

_READ = 8 * MIB

# --- the chunker ------------------------------------------------------------
#
# A cut is content-defined: whether there is one after byte p depends only on
# the 32 bytes before p (and on how far back the previous cut is), so the
# same data cut at a different offset in the stream gets the same cuts.
#
# Per-byte work in Python would run at about 1 MB/s, so the first test is
# done with whole-buffer operations that run in C: every byte goes through a
# fixed table, the results are spread into 16-bit lanes of one big integer,
# and five shift-and-adds leave each lane holding the sum of the 32 table
# values that start there. A lane whose low 10 bits equal `_TARGET` is a
# candidate (1 position in 1,024 on ordinary data), found with a compiled
# pattern. A CRC-32 of the same 32 bytes then decides, which supplies the
# rest of the bits for the average chunk size.
#
# `_TARGET` is odd on purpose. A run of one repeated byte sums to 32 x the
# table value, whose low five bits are zero, so a constant run (or any period
# that divides 32) is never a candidate and never slows the scan; it is cut
# at the maximum chunk size instead, which dedups it just as well.
_WINDOW = 32
_TABLE = b"".join(hashlib.sha256(b"excmp-dedup-%d" % i).digest() for i in range(8))
_TARGET = 0x2A5
_CAND_BITS = 10
#: After a rejected candidate the search moves on this many bytes. On
#: ordinary data candidates are ~1,024 bytes apart and it changes nothing; on
#: a short-period pattern where every few bytes is a candidate it bounds the
#: Python-level work.
_REJECT_STEP = 16
_CAND = re.compile(
    b"\\x%02x[" % (_TARGET & 0xFF)
    + b"".join(b"\\x%02x" % b for b in range(256)
               if b & ((1 << (_CAND_BITS - 8)) - 1) == _TARGET >> 8 and b < 32)
    + b"]")
assert _TARGET & 1 and (_TARGET & 0xFF) > 31     # see the two notes above


def _lanes(buf: bytes) -> bytes:
    """Two bytes per input byte: the 16-bit sum of the 32 table values that
    start at that byte (partial for the last 31, which callers ignore)."""
    n = int.from_bytes(
        buf.translate(_TABLE).decode("latin-1").encode("utf-16-le"), "little")
    for shift in (16, 32, 64, 128, 256):
        n += n >> shift
    return n.to_bytes(2 * len(buf), "little")


def chunk_size_for(stream_bytes: int, avg: int = AVG_CHUNK) -> int:
    """The average chunk for a stream this long: ``avg``, doubled until the
    stream is at most :data:`MAX_CHUNKS` chunks, so the index a huge job
    builds in memory stays the size of a small one."""
    while stream_bytes / avg > MAX_CHUNKS and avg < 1 << 28:
        avg *= 2
    return avg


class Chunker:
    """Feed it the stream in blocks; get back chunk lengths.

    The cuts do not depend on how the stream is split into blocks.
    """

    def __init__(self, avg: int = AVG_CHUNK) -> None:
        bits = max(avg.bit_length() - 1, _CAND_BITS + 1)
        self.avg = 1 << bits
        self.min = self.avg // 4
        self.max = self.avg * 8
        extra = bits - _CAND_BITS
        # Normalized chunking: one bit harder before the average, one bit
        # easier after it, which pulls the sizes toward the average.
        self._strict = (1 << (extra + 1)) - 1
        self._loose = (1 << max(extra - 1, 0)) - 1
        self._pending = b""

    def feed(self, block: bytes, final: bool = False) -> tuple[bytes, list[int]]:
        """Returns ``(data, lengths)``: ``data`` is the bytes the lengths cut
        up, in order. What is not yet cut is held for the next call; with
        ``final`` everything is returned."""
        work = self._pending + block if self._pending else block
        size = len(work)
        lengths: list[int] = []
        start = 0
        if size >= self.min:
            lanes = _lanes(work)
            search = _CAND.search
            crc = zlib.crc32
            minimum, average, maximum = self.min, self.avg, self.max
            window = _WINDOW
            last_window = size - window          # last complete window start
            while True:
                limit = start + maximum
                pos = start + minimum - window
                cut = 0
                while pos <= last_window:
                    m = search(lanes, 2 * pos)
                    if m is None:
                        break
                    i = m.start()
                    if i & 1:                     # cannot happen; see _TARGET
                        pos = (i + 1) // 2
                        continue
                    i //= 2
                    if i > last_window or i + window > limit:
                        break
                    end = i + window
                    mask = self._strict if end - start < average else self._loose
                    if crc(work[i:end]) & mask == 0:
                        cut = end
                        break
                    pos = i + _REJECT_STEP
                if not cut:
                    if limit <= size:
                        cut = limit               # no cut found in a full span
                    else:
                        break
                lengths.append(cut - start)
                start = cut
        if final:
            if start < size:
                lengths.append(size - start)
                start = size
            self._pending = b""
            return work, lengths
        self._pending = work[start:]
        return (work[:start] if start < size else work), lengths


# --- scanning ---------------------------------------------------------------

@dataclass
class Scan:
    """What one read of the stream found. Nothing has been written."""

    orig_size: int
    stream_digest: bytes
    #: Per unique chunk: its length, digest, and where its first copy starts.
    lengths: array
    digests: bytearray
    offsets: array
    #: ``[first_chunk, count, ...]`` flattened.
    runs: array
    #: Bytes that are later copies of a chunk already seen.
    duplicate_bytes: int
    #: The part of those whose earlier copy the codec could not have reached.
    far_bytes: int

    @property
    def data_size(self) -> int:
        return self.orig_size - self.duplicate_bytes

    @property
    def index_size(self) -> int:
        return len(self.lengths) * _CHUNK_REC.size + len(self.runs) // 2 * _RUN_REC.size

    @property
    def output_size(self) -> int:
        return HEADER_SIZE + self.data_size + self.index_size


def _blocks(fh: BinaryIO, cancelled: Callable[[], bool]) -> Iterator[bytes]:
    while True:
        if cancelled():
            raise StageError("dedup: cancelled")
        block = fh.read(_READ)
        if not block:
            return
        yield block


def scan(src: Path, window: int = DEFAULT_WINDOW, avg: int | None = None,
         progress: Callable[[float], None] = lambda pct: None,
         cancelled: Callable[[], bool] = lambda: False) -> Scan:
    """Read ``src`` once and find its repeated chunks.

    A repeat counts as *far* when the codec could not have used the earlier
    copy: the nearest one is more than ``window`` bytes back. Distance is the
    whole rule. 7-Zip 26.02 at ``-mx9 -mmt2`` was measured on 160 MiB of
    random bytes written twice: 160.0 MiB out, so it found a repeat 160 MiB
    back *across* the 256 MiB mark, and block boundaries are not a limit.
    """
    src = Path(src)
    total = src.stat().st_size
    chunker = Chunker(avg if avg is not None else chunk_size_for(total))
    stream = hashlib.blake2b(digest_size=32)
    seen: dict[bytes, int] = {}
    lengths, offsets, last = array("I"), array("Q"), array("Q")
    digests = bytearray()
    runs = array("I")
    run_first, run_count = 0, 0
    duplicate = far = 0
    position = 0
    blake = hashlib.blake2b

    def consume(data: bytes, cuts: list[int]) -> None:
        nonlocal run_first, run_count, duplicate, far, position
        view = memoryview(data)
        at = 0
        for length in cuts:
            digest = blake(view[at:at + length], digest_size=16).digest()
            at += length
            cid = seen.get(digest)
            if cid is None:
                cid = len(lengths)
                seen[digest] = cid
                lengths.append(length)
                offsets.append(position)
                last.append(position)
                digests.extend(digest)
            else:
                duplicate += length
                before = last[cid]
                if position - before > window:
                    far += length
                last[cid] = position
            if run_count and cid == run_first + run_count:
                run_count += 1
            else:
                if run_count:
                    runs.append(run_first)
                    runs.append(run_count)
                run_first, run_count = cid, 1
            position += length

    with open(src, "rb") as fh:
        for block in _blocks(fh, cancelled):
            stream.update(block)
            consume(*chunker.feed(block))
            progress(100.0 * position / total if total else 100.0)
        consume(*chunker.feed(b"", final=True))
    if run_count:
        runs.append(run_first)
        runs.append(run_count)
    if position != total:
        raise StageError(f"dedup: read {position} bytes of a {total}-byte stream")
    return Scan(orig_size=total, stream_digest=stream.digest(), lengths=lengths,
                digests=digests, offsets=offsets, runs=runs,
                duplicate_bytes=duplicate, far_bytes=far)


# --- writing ----------------------------------------------------------------

def _index_bytes(found: Scan) -> bytes:
    out = bytearray()
    digests = found.digests
    for cid, length in enumerate(found.lengths):
        out += _CHUNK_REC.pack(length, bytes(digests[cid * 16:cid * 16 + 16]))
    runs = found.runs
    for i in range(0, len(runs), 2):
        out += _RUN_REC.pack(runs[i], runs[i + 1])
    return bytes(out)


def write(src: Path, dst: Path, found: Scan,
          progress: Callable[[float], None] = lambda pct: None,
          cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Write the deduplicated form of ``src`` (which :func:`scan` read) to ``dst``."""
    index = _index_bytes(found)
    header = _HEADER.pack(
        MAGIC, FORMAT_VERSION, 0, found.orig_size, found.data_size,
        len(found.lengths), len(found.runs) // 2, len(index),
        found.stream_digest, hashlib.blake2b(index, digest_size=16).digest())
    lengths, offsets = found.lengths, found.offsets
    done = 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(header)
        cid, count = 0, len(lengths)
        while cid < count:
            # First copies that sit side by side in the source are one read.
            begin = offsets[cid]
            end = begin + lengths[cid]
            cid += 1
            while cid < count and offsets[cid] == end and end - begin < _READ:
                end += lengths[cid]
                cid += 1
            if cancelled():
                raise StageError("dedup: cancelled")
            fin.seek(begin)
            piece = fin.read(end - begin)
            if len(piece) != end - begin:
                raise StageError("dedup: the stream changed while it was being written")
            fout.write(piece)
            done += len(piece)
            progress(100.0 * done / found.data_size if found.data_size else 100.0)
        fout.write(index)
    return dst


# --- restoring --------------------------------------------------------------

def _bad(why: str) -> StageError:
    return StageError(f"dedup: this archive's dedup stream is damaged ({why})")


def restore(src: Path, dst: Path | None, output_limit: int = 0,
            progress: Callable[[float], None] = lambda pct: None,
            cancelled: Callable[[], bool] = lambda: False) -> int:
    """Rebuild the original stream from ``src`` into ``dst``; return its size.

    ``dst=None`` does everything but write, which is the stage's self-check.
    ``output_limit`` (when not 0) refuses a stream that declares more than
    that many bytes, before anything is written.

    Every figure in the file is checked against the file before it is used,
    and every chunk against its digest before its bytes go out. A mismatch
    raises :class:`StageError` and leaves no output behind.
    """
    src = Path(src)
    file_size = src.stat().st_size
    with open(src, "rb") as fin:
        raw = fin.read(HEADER_SIZE)
        if len(raw) != HEADER_SIZE:
            raise _bad("too short for a header")
        (magic, version, flags, orig_size, data_size, chunk_count, run_count,
         index_size, stream_digest, index_digest) = _HEADER.unpack(raw)
        if magic != MAGIC:
            raise _bad("wrong signature")
        if version != FORMAT_VERSION or flags != 0:
            raise StageError(
                f"dedup: stream format {version} (flags {flags:#x}) is newer than "
                f"this build understands ({FORMAT_VERSION})")
        if HEADER_SIZE + data_size + index_size != file_size:
            raise _bad("the sections do not add up to the file")
        if chunk_count * _CHUNK_REC.size + run_count * _RUN_REC.size != index_size:
            raise _bad("the index is not the size its counts give")
        if output_limit and orig_size > output_limit:
            raise StageError(
                f"dedup: the stream declares {orig_size >> 20} MiB, beyond the "
                f"{output_limit >> 20} MiB this archive allows for it")
        fin.seek(HEADER_SIZE + data_size)
        index = fin.read(index_size)
        if len(index) != index_size:
            raise _bad("the index is cut short")
        if hashlib.blake2b(index, digest_size=16).digest() != index_digest:
            raise _bad("the index does not match its checksum")

        table = memoryview(index)[:chunk_count * _CHUNK_REC.size]
        lengths = array("I", bytes(chunk_count * 4))
        offsets = array("Q", bytes(chunk_count * 8))
        at = 0
        for cid, (length, _digest) in enumerate(_CHUNK_REC.iter_unpack(table)):
            if length == 0:
                raise _bad("an empty chunk")
            lengths[cid] = length
            offsets[cid] = at
            at += length
        if at != data_size:
            raise _bad("the chunks do not add up to the data")
        runs = list(_RUN_REC.iter_unpack(memoryview(index)[len(table):]))
        produced = 0
        for first, count in runs:
            if count == 0 or first + count > chunk_count:
                raise _bad("a run points outside the chunk table")
            # offsets are cumulative, so a run's bytes are one subtraction
            last = first + count - 1
            produced += offsets[last] + lengths[last] - offsets[first]
            if produced > orig_size:
                raise _bad("the runs produce more than the declared size")
        if produced != orig_size:
            raise _bad("the runs do not produce the declared size")

        stream = hashlib.blake2b(digest_size=32)
        blake = hashlib.blake2b
        rec = _CHUNK_REC.size
        out = open(dst, "wb") if dst is not None else None
        ok = False
        written = 0
        try:
            for first, count in runs:
                cid, stop = first, first + count
                while cid < stop:
                    if cancelled():
                        raise StageError("dedup: cancelled")
                    # one read for as many whole chunks as fit a buffer
                    begin = offsets[cid]
                    upto = cid
                    span = 0
                    while upto < stop and (span == 0 or span + lengths[upto] <= _READ):
                        span += lengths[upto]
                        upto += 1
                    fin.seek(HEADER_SIZE + begin)
                    piece = fin.read(span)
                    if len(piece) != span:
                        raise _bad("the data is cut short")
                    view = memoryview(piece)
                    pos = 0
                    for c in range(cid, upto):
                        length = lengths[c]
                        want = table[c * rec + 4:c * rec + rec]
                        if blake(view[pos:pos + length], digest_size=16).digest() != want:
                            raise _bad(f"chunk {c} does not match its checksum")
                        pos += length
                    stream.update(piece)
                    if out is not None:
                        out.write(piece)
                    written += span
                    cid = upto
                    progress(100.0 * written / orig_size if orig_size else 100.0)
            if stream.digest() != stream_digest:
                raise _bad("the rebuilt stream does not match its checksum")
            ok = True
        finally:
            if out is not None:
                out.close()
                if not ok:
                    Path(dst).unlink(missing_ok=True)
    return orig_size


# --- the stage --------------------------------------------------------------

class DedupStage(Stage):
    """See the module docstring. ``window`` is how far back the next codec
    can see on its own (its dictionary)."""

    id = "dedup"

    def __init__(self, window: int = DEFAULT_WINDOW, min_saving: float = MIN_SAVING,
                 avg_chunk: int | None = None) -> None:
        self.window = max(int(window), 1)
        self.min_saving = float(min_saving)
        self.avg_chunk = avg_chunk

    def available(self) -> bool:
        return True

    def record_params(self) -> dict:
        """What the manifest's stage record says about this stage."""
        return {"format": FORMAT_VERSION, "window": self.window}

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        if not src.is_file():
            raise QuietSkip(f"{self.id}: needs a single stream")
        size = src.stat().st_size
        if size <= self.window:
            # The codec's own window covers the whole stream. Not even read.
            raise QuietSkip(f"{self.id}: the stream fits the codec's window")

        def cancelled() -> bool:
            return ctx.cancel.is_set()

        try:
            # Scanning is ~90% of the stage when it then skips, ~70% when not.
            found = scan(src, self.window, self.avg_chunk,
                         lambda pct: ctx.progress_cb(self.id, pct * 0.7), cancelled)
            saved = found.orig_size - found.output_size
            if found.far_bytes < self.min_saving * size or saved <= 0:
                ctx.log_cb(self.id, f"scanned {size >> 20} MiB: {found.far_bytes >> 20} "
                                    f"MiB of long-range repeats, not worth a stage")
                ctx.progress_cb(self.id, 100.0)
                raise QuietSkip(f"{self.id}: nothing worth deduplicating")
            free = shutil.disk_usage(dst.parent).free
            if free < found.output_size + 64 * MIB:
                raise StageSkip(
                    f"{self.id}: {found.duplicate_bytes >> 20} MiB of repeated data "
                    f"was found but the temp folder has no room to remove it "
                    f"({free >> 20} MiB free); compressed without that step")
            write(src, dst, found,
                  lambda pct: ctx.progress_cb(self.id, 70.0 + pct * 0.2), cancelled)
            # Prove the file just written rebuilds the stream that was read,
            # with the reader users will run, before the chain depends on it.
            if restore(dst, None, cancelled=cancelled) != size:
                raise StageError(f"{self.id}: self-check size mismatch")
        except StageSkip:
            dst.unlink(missing_ok=True)
            raise
        except Exception as exc:
            dst.unlink(missing_ok=True)
            if ctx.cancel.is_set():
                raise StageError(f"{self.id}: cancelled") from exc
            # Fail-safe: whatever went wrong here, the chain without this
            # stage is the one every earlier release ran.
            raise StageSkip(f"{self.id}: skipped after an error ({exc}); "
                            f"compressed without it") from exc
        ctx.log_cb(self.id, f"removed {found.duplicate_bytes >> 20} MiB of repeated "
                            f"data from {size >> 20} MiB ({len(found.lengths):,} "
                            f"unique chunks, {len(found.runs) // 2:,} runs)")
        ctx.progress_cb(self.id, 100.0)
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        out = dst / (src.stem + ".stream")
        restore(src, out, getattr(ctx, "output_limit", 0),
                lambda pct: ctx.progress_cb(self.id, pct),
                lambda: ctx.cancel.is_set())
        ctx.progress_cb(self.id, 100.0)
        return out
