"""Quiet-machine re-measures (2026-10-17): the time priors B13, B19 and B20
set from contended runs, measured again with WSL and Docker stopped and the
other processes at 6-32% of the CPU (docs/benchmarks/
2026-10-17-quiet-remeasure.md).

Each figure is the median of three runs through the app (engine.compress with
D9, engine.extract, an independent SHA-256 of every file; 0 mismatches in 37
rows) unless it says otherwise. The expected figure is the best guess on a
quiet machine, so it has to land near these; the range has to hold them, and
the contended runs the old priors came from too (tests/test_b19_media.py and
tests/test_b20_zip_family.py keep those).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import Rates, estimate_time, pack_cost, time_split
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
JPEG = Rates(ogg_pack=False, jpeg_pack=True)
OGG = Rates(ogg_pack=True, jpeg_pack=False)


@pytest.fixture(autouse=True)
def _balrogg_is_installed_in_the_plan(monkeypatch):
    from excmp import oggpack
    monkeypatch.setattr(oggpack, "available", lambda: True)


def _jpeg(name, size, refuses=False):
    return FileInfo(path=Path(name), size=size, category=Category.IMAGE,
                    entropy_bps=7.97, is_jpeg=True, lepton_refuses=refuses)


def _mp3(name, size):
    return FileInfo(path=Path(name), size=size, category=Category.AUDIO,
                    entropy_bps=7.99)


def _container(name, size):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0,
                    expandable=True)


def _ogg(name, size):
    return FileInfo(path=Path(name), size=size, category=Category.AUDIO,
                    entropy_bps=7.97, sample_ratio=1.0, sample_ratio_max=1.0)


def _even(make, prefix, suffix, total, n, **kw):
    return [make(f"{prefix}{i}{suffix}", total // n, **kw) for i in range(n)]


#: corpus -> (files, profile, measured seconds: compress including D9)
QUIET = {
    # The two CMYK files lepton refuses: 15.0, 14.5, 16.3 s.
    "cmyk": (lambda: [_jpeg("c1.jpg", 12_112, True), _jpeg("c2.jpg", 8_373_937, True)],
             Profile.EXTREME, 15.0),
    # 14 refused print files (135.5 MB, piped to packJPG) and 24 photos
    # lepton takes (15.8 MB): 283.8, 393.8, 279.1 s.
    "design": (lambda: (_even(_jpeg, "d", ".jpg", 135_503_920, 14, refuses=True)
                        + _even(_jpeg, "p", ".jpg", 15_786_950, 24)),
               Profile.EXTREME, 283.8),
    # packMP3: 51.1, 44.8, 144.0 s and 130.7, 107.3, 126.8 s.
    "mp3-music": (lambda: _even(_mp3, "m", ".mp3", 33_922_849, 5), Profile.EXTREME, 51.1),
    "mp3-misc": (lambda: _even(_mp3, "m", ".mp3", 80_307_437, 16), Profile.EXTREME, 126.8),
    # One run (the same night): the two Android App Bundles, 121 MB, B20's
    # container rate (0.46 MB/s), which the re-measure kept.
    "aab": (lambda: [_container("a1.aab", 59_798_145), _container("a2.aab", 61_202_644)],
            Profile.EXTREME, 343.3),
}


@pytest.mark.parametrize("corpus", sorted(QUIET))
def test_a_quiet_run_sits_in_the_range(corpus):
    make, profile, measured = QUIET[corpus]
    infos = make()
    t = estimate_time(infos, plan(infos, profile, TOOLS), JPEG)
    assert t.low <= measured <= t.high, (t.low, t.expected, t.high)


@pytest.mark.parametrize("corpus", sorted(QUIET))
def test_the_expected_figure_is_close_to_a_quiet_run(corpus):
    """The contended priors put MP3 at 2.8x and the CMYK files at 2.1x the
    quiet time."""
    make, profile, measured = QUIET[corpus]
    infos = make()
    t = estimate_time(infos, plan(infos, profile, TOOLS), JPEG)
    assert measured / 1.25 <= t.expected <= measured * 1.25, (t.expected, measured)


#: Insane, one run each: MP3 music quiet (335.3 s) and contended (B18,
#: 1,025.4 s); the design folder quiet (1,045.8 s).
INSANE = {
    "mp3-quiet": (QUIET["mp3-music"][0], 335.3),
    "mp3-contended": (QUIET["mp3-music"][0], 1_025.4),
    "design-quiet": (QUIET["design"][0], 1_045.8),
}


def test_insane_s_range_holds_a_contended_recoded_run():
    make, measured = INSANE["mp3-contended"]
    infos = make()
    t = estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), JPEG)
    assert t.low <= measured <= t.high, (t.low, t.expected, t.high)


@pytest.mark.parametrize("label", ["mp3-quiet", "design-quiet"])
def test_insane_s_estimate_fits_a_quiet_recoded_run(label):
    """Was a strict xfail (2026-10-17): Insane billed recoded media at
    zpaqfranz's Silesia rate and a quiet run finished under the low end. B22
    (2026-11-17) measured Insane per kind, JPEG and MP3 among them, and
    tests/test_b22_insane_recoded.py holds the new rows."""
    make, measured = INSANE[label]
    infos = make()
    t = estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), JPEG)
    assert t.low <= measured <= t.high, (t.low, t.expected, t.high)
    assert measured / 1.5 <= t.expected <= measured * 1.5, (t.expected, measured)


@pytest.mark.parametrize("corpus", ["cmyk", "design", "mp3-music", "mp3-misc"])
def test_the_low_end_stays_informative(corpus):
    """Review: spreading the recoded time both ways put the design folder's
    low end at 71.5 s; its fastest run took 279 s. Contention only slows a
    job down, so the quiet median is near the floor."""
    make, profile, measured = QUIET[corpus]
    infos = make()
    t = estimate_time(infos, plan(infos, profile, TOOLS), JPEG)
    assert t.low >= measured / 2, (t.low, measured)


#: The B13 music corpus: 13 Vorbis files (11 .ogg, 2 .oga) and 5 Opus.
def _music():
    return (_even(_ogg, "v", ".ogg", 143_546_732, 13)
            + _even(_ogg, "o", ".opus", 26_428_582, 5))


def test_the_ogg_self_test_takes_as_long_as_a_quiet_run():
    """D9 decoded the 170 MB in 122.1, 181.2 and 182.7 s at Normal; the old
    1.5 MB/s, from the CLI per file, said 113 s."""
    infos = _music()
    _, verify = time_split(0, 0, [], OGG, pack=pack_cost(infos, plan(infos, Profile.NORMAL,
                                                                     TOOLS), OGG))
    assert 181.2 / 1.15 <= verify <= 181.2 * 1.15, verify


def test_an_ogg_folder_s_quiet_run_sits_in_the_range():
    infos = _music()
    t = estimate_time(infos, plan(infos, Profile.NORMAL, TOOLS), OGG)
    assert t.low <= 485.5 <= t.high, (t.low, t.expected, t.high)
    assert 485.5 / 1.25 <= t.expected <= 485.5 * 1.25, t.expected


def _suggestion(infos):
    from gui.suggest import recommend_profile, strongest_profile, summarize
    summary = summarize(infos, plan(infos, Profile.EXTREME, TOOLS), TOOLS,
                        reference_plan=plan(infos, strongest_profile(TOOLS), TOOLS))
    return summary, recommend_profile(summary, cores=2)


def test_a_small_recoded_folder_s_wait_counts_its_whole_time():
    """The suggestion read only what the recoder adds beyond the chain's rate.
    At the quiet rates that is 13 s for 50 MB of CMYK, whose compress and
    self-test the model puts at ~98 s, so the folder was told "seconds"
    (tests/test_b19_media.py keeps the sentence)."""
    summary, _ = _suggestion(_even(_jpeg, "c", ".jpg", 50_000_000, 10, refuses=True))
    assert 80 <= summary.strongest_recode_seconds <= 120


def _text(n, size):
    return [FileInfo(path=Path(f"t{i}.txt"), size=size, category=Category.TEXT,
                     entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)
            for i in range(n)]


@pytest.mark.parametrize("make", [
    # Review: 25 MB of CMYK beside 35 MB of text, the table ~2 min (79 s).
    lambda: _even(_jpeg, "c", ".jpg", 25_000_000, 5, refuses=True) + _text(7, 5_000_000),
    # 30 MB of MP3 beside 30 MB of text, ~2 min (71 s).
    lambda: _even(_mp3, "m", ".mp3", 30_000_000, 6) + _text(6, 5_000_000),
    # 60 MB of Ogg, which balrogg repacks: ~5 min, and never part of the check.
    lambda: _even(_ogg, "g", ".ogg", 60_000_000, 10),
], ids=["cmyk+text", "mp3+text", "ogg"])
def test_a_small_folder_is_promised_seconds_only_if_the_job_takes_seconds(make):
    """The sentence read the recoded files alone, so a folder that was half
    something else, or Ogg that balrogg repacks, was told "seconds" beside a
    table saying minutes."""
    from excmp.estimate import estimate_time
    infos = make()
    summary, (profile, reason) = _suggestion(infos)
    t = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS))
    assert profile is Profile.EXTREME and t.expected >= 60
    assert "costs seconds" not in reason and "minutes" in reason, reason


def test_lepton_s_fit_holds_on_a_corpus_it_was_not_fitted_to():
    """The design folder's 24 photos lepton takes (15.8 MB) packed in 4.6,
    4.5 and 6.3 s; the contended prior said 7.8 s."""
    infos = _even(_jpeg, "p", ".jpg", 15_786_950, 24)
    cost = pack_cost(infos, plan(infos, Profile.FAST, TOOLS), JPEG)
    assert 4.5 / 1.15 <= cost.seconds <= 6.3 * 1.15, cost.seconds


def test_a_small_folder_without_recoded_media_is_still_promised_seconds():
    summary, (profile, reason) = _suggestion(_text(10, 2_000_000))
    assert summary.strongest_recode_seconds == 0
    assert profile is Profile.EXTREME and "costs seconds" in reason


#: Lepton's phases at Fast, medians of three: (files, bytes, pack s, D9 s).
LEPTON = {"phone": (150, 49_138_142, 21.6, 13.3), "web": (299, 20_437_711, 19.2, 14.1)}


@pytest.mark.parametrize("corpus", sorted(LEPTON))
def test_lepton_s_phases_match_a_quiet_run(corpus):
    n, total, pack_s, decode_s = LEPTON[corpus]
    infos = _even(_jpeg, "p", ".jpg", total, n)
    cost = pack_cost(infos, plan(infos, Profile.FAST, TOOLS), JPEG)
    assert cost.jpeg_bytes == (total // n) * n
    assert pack_s / 1.15 <= cost.seconds <= pack_s * 1.15, cost.seconds
    assert decode_s / 1.15 <= cost.verify_seconds <= decode_s * 1.15, cost.verify_seconds
