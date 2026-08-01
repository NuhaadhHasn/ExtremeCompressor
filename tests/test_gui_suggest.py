"""The analysis summary and the honesty copy built on top of it."""

import random

from pathlib import Path

from excmp.analyzer import Category, FileInfo, analyze_tree
from excmp.estimate import compare_profiles
from excmp.planner import Profile, plan as make_plan
from excmp.tools import find_tools
from gui.suggest import (AnalysisSummary, comparison_caption, gain_note,
                         headline, profile_comparison, recommend_profile,
                         recommend_with_estimates, shrink_mode_hint,
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


def test_srep_alone_is_no_longer_a_reason_to_go_extreme():
    """B11: SREP is out of every chain, so its presence on the machine buys the
    Extreme profile nothing - only Precomp does. Before the change, a machine
    with srep but no precomp was steered into a chain identical to Normal."""
    from gui.suggest import strongest_profile
    from excmp.tools import ToolInfo

    srep_only = {"7z": ToolInfo("7z", "x"), "srep": ToolInfo("srep", "x"),
                 "precomp": None}
    assert strongest_profile(srep_only) is Profile.NORMAL

    summary = _fake(2 * 1024**3, 0, tools={"7z": True, "precomp": False, "srep": True})
    assert recommend_profile(summary, cores=8)[0] is Profile.NORMAL


def test_recommendation_is_not_circular():
    """A folder of zlib-wrapped game paks looks ~90% incompressible to Normal
    (no Precomp) but is mostly compressible under Extreme. Recommending Fast
    here would talk the user out of the one profile that helps."""
    total = 2 * 1024**3
    summary = _fake(total, store=int(total * 0.9), floor=int(total * 0.08))
    profile, _reason = recommend_profile(summary, cores=8)
    assert profile is Profile.EXTREME


# ---------------------------------------------------------------------------
# The comparison table (J3)
# ---------------------------------------------------------------------------

_TOOLS = {"7z": object(), "precomp": object(), "srep": object()}

# The 2026-08-01 corpus by the numbers, with sample ratios measured off the real
# files - the run where Extreme cost 2.7x Normal's time for 0.17 points.
_REAL = [
    ("R-4.5.1-win.exe", 90_111_968, Category.EXECUTABLE, 7.78, 0.8231, 1.0),
    ("Windows-KB890830.exe", 76_629_432, Category.EXECUTABLE, 7.93, 0.9594, 1.0),
    ("lghub_installer.exe", 58_146_712, Category.EXECUTABLE, 6.51, 0.4411, 0.7772),
    ("DB.Browser.msi", 19_783_680, Category.BINARY, 7.99, 0.9690, 1.0),
    ("Winxvideo.rar", 212_734_622, Category.COMPRESSED_ARCHIVE, 8.00, 1.0, 1.0),
    ("Wondershare.zip", 263_670_338, Category.COMPRESSED_ARCHIVE, 8.00, 1.0, 1.0),
]


def _real_infos():
    return [FileInfo(path=Path(n), size=s, category=c, entropy_bps=e,
                     sample_ratio=mean, sample_ratio_max=mx)
            for n, s, c, e, mean, mx in _REAL]


def _real_summary(infos):
    weak = make_plan(infos, Profile.NORMAL, _TOOLS)
    strong = make_plan(infos, Profile.EXTREME, _TOOLS)
    return summarize(infos, weak, _TOOLS, strong)


def test_comparison_shows_every_profile_with_a_size_and_a_time():
    infos = _real_infos()
    rows = profile_comparison(infos, _TOOLS, _real_summary(infos), cores=2)

    assert [r.profile for r in rows] == list(Profile)
    for row in rows:
        assert row.size_text and row.time_text and row.chain
        # A range is either a real span or absent - never a restatement of the
        # value above it.
        for span, value in ((row.size_range, row.size_text),
                            (row.time_range, row.time_text)):
            assert span == "" or "–" in span
            assert span != value.lstrip("≤~ ").replace("about ", "")


def test_exactly_one_row_is_recommended_and_it_owns_the_reason():
    """One recommendation, one reason, one source of truth. The table must not
    decide separately, or the highlighted row and the preset card's badge could
    disagree about what the app is advising."""
    infos = _real_infos()
    summary = _real_summary(infos)
    estimates = compare_profiles(infos, _TOOLS)
    expected, reason = recommend_with_estimates(summary, estimates, cores=2)
    rows = profile_comparison(infos, _TOOLS, summary, cores=2)

    marked = [r for r in rows if r.recommended]
    assert len(marked) == 1
    assert marked[0].profile is expected
    assert marked[0].reason == reason
    assert all(not r.reason for r in rows if not r.recommended)


def test_the_estimate_defers_to_the_heuristic_when_nothing_is_flagged():
    """The override is a guard, not a second opinion: with no bad trade to
    correct, the recommendation is the heuristic's, reason and all."""
    infos = [FileInfo(path=Path(f"pak{i}.pak"), size=200_000_000,
                      category=Category.BINARY, entropy_bps=7.99,
                      zlib_stream=True, sample_ratio=1.0, sample_ratio_max=1.0)
             for i in range(3)]
    summary = _real_summary(infos)
    estimates = compare_profiles(infos, _TOOLS)
    assert (recommend_with_estimates(summary, estimates, cores=8)
            == recommend_profile(summary, cores=8))


def test_the_bad_trade_is_spelled_out_on_the_row():
    infos = _real_infos()
    rows = {r.profile: r for r in profile_comparison(infos, _TOOLS,
                                                     _real_summary(infos), cores=2)}
    extreme = rows[Profile.EXTREME]
    assert "Normal" in extreme.note and "quicker" in extreme.note
    assert not rows[Profile.NORMAL].note
    # Extreme is recommended here *and* flagged - both are true, and the
    # recommendation must not be allowed to bury the caveat that qualifies it.
    assert extreme.recommended and extreme.reason and extreme.note


def test_a_conditional_flag_warns_but_does_not_demote_the_recommendation():
    """Measured both ways, which is why this rule exists. On this corpus Precomp
    found nothing and Extreme cost 2.7x for 0.17 points. On a 163 MB installer
    corpus with an indistinguishable probe reading, Precomp found plenty and
    Extreme delivered 41.4% against Normal's 7.3%.

    So a Precomp-chain flag is a warning, never a demotion: the row says "if
    Precomp cannot open these streams...", and the user decides. Overruling here
    would have cost that second corpus 34 percentage points."""
    infos = _real_infos()
    summary = _real_summary(infos)
    assert recommend_profile(summary, cores=2)[0] is Profile.EXTREME

    rows = profile_comparison(infos, _TOOLS, summary, cores=2)
    marked = next(r for r in rows if r.recommended)
    assert marked.profile is Profile.EXTREME
    # Asserted on meaning, not wording: the warning must name Precomp as the
    # condition, so it reads as "it depends" rather than "do not do this".
    assert "Precomp" in marked.note


def test_an_unconditional_flag_does_overrule():
    """When Precomp is not in the picture there is no hidden upside, so a profile
    that costs twice the time for nothing gets demoted outright."""
    from excmp.estimate import DEFAULT_RATES, Rates

    infos = _real_infos()
    summary = _real_summary(infos)
    # Injected rates (the J7 seam) make plain 7-Zip four times slower than zstd,
    # so Normal becomes an unconditional bad trade against Fast.
    key = Rates.chain_key(["sevenzip"])
    crawling = Rates(codec={**DEFAULT_RATES.codec, key: DEFAULT_RATES.codec[key] / 8})

    rows = profile_comparison(infos, _TOOLS, summary, cores=2, rates=crawling)
    normal = next(r for r in rows if r.profile is Profile.NORMAL)
    assert normal.note and not normal.note.startswith("If Precomp")
    assert not any(r.recommended and r.profile is Profile.NORMAL for r in rows)


def test_the_caption_points_at_the_flagged_rows_without_repeating_them():
    """Seen on screen, a caption that restated the row's warning printed the same
    sentence three times in one panel. It names the rows instead."""
    infos = _real_infos()
    rows = profile_comparison(infos, _TOOLS, _real_summary(infos), cores=2)
    caption = comparison_caption(rows)

    assert "Extreme" in caption and "Insane" in caption
    flagged = next(r for r in rows if r.note)
    assert flagged.note not in caption


def test_a_precomp_row_says_at_most_rather_than_about():
    """The Extreme estimate assumes Precomp finds nothing, so it is a ceiling.
    Printing it as a point estimate would be the one dishonest thing this whole
    table exists to avoid."""
    infos = _real_infos()
    rows = {r.profile: r for r in profile_comparison(infos, _TOOLS,
                                                     _real_summary(infos), cores=2)}
    assert rows[Profile.EXTREME].size_text.startswith("≤")
    assert "or better" in rows[Profile.EXTREME].saved_text
    # Normal has no Precomp, so its estimate is an ordinary prediction.
    assert rows[Profile.NORMAL].size_text.startswith("about ")
    assert "or better" not in rows[Profile.NORMAL].saved_text


def test_the_precomp_warning_is_stated_as_a_condition():
    """'Extreme is not worth it' would be a lie on repack data, where Precomp is
    the whole point. The row has to make Precomp the condition, and stay one
    sentence - it is repeated on every flagged row."""
    infos = _real_infos()
    rows = {r.profile: r for r in profile_comparison(infos, _TOOLS,
                                                     _real_summary(infos), cores=2)}
    note = rows[Profile.EXTREME].note
    assert "Precomp" in note and "otherwise" in note
    # One sentence. Counting "." would trip over the "5.7x" multiplier, so look
    # for a real sentence break instead.
    assert ". " not in note, f"one sentence, got: {note}"


def test_the_caption_stays_neutral_when_every_profile_earns_its_time():
    infos = [FileInfo(path=Path(f"pak{i}.pak"), size=200_000_000,
                      category=Category.BINARY, entropy_bps=7.99,
                      zlib_stream=True, sample_ratio=1.0, sample_ratio_max=1.0)
             for i in range(3)]
    rows = profile_comparison(infos, _TOOLS, _real_summary(infos), cores=8)
    caption = comparison_caption(rows)
    assert "not worth it" not in caption
    assert "ranges, not promises" in caption


def test_a_not_yet_wired_backend_is_disclosed_on_its_row():
    """Insane shows the same chain and the same numbers as Extreme, so the row
    has to explain why - naming the missing backend, not leaking the planner's
    log sentence into the UI."""
    infos = _real_infos()
    rows = {r.profile: r for r in profile_comparison(infos, _TOOLS,
                                                     _real_summary(infos), cores=2)}
    caveat = rows[Profile.INSANE].caveat
    assert "zpaqfranz" in caveat
    assert "Extreme" in caveat
    assert "stage" not in caveat and "insane:" not in caveat, "engine vocabulary leaked"
    assert len(caveat) < 60, f"chain column needs a phrase, not a sentence: {caveat}"


def test_a_missing_tool_is_named_in_the_caveat():
    """With nothing installed every profile silently degrades to Zstandard. The
    chain column shows what will run; the caveat has to name what is absent, or
    the user cannot tell a deliberate Fast from a broken Normal."""
    infos = _real_infos()
    nothing = {"7z": None, "precomp": None, "srep": None}
    rows = {r.profile: r for r in profile_comparison(infos, nothing,
                                                     _real_summary(infos), cores=2)}
    assert rows[Profile.NORMAL].chain == "Zstandard"
    assert "7z" in rows[Profile.NORMAL].caveat
    assert not rows[Profile.FAST].caveat, "Fast wanted no external tool"


def test_no_input_means_no_table():
    assert profile_comparison([], _TOOLS, _real_summary(_real_infos())) == []
    assert comparison_caption([]) == ""


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
