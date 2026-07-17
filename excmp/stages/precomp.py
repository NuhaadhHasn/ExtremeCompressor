"""Precomp stage: expands zlib/deflate/jpeg streams inside the payload so
later stages can recompress them harder. Input and output are single files.

Precomp writes its recursion metadata into the .pcf, so ``-r`` restores the
original bit-exactly. The output is usually LARGER than the input - that is
the point: it trades size now for a better final ratio.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..tools import find_tools, require
from .base import Stage, StageContext, StageError, StageSkip, run_tool

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
_NO_GAIN = "There will be no gain"


def _parse_percent(line: str) -> float | None:
    m = _PCT.search(line)
    return float(m.group(1)) if m else None


class PrecompStage(Stage):
    id = "precomp"
    tool_name = "precomp"

    def __init__(self, intense: bool = True):
        # -intense also finds raw zlib streams (game paks); costs time, which
        # is exactly what the Extreme/Insane profiles trade for ratio.
        self.intense = intense

    def _exe(self) -> str:
        return require(find_tools(), "precomp").path

    def available(self) -> bool:
        return find_tools()["precomp"] is not None

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        if dst.exists():
            dst.unlink()
        # -cn = no internal compression (later stages do that job better)
        cmd = [self._exe(), "-cn"]
        if self.intense:
            cmd.append("-intense")
        cmd += [f"-o{dst}", str(src)]
        try:
            run_tool(cmd, ctx, self.id, _parse_percent)
        except StageError as exc:
            if _NO_GAIN in str(exc):
                raise StageSkip(f"{self.id}: no recompressible streams found") from exc
            raise
        if not dst.exists():
            raise StageError(f"{self.id}: output not created")
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        out = dst / (src.stem if src.suffix == ".pcf" else src.name + ".restored")
        run_tool([self._exe(), "-r", f"-o{out}", str(src)], ctx, self.id, _parse_percent)
        if not out.exists():
            raise StageError(f"{self.id}: restore produced no output")
        return out
