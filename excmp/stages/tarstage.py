"""Plain tar stage: turns a tree into the single file that byte-oriented
stages (precomp, srep) need as input. No compression here by design."""

from __future__ import annotations

import tarfile
from pathlib import Path

from .base import Stage, StageContext, StageError


class TarStage(Stage):
    id = "tar"

    def available(self) -> bool:
        return True

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        files = [p for p in ([src] if src.is_file() else sorted(src.rglob("*"))) if p.is_file()]
        with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT) as tar:
            for p in files:
                if ctx.cancel.is_set():
                    raise StageError(f"{self.id}: cancelled")
                arcname = p.name if src.is_file() else str(p.relative_to(src))
                tar.add(p, arcname=arcname, recursive=False)
        ctx.progress_cb(self.id, 100.0)
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        with tarfile.open(src, "r") as tar:
            tar.extractall(dst, filter="data")
        ctx.progress_cb(self.id, 100.0)
        return dst
