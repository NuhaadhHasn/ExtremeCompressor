"""B30: JPEG members of a container are priced slower than a JPEG file on its own.

B26 priced a container's JPEG members at B22's plain-JPEG rate and checked it on one album (23 stored
photos, 91.4 s measured). Two more JPEG-dominant containers, run in B27/B29 on a quiet machine, ran
1.77x (a second album, 13.4 MB, 165.1 s) and 1.53x (six JPEG EPUBs, 60.9 MB, 684.1 s) over that model,
and a JPEG-heavy `.pptx` corpus ran 1.41x over. A JPEG inside a zip pays the unzip and the re-zip as
well as the recoder, so it is slower than the file. One factor over the three pure-JPEG corpora
(least squares in the log) is 1.45: measured / expected then reads 0.78x, 1.23x and 1.09x.

That is fitted on the very corpora asserted below, so these are regression pins, not validation. The
check that was not fitted: the `.pptx` corpus (still priced at the chain's rate, because it is a B5
type) comes closer, 1.41x -> 1.31x. A plain `.jpg` is untouched.

The counts are what the probe read on the real files (summed over each corpus).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import Rates, estimate_time
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t") for n in ("7z", "precomp", "zpaqfranz")}
NO_PACK = Rates(ogg_pack=False, jpeg_pack=False)


def _container(name, size, deflated, png, jpeg, other):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0,
                    expandable=True, zip_deflated_bytes=deflated, zip_png_bytes=png,
                    zip_jpeg_bytes=jpeg, zip_other_bytes=other)


#: bytes, deflated, PNG, JPEG, other -> measured quiet seconds (compress + the D9 gate).
CORPORA = {
    "album": (lambda: [_container("a.epub", 11_620_228, 6_230, 0, 11_617_184, 20)], 91.4),
    "album2": (lambda: [_container("b.cbz", 13_357_418, 0, 0, 13_355_596, 0)], 165.1),
    "jpeg2": (lambda: [_container("c.epub", 60_917_061, 8_198_049, 0, 58_975_946, 120)], 684.1),
}


def _insane(corpus, name=None):
    infos = CORPORA[corpus][0]()
    return estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), NO_PACK)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_quiet_run_sits_in_the_range(corpus):
    t = _insane(corpus)
    assert t.low <= CORPORA[corpus][1] <= t.high, (corpus, t.low, t.expected, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_measured_over_expected_is_within_0_7x_and_1_35x(corpus):
    """Before: 1.13x, 1.77x, 1.53x. After: 0.78x, 1.23x, 1.09x."""
    t = _insane(corpus)
    ratio = CORPORA[corpus][1] / t.expected
    assert 0.7 <= ratio <= 1.35, (corpus, ratio)


def test_a_plain_jpeg_file_keeps_its_own_rate():
    """B22's rate is for the file by itself and is untouched."""
    from excmp.estimate import _INSANE_RECODE_RATE
    assert _INSANE_RECODE_RATE["jpeg"] == 0.277e6


def test_the_slowdown_is_one_named_constant_in_a_measured_band():
    from excmp.estimate import _ZIP_JPEG_SLOWDOWN
    assert 1.3 <= _ZIP_JPEG_SLOWDOWN <= 1.6


@pytest.mark.parametrize("profile", [Profile.NORMAL, Profile.EXTREME])
def test_only_insane_reads_it(profile):
    infos = CORPORA["jpeg2"][0]()
    bare = [FileInfo(**{**infos[0].__dict__, "zip_jpeg_bytes": 0})]
    a = estimate_time(infos, plan(infos, profile, TOOLS), NO_PACK)
    b = estimate_time(bare, plan(bare, profile, TOOLS), NO_PACK)
    assert (a.low, a.expected, a.high) == (b.low, b.expected, b.high)
