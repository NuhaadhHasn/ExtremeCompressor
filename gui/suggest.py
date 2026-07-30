"""What did the user just drop, and what should we suggest they do with it?

This module is pure data + prose: it takes the analyzer's per-file facts and
the planner's routing decision and turns them into the sentences the
analysis card shows. No Qt here, so it is directly testable.

The product promise lives in :func:`gain_note` and :func:`store_explanations`
- every other compressor silently spends your evening achieving 0%, and this
one says so before you start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from excmp.analyzer import Category, FileInfo
from excmp.planner import Plan, Profile, store_reason
from excmp.tools import ToolInfo

from .format import fmt_percent, fmt_size
from .progress import expected_chain

# Plain-English category names. "binary"/"compressed_archive" are engine
# vocabulary; nobody drops a folder thinking "ah yes, my executables".
CATEGORY_LABELS: dict[Category, str] = {
    Category.VIDEO: "video",
    Category.AUDIO: "audio",
    Category.IMAGE: "images",
    Category.COMPRESSED_ARCHIVE: "archives",
    Category.EXECUTABLE: "programs",
    Category.TEXT: "text",
    Category.BINARY: "game/app data",
}

# Above this share of already-compressed bytes, the honest advice is "don't
# bother with the slow profiles".
MOSTLY_INCOMPRESSIBLE = 0.85
# Past this size, Extreme stops being an evening and starts being a weekend
# on a low-core laptop.
BIG_JOB_BYTES = 8 * 1024**3
SMALL_JOB_BYTES = 64 * 1024**2


@dataclass(frozen=True)
class AnalysisSummary:
    """Everything the analysis card, preset cards and results screen need."""

    total_bytes: int
    file_count: int
    by_category: dict[Category, int]
    store_by_category: dict[Category, int]
    store_bytes: int
    pipeline_bytes: int
    store_files: list[tuple[str, int, str]]  # (name, size, why it won't shrink)
    warnings: list[str]
    chain: list[str]
    tools: dict[str, bool] = field(default_factory=dict)
    # Bytes that stay stored even under the strongest chain this machine can
    # run. See summarize() for why this is tracked separately.
    floor_store_bytes: int = 0

    @property
    def store_fraction(self) -> float:
        return self.store_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def pipeline_fraction(self) -> float:
        return self.pipeline_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def floor_store_fraction(self) -> float:
        """Share of bytes that *no* available profile can shrink."""
        return self.floor_store_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def floor_pipeline_fraction(self) -> float:
        return 1.0 - self.floor_store_fraction

    def ranked_categories(self) -> list[tuple[Category, int]]:
        return sorted(self.by_category.items(), key=lambda kv: kv[1], reverse=True)


def strongest_profile(tools: dict[str, ToolInfo | None] | None) -> Profile:
    """The best profile this machine can actually run end to end."""
    tools = tools or {}
    if tools.get("precomp") is not None or tools.get("srep") is not None:
        return Profile.EXTREME
    return Profile.NORMAL if tools.get("7z") is not None else Profile.FAST


def summarize(infos: list[FileInfo], the_plan: Plan,
              tools: dict[str, ToolInfo | None] | None = None,
              reference_plan: Plan | None = None) -> AnalysisSummary:
    """Fold analyzer output + a routing plan into one summary object.

    ``the_plan`` describes what will happen with the *currently selected*
    profile - that is what the analysis card reports.

    ``reference_plan`` is the same files routed through the strongest chain
    available. Without it the suggestion would be circular: Normal has no
    Precomp, so a folder of zlib-wrapped game paks looks 86% incompressible,
    and the app would recommend Fast - talking the user out of the very
    profile that shrinks those paks by 70%. The recommendation reads the
    reference plan; everything else reads the real one.
    """
    by_category: dict[Category, int] = {}
    for info in infos:
        by_category[info.category] = by_category.get(info.category, 0) + info.size

    stored: set[Path] = set()
    for route in the_plan.routes:
        if route.action == "store":
            stored.update(route.files)

    store_by_category: dict[Category, int] = {}
    for info in infos:
        if info.path in stored:
            store_by_category[info.category] = (
                store_by_category.get(info.category, 0) + info.size)

    store_bytes = sum(i.size for i in infos if i.path in stored)
    store_files = [
        (i.path.name, i.size, store_reason(i) or "stored")
        for i in sorted((i for i in infos if i.path in stored),
                        key=lambda i: i.size, reverse=True)
    ]
    total = sum(i.size for i in infos)
    pipeline_stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])

    if reference_plan is None:
        floor_store_bytes = store_bytes
    else:
        floor: set[Path] = set()
        for route in reference_plan.routes:
            if route.action == "store":
                floor.update(route.files)
        floor_store_bytes = sum(i.size for i in infos if i.path in floor)

    return AnalysisSummary(
        total_bytes=total,
        file_count=len(infos),
        by_category=by_category,
        store_by_category=store_by_category,
        store_bytes=store_bytes,
        pipeline_bytes=total - store_bytes,
        store_files=store_files,
        warnings=list(the_plan.warnings),
        chain=expected_chain(list(pipeline_stages)),
        tools={name: info is not None for name, info in (tools or {}).items()},
        floor_store_bytes=floor_store_bytes,
    )


def headline(summary: AnalysisSummary) -> str:
    """'3.2 GB across 412 files — 82% video, 12% game/app data, 6% text'."""
    if not summary.file_count:
        return "Nothing to analyze yet."
    parts = []
    for category, size in summary.ranked_categories()[:3]:
        share = size / summary.total_bytes if summary.total_bytes else 0
        if share >= 0.01:
            parts.append(f"{fmt_percent(share)} {CATEGORY_LABELS.get(category, str(category))}")
    files = "file" if summary.file_count == 1 else "files"
    breakdown = " · ".join(parts)
    return (f"{fmt_size(summary.total_bytes)} across {summary.file_count} {files}"
            + (f" — {breakdown}" if breakdown else ""))


def gain_note(summary: AnalysisSummary) -> str:
    """The honest one-liner about what lossless compression can achieve."""
    if not summary.file_count:
        return ""
    frac = summary.store_fraction
    if frac >= 0.99:
        return ("Every byte here is already compressed — lossless gain is ~0%. "
                "The archive will be about the same size as the input.")
    if frac >= MOSTLY_INCOMPRESSIBLE:
        return (f"{fmt_percent(frac)} of this is already compressed and will be stored "
                f"bit-exact; only {fmt_size(summary.pipeline_bytes)} can actually shrink.")
    if frac >= 0.2:
        return (f"{fmt_size(summary.pipeline_bytes)} can shrink; the other "
                f"{fmt_size(summary.store_bytes)} is already compressed and gets "
                "stored losslessly.")
    return f"Nearly all of this ({fmt_size(summary.pipeline_bytes)}) is worth compressing."


def shrink_mode_hint(summary: AnalysisSummary) -> str | None:
    """Suggest the (not-yet-built) re-encode mode only when it would matter."""
    media = sum(summary.by_category.get(c, 0)
                for c in (Category.VIDEO, Category.AUDIO))
    if summary.total_bytes and media / summary.total_bytes >= 0.4:
        return (f"{fmt_percent(media / summary.total_bytes)} of this is video/audio. "
                "Only re-encoding makes that smaller — Shrink mode is coming in a "
                "later release, and it will always be opt-in.")
    return None


def store_explanations(summary: AnalysisSummary, limit: int = 6) -> list[tuple[str, str]]:
    """(file name, why it didn't shrink) for the results screen, biggest first."""
    return [(name, reason) for name, _size, reason in summary.store_files[:limit]]


# ---------------------------------------------------------------------------
# The suggestion heuristic
# ---------------------------------------------------------------------------
# This is the judgement call that decides whether the app respects the user's
# evening. It is intentionally small, explicit and in one place so it can be
# tuned against real runs on the machine it ships to. The trade-off it
# balances:
#
#   Extreme (precomp -> srep -> 7z) wins enormously on repack-style data
#   - 72% on the benchmark corpus - but it is single-digit MB/s on two cores
#   and can inflate temp space 2-5x mid-pipeline.
#
#   When most bytes are already-compressed media, *every* profile returns
#   ~0%, so the fastest one is the only honest recommendation: the user gets
#   the same archive in minutes instead of hours.
#
# Tune the three constants above (MOSTLY_INCOMPRESSIBLE, BIG_JOB_BYTES,
# SMALL_JOB_BYTES) rather than rewriting the branches.

def recommend_profile(summary: AnalysisSummary, cores: int | None = None) -> tuple[Profile, str]:
    """Pick the preset to pre-select, plus the reason shown on its card.

    Reads ``floor_store_fraction``, never ``store_fraction``: the question is
    what this data *can* do under the best chain, not what the currently
    selected profile happens to manage.
    """
    cores = cores or os.cpu_count() or 2
    heavy_tools = summary.tools.get("precomp", False) or summary.tools.get("srep", False)

    if summary.floor_store_fraction >= MOSTLY_INCOMPRESSIBLE:
        return Profile.FAST, (
            "Almost all of this is already compressed — the slow profiles would "
            "spend hours to save the same ~0%.")

    if summary.total_bytes <= SMALL_JOB_BYTES:
        return Profile.EXTREME, (
            "Small enough that the full chain costs seconds, so take the best ratio.")

    if summary.total_bytes >= BIG_JOB_BYTES and cores <= 4:
        return Profile.NORMAL, (
            f"{fmt_size(summary.total_bytes)} on {cores} cores — Extreme would run for "
            "hours here. Normal gets most of the win quickly.")

    if heavy_tools and summary.floor_pipeline_fraction >= 0.3:
        return Profile.EXTREME, (
            "Lots of compressible data and the repack tools are installed — this is "
            "exactly what the full chain is for.")

    return Profile.NORMAL, "A solid ratio without the long wait."
