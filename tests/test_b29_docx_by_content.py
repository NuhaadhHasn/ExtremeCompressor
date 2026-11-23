"""B29: a ``.docx`` is priced at Insane by what its central directory counts, not at the chain's rate.

B27 measured B5's types at Insane. ``.docx`` was the one that landed outside the chain model on the
unsafe side: 4,632 s measured against a chain range of 1,023-3,567 s (2.84x the expected). A second,
independent corpus (55 files, 43.8 MB, 73% PNG by bytes) took 1,794 s against 560-1,954 s (2.01x the
expected, at the very top of the range). The container model (B26) priced both inside its range:
0.97x and 0.78x of its expected, on the safe side. So ``.docx`` leaves the chain-rate list for TIME.

Only the time: the *size* ratio stays B5's measured one, and the planner's piping is untouched.
``.xlsx`` (PNG 6.1 MB in a 7.2 MB corpus, container 3.4x over) and ``.pptx`` (mostly JPEG, 1.64x chain,
1.41x container) are not lifted: one corpus each, and the container model is no better for them.

The counts below are what the probe read on the two real corpora (``analyze_file`` summed over files).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import Rates, estimate_time, recode_cost
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t") for n in ("7z", "precomp", "zpaqfranz")}
NO_PACK = Rates(ogg_pack=False, jpeg_pack=False)


def _docx(name, size, deflated, png, jpeg, other):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0,
                    expandable=True, zip_deflated_bytes=deflated, zip_png_bytes=png,
                    zip_jpeg_bytes=jpeg, zip_other_bytes=other)


#: bytes, deflated, PNG, JPEG, other - the probe's counts for each corpus, one aggregate entry each.
CORPORA = {
    "docx-b27": (lambda: [_docx("a.docx", 79_992_142, 20_292_930, 71_745_339, 5_740_808, 88_212)], 4_632.0),
    "docx2": (lambda: [_docx("b.docx", 43_759_565, 34_617_758, 32_053_303, 6_474_495, 226_629)], 1_794.0),
}


def _insane(corpus):
    infos = CORPORA[corpus][0]()
    return infos, estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), NO_PACK)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_both_docx_corpora_sit_inside_the_range(corpus):
    _, t = _insane(corpus)
    measured = CORPORA[corpus][1]
    assert t.low <= measured <= t.high, (corpus, measured, t.low, t.expected, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_expected_figure_is_within_a_band_of_both_measured_rows(corpus):
    """0.97x and 0.78x of the real runs with this model. The band is 0.6x-1.6x: set after seeing
    both corpora, so a regression pin, not validation (and the chain rate it replaced was 0.35x-0.50x)."""
    _, t = _insane(corpus)
    measured = CORPORA[corpus][1]
    assert measured / 1.6 <= t.expected <= measured / 0.6, (corpus, t.expected, measured)


def test_a_png_dominant_docx_is_billed_at_its_own_rates_and_the_other_b5_types_are_not():
    for name, own in (("a.docx", True), ("b.xlsx", False), ("c.pptx", False),
                      ("d.zip", False), ("e.jar", False), ("f.apk", False)):
        info = _docx(name, 10_000_000, 3_000_000, 8_000_000, 0, 0)
        the_plan = plan([info], Profile.INSANE, TOOLS)
        assert (recode_cost([info], the_plan).own_bytes > 0) is own, name


def test_a_docx_with_little_png_keeps_the_chain_rate():
    """The container price of a JPEG-heavy docx is ~3x below the chain's, on a JPEG rate that rests on
    one album: no evidence, so it stays at the chain's rate (the safer, higher one). The reviewer
    of B29 reproduced this: 20 MB of JPEG went 409 s -> 138 s expected before the PNG-share rule."""
    jpeg = _docx("photos.docx", 20_000_000, 100_000, 0, 19_800_000, 0)
    text = _docx("memo.docx", 2_000_000, 8_000_000, 0, 0, 0)
    for info in (jpeg, text):
        the_plan = plan([info], Profile.INSANE, TOOLS)
        assert recode_cost([info], the_plan).own_bytes == 0, info.path.name
    chain = _docx("photos.xlsx", 20_000_000, 100_000, 0, 19_800_000, 0)
    the_plan = plan([chain], Profile.INSANE, TOOLS)
    t_chain = estimate_time([chain], the_plan, NO_PACK)
    t_docx = estimate_time([jpeg], plan([jpeg], Profile.INSANE, TOOLS), NO_PACK)
    assert (t_docx.low, t_docx.expected, t_docx.high) == (t_chain.low, t_chain.expected, t_chain.high)


def test_the_png_share_is_by_bytes_at_the_threshold():
    from excmp.estimate import _DOCX_PNG_SHARE
    assert _DOCX_PNG_SHARE == 0.5
    at = _docx("at.docx", 10_000_000, 5_000_000, 5_000_000, 0, 0)
    below = _docx("below.docx", 10_000_000, 5_000_001, 4_999_999, 0, 0)
    assert recode_cost([at], plan([at], Profile.INSANE, TOOLS)).own_bytes > 0
    assert recode_cost([below], plan([below], Profile.INSANE, TOOLS)).own_bytes == 0


def test_a_docx_the_probe_did_not_read_keeps_the_chain_rate():
    """No counts (a hand-built or unreadable file): still priced as before, never at zero."""
    info = _docx("x.docx", 10_000_000, 0, 0, 0, 0)
    the_plan = plan([info], Profile.INSANE, TOOLS)
    assert recode_cost([info], the_plan).own_bytes == 0
    assert estimate_time([info], the_plan, NO_PACK).expected > 100


def test_the_size_ratio_of_a_docx_is_still_b5s_measured_one():
    from excmp.estimate import _EXPANDABLE_EXPECTED, estimate_size
    info = _docx("report.docx", 10_000_000, 30_000_000, 0, 0, 0)
    est = estimate_size([info], plan([info], Profile.EXTREME, TOOLS))
    assert (est.expected - est.overhead_bytes) / info.size == pytest.approx(_EXPANDABLE_EXPECTED, abs=0.001)


@pytest.mark.parametrize("profile", [Profile.NORMAL, Profile.EXTREME])
@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_only_insane_reads_the_counts(profile, corpus):
    infos = CORPORA[corpus][0]()
    bare = [FileInfo(**{**infos[0].__dict__, "zip_deflated_bytes": 0, "zip_png_bytes": 0,
                        "zip_jpeg_bytes": 0, "zip_other_bytes": 0})]
    a = estimate_time(infos, plan(infos, profile, TOOLS), NO_PACK)
    b = estimate_time(bare, plan(bare, profile, TOOLS), NO_PACK)
    assert (a.low, a.expected, a.high) == (b.low, b.expected, b.high)


@pytest.mark.parametrize("profile", [Profile.NORMAL, Profile.EXTREME])
@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_below_insane_a_docx_is_priced_exactly_as_an_xlsx_with_the_same_counts(profile, corpus):
    """B5 measured .docx at Extreme and that figure stands: the lift is Insane's alone. (The first
    version of B29 moved Extreme too; a test that only compared files with and without counts
    missed it. This compares against a type that is still at the chain rate.)"""
    docx = CORPORA[corpus][0]()[0]
    xlsx = FileInfo(**{**docx.__dict__, "path": Path("same.xlsx")})
    a = estimate_time([docx], plan([docx], profile, TOOLS), NO_PACK)
    b = estimate_time([xlsx], plan([xlsx], profile, TOOLS), NO_PACK)
    assert (a.low, a.expected, a.high) == (b.low, b.expected, b.high)
    assert recode_cost([docx], plan([docx], profile, TOOLS)).own_bytes == 0
