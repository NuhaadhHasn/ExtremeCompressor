"""Fast profile stage: tar the tree, stream it through Zstandard.

Uses the ``zstandard`` pip package (BSD, bundles libzstd) so the Fast
profile needs no external binary. Long-distance matching gives it a bit
of SREP-like long-range dedup for free.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import zstandard

from .base import Stage, StageContext, StageError

_CHUNK = 1 << 20


class ZstdStage(Stage):
    id = "zstd"

    def __init__(self, level: int = 19, long_log: int = 27):
        self.level = level
        self.long_log = long_log  # 27 = 128 MiB window; safe within 16 GB RAM

    def available(self) -> bool:
        return True  # pure pip dependency

    def _params(self) -> zstandard.ZstdCompressionParameters:
        return zstandard.ZstdCompressionParameters.from_level(
            self.level,
            window_log=self.long_log,
            enable_ldm=True,
            threads=-1,
        )

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        files = [p for p in ([src] if src.is_file() else sorted(src.rglob("*"))) if p.is_file()]
        total = sum(p.stat().st_size for p in files) or 1
        done = 0
        cctx = zstandard.ZstdCompressor(compression_params=self._params())
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
        dctx = zstandard.ZstdDecompressor(max_window_size=1 << self.long_log)
        with src.open("rb") as raw:
            with dctx.stream_reader(raw) as zr:
                with tarfile.open(mode="r|", fileobj=zr) as tar:
                    tar.extractall(dst, filter="data")
        ctx.progress_cb(self.id, 100.0)
        return dst
