"""The analysis summary and the honesty copy built on top of it."""

import random

from excmp.analyzer import Category, analyze_tree
from excmp.planner import Profile, plan as make_plan
from excmp.tools import find_tools
from gui.suggest import (AnalysisSummary, gain_note, headline,
                         recommend_profile, shrink_mode_hint,
                         store_explanations, summarize)


def _summary_for(root, profile=Profile.NORMAL):
    tools = find_tools()
    infos = analyze_tree(root)
    return summarize(infos, make_plan(infos, profile, tools), tools)


def _media_tree(root):
    rng = random.Random(3)
    root.mkdir()
    (root / "movie.mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom" + bytes(rng.getrandbits(8) for _ in range(500_000)))
    (root / "notes.txt").write_text("hello world\n" * 500)
    return root


def _text_tree(root):
    root.mkdir()
    for i in range(4):
        (root / f"doc{i}.txt").write_text("the quick brown fox. " * 20_000)
    return root


def test_summary_splits_stored_from_pipelined(tmp_path):
    summary = _summary_for(_media_tree(tmp_path / "mixed"))
    assert summary.file_count == 2
    assert summary.total_bytes == summary.store_bytes + summary.pipeline_bytes
    assert summary.store_by_category[Category.VIDEO] > 0
    assert Category.TEXT not in summary.store_by_category
    assert 0.9 < summary.store_fraction < 1.0


def test_every_stored_file_carries_a_reason(tmp_path):
    summary = _summary_for(_media_tree(tmp_path / "mixed"))
    names = [name for name, _size, _reason in summary.store_files]
    assert names == ["movie.mp4"]
    _name, reason = store_explanations(summary)[0]
    assert "media file" in reason and "quality is untouched" in reason


def test_headline_and_gain_note_are_specific(tmp_path):
    summary = _summary_for(_media_tree(tmp_path / "mixed"))
    text = headline(summary)
    assert "2 files" in text and "video" in text
    assert "already compressed" in gain_note(summary)
    assert "video/audio" in (shrink_mode_hint(summary) or "")


def test_no_shrink_hint_when_there_is_no_media(tmp_path):
    assert shrink_mode_hint(_summary_for(_text_tree(tmp_path / "docs"))) is None


def test_chain_reflects_the_profile(tmp_path):
    root = _text_tree(tmp_path / "docs")
    tools = find_tools()
    if tools.get("7z") is None:
        return
    assert _summary_for(root, Profile.NORMAL).chain == ["sevenzip"]
    assert _summary_for(root, Profile.FAST).chain == ["zstd"]


def _fake(total, store, floor=None, **kwargs):
    """``floor`` defaults to ``store``: the common case where the selected
    profile already routes as well as any profile could."""
    return AnalysisSummary(
        total_bytes=total, file_count=kwargs.get("files", 10),
        by_category=kwargs.get("by_category", {}),
        store_by_category={}, store_bytes=store, pipeline_bytes=total - store,
        store_files=[], warnings=[], chain=["sevenzip"],
        tools=kwargs.get("tools", {"7z": True, "precomp": True, "srep": True}),
        floor_store_bytes=store if floor is None else floor,
    )


def test_incompressible_pile_gets_the_fast_recommendation():
    profile, reason = recommend_profile(_fake(50 * 1024**3, 49 * 1024**3), cores=2)
    assert profile is Profile.FAST
    assert "already compressed" in reason


def test_small_job_takes_the_best_ratio():
    profile, _reason = recommend_profile(_fake(10 * 1024**2, 0), cores=2)
    assert profile is Profile.EXTREME


def test_huge_job_on_a_small_cpu_backs_off():
    profile, reason = recommend_profile(_fake(40 * 1024**3, 0), cores=2)
    assert profile is Profile.NORMAL
    assert "hours" in reason


def test_big_compressible_job_on_a_real_cpu_goes_extreme():
    profile, _reason = recommend_profile(_fake(2 * 1024**3, 0), cores=8)
    assert profile is Profile.EXTREME


def test_recommendation_backs_off_without_the_repack_tools():
    summary = _fake(2 * 1024**3, 0, tools={"7z": True, "precomp": False, "srep": False})
    assert recommend_profile(summary, cores=8)[0] is Profile.NORMAL


def test_recommendation_is_not_circular():
    """A folder of zlib-wrapped game paks looks ~90% incompressible to Normal
    (no Precomp) but is mostly compressible under Extreme. Recommending Fast
    here would talk the user out of the one profile that helps."""
    total = 2 * 1024**3
    summary = _fake(total, store=int(total * 0.9), floor=int(total * 0.08))
    profile, _reason = recommend_profile(summary, cores=8)
    assert profile is Profile.EXTREME


def test_summary_floor_uses_the_reference_plan(tmp_path):
    """Same files, two plans: the floor must come from the stronger one."""
    tools = find_tools()
    if tools.get("precomp") is None:
        return
    root = tmp_path / "paks"
    root.mkdir()
    import zlib

    # The zlib *output* has to look like noise (entropy >= 7.9) or Normal
    # would happily pipeline it and there would be no gap to measure.
    rng = random.Random(11)
    for i in range(3):
        body = bytes(rng.getrandbits(8) for _ in range(120_000))
        (root / f"a{i}.pak").write_bytes(zlib.compress(body, 1))

    infos = analyze_tree(root)
    weak = make_plan(infos, Profile.NORMAL, tools)
    strong = make_plan(infos, Profile.EXTREME, tools)
    summary = summarize(infos, weak, tools, strong)

    assert summary.store_bytes > 0, "Normal should shelve these zlib paks"
    assert summary.floor_store_bytes < summary.store_bytes, \
        "Extreme reaches data Normal cannot, so the floor must be lower"
