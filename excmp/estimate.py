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

from . import jpeg, oggpack
from .analyzer import FileInfo
from .manifest import STORED_PREFIX
from .planner import (_PRECOMP_EXPANDABLE, Plan, Profile, image_format,
                      plan as make_plan, store_reason)
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
    # Fast is zstd level 12 since 2026-11-25 (it was 19, which measured 3.2 / 3.627 / 3.677 MB/s). Level 12 on the
    # codec alone, contended machine: 63.6 MB/s (Office zips), 104.7 (installers), 20.2 (Python source, the
    # slowest of three). The slowest is the rate: a job's time also holds per-file work, which this does not model.
    "zstd": 20.0e6,
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

# B20: expandable containers outside B5's PDF/Office types, which the planner
# now pipes by structure rather than by name. `precomp -cn -intense` then
# 7-Zip, file by file, 22 real files, every one restored (2026-10-16): NuGet
# 0.36-0.60, APPX 0.49-0.71, AAR 0.47-0.70, ODT/ODS 0.60-0.67, EPUB
# 0.67-0.89. EPUBs, mostly images, gain least. Under the Precomp ceiling
# `expected` is the worst file (0.888, an EPUB): B5's 0.55 would have put the
# "≤ X" under every EPUB measured. `low` is the best file.
_ZIP_CONTAINER_RATIO = (0.36, 0.89, 1.0)

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
    #: B19: will JPEGs be packed by lepton? ``None`` asks this machine, as above.
    jpeg_pack: bool | None = None

    def ogg_packed(self) -> bool:
        return oggpack.available() if self.ogg_pack is None else self.ogg_pack

    def jpeg_packed(self) -> bool:
        return jpeg.available() if self.jpeg_pack is None else self.jpeg_pack

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
    #: Original bytes a store-route specialist will pack: Ogg audio by balrogg
    #: (B13) and JPEGs by lepton (B19). They sit inside ``stored_bytes`` and
    #: are *predicted*, not exact like the rest of it.
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

#: A JPEG lepton refuses (CMYK, or a side over 16,386 px), which a chain with
#: Precomp pipes to packJPG (B19, 2026-10-16). `precomp -cn -intense` then
#: 7-Zip, file by file, on all 16 such files found in two corpora (14 design
#: files, 2 elsewhere), every one restored: 0.394 to 0.755 of the original.
#: `expected` is the worst file, rounded up, for the ceiling reason above.
#: `high` is 1.0: a file packJPG can't open passes through about as it was.
_JPEG_PRECOMP_RATIO = (0.39, 0.76, 1.0)

#: A piped GIF's `high` (B21, review). Over 1 KB, two of 88 recoded GIFs came
#: out bigger through `precomp -> 7z`, 1.176 and 1.254 of their size (noisy
#: frames whose LZW beat LZMA on the raw pixels), and a one-file job of the
#: worse one went 24.5% over a `high` of 1.0 through the engine. The disk
#: preflight books `high`. `expected` stays the probe's reading: a GIF that
#: grows is rare enough (90 KB of 36 MB) that pricing every GIF at 1.26 would
#: make Extreme's ceiling a lie about the folders that shrink 7-26%; a job of
#: only such GIFs can exceed "≤ X", as an MP3 packMP3 declines can.
_GIF_PRECOMP_HIGH = 1.26


def _piped_ratios(info: FileInfo, factor: float,
                  has_precomp: bool) -> tuple[float, float, float]:
    """(low, expected, high) ratio for one file the chain will process."""
    if has_precomp and info.path.suffix.lower() == ".mp3":
        return _MP3_PRECOMP_RATIO
    if has_precomp and info.lepton_refuses:
        return _JPEG_PRECOMP_RATIO
    if store_reason(info) is not None:
        # Piped only because the profile has Precomp - see _ZLIB_* above.
        if info.zlib_stream:
            return _ZLIB_LOW, _ZLIB_EXPECTED, _ZLIB_HIGH
        if (has_precomp and info.expandable
                and info.path.suffix.lower() not in _PRECOMP_EXPANDABLE):
            # B20's containers, which look random; B5's measured types keep
            # B5's figures below. A container whose bytes *don't* look random
            # falls through to its own samples (review, B20).
            return _ZIP_CONTAINER_RATIO
        if has_precomp and info.expandable:
            # Roughly half of the real PDF/Office corpus lands here: high
            # entropy, so `store_reason` would keep it, but the container
            # probe says Precomp can open it. Before B5 this returned
            # `sample_ratio_max` (~0.90) as `expected` and predicted no gain.
            return (_EXPANDABLE_LOW, _EXPANDABLE_EXPECTED, 1.0)
        if has_precomp and image_format(info) == "gif":
            return _OVERRIDE_LOW, info.sample_ratio_max, _GIF_PRECOMP_HIGH
        return _OVERRIDE_LOW, info.sample_ratio_max, 1.0

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
    if has_precomp and info.expandable:
        # Structurally known to hold an expandable deflate layer. The probe's
        # own reading of this file beats the entropy sample, which measured
        # 0.88-0.91 on exactly these files while the real chain took half:
        # so B5's figures cap the sample-based ones. This used to *replace*
        # them, which returned expected 0.55 beside a high of probe x 1.05,
        # an inverted range whenever the probe read under ~0.52, and put a
        # mostly-stored text .xpi's real 0.225 under `low` (review, B20).
        low = min(low, _EXPANDABLE_LOW)
        expected = min(expected, _EXPANDABLE_EXPECTED)
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


def _name_bytes(info: FileInfo) -> int:
    """The file's archive name in bytes: recorded by the analyzer when it
    knew the input root (B19d), else the basename, the old reading."""
    return info.arc_name_bytes or len(info.path.name.encode("utf-8"))


def _overhead(infos: list[FileInfo], stored: list[FileInfo]) -> int:
    """Manifest + zip headers. The manifest is deflated; everything else in the
    container is ZIP_STORED.

    **B19(d): each stored file's zip entry carries its full archive name
    twice** - `stored/<root>/<path>` in the local header and again in the
    central directory, uncompressed. This term used to add every file's
    *basename* once, piped files included (they have no entry of their own:
    they travel inside the payload). On anything but a flat folder that
    under-booked: 64 Takeout MOVs came out 3,173 B over a store-only estimate
    whose range has zero width, and a 4-deep synthetic tree 2,748 B over 12
    files. The disk preflight books this figure, so it may err high, never
    low.

    The manifest's ledger keys are the same archive names; there they are
    deflated, and `_MANIFEST_DEFLATE_FACTOR` covers them.
    """
    if not infos:
        return 0
    names = sum(_name_bytes(i) for i in infos)
    manifest = (_LEDGER_BYTES_PER_FILE * len(infos)
                + names)                             # ledger key
    member_names = sum(len(STORED_PREFIX) + _name_bytes(i) for i in stored)
    return (_CONTAINER_BASE
            + int(manifest * _MANIFEST_DEFLATE_FACTOR)
            + 2 * member_names                       # local + central header
            + _ZIP_ENTRY_BYTES * (len(stored) + 2))  # + manifest and payload


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

# Decode speed, both formats. The CLI per file said 1.5 MB/s (143.5 MB in
# 94 s; 26.4 MB in 18 s), but through the app D9 decodes slower: the B13
# music corpus (170 MB, 11 Vorbis, 2 .oga, 5 Opus) at Normal took 122, 181
# and 183 s on a quiet machine (2026-10-17; docs/benchmarks/
# 2026-10-17-quiet-remeasure.md), median 0.94 MB/s. Extract matched (0.88).
_PACK_DECODE_RATE = 0.94e6

# The same Vorbis files took 85 s and then 290 s at -9 an hour apart, so the
# range has to be at least that wide.
_PACK_SPREAD = 3.5

# Under a ceiling (review, B19). On a Precomp chain with anything piped,
# `expected` is shown as "≤ X" (B18), so a packer's share of it has to be its
# worst file measured, not its mean: a photo folder with one text file at
# Extreme came out 96,373 B over a ceiling that priced the JPEGs at their
# 0.79 corpus mean. B13 per file at -9: Vorbis 8.5-44.3% saved (worst
# 0.915), Opus 3.6-4.8% (worst 0.964). A row that isn't a ceiling keeps the
# best guess in `_PACK_RATIO`.
_PACK_CEILING = {"vorbis": 0.92, "opus": 0.97}


# -- B19: JPEGs packed by lepton ----------------------------------------------
#
# Every JPEG on the store route has been packed by lepton since B2, and until
# B19 the estimate billed it as an exact copy. End to end at Extreme
# (2026-10-16), every file restored, the whole range sat above the archive:
# +28.6% on 150 phone photos, +27.1% on 299 web images, +3.6% on a design
# folder that is mostly CMYK lepton refuses.
#
# Per file, lepton's output over the original on the files it took (466 of
# them, three corpora): byte-weighted 0.777 (phone), 0.784 (web), 0.666
# (design); file by file 0.36 to 0.97. With the files it declined counted at
# 1.0 the web corpus is 0.786. `expected` is that worst corpus, rounded up:
# the best guess for a row that says "about X". `low` sits under the best
# corpus. `high` is 1.0: lepton declines some progressive layouts the header
# can't reveal, and those are stored as-is.
_LEPTON_RATIO = (0.62, 0.79, 1.0)

# Under a ceiling ("≤ X", see _PACK_CEILING) the worst file instead: 0.966
# of 466. Real subsets beat the mean: phone photos over 2 MB 0.802, the nine
# Windows 4K wallpapers 0.808-0.829 per file (review).
_LEPTON_CEILING = 0.97

# Time. `jpeg.pack` compresses and then decompresses every file to prove it,
# and D9 decodes it once more. Bytes plus a per-file cost, fitted to the
# app's own phase times on two corpora, median of three quiet runs each
# (2026-10-17, at Fast: lepton has no effort): phone 49.1 MB / 150 files
# packed in 21.6 s and decoded in 13.3 s, web 20.4 MB / 299 files in 19.2 s
# and 14.1 s. The design folder's 24 photos (15.8 MB) then predict 5.9 s
# against 4.5-6.3 s measured. The contended priors these replace (2.3 MB/s
# + 0.04 s pack, 5.8 + 0.04 decode) sat within 30%; runs still swing (phone
# packed in 15.6-22.4 s the same night), so they keep _PACK_SPREAD's range.
_LEPTON_PACK_RATE = 3.25e6
_LEPTON_PER_FILE_S = 0.043
_LEPTON_DECODE_RATE = 6.2e6
_LEPTON_DECODE_PER_FILE_S = 0.036


# -- B19: Precomp's own recoders ----------------------------------------------
#
# Precomp recodes media itself on Extreme and Insane: MP3 with packMP3 (B18:
# every MP3 is piped) and JPEG with packJPG (B19: the ones lepton refuses),
# and PNG and GIF below (B21). Both are slower than the generic Precomp chain the model
# billed them at (1.41 MB/s compress, 6.5 MB/s self-test). The app's own
# phase times at Extreme, every file restored, three quiet runs on each of
# two corpora (2026-10-17; docs/benchmarks/2026-10-17-quiet-remeasure.md):
#
#     packJPG  compress 0.57-1.25 MB/s, median 1.03; self-test median 1.02
#              (design 151 MB, other CMYK 8 MB)
#     packMP3  compress 0.31-1.41 MB/s, median 1.18; self-test median 1.49
#              (music 34 MB, misc 80 MB)
#
# The contended priors these replace (packJPG 0.41 / 0.83, packMP3 0.35 /
# 0.72, from the afternoon of 2026-10-16 with WSL busy) were 2.5-3.4x slow
# on compress. The difference from the generic chain is added per byte on top
# of whatever Precomp chain runs, so Insane pays it too.
#
# B20 adds the containers it routes by structure (EPUB, AAR, NuGet, APPX...):
# expanding every member is Precomp's slow regime. The two AABs (121 MB) and
# a 36.8 MB ODT ran at 0.446 and 0.439 MB/s compress, 1.68 and 3.06 MB/s
# self-test, so the sample-based 0.46 / 1.5 stand. The 1-6 MB samples ran
# 0.08-0.51 MB/s on the quiet night, slower than the contended afternoon, and
# start-up doesn't explain it (a 64 KB ODT job takes ~2 s); the CPU log
# shows nothing beside the slow runs, so on samples that small the rate is
# noise.
#
# B21 adds PNG and GIF, which had no term at all: since B3 a PNG was billed at
# the generic 1.41 MB/s. Precomp expands each into raw pixels (a 1.4 KB PNG
# became a 704 KB .pcf) and 7-Zip then pays for the pixels. Three rounds at
# Extreme on each of two corpora per format, every file restored
# (2026-10-19; docs/benchmarks/2026-10-19-b21-stored-formats.md):
#
#     PNG  compress 0.187-0.218 MB/s, 0.21 over all six runs; self-test
#          0.58-1.37, 0.76 (8.2 MB from each drive, 70 and 80 files)
#     GIF  compress 0.275-0.334 MB/s on 30.0 MB (64 files), 0.61-0.92 on
#          6.0 MB (24); 0.34 over all six runs; self-test 2.40
#
# Rates are total bytes over total seconds: the two GIF corpora ran 2x apart
# and a median of six fell between them, under every run of the larger one.
# Not a quiet afternoon: another session's hooks held ~30-60% of the CPU on
# average per run (peaks 79%). The compress rates still agreed within ~20%
# on three of the four corpora; the least contended PNG run of an earlier
# set went 2x faster, which the low end holds. The cost follows pixels, not
# bytes, so a folder of small, large-canvas images runs slower than this.
_RECODE_RATE = {"jpeg": 1.03e6, "mp3": 1.18e6, "zip": 0.46e6,
                "png": 0.21e6, "gif": 0.34e6}
_RECODE_VERIFY_RATE = {"jpeg": 1.02e6, "mp3": 1.49e6, "zip": 1.5e6,
                       "png": 0.76e6, "gif": 2.40e6}

# How much slower than the quiet median a recoded file's time can run (the
# high side only; see estimate_time). B18's contended packMP3 run compressed
# at 0.30 MB/s, 4.0x under the median, and has to stay inside the range, as
# do B19's contended JPEG rows. Not every run fits: one B19 design run went
# at 0.09 MB/s beside GUI renders and tests, and two 6 MB container runs on
# the quiet night came out a few seconds over (record, 2026-10-17).
_RECODE_SPREAD = 4.0
_RECODE_BASE_RATE = 1.41e6          # _CODEC_RATE["precomp+sevenzip"]
_RECODE_BASE_VERIFY_RATE = 6.5e6    # _VERIFY_RATE["precomp+sevenzip"]

# B22: Insane (`precomp -cn -intense`, then zpaqfranz -m58) on the same kinds.
# Priced at the chain's one rate (0.091 MB/s compress, 0.107 self-test) plus the
# recoder's extra, it was 2-3x too high on JPEG (zpaqfranz runs ~3x faster on
# packJPG output than on Silesia) and MP3 (~2x), and 2.3-2.7x too low on PNG
# (Precomp expands ~50x into pixels, and zpaqfranz pays for every one).
# Eight corpora through engine.compress and engine.extract, every file
# restored, 24 valid rows (3 rounds each) (2026-11-16/17; docs/benchmarks/
# 2026-11-16-b22-insane-recoded.md). Each rate is the least-contended row of
# each corpus (others about 15% of the CPU or less, 4+ GB free), bytes over
# (compress incl. D9 - extract) and bytes over extract, byte-weighted over the
# two corpora of each kind (the unmodified figures, nothing taken out):
#
#     jpeg  CMYK 8 MB and design 135 MB: 0.2795 and 0.2767 -> 0.277;
#           self-test 0.3165 and 0.3118 -> 0.312
#     mp3   0.208 and 0.159 MB/s -> 0.171; self-test 0.228 and 0.219 -> 0.221
#     gif   0.1203 and 0.1209 MB/s -> 0.121; self-test 0.158 and 0.146 -> 0.148
#           (B24: round 3 of the 30 MB corpus ran 454 s on a quiet machine, others
#           5%; its earlier "quiet" row, 596 s at 6%, was not. The two corpora
#           agreed on the compress rate to 0.5% once it was in.)
#     png   total 0.0156 MB/s over both corpora, split 54:46 by the one corpus
#           whose self-test ran separate from its compress (png-dl1's extract
#           was as long as its whole compress+D9, so its split is unusable)
#
# These four kinds are priced by file size. The B20 containers are priced by
# what Precomp expands them to (B26, below).
_INSANE_RECODE_RATE = {"jpeg": 0.277e6, "mp3": 0.171e6, "gif": 0.121e6,
                       "png": 0.0289e6}
_INSANE_RECODE_VERIFY_RATE = {"jpeg": 0.312e6, "mp3": 0.221e6, "gif": 0.148e6,
                              "png": 0.0339e6}

# B26: the B20 containers at Insane (2026-11-19/20; docs/benchmarks/
# 2026-11-20-b26-insane-containers.md). Six corpora, 176.5 MB, 16 valid rows
# through engine.compress and engine.extract, every file restored. The chain's
# rate plus B20's extra held for five of the six; EPUB ran 3.5x over its
# expected and past its high. What predicts the time is not the file's size but
# what Precomp hands zpaqfranz: seconds per input MB ran 16 (AAB) to 80 (EPUB),
# per expanded MB only 4.4-7.2 (fastest rows).
#
# * Plain deflate content: the members' uncompressed size IS the `.pcf` (0.94-
#   1.00 of it on 13 of 14 files; the 14th, an AAR holding a nested jar, is
#   0.50 and is priced about 2x low), so its rate is bytes of
#   ``zip_deflated_bytes`` per second. Fitted on the four corpora with no PNG
#   worth the name, the fastest row of each, each row split by its own phase
#   events (the compress phase ends at the first `verify` event; the D9 phase
#   is the rest), byte-weighted:
#
#       corpus  deflated MB  compress  self-test      per corpus, MB/s
#       nupkg       4.00      16.6 s    12.0 s        0.241 / 0.332
#       appx       19.29      71.4 s    66.7 s        0.270 / 0.289
#       aar        16.17      65.0 s    44.4 s        0.249 / 0.364
#       aab       346.15     849.6 s   947.5 s        0.407 / 0.365
#
#   0.385 and 0.360 MB/s. **The AABs are 90% of the fit's deflated bytes** (68%
#   of all six corpora's input bytes), so this is the AABs' rate: the three
#   small corpora agree on compress within 12% and run 30-37% under it, and
#   sit 17-23% under their quiet rows here (expected over fastest 0.77-0.83).
#   The AABs are two apps from one
#   toolchain that share most of their expanded bytes (the per-file model
#   cannot see that). B22 split by `extract_s` instead; on the AAB row the D9
#   phase (990.6 s) is 20% longer than extract (827.8 s), on eight other rows
#   within 7%, so the totals agree and only the split moves (0.331 / 0.425).
# * PNG members are what a directory cannot size: Precomp expands each one's
#   own deflate into pixels, 6x (ODT) to 106x (an EPUB) per PNG byte. They are
#   priced as the PNGs they are, at B22's rates, which came from other
#   corpora, so the PNG rate itself is out of sample for EPUB (4.2 MB of PNG in
#   5.7) and ODT (33.8 MB in 36.8): 0.66x and 1.57x their fastest rows. The 1.7x
#   band and the ODT low-end pin in the tests were set after seeing those two:
#   a regression pin, not validation. A container's PNGs can sit 5x either side
#   of the one rate.
# * JPEG members (``zip_jpeg_bytes``) are priced at B22's JPEG rates times
#   ``_ZIP_JPEG_SLOWDOWN`` (B30, x1.45: two more JPEG containers ran 1.53-1.77x over the
#   plain rate). B26 first measured on ONE album of 23 stored photographs, 11.6 MB, 30.7% smaller, every file
#   restored: 91.4 s (compress 45.8 + D9 45.6) and 198.3 s (a contended round,
#   others 24%), against 79 s at the JPEG rates and 238 s at the chain's; so the
#   fastest row is 1.16x the model. (First priced at the chain's rate, which put
#   the low end above that row.) ODT holds 2.5 MB of JPEG, EPUB 0.9 MB.
# * Everything else (GIF members, stored members, other methods:
#   ``zip_other_bytes``) is priced at the chain's own Insane rate, unmeasured,
#   so the safe way round.
_INSANE_ZIP_RATE = 0.385e6
_INSANE_ZIP_VERIFY_RATE = 0.360e6
# How far under the model the self-test of a container's PNG members can run
# (the low end only; the high end already has _RECODE_SPREAD). The ODT, the
# least expanding PNG container measured, ran at 1/1.6 of it.
_ZIP_PNG_VERIFY_LOW = 1.6

# B28: a member that is itself an archive (a `.jar` inside a `.war`) is a deflate container whose OWN
# streams Precomp expands again, so a nested byte costs several plain deflated ones. Fitted on TWO
# corpora, fastest of two rounds each (compress + D9), against the plain rate's 5.38 s/MB (compress +
# self-test): B27's `.war` (3 files, 16.9 MB, 99% nested jars, 18.03 MB of nested members) 300 s -> 3.05;
# the synthetic nested corpus (one 10.1 MB zip, 16.2 MB of nested members) 242 s -> 2.75. 3.0 puts both
# inside their ranges. (The `.war`'s first round read 512 s -> 5.3: the machine slept 6.9 h through it,
# its extract took 277 s against 96 s on round 2, and the fit built on it was wrong.) Only a container
# priced by its counts (zip kind) carries nested bytes; `.zip`, `.jar`, `.apk`, `.xlsx`, `.pptx` and a
# docx with little PNG keep the chain rate (`_recode_kind`; a PNG-dominant `.docx` is lifted by B29), so this reaches `.war`, `.ear`, `.aar`, `.nupkg`, `.whl` and
# other zips under another name. A third corpus (B30: four zips, 45.6 MB nested, copied as `.war`) ran
# 2,373 s against 2,154 s expected at 3.0 (1.10x): the factor stands. Record: docs/benchmarks/2026-11-21-b27-b5-types.md.
_NESTED_FACTOR = 3.0


# The signed extras are measured against these fixed constants, never against
# the machine's calibrated rates: the summary builds them with the defaults and
# the progress bar adds them to the calibrated chain's time, so a rate-relative
# extra went negative (10 MB of CMYK after a text job taught Insane 0.16 MB/s:
# -11.5 s compress, -11.6 s self-test, against 67.7 s in the table).
# ``time_split`` takes the own-rated bytes out of the chain's term and puts
# them back at these constants.
_INSANE_BASE_RATE = _CODEC_RATE["precomp+zpaqfranz"]
_INSANE_BASE_VERIFY_RATE = _VERIFY_RATE["precomp+zpaqfranz"]


def _insane_chain(stages: Sequence[str]) -> bool:
    return "precomp" in stages and "zpaqfranz" in stages


# B22: what a job costs before it moves a byte. Medians of three runs of a
# 2 KB file and of twenty 4 KB files through engine.compress (D9 included),
# 2026-11-17, 0 mismatches in 30 runs (the contention log covers only the
# first run, others 9%; the logger was reaped after it, so the rest are
# unlogged, on a machine that had 6.5 GB free at the start):
#
#     Fast 0.5/1.0 s, Normal 0.7/1.0, Extreme 1.3/1.2, Insane 3.8/2.7
#     the B21 6 MB GIF folder stored (nothing to pipe): Fast 1.0, Normal 0.8
#
# so about a second, and two at Insane (zpaqfranz allocates before it
# starts). Insane's two cells disagree (3.8 s and 2.7 s) and the second holds
# ~1.7 s that the chain's own rates already bill for its 80 KB, so 2.0 s is
# the figure that keeps all six Insane runs (1.1-5.2 s) inside the range. The
# first run after idle is the slow one (2.4 s at Fast, 5.2 at Insane against
# 0.5 and 1.1 for the next two), which the 3x high margin holds.
# Not a 10-50 s cost: the handoff's stored-GIF folders at 17-20 s did not
# reproduce (1.0 s here), so whatever made those runs slow was not the job.
_JOB_FIXED_SECONDS = 1.0
_JOB_FIXED_SECONDS_INSANE = 2.0
_JOB_FIXED_RANGE = (0.3, 3.0)           # of the figure: low and high margins


def job_fixed_seconds(stages: Sequence[str]) -> float:
    return _JOB_FIXED_SECONDS_INSANE if "zpaqfranz" in stages else _JOB_FIXED_SECONDS


# What a job costs per FILE, whatever the file holds: (compress side, D9
# self-test), in seconds. The rates above are bytes per second and were fitted
# on big files, so a tree of small ones was promised the codec's time and
# nothing else: 1,801 Python files (43 MB) at Fast were quoted 14.1 s and took
# 44.1 s, 4.6x over and on the unsafe side (2026-11-25).
#
# Where it goes, measured on the i5-7200U with real-time protection on
# (docs/benchmarks/2026-11-25-small-files.md has the runs):
#
# * compress side: every file is opened to be analysed and again to be
#   archived (about 1-2 ms an open, before any byte is read), and sampled;
# * self-test: every file is created again by the restore, and then opened
#   to be hashed - and the FIRST open of a file that has just been written
#   waits on the scanner: 15-19 ms a file one at a time, against 0.3 ms for a
#   second open. That one wait is most of the term, which is why it is its own
#   term and not a slower byte rate: it does not grow with the file.
#
# One pair for every chain: 8.7 ms a file, the median residual (measured
# median minus the byte terms, over the files past _PER_FILE_FREE) of eight
# cells, Fast and Normal on four trees of 307 to 3,912 files: 8.9, 6.4, 8.8,
# 10.8, 7.9, 6.4, 9.1 and 8.7 ms. Split 3.0 / 5.7 by where the time was seen.
# Extreme was checked against it, not fitted (three trees, 0.6-0.9x of the
# figure when quiet). Insane was not: 307 files took 259 and 343 s, which is
# zpaqfranz and not this term. Trees of mid-sized stored files run over it
# (238 PNG/GIF: 5.2 s against 3.9; 150 photos with lepton off: 5.9 against
# 3.1), because analysis samples up to 1 MiB of each; the range holds them.
#
# The range is wide on purpose. The low end is a machine with scanning off
# (the opens alone); the high end holds every run in the record, taken beside
# another job on the same two cores. Files a store-route specialist packs
# (lepton, balrogg) are left out: their own per-file constants were fitted on
# whole jobs and already hold this.
_PER_FILE_SECONDS = (0.003, 0.0057)
_PER_FILE_RANGE = (0.3, 2.5)             # of the figure: low and high margins
# The job's fixed second (B22, above) was fitted on jobs of 1, 20 and 24
# files - Fast took 0.5 s for one file and 1.0 s for twenty - so it already
# holds the per-file cost of a job that size. Charging those files again
# would move every figure B22 measured; only the files past them are charged.
_PER_FILE_FREE = 24


def per_file_seconds(files: int) -> tuple[float, float]:
    """(compress, self-test) seconds that ``files`` files cost by being
    files. See `_PER_FILE_SECONDS`."""
    files = max(0, int(files) - _PER_FILE_FREE)
    return files * _PER_FILE_SECONDS[0], files * _PER_FILE_SECONDS[1]


@dataclass(frozen=True)
class RecodeCost:
    """Seconds a Precomp chain spends recoding media, beyond its own rate.

    The extras are signed: at Insane the recoder can be faster than the chain
    (packJPG output under zpaqfranz), and ``time_split`` adds them to the
    chain's own time for the same bytes, so the sum is the measured time.
    ``own_*`` is the part billed at Insane's per-kind rates in full (B22): its
    bytes, and the seconds they take, compress and self-test.
    """

    bytes: int = 0
    compress_seconds: float = 0.0
    verify_seconds: float = 0.0
    own_bytes: int = 0
    own_compress_seconds: float = 0.0
    own_verify_seconds: float = 0.0
    #: B26: the self-test seconds of PNG members inside zip containers, which
    #: ``estimate_time`` lets the low end undercut (`_ZIP_PNG_VERIFY_LOW`).
    zip_png_verify_seconds: float = 0.0


#: B30: a JPEG *inside* a container is slower than the same JPEG as a file (the unzip and the re-zip
#: come on top of the recoder). B26 priced it at the file's rate on one album; two more JPEG-dominant
#: containers ran 1.77x (a second album) and 1.53x (six JPEG EPUBs) over that, and a JPEG-heavy .pptx
#: corpus 1.41x. 1.45 is the least-squares fit (in the log) over the three pure-JPEG corpora, so the
#: three read 0.78x, 1.23x and 1.09x: a regression pin, not validation. Plain JPEG files keep B22's
#: rate. Record: docs/benchmarks/2026-11-21-b27-b5-types.md, last section.
_ZIP_JPEG_SLOWDOWN = 1.45


def _insane_own_seconds(kind: str, info: FileInfo) -> tuple[float, float] | None:
    """(compress, self-test) seconds Insane spends on this file by its own
    measured rates, or None where it has none and the chain's rate applies.

    B26: a zip container is priced by what Precomp hands zpaqfranz, not by its
    own size - 3x the size for plain deflate content, 6-18x for one full of
    PNGs (EPUB, ODT). The directory gives the deflated members' size; the PNG
    members are priced as the PNGs they are and the JPEG members as JPEGs
    (B22); whatever else the container holds is priced at the chain's rate. A
    container the probe did not read (a hand-built FileInfo) has no counts:
    None.
    """
    if kind == "zip":
        deflated, png, jpeg, other = (info.zip_deflated_bytes, info.zip_png_bytes,
                                      info.zip_jpeg_bytes, info.zip_other_bytes)
        if not (deflated or png or jpeg or other or info.zip_nested_bytes):
            return None
        # B28: archives inside the archive count as several plain deflated bytes each.
        deflated += _NESTED_FACTOR * info.zip_nested_bytes
        return (deflated / _INSANE_ZIP_RATE + png / _INSANE_RECODE_RATE["png"]
                + jpeg * _ZIP_JPEG_SLOWDOWN / _INSANE_RECODE_RATE["jpeg"] + other / _INSANE_BASE_RATE,
                deflated / _INSANE_ZIP_VERIFY_RATE
                + png / _INSANE_RECODE_VERIFY_RATE["png"]
                + jpeg * _ZIP_JPEG_SLOWDOWN / _INSANE_RECODE_VERIFY_RATE["jpeg"]
                + other / _INSANE_BASE_VERIFY_RATE)
    if kind in _INSANE_RECODE_RATE:
        return (info.size / _INSANE_RECODE_RATE[kind],
                info.size / _INSANE_RECODE_VERIFY_RATE[kind])
    return None


#: B5's types whose TIME stays at the chain's rate at Insane. ``.docx`` leaves it only when PNG-dominant
#: (B29): two independent corpora, 73% and 90% PNG by bytes, ran 2.84x and 2.01x over the chain model's
#: expected (4,632 s and 1,794 s) and 0.97x and 0.78x of the container model's. A docx with little PNG
#: has no evidence behind the container price (the JPEG-in-zip rate, B30's x1.45, rests on three JPEG
#: containers, none a docx, and the JPEG-heavy .pptx corpora disagree 2.5-3x), so it keeps the chain rate. ``.xlsx`` and ``.pptx``
#: stay: one corpus each, and the container model is no better for them. The planner's piping and the
#: SIZE ratio still use ``_PRECOMP_EXPANDABLE``, which this does not change.
_CHAIN_RATE_TIME_TYPES = _PRECOMP_EXPANDABLE
_DOCX_PNG_SHARE = 0.5          # PNG bytes / file size from which a docx is priced by its counts


def _priced_by_counts(info: FileInfo, insane: bool) -> bool:
    if info.path.suffix.lower() == ".docx":
        # Only at Insane: B5 measured .docx at Extreme, and that figure stands.
        return insane and info.zip_png_bytes >= _DOCX_PNG_SHARE * info.size
    return info.path.suffix.lower() not in _CHAIN_RATE_TIME_TYPES


def _recode_kind(info: FileInfo, insane: bool = False) -> str | None:
    if info.lepton_refuses:
        return "jpeg"
    if (fmt := image_format(info)) in ("png", "gif"):
        return fmt          # B21: by content, as the planner routes them
    if info.path.suffix.lower() == ".mp3":
        return "mp3"
    if info.expandable and _priced_by_counts(info, insane):
        return "zip"        # B20's containers, and (B29) a PNG-dominant .docx; the other B5 types keep the chain rate
    return None


def recode_cost(infos: list[FileInfo], the_plan: Plan,
                rates: Rates = DEFAULT_RATES) -> RecodeCost:
    """The extra time Precomp's recoders add to this plan's piped files.
    Nothing without Precomp: the chain then never touches them."""
    stages = _stages_of(the_plan)
    if "precomp" not in stages:
        return RecodeCost()
    _, piped = _split(infos, the_plan)
    insane = _insane_chain(stages)
    total = own_bytes = 0
    compress = verify = own_c = own_v = png_v = 0.0
    for info in piped:
        kind = _recode_kind(info, insane)
        if kind is None:
            continue
        total += info.size
        own = _insane_own_seconds(kind, info) if insane else None
        if own is not None:
            # B22: billed at its own measured rate, in place of the chain's.
            c, v = own
            if kind == "zip":
                png_v += info.zip_png_bytes / _INSANE_RECODE_VERIFY_RATE["png"]
            own_bytes += info.size
            own_c += c
            own_v += v
            compress += c - info.size / _INSANE_BASE_RATE
            verify += v - info.size / _INSANE_BASE_VERIFY_RATE
            continue
        compress += info.size * (1 / _RECODE_RATE[kind] - 1 / _RECODE_BASE_RATE)
        verify += info.size * (1 / _RECODE_VERIFY_RATE[kind]
                               - 1 / _RECODE_BASE_VERIFY_RATE)
    if not own_bytes:           # nothing here can be negative: the old floor
        compress, verify = max(0.0, compress), max(0.0, verify)
    return RecodeCost(bytes=total, compress_seconds=compress, verify_seconds=verify,
                      own_bytes=own_bytes, own_compress_seconds=own_c,
                      own_verify_seconds=own_v, zip_png_verify_seconds=png_v)


def recoded_seconds(recode: RecodeCost, stages: Sequence[str],
                    rates: Rates = DEFAULT_RATES) -> tuple[float, float]:
    """(compress, self-test) seconds the recoded files take on this chain.

    `RecodeCost` holds only what the recoders add beyond the chain's rate;
    this puts the chain's own share of those bytes back, because the recoder
    sets the pace for all of it. At the measured rates the extra alone is a
    fraction of the job (50 MB of CMYK: 13 s of about 98 s), so anything that
    asks "how long do these files take" has to read this instead.

    The chain's share is capped at the generic Precomp chain's rate, which is
    what the recoders were measured beside. Insane's zpaqfranz is slower than
    that on every byte, and the excess is zpaqfranz's own time, not the
    recoder's (review: 95% of an Insane "recode" was zpaqfranz).
    """
    rate, verify_rate = rates.rate_for(stages), rates.verify_rate_for(stages)
    # B22: the bytes billed at Insane's own per-kind rates are those files'
    # whole time, so the chain's share and the signed extras that were
    # computed against it come out and the own seconds go in.
    rest = recode.bytes - recode.own_bytes
    chain_c = recode.own_bytes / _INSANE_BASE_RATE
    chain_v = recode.own_bytes / _INSANE_BASE_VERIFY_RATE
    compress = rest / max(rate, _RECODE_BASE_RATE) if rate else 0.0
    verify = rest / max(verify_rate, _RECODE_BASE_VERIFY_RATE) if verify_rate else 0.0
    return (compress + (recode.compress_seconds - (recode.own_compress_seconds - chain_c))
            + recode.own_compress_seconds,
            verify + (recode.verify_seconds - (recode.own_verify_seconds - chain_v))
            + recode.own_verify_seconds)


@dataclass(frozen=True)
class PackCost:
    """What packing the store route's files will cost: Ogg audio (balrogg,
    B13) and JPEGs (lepton, B19)."""

    bytes: int = 0
    #: Compress side: every file is encoded, then decoded once to prove it.
    seconds: float = 0.0
    #: D9's restore decodes every packed entry again before publishing.
    verify_seconds: float = 0.0
    vorbis_bytes: int = 0
    opus_bytes: int = 0
    jpeg_bytes: int = 0
    #: How many files this prices. Their per-file time is in ``seconds``
    #: already, so `per_file_seconds` is not charged for them again.
    files: int = 0


def _ogg_kind(info: FileInfo) -> str:
    return "opus" if info.path.suffix.lower() == ".opus" else "vorbis"


def packable(infos: list[FileInfo], the_plan: Plan,
             rates: Rates = DEFAULT_RATES) -> list[FileInfo]:
    """The files on this plan's store route that a specialist will pack:
    balrogg's Ogg and lepton's JPEGs. The GUI's summary reads it so the card,
    the table and the bar agree."""
    stored, _ = _split(infos, the_plan)
    return _packable(stored, rates) + _lepton_packable(stored, rates)


def _packable(stored: list[FileInfo], rates: Rates) -> list[FileInfo]:
    """Stored files balrogg will be handed: Ogg, within its size window. Not
    a JPEG under an Ogg name: the store route claims by content and lepton
    comes first, so pricing it here too counted it twice (review, B19)."""
    if not rates.ogg_packed():
        return []
    return [i for i in stored if i.path.suffix.lower() in oggpack.SUFFIXES
            and oggpack.accepts(i.size) and not i.is_jpeg]


def _lepton_packable(stored: list[FileInfo], rates: Rates) -> list[FileInfo]:
    """Stored files lepton will be handed and can be expected to take: a JPEG
    by its content (as the store route claims it), big enough for `jpeg.pack`
    to try, and not one its frame header says lepton refuses."""
    if not rates.jpeg_packed():
        return []
    return [i for i in stored if i.is_jpeg and not i.lepton_refuses
            and i.size >= jpeg.MIN_SIZE]


def _pack_ratio(info: FileInfo, effort: int,
                ceiling: bool = False) -> tuple[float, float, float]:
    """(low, expected, high) of the original size, at this effort. With
    ``ceiling`` the expected figure is the worst file (_PACK_CEILING)."""
    low, expected, high = _PACK_RATIO[_ogg_kind(info)]
    if ceiling:
        expected = _PACK_CEILING[_ogg_kind(info)]
    share = _PACK_EFFORT_SAVING.get(effort, 1.0)
    return 1.0 - (1.0 - low) * share, 1.0 - (1.0 - expected) * share, high


def pack_cost(infos: list[FileInfo], the_plan: Plan,
              rates: Rates = DEFAULT_RATES) -> PackCost:
    """Seconds and bytes for the files the store route's specialists will
    pack under this plan: Ogg (balrogg) and JPEG (lepton).

    balrogg's effort follows the profile (``oggpack.effort_for``), so the four
    rows of the comparison table differ for an Ogg folder, as they do in life.
    Lepton has no effort setting.
    """
    stored, _ = _split(infos, the_plan)
    files = _packable(stored, rates)
    photos = _lepton_packable(stored, rates)
    if not files and not photos:
        return PackCost()
    encode = decode = 0.0
    by_kind = {"vorbis": 0, "opus": 0}
    if files:
        effort_time = _PACK_EFFORT_TIME.get(oggpack.effort_for(the_plan.profile), 0.27)
        for info in files:
            kind = _ogg_kind(info)
            by_kind[kind] += info.size
            encode += info.size * effort_time / _PACK_ENCODE_RATE[kind] + _PACK_PER_FILE_S
            decode += info.size / _PACK_DECODE_RATE
    # Lepton's pack time already includes the decode that proves each file
    # (`jpeg.pack`), so it is not added twice the way balrogg's is.
    jpeg_bytes = sum(i.size for i in photos)
    jpeg_pack = jpeg_bytes / _LEPTON_PACK_RATE + len(photos) * _LEPTON_PER_FILE_S
    jpeg_decode = (jpeg_bytes / _LEPTON_DECODE_RATE
                   + len(photos) * _LEPTON_DECODE_PER_FILE_S)
    return PackCost(bytes=sum(by_kind.values()) + jpeg_bytes,
                    seconds=encode + decode + jpeg_pack,
                    verify_seconds=decode + jpeg_decode,
                    vorbis_bytes=by_kind["vorbis"], opus_bytes=by_kind["opus"],
                    jpeg_bytes=jpeg_bytes, files=len(files) + len(photos))


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
    overhead = _overhead(infos, stored)

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
    # A Precomp chain with anything piped shows `expected` as a ceiling, so
    # the packers below price at their worst file there (review, B19).
    upper_bound = has_precomp and bool(piped)
    packed = _packable(stored, rates)
    packed_bytes = sum(i.size for i in packed)
    for info in packed:
        p_low, p_expected, p_high = _pack_ratio(
            info, oggpack.effort_for(the_plan.profile), ceiling=upper_bound)
        low += info.size * p_low
        expected += info.size * p_expected
        high += info.size * p_high

    # B19: and so are stored JPEGs, by lepton - the same move.
    photos = _lepton_packable(stored, rates)
    packed_bytes += sum(i.size for i in photos)
    j_expected = _LEPTON_CEILING if upper_bound else _LEPTON_RATIO[1]
    for info in photos:
        low += info.size * _LEPTON_RATIO[0]
        expected += info.size * j_expected
        high += info.size * _LEPTON_RATIO[2]

    base = stored_bytes - packed_bytes + overhead
    return SizeEstimate(
        low=int(base + low),
        expected=int(base + expected),
        high=int(base + high),
        stored_bytes=stored_bytes,
        piped_bytes=piped_bytes,
        overhead_bytes=overhead,
        upper_bound=upper_bound,
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
    recode = recode_cost(infos, the_plan, rates)
    files = len(infos) - cost.files
    compress_seconds, verify_seconds = time_split(stored_bytes, piped_bytes,
                                                  stages, rates, pack=cost,
                                                  recode=recode, files=files)
    # B22: the setup cost is not throughput, so it stays out of the codec
    # term the spread multiplies and gets its own, smaller margins. The
    # per-file cost is not throughput either, and has its own margins too.
    in_split = job_fixed_seconds(stages)
    per_file_compress, per_file_verify = per_file_seconds(files)
    per_file = per_file_compress + per_file_verify
    codec_seconds = (compress_seconds - io_seconds - cost.seconds - in_split
                     - per_file_compress)
    fixed = in_split if infos else 0.0          # no files, no job: nothing to wait for
    spread = max(1.0, rates.spread_for(stages))

    base = io_seconds + verify_seconds - per_file_verify
    # The time the recoders pace, compress and self-test, swings by
    # _RECODE_SPREAD on the slow side (2026-10-17). Only that side: the
    # priors are quiet medians, and contention only slows a job down, so the
    # low end stays the chain's (review: a symmetric spread put the design
    # folder's low at 71.5 s, its fastest run took 279 s).
    paced_compress, paced_verify = recoded_seconds(recode, stages, rates)
    # B26: a PNG inside a container expands 6x (an ODT) to 106x (an EPUB) per
    # byte and one rate prices them all, so its self-test can run well under
    # the figure: the ODT's ran at 0.63x of it (665 s against 1,057 s).
    png_cut = recode.zip_png_verify_seconds * (1 - 1 / _ZIP_PNG_VERIFY_LOW)
    return TimeEstimate(
        low=(base + codec_seconds / spread + cost.seconds / _PACK_SPREAD
             + fixed * _JOB_FIXED_RANGE[0] + per_file * _PER_FILE_RANGE[0]
             - png_cut),
        expected=base + codec_seconds + cost.seconds + fixed + per_file,
        high=(base - paced_verify + (codec_seconds - paced_compress) * spread
              + (paced_compress + paced_verify) * _RECODE_SPREAD
              + cost.seconds * _PACK_SPREAD + fixed * _JOB_FIXED_RANGE[1]
              + per_file * _PER_FILE_RANGE[1]),
    )


def time_split(stored_bytes: int, piped_bytes: int, stages: Sequence[str],
               rates: Rates = DEFAULT_RATES,
               pack: PackCost | None = None,
               recode: RecodeCost | None = None,
               files: int = 0) -> tuple[float, float]:
    """(compress, verify) expected seconds for one job.

    ``files`` is how many files the job holds that no specialist packs; each
    costs `per_file_seconds` on both sides, whatever its size. Left at 0 the
    answer is the byte terms alone, as it was before that term existed.

    ``pack`` (B13) adds the store-route specialists' encode-and-prove time to
    the compress side and their decode time to the restore side. ``recode``
    (B19) adds what Precomp's own MP3 and JPEG recoders cost beyond the
    chain's rate, on both sides.

    I11: the progress bar gives the D9 self-test its own share of the job, so
    the two halves of :func:`estimate_time` are exposed rather than summed.
    One formula serves both, so the bar and the comparison table can never
    disagree about how long the self-test takes.
    """
    io_seconds = stored_bytes / rates.io_rate if rates.io_rate else 0.0
    rate = rates.rate_for(stages)
    # B22: bytes Insane prices at their own measured rates leave the chain's
    # term and come back at the fixed constants the signed extras were made
    # against, so a learned chain rate moves everything but them.
    own = recode.own_bytes if recode is not None else 0
    codec_seconds = (piped_bytes - own) / rate if rate else 0.0
    verify_rate = rates.verify_rate_for(stages)
    # B17: stored files are restored by a zip copy (`extract_stored`), not
    # through the chain, so only piped bytes pay the chain's restore rate.
    # Billing them all at the chain rate cost little at 7-Zip's 21 MB/s, but
    # at Insane's measured ~0.1 MB/s a 2 GB stored video beside 20 MB of text
    # was estimated at over four hours.
    verify_seconds = io_seconds + ((piped_bytes - own) / verify_rate
                                   if verify_rate else 0.0)
    if recode is not None:
        codec_seconds += recode.compress_seconds + own / _INSANE_BASE_RATE
        verify_seconds += recode.verify_seconds + own / _INSANE_BASE_VERIFY_RATE
    codec_seconds += job_fixed_seconds(stages)
    per_file_compress, per_file_verify = per_file_seconds(files)
    codec_seconds += per_file_compress
    verify_seconds += per_file_verify
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
