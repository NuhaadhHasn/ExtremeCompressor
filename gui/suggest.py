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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from excmp.analyzer import Category, FileInfo
from excmp.estimate import (DEFAULT_RATES, Rates, compare_profiles, estimate_time,
                            pack_cost, packable, recode_cost, recoded_seconds)
from excmp.planner import (_PRECOMP_MEDIA, Plan, Profile, _probe_pipes,
                           precomp_inflation, store_reason)
from excmp.planner import plan as make_plan
from excmp.sample import MeasuredRun, Sample
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
    #: B21b: of the bytes the strongest chain pipes, those only the probe
    #: rule sends (video, M4A, Ogg; not MP3, which packMP3 recodes). Every
    #: profile gets the same few percent from them, so they are not a reason
    #: for Extreme.
    floor_probe_bytes: int = 0
    #: B23: bytes THIS job's plan pipes only because the probe flagged them
    #: (video, M4A, Ogg; not what Precomp recodes). Calibration leaves a job
    #: made mostly of these out, as it does one made of recoded media.
    probe_piped_bytes: int = 0
    #: B13: Ogg audio balrogg will pack, and what packing it costs. They sit
    #: inside ``store_bytes`` (the files take the store route) but they are
    #: slow, so the bar and the time estimate have to know. B19: JPEGs lepton
    #: will pack count here too; ``pack_jpeg_bytes`` is their share.
    pack_bytes: int = 0
    pack_seconds: float = 0.0
    pack_verify_seconds: float = 0.0
    pack_jpeg_bytes: int = 0
    #: B19: what Precomp's own MP3/JPEG recoders add beyond the chain's rate,
    #: so the bar's split agrees with the table (`estimate.recode_cost`).
    recode_seconds: float = 0.0
    recode_verify_seconds: float = 0.0
    recode_bytes: int = 0
    #: B22: the part of ``recode_bytes`` Insane prices at its own measured
    #: rates; the bar needs it to take them out of the chain's term.
    recode_own_bytes: int = 0
    #: Under the strongest available chain, which the recommendation reasons
    #: about: the whole job's expected seconds (it says whether "seconds" is
    #: true), and the recoded files' share of them (compress and self-test,
    #: the chain's share included: `estimate.recoded_seconds`), which says
    #: whether Precomp's recoders are why.
    strongest_seconds: float = 0.0
    strongest_recode_seconds: float = 0.0
    #: Files the time estimate charges per file (`estimate.per_file_seconds`):
    #: all of them but those a store-route specialist packs.
    per_file_count: int = 0

    @property
    def store_fraction(self) -> float:
        return self.store_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def fixed_fraction(self) -> float:
        """Share stored exactly as it is: the store route minus what a
        specialist repacks there. What the note calls "already compressed"."""
        fixed = self.store_bytes - self.pack_bytes
        return fixed / self.total_bytes if self.total_bytes else 0.0

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

    # B13: Ogg audio balrogg repacks takes the store route but is not "stored
    # as-is" and did not fail to shrink. It stays in `store_bytes` (the route,
    # which the time arithmetic reads) and is left out of everything that
    # tells the user what cannot shrink. B19: so are the JPEGs lepton packs.
    packed_infos = packable(infos, the_plan)
    repacked = {i.path for i in packed_infos}
    # ...but not out of the *floor*, which only the recommendation reads: the
    # bytes no profile does better on than another. balrogg's effort rises
    # with the profile (B13), so Ogg leaves it; lepton packs a JPEG the same
    # way under every profile, so a photo folder must not look like a reason
    # for Extreme. (Rendering caught it: all four rows read the same size and
    # time, and Extreme was suggested on 3x Fast's RAM.)
    profile_sensitive = {i.path for i in packed_infos if not i.is_jpeg}

    store_by_category: dict[Category, int] = {}
    for info in infos:
        if info.path in stored and info.path not in repacked:
            store_by_category[info.category] = (
                store_by_category.get(info.category, 0) + info.size)

    store_bytes = sum(i.size for i in infos if i.path in stored)
    store_files = [
        (i.path.name, i.size, store_reason(i) or "stored")
        for i in sorted((i for i in infos
                         if i.path in stored and i.path not in repacked),
                        key=lambda i: i.size, reverse=True)
    ]
    total = sum(i.size for i in infos)
    pipeline_stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])

    if reference_plan is None:
        floor_store_bytes = store_bytes - sum(i.size for i in infos
                                              if i.path in profile_sensitive)
    else:
        floor: set[Path] = set()
        for route in reference_plan.routes:
            if route.action == "store":
                floor.update(route.files)
        floor -= {i.path for i in packable(infos, reference_plan) if not i.is_jpeg}
        floor_store_bytes = sum(i.size for i in infos if i.path in floor)

    cost = pack_cost(infos, the_plan)
    recode = recode_cost(infos, the_plan)
    strongest_plan = the_plan if reference_plan is None else reference_plan
    strongest_stages = next((r.stages for r in strongest_plan.routes
                             if r.action == "pipeline"), [])
    strongest = recoded_seconds(recode_cost(infos, strongest_plan), strongest_stages)
    # B21b: piped under the strongest chain only because the probe flagged it,
    # in a format Precomp has no recoder for (video, M4A, Ogg; MP3 has
    # packMP3). The chain gets the same few percent out of it at any profile.
    strongest_piped = {f for r in strongest_plan.routes if r.action == "pipeline"
                       for f in r.files}
    # An MP3 is packMP3's only where the chain has Precomp (review).
    recoded = _PRECOMP_MEDIA if "precomp" in strongest_stages else set()
    floor_probe_bytes = sum(
        i.size for i in infos if i.path in strongest_piped and _probe_pipes(i)
        and i.path.suffix.lower() not in recoded)
    # B23: the same under THIS job's own plan, for calibration: Precomp passes
    # such files straight through, which is the chain's no-op regime and not
    # its rate (one MKV job taught Extreme 3.1 MB/s against 1.41).
    job_piped = {f for r in the_plan.routes if r.action == "pipeline" for f in r.files}
    job_recoded = _PRECOMP_MEDIA if "precomp" in pipeline_stages else set()
    probe_piped_bytes = sum(
        i.size for i in infos if i.path in job_piped and _probe_pipes(i)
        and i.path.suffix.lower() not in job_recoded)
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
        floor_probe_bytes=floor_probe_bytes,
        probe_piped_bytes=probe_piped_bytes,
        pack_bytes=cost.bytes,
        pack_seconds=cost.seconds,
        pack_verify_seconds=cost.verify_seconds,
        pack_jpeg_bytes=cost.jpeg_bytes,
        recode_seconds=recode.compress_seconds,
        recode_verify_seconds=recode.verify_seconds,
        recode_bytes=recode.bytes,
        recode_own_bytes=recode.own_bytes,
        strongest_seconds=estimate_time(infos, strongest_plan).expected,
        strongest_recode_seconds=sum(strongest),
        per_file_count=len(infos) - cost.files,
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
    # B13: Ogg audio sits on the store route but is repacked, so it is neither
    # "stored bit-exact" nor "can't shrink". It counts with what can shrink,
    # and the note says what happens to it.
    packed = summary.pack_bytes
    shrinkable = summary.pipeline_bytes + packed
    fixed = summary.store_bytes - packed
    frac = summary.fixed_fraction
    ogg = packed - summary.pack_jpeg_bytes
    suffix = (f" Ogg audio ({fmt_size(ogg)}) is repacked losslessly, "
              "typically 4–15% smaller." if ogg else "")
    # B19: measured 21.4% (web images), 22.3% (phone photos) and 33.4% (the
    # design files lepton took), every file restored.
    if summary.pack_jpeg_bytes:
        suffix += (f" JPEG photos ({fmt_size(summary.pack_jpeg_bytes)}) are "
                   "repacked losslessly, typically 21–33% smaller.")
    if frac >= 0.99:
        # B21 (review): what this profile stores is not what the bytes are. A
        # stronger profile opens PNG, GIF, EPUB and the JPEGs lepton refuses,
        # so "already compressed, ~0%" was false beside its own Extreme row.
        unlocked = summary.store_bytes - summary.floor_store_bytes
        if unlocked >= 0.01 * summary.total_bytes:
            return ("Everything here is stored as-is on this profile — lossless "
                    f"gain is ~0%. A stronger profile can shrink {fmt_size(unlocked)} "
                    "of it losslessly.")
        return ("Every byte here is already compressed — lossless gain is ~0%. "
                "The archive will be about the same size as the input.")
    if frac >= MOSTLY_INCOMPRESSIBLE:
        return (f"{fmt_percent(frac)} of this is already compressed and will be stored "
                f"bit-exact; only {fmt_size(shrinkable)} can actually shrink." + suffix)
    if frac >= 0.2:
        return (f"{fmt_size(shrinkable)} can shrink; the other "
                f"{fmt_size(fixed)} is already compressed and gets "
                "stored losslessly." + suffix)
    if shrinkable and summary.floor_probe_bytes >= 0.9 * shrinkable:
        # B21b: piped because its probe flags it, which is a few percent
        # (MKV 3.7%, MP4 3.8-9.2%), not "worth compressing" beside a table
        # that says 3%. Only when that is nearly all of it (review: 60 MB of
        # MKV beside 40 MB of text was told "no more").
        return (f"Mostly compressed video/audio ({fmt_size(shrinkable)}): "
                "recompressing it saves a few percent, no more." + suffix)
    return (f"Nearly all of this ({fmt_size(shrinkable)}) is worth compressing."
            + suffix)


def shrink_mode_hint(summary: AnalysisSummary) -> str | None:
    """Suggest the (not-yet-built) re-encode mode only when it would matter."""
    # Only media that is stored as-is: `store_by_category` already leaves out
    # the audio balrogg repacks (B13), and media the probe flags is piped and
    # shrinks losslessly (B13a's Ogg, B18's MP3/MP4), so it is not on the
    # store route at all.
    media = sum(summary.store_by_category.get(c, 0)
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

def _mostly_settled_reason(summary: AnalysisSummary) -> str:
    """Why Fast, when almost nothing does better under a slower profile.

    B19 review: lepton packs stored JPEGs ~21-33% smaller under every profile
    alike, so they sit in the floor, and "the same ~0%" is only true when
    there are none. Nor is "the same archive" true when part of the input
    (CMYK JPEGs, say) does shrink further under Precomp: name that part.
    """
    if not summary.pack_jpeg_bytes:
        return ("Almost all of this is already compressed — the slow profiles would "
                "spend hours to save the same ~0%.")
    photos = summary.pack_jpeg_bytes / summary.total_bytes if summary.total_bytes else 0.0
    lead = ("Mostly JPEG photos, which every profile packs the same way"
            if photos >= 0.5 else
            "Almost all of this is already compressed, or JPEG photos every "
            "profile packs the same way")
    rest = summary.floor_pipeline_fraction
    if rest < 0.005:
        return lead + " — Fast makes the same archive quickest."
    return lead + (f" — a slower profile could only gain on the other "
                   f"{fmt_percent(rest)}.")


def recommend_profile(summary: AnalysisSummary, cores: int | None = None) -> tuple[Profile, str]:
    """Pick the preset to pre-select, plus the reason shown on its card.

    Reads ``floor_store_fraction``, never ``store_fraction``: the question is
    what this data *can* do under the best chain, not what the currently
    selected profile happens to manage.
    """
    # Physical cores: os.cpu_count() reports logical processors, and the
    # sentence below used to tell a 2-core laptop it had 4 cores.
    from excmp.ram import physical_cores
    cores = cores or physical_cores()
    heavy_tools = summary.tools.get("precomp", False)

    if summary.floor_store_fraction >= MOSTLY_INCOMPRESSIBLE:
        return Profile.FAST, _mostly_settled_reason(summary)

    if summary.total_bytes <= SMALL_JOB_BYTES:
        # "Seconds" is a claim about the whole job, so it reads the whole
        # job's estimate (2026-10-17 review: a folder half CMYK and half text,
        # or Ogg that balrogg repacks, was told "seconds" beside a table
        # saying minutes). The cause is named only when it is the cause:
        # Precomp's MP3/JPEG recoders, ~1 MB/s each way measured quiet.
        if summary.strongest_seconds >= 60:
            if summary.strongest_recode_seconds * 2 >= summary.strongest_seconds:
                return Profile.EXTREME, (
                    "Small, though Precomp recodes these files slowly — minutes, "
                    "not seconds. Still the best ratio.")
            return Profile.EXTREME, (
                "Small, though the full chain still takes minutes here. Still "
                "the best ratio.")
        return Profile.EXTREME, (
            "Small enough that the full chain costs seconds, so take the best ratio.")

    if summary.total_bytes >= BIG_JOB_BYTES and cores <= 4:
        # B21 (review): no claim about Normal's ratio. On PNG, GIF and the
        # containers only Precomp opens, Normal's own row reads 0%, and "most
        # of the win" sat beside it.
        return Profile.NORMAL, (
            f"{fmt_size(summary.total_bytes)} on {cores} cores — Extreme would run for "
            "hours here. Normal finishes far sooner.")

    probe = (summary.floor_probe_bytes / summary.total_bytes
             if summary.total_bytes else 0.0)
    if heavy_tools and summary.floor_pipeline_fraction - probe >= 0.3:
        return Profile.EXTREME, (
            "Lots of compressible data and the repack tools are installed — this is "
            "exactly what the full chain is for.")
    if probe >= 0.3 and summary.floor_pipeline_fraction - probe < 0.05:
        # B21b: Extreme came out the same size as Normal on MKV and MP4, 60%
        # slower; Precomp has no video codec. Only said when there is little
        # else for Extreme to do (review: beside 29% PNG it would take a
        # third off those).
        return Profile.NORMAL, (
            "Mostly compressed video/audio: Normal takes the few percent 7-Zip "
            "finds in it. Extreme adds only time on video.")

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
#: Past this, the wait stops being something you sit through (J6). 45 minutes
#: is roughly where "I will wait" turns into "I will come back later" - and the
#: point of saying so is that "3 hours" means something to a person in a way
#: that "0.842 MB/s" does not.
LONG_JOB_SECONDS = 45 * 60


def long_job_warning(seconds: float) -> str | None:
    """A sentence for a job worth walking away from, or None.

    Generalises C4's media-specific warning. The measurement that justified
    the whole Smart Advisor was that Extreme cost 2.7x the time of Normal for
    0.17 extra percentage points, and nothing said so until after the wait
    (benchmarks/2026-08-01). The comparison table makes the *relative* cost
    visible; this makes the absolute one visible.

    The suggestion matters as much as the number. "About 3 hours" is a fact;
    "about 3 hours - worth starting before you step away" is help.
    """
    if seconds < LONG_JOB_SECONDS:
        return None
    if seconds >= 90 * 60:
        hours = seconds / 3600.0
        amount = (f"about {hours:.0f} hours" if hours >= 1.75
                  else "about an hour and a half")
        return (f"This job is {amount} on this machine - worth starting "
                f"before you step away, or leaving to run overnight.")
    minutes = int(round(seconds / 60.0))
    return (f"This job is about {minutes} minutes on this machine - worth "
            f"starting before you step away.")


STAGE_LABELS: dict[str, str] = {
    "tar": "tar",
    "zstd": "Zstandard",
    "sevenzip": "7-Zip",
    "precomp": "Precomp",
    "srep": "SREP",
    "dedup": "Dedup",
    "zpaqfranz": "zpaqfranz",
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


def _saved_words(fraction: float, upper_bound: bool) -> str:
    """How much a profile saves, in words that stay possible.

    ``fmt_percent`` rounds, so a Precomp ceiling of 1.5 KB out of 371.5 KB
    (99.6 %) printed "100 % or better" — an archive of zero bytes, or smaller.
    The display is capped at 99 % whenever anything at all survives, which is
    always: the container carries a manifest even if every stage returns
    nothing. Only the *wording* is capped; the estimator's own number is
    untouched, so nothing downstream is lied to.
    """
    percent = fraction * 100
    if percent >= 99.5:
        percent = 99
    text = f"{percent:.0f}%"
    return f"{text} or better" if upper_bound else text


def _ram_words(profile: Profile, cores: int | None,
               input_bytes: int = 0, stages: Sequence[str] | None = None,
               inflation: int = 1, piped_bytes: int | None = None,
               threads: int | None = None) -> str:
    """Peak compression RAM for a profile on this machine.

    **Fast is no longer blank.** It used to be, on the stated grounds that
    "zstd's window is a tenth of it and never the thing that runs a 16 GB
    laptop out of memory" - and K4 measured 1,813 MiB for exactly that stage
    with the window pinned wide, which is the same order as an LZMA2
    dictionary. Leaving the cell empty in a *comparison* table then implied
    Fast was free rather than unmeasured, which is the worse of the two
    errors a column like this can make.

    Fast's figure moves with the input, because `ZstdStage` fits its window to
    the data rather than pinning it - so a small job honestly reports a small
    number here.

    **B17: Insane follows its chain, not its name.** When the chain really
    ends in zpaqfranz, the figure is zpaqfranz's measured model; with
    zpaqfranz missing, Insane falls back to 7-Zip and LZMA2's figure is
    correct again. Before this, Insane always quoted LZMA2: 7,084 MiB for a
    Silesia-sized job at the default thread count, where zpaqfranz peaked at
    1,819 MiB (-m5) or 2,761 MiB (-m58) on a comparable 237 MB input.
    ``cores`` of None means each tool's own default, and zpaqfranz's is
    physical cores (measured: ``2T`` on this 4-logical-processor laptop), not
    `os.cpu_count()`. ``inflation`` is Precomp's worst-case multiplier: the
    block count depends on what zpaqfranz receives, not on the original size.
    """
    from excmp.ram import (ZPAQFRANZ_METHOD, effective_dict,
                           lzma2_compress_ram, lzma2_default_dict,
                           zpaqfranz_compress_ram, zpaqfranz_threads,
                           zstd_compress_ram)

    if stages and stages[-1] == "zpaqfranz":
        # Stored files never reach zpaqfranz, so only piped bytes count.
        base = piped_bytes if piped_bytes is not None else input_bytes
        fed = base * (inflation if "precomp" in stages else 1)
        # `threads` is the Worker threads setting, the same request the
        # stage hands `zpaqfranz_threads`, so the cell and the job agree.
        return fmt_size(zpaqfranz_compress_ram(
            ZPAQFRANZ_METHOD,
            zpaqfranz_threads(threads or cores or 0, ZPAQFRANZ_METHOD), fed))
    if profile is Profile.FAST:
        from excmp.stages.zstdstage import _window_log_for
        return fmt_size(zstd_compress_ram(_window_log_for(input_bytes)))
    # The threads SevenZipStage will really pass: the Worker threads setting
    # when there is one, else one per physical core. os.cpu_count() here
    # quoted the 4-thread figure.
    from excmp.ram import physical_cores
    threads = threads or cores or physical_cores()
    # Clamped to the data: 7-Zip does the same before quoting its own figure,
    # and without it a 371 KB job was advertised as needing 6 GB.
    dict_bytes = effective_dict(lzma2_default_dict(9), input_bytes)
    return fmt_size(lzma2_compress_ram(dict_bytes, threads))


def _span(low: float, high: float, formatter) -> str:
    """'34s – 2 min', or '' when the ends round to the same thing.

    Endpoints lose the '~' that fmt_eta adds - the range already says the number
    is approximate. A collapsed range returns empty rather than repeating the
    value: on a small corpus the first draft printed "about 16.6 MB" with
    "16.6 MB" underneath it, and "a few seconds" twice.
    """
    lo, hi = formatter(low).lstrip("~ "), formatter(high).lstrip("~ ")
    if lo == hi:
        return ""
    # A shared unit is written once: "40.0 – 90.1 MB", not
    # "40.0 MB – 90.1 MB". Cosmetic until B8, which made the estimator
    # honest about compressible data and therefore widened every range - the
    # populated Compress page went 415 -> 447px against a 420px guard, and
    # this is where the characters went. Saying "MB" twice was never carrying
    # information the reader did not already have from the second one.
    lo_unit = lo.rpartition(" ")[2]
    if lo_unit and lo_unit == hi.rpartition(" ")[2]:
        return f"{lo.rpartition(' ')[0]} – {hi}"
    return f"{lo} – {hi}"


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
    ram_text: str = ""    # peak compression RAM - nobody else shows this
    #: B17: "low – high" when the peak depends on what Precomp finds (a
    #: zpaqfranz chain), shown as the cell's second line. Empty otherwise.
    ram_range: str = ""
    recommended: bool = False
    reason: str = ""      # why it is recommended (from recommend_profile)
    note: str = ""        # the trade-off warning, when a cheaper profile wins
    caveat: str = ""      # missing tools / not-yet-wired backends
    tone: str = ""        # "", "ok", "warn" - always paired with words
    #: The estimate in raw seconds. `time_text` is already formatted for a
    #: human, and re-parsing "about 3 hours" to decide whether to warn about
    #: it would be a formatting bug waiting to happen (J6).
    time_seconds: float = 0.0
    #: I6: what this profile really saved when it was run on the sample, e.g.
    #: "63%". Empty until a comparison has actually run this profile.
    #:
    #: It sits **beside** the estimate rather than replacing it, because the
    #: two answer different questions: the estimate is about the whole input,
    #: this is about the bytes that were measured. Merging them would produce
    #: a number with a measurement's authority and an estimate's scope.
    measured_saved_text: str = ""
    #: The archive this profile really produced - but ONLY when the sample was
    #: the whole input, because then it is not a projection, it is the answer.
    #: On a genuine subset this stays empty and the estimate keeps the column:
    #: scaling a sample's archive up to the folder's size would be an estimate
    #: wearing a measurement's clothes.
    measured_size_text: str = ""
    #: The word under them. Always present when either measured field is, so a
    #: reader never has to guess which of the two kinds of number they see.
    measured_note: str = ""


def profile_comparison(infos: list[FileInfo], tools: dict[str, ToolInfo | None],
                       summary: AnalysisSummary,
                       cores: int | None = None,
                       rates: Rates = DEFAULT_RATES,
                       measured: Mapping[Profile, MeasuredRun] | None = None,
                       measured_whole_input: bool = False,
                       zpaq_threads: int | None = None,
                       ) -> list[ComparisonRow]:
    """Every profile with its estimated size and time, recommendation marked.

    Reads the recommendation from :func:`recommend_with_estimates` rather than
    deciding again, so the highlighted row and the card badge can never disagree
    - and so the table never recommends a row it has itself flagged.

    ``measured`` (I6) carries the profiles a comparison run has actually
    executed on a sample. Those rows gain a second, measured saving beside the
    estimate. It never changes the estimate, the recommendation or the flags:
    a ratio measured on 56 MB of a 5 GB folder is a ranking, not a forecast,
    and letting it move the recommendation would quietly turn it into one.

    ``measured_whole_input`` says the sample was not a sample at all - every
    file went through - so the measured archive size may take the size column
    as well. It is a separate flag rather than something inferred here because
    only the caller holds the :class:`~excmp.sample.Sample` that knows.
    """
    if not infos:
        return []
    measured = dict(measured or {})

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
        else:
            size_text = f"about {fmt_size(est.size.expected)}"
        saved_text = _saved_words(est.size.saved_fraction, est.size.upper_bound)

        # Peak RAM for this profile on THIS machine. 7-Zip's Add dialog is the
        # only other place you can see this before starting, and on a 16 GB
        # two-core laptop it is the difference between a job and a swap storm.
        ram_text, ram_range = _ram_words(est.profile, cores, summary.total_bytes,
                                         threads=zpaq_threads), ""
        if est.stages and est.stages[-1] == "zpaqfranz":
            # Inflation over *this profile's piped files* only: averaged over
            # stored files too, a stored video used to lower the quoted peak.
            piped = {f for r in make_plan(infos, est.profile, tools).routes
                     if r.action == "pipeline" for f in r.files}
            inflation = precomp_inflation([i for i in infos if i.path in piped]) \
                if piped else 1
            lo = _ram_words(est.profile, cores, summary.total_bytes,
                            stages=est.stages, inflation=1,
                            piped_bytes=est.size.piped_bytes, threads=zpaq_threads)
            ram_text = _ram_words(est.profile, cores, summary.total_bytes,
                                  stages=est.stages, inflation=inflation,
                                  piped_bytes=est.size.piped_bytes,
                                  threads=zpaq_threads)
            ram_range = f"{lo} – {ram_text}" if lo != ram_text else ""

        # I6. `_saved_words` caps its wording at 99% for an upper bound it
        # cannot rule out; a measurement has no such problem, so it is
        # reported plainly. `upper_bound=False` says exactly that: this
        # number happened.
        run = measured.get(est.profile)
        measured_saved = ""
        measured_size = ""
        measured_note = ""
        if run is not None and run.verified and run.orig_bytes > 0:
            measured_saved = _saved_words(run.saved_fraction, upper_bound=False)
            measured_note = "measured"
            if measured_whole_input:
                measured_size = fmt_size(run.final_bytes)

        rows.append(ComparisonRow(
            profile=est.profile,
            title=PROFILE_LABELS.get(est.profile, est.profile.value),
            chain=chain,
            size_text=size_text,
            size_range=_span(est.size.low, est.size.high, fmt_size),
            saved_text=saved_text,
            ram_text=ram_text,
            ram_range=ram_range,
            time_text=fmt_eta(est.time.expected),
            time_range=_span(est.time.low, est.time.high, fmt_eta),
            time_seconds=est.time.expected,
            recommended=is_recommended,
            reason=reason if is_recommended else "",
            note=note,
            caveat=_short_caveat(est.warnings),
            tone="ok" if is_recommended else ("warn" if note else ""),
            measured_saved_text=measured_saved,
            measured_size_text=measured_size,
            measured_note=measured_note,
        ))
    return rows


def measurement_caption(sample: Sample, profiles_run: int) -> str:
    """One line saying exactly what was measured, including what it missed.

    Every clause here is load-bearing and each exists because the alternative
    is a lie of omission:

    - the byte count and share, because "measured" on 1.1% of a folder is a
      different claim from "measured";
    - the drift, because the sampler cannot always keep a category's share
      (see :mod:`excmp.sample`) and a starved category moves the ratio;
    - "ranks the profiles", because that is the only claim a sample supports.
    """
    if not profiles_run or not sample.files:
        return ""
    files = len(sample.files)
    noun = "file" if files == 1 else "files"
    if sample.is_whole_input:
        where = f"Measured on all {files} {noun} ({fmt_size(sample.total_bytes)})"
    else:
        where = (f"Measured on {files} {noun} — {fmt_size(sample.total_bytes)}, "
                 f"{sample.fraction * 100:.1f}% of this input")

    left_out = list(sample.missing_categories) + list(sample.under_represented)
    if left_out:
        names = ", ".join(CATEGORY_LABELS.get(c, c.value) for c in left_out)
        names = names[:1].upper() + names[1:]
        return (f"{where}. {names} could not fit the sample in proportion, so "
                f"this ranks the profiles rather than predicting the final size.")
    if sample.is_whole_input:
        return f"{where}. These are the real numbers for this job."
    return f"{where}. Real ratios for those bytes, not a forecast for the rest."



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
