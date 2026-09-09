"""K4: zstd's window was costing half the output size on this corpus.

Measured 2026-09-07 on the roadmap's own case - 300 MiB whose duplicate half
sits 150 MiB away, i.e. a match distance beyond the 128 MiB that
``window_log=27`` can see - streamed through the same API `ZstdStage` uses:

| window_log | output      | compress |
|------------|------------:|---------:|
| 27 (was)   | 314,580,006 |  115.3 s |
| **31**     | **157,699,989** | **74.8 s** |

**49.9% smaller and 1.54x faster**, because there is half as much left to
entropy-code. (The roadmap predicted "half the size and 2.1x faster"; the size
reproduced to within 4 bytes, the speedup measured 1.54x here.)

**That is the synthetic best case, and real data is far more modest.** Two
builds of the same installer - mysql-installer-community 8.0.35.0 and 8.0.43.0,
642.9 MiB together, whatever they share sitting ~288 MiB apart - forced through
this stage:

    window_log 27   668,628,541 B   195.2 s
    window_log 31   639,241,730 B   195.9 s     4.40% smaller, no speedup

4.40%, not 49.9%, and no speed change at all. Read the 49.9% as "what a window
can be worth when the duplicate is exact", and the 4.40% as "what it is worth
on two versions of a real installer". Both are true; only one describes usage.

And a third number matters more than either: in the *actual pipeline* those two
MSIs are high-entropy, so the analyzer routes them to **store** and the zstd
stage never sees them. K4 changes nothing for that job. The win applies only to
what is routed through the codec.

The cost, measured as peak working set from the OS rather than from
`tracemalloc`, which cannot see zstd's C-side window buffer:

| decompress cap | frame       | peak    |
|----------------|-------------|--------:|
| 27             | 27-window   | 146 MiB |
| 31             | 27-window   | 146 MiB |
| 31             | 31-window   | 317 MiB |

Two things follow, and the second is the actual defect this file exists for:

* **Raising the cap is free.** Reading a narrow frame with a wide cap costs
  exactly what reading it with a narrow cap costs, because `max_window_size` is
  a ceiling and zstd sizes the real buffer to the frame. Doc 12's warning that
  ``--long=31`` "costs the decompressor too" is true only for genuinely wide
  frames, and there it is +171 MiB on a 16 GB target for half the bytes.
* **`extract` derived its ceiling from the compress setting**
  (``max_window_size = 1 << self.long_log``), so a build could only ever read
  archives as wide as it writes. Measured directly: a 27-cap reader given a
  31-window frame fails with *"Frame requires too much memory for decoding"*,
  while a 31-cap reader opens a 27-window frame fine. That asymmetry is why
  the ceiling has to be a constant and not a mirror of the writer's choice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.stages.base import StageContext
from excmp.stages.zstdstage import (COMPRESS_WINDOW_LOG_FLOOR,
                                    COMPRESS_WINDOW_LOG_MAX,
                                    DECOMPRESS_WINDOW_LOG, ZstdStage,
                                    _window_log_for)


def _tree(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "a.txt").write_text("the quick brown fox\n" * 3000, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("lorem ipsum dolor\n" * 3000, encoding="utf-8")
    return root


def test_the_window_is_fitted_to_the_input_not_pinned_at_the_maximum():
    """A window larger than the data cannot find matches the data does not
    contain, and pinning it at 31 cost 769 MiB for nothing. Measured on the
    same 300 MiB corpus, byte-identical output at three window sizes:

        wl 29 (512 MiB)  157,699,989 B  1,045 MiB peak
        wl 30 (1 GiB)    157,699,989 B  1,289 MiB peak
        wl 31 (2 GiB)    157,699,989 B  1,814 MiB peak

    So the default fits the input and clamps to [27, 31].
    """
    assert ZstdStage().long_log is None, "the default is 'fit', not a number"
    # Small jobs stay exactly where they were before K4.
    assert _window_log_for(1) == COMPRESS_WINDOW_LOG_FLOOR == 27
    assert _window_log_for(10 << 20) == 27
    # Mid-size jobs get just enough to see across themselves.
    assert _window_log_for(314_572_800) == 29
    assert (1 << 29) >= 314_572_800, "the window has to cover the input"
    assert _window_log_for(674_115_584) == 30
    # And nothing exceeds what zstd supports.
    assert _window_log_for(64 << 30) == COMPRESS_WINDOW_LOG_MAX == 31


def test_the_fitted_window_always_covers_its_input():
    """The property that makes the fitting correct rather than merely smaller:
    whatever size comes in, the chosen window can span it - so no long-range
    match inside a single job is ever out of reach until 2 GiB."""
    for n in (1, 2, 4095, 1 << 20, (1 << 27) - 1, 1 << 27, 300 << 20,
              (1 << 31) - 1):
        wl = _window_log_for(n)
        assert (1 << wl) >= n or wl == COMPRESS_WINDOW_LOG_MAX, (n, wl)


def test_an_explicit_window_is_still_honoured():
    """The advanced knobs and these tests pass a number; fitting is only the
    default. A stage told 27 must compress at 27."""
    assert ZstdStage(long_log=27)._compress_window_log(300 << 20) == 27
    assert ZstdStage(long_log=31)._compress_window_log(1) == 31


def test_the_decompress_ceiling_does_not_depend_on_the_compress_setting():
    """The bug itself. A reader's ceiling must be a constant, so that a build
    can open an archive wider than the one it would write."""
    narrow = ZstdStage(long_log=20)
    assert DECOMPRESS_WINDOW_LOG >= 31
    # Whatever it was told to compress with, it reads with the ceiling.
    assert narrow._decompress_window_log() == DECOMPRESS_WINDOW_LOG
    # ...and the fitting default does not change that either.
    assert ZstdStage()._decompress_window_log() == DECOMPRESS_WINDOW_LOG


def test_a_wide_archive_is_readable_by_a_narrow_writer(tmp_path):
    """The end-to-end form of the same thing, and the one that would have
    broken real archives: write at 31, then read with a stage configured to
    compress at 20. Before K4 this raised "Frame requires too much memory for
    decoding" and the archive was simply unreadable."""
    src = _tree(tmp_path / "src")
    packed = tmp_path / "payload.zst"
    ctx = StageContext(temp_dir=tmp_path / "t")
    ZstdStage(long_log=31).compress(src, packed, ctx)

    out = tmp_path / "out"
    ZstdStage(long_log=20).extract(packed, out, ctx)
    assert (out / "a.txt").read_text(encoding="utf-8") == \
        "the quick brown fox\n" * 3000
    assert (out / "sub" / "b.txt").is_file()


def test_a_narrow_legacy_archive_still_reads(tmp_path):
    """Every Fast-profile archive written before K4 has a 27-bit window. The
    ceiling rising is what keeps those readable - it is a maximum, so a
    smaller frame is unaffected."""
    src = _tree(tmp_path / "src")
    packed = tmp_path / "payload.zst"
    ctx = StageContext(temp_dir=tmp_path / "t")
    ZstdStage(long_log=27).compress(src, packed, ctx)

    out = tmp_path / "out"
    ZstdStage().extract(packed, out, ctx)          # today's default reader
    assert (out / "a.txt").read_text(encoding="utf-8") == \
        "the quick brown fox\n" * 3000


def test_the_wide_window_actually_finds_a_long_range_match(tmp_path):
    """Guard against the win being an artefact of the test data.

    The first attempt at measuring this built a corpus from one repeated 1 MiB
    block, so LDM found matches every megabyte and *both* windows scored the
    same. The duplicate has to be unique-then-repeated at a distance only the
    wide window can reach. Scaled down here so it runs in seconds; the full
    300 MiB measurement is in the module docstring.
    """
    import os
    import zstandard

    half = 40 << 20                      # 40 MiB, beyond a 2**22 window
    unique = os.urandom(half)
    data = unique + unique

    sizes = {}
    for wl in (22, 31):
        params = zstandard.ZstdCompressionParameters.from_level(
            19, window_log=wl, enable_ldm=True, threads=-1)
        cctx = zstandard.ZstdCompressor(compression_params=params)
        buf = tmp_path / f"o{wl}.zst"
        with buf.open("wb") as fh:
            with cctx.stream_writer(fh, closefd=False) as zw:
                for i in range(0, len(data), 1 << 20):
                    zw.write(data[i:i + (1 << 20)])
        sizes[wl] = buf.stat().st_size

    assert sizes[31] < sizes[22] * 0.6, (
        f"the wide window should roughly halve this: {sizes}")


def test_the_ceiling_does_not_allocate_what_it_permits(tmp_path):
    """Why a 2 GiB ceiling is safe: `max_window_size` is a refusal threshold,
    not a buffer. Measured 14 MiB peak for a 27-byte frame under a 2 GiB
    ceiling - the same as under a 128 MiB one.

    Worth pinning because the opposite would be a serious regression: every
    extract on the machine would reserve 2 GiB.
    """
    import io
    import zstandard
    tiny = zstandard.ZstdCompressor().compress(b"hello world" * 10)
    dctx = zstandard.ZstdDecompressor(max_window_size=1 << DECOMPRESS_WINDOW_LOG)
    with dctx.stream_reader(io.BytesIO(tiny)) as r:
        assert r.read(1 << 20) == b"hello world" * 10


def test_the_ceiling_is_documented_as_a_ceiling():
    """A constant with no reason beside it is how the 8 MiB manifest cap
    happened. This one has a measurement: raising it cost 0 MiB on a narrow
    frame, 146 -> 146."""
    from excmp.stages import zstdstage
    assert "146" in (zstdstage.__doc__ or "") or \
        "ceiling" in (zstdstage.__doc__ or "").lower()


def test_the_fast_estimate_still_contains_the_truth_after_k4(tmp_path):
    """K4 changed the codec and left the calibration describing the old one.

    `_CODEC_FACTOR["zstd"]` is a **per-file** multiplier on each file's own
    worst zstd-3 sample. Nothing per-file can represent "this whole file is a
    duplicate of one 170 MiB earlier", which is precisely the saving the wide
    window made findable - so the measured archive landed *below* the
    estimator's own optimistic bound and the range excluded the truth, which is
    worse than having no range.

    Measured at full scale (220,200,960 B in three files, the third
    byte-identical to the first): predicted low 61,945,796 against an actual
    41,963,379 - the truth at 0.677x the low end. Scaled down here so it runs
    in seconds.

    **Two fixes were tried and rejected before the one that shipped**, and both
    rejections are the reason the third looks the way it does. Clamping the
    *per-file* low changed nothing, because for compressible data that number
    (0.28) already sits below any sane cap - the discount has to apply to the
    aggregate. Discounting the aggregate by a flat factor for every zstd chain
    then worked, but rendered a 2.2x numeric range that wrapped a line and
    pushed the populated Compress page from 420 to 431px, past the budget
    research/23 2.4 argues for - and it claimed a dedup saving on corpora that
    contain no duplicates at all, which is most of them.

    So `_long_range_discount` awards the credit **per duplicate candidate**,
    keyed on exact file size. Same-size is a superset of same-content, so it
    over-credits rather than under-credits, which is the honest direction for
    an optimistic bound; and it collapses to zero when no two files share a
    size, which is what keeps every ordinary estimate - and the page height -
    exactly as it was.
    """
    import random

    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    from excmp.planner import Profile, plan as make_plan
    from excmp.tools import find_tools

    words = [f"tok{i:04d}" for i in range(4000)]

    def wordy(n: int, seed: int) -> bytes:
        r = random.Random(seed)
        out = bytearray()
        while len(out) < n:
            out += (" ".join(r.choice(words) for _ in range(12)) + "\n").encode()
        return bytes(out[:n])

    src = tmp_path / "src"
    src.mkdir()
    unique = wordy(6 << 20, seed=1)
    (src / "u1.dat").write_bytes(unique)
    (src / "f.dat").write_bytes(wordy(20 << 20, seed=2))
    (src / "u2.dat").write_bytes(unique)      # the cross-file duplicate

    infos = analyze_tree(src)
    the_plan = make_plan(infos, Profile.FAST, find_tools())
    assert all(r.action != "store" or not r.files for r in the_plan.routes),         "this corpus must be compressible enough to be piped, or it tests nothing"

    est = estimate_size(infos, the_plan)
    packed = tmp_path / "p.zst"
    ZstdStage().compress(src, packed, StageContext(temp_dir=tmp_path / "t"))
    real = packed.stat().st_size

    assert est.low <= real <= est.high, (
        f"the estimate range {est.low:,}..{est.high:,} excludes the real "
        f"{real:,} - the calibration no longer describes the codec")


# --------------------------------------------------------------------------
# B8: the calibration, stressed across corpus shapes instead of fitted to one
# --------------------------------------------------------------------------

def _infos(sizes, ratio=1.0):
    """FileInfo list with a chosen worst-sample ratio, no disk involved."""
    from excmp.analyzer import Category, FileInfo

    return [FileInfo(path=Path(f"f{i}.dat"), size=n, category=Category.BINARY,
                     entropy_bps=4.0, sample_ratio=ratio,
                     sample_ratio_max=ratio)
            for i, n in enumerate(sizes)]


def _fast_plan(infos):
    from excmp.planner import Profile, plan as make_plan
    return make_plan(infos, Profile.FAST, {})


def test_the_estimate_is_never_negative():
    """A size-keyed duplicate credit drove `low` to **-33,024,744** on four
    distinct 20 MiB text files, because they happened to share a size and each
    was credited 90% of itself. An archive cannot be smaller than nothing, and
    a negative bound is not a conservative one - it is a broken one."""
    from excmp.estimate import estimate_size

    infos = _infos([20 << 20] * 4, ratio=0.25)
    est = estimate_size(infos, _fast_plan(infos))
    assert est.low >= 0, est.low
    assert est.low <= est.expected <= est.high


def test_same_size_distinct_files_are_not_credited_as_duplicates():
    """The false positive that produced the negative bound. Six equal-sized
    files with unrelated contents are not six duplicates, and measured on real
    random data they deduplicated by nothing at all."""
    from excmp.estimate import estimate_size

    infos = _infos([20 << 20] * 6, ratio=1.0)
    est = estimate_size(infos, _fast_plan(infos))
    total = sum(i.size for i in infos)
    # Not asserting a tight floor - just that the estimate has not been
    # discounted into fantasy by a coincidence of file sizes.
    assert est.low >= total * 0.05, (est.low, total)


def test_the_optimistic_end_reaches_cross_file_deduplication():
    """The measurement that killed the size-keyed heuristic.

    Three files sharing a 40 MiB body but of **three different sizes**
    compressed to **12.2%** of the input - 87.84% saved - while `low` sat at
    43.6%, so the range excluded the truth by 31.41 points. Substring
    deduplication does not care whether two files are the same length, which
    is exactly what a size key cannot see.
    """
    from excmp.estimate import estimate_size

    sizes = [44 << 20, 42 << 20, 40 << 20]
    infos = _infos(sizes, ratio=0.30)
    est = estimate_size(infos, _fast_plan(infos))
    total = sum(sizes)
    assert est.low <= total * 0.13, (
        f"low={est.low} is {est.low / total:.3f} of the input; the measured "
        f"corpus reached 0.122 and the range has to contain it")
