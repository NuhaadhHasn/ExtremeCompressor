"""I6: choosing the sample the preset comparison actually measures.

The feature's whole claim is that its numbers are measured rather than
estimated, so the sample is not a convenience - it is the measurement's
validity. A subset that quietly drops a category, or that fills its budget
with the smallest files because they were easiest to fit, produces a
*confidently wrong* ratio, which is worse than the estimate it replaces.

Three properties carry that weight and each has a test below:

- **every category present in the input is present in the sample.** On the
  real Programs corpus 41.9% of the bytes are in the store bucket; a sample
  that omits them measures a machine nobody has.
- **whole files only.** A prefix of a file does not compress like the file,
  and the point of I6 is to run what the real job would run.
- **the spread, not the head or the tail.** Taking files in size order fills
  the budget with one end of the distribution.
"""

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.sample import DEFAULT_SAMPLE_BYTES, Sample, pick_sample


def _f(name: str, size: int, category: Category = Category.BINARY) -> FileInfo:
    return FileInfo(path=Path(name), size=size, category=category,
                    entropy_bps=7.0)


def _sizes(sample: Sample) -> list[int]:
    return [f.size for f in sample.files]


# -- the trivial case: nothing to choose ----------------------------------

def test_an_empty_input_samples_to_nothing_rather_than_raising():
    sample = pick_sample([])
    assert sample.files == ()
    assert sample.total_bytes == 0
    assert sample.source_bytes == 0
    assert not sample.over_cap


def test_an_input_under_the_cap_is_its_own_sample():
    infos = [_f("a", 10), _f("b", 20), _f("c", 30)]
    sample = pick_sample(infos, cap_bytes=1000)
    assert sample.is_whole_input
    assert list(sample.files) == infos
    assert sample.total_bytes == 60
    assert sample.fraction == 1.0


def test_the_default_cap_is_the_hundred_megabytes_the_roadmap_specified():
    assert DEFAULT_SAMPLE_BYTES == 100_000_000


# -- the cap is a cap ------------------------------------------------------

def test_a_sample_never_exceeds_its_cap_when_whole_files_can_fit_under_it():
    infos = [_f(f"f{i}", 1_000_000) for i in range(500)]
    sample = pick_sample(infos, cap_bytes=10_000_000)
    assert sample.total_bytes <= 10_000_000
    assert not sample.is_whole_input
    assert not sample.over_cap


def test_the_sample_is_a_subset_of_the_input_and_never_repeats_a_file():
    infos = [_f(f"f{i}", 1_000_000) for i in range(500)]
    sample = pick_sample(infos, cap_bytes=10_000_000)
    paths = [f.path for f in sample.files]
    assert len(paths) == len(set(paths))
    assert set(sample.files).issubset(set(infos))


def test_whole_files_only_a_sampled_file_keeps_its_original_size():
    infos = [_f(f"f{i}", 3_000_000) for i in range(100)]
    sample = pick_sample(infos, cap_bytes=10_000_000)
    by_path = {f.path: f for f in infos}
    for chosen in sample.files:
        assert chosen.size == by_path[chosen.path].size


# -- the case the cap cannot honour ---------------------------------------

def test_one_file_bigger_than_the_cap_is_reported_rather_than_truncated():
    """Never a prefix. The caller warns; it does not measure half a file."""
    infos = [_f("huge.iso", 4_000_000_000)]
    sample = pick_sample(infos, cap_bytes=100_000_000)
    assert sample.over_cap
    assert _sizes(sample) == [4_000_000_000]
    assert sample.total_bytes == 4_000_000_000


def test_when_nothing_fits_the_smallest_file_is_the_sample():
    infos = [_f("big", 900_000_000), _f("small", 300_000_000)]
    sample = pick_sample(infos, cap_bytes=100_000_000)
    assert sample.over_cap
    assert [f.path.name for f in sample.files] == ["small"]


# -- the three properties that make the number honest ---------------------

def test_every_category_in_the_input_survives_into_the_sample():
    infos = (
        [_f(f"vid{i}", 4_000_000, Category.VIDEO) for i in range(20)]
        + [_f(f"exe{i}", 2_000_000, Category.EXECUTABLE) for i in range(20)]
        + [_f(f"txt{i}", 100_000, Category.TEXT) for i in range(20)]
        + [_f("one.jpg", 500_000, Category.IMAGE)]
    )
    sample = pick_sample(infos, cap_bytes=20_000_000)
    present = {f.category for f in sample.files}
    assert present == {Category.VIDEO, Category.EXECUTABLE,
                       Category.TEXT, Category.IMAGE}
    assert sample.missing_categories == ()


def test_a_category_too_big_for_the_cap_is_reported_not_silently_dropped():
    """No silent caps. A measurement that quietly skipped the video is a
    measurement of a different folder, and the caption has to say so."""
    infos = ([_f("film.mkv", 900_000_000, Category.VIDEO)]
             + [_f(f"t{i}", 200_000, Category.TEXT) for i in range(50)])
    sample = pick_sample(infos, cap_bytes=5_000_000)
    assert Category.VIDEO in sample.missing_categories
    assert {f.category for f in sample.files} == {Category.TEXT}
    assert sample.total_bytes <= 5_000_000


def test_a_categorys_share_of_the_sample_tracks_its_share_of_the_input():
    """80% of the bytes should not become 20% of the measurement."""
    infos = ([_f(f"v{i}", 8_000_000, Category.VIDEO) for i in range(100)]
             + [_f(f"t{i}", 2_000_000, Category.TEXT) for i in range(100)])
    sample = pick_sample(infos, cap_bytes=50_000_000)
    video = sum(f.size for f in sample.files if f.category is Category.VIDEO)
    share = video / sample.total_bytes
    assert 0.65 <= share <= 0.95, f"video took {share:.0%} of a 80% input"


def test_the_sample_walks_the_size_distribution_instead_of_one_end_of_it():
    """Sorted order fills the budget with the smallest or the largest files,
    and both give a ratio the real job will not reproduce.

    100 files of 100 KB .. 10 MB against a 5 MB budget. Filling in ascending
    order buys files 1..9 and tops out at 900 KB; filling in descending order
    buys one 5 MB file and nothing else. A spread has to do both.
    """
    infos = [_f(f"f{i}", (i + 1) * 100_000) for i in range(100)]
    sample = pick_sample(infos, cap_bytes=5_000_000)
    sizes = _sizes(sample)
    assert len(sizes) >= 3
    assert max(sizes) >= 2_000_000, "never reached past the smallest files"
    assert min(sizes) <= 1_000_000, "took only the big end"


# -- properties a caller relies on ----------------------------------------

def test_a_category_the_sample_starves_is_named_so_the_caption_can_say_so():
    """The real Programs corpus, in miniature: 42% of the bytes live in a
    handful of archives each larger than the whole cap, so no whole-file
    subset can carry 42% of the sample. The bias is reported, not hidden."""
    infos = ([_f(f"big{i}.zip", 200_000_000, Category.COMPRESSED_ARCHIVE)
              for i in range(4)]
             + [_f("small.zip", 1_000_000, Category.COMPRESSED_ARCHIVE)]
             + [_f(f"e{i}.exe", 2_000_000, Category.EXECUTABLE) for i in range(300)])
    sample = pick_sample(infos, cap_bytes=50_000_000)
    assert Category.COMPRESSED_ARCHIVE in sample.under_represented
    assert Category.COMPRESSED_ARCHIVE not in sample.missing_categories
    assert Category.EXECUTABLE not in sample.under_represented


def test_a_sample_that_keeps_its_proportions_reports_no_drift():
    infos = ([_f(f"v{i}", 8_000_000, Category.VIDEO) for i in range(100)]
             + [_f(f"t{i}", 2_000_000, Category.TEXT) for i in range(100)])
    sample = pick_sample(infos, cap_bytes=50_000_000)
    assert sample.under_represented == ()
    assert sample.missing_categories == ()


def test_the_whole_input_never_drifts_from_itself():
    infos = [_f("a", 10, Category.TEXT), _f("b", 5_000, Category.VIDEO)]
    sample = pick_sample(infos, cap_bytes=1_000_000)
    assert sample.is_whole_input
    assert sample.under_represented == ()


def test_sampling_is_deterministic_so_two_runs_compare():
    infos = [_f(f"f{i}", (i + 1) * 7_919, Category.BINARY) for i in range(300)]
    first = pick_sample(infos, cap_bytes=1_000_000)
    second = pick_sample(infos, cap_bytes=1_000_000)
    assert [f.path for f in first.files] == [f.path for f in second.files]


def test_the_sample_reports_what_it_came_from_so_the_caption_can_say_so():
    infos = [_f(f"f{i}", 1_000_000) for i in range(500)]
    sample = pick_sample(infos, cap_bytes=10_000_000)
    assert sample.source_files == 500
    assert sample.source_bytes == 500_000_000
    assert 0.0 < sample.fraction < 1.0
    assert sample.cap_bytes == 10_000_000


def test_zero_byte_files_do_not_divide_by_zero():
    infos = [_f("empty", 0), _f("also-empty", 0)]
    sample = pick_sample(infos, cap_bytes=1000)
    assert sample.is_whole_input
    assert sample.fraction == 1.0


@pytest.mark.parametrize("cap", [1, 1000, 999_999, 100_000_000])
def test_no_cap_produces_a_sample_larger_than_the_input(cap):
    infos = [_f(f"f{i}", 1_000_000) for i in range(50)]
    sample = pick_sample(infos, cap_bytes=cap)
    assert sample.total_bytes <= sample.source_bytes


# -- defects found by the 2026-09-20 adversarial review --------------------

def test_a_dominant_file_is_not_crowded_out_by_the_crumbs_around_it():
    """The installer case. 95 MB of setup.exe beside forty 300 KB DLLs is an
    installer; a sample that spends 13.6 MB on DLLs and omits the setup is a
    sample of something else. Reproduced at the shipped cap before the fix."""
    infos = ([_f("setup.exe", 95_000_000, Category.EXECUTABLE)]
             + [_f(f"lib{i:03d}.dll", 300_000, Category.EXECUTABLE)
                for i in range(40)])
    sample = pick_sample(infos)          # the shipped 100 MB cap
    assert any(f.path.name == "setup.exe" for f in sample.files)
    assert sample.total_bytes > 90_000_000, "spent the cap on crumbs"
    assert sample.total_bytes <= DEFAULT_SAMPLE_BYTES


def test_taking_the_dominant_file_does_not_replace_the_spread():
    """The guard has to be a threshold, not "always take the largest": taking
    the biggest file unconditionally collapses this sample from three files
    to two and undoes the distribution walk."""
    infos = [_f(f"f{i}", (i + 1) * 100_000) for i in range(100)]
    sample = pick_sample(infos, cap_bytes=5_000_000)
    assert len(sample.files) >= 3


@pytest.mark.parametrize("cap", [0, -1, -1_000_000])
def test_a_nonpositive_cap_is_clamped_rather_than_raising(cap):
    """`tools/bench.py --sample` takes an int straight off the command line."""
    assert pick_sample([], cap_bytes=cap).files == ()
    sample = pick_sample([_f("a", 10), _f("b", 20)], cap_bytes=cap)
    assert len(sample.files) == 1        # the smallest, and over_cap says so
    assert sample.over_cap
