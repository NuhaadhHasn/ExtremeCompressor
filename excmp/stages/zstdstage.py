"""Fast profile stage: tar the tree, stream it through Zstandard.

Uses the ``zstandard`` pip package (BSD, bundles libzstd) so the Fast
profile needs no external binary. Long-distance matching gives it a bit
of SREP-like long-range dedup for free.

K4 (2026-09-07) widened the window from 27 (128 MiB) to 31 (2 GiB) and, more
importantly, **decoupled the read ceiling from the write setting**. Measured on
300 MiB whose duplicate half sits 150 MiB away, streamed:

    window_log 27   314,580,006 B   115.3 s
    window_log 31   157,699,989 B    74.8 s     49.9% smaller, 1.54x faster

The saving is not magic: at 27 the match is simply out of range, so half the
data has to be entropy-coded a second time. The Programs corpus averages
~143 MB per installer, so anything shared between two of them sat beyond the
old window and was invisible.

The read side is where the real defect was. ``extract`` used
``max_window_size = 1 << self.long_log``, i.e. a build could only ever read
archives as wide as it writes - so raising the compress default alone would
have produced archives older builds could not open. Measured peak working set
(from the OS; ``tracemalloc`` cannot see zstd's C-side window buffer):

    ceiling 27, 27-window frame    146 MiB
    ceiling 31, 27-window frame    146 MiB     <- raising the ceiling is free
    ceiling 31, 31-window frame    317 MiB

So the ceiling is exactly that - a ceiling, not an allocation - and it is now a
module constant rather than a mirror of whatever the writer was told to do.
Reading a genuinely wide frame costs +171 MiB on a 16 GB target, which is the
honest price of halving the output, and decompress *time* is unchanged.

The compress side costs real memory, and the roadmap was wrong about the
direction: it predicted peak working set would *fall* (1,707 -> 1,644 MiB), and
measured at ``threads=-1`` a fixed window_log=31 made it **rise** from 1,002 to
1,813 MiB.

So the window is **fitted to the input** rather than pinned at the maximum. A
window larger than the data cannot find matches the data does not contain, and
that is not a guess either - the same 300 MiB corpus, three windows:

    window_log 29 (512 MiB)   157,699,989 B   54.0 s   1,045 MiB peak
    window_log 30 (1 GiB)     157,699,989 B   71.5 s   1,289 MiB peak
    window_log 31 (2 GiB)     157,699,989 B   55.0 s   1,814 MiB peak

**Byte-identical output at all three**, for 769 MiB less memory at the fitted
size. `_window_log_for` therefore rounds the input size up to the next power of
two and clamps it to [27, 31]: the floor keeps small jobs exactly where they
were before K4, and the ceiling is the most zstd supports.

`excmp/ram.py` models LZMA2 dictionaries only, so none of this appears in the
GUI's peak-RAM column for the Fast profile - noted in the roadmap as a gap.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import zstandard

from .base import Stage, StageContext, StageError

_CHUNK = 1 << 20

#: Compress-side ceiling: 2 GiB of match distance, the most zstd supports.
COMPRESS_WINDOW_LOG_MAX = 31

#: Compress-side floor: what the stage used before K4 (128 MiB). Keeping it
#: means a small job allocates no more than it always did, and never less -
#: dropping below what `from_level(19)` would choose could cost ratio.
COMPRESS_WINDOW_LOG_FLOOR = 27

#: Read-side ceiling, deliberately **not** derived from the compress setting.
#:
#: A decompressor's ``max_window_size`` is a refusal threshold, not a buffer
#: size: zstd allocates what the frame declares it needs, so a wide ceiling
#: costs nothing on a narrow archive (measured 146 MiB either way). Deriving it
#: from ``long_log`` meant a build configured to compress narrowly could not
#: read a wide archive at all - *"Frame requires too much memory for
#: decoding"* - which would have made every K4-era archive unreadable by any
#: caller that passed a smaller ``long_log``.
#:
#: It bounds a hostile frame at 2 GiB, which is the point of having it. The
#: ledger-derived bounds in `manifest`/`engine` are what bound the *output*;
#: this bounds the window buffer alone.
DECOMPRESS_WINDOW_LOG = 31


def _window_log_for(total_bytes: int) -> int:
    """The smallest window that can still see across the whole input.

    ``bit_length()`` on the byte count is ceil(log2) rounded up to the next
    power of two, which is exactly what a window_log is. Clamped to
    [27, 31]: below the floor a job would get a smaller window than it had
    before K4, and 31 is zstd's maximum.
    """
    need = max(int(total_bytes), 1).bit_length()
    return max(COMPRESS_WINDOW_LOG_FLOOR, min(COMPRESS_WINDOW_LOG_MAX, need))


def _all_logical() -> int:
    """What zstd's -1 resolves to: python-zstandard turns it into the logical
    processor count when it builds the parameters (4 on the i5-7200U)."""
    return zstandard.ZstdCompressionParameters.from_level(1, threads=-1).threads


class ZstdStage(Stage):
    id = "zstd"

    def __init__(self, level: int = 19, long_log: int | None = None):
        self.level = level
        #: ``None`` means "fit the window to the input" (the default, and the
        #: only setting that gets K4's ratio without K4's memory bill). An
        #: explicit value is honoured as-is, which is what the tests and the
        #: advanced knobs use.
        self.long_log = long_log

    def available(self) -> bool:
        return True  # pure pip dependency

    def _compress_window_log(self, total_bytes: int) -> int:
        return (self.long_log if self.long_log is not None
                else _window_log_for(total_bytes))

    def _params(self, total_bytes: int = 0,
                threads: int = 0) -> zstandard.ZstdCompressionParameters:
        """``threads`` is the Worker threads setting: 0 ("auto") keeps -1,
        every logical processor, and a count the user chose is passed as is.

        B18 measured -1 against 2 on a 212 MB Silesia tar: identical bytes,
        184 MiB more peak at -1 (735 against 552 MiB), and timings that can't
        settle speed. -1 was quicker in three pairs, but always ran first, and
        on a contended machine the same 4-thread setting took 37.1 s and
        19.6 s on the installer tar. Unlike 7-Zip, whose extra threads cost
        ratio, zstd's bytes don't depend on the worker count (1, 2, 4 and -1
        all gave 46,982,246 B), so nothing measured argues for changing the
        default, and it stays. Honouring the setting changes speed and
        memory, never the archive. 0 is not passed through: to zstd it means
        no worker threads, which *does* change the bytes.

        A count above the default is capped at it (review, B18): each worker
        holds its own window-sized buffers, `ram.zstd_compress_ram` was fitted
        at -1, and the setting exists to lower the load, not raise it.
        """
        return zstandard.ZstdCompressionParameters.from_level(
            self.level,
            window_log=self._compress_window_log(total_bytes),
            enable_ldm=True,
            threads=min(threads, _all_logical()) if threads > 0 else -1,
        )

    def _decompress_window_log(self) -> int:
        """The read ceiling. A method so a test can pin that it ignores
        ``long_log`` - that coupling is the bug K4 fixed, and it is the kind
        that reappears the moment somebody "tidies" the constant away."""
        # Clamped, not `max()`. 31 is zstd's hard maximum on 64-bit
        # (`zstandard.WINDOWLOG_MAX`), so an unbounded `max()` against a
        # larger `long_log` produced an *invalid* parameter and extract raised
        # "unable to set max window size: Parameter is out of bound" - a
        # ceiling that refuses to read anything, which is the exact opposite
        # of this method's purpose.
        return min(COMPRESS_WINDOW_LOG_MAX,
                   max(DECOMPRESS_WINDOW_LOG, self.long_log or 0))

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        files = [p for p in ([src] if src.is_file() else sorted(src.rglob("*"))) if p.is_file()]
        total = sum(p.stat().st_size for p in files) or 1
        done = 0
        # The window is sized from the real byte count, which is already in
        # hand for the progress denominator.
        cctx = zstandard.ZstdCompressor(
            compression_params=self._params(total, getattr(ctx, "threads", 0) or 0))
        with dst.open("wb") as raw:
            with cctx.stream_writer(raw, closefd=False) as zw:
                with tarfile.open(mode="w|", fileobj=zw, format=tarfile.PAX_FORMAT) as tar:
                    for p in files:
                        if ctx.cancel.is_set():
                            raise StageError(f"{self.id}: cancelled")
                        arcname = p.name if src.is_file() else str(p.relative_to(src))
                        tar.add(p, arcname=arcname, recursive=False)
                        done += p.stat().st_size
                        ctx.progress_cb(self.id, done * 100.0 / total)
        ctx.progress_cb(self.id, 100.0)
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        dctx = zstandard.ZstdDecompressor(
            max_window_size=1 << self._decompress_window_log())
        with src.open("rb") as raw:
            with dctx.stream_reader(raw) as zr:
                with tarfile.open(mode="r|", fileobj=zr) as tar:
                    tar.extractall(dst, filter="data")
        ctx.progress_cb(self.id, 100.0)
        return dst
