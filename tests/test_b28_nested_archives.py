"""B28: archives inside archives, at Insane.

B26 priced a zip container by what Precomp expands it to, reading the central directory: the deflated
members' uncompressed size IS the `.pcf` for plain content (0.94-1.00 on 13 of 14 files). It flagged
one file that was not (`aar-01`: a deflated `libs/*.jar`, 0.50 of its `.pcf`) and said "priced about
2x low". B27's `.war` corpus (3 web apps, 16.9 MB, **99% nested jars**) measured it properly: 511.6 s
against a model that said 100 s, outside even the high end (398 s). A member that is itself an archive
is a deflate container whose OWN streams Precomp expands again (it recurses), so its bytes cost several
times a plain member's. `zip_nested_bytes` counts them, and the estimate prices them at
``_NESTED_FACTOR`` times the deflated rate.
"""

from __future__ import annotations

import random
import zipfile
from pathlib import Path

import pytest

from excmp import estimate
from excmp.analyzer import Category, FileInfo, analyze_file
from excmp.estimate import Rates, estimate_time, recode_cost, recoded_seconds
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
NO_PACK = Rates(ogg_pack=False, jpeg_pack=False)
_RNG = random.Random(28)


def _text(n=60_000, seed=1) -> bytes:
    rng = random.Random(seed)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 10)))
             for _ in range(20_000)]
    return " ".join(rng.choice(vocab) for _ in range(n)).encode()


def _with_members(path: Path, **members) -> Path:
    """A deflated page plus the given members (name -> (bytes, method))."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("WEB-INF/page.xhtml", _text())
        for name, (data, method) in members.items():
            zf.writestr(name, data, compress_type=method)
    return path


# -- the probe -------------------------------------------------------------------

@pytest.mark.parametrize("suffix", [".jar", ".JAR", ".zip", ".war", ".aar", ".apk", ".nupkg",
                                    ".ear", ".whl", ".vsix"])
def test_a_member_that_is_an_archive_is_counted_as_nested(tmp_path, suffix):
    p = _with_members(tmp_path / "app.war", **{f"WEB-INF/lib/dep{suffix}": (_RNG.randbytes(100_000), zipfile.ZIP_DEFLATED)})
    info = analyze_file(p)
    assert info.expandable is True
    assert 99_000 <= info.zip_nested_bytes <= 100_000
    assert info.zip_deflated_bytes == len(_text())        # the nested member is NOT also plain content


@pytest.mark.parametrize("name", ["lib/dep.jarx", "lib/dep.jar.txt", "lib/jar", "lib/dep.gz", "lib/dep.tar"])
def test_other_names_are_not_nested(tmp_path, name):
    p = _with_members(tmp_path / "app.war", **{name: (_RNG.randbytes(100_000), zipfile.ZIP_DEFLATED)})
    assert analyze_file(p).zip_nested_bytes == 0


def test_a_stored_nested_archive_is_counted_too(tmp_path):
    """Precomp finds the inner deflate streams whether or not the outer zip deflated the member."""
    p = _with_members(tmp_path / "app.war", **{"lib/dep.jar": (_RNG.randbytes(100_000), zipfile.ZIP_STORED)})
    info = analyze_file(p)
    assert info.zip_nested_bytes == 100_000 and info.zip_other_bytes == 0


def test_a_nested_archive_is_never_counted_past_what_it_can_hold(tmp_path):
    from tests.test_b26_zip_insane import _raw_zip
    p = _raw_zip(tmp_path / "x.war", [("a.xml", 8, 5_000, 20_000), ("lib/b.jar", 8, 100, 10 * 2**40),
                                       ("lib/c.jar", 0, 100, 10 * 2**40)], pad=5_200)
    info = analyze_file(p)
    assert info.zip_nested_bytes == 1032 * 100 + 100       # deflate's bound, and a stored member's own bytes


def test_a_member_cannot_claim_more_compressed_bytes_than_the_file_has(tmp_path):
    """Review (B28): a 226-byte `.war` claiming a `lib/b.jar` of 900,000 compressed
    bytes was priced at 26,465 s - the 1032:1 bound is applied to the *claimed*
    compressed size, and that claim was never checked against the file. The bytes
    a zip's members occupy cannot add up to more than the zip."""
    from tests.test_b26_zip_insane import _raw_zip
    p = _raw_zip(tmp_path / "lie.war", [("lib/b.jar", 8, 900_000, 10 * 2**40)])
    size = p.stat().st_size
    info = analyze_file(p)
    assert info.zip_nested_bytes <= 1032 * size


def test_members_that_claim_more_than_the_file_in_total_are_scaled_down(tmp_path):
    from tests.test_b26_zip_insane import _raw_zip
    p = _raw_zip(tmp_path / "lie2.war", [("a.xml", 8, 600, 10 * 2**30), ("lib/b.jar", 8, 600, 10 * 2**40),
                                          ("c.png", 8, 600, 10 * 2**30)], pad=0)
    size = p.stat().st_size
    info = analyze_file(p)
    held = info.zip_deflated_bytes + info.zip_nested_bytes + info.zip_png_bytes
    assert held <= 1032 * size


def test_a_hand_built_fileinfo_has_no_nested_bytes():
    info = FileInfo(path=Path("a.war"), size=10, category=Category.COMPRESSED_ARCHIVE, entropy_bps=7.99,
                    expandable=True)
    assert info.zip_nested_bytes == 0


# -- the pricing -------------------------------------------------------------------

def _container(name, size, deflated=0, nested=0, png=0, jpeg=0, other=0):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE, entropy_bps=7.99,
                    sample_ratio=1.0, sample_ratio_max=1.0, expandable=True,
                    zip_deflated_bytes=deflated, zip_png_bytes=png, zip_jpeg_bytes=jpeg,
                    zip_other_bytes=other, zip_nested_bytes=nested)


def _seconds(infos):
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    stages = [s for r in the_plan.routes if r.action == "pipeline" for s in r.stages]
    return recoded_seconds(recode_cost(infos, the_plan), stages)


def test_a_nested_byte_costs_the_nested_factor_times_a_deflated_one():
    plain = _seconds([_container("p.war", 10_000_000, deflated=10_000_000)])
    nested = _seconds([_container("n.war", 10_000_000, nested=10_000_000)])
    k = estimate._NESTED_FACTOR
    assert nested[0] == pytest.approx(plain[0] * k, rel=0.01)
    assert nested[1] == pytest.approx(plain[1] * k, rel=0.01)
    assert 2.0 <= k <= 4.5, "a nested byte is several times a plain one (measured 2.75-3.05), never 1 and never 20"


def test_a_container_with_only_nested_bytes_is_not_priced_as_unread():
    info = _container("n.war", 10_000_000, nested=10_000_000)
    assert recode_cost([info], plan([info], Profile.INSANE, TOOLS)).own_bytes == 10_000_000


def test_extreme_does_not_read_the_nested_count():
    import dataclasses
    info = _container("n.war", 10_000_000, nested=10_000_000)
    bare = dataclasses.replace(info, zip_nested_bytes=0)
    a = estimate_time([info], plan([info], Profile.EXTREME, TOOLS), NO_PACK)
    b = estimate_time([bare], plan([bare], Profile.EXTREME, TOOLS), NO_PACK)
    assert (a.low, a.expected, a.high) == (b.low, b.expected, b.high)


#: Measured, compress + D9, fastest of two rounds. B27's `.war` corpus: 3 files, 99% nested jars (round 1
#: read 512 s but the machine slept 6.9 h through it: its extract took 277 s against 96 s on round 2).
#: The synthetic nested corpus: one zip of archives.
WAR = dict(size=16_944_934, deflated=216_964, nested=18_026_265, seconds=300.0)
SYNTH = dict(size=10_114_161, deflated=31_726, nested=16_226_377, seconds=242.0)


@pytest.mark.parametrize("corpus", [WAR, SYNTH], ids=["war", "nested-synth"])
def test_both_nested_corpora_are_inside_their_range_and_near_the_expected(corpus):
    """Before B28 the war's expected was 100 s against 300 s measured."""
    info = _container("x.war", corpus["size"], deflated=corpus["deflated"], nested=corpus["nested"])
    t = estimate_time([info], plan([info], Profile.INSANE, TOOLS), NO_PACK)
    assert t.low <= corpus["seconds"] <= t.high, (t.low, t.expected, t.high)
    assert corpus["seconds"] / 1.3 <= t.expected <= corpus["seconds"] * 1.3, t.expected


def test_a_container_without_nested_members_is_priced_exactly_as_before():
    """B26's six corpora must not move: the nested count is 0 for all of them."""
    info = _container("x.aab", 121_000_789, deflated=346_149_382, png=1_459_915)
    t = estimate_time([info], plan([info], Profile.INSANE, TOOLS), NO_PACK)
    assert 1_201 <= t.low and t.expected == pytest.approx(1_956, abs=6)
