"""Stage framework: every pipeline step implements the same tiny contract.

A stage transforms one path into another in each direction:
``compress(src, dst, ctx)`` and ``extract(src, dst, ctx)``. Stages report
progress through ``ctx.progress_cb(stage_id, percent)`` and honor
``ctx.cancel`` cooperatively (the running tool is killed).
"""

from __future__ import annotations

import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

CREATE_NO_WINDOW = 0x08000000  # keep console tools invisible under a GUI


class StageError(RuntimeError):
    """A stage failed; message carries the tool's captured output tail."""


class StageSkip(Exception):
    """A stage found nothing it can improve; the engine passes the data
    through unchanged and leaves the stage out of the manifest."""


@dataclass
class StageContext:
    temp_dir: Path
    threads: int = 0  # 0 = tool default / all cores
    progress_cb: Callable[[str, float], None] = lambda stage, pct: None
    cancel: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.temp_dir = Path(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


class Stage(ABC):
    id: str = "stage"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path: ...

    @abstractmethod
    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path: ...


def run_tool(
    cmd: list[str],
    ctx: StageContext,
    stage_id: str,
    parse_line: Optional[Callable[[str], Optional[float]]] = None,
    cwd: Optional[Path] = None,
) -> None:
    """Run a CLI tool, pumping merged stdout/stderr lines through
    ``parse_line`` (which may return a progress percentage). Raises
    :class:`StageError` on non-zero exit or cancellation."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if ctx.cancel.is_set():
                proc.kill()
                proc.wait()
                raise StageError(f"{stage_id}: cancelled")
            line = line.rstrip("\n")
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
            if parse_line is not None:
                pct = parse_line(line)
                if pct is not None:
                    ctx.progress_cb(stage_id, max(0.0, min(100.0, pct)))
    finally:
        proc.stdout.close()
    code = proc.wait()
    if code != 0:
        raise StageError(
            f"{stage_id}: '{cmd[0]}' exited with code {code}\n" + "\n".join(tail[-15:])
        )
    ctx.progress_cb(stage_id, 100.0)
