"""7-Zip LZMA2 stage — the workhorse of the Normal/Extreme profiles."""

from __future__ import annotations

import re
from pathlib import Path

from ..tools import find_tools, require
from .base import Stage, StageContext, StageError, run_tool

_PCT = re.compile(r"^\s*(\d{1,3})%")


def _parse_percent(line: str) -> float | None:
    m = _PCT.match(line)
    return float(m.group(1)) if m else None


class SevenZipStage(Stage):
    id = "sevenzip"

    def __init__(self, level: int = 9, dict_size: str | None = None):
        self.level = level
        self.dict_size = dict_size  # e.g. "192m"; None = 7z default for level

    def _exe(self) -> str:
        return require(find_tools(), "7z").path

    def available(self) -> bool:
        return find_tools()["7z"] is not None

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        if dst.exists():
            dst.unlink()
        cmd = [self._exe(), "a", "-t7z", f"-mx{self.level}", "-bsp1", "-y"]
        if self.dict_size:
            cmd.append(f"-md={self.dict_size}")
        if ctx.threads:
            cmd.append(f"-mmt{ctx.threads}")
        # For a directory, archive its *contents* (src\*) so extraction
        # recreates the tree without an extra wrapping folder.
        target = str(src / "*") if src.is_dir() else str(src)
        cmd += [str(dst), target]
        run_tool(cmd, ctx, self.id, _parse_percent)
        if not dst.exists():
            raise StageError(f"{self.id}: archive was not created")
        return dst

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        cmd = [self._exe(), "x", "-bsp1", "-y", f"-o{dst}", str(src)]
        run_tool(cmd, ctx, self.id, _parse_percent)
        return dst

    def test(self, archive: Path, ctx: StageContext) -> None:
        run_tool([self._exe(), "t", "-bsp1", "-y", str(archive)], ctx, self.id, _parse_percent)
