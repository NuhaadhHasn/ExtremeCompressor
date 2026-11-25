"""Stage framework: every pipeline step implements the same tiny contract.

A stage transforms one path into another in each direction:
``compress(src, dst, ctx)`` and ``extract(src, dst, ctx)``. Stages report
progress through ``ctx.progress_cb(stage_id, percent)`` and honor
``ctx.cancel`` cooperatively (the running tool is killed).

``ctx.pause`` is checked by the *engine* at stage boundaries, not inside
stages: holding mid-stage would mean either leaving a tool suspended or
throwing away its work, so "pause" means "finish this stage, then wait".
"""

from __future__ import annotations

import subprocess
import time
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


class QuietSkip(StageSkip):
    """A skip that is not news. An opportunistic stage (dedup) steps aside on
    most jobs, and a note about it on every archive would be noise: the
    engine logs this one and adds nothing to the job's warnings."""


@dataclass
class StageContext:
    temp_dir: Path
    threads: int = 0  # 0 = tool default / all cores
    #: G7. Decoder threads on **extraction**, 0 = tool default.
    #:
    #: Separate from `threads` on purpose: that one sizes the *compressor*,
    #: and the two have opposite defaults. Compression wants every core; an
    #: extraction that has to fit a memory budget wants exactly one, because
    #: each LZMA2 decoder thread holds its own dictionary buffer.
    #:
    #: Measured 2026-09-11 (Silesia, `-md=64m`, peak working set): **255 MiB
    #: with no switch, 71 MiB at `-mmt=1`** - 3.6x - while `-mmt=2` and
    #: `-mmt=4` both stayed at 255 MiB. It lives on the context rather than in
    #: a parameter because the chain drives stages through the generic
    #: `Stage.extract(src, dst, ctx)`, so a new argument would have to be
    #: added to every stage that cannot use it.
    extract_threads: int = 0
    #: The most bytes the stage now being **extracted** may produce, or 0 for
    #: "not told". The engine checks every stage's output against this after
    #: it finishes; a stage whose input declares its output size (dedup) can
    #: refuse before writing a byte instead.
    output_limit: int = 0
    progress_cb: Callable[[str, float], None] = lambda stage, pct: None
    log_cb: Callable[[str, str], None] = lambda stage, line: None
    cancel: threading.Event = field(default_factory=threading.Event)
    pause: threading.Event = field(default_factory=threading.Event)  # set = hold

    def __post_init__(self) -> None:
        # Absolute: stages hand this to subprocesses as their working
        # directory, and a relative path would follow the caller around.
        self.temp_dir = Path(self.temp_dir).absolute()
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
        # Nothing here is ever interactive, and a tool that decides to ask a
        # question must get an immediate EOF rather than a handle it can wait
        # on forever. Measured on 7-Zip 24.07: `7z x` on an encrypted archive
        # with stdin held open was still running after 8 seconds, invisibly,
        # because CREATE_NO_WINDOW means the prompt has nowhere to appear.
        # (The 7-Zip-specific half of that fix is the dummy `-p` in
        # sevenzip.py; this is the belt to its braces, and it covers every
        # other tool we shell out to.)
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        bufsize=1,
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    # K6: a watcher thread owns cancellation, not the read loop. The loop only
    # runs when the tool prints, and zpaqfranz prints *nothing* for the whole
    # of a restore (measured: header by 0.3 s, then silence until the summary
    # 151 s later, -verbose included). At -m58 that silence is ~25 minutes on
    # a Silesia-sized job, and Cancel and window-close waited for all of it.
    # Killing the child closes its pipe, so the read below sees EOF at once.
    finished = threading.Event()

    def _watch_for_cancel() -> None:
        while not finished.is_set():
            if ctx.cancel.wait(0.25):
                try:
                    proc.kill()
                except OSError:
                    pass
                return

    watcher = threading.Thread(target=_watch_for_cancel, daemon=True)
    watcher.start()
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
            ctx.log_cb(stage_id, line)
            if parse_line is not None:
                pct = parse_line(line)
                if pct is not None:
                    ctx.progress_cb(stage_id, max(0.0, min(100.0, pct)))
    finally:
        finished.set()
        proc.stdout.close()
    code = proc.wait()
    if ctx.cancel.is_set():
        # Checked before the exit code: a killed tool exits non-zero, and
        # "exited with code 1" would tell the user it failed when they
        # stopped it.
        raise StageError(f"{stage_id}: cancelled")
    if code != 0:
        raise StageError(
            f"{stage_id}: '{cmd[0]}' exited with code {code}\n" + "\n".join(tail[-15:])
        )
    ctx.progress_cb(stage_id, 100.0)


@dataclass
class Capture:
    """What a tool said, plus whether we let it finish."""

    code: int
    lines: list[str]
    #: We stopped reading at ``max_lines``. ``code`` is then meaningless -
    #: the tool was killed mid-sentence - and any list built from ``lines``
    #: is a prefix, which the surface above has to admit to.
    truncated: bool = False
    #: The tool outlived ``timeout_s``. Also meaningless ``code``.
    timed_out: bool = False


def run_capture(
    cmd: list[str],
    ctx: StageContext,
    max_lines: int,
    timeout_s: float,
    encoding: str = "utf-8",
) -> Capture:
    """Run a tool and **return** what happened, rather than raising on it.

    :func:`run_tool` is right for a stage, where a non-zero exit is simply a
    failure. Listing is different: a non-zero exit is the *answer* about half
    the time ("this archive is encrypted") and has to be classified, not
    thrown. Hence a second entry point rather than a flag on the first.

    Three bounds, because this one runs against arbitrary user files:
    ``max_lines`` (a huge archive's listing is unbounded), ``timeout_s`` (a
    tool that blocks anyway must not take the app with it), and the inherited
    ``ctx.cancel``. ``encoding`` is explicit because 7-Zip's ``-scc`` switch
    lets us *choose* the console charset, and the default locale codec would
    mangle every non-ASCII filename.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding=encoding,
        errors="replace",
        bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )
    lines: list[str] = []
    truncated = False
    expired = threading.Event()

    def _expire() -> None:
        # The deadline cannot be enforced inside the read loop: a tool that
        # blocks *without printing anything* - which is exactly what a
        # password prompt does - never returns from `for line in stdout`, so
        # a check at the top of the loop body is never reached. Killing from
        # a timer closes the pipe, the read gets EOF, and the loop ends.
        expired.set()
        proc.kill()

    watchdog = threading.Timer(timeout_s, _expire)
    watchdog.daemon = True
    watchdog.start()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            lines.append(line.rstrip("\r\n"))
            if len(lines) >= max_lines:
                truncated = True
                break
            if ctx.cancel.is_set():
                break
    finally:
        watchdog.cancel()
        proc.stdout.close()

    if truncated or expired.is_set() or ctx.cancel.is_set():
        proc.kill()
        proc.wait()
        return Capture(code=-1, lines=lines, truncated=truncated,
                       timed_out=expired.is_set())
    return Capture(code=proc.wait(), lines=lines)
