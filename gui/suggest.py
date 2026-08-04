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
from excmp.estimate import DEFAULT_RATES, Rates, compare_profiles
from excmp.planner import Plan, Profile, store_reason
from excmp.tools import ToolInfo

from .format import fmt_eta, fmt_percent, fmt_size
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
    """The best profile this machine can actually run end to end.

    Precomp is the only tool that changes what Extreme *is* - it opens deflate
    streams the other chains must store. SREP no longer counts (B11 removed it
    from every chain), so without Precomp, Extreme would plan the same stages
    as Normal and claiming it as "strongest" would be a lie.
    """
    tools = tools or {}
    if tools.get("precomp") is not None:
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
#   Extreme (precomp -> 7z) wins enormously on repack-style data
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
    heavy_tools = summary.tools.get("precomp", False)

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


# ---------------------------------------------------------------------------
# The profile comparison table (J3)
# ---------------------------------------------------------------------------
# recommend_profile() answers "which one?"; this answers "and what do the others
# cost?". Both are needed: the suggestion is only trustworthy if the user can
# see the trade it made. The estimator supplies the numbers (excmp.estimate);
# everything here is presentation.

PROFILE_LABELS: dict[Profile, str] = {
    Profile.FAST: "Fast",
    Profile.NORMAL: "Normal",
    Profile.EXTREME: "Extreme",
    Profile.INSANE: "Insane",
}

# Short, honest names for the chain column - tool names, not stage ids.
STAGE_LABELS: dict[str, str] = {
    "tar": "tar",
    "zstd": "Zstandard",
    "sevenzip": "7-Zip",
    "precomp": "Precomp",
    "srep": "SREP",
}


def recommend_with_estimates(summary: AnalysisSummary, estimates, cores: int | None = None
                             ) -> tuple[Profile, str]:
    """:func:`recommend_profile` with the measured estimate as a final check.

    The heuristic reasons about *routing*: how many bytes a profile is willing to
    push through the chain. That is the right question until Precomp is involved,
    because Precomp's override routes anything archive-shaped into the pipeline on
    the chance it can expand the streams inside. When it cannot - a .rar payload
    inside a .zip, an .msi - the pipeline fraction looks big while the gain is
    nil, and the heuristic recommends an hour of work for nothing.

    That is not hypothetical: on the recorded 721 MB corpus the heuristic picks
    Extreme, which measured 2.7x Normal's time for 0.17 extra percentage points.
    So the estimate gets the last word, and says why it overruled.

    **But only when the estimate actually knows.** For a Precomp chain the size
    estimate is a conservative ceiling, not a prediction - Precomp may open
    streams the sample probe cannot see. Overruling on that would be the
    estimator acting on an admitted unknown, and it measurably backfires: on a
    163 MB installer corpus Extreme was flagged as a bad trade and then delivered
    41.4% against Normal's 7.3%. Demoting it there would have cost the user 34
    percentage points to save two minutes. So when the flag is conditional the
    recommendation stands and the row carries the caveat instead - visible before
    it is paid for, which is what was asked for, rather than a coin flip made on
    the user's behalf.

    ``recommend_profile`` itself is deliberately left alone - it is the routing
    judgement, still correct on its own terms and still unit-tested as such.
    """
    profile, reason = recommend_profile(summary, cores)
    row = next((e for e in estimates if e.profile is profile), None)
    if row is None or not row.not_worth_it or row.beaten_by is None:
        return profile, reason
    if row.size.upper_bound:
        return profile, reason
    return row.beaten_by, (
        f"{PROFILE_LABELS.get(profile, profile.value)} would push more data through "
        f"the chain here, but samples of your files say it lands within "
        f"{abs(row.extra_points):.1f} points of "
        f"{PROFILE_LABELS.get(row.beaten_by, row.beaten_by.value)} while taking "
        f"{row.time_multiple:.1f}× as long.")


def _span(low: float, high: float, formatter) -> str:
    """'34s – 2 min', or '' when the ends round to the same thing.

    Endpoints lose the '~' that fmt_eta adds - the range already says the number
    is approximate. A collapsed range returns empty rather than repeating the
    value: on a small corpus the first draft printed "about 16.6 MB" with
    "16.6 MB" underneath it, and "a few seconds" twice.
    """
    lo, hi = formatter(low).lstrip("~ "), formatter(high).lstrip("~ ")
    return "" if lo == hi else f"{lo} – {hi}"


def _short_caveat(warnings: list[str]) -> str:
    """A few words for the chain column, not the planner's raw sentence.

    ``planner`` writes for a log: "insane: zpaqfranz backend not integrated yet -
    using extreme chain". Putting that on screen leaks stage vocabulary and an
    ASCII hyphen into the UI, and the preset card already says it in prose. All
    the table needs is enough to explain why two rows show the same chain.
    """
    for warning in warnings:
        if "zpaqfranz" in warning:
            # Keeps the tool name: which backend is missing is exactly the kind
            # of thing this app does not get to be vague about. Short enough
            # for the chain column - the cells clip rather than wrap now.
            return "zpaqfranz missing — runs as Extreme"
    missing = [w.split("tool '")[1].split("'")[0]
               for w in warnings if "tool '" in w and "not installed" in w]
    if missing:
        return f"{', '.join(dict.fromkeys(missing))} missing — stage skipped"
    if any("fell back to zstd" in w for w in warnings):
        return "no tools found — Zstandard only"
    return ""


@dataclass(frozen=True)
class ComparisonRow:
    """One profile's predicted cost, ready to render."""

    profile: Profile
    title: str
    chain: str
    size_text: str
    size_range: str
    saved_text: str
    time_text: str
    time_range: str
    recommended: bool = False
    reason: str = ""      # why it is recommended (from recommend_profile)
    note: str = ""        # the trade-off warning, when a cheaper profile wins
    caveat: str = ""      # missing tools / not-yet-wired backends
    tone: str = ""        # "", "ok", "warn" - always paired with words


def profile_comparison(infos: list[FileInfo], tools: dict[str, ToolInfo | None],
                       summary: AnalysisSummary,
                       cores: int | None = None,
                       rates: Rates = DEFAULT_RATES) -> list[ComparisonRow]:
    """Every profile with its estimated size and time, recommendation marked.

    Reads the recommendation from :func:`recommend_with_estimates` rather than
    deciding again, so the highlighted row and the card badge can never disagree
    - and so the table never recommends a row it has itself flagged.
    """
    if not infos:
        return []

    estimates = compare_profiles(infos, tools, rates)
    recommended, reason = recommend_with_estimates(summary, estimates, cores)
    rows: list[ComparisonRow] = []
    for est in estimates:
        chain = " → ".join(STAGE_LABELS.get(s, s)
                           for s in expected_chain(est.stages)) or "store only"
        is_recommended = est.profile is recommended

        # One sentence, because it is repeated on every flagged row and the panel
        # already carries a caption and a footnote. The "no way to know" caveat
        # lives in the footnote, said once.
        note = ""
        if est.not_worth_it and est.beaten_by is not None:
            beaten = PROFILE_LABELS[est.beaten_by]
            if est.size.upper_bound:
                # The estimate assumed Precomp finds nothing, so the warning is
                # a condition, not a verdict. Saying otherwise would talk people
                # out of the one profile that cracks repack-style data.
                note = (f"Only worth it if Precomp can open these streams — "
                        f"otherwise {beaten} is {est.time_multiple:.1f}× quicker "
                        f"for the same result.")
            else:
                note = (f"{beaten} is {est.time_multiple:.1f}× quicker and lands "
                        f"within {abs(est.extra_points):.1f} points of this.")

        # A Precomp chain's size is a ceiling, not a guess - see
        # excmp.estimate._PRECOMP_OPTIMISTIC. The words have to say which.
        if est.size.upper_bound:
            size_text = f"≤ {fmt_size(est.size.expected)}"
            saved_text = f"{fmt_percent(est.size.saved_fraction)} or better"
        else:
            size_text = f"about {fmt_size(est.size.expected)}"
            saved_text = fmt_percent(est.size.saved_fraction)

        rows.append(ComparisonRow(
            profile=est.profile,
            title=PROFILE_LABELS.get(est.profile, est.profile.value),
            chain=chain,
            size_text=size_text,
            size_range=_span(est.size.low, est.size.high, fmt_size),
            saved_text=saved_text,
            time_text=fmt_eta(est.time.expected),
            time_range=_span(est.time.low, est.time.high, fmt_eta),
            recommended=is_recommended,
            reason=reason if is_recommended else "",
            note=note,
            caveat=_short_caveat(est.warnings),
            tone="ok" if is_recommended else ("warn" if note else ""),
        ))
    return rows


def comparison_caption(rows: list[ComparisonRow]) -> str:
    """The line above the table.

    Points at a flagged row rather than repeating its sentence. Seen on screen,
    the first draft printed the same warning three times in one panel - caption,
    Extreme row, Insane row - which reads as noise and trains people to skip it.
    """
    if not rows:
        return ""
    flagged = [r for r in rows if r.note]
    if not flagged:
        return "Estimates for this input — ranges, not promises."
    names = " and ".join(dict.fromkeys(r.title for r in flagged))
    return f"Estimates for this input. Read the note on {names} before starting."
