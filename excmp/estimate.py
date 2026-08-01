"""How big will the archive be, and how long will it take? (Phase J, J1+J2)

Qt-free and engine-side, so it is testable on its own and usable from the CLI.
Returns numbers only - the prose and the rounding live in ``gui/`` (see
``gui.format`` and ``gui.suggest``), because "~3 min" is a presentation
decision and 163.4 seconds is a fact.

Two rules shape everything here.

**Measure, do not look up.** ``analyzer.sample_stats`` already compressed each
file's samples during analysis, so the per-file ratio is an observation. Files
routed to ``store`` are copied verbatim, so their contribution is not an
estimate at all - it is addition, and it is exact.

**Two rates, not one.** On the 2026-08-01 corpus 79% of the bytes were stored
(disk-bound) and 21% piped (CPU-bound). Blending those into a single "11.6 MB/s"
would mispredict on any other mix, so time is
``stored/io_rate + piped/codec_rate``.

Everything the model does not know shows up as a **range**. There is no single
number here, on purpose: measured throughput for the same chain varied 2.5x
between two real corpora, and pretending otherwise is how progress bars come to
be disbelieved.

Calibration
-----------
Rates and factors are keyed on the **resolved chain**, not the profile name.
When Precomp is missing, Extreme runs the same stages Fast does, and it must
then predict the same result rather than keep promising a ratio the absent tool
was going to deliver.

The shipped values are derived in
``docs/benchmarks/2026-08-01-estimator-backtest.md`` from a recorded 721 MB run.
They are a cold-start prior: J7 will record real throughput per completed job
and blend it in, which is why :class:`Rates` is an argument and not a global.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from .analyzer import FileInfo
from .planner import Plan, Profile, plan as make_plan, store_reason
from .tools import ToolInfo

# --- calibration ----------------------------------------------------------
# Bytes/s for verbatim copies. Capped by the *source* disk in practice, and the
# model is insensitive to it: on the reference corpus, moving this from 100 to
# 60 MB/s shifted the derived codec rates by only ~7%.
_IO_RATE = 100e6

# Multiplier turning the zstd-3 worst-sample probe into the chain's real ratio.
# Fitted at 0.947 for a plain 7z chain on the reference corpus; ordered by chain
# strength rather than fitted per profile, which would over-fit one corpus's
# composition. All near 1.0, which is the sign the *structure* is right - the
# mean-sample model needed 1.28 here and 1.07 on the same run's other profile.
_CODEC_FACTOR: Mapping[str, float] = MappingProxyType({
    "zstd": 0.960,
    "sevenzip": 0.947,
    "precomp+sevenzip": 0.941,
})

# Bytes/s through the chain, piped bytes only - geometric means of every real
# measurement we have, because they disagree by a lot and no single run deserves
# to win. 7-Zip: 2.616 MB/s reading an external HDD, 4.031 MB/s on local disk.
# zstd: 3.2 and 3.627 MB/s. (An earlier guess had zstd at half 7-Zip's speed,
# inferred from a 16 MB corpus; measuring 139 MB showed the two are within 5% of
# each other, so ZstdStage's level 19 is not the handicap it looked like.)
#
# The Precomp chain is the hard case. Measured with the pre-B11 srep chain:
# 2.642 MB/s when Precomp finds nothing and streams straight through, and
# 0.842 MB/s when it does find deflate streams and the inflated data lands on
# the final codec - a 3.1x spread between two regimes, not noise. Nothing cheap
# predicts which regime applies (see _PRECOMP_OPTIMISTIC), so the rate sits in
# the middle and the range covers both. B11 removed srep from the chain, which
# should only make it faster; the 2026-08-01 post-B11 runs re-anchor this.
#
# (No key for chains containing srep: they are never planned any more. Old
# srep archives still extract, but extraction needs no estimate.)
_CODEC_RATE: Mapping[str, float] = MappingProxyType({
    "zstd": 3.407e6,
    "sevenzip": 3.247e6,
    "precomp+sevenzip": 1.55e6,
})

_FALLBACK_FACTOR = 0.95
_FALLBACK_RATE = 2.5e6

# How wide the time range has to be to stay honest. Ordinary chains vary about
# 2x between corpora; a Precomp chain has to span its two regimes as well.
_RATE_SPREAD = 2.0
_PRECOMP_RATE_SPREAD = 3.2

# How much worse than the worst sample things can still turn out. Small, because
# the worst sample is already the pessimistic reading.
_HIGH_SLACK = 1.05

# Files the planner piped *despite* store_reason() advising against it - the
# Precomp override. The probe measured already-deflated bytes, so it says
# "incompressible" and knows nothing about what Precomp will find underneath.
#
# With a zlib header present, Precomp almost certainly cracks it: the 2026-07-18
# run reached a 0.276 ratio on exactly this shape. Without one (a .rar payload
# inside a .zip, an .msi), it usually cannot - which is what the 2026-08-01 run
# measured, where these files gained essentially nothing. Hence two ranges, both
# deliberately wide: this is the one place the estimator genuinely cannot know.
_ZLIB_LOW, _ZLIB_EXPECTED, _ZLIB_HIGH = 0.28, 0.45, 1.0
_OVERRIDE_LOW = 0.30

# The limit of what sampling can know, found the hard way.
#
# A zstd probe reads raw bytes. Precomp reads *structure*: it finds deflate
# streams inside a file and expands them so LZMA2 can work on the original data.
# Measured on two real installers with near-identical probe readings - entropy
# 7.52 and 7.78, worst-sample ratio 0.96 and 1.00 - Precomp found nothing in one
# and cut the other by a further 33 percentage points. No cheap signal separates
# them, so this is a documented limitation and not a tuning problem.
#
# The consequence, deliberately chosen: under a Precomp chain, `expected` assumes
# Precomp finds nothing, which makes it a conservative *upper bound* on the size
# rather than a best guess (SizeEstimate.upper_bound says so, and the GUI says
# "at most"). Never overselling a win that may not arrive is the right bias for
# this product. But `low` then has to reach far enough down to contain the case
# where Precomp does work, or the range would exclude the truth - which is worse
# than having no range.
_PRECOMP_OPTIMISTIC = 0.30

# Container overhead. Everything in the .excmp is ZIP_STORED, so manifest.json
# counts at full size: a ledger entry per file (size, 64-hex sha256, route) plus
# the routes list naming every file a second time, plus zip headers per stored
# entry. Only material for very small archives.
_LEDGER_BYTES_PER_FILE = 150
_ZIP_ENTRY_BYTES = 76
_CONTAINER_BASE = 512


@dataclass(frozen=True)
class Rates:
    """The machine-specific half of the model, injected so J7 can replace it."""

    io_rate: float = _IO_RATE
    codec: Mapping[str, float] = _CODEC_RATE
    codec_factor: Mapping[str, float] = _CODEC_FACTOR
    rate_spread: float = _RATE_SPREAD

    @staticmethod
    def chain_key(stages: Sequence[str]) -> str:
        """``['precomp', 'sevenzip']`` -> ``'precomp+sevenzip'``.

        The engine prepends a ``tar`` stage at run time for multi-stage chains;
        it is pure I/O and carries no calibration, so it is ignored here.
        """
        return "+".join(s for s in stages if s != "tar")

    def rate_for(self, stages: Sequence[str]) -> float:
        return self.codec.get(self.chain_key(stages), _FALLBACK_RATE)

    def factor_for(self, stages: Sequence[str]) -> float:
        return self.codec_factor.get(self.chain_key(stages), _FALLBACK_FACTOR)

    def spread_for(self, stages: Sequence[str]) -> float:
        """Precomp chains need a wider range - they have two throughput regimes."""
        if "precomp" in stages:
            return max(self.rate_spread, _PRECOMP_RATE_SPREAD)
        return self.rate_spread


DEFAULT_RATES = Rates()


@dataclass(frozen=True)
class SizeEstimate:
    """Predicted archive size. ``stored_bytes`` is exact, the rest is not."""

    low: int
    expected: int
    high: int
    stored_bytes: int
    piped_bytes: int
    overhead_bytes: int
    # True for Precomp chains: ``expected`` assumes Precomp finds nothing, so the
    # real archive may be far smaller. Say "at most", never "about".
    upper_bound: bool = False

    @property
    def total_bytes(self) -> int:
        """Input size - what the archive is being compared against."""
        return self.stored_bytes + self.piped_bytes

    @property
    def saved_bytes(self) -> int:
        return max(0, self.total_bytes - self.expected)

    @property
    def saved_fraction(self) -> float:
        return self.saved_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def saved_percent(self) -> float:
        return self.saved_fraction * 100.0


@dataclass(frozen=True)
class TimeEstimate:
    """Predicted compress seconds. Round it for display; never show it raw."""

    low: float
    expected: float
    high: float


@dataclass(frozen=True)
class ProfileEstimate:
    """One row of the comparison table."""

    profile: Profile
    stages: list[str]
    size: SizeEstimate
    time: TimeEstimate
    warnings: list[str] = field(default_factory=list)
    # Set when a *faster* profile gets essentially the same archive. The GUI
    # turns these numbers into the sentence; the engine only measures.
    not_worth_it: bool = False
    beaten_by: Profile | None = None
    time_multiple: float = 0.0
    extra_points: float = 0.0


# A slower profile has to earn its extra time: at least this much more saving,
# or it gets flagged. Measured motivation: on the reference corpus Extreme cost
# 2.7x Normal's time for 0.17 extra percentage points.
NOT_WORTH_IT_TIME_MULTIPLE = 2.0
NOT_WORTH_IT_MIN_POINTS = 1.0


def _split(infos: list[FileInfo], the_plan: Plan) -> tuple[list[FileInfo], list[FileInfo]]:
    """(stored, piped) - the routing decision the planner already made."""
    piped_paths: set[Path] = set()
    for route in the_plan.routes:
        if route.action == "pipeline":
            piped_paths.update(route.files)
    stored = [i for i in infos if i.path not in piped_paths]
    piped = [i for i in infos if i.path in piped_paths]
    return stored, piped


def _stages_of(the_plan: Plan) -> list[str]:
    for route in the_plan.routes:
        if route.action == "pipeline":
            return list(route.stages)
    return []


def _piped_ratios(info: FileInfo, factor: float,
                  has_precomp: bool) -> tuple[float, float, float]:
    """(low, expected, high) ratio for one file the chain will process."""
    if store_reason(info) is not None:
        # Piped only because the profile has Precomp - see _ZLIB_* above.
        if info.zlib_stream:
            return _ZLIB_LOW, _ZLIB_EXPECTED, _ZLIB_HIGH
        return _OVERRIDE_LOW, info.sample_ratio_max, 1.0

    low = info.sample_ratio * factor
    expected = info.sample_ratio_max * factor
    high = min(1.0, info.sample_ratio_max * _HIGH_SLACK)
    if has_precomp:
        # The probe cannot see the deflate streams Precomp will open, so the
        # optimistic end has to allow for it. See _PRECOMP_OPTIMISTIC.
        low = min(low, _PRECOMP_OPTIMISTIC)
    return low, expected, max(expected, high)


def _overhead(infos: list[FileInfo], stored_count: int) -> int:
    """Manifest + zip headers. Everything in the container is ZIP_STORED."""
    if not infos:
        return 0
    names = sum(len(i.path.name) for i in infos)
    return (_CONTAINER_BASE
            + _LEDGER_BYTES_PER_FILE * len(infos)
            + 3 * names                              # ledger, routes, zip header
            + _ZIP_ENTRY_BYTES * (stored_count + 2))  # + manifest and payload


def estimate_size(infos: list[FileInfo], the_plan: Plan,
                  rates: Rates = DEFAULT_RATES) -> SizeEstimate:
    """Predict the archive's size as a range.

    Stored files land at exactly 1.0 because they are copied byte for byte.
    Piped files are predicted from their measured samples, driven by the *worst*
    sample rather than the mean - see ``analyzer.sample_stats``.
    """
    stored, piped = _split(infos, the_plan)
    stages = _stages_of(the_plan)
    factor = rates.factor_for(stages)
    has_precomp = "precomp" in stages

    stored_bytes = sum(i.size for i in stored)
    piped_bytes = sum(i.size for i in piped)
    overhead = _overhead(infos, len(stored))

    low = expected = high = 0.0
    for info in piped:
        r_low, r_expected, r_high = _piped_ratios(info, factor, has_precomp)
        low += info.size * r_low
        expected += info.size * r_expected
        high += info.size * r_high

    base = stored_bytes + overhead
    return SizeEstimate(
        low=int(base + low),
        expected=int(base + expected),
        high=int(base + high),
        stored_bytes=stored_bytes,
        piped_bytes=piped_bytes,
        overhead_bytes=overhead,
        upper_bound=has_precomp and bool(piped),
    )


def estimate_time(infos: list[FileInfo], the_plan: Plan,
                  rates: Rates = DEFAULT_RATES) -> TimeEstimate:
    """Predict compress seconds with the two-rate model."""
    stored, piped = _split(infos, the_plan)
    stored_bytes = sum(i.size for i in stored)
    piped_bytes = sum(i.size for i in piped)

    stages = _stages_of(the_plan)
    io_seconds = stored_bytes / rates.io_rate if rates.io_rate else 0.0
    rate = rates.rate_for(stages)
    codec_seconds = piped_bytes / rate if rate else 0.0
    spread = max(1.0, rates.spread_for(stages))

    return TimeEstimate(
        low=io_seconds + codec_seconds / spread,
        expected=io_seconds + codec_seconds,
        high=io_seconds + codec_seconds * spread,
    )


def compare_profiles(infos: list[FileInfo], tools: dict[str, ToolInfo | None],
                     rates: Rates = DEFAULT_RATES,
                     profiles: Sequence[Profile] | None = None) -> list[ProfileEstimate]:
    """Every profile side by side, with the bad trades flagged.

    ``planner.plan()`` is pure and already runs per profile elsewhere, so this
    costs nothing but arithmetic - no files are re-read.
    """
    if not infos:
        return []

    rows: list[ProfileEstimate] = []
    for profile in (profiles if profiles is not None else list(Profile)):
        the_plan = make_plan(infos, profile, tools)
        rows.append(ProfileEstimate(
            profile=profile,
            stages=_stages_of(the_plan),
            size=estimate_size(infos, the_plan, rates),
            time=estimate_time(infos, the_plan, rates),
            warnings=list(the_plan.warnings),
        ))
    return _flag_bad_trades(rows)


def _flag_bad_trades(rows: list[ProfileEstimate]) -> list[ProfileEstimate]:
    """Mark any row a *faster* profile makes pointless.

    Among the alternatives that qualify, names the one that compresses best
    rather than the very quickest. They are all already at least twice as fast,
    so the useful sentence is "and this one also gets the smallest archive" -
    pointing at Fast because it beat Normal by four percent of the wall clock
    would be technically true and practically misleading.
    """
    out: list[ProfileEstimate] = []
    for row in rows:
        best: ProfileEstimate | None = None
        multiple = points = 0.0
        for other in rows:
            if other.profile is row.profile or other.time.expected >= row.time.expected:
                continue
            if other.time.expected <= 0:
                continue
            ratio = row.time.expected / other.time.expected
            gain = row.size.saved_percent - other.size.saved_percent
            if ratio < NOT_WORTH_IT_TIME_MULTIPLE or gain >= NOT_WORTH_IT_MIN_POINTS:
                continue
            better = (best is None
                      or other.size.saved_percent > best.size.saved_percent
                      or (other.size.saved_percent == best.size.saved_percent
                          and other.time.expected < best.time.expected))
            if better:
                best, multiple, points = other, ratio, gain
        if best is None:
            out.append(row)
            continue
        out.append(ProfileEstimate(
            profile=row.profile, stages=row.stages, size=row.size, time=row.time,
            warnings=row.warnings, not_worth_it=True, beaten_by=best.profile,
            time_multiple=multiple, extra_points=points,
        ))
    return out
