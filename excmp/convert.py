"""G5 — convert somebody else's archive into ours, and say whether it helped.

Point this at a `.zip`, `.rar`, `.7z`, `.iso` or anything else 7-Zip can open.
It extracts to temp, analyses what was actually inside, runs the normal
pipeline, and reports the comparison.

Recompressing archives is not a new idea. The part that is ours is the last
step: :mod:`excmp.planner` already knows *why* each file was stored or piped,
so a conversion that gained nothing can explain itself in a sentence instead
of leaving the user to compare two numbers and guess. "Your archive is already
mostly JPEGs, and JPEGs do not compress twice" is a better answer than
"1,041,203 → 1,038,881".

Three rules:

**The source archive is never touched.** Not moved, not deleted, not on
success. Deleting the only copy of somebody's data because ours came out
smaller is not a decision this program gets to make; if they want the space
back they can delete it themselves, having seen the number.

**A conversion that does not help says so.** Loudly enough to act on. A tool
that answers "done!" to a job that achieved nothing is teaching its user to
stop reading it.

**Nothing is published that does not verify.** This routes through
:func:`excmp.engine.compress`, so the D9 gate applies unchanged: the new
archive is fully restored and hashed before it is renamed into place.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import analyze_tree
from .planner import Profile, plan as make_plan, store_reason
from .tempclean import rmtree_force
from .stages.base import StageContext, StageError
from .stages.sevenzip import SevenZipStage
from .tools import ToolInfo, find_tools

#: Below this, a difference is noise rather than a result - archive framing and
#: manifest overhead alone move a small archive by more than this.
MEANINGFUL_GAIN = 0.01


@dataclass
class ConvertResult:
    """What the conversion produced, and whether it was worth doing."""

    archive: Path
    source: Path
    source_bytes: int
    archive_bytes: int
    files: int
    elapsed_s: float
    #: True only when the new archive is *meaningfully* smaller.
    improved: bool
    #: One sentence a person can act on.
    verdict: str
    #: Per-file "why this did not shrink", straight from the planner. The
    #: thing no other converter can print.
    reasons: list[str] = field(default_factory=list)


def convert_archive(source: Path, out_path: Path, profile: Profile,
                    ctx: StageContext,
                    tools: dict[str, ToolInfo | None] | None = None,
                    password: str | None = None) -> ConvertResult:
    """Extract ``source``, recompress it as an ``.excmp``, and report.

    ``password`` is for the *source* archive if it is encrypted - not for the
    output. Protecting the result is a separate decision and takes a separate
    trip through :func:`excmp.engine.compress`.
    """
    import time

    from .engine import compress

    source, out_path = Path(source), Path(out_path)
    if not source.exists():
        raise StageError(f"{source} does not exist")
    tools = tools if tools is not None else find_tools(with_versions=True)

    t0 = time.monotonic()
    source_bytes = source.stat().st_size
    work = Path(tempfile.mkdtemp(prefix="excmp-conv-", dir=ctx.temp_dir))
    try:
        staged = work / "unpacked"
        staged.mkdir(parents=True, exist_ok=True)
        try:
            SevenZipStage().extract(source, staged, ctx, password=password)
        except StageError as exc:
            raise StageError(
                f"{source.name} could not be opened as an archive: {exc}"
            ) from exc

        files = [p for p in staged.rglob("*") if p.is_file()]
        if not files:
            raise StageError(
                f"{source.name} contains no files - there is nothing to "
                f"convert, and writing an empty archive would only look like "
                f"success")

        # Analyse the *contents*, which is the whole point: the source archive
        # is one opaque blob, and what matters is what is inside it.
        infos = analyze_tree(staged)
        the_plan = make_plan(infos, profile, tools)
        reasons = _explain(infos)

        result = compress([staged], out_path, profile, ctx, tools)
        archive_bytes = result.final_bytes
    finally:
        # The staging copy is the size of their whole archive. Leaving it
        # behind would quietly cost the user that space twice.
        rmtree_force(work)

    gain = (source_bytes - archive_bytes) / source_bytes if source_bytes else 0.0
    improved = gain > MEANINGFUL_GAIN
    return ConvertResult(
        archive=out_path,
        source=source,
        source_bytes=source_bytes,
        archive_bytes=archive_bytes,
        files=len(files),
        elapsed_s=time.monotonic() - t0,
        improved=improved,
        verdict=_verdict(source, source_bytes, archive_bytes, gain, improved,
                         reasons),
        reasons=reasons,
    )


def _explain(infos) -> list[str]:
    """The planner's per-file reasons, deduplicated and counted.

    Collapsed by reason rather than listed per file: "31 files: already
    compressed" is what somebody reads, and thirty-one identical lines is what
    they scroll past.
    """
    tally: dict[str, int] = {}
    for info in infos:
        why = store_reason(info)
        if why:
            tally[why] = tally.get(why, 0) + 1
    return [f"{count} file(s): {why}"
            for why, count in sorted(tally.items(), key=lambda kv: -kv[1])]


def _verdict(source: Path, before: int, after: int, gain: float,
             improved: bool, reasons: list[str]) -> str:
    if improved:
        return (f"{source.name} was {_mb(before)}; the converted archive is "
                f"{_mb(after)} - {gain * 100:.1f}% smaller.")
    if after >= before:
        head = (f"{source.name} was {_mb(before)} and the converted archive is "
                f"{_mb(after)} - no smaller, so keep the original.")
    else:
        head = (f"{source.name} was {_mb(before)} and the converted archive is "
                f"{_mb(after)} - only {gain * 100:.1f}% smaller, which is not "
                f"worth keeping a second copy for.")
    if reasons:
        head += " " + reasons[0].split(": ", 1)[-1].split(";")[0].strip() + "."
    return head


def _mb(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    return f"{n / 1024:.0f} KB"
