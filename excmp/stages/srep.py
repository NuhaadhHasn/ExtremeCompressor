"""SREP stage: long-range deduplication over a single file.

``-m3f`` = future-LZ matching, good ratio at moderate RAM; ``-d`` restores.
SREP is closed freeware - it is detected on the machine, never bundled.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..tools import find_tools, require
from .base import Stage, StageContext, StageError, run_tool

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")


def _parse_percent(line: str) -> float | None:
    m = _PCT.search(line)
    return float(m.group(1)) if m else None


class SrepStage(Stage):
    id = "srep"
    tool_name = "srep"

    def _exe(self) -> str:
        return require(find_tools(), "srep").path

    def available(self) -> bool:
        return find_tools()["srep"] is not None

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        if dst.exists():
            dst.unlink()
        run_tool([self._exe(), "-m3f", str(src), str(dst)], ctx, self.id,
                 _parse_percent, cwd=ctx.temp_dir)
        if not dst.exists():
            raise StageError(f"{self.id}: output not created")
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        out = dst / (src.stem if src.suffix == ".srep" else src.name + ".restored")
        run_tool([self._exe(), "-d", str(src), str(out)], ctx, self.id,
                 _parse_percent, cwd=ctx.temp_dir)
        if not out.exists():
            raise StageError(f"{self.id}: restore produced no output")
        return out
