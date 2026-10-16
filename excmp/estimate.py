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

from . import oggpack
from .analyzer import FileInfo
from .planner import Plan, Profile, plan as make_plan, store_reason
from .tools import ToolInfo

# --- calibration ----------------------------------------------------------
# Bytes/s for verbatim copies. Capped by the *source* disk in practice, and the
# model is insensitive to it: on the reference corpus, moving this from 100 to
# 60 MB/s shifted the derived codec rates by only ~7%.
_IO_RATE = 100e6

# How much better than the zstd-3 probe the real chain does - and it is **not a
# constant**, which is what B8 found.
#
# The old model was a single multiplier per chain, all near 1.0, fitted on the
# 721 MB Programs corpus. That corpus is installers: the probe reads
# ratio_max = 0.91-0.97, there is almost nothing left to compress, and a real
# chain can only match the probe. Near 1.0 was correct *there* and was mistaken
# for a property of the chain.
#
# Silesia says otherwise. Measured 2026-09-08, 12 files / 211,938,580 B, all
# four profiles, every restore byte-identical:
#
#     chain                probe   real ratio   implied factor
#     zstd                0.4047       0.2482            0.613
#     sevenzip            0.4047       0.2297            0.568
#     precomp+sevenzip    0.4047       0.2195            0.542
#     precomp+zpaqfranz   0.4047       0.1945            0.481
#
# So on compressible text the real chains beat the probe by ~2x, the constant
# was wrong by that factor, and the estimator's range excluded the truth on
# 3 of 4 profiles.
#
# **The fit is anchored by physics, not just by two points.** At probe = 1.0 the
# data is incompressible, so a real codec cannot beat the probe either and the
# factor must be 1.0. Fitting a line through the two measured anchors gives
# exactly that, without being told to:
#
#     normal   installers 0.9126 -> 0.9465 | silesia 0.4047 -> 0.5676
#              => factor(r) = 0.2657 + 0.7460 r   ... at r=1.0 -> 1.0117
#     extreme  installers 0.9700 -> 0.9798 | silesia 0.4047 -> 0.5424
#              => factor(r) = 0.2292 + 0.7738 r   ... at r=1.0 -> 1.0030
#
# Landing within 1.2% of 1.0 from two independent corpora is the sign the
# *shape* is right. So the shipped form is the (1.0, 1.0)-anchored one -
# `factor(r) = (1 - k) + k*r` - with `k` from the Silesia anchor and the
# installer anchor kept as the cross-check it turned out to be:
#
#     chain               k      predicted at installer probe   measured
#     sevenzip            0.726                        0.937      0.9465
#     precomp+sevenzip    0.769                        0.977      0.9798
#
# `zstd` and `precomp+zpaqfranz` have only the Silesia anchor plus the physical
# constraint; there is no installer measurement for Fast or Insane on that
# corpus. Recorded as one anchor, not two.
#
# Applied **per file** rather than to the aggregate: a file whose own probe
# says 1.0 gets factor 1.0 and is predicted not to shrink, which is right, and
# a mixed selection is no longer averaged into a single wrong slope.
_CODEC_SLOPE: Mapping[str, float] = MappingProxyType({
    "zstd": 0.650,                  # Silesia anchor only
    "sevenzip": 0.726,              # two anchors, cross-checked to 1.1%
    "precomp+sevenzip": 0.769,      # two anchors, cross-checked to 0.3%
    # B17: re-anchored at -m58, the method Insane now runs. Silesia through
    # engine.compress, 2026-09-27: 37,542,028 B, ratio 0.1771 at probe
    # 0.4047, so factor 0.4377 and k = 0.945. At -m4 it was 0.873 (B8,
    # ratio 0.1945). Still one anchor: the installer run below is a time
    # anchor, and its size is checked by the estimator backtest-style test in
    # tests/test_b17_insane_method.py rather than fitted.
    "precomp+zpaqfranz": 0.945,     # Silesia anchor only, at -m58
})


def codec_factor(slope: float, probe_ratio: float) -> float:
    """The probe-to-reality multiplier at this compressibility.

    ``(1 - k) + k*r``, so incompressible data (r = 1.0) gets 1.0 by
    construction - the one point on this curve that is not a measurement but a
    fact about compression.
    """
    return (1.0 - slope) + slope * max(0.0, min(1.0, probe_ratio))

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
    "zstd": 3.50e6,      # 3.2 / 3.627 / 3.677 MB/s measured
    "sevenzip": 3.38e6,  # 2.616 (external HDD) / 4.031 / 3.985 / 3.104 MB/s
    # Post-B11 chain, both regimes measured on 2026-08-01: 2.218 MB/s when
    # Precomp found nothing (721 MB corpus), 0.891 MB/s when it opened streams
    # (163 MB corpus). Note the same corpora ran the old srep chain at 2.642
    # no-op - srep's dedup used to SHRINK 7-Zip's input, so removing it costs
    # some throughput as well as ratio. Geometric mean of the two regimes.
    "precomp+sevenzip": 1.41e6,
    # B17. Insane had no key at all before this, so it fell back to 2.5 MB/s:
    # a Silesia job was predicted at 99 s and took 3,810 s. Measured at -m58
    # through engine.compress, piped bytes over (compress - restore) seconds:
    # 0.094 MB/s on Silesia (212 MB, Precomp found nothing) and 0.087 MB/s on
    # the 13-file installer sample (Precomp working). Two corpora, two
    # regimes, 8% apart; geometric mean.
    "precomp+zpaqfranz": 0.091e6,
})

# For a chain with no anchor of its own. 0.95 was carried over from when this
# was a *factor*; as a *slope* it means something entirely different - it would
# claim the strongest compressibility response of any chain measured. 0.650 is
# the weakest measured slope (zstd), so an unknown chain is credited no more
# than the least impressive thing we have actually seen.
_FALLBACK_SLOPE = 0.650
_FALLBACK_RATE = 2.5e6

# How wide the time range has to be to stay honest. Ordinary chains vary about
# 2x between corpora; a Precomp chain has to span its two regimes as well.
_RATE_SPREAD = 2.0
_PRECOMP_RATE_SPREAD = 3.2

# Bytes/s for the D9 pre-publish self-test, which restores the WHOLE archive
# (stored files included) and re-hashes it before the atomic rename. Every job
# pays it, so the promised wait must include it. Keyed per chain because the
# verify pass replays the chain's own restore: measured 62.8 MB/s for zstd,
# 31.4 for 7-Zip - and only 3.5 MB/s for a Precomp chain whose streams Precomp
# actually reconstructed, vs 12.4 when it had found nothing. Same two-regime
# problem as compression, priors are geometric means across the measured runs.
_VERIFY_RATE: Mapping[str, float] = MappingProxyType({
    "zstd": 58e6,        # 62.8 MB/s measured
    "sevenzip": 21e6,    # 31.4 / 14.3 MB/s - cache effects swing this 2x+:
    #                      the same extract measured 50.3s inside the gate and
    #                      19.9s user-side minutes later. Coarse on purpose.
    "precomp+sevenzip": 6.5e6,   # 12.7 no-op regime / 3.5 working regime
    # B17, -m58. Context mixing restores as slowly as it compresses, so D9
    # costs Insane nearly a second compress. *Piped* bytes over the
    # engine.extract seconds, since stored bytes are now billed at io_rate:
    # 211,938,580 / 1,555.7 s = 0.136 MB/s (Silesia, nothing stored) and
    # 31,953,310 / 378.1 s = 0.0845 MB/s (installers). Geometric mean.
    "precomp+zpaqfranz": 0.107e6,
})
_FALLBACK_VERIFY_RATE = 15e6

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

# B5: a container whose deflate layer Precomp really can reach.
#
# `analyzer.probe_expandable` answers this structurally - a zip's central
# directory member flags, or a `/FlateDecode` scan for a PDF - which is what
# makes it usable where entropy sampling is not. The note above ("no cheap
# signal separates them") stands for the *bytes*; it does not stand for the
# container, and 224 real files measured the difference:
#
#     profile   predicted (before)   measured
#     normal          9.40%           10.37%
#     extreme        13.78%           50.36%
#
# So the comparison table showed Extreme beating Normal by 4 points where the
# truth was 40, steering users past the bigger win on PDFs and Office
# documents. The aggregate came out at 0.496; 0.55 is used here for the usual
# reason - `expected` must not oversell - and the range still spans the case
# where a particular file turns out to hold nothing.
_EXPANDABLE_LOW, _EXPANDABLE_EXPECTED = 0.30, 0.55
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

# The same problem on the zstd chain after K4, and a remedy that took two
# attempts because the first one was fitted to a single corpus.
#
# `_CODEC_SLOPE["zstd"]` multiplies each file's *own* worst zstd-3 sample.
# Nothing in that shape can express "this file shares 40 MiB with another one",
# which is exactly what K4's wide window made findable, so the measured archive
# landed below `low` and the range excluded the truth.
#
# **The first fix keyed a per-duplicate credit on exact file size** - the
# reasoning being that two files of different lengths cannot be duplicates.
# That is true of *whole-file* duplicates and false of what zstd actually
# does, which is match **substrings**. B8 stressed it across six corpus
# shapes and it failed in both directions at once:
#
#   4x20 MiB distinct text files, equal sizes  ->  low = -33,024,744
#   40 MiB body shared across 3 DIFFERENT sizes ->  actual 0.122 of input,
#                                                   low 0.436, truth excluded
#
# So a coincidence of sizes bought a 90% discount per file and drove the bound
# negative, while genuine cross-file sharing bought nothing. A per-file
# estimator cannot see cross-file redundancy, and pretending otherwise with a
# cheap proxy was worse than admitting it.
#
# What replaces it is a **floor**, applied only to chains with long-range
# matching on, derived from the widest real saving measured across those
# shapes: 87.84% on the cross-size corpus, i.e. 0.122 of the input. 0.10
# clears it with margin and nothing observed goes below it.
#
# The cost is a wider numeric range on ordinary input, which is what this was
# avoiding the first time round. That objection was carried from memory rather
# than re-measured; see the height figure recorded in
# docs/benchmarks/2026-09-08-b8-rebenchmark.md.
_ZSTD_LONG_RANGE_FLOOR = 0.10

# Container overhead: a ledger entry per file (size, 64-hex sha256, route) plus
# zip headers per stored entry. Only material for very small archives.
#
# K1 changed both halves of this. The manifest no longer names every file a
# second time under `routes[].files`, so the name term went from three copies
# to two (ledger key + zip header); and `manifest.json` is now the one DEFLATED
# member of the container, so its share arrives compressed.
#
# The factor is measured on a **real archive**, which matters more than it
# sounds. This constant was first set to 0.10 against a benchmark that deflated
# 14.54 MiB of manifest to 0.65 MiB - a factor of 0.045 - but that document was
# built with a placeholder sha256 (`"0" * 64` on every entry), and a column of
# identical hashes compresses to nothing. Real hashes are random hex and are
# very close to incompressible: 64 chars x N files sets a hard floor no
# deflater can go under.
#
# Measured 2026-09-06 on the 55,477-file end-to-end archive, with real hashes:
#
#     manifest.json  12,782,745 B  ->  2,720,064 B deflated  =  0.213
#
# So 0.045 was optimistic by ~5x and 0.10 by ~2x - i.e. it *under*-booked disk,
# which is the one direction this file is not allowed to err in. 0.30 restores
# the intended pessimism with room for a manifest that is mostly hashes.
_LEDGER_BYTES_PER_FILE = 150
_MANIFEST_DEFLATE_FACTOR = 0.30
# Per stored entry: a 30-byte local header plus a 46-byte central directory
# record, plus the name twice.
#
# This was briefly raised to 160 on the assumption it was too small, because
# pure-random shapes came out above the high bound. Then it was **measured**,
# and the assumption was wrong in the opposite direction - the model already
# over-books:
#
#     files   input        archive      real overhead   modelled
#         1   2,097,152    2,097,725              573      1,044
#         3   6,291,456    6,292,355              899      1,470
#         6  12,582,912   12,584,278            1,366      2,108
#
# So the high bound already covers the container and the D/E miss has some
# other cause, recorded as open in docs/benchmarks/2026-09-08-b8. Reverted to
# 76 rather than left inflated on a guess that measurement contradicted.
_ZIP_ENTRY_BYTES = 76
_CONTAINER_BASE = 512


@dataclass(frozen=True)
class Rates:
    """The machine-specific half of the model, injected so J7 can replace it."""

    io_rate: float = _IO_RATE
    codec: Mapping[str, float] = _CODEC_RATE
    codec_factor: Mapping[str, float] = _CODEC_SLOPE
    rate_spread: float = _RATE_SPREAD
    verify: Mapping[str, float] = _VERIFY_RATE
    #: B13: will Ogg audio be packed by balrogg? ``None`` asks this machine.
    #: Explicit in tests, so an estimate does not depend on what is installed.
    ogg_pack: bool | None = None

    def ogg_packed(self) -> bool:
        return oggpack.available() if self.ogg_pack is None else self.ogg_pack

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
        """The chain's **slope**, not a ready-made multiplier.

        Renamed in spirit but not in name to keep the call sites: what comes
        back feeds `codec_factor(slope, probe)`, because B8 established that
        the multiplier depends on how compressible the file is. See
        `_CODEC_SLOPE`.
        """
        return self.codec_factor.get(self.chain_key(stages), _FALLBACK_SLOPE)

    def spread_for(self, stages: Sequence[str]) -> float:
        """Precomp chains need a wider range - they have two throughput regimes."""
        if "precomp" in stages:
            return max(self.rate_spread, _PRECOMP_RATE_SPREAD)
        return self.rate_spread

    def verify_rate_for(self, stages: Sequence[str]) -> float:
        # A store-only archive restores as a copy + hash: io-bound, no codec.
        if not self.chain_key(stages):
            return self.io_rate
        return self.verify.get(self.chain_key(stages), _FALLBACK_VERIFY_RATE)


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
    #: Original bytes of Ogg audio that balrogg will pack (B13). They sit inside
    #: ``stored_bytes`` and are *predicted*, not exact like the rest of it.
    packed_bytes: int = 0

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


#: MP3 on a chain with Precomp, which recodes it with its built-in packMP3
#: (B18, 2026-10-16). `precomp -cn` then 7-Zip, file by file, on 21 real MP3s
#: from two corpora, every one restored: 0.741 to 0.900 of the original,
#: 0.835 byte-weighted (in-sample). The probe can't see this gain, so it isn't
#: consulted.
#:
#: `expected` is the *worst* file, 0.90, not the average, because a Precomp
#: chain's `expected` is shown as a ceiling ("≤ X", see _PRECOMP_OPTIMISTIC).
#: The average put "≤ 64.0 MB" over a 64.4 MB archive (review, B18); at 0.90
#: every measured file and run sits under it. An MP3 packMP3 declines (a
#: mislabelled file) can still exceed it. `high` is 1.0 for that case, and
#: the disk preflight books `high`.
_MP3_PRECOMP_RATIO = (0.74, 0.90, 1.0)


def _piped_ratios(info: FileInfo, factor: float,
                  has_precomp: bool) -> tuple[float, float, float]:
    """(low, expected, high) ratio for one file the chain will process."""
    if has_precomp and info.path.suffix.lower() == ".mp3":
        return _MP3_PRECOMP_RATIO
    if store_reason(info) is not None:
        # Piped only because the profile has Precomp - see _ZLIB_* above.
        if info.zlib_stream:
            return _ZLIB_LOW, _ZLIB_EXPECTED, _ZLIB_HIGH
        if has_precomp and info.expandable:
            # Roughly half of the real PDF/Office corpus lands here: high
            # entropy, so `store_reason` would keep it, but the container
            # probe says Precomp can open it. Before B5 this returned
            # `sample_ratio_max` (~0.90) as `expected` and predicted no gain.
            return (_EXPANDABLE_LOW, _EXPANDABLE_EXPECTED, 1.0)
        return _OVERRIDE_LOW, info.sample_ratio_max, 1.0

    if has_precomp and info.expandable:
        # Structurally known to hold an expandable deflate layer. The probe's
        # own reading of this file beats the entropy sample, which measured
        # 0.88-0.91 on exactly these files while the real chain took half.
        return (_EXPANDABLE_LOW, _EXPANDABLE_EXPECTED,
                min(1.0, info.sample_ratio_max * _HIGH_SLACK))

    # The multiplier is evaluated at *this file's* own probe reading, so a
    # file the probe calls incompressible is predicted not to shrink while a
    # highly compressible one gets the full benefit of the chain (B8).
    low = info.sample_ratio * codec_factor(factor, info.sample_ratio)
    expected = info.sample_ratio_max * codec_factor(factor, info.sample_ratio_max)
    high = min(1.0, info.sample_ratio_max * _HIGH_SLACK)
    if has_precomp:
        # The probe cannot see the deflate streams Precomp will open, so the
        # optimistic end has to allow for it. See _PRECOMP_OPTIMISTIC.
        low = min(low, _PRECOMP_OPTIMISTIC)
    return low, expected, max(expected, high)


def _dedup_credit(stored: list[FileInfo]) -> int:
    """Bytes G9 *might* remove from the stored route - and **deliberately not
    used**. Kept as the record of an attempt that was measured and rejected.

    The tempting reasoning: `write_container` writes one copy per distinct
    SHA-256, the estimator cannot hash, but equal size is a necessary
    condition for whole-file identity, so crediting all but the first file in
    each size group is an optimistic bound that can only over-credit.

    It cost 50 points of error on a shape where 20 MiB of random data was
    duplicated once (predicted to compress by nothing; actually halved), so it
    looked like a clear win. **It breaks a bigger promise.** Five 10,000,000-byte
    videos that are *not* duplicates got `low = 10 MB` against a true 50 MB,
    and "stored bytes are exact, not estimated" is a documented product
    property - the first test in `tests/test_estimate.py` calls it
    load-bearing, and it is the one number here that is arithmetic rather than
    prediction.

    A store-only estimate that says "exactly this" and is right is worth more
    than one that says "between half and all of it" to accommodate a case that
    may not occur. So shape C stays a known limitation: **duplicates are not
    knowable without hashing, and breaking exactness to guess at them is the
    wrong trade.**

    Note this is the *second* time the same proxy has been wrong (see
    `_ZSTD_LONG_RANGE_FLOOR` for the first). There it failed because zstd
    matches substrings; here the mechanism is right and the *cost* is wrong.
    Two different reasons, one seductive proxy.

    `write_container` writes one copy per distinct SHA-256 and points the rest
    at it with a `same_as`. The estimator cannot hash - that is the whole
    reason the analysis pass is fast - but identical size is a **necessary**
    condition for identical content, so files sharing a size are the exact
    superset of the set G9 will collapse. Crediting all but the first in each
    size group is therefore an optimistic bound that can over-credit and never
    under-credit, which is what the low end is for.

    Measured before this existed: 20 MiB of random data duplicated once was
    predicted to compress by **nothing** - random bytes route to `store`, so
    every ratio in the model was 1.0 - while the real archive came out at
    exactly half the input because G9 found the duplicate. A 50-point miss,
    and the largest single error in the whole stress matrix.

    This is the same size-based reasoning that was **wrong** for the zstd
    window (see `_ZSTD_LONG_RANGE_FLOOR`), and it is right here for a reason
    worth keeping straight: zstd matches *substrings*, so two files of
    different lengths can still share megabytes, and equal length implies
    nothing. G9 matches *whole files*, so equal length is exactly the right
    filter. The mechanism decides whether the proxy is valid, not the fact
    that both involve duplicates.
    """
    by_size: dict[int, int] = {}
    for info in stored:
        by_size[info.size] = by_size.get(info.size, 0) + 1
    return sum(size * (count - 1)
               for size, count in by_size.items() if count > 1)


def _overhead(infos: list[FileInfo], stored_count: int) -> int:
    """Manifest + zip headers. The manifest is deflated; everything else in the
    container is ZIP_STORED.

    `names` uses the *basename*, not the archive-relative path that actually
    lands in the manifest - measured on a `node_modules` tree those are 20 and
    152 bytes, so this term under-reads a deep tree ~7x. It is left alone
    because `_overhead` is not given the relmap, and because deflating the
    manifest shrinks the whole term by another order of magnitude: 8.5 MB of
    ledger for 57,020 files becomes ~850 KB against a multi-gigabyte archive.
    `manifest.manifest_size_estimate` is the function that has to be exact,
    and it takes the real relative paths.
    """
    if not infos:
        return 0
    names = sum(len(i.path.name) for i in infos)
    manifest = (_LEDGER_BYTES_PER_FILE * len(infos)
                + names)                             # ledger key
    return (_CONTAINER_BASE
            + int(manifest * _MANIFEST_DEFLATE_FACTOR)
            + names                                  # zip header per entry
            + _ZIP_ENTRY_BYTES * (stored_count + 2))  # + manifest and payload


# -- B13: Ogg audio packed by balrogg ---------------------------------------
#
# Priors from 18 real music files (169,975,314 B, Wikimedia Commons) on one
# machine whose speed varied 3.5x within a session (docs/benchmarks/
# 2026-10-06-b13). They are priors, so everything built on them is a range.
#
# Saved, bytes-weighted: corpus 1 (13 Vorbis) 15.1% at -9, corpus 2 (25 Vorbis
# game music and speech) 12.5% at -5, per file 8.5% .. 44.3%; Opus 3.9% and
# 4.8%. Corpus 2 also held two files balrogg refused outright (Ogg FLAC, and
# Vorbis behind a Skeleton track: 6.2% of that corpus's bytes), which is what
# `high` is for: the case where little or nothing is gained.
#
# `high` is exactly 1.0: `pack` never returns bytes that are not smaller, and a
# file balrogg declines is stored as it is. The disk preflight books `high`,
# so anything under 1.0 would let it under-reserve (review, B13).
_PACK_RATIO = {"vorbis": (0.74, 0.865, 1.0), "opus": (0.94, 0.96, 1.0)}

# The saving at each effort as a share of -9's (three real files, 19.3 MB):
# -1 9.448%, -2 10.879%, -3 11.039%, -4 11.242%, -5 11.547% ... -9 11.586%.
# The ratios above are -9's; a profile that packs at a lower effort saves this
# much of the same saving.
_PACK_EFFORT_SAVING = {1: 0.815, 2: 0.939, 3: 0.953, 4: 0.970, 5: 0.997,
                       6: 0.9986, 7: 0.9988, 8: 0.9991, 9: 1.0}

# Two process starts per file (encode, then the decode that proves it) and
# their temp files, whatever the file's size. Small game sound effects come
# in thousands, so this is not rounding.
_PACK_PER_FILE_S = 0.3

# Encode speed at -9, bytes/s, aggregate over each format: Vorbis 143.5 MB in
# 1,205 s, Opus 26.4 MB in 20 s. Opus is ten times quicker.
_PACK_ENCODE_RATE = {"vorbis": 0.119e6, "opus": 1.337e6}

# Time at each effort as a fraction of -9's (three real files, one batch):
# -1 0.042, -2 0.074, -3 0.087, -4 0.113, -5 0.27, -6 0.49, -7 0.55, -8 0.75.
_PACK_EFFORT_TIME = {1: 0.042, 2: 0.074, 3: 0.087, 4: 0.113, 5: 0.27,
                     6: 0.49, 7: 0.55, 8: 0.75, 9: 1.0}

# Decode speed, both formats (143.5 MB in 94 s; 26.4 MB in 18 s).
_PACK_DECODE_RATE = 1.5e6

# The same Vorbis files took 85 s and then 290 s at -9 an hour apart, so the
# range has to be at least that wide.
_PACK_SPREAD = 3.5


@dataclass(frozen=True)
class PackCost:
    """What packing the Ogg files on the store route will cost."""

    bytes: int = 0
    #: Compress side: every file is encoded, then decoded once to prove it.
    seconds: float = 0.0
    #: D9's restore decodes every packed entry again before publishing.
    verify_seconds: float = 0.0
    vorbis_bytes: int = 0
    opus_bytes: int = 0


def _ogg_kind(info: FileInfo) -> str:
    return "opus" if info.path.suffix.lower() == ".opus" else "vorbis"


def packable(infos: list[FileInfo], the_plan: Plan,
             rates: Rates = DEFAULT_RATES) -> list[FileInfo]:
    """The files on this plan's store route that balrogg will be handed. The
    GUI's summary reads it so the card, the table and the bar agree."""
    stored, _ = _split(infos, the_plan)
    return _packable(stored, rates)


def _packable(stored: list[FileInfo], rates: Rates) -> list[FileInfo]:
    """Stored files balrogg will be handed: Ogg, within its size window."""
    if not rates.ogg_packed():
        return []
    return [i for i in stored if i.path.suffix.lower() in oggpack.SUFFIXES
            and oggpack.accepts(i.size)]


def _pack_ratio(info: FileInfo, effort: int) -> tuple[float, float, float]:
    """(low, expected, high) of the original size, at this effort."""
    low, expected, high = _PACK_RATIO[_ogg_kind(info)]
    share = _PACK_EFFORT_SAVING.get(effort, 1.0)
    return 1.0 - (1.0 - low) * share, 1.0 - (1.0 - expected) * share, high


def pack_cost(infos: list[FileInfo], the_plan: Plan,
              rates: Rates = DEFAULT_RATES) -> PackCost:
    """Seconds and bytes for the Ogg files balrogg will pack under this plan.

    The effort follows the profile (``oggpack.effort_for``), so the four rows
    of the comparison table differ for an Ogg folder, as they do in life.
    """
    stored, _ = _split(infos, the_plan)
    files = _packable(stored, rates)
    if not files:
        return PackCost()
    effort_time = _PACK_EFFORT_TIME.get(oggpack.effort_for(the_plan.profile), 0.27)
    encode = decode = 0.0
    by_kind = {"vorbis": 0, "opus": 0}
    for info in files:
        kind = _ogg_kind(info)
        by_kind[kind] += info.size
        encode += info.size * effort_time / _PACK_ENCODE_RATE[kind] + _PACK_PER_FILE_S
        decode += info.size / _PACK_DECODE_RATE
    return PackCost(bytes=sum(by_kind.values()), seconds=encode + decode,
                    verify_seconds=decode, vorbis_bytes=by_kind["vorbis"],
                    opus_bytes=by_kind["opus"])


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

    # K4's long-range window, on the optimistic end only.
    #
    # A floor rather than a computation: every ratio above is per-file, and no
    # per-file quantity can represent redundancy *between* files. See
    # `_ZSTD_LONG_RANGE_FLOOR` for the two ways the previous attempt - a
    # credit keyed on matching file sizes - got this wrong.

    # The floor stays **zstd-only**, and that is a measured trade rather than
    # an oversight.
    #
    # 7-Zip at mx9 uses a 256 MiB dictionary, which is a long-range window
    # under another name, and extending the floor to it did fix a synthetic
    # shape - 30 MiB of duplicate data 120 MiB apart, previously 7.56 points
    # below the low bound. But it also set `low` to 10% of the piped bytes for
    # **every** ordinary 7-Zip estimate, which is a far worse statement in the
    # common case than the miss it repaired in a rare one: it broke the
    # exactness of a uniform file's estimate, collapsed the distinction between
    # Normal's and Extreme's optimistic ends, and rendered a range wide enough
    # to push the populated Compress page from 415 to 447px against a 420px
    # guard.
    #
    # zstd keeps it because K4 turned long-range matching into a *deliberate*
    # feature of that chain with the window fitted to the input, so the
    # optimistic end genuinely has to reach for it. For 7-Zip the same saving
    # is incidental, and shape B is recorded as a known limitation instead.
    if piped and "zstd" in stages:
        low = min(low, piped_bytes * _ZSTD_LONG_RANGE_FLOOR)

    # Never negative, whatever the terms above did. An archive cannot be
    # smaller than nothing, and a bound that says otherwise is not
    # conservative - it is broken, and it renders as a nonsense number.
    low = max(0.0, low)

    # B13: stored Ogg audio is packed, so it is predicted rather than copied at
    # exactly 1.0. Its bytes come out of the exact base and go in as a range.
    packed = _packable(stored, rates)
    packed_bytes = sum(i.size for i in packed)
    for info in packed:
        p_low, p_expected, p_high = _pack_ratio(
            info, oggpack.effort_for(the_plan.profile))
        low += info.size * p_low
        expected += info.size * p_expected
        high += info.size * p_high

    base = stored_bytes - packed_bytes + overhead
    return SizeEstimate(
        low=int(base + low),
        expected=int(base + expected),
        high=int(base + high),
        stored_bytes=stored_bytes,
        piped_bytes=piped_bytes,
        overhead_bytes=overhead,
        upper_bound=has_precomp and bool(piped),
        packed_bytes=packed_bytes,
    )


def estimate_time(infos: list[FileInfo], the_plan: Plan,
                  rates: Rates = DEFAULT_RATES) -> TimeEstimate:
    """Predict the seconds the user will wait, with the two-rate model.

    Three terms since D9: stored bytes cost a disk copy, piped bytes cost the
    codec, and then the pre-publish self-test restores and re-hashes the whole
    archive. Leaving the third term out would make every estimate
    systematically low by the exact amount of the integrity guarantee.
    """
    stored, piped = _split(infos, the_plan)
    stored_bytes = sum(i.size for i in stored)
    piped_bytes = sum(i.size for i in piped)

    stages = _stages_of(the_plan)
    io_seconds = stored_bytes / rates.io_rate if rates.io_rate else 0.0
    cost = pack_cost(infos, the_plan, rates)
    compress_seconds, verify_seconds = time_split(stored_bytes, piped_bytes,
                                                  stages, rates, pack=cost)
    codec_seconds = compress_seconds - io_seconds - cost.seconds
    spread = max(1.0, rates.spread_for(stages))

    base = io_seconds + verify_seconds
    return TimeEstimate(
        low=base + codec_seconds / spread + cost.seconds / _PACK_SPREAD,
        expected=base + codec_seconds + cost.seconds,
        high=base + codec_seconds * spread + cost.seconds * _PACK_SPREAD,
    )


def time_split(stored_bytes: int, piped_bytes: int, stages: Sequence[str],
               rates: Rates = DEFAULT_RATES,
               pack: PackCost | None = None) -> tuple[float, float]:
    """(compress, verify) expected seconds for one job.

    ``pack`` (B13) adds the Ogg specialist's encode-and-prove time to the
    compress side and its decode time to the restore side.

    I11: the progress bar gives the D9 self-test its own share of the job, so
    the two halves of :func:`estimate_time` are exposed rather than summed.
    One formula serves both, so the bar and the comparison table can never
    disagree about how long the self-test takes.
    """
    io_seconds = stored_bytes / rates.io_rate if rates.io_rate else 0.0
    rate = rates.rate_for(stages)
    codec_seconds = piped_bytes / rate if rate else 0.0
    verify_rate = rates.verify_rate_for(stages)
    # B17: stored files are restored by a zip copy (`extract_stored`), not
    # through the chain, so only piped bytes pay the chain's restore rate.
    # Billing them all at the chain rate cost little at 7-Zip's 21 MB/s, but
    # at Insane's measured ~0.1 MB/s a 2 GB stored video beside 20 MB of text
    # was estimated at over four hours.
    verify_seconds = io_seconds + (piped_bytes / verify_rate if verify_rate else 0.0)
    if pack is not None:
        return (io_seconds + codec_seconds + pack.seconds,
                verify_seconds + pack.verify_seconds)
    return io_seconds + codec_seconds, verify_seconds


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
