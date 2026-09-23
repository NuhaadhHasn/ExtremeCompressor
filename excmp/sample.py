"""I6: pick the slice of an input that a preset comparison actually measures.

Running every profile over a 6 GB folder to find out which one to use costs
more than the job it is advising on, so the comparison runs on a sample. That
makes the *choice of sample* the honest part of the feature: the number it
produces is a measurement, and a measurement of the wrong bytes is worse than
the estimate it replaces, because it arrives with a measurement's authority.

Four rules, and each one is a test in ``tests/test_sample.py``:

1. **Whole files, never a prefix.** A truncated file does not compress like the
   file - its deflate streams are cut mid-stream, its tail dictionary never
   forms - and the point of I6 is to run what the real job would run.
2. **Every category that is in the input is in the sample.** On the real
   Programs corpus **41.9%** of the bytes route to ``store`` and contribute at
   exactly 1.0; a sample that dropped them would report a ratio no run of the
   real job can reproduce.
3. **Proportional to bytes, not to file count.** One 4 GB video and 900 text
   files is a video job. Counting files would call it a text job.
4. **Across the size distribution, not one end of it.** Filling a budget in
   ascending size order buys the smallest files, descending buys one big one;
   both measure a corner. :func:`_spread` walks the median first, then the
   quartiles, so a budget that runs out early has still seen the range.

What this module deliberately does **not** do is decide that a sample is good
enough. When a category will not fit under the cap at all it is named in
:attr:`Sample.missing_categories` and the caller discloses it, because a
silently truncated measurement reads exactly like a complete one.

**Rule 3 cannot always be honoured, and that is the important part.** Measured
on the real Programs corpus (29 files, 4.99 GB) the sampler picks 13 files /
55.7 MB under the 100 MB cap, and its composition drifts badly:

    executable          input 48.5%  ->  sample 60.6%
    compressed_archive  input 42.4%  ->  sample  3.9%
    binary              input  9.1%  ->  sample 35.5%

Not a bug in the fill: that corpus keeps 2.1 GB of `.zip`/`.rar` in a handful
of files that are each larger than the entire cap, so no whole-file subset can
carry 42.4% of the sample. Forcing the proportions would mean scaling every
other category down to that category's 5% fill rate and measuring 5 MB, which
trades a known bias for a worthless sample.

So the bias is **reported**, in :attr:`Sample.under_represented`, and the
consequence is a scoping decision the caller has to respect: a measured
comparison **ranks the profiles against each other on identical bytes**; it
does not predict the final size of the whole job. The estimate columns still
do that. Those two claims are not the same claim and the UI must not merge
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from .analyzer import Category, FileInfo
from .planner import Profile

#: The roadmap's cap for I6, as it is written there: 100 MB, decimal. Note
#: that `gui.format.fmt_size` reports in binary MiB under an "MB" label, so
#: a full sample displays as 95.4 MB. The cap is the budget, not the caption.
DEFAULT_SAMPLE_BYTES = 100_000_000


@dataclass(frozen=True)
class MeasuredRun:
    """What one profile actually did to the sample.

    Deliberately not a prediction and deliberately not comparable with a
    :class:`~excmp.estimate.SizeEstimate`: the estimate is about the whole
    input, this is about the bytes that were really run. The only claim it
    supports is the one the sample can carry - how the profiles rank against
    each other on identical data.
    """

    profile: Profile
    orig_bytes: int
    final_bytes: int
    elapsed_s: float = 0.0
    #: The engine verifies every archive before publishing it, so this is
    #: True for any run that produced one. It is carried anyway, because a
    #: measured number from an unverified archive must never reach a card.
    verified: bool = True

    @property
    def saved_fraction(self) -> float:
        if self.orig_bytes <= 0:
            return 0.0
        return max(0.0, 1.0 - self.final_bytes / self.orig_bytes)


@dataclass(frozen=True)
class Sample:
    """The chosen subset, plus everything a caption needs to be honest."""

    files: tuple[FileInfo, ...]
    cap_bytes: int
    source_files: int
    source_bytes: int
    #: Categories present in the input whose smallest file does not fit under
    #: the cap. Never silently empty - see the module docstring.
    missing_categories: tuple[Category, ...] = ()
    #: Categories that made it into the sample but carry less than half the
    #: share of it that they carry of the input. Measured at 3.9%-against-42.4%
    #: on the real Programs corpus, so this is the common case, not the corner.
    under_represented: tuple[Category, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def is_whole_input(self) -> bool:
        """True when nothing was left out, so "sample" is a formality and the
        measurement is of the job itself."""
        return len(self.files) == self.source_files

    @property
    def over_cap(self) -> bool:
        """True when honouring the cap would have meant truncating a file.

        The cap loses; the caller warns. One 4 GB ISO is a legitimate input
        and half of it is not a measurement of anything.
        """
        return self.total_bytes > self.cap_bytes

    @property
    def fraction(self) -> float:
        """Share of the input's bytes this sample carries. 1.0 when empty, so
        a caller formatting a percentage never divides by zero."""
        if not self.source_bytes:
            return 1.0
        return self.total_bytes / self.source_bytes


def _spread(items: Sequence[FileInfo]) -> Iterator[FileInfo]:
    """Yield ``items`` median-first, then quartiles, then eighths.

    ``items`` is expected sorted by size. A breadth-first bisection means the
    first few yields already span the distribution, so a budget that stops
    after three files has still seen a small, a middling and a large one.
    """
    ranges = [(0, len(items))]
    while ranges:
        nxt: list[tuple[int, int]] = []
        for lo, hi in ranges:
            if lo >= hi:
                continue
            mid = (lo + hi) // 2
            yield items[mid]
            nxt.append((lo, mid))
            nxt.append((mid + 1, hi))
        ranges = nxt


#: A file holding at least this share of its category's bytes is taken before
#: the spread runs. See :func:`_fill`.
_DOMINANT_SHARE = 0.25


def _fill(candidates: Iterable[FileInfo], budget: int, taken: set[int],
          pool_bytes: int = 0) -> tuple[list[FileInfo], int]:
    """Take whatever fits, spread-first — but never let crumbs block the loaf.

    A plain greedy walk of :func:`_spread` fills the budget from the middle of
    the size distribution outwards, and a single dominant file is the last
    thing it reaches. Measured on the shipped 100 MB cap with
    ``setup.exe 95,000,000 B`` beside forty 300,000 B DLLs, that spent
    **13,600,000 B of the cap and omitted the file that was 89% of the data** —
    a sample of an installer that contains no installer.

    So a file carrying at least ``_DOMINANT_SHARE`` of ``pool_bytes`` is taken
    first if it fits. The threshold matters: taking the largest file
    unconditionally would defeat rule 4, and does — on a 100-file 100 KB–10 MB
    spread it collapses a three-file sample to two.

    ``taken`` holds ``id()`` of files already chosen, so the leftover pass
    cannot buy the same file twice.
    """
    chosen: list[FileInfo] = []
    spent = 0
    free = [c for c in candidates if id(c) not in taken]

    if pool_bytes > 0:
        for info in sorted(free, key=lambda f: -f.size):
            if info.size < pool_bytes * _DOMINANT_SHARE:
                break          # sorted descending: nothing later qualifies
            if info.size <= budget:
                chosen.append(info)
                taken.add(id(info))
                spent += info.size
                break
    for info in free:
        if id(info) in taken:
            continue
        if spent + info.size <= budget:
            chosen.append(info)
            taken.add(id(info))
            spent += info.size
    return chosen, spent


def pick_sample(infos: Sequence[FileInfo],
                cap_bytes: int = DEFAULT_SAMPLE_BYTES) -> Sample:
    """Choose at most ``cap_bytes`` of ``infos`` to measure the profiles on.

    Deterministic: the same input gives the same sample, so two comparison
    runs are comparable with each other.
    """
    infos = list(infos)
    source_files = len(infos)
    source_bytes = sum(f.size for f in infos)
    # A caller can hand this anything - `tools/bench.py --sample` takes an int
    # straight off the command line. A cap below zero used to reach the
    # `min(infos, ...)` fallback with nothing to minimise and raise ValueError.
    cap_bytes = max(0, cap_bytes)

    if not infos or source_bytes <= cap_bytes:
        # Nothing to choose. Note this branch also covers the all-zero-byte
        # input, which would otherwise divide by zero below.
        return Sample(files=tuple(infos), cap_bytes=cap_bytes,
                      source_files=source_files, source_bytes=source_bytes)

    groups: dict[Category, list[FileInfo]] = {}
    for info in infos:
        groups.setdefault(info.category, []).append(info)
    for files in groups.values():
        files.sort(key=lambda f: (f.size, str(f.path)))

    # Biggest category first: when whole-file granularity leaves a remainder,
    # the bytes that dominate the input should be the ones that absorb it.
    order = sorted(groups, key=lambda c: (-sum(f.size for f in groups[c]), c.value))

    taken: set[int] = set()
    chosen: list[FileInfo] = []
    used = 0
    missing: list[Category] = []

    # Reserve one file per category FIRST, cheapest category first.
    #
    # Doing this at the end instead - as the first version did - spends the
    # budget on the dominant category and then has nothing left to buy the
    # small ones with. Measured on Silesia at a 20 MB cap it picked 2 of 12
    # files, left 4 MB of the budget unspent, and reported `executable` as
    # missing when its one 6.2 MB member would have fitted easily. Presence
    # is cheap and it has to be bought before the budget is gone.
    per_category_floor = sorted(order, key=lambda c: groups[c][0].size)
    for category in per_category_floor:
        smallest = groups[category][0]
        if used + smallest.size <= cap_bytes:
            chosen.append(smallest)
            taken.add(id(smallest))
            used += smallest.size
        else:
            missing.append(category)

    for category in order:
        files = groups[category]
        share = sum(f.size for f in files) / source_bytes
        already = sum(f.size for f in chosen if f.category is category)
        budget = min(int(cap_bytes * share) - already, cap_bytes - used)
        if budget <= 0:
            continue
        picked, spent = _fill(list(_spread(files)), budget, taken,
                              pool_bytes=sum(f.size for f in files))
        chosen.extend(picked)
        used += spent

    if not chosen:
        # Every category's smallest file is bigger than the whole cap. One
        # file it is, and `over_cap` tells the caller to warn rather than
        # pretend this was cheap. Never a prefix. (`missing` is rebuilt below
        # from what actually got in, so the reserve pass's list is dropped.)
        smallest = min(infos, key=lambda f: (f.size, str(f.path)))
        return Sample(files=(smallest,), cap_bytes=cap_bytes,
                      source_files=source_files, source_bytes=source_bytes,
                      missing_categories=tuple(
                          c for c in order if c is not smallest.category))

    # Whatever the per-category rounding left on the table, spent in the same
    # order, so a 20 MB budget does not stop at 14 MB for arithmetic reasons.
    for category in order:
        if used >= cap_bytes:
            break
        picked, spent = _fill(list(_spread(groups[category])),
                              cap_bytes - used, taken)
        chosen.extend(picked)
        used += spent

    # Input order, not selection order: the sample should read like the folder.
    position = {id(f): i for i, f in enumerate(infos)}
    chosen.sort(key=lambda f: position[id(f)])
    return Sample(files=tuple(chosen), cap_bytes=cap_bytes,
                  source_files=source_files, source_bytes=source_bytes,
                  missing_categories=tuple(missing),
                  under_represented=_drifted(chosen, groups, source_bytes))


#: A category has to lose more than half its share before it is called out.
#: Whole-file granularity always drifts a little and a caveat that fires on
#: every input is a caveat nobody reads.
_DRIFT_FLOOR = 0.5
#: ...and it has to be worth mentioning in the first place.
_DRIFT_MIN_SHARE = 0.02


def _drifted(chosen: Sequence[FileInfo],
             groups: dict[Category, list[FileInfo]],
             source_bytes: int) -> tuple[Category, ...]:
    """Which categories the sample carries far less of than the input does."""
    sampled = sum(f.size for f in chosen)
    if not sampled or not source_bytes:
        return ()
    taken: dict[Category, int] = {}
    for info in chosen:
        taken[info.category] = taken.get(info.category, 0) + info.size
    drifted = []
    for category, files in groups.items():
        if category not in taken:
            continue        # already reported as missing
        input_share = sum(f.size for f in files) / source_bytes
        if input_share < _DRIFT_MIN_SHARE:
            continue
        if taken[category] / sampled < input_share * _DRIFT_FLOOR:
            drifted.append(category)
    return tuple(sorted(drifted, key=lambda c: c.value))
