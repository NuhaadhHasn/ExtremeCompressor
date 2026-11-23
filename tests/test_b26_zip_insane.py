"""B26: the B20 zip containers at Insane, measured.

Insane (`precomp -cn -intense`, then zpaqfranz -m58) priced these containers at
the chain's one rate plus B20's old extra. Six corpora (176.5 MB) went through
engine.compress and engine.extract at Insane, 16 rows, every file restored
(docs/benchmarks/2026-11-20-b26-insane-containers.md). The input-byte rate was
no guide: seconds per input MB ran from 16 (AAB) to 80 (EPUB), because Precomp
hands zpaqfranz the *expanded* stream and that is 3x the input for a plain zip
(AAB, AAR, APPX, NuGet) and 6-18x for one full of PNGs (ODT, EPUB).

What predicts it is already in the central directory the probe opens:

* for plain deflate content the members' uncompressed sizes are the `.pcf`:
  0.94-1.00 of it on 13 of 14 files (NuGet, APPX, AAR, AAB); the 14th, an AAR
  holding a nested jar, is 0.50;
* PNG members are the rest. Precomp expands a PNG's inner deflate into pixels,
  6-106x per PNG byte - which a directory cannot show - so they are priced at
  what a standalone PNG costs at Insane (B22), measured on other corpora;
* JPEG members are priced at B22's JPEG rate (one album of 23 photographs ran
  within 16% of it), whatever else is in the zip at the chain's rate.

Rows (compress incl. D9, seconds; the fastest is the quiet figure):

    corpus     bytes        fastest   others
    nupkg       1,392,266     29.4     35.0, 313.2 (10.7x: beside a runaway
                                       `find` and a 0.6 GB memory squeeze)
    appx        6,015,103    138.4     183.2, 339.6
    aar         5,665,058    109.4     110.6, 135.4
    epub        5,686,653    455.4     589.6, 1,020.3
    odt-big    36,764,796  1,417.7     1,464.2
    aab       121,000,789  1,890.7     2,594.8
    album      11,620,228     91.4     198.3 (others 24% of the CPU)

The review found that the first version priced a container of JPEGs and one
small deflated page at about 0 s, and that a header could claim 10 TB; both are
guarded below, and three mutations of the probe the first tests missed.
"""

from __future__ import annotations

import dataclasses
import random
import struct
import zipfile
from pathlib import Path

import pytest

from excmp import estimate
from excmp.analyzer import (Category, FileInfo, analyze_file, probe_container,
                            probe_expandable)
from excmp.estimate import Rates, estimate_time, recode_cost, recoded_seconds
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
NO_PACK = Rates(ogg_pack=False, jpeg_pack=False)

_RNG = random.Random(26)


def _text(n=60_000, seed=1) -> bytes:
    rng = random.Random(seed)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz")
                     for _ in range(rng.randint(3, 10))) for _ in range(20_000)]
    return " ".join(rng.choice(vocab) for _ in range(n)).encode()


def _epubish(path: Path, png=300_000, jpg=50_000, gif=20_000, text_seeds=(1, 2)) -> tuple[Path, int]:
    """A zip with deflated text, PNG, JPEG and GIF members; returns the text bytes."""
    texts = [_text(seed=s) for s in text_seeds]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, t in enumerate(texts):
            zf.writestr(f"OEBPS/chapter{i}.xhtml", t)
        if png:
            zf.writestr("OEBPS/img/cover.png", _RNG.randbytes(png))
        if jpg:
            zf.writestr("OEBPS/img/photo.JPG", _RNG.randbytes(jpg))
        if gif:
            zf.writestr("OEBPS/img/spin.gif", _RNG.randbytes(gif))
    return path, sum(len(t) for t in texts)


# -- the probe -----------------------------------------------------------------

def test_the_probe_counts_the_deflated_bytes_and_the_png_bytes(tmp_path):
    p, text = _epubish(tmp_path / "book.epub")
    info = analyze_file(p)
    assert info.expandable is True
    assert info.zip_deflated_bytes == text
    assert info.zip_png_bytes == 300_000


def test_jpeg_and_gif_members_are_not_deflated_content(tmp_path):
    """JPEGs are recoded by packJPG, GIFs by Precomp's own GIF path: neither is
    a deflate stream zpaqfranz is handed expanded. JPEGs are counted as JPEGs,
    GIFs with the rest."""
    p, text = _epubish(tmp_path / "book.epub", png=0, jpg=200_000, gif=100_000)
    info = analyze_file(p)
    assert info.expandable is True
    assert (info.zip_deflated_bytes, info.zip_png_bytes) == (text, 0)
    assert 199_000 <= info.zip_jpeg_bytes <= 200_000
    assert 99_000 <= info.zip_other_bytes <= 100_000


def test_a_png_member_is_counted_by_name_whatever_the_case(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.aar", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("res/a.PNG", _RNG.randbytes(40_000))
        zf.writestr("res/b.Png", _RNG.randbytes(60_000))
        zf.writestr("classes.dex", _text())
    info = analyze_file(tmp_path / "a.aar")
    assert info.zip_png_bytes == 100_000


def test_a_file_precomp_cannot_open_reports_no_bytes(tmp_path):
    """Not expandable means nothing is priced from it, whatever it holds."""
    p = tmp_path / "x.nupkg"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a.xml", _text())
        zf.writestr("b.png", _RNG.randbytes(10_000))
    info = analyze_file(p)
    assert info.expandable is False
    assert (info.zip_deflated_bytes, info.zip_png_bytes,
            info.zip_jpeg_bytes, info.zip_other_bytes) == (0, 0, 0, 0)

    q = tmp_path / "book.epub"
    q.write_bytes(random.Random(3).randbytes(200_000))
    info = analyze_file(q)
    assert (info.expandable, info.zip_deflated_bytes, info.zip_png_bytes) == (False, 0, 0)


def test_a_hand_built_fileinfo_has_no_counts():
    info = FileInfo(path=Path("a.aab"), size=10, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, expandable=True)
    assert (info.zip_deflated_bytes, info.zip_png_bytes,
            info.zip_jpeg_bytes, info.zip_other_bytes) == (0, 0, 0, 0)


def test_probe_expandable_keeps_answering_a_bool(tmp_path):
    p, _ = _epubish(tmp_path / "book.epub")
    head = p.read_bytes()[:65_536]
    assert probe_expandable(p, head) is True
    assert probe_container(p, head).expandable is True
    assert probe_container(p, head)[0] is True
    assert probe_container(tmp_path / "missing.bin", b"").expandable is False


# -- the rest of the container, and what a header may claim --------------------

def _raw_zip(path: Path, members, pad: int = 0) -> Path:
    """A zip whose central directory says what we like and whose members have no
    data: (name, method, compressed size, uncompressed size). The probe reads the
    directory only. ``pad`` bytes of filler stand in for the compressed data, so the
    sizes the directory claims can be made plausible for the file's length."""
    body = cd = b""
    for name, method, cs, us in members:
        nb = name.encode()
        off = len(body)
        body += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0, 0, 0, 0, len(nb), 0) + nb
        extra, c32, u32 = b"", cs, us
        if cs >= 2**32 or us >= 2**32:
            extra, c32, u32 = struct.pack("<HHQQ", 1, 16, us, cs), 0xFFFFFFFF, 0xFFFFFFFF
        cd += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 45, 45, 0, method, 0, 0, 0, c32, u32,
                          len(nb), len(extra), 0, 0, 0, 0, off) + nb + extra
    body += bytes(pad)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(members), len(members), len(cd), len(body), 0)
    path.write_bytes(body + cd + eocd)
    return path


def _mixed(path: Path, **members) -> Path:
    """A deflated page plus the given extra members (name -> (bytes, method))."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("OEBPS/page.xhtml", _text())
        for name, (data, method) in members.items():
            zf.writestr(name, data, compress_type=method)
    return path


@pytest.mark.parametrize("name", ["a.jpg", "a.JPEG", "a.Jpg", "a.jpeg"])
@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_a_jpeg_member_is_counted_as_a_jpeg_whatever_its_case_or_method(tmp_path, name, method):
    """Review: a container of JPEGs and one small deflated page was priced at
    about 0 s (448 s -> 2 s for a 20 MB EPUB), because the images were in no
    count and any non-zero count switched the chain-rate fallback off. (`.jpeg`
    was also missing from the excluded names and no test noticed.)"""
    p = _mixed(tmp_path / "album.epub", **{f"img/{name}": (_RNG.randbytes(120_000), method)})
    info = analyze_file(p)
    assert info.expandable is True
    assert info.zip_deflated_bytes == len(_text())
    assert info.zip_png_bytes == 0 and info.zip_other_bytes == 0
    assert 119_000 <= info.zip_jpeg_bytes <= 120_000     # what the member occupies


@pytest.mark.parametrize("name", ["a.gif", "a.GIF"])
def test_a_gif_member_is_counted_with_the_rest(tmp_path, name):
    p = _mixed(tmp_path / "album.epub", **{f"img/{name}": (_RNG.randbytes(120_000), zipfile.ZIP_STORED)})
    info = analyze_file(p)
    assert info.zip_deflated_bytes == len(_text())
    assert info.zip_jpeg_bytes == 0
    assert info.zip_other_bytes == 120_000


def test_a_stored_member_is_the_rest_not_deflated_content(tmp_path):
    """Mutation (review): counting stored members as deflated passed every test."""
    p = _mixed(tmp_path / "pkg.nupkg", **{"lib/blob.bin": (_RNG.randbytes(100_000), zipfile.ZIP_STORED)})
    info = analyze_file(p)
    assert info.zip_deflated_bytes == len(_text())
    assert info.zip_other_bytes == 100_000


def test_a_stored_png_is_still_a_png(tmp_path):
    p = _mixed(tmp_path / "pkg.nupkg", **{"res/a.png": (_RNG.randbytes(100_000), zipfile.ZIP_STORED)})
    info = analyze_file(p)
    assert info.zip_png_bytes == 100_000
    assert info.zip_other_bytes == 0


def test_a_webp_is_not_a_png(tmp_path):
    """Mutation (review): counting `.webp` as PNG passed every test."""
    p = _mixed(tmp_path / "app.apk", **{"res/a.webp": (_RNG.randbytes(80_000), zipfile.ZIP_DEFLATED)})
    info = analyze_file(p)
    assert info.zip_png_bytes == 0


def test_a_header_cannot_claim_more_than_deflate_can_make(tmp_path):
    """Review: a 234-byte zip claiming 10 TB was estimated at 24 years at Insane
    (2**64 - 1: 3 million years). Deflate cannot expand past ~1032:1, so a header
    that claims more is not believed past it."""
    p = _raw_zip(tmp_path / "bomb.aab", [("a.dex", 8, 100, 10 * 2**40),
                                          ("b.png", 8, 100, 2**64 - 1)])
    info = analyze_file(p)
    assert info.expandable is True
    assert info.zip_deflated_bytes == 1032 * 100
    assert info.zip_png_bytes == 1032 * 100
    the_plan = plan([info], Profile.INSANE, TOOLS)
    assert estimate_time([info], the_plan, NO_PACK).high < 3_600       # seconds, not years


def test_a_stored_member_is_never_counted_past_its_own_bytes(tmp_path):
    p = _raw_zip(tmp_path / "x.aab", [("a.dex", 8, 5_000, 20_000), ("blob.bin", 0, 100, 10 * 2**40)], pad=5_100)
    info = analyze_file(p)
    assert info.zip_other_bytes == 100


def test_a_stored_png_is_never_counted_past_its_own_bytes(tmp_path):
    """Mutation (this review's): believing a stored PNG's claimed size passed."""
    p = _raw_zip(tmp_path / "x.aab", [("a.dex", 8, 5_000, 20_000), ("r.png", 0, 100, 10 * 2**40)], pad=5_100)
    info = analyze_file(p)
    assert info.zip_png_bytes == 100


# -- the pricing ---------------------------------------------------------------

def _container(name, size, deflated, png, jpeg=0, other=0):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0,
                    expandable=True, zip_deflated_bytes=deflated, zip_png_bytes=png,
                    zip_jpeg_bytes=jpeg, zip_other_bytes=other)


#: What the probe reads on the real files: input bytes, deflated, PNG, JPEG, rest.
CORPORA = {
    "nupkg": lambda: [_container("x.nupkg", 1_392_266, 4_002_260, 0, 0, 37_668)],
    "appx": lambda: [_container("x.appx", 6_015_103, 19_287_922, 4_803)],
    "aar": lambda: [_container("x.aar", 5_665_058, 16_173_607, 0)],
    "epub": lambda: [_container("x.epub", 5_686_653, 4_003_996, 4_244_771, 885_211, 120)],
    "odt-big": lambda: [_container("x.odt", 36_764_796, 6_926_046, 33_801_207, 2_495_647, 39)],
    "aab": lambda: [_container("x.aab", 121_000_789, 346_149_382, 1_459_915)],
    "album": lambda: [_container("x.epub", 11_620_228, 6_230, 0, 11_617_184, 20)],
}

#: (quiet seconds, contended rows the high side holds). nupkg's 313.2 s is a
#: 10.7x row from a memory squeeze and is not asserted.
MEASURED = {
    "nupkg": (29.4, [35.0]),
    "appx": (138.4, [183.2, 339.6]),
    "aar": (109.4, [110.6, 135.4]),
    "epub": (455.4, [589.6, 1_020.3]),
    "odt-big": (1_417.7, [1_464.2]),
    "aab": (1_890.7, [2_594.8]),
    "album": (91.4, [198.3]),
}


def _insane(corpus):
    infos = CORPORA[corpus]()
    return infos, estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), NO_PACK)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_a_quiet_insane_run_sits_in_the_range(corpus):
    _, t = _insane(corpus)
    assert t.low <= MEASURED[corpus][0] <= t.high, (corpus, t.low, t.expected, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_expected_figure_is_within_1_7x_of_a_quiet_run(corpus):
    """Before: EPUB 3.5x over its range's expected, ODT 0.58x. Now 0.66x (EPUB)
    to 1.57x (ODT): a PNG's expansion runs 6x (ODT) to 106x (an EPUB) per byte,
    and one PNG rate prices both. The 1.7x band was set after seeing those two:
    a regression pin, not validation."""
    _, t = _insane(corpus)
    quiet = MEASURED[corpus][0]
    assert quiet / 1.7 <= t.expected <= quiet * 1.7, (corpus, t.expected, quiet)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_range_holds_the_contended_rows(corpus):
    _, t = _insane(corpus)
    for measured in MEASURED[corpus][1]:
        assert measured <= t.high, (corpus, measured, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_low_end_stays_informative(corpus):
    """The PNG allowance (below) widens an EPUB's low to 3.2x under its quiet
    row; no corpus is further than 3.5x."""
    _, t = _insane(corpus)
    assert t.low >= MEASURED[corpus][0] / 3.5, (corpus, t.low)


def test_png_members_let_the_low_end_undercut_their_self_test(monkeypatch):
    """The ODT's self-test ran at 0.63x of the model's (665 s against 1,057 s):
    its PNGs expand 6x per byte, the least of any container measured, and one
    rate prices them all. Only the low end moves."""
    infos = CORPORA["odt-big"]()
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    with_allowance = estimate_time(infos, the_plan, NO_PACK)
    monkeypatch.setattr(estimate, "_ZIP_PNG_VERIFY_LOW", 1.0)
    without = estimate_time(infos, the_plan, NO_PACK)
    png_verify = 33_801_207 / 0.0339e6
    assert without.low - with_allowance.low == pytest.approx(png_verify * (1 - 1 / 1.6), rel=0.01)
    assert (without.expected, without.high) == (with_allowance.expected, with_allowance.high)
    # Without it the ODT's low end sat 1.3% under its one quiet row (1,399 s
    # against 1,418 s: the reviewer's "2% of room"); with it, 26% under.
    assert MEASURED["odt-big"][0] * 0.98 < without.low <= MEASURED["odt-big"][0]
    assert with_allowance.low < MEASURED["odt-big"][0] * 0.8


def _seconds(infos):
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    stages = [s for r in the_plan.routes if r.action == "pipeline" for s in r.stages]
    return recoded_seconds(recode_cost(infos, the_plan), stages)


def test_a_container_costs_what_it_expands_to_not_what_it_weighs():
    """Same 10 MB on disk. Plain deflate (a NuGet, an AAR) expands 3x; one that
    is mostly PNG (an EPUB) hands zpaqfranz many times that."""
    plain = [_container("p.aar", 10_000_000, 30_000_000, 0)]
    images = [_container("i.epub", 10_000_000, 2_000_000, 8_000_000)]
    pc, pv = _seconds(plain)
    ic, iv = _seconds(images)
    assert pc == pytest.approx(30_000_000 / 0.385e6, rel=0.02)
    assert pv == pytest.approx(30_000_000 / 0.360e6, rel=0.02)
    assert ic == pytest.approx(2_000_000 / 0.385e6 + 8_000_000 / 0.0289e6, rel=0.02)
    assert iv == pytest.approx(2_000_000 / 0.360e6 + 8_000_000 / 0.0339e6, rel=0.02)
    assert 2.5 <= (ic + iv) / (pc + pv) <= 4.0, (pc + pv, ic + iv)


def test_a_container_of_jpegs_and_one_small_page_is_not_free():
    """The review's regression: 448 s on main, 2.0 s with the images in no count.
    Priced as JPEGs (B22's rates) it is ~140 s; the measured 11.6 MB album ran
    at 0.8x of that model's seconds."""
    info = _container("album.epub", 20_000_000, 5_007, 0, jpeg=19_990_000)
    t = estimate_time([info], plan([info], Profile.INSANE, TOOLS), NO_PACK)
    assert 100 <= t.expected <= 200, t.expected
    assert t.low > 30 and t.high > t.expected


def test_jpeg_members_are_priced_as_jpegs_and_the_rest_at_the_chain_rate():
    jpegs = [_container("a.epub", 10_000_000, 0, 0, jpeg=10_000_000)]
    rest = [_container("b.epub", 10_000_000, 0, 0, other=10_000_000)]
    jc, jv = _seconds(jpegs)
    rc, rv = _seconds(rest)
    assert jc == pytest.approx(10_000_000 / 0.277e6, rel=0.02)
    assert jv == pytest.approx(10_000_000 / 0.312e6, rel=0.02)
    assert rc == pytest.approx(10_000_000 / 0.091e6, rel=0.02)
    assert rv == pytest.approx(10_000_000 / 0.107e6, rel=0.02)


def test_a_container_the_probe_did_not_read_keeps_the_chain_rate():
    """A hand-built FileInfo has no counts: it is priced as before, at the
    chain's rate plus B20's extra, and is not billed at an own rate."""
    info = _container("x.aab", 10_000_000, 0, 0)
    the_plan = plan([info], Profile.INSANE, TOOLS)
    rc = recode_cost([info], the_plan)
    assert rc.bytes == 10_000_000 and rc.own_bytes == 0
    t = estimate_time([info], the_plan, NO_PACK)
    assert 150 <= t.expected <= 300, t.expected      # 10 MB at ~0.09 MB/s + the self-test


def test_the_b5_types_keep_the_chain_rate_at_insane():
    """`.xlsx .pptx .zip .jar .apk` are B5's, measured at Extreme; B27 measured them at Insane
    and none was lifted, so the counts do not move them. (`.docx` is the exception, B29:
    tests/test_b29_docx_by_content.py.)"""
    for name in ("b.xlsx", "c.pptx", "d.zip", "e.jar", "f.apk"):
        info = _container(name, 10_000_000, 30_000_000, 0)
        the_plan = plan([info], Profile.INSANE, TOOLS)
        assert recode_cost([info], the_plan).own_bytes == 0, name


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_extreme_does_not_read_the_counts(corpus):
    infos = CORPORA[corpus]()
    bare = [dataclasses.replace(i, zip_deflated_bytes=0, zip_png_bytes=0,
                                zip_jpeg_bytes=0, zip_other_bytes=0) for i in infos]
    a = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS), NO_PACK)
    b = estimate_time(bare, plan(bare, Profile.EXTREME, TOOLS), NO_PACK)
    assert (a.low, a.expected, a.high) == (b.low, b.expected, b.high)


@pytest.mark.parametrize("learned", [(0.050e6, 0.060e6), (0.091e6, 0.107e6),
                                     (0.160e6, 0.200e6)])
def test_the_bar_s_split_ignores_a_learned_insane_chain_rate_on_containers(
        monkeypatch, learned):
    """As B22's: the extras are signed and measured against fixed constants, so
    a chain rate learned from text cannot drive a container job's bar
    negative or off the table."""
    from excmp import calibrate
    from excmp.estimate import _CODEC_RATE, _VERIFY_RATE
    from gui.queue_manager import _time_split
    from gui.suggest import summarize
    infos = CORPORA["aab"]()
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    summary = summarize(infos, the_plan, TOOLS)
    rates = Rates(codec={**_CODEC_RATE, "precomp+zpaqfranz": learned[0]},
                  verify={**_VERIFY_RATE, "precomp+zpaqfranz": learned[1]},
                  ogg_pack=False, jpeg_pack=False)
    monkeypatch.setattr(calibrate, "blended_rates", lambda: rates)
    compress, verify = _time_split(summary)
    table = estimate_time(infos, the_plan, rates).expected
    assert compress > 0 and verify > 0
    assert compress + verify == pytest.approx(table, rel=0.01), (compress, verify, table)
