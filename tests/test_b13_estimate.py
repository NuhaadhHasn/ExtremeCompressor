"""B13: the estimate has to know that packing Ogg audio is slow.

Stored files were costed as a plain copy at exactly 1.0, which was right for a
folder of videos and harmless for FLAC and lepton, which run at tens of MB/s.
balrogg encodes at ~0.1-0.3 MB/s at ``-9``: a 1 GB folder of Vorbis is about
an hour, and an estimate that said "a few seconds" because the files are
"stored" would be worse than having no estimate at all. The numbers below are
priors from 18 real music files and one machine whose speed varied 3.5x within
a session, so every time is a range and the range is wide.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import (DEFAULT_RATES, Rates, compare_profiles,
                            estimate_size, estimate_time, pack_cost, time_split)
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
WITH = Rates(ogg_pack=True)
WITHOUT = Rates(ogg_pack=False)


@pytest.fixture(autouse=True)
def _balrogg_is_installed_in_the_plan(monkeypatch):
    """The plan routes Ogg to the store route only when balrogg is installed;
    these tests describe that machine, so they say so."""
    from excmp import oggpack
    monkeypatch.setattr(oggpack, "available", lambda: True)


def _ogg(name, size, ext=".ogg"):
    return FileInfo(path=Path(f"{name}{ext}"), size=size, category=Category.AUDIO,
                    entropy_bps=7.97, sample_ratio=1.0, sample_ratio_max=1.0)


def _video(name, size):
    return FileInfo(path=Path(f"{name}.mp4"), size=size, category=Category.VIDEO,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0)


def _plan(infos, profile=Profile.NORMAL):
    return plan(infos, profile, TOOLS)


# -- size ----------------------------------------------------------------------

def test_ogg_audio_is_predicted_smaller_not_copied_at_exactly_one():
    infos = [_ogg("a", 100_000_000), _ogg("b", 50_000_000)]
    size = estimate_size(infos, _plan(infos), WITH)
    assert size.packed_bytes == 150_000_000
    assert size.low < size.expected < size.high <= size.total_bytes + 1_000_000
    # Measured 15.1% on 13 Vorbis files; the expectation is near that, and the
    # honest range is wide because it ran from 9.5% to 25.7% file by file.
    assert 0.10 < size.saved_fraction < 0.20
    assert (size.total_bytes - size.low) / size.total_bytes > 0.20


def test_opus_is_predicted_to_shrink_far_less_than_vorbis():
    vorbis = estimate_size([_ogg("v", 50_000_000)], _plan([_ogg("v", 50_000_000)]), WITH)
    opus_info = [_ogg("o", 50_000_000, ".opus")]
    opus = estimate_size(opus_info, _plan(opus_info), WITH)
    assert opus.saved_fraction < 0.06 < 0.10 < vorbis.saved_fraction


def test_without_balrogg_the_estimate_is_what_it_always_was():
    infos = [_ogg("a", 100_000_000), _video("v", 100_000_000)]
    size = estimate_size(infos, _plan(infos), WITHOUT)
    assert size.packed_bytes == 0
    assert size.expected == size.stored_bytes + size.overhead_bytes


def test_only_ogg_is_predicted_other_stored_files_stay_exact():
    infos = [_ogg("a", 100_000_000), _video("v", 100_000_000)]
    size = estimate_size(infos, _plan(infos), WITH)
    assert size.packed_bytes == 100_000_000
    # The video is still copied at exactly 1.0 inside the expectation.
    assert size.expected >= 100_000_000 + int(100_000_000 * 0.74)


def test_the_estimate_matches_what_the_measurement_found():
    """18 real files, 169,975,314 B: Vorbis 143,546,732 B saved 15.100%, Opus
    26,428,582 B saved 3.893% - 13.358% together. The prior must land close,
    and the measured whole must sit inside the range."""
    infos = [_ogg("vorbis", 143_546_732), _ogg("opus", 26_428_582, ".opus")]
    size = estimate_size(infos, _plan(infos, Profile.INSANE), WITH)  # measured at -9
    measured_out = 147_270_639
    assert size.low <= measured_out <= size.high
    assert abs(size.expected - measured_out) / measured_out < 0.03


# -- time ----------------------------------------------------------------------

def test_a_folder_of_vorbis_is_not_estimated_as_a_copy():
    infos = [_ogg(f"a{i}", 100_000_000) for i in range(10)]   # 1 GB
    without = estimate_time(infos, _plan(infos), WITHOUT).expected
    with_pack = estimate_time(infos, _plan(infos), WITH)
    assert without < 60                      # a copy and a hash: seconds
    assert with_pack.expected > 600          # 1 GB at ~0.1-1 MB/s: an hour-ish
    assert with_pack.low < with_pack.expected < with_pack.high
    assert with_pack.high / with_pack.low > 3


def test_the_effort_follows_the_profile_and_so_does_the_time():
    infos = [_ogg("a", 200_000_000)]
    seconds = {p: estimate_time(infos, _plan(infos, p), WITH).expected
               for p in (Profile.FAST, Profile.NORMAL, Profile.EXTREME, Profile.INSANE)}
    assert (seconds[Profile.FAST] < seconds[Profile.NORMAL]
            < seconds[Profile.EXTREME] < seconds[Profile.INSANE])


def test_opus_packs_far_faster_than_vorbis():
    """Measured: Opus encodes ten times quicker (1.34 vs 0.119 MB/s at -9).
    Decoding costs the same for both, so at a low effort the difference is
    smaller than ten and at Insane's -9 it is large."""
    for profile, factor in ((Profile.NORMAL, 0.6), (Profile.INSANE, 0.25)):
        v_info = [_ogg("v", 100_000_000)]
        o_info = [_ogg("o", 100_000_000, ".opus")]
        vorbis = pack_cost(v_info, _plan(v_info, profile), WITH)
        opus = pack_cost(o_info, _plan(o_info, profile), WITH)
        assert opus.seconds < vorbis.seconds * factor, profile
        assert opus.verify_seconds == vorbis.verify_seconds


def test_the_restore_check_pays_for_decoding_every_packed_file_again():
    """D9 restores the whole archive before publishing, and a packed entry is
    restored by running balrogg's decoder. That is on top of the decode inside
    `pack` that proves the file."""
    infos = [_ogg("a", 150_000_000)]
    cost = pack_cost(infos, _plan(infos), WITH)
    assert cost.verify_seconds > 30
    compress_s, verify_s = time_split(150_000_000, 0, [], WITH, pack=cost)
    assert verify_s >= cost.verify_seconds
    assert compress_s >= cost.seconds


def test_time_split_without_a_pack_cost_is_unchanged():
    assert time_split(10_000_000, 2_000_000, ["sevenzip"], DEFAULT_RATES) == \
        time_split(10_000_000, 2_000_000, ["sevenzip"], DEFAULT_RATES, pack=None)


def test_no_ogg_means_no_pack_cost():
    infos = [_video("v", 100_000_000)]
    cost = pack_cost(infos, _plan(infos), WITH)
    assert (cost.bytes, cost.seconds, cost.verify_seconds) == (0, 0.0, 0.0)


def test_the_comparison_table_shows_the_profiles_differ_for_an_ogg_folder():
    infos = [_ogg("a", 300_000_000)]
    rows = {r.profile: r for r in compare_profiles(infos, TOOLS, WITH)}
    assert rows[Profile.FAST].time.expected < rows[Profile.INSANE].time.expected
    assert all(r.size.packed_bytes == 300_000_000 for r in rows.values())


def test_the_second_corpus_also_sits_inside_the_range():
    """Corpus 2 (26 game-music and speech files, 192,105,873 B, balrogg -5):
    25 Vorbis files at 153,119,905 B and one Opus at 38,985,968 B came out at
    171,127,274 B - 10.920% saved, with two files refused. The prior was fitted
    on corpus 1, so this is the check that it was not fitted *to* it."""
    infos = [_ogg("vorbis", 153_119_905), _ogg("opus", 38_985_968, ".opus")]
    size = estimate_size(infos, _plan(infos, Profile.EXTREME), WITH)  # measured at -5
    measured_out = 171_127_274
    assert size.low <= measured_out <= size.high
    assert abs(size.expected - measured_out) / measured_out < 0.03


# -- review fixes -------------------------------------------------------------------

def test_a_lower_effort_is_predicted_to_save_less():
    """Fast packs at -1, which measured 9.448% against -9's 11.586%. Every row
    of the table used to predict -9's saving (review, B13)."""
    infos = [_ogg("a", 100_000_000)]
    saved = {p: estimate_size(infos, _plan(infos, p), WITH).saved_fraction
             for p in (Profile.FAST, Profile.NORMAL, Profile.INSANE)}
    assert saved[Profile.FAST] < saved[Profile.NORMAL] < saved[Profile.INSANE]
    assert saved[Profile.FAST] / saved[Profile.INSANE] == pytest.approx(0.815, abs=0.01)


def test_the_pessimistic_end_is_no_gain_at_all():
    """pack never returns bytes that are not smaller, and a declined file is
    stored as it is, so the worst case is the original size. The disk
    preflight books `high`; anything under 1.0 let it under-reserve."""
    infos = [_ogg("a", 100_000_000), _ogg("o", 50_000_000, ".opus")]
    size = estimate_size(infos, _plan(infos), WITH)
    assert size.high >= size.stored_bytes


def test_files_outside_balrogg_s_size_window_are_not_predicted_to_shrink():
    from excmp import oggpack

    tiny = [_ogg("t", oggpack.MIN_SIZE - 1)]
    size = estimate_size(tiny, _plan(tiny), WITH)
    assert size.packed_bytes == 0
    assert pack_cost(tiny, _plan(tiny), WITH).bytes == 0


def test_thousands_of_small_files_cost_more_than_their_bytes_suggest():
    many = [_ogg(f"s{i}", 20_000) for i in range(2000)]
    one = [_ogg("big", 40_000_000)]
    assert (pack_cost(many, _plan(many), WITH).seconds
            > pack_cost(one, _plan(one), WITH).seconds + 500)
