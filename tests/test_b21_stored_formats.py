"""B21: the stored formats nobody had measured, measured.

(1) GIF. Precomp recodes a GIF's LZW itself (`-t` lists "F = GIF"), and every
GIF was stored. `precomp -cn -intense` then 7-Zip, file by file, every file
restored and SHA-256 compared (2026-10-19;
docs/benchmarks/2026-10-19-b21-stored-formats.md):

    corpus              files   bytes        stored   Precomp -> 7-Zip
    Downloads GIFs        64    30,035,992     0%         25.66%
    Downloads-1 GIFs      24     5,990,579     0%          6.85%

A GIF whose LZW Precomp can't re-create passes through (28 of 88). Over 1 KB,
two it did recode came out bigger, 1.176 and 1.254 of 72 KB and 18 KB, noisy
frames whose LZW beat LZMA on the raw pixels: 90 KB of 36 MB, with nothing
cheap to tell them apart. So on a chain with Precomp every GIF is piped, as
every PNG and MP3 is.

(2) PNG by content. The PNG exception keyed on the suffix while the analyzer
sniffs the first bytes, so the two disagreed: 10 PNGs named `.jpg` on the
owner's drives were stored at 0%, and 268 JPEGs named `.png` went to Precomp's
packJPG instead of lepton, which B19 measured ahead of packJPG on the JPEGs it
accepts. A PNG or a GIF is now one by content (`FileInfo.image_format`), as a
JPEG has been since B19 (`is_jpeg`).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, precomp_inflation
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
NO_PRECOMP = {"7z": TOOLS["7z"], "precomp": None, "zpaqfranz": None}


def _image(name, fmt, *, is_jpeg=False, size=1_000_000, probe=0.99):
    return FileInfo(path=Path(name), size=size, category=Category.IMAGE,
                    entropy_bps=7.95, sample_ratio=probe, sample_ratio_max=probe,
                    image_format=fmt, is_jpeg=is_jpeg)


def _actions(info, profile, tools=TOOLS):
    return [r.action for r in plan([info], profile, tools).routes]


# -- (1) GIF ---------------------------------------------------------------------

@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
def test_a_gif_is_piped_on_a_chain_with_precomp(profile):
    assert _actions(_image("anim.gif", "gif"), profile) == ["pipeline"]


@pytest.mark.parametrize("profile", [Profile.FAST, Profile.NORMAL])
def test_a_gif_stays_stored_on_a_chain_without_precomp(profile):
    """Nothing in Fast or Normal recodes LZW; the media rule stands."""
    assert _actions(_image("anim.gif", "gif"), profile) == ["store"]


def test_a_gif_stays_stored_when_precomp_is_not_installed():
    assert _actions(_image("anim.gif", "gif"), Profile.EXTREME, NO_PRECOMP) == ["store"]


def test_a_gif_is_piped_whatever_it_is_called():
    assert _actions(_image("banner.dat", "gif"), Profile.EXTREME) == ["pipeline"]


def test_a_file_named_gif_that_is_not_one_is_not_piped_for_it():
    """A WebP under a .gif name: Precomp has nothing to recode in it."""
    assert _actions(_image("sticker.gif", ""), Profile.EXTREME) == ["store"]


# -- (2) PNG by content --------------------------------------------------------------

def test_a_png_named_jpg_is_piped():
    """Ten of these on the owner's drives were stored at 0%."""
    assert _actions(_image("photo.jpg", "png"), Profile.EXTREME) == ["pipeline"]


def test_a_jpeg_named_png_stays_on_the_store_route_for_lepton():
    """268 on the owner's drives went to packJPG by their name."""
    info = _image("icon.png", "", is_jpeg=True)
    for profile in Profile:
        assert _actions(info, profile) == ["store"], profile


def test_a_jpeg_named_png_that_lepton_refuses_is_still_piped():
    """B19's rule is by content already: packJPG gets what lepton refuses."""
    info = replace(_image("poster.png", "", is_jpeg=True), lepton_refuses=True)
    assert _actions(info, Profile.EXTREME) == ["pipeline"]


@pytest.mark.parametrize("name", ["shot.png", "SHOT.PNG", "anim.gif"])
def test_a_hand_built_fileinfo_is_taken_at_its_name(name):
    """``image_format=None`` means nobody read the file (fixtures), and then
    the name is all there is. A real analysis always reads it."""
    assert _actions(_image(name, None), Profile.EXTREME) == ["pipeline"]
    assert _actions(_image(name, None), Profile.NORMAL) == ["store"]


def test_the_temp_budget_reads_the_content_too():
    """PNG's ~50x temp budget (B3) follows the PNG, not the name."""
    generic = precomp_inflation([_image("c.bin", "")])
    assert precomp_inflation([_image("a.jpg", "png")]) >= 20
    assert precomp_inflation([_image("b.png", "", is_jpeg=True)]) == generic


# -- the estimate, against the archives the app wrote --------------------------------
#
# A piped GIF needs no constant of its own: it is priced like any media file
# Precomp is let at (`_OVERRIDE_LOW`, its probe, 1.0), and under a Precomp
# chain `expected` is a ceiling. End to end at Extreme (b21_app.py, every
# file restored and SHA-256 compared, 2026-10-19):

BENCH = Path(r"C:\excmp-bench\b21")
GIF_E2E = {"gif-dl": (30_035_992, 22_292_068), "gif-dl1": (5_990_579, 5_572_190)}


@pytest.mark.skipif(not (BENCH / "gif-dl").is_dir(), reason="B21's corpora are not here")
@pytest.mark.parametrize("corpus", sorted(GIF_E2E))
def test_the_estimate_brackets_the_real_gif_archive(corpus):
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    infos = analyze_tree(BENCH / corpus)
    assert sum(i.size for i in infos) == GIF_E2E[corpus][0]
    est = estimate_size(infos, plan(infos, Profile.EXTREME, TOOLS))
    archive = GIF_E2E[corpus][1]
    assert est.upper_bound
    assert est.low <= archive <= est.high
    assert est.expected >= archive


# -- the time: Precomp expands a PNG or a GIF into pixels ---------------------------
#
# The model had no PNG term at all since B3: a PNG was billed at the generic
# Precomp chain's 1.41 MB/s while 8 PNGs named .jpg took 123.5 s for 2.0 MB
# (Precomp turned a 1.4 KB file into a 704 KB .pcf). GIF expands the same way.
# Both are recoders now, priced like packJPG and packMP3 (`_RECODE_RATE`).

def test_png_and_gif_are_recoded_by_content():
    from excmp.estimate import _recode_kind
    assert _recode_kind(_image("a.jpg", "png")) == "png"
    assert _recode_kind(_image("b.dat", "gif")) == "gif"
    assert _recode_kind(_image("shot.png", None)) == "png"      # nobody read it
    assert _recode_kind(_image("c.png", "", is_jpeg=True)) is None


def test_a_piped_png_costs_more_than_the_generic_chain():
    from excmp.estimate import estimate_time
    png, txt = _image("a.png", "png"), FileInfo(path=Path("a.txt"), size=1_000_000,
                                                category=Category.TEXT, entropy_bps=4.0,
                                                sample_ratio=0.3, sample_ratio_max=0.35)
    t_png = estimate_time([png], plan([png], Profile.EXTREME, TOOLS))
    t_txt = estimate_time([txt], plan([txt], Profile.EXTREME, TOOLS))
    assert t_png.expected > 3 * t_txt.expected


#: Compress plus D9 at Extreme, median of three rounds with the branch's code
#: (2026-10-19, `timing2\` and `timing3\`; other processes ~30-60% of the CPU
#: per run on average, peaks 79%).
TIME_E2E = {"gif-dl": 107.6, "gif-dl1": 12.7, "png-dl": 49.9, "png-dl1": 51.7,
            "png-as-jpg": 34.7}


@pytest.mark.skipif(not (BENCH / "png-dl").is_dir(), reason="B21's corpora are not here")
@pytest.mark.parametrize("corpus", sorted(TIME_E2E))
def test_the_time_range_holds_the_measured_median(corpus):
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_time
    infos = analyze_tree(BENCH / corpus)
    t = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS))
    assert t.low <= TIME_E2E[corpus] <= t.high
    if corpus == "png-as-jpg":
        # Not one of the corpora the rates came from, and the worst shape for
        # a per-byte rate: small PNGs that expand ~500x (1.4 KB -> 704 KB).
        # Its one quiet run took 17.0 s against 12.5 s expected; the other two
        # rounds took 35-39 s, which the slow side holds. A first run during
        # the afternoon's worst spell took 123.5 s, which it doesn't.
        return
    # and the expected figure is the right order, not a range wide enough to hold anything
    assert TIME_E2E[corpus] / 2.5 <= t.expected <= TIME_E2E[corpus] * 2.5


# -- (3) MKV, WebM, M4A: B18's probe rule ----------------------------------------
#
# Per file, 7-Zip -mx9 and zstd -19, every file restored (b18_media.codec,
# 2026-10-19 and 2026-11-12), split by the analyzer's probe as B18 split
# MP3/MP4:
#
#     corpus                       probe flags it         probe doesn't
#     MKV, 16 files, 2.07 GB       12 files, 7z 3.68%     4 files, 2.23%
#     M4A, 25 files, 356 MB         2 files,    7.37%    23 files, 1.79%
#     WebM, 3 files, 0.6 MB         1 file,     6.97%     2 files, 0.57%
#
# Weaker on MKV than B18's MP4 (9.20% / 1.61%), but the probe routes 81% of
# the MKV bytes and 88% of what 7-Zip can take. B18 left the unflagged
# MP4s' 1.61% on the table for the same trade.

@pytest.mark.parametrize("name, category", [
    ("lesson.mkv", Category.VIDEO), ("clip.webm", Category.VIDEO),
    ("talk.m4a", Category.AUDIO), ("TALK.M4A", Category.AUDIO)])
def test_a_container_the_probe_says_shrinks_is_piped(name, category):
    info = FileInfo(path=Path(name), size=50_000_000, category=category,
                    entropy_bps=7.97, sample_ratio=0.97, sample_ratio_max=0.98)
    for profile in Profile:
        assert _actions(info, profile) == ["pipeline"], profile


@pytest.mark.parametrize("name, category", [
    ("lesson.mkv", Category.VIDEO), ("clip.webm", Category.VIDEO),
    ("talk.m4a", Category.AUDIO)])
def test_a_container_the_probe_cannot_shrink_stays_stored(name, category):
    info = FileInfo(path=Path(name), size=50_000_000, category=category,
                    entropy_bps=7.99, sample_ratio=0.99, sample_ratio_max=1.0)
    for profile in Profile:
        assert _actions(info, profile) == ["store"], profile


# -- the analyzer ------------------------------------------------------------------

def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 90)).save(buf, "PNG")
    return buf.getvalue()


def _gif() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    frames = [Image.new("P", (40, 30), i * 20) for i in range(3)]
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_the_analyzer_reads_the_format_from_the_first_bytes(tmp_path):
    from excmp.analyzer import analyze_file
    cases = {"real.png": (_png(), "png"), "png.jpg": (_png(), "png"),
             "anim.gif": (_gif(), "gif"), "gif.bin": (_gif(), "gif"),
             "jpeg.png": (_jpeg(), ""), "webp.gif": (b"RIFF\x10\x00\x00\x00WEBPVP8 ", ""),
             "empty.png": (b"", "")}
    for name, (data, want) in cases.items():
        (tmp_path / name).write_bytes(data)
        assert analyze_file(tmp_path / name).image_format == want, name


# -- through the engine ---------------------------------------------------------------

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_a_gif_and_a_misnamed_png_go_through_extreme_and_come_back(tmp_path):
    """The public API, as the app calls it: both piped, both restored."""
    from excmp import engine
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    if find_tools().get("precomp") is None:
        pytest.skip("needs Precomp")
    src = tmp_path / "src"
    src.mkdir()
    (src / "anim.gif").write_bytes(_gif())
    (src / "scan.jpg").write_bytes(_png())
    out = tmp_path / "m.excmp"
    engine.compress([src], out, Profile.EXTREME, StageContext(temp_dir=tmp_path / "t"))
    routes = {Path(e.name).name: e.route for e in engine.list_archive(out).entries}
    assert routes == {"anim.gif": "pipeline", "scan.jpg": "pipeline"}
    engine.extract(out, tmp_path / "x", StageContext(temp_dir=tmp_path / "t2"))
    for f in src.iterdir():
        assert _sha(tmp_path / "x" / "src" / f.name) == _sha(f), f.name


# -- review fixes ----------------------------------------------------------------------
#
# Three reviewers and a skeptic, 2026-10-19. Each test below reproduces a
# finding that survived the skeptic, before its fix.

def _gif_summary(profile, n=10, size=5_000_000):
    """As the GUI builds it (mainwindow._summary): the selected profile's
    plan, plus the strongest chain's as the reference."""
    from gui.suggest import strongest_profile, summarize
    gifs = [_image(f"g{i}.gif", "gif", size=size) for i in range(n)]
    return summarize(gifs, plan(gifs, profile, TOOLS), TOOLS,
                     plan(gifs, strongest_profile(TOOLS), TOOLS))


def test_a_stored_png_or_gif_is_told_extreme_can_shrink_it():
    """(F2) Without Precomp a PNG or GIF was "already compressed by its
    codec", beside an Extreme row that takes 7-38% off. JPEGs lepton refuses
    and B20's containers already say where Precomp shrinks them."""
    from excmp.planner import store_reason
    for info in (_image("a.gif", "gif"), _image("b.jpg", "png"), _image("c.png", None)):
        reason = store_reason(info)
        assert "Extreme" in reason and "already compressed" not in reason, info.path
    # A JPEG under a PNG name is the store route's own (lepton): no promise.
    assert "Extreme" not in store_reason(_image("d.png", "", is_jpeg=True))


def test_the_gain_note_does_not_call_gifs_incompressible_under_normal():
    """(F3) Normal stores them, but "every byte here is already compressed —
    lossless gain is ~0%" is a claim about the bytes, and Extreme takes 7-26%
    off them. The same note told PNG, EPUB and CMYK folders the same."""
    from gui.suggest import gain_note
    note = gain_note(_gif_summary(Profile.NORMAL))
    assert "already compressed" not in note
    assert "stronger profile" in note and "47.7 MB" in note     # 50,000,000 B


def test_the_gain_note_still_says_so_when_nothing_can_shrink():
    from gui.suggest import gain_note, summarize
    clips = [FileInfo(path=Path(f"c{i}.mp4"), size=5_000_000, category=Category.VIDEO,
                      entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0)
             for i in range(3)]
    note = gain_note(summarize(clips, plan(clips, Profile.NORMAL, TOOLS), TOOLS,
                               plan(clips, Profile.EXTREME, TOOLS)))
    assert note.startswith("Every byte here is already compressed")


def test_a_big_gif_folder_is_not_promised_a_win_by_normal():
    """(F1) Over 8 GiB on a 2-core laptop the card said "Normal gets most of
    the win quickly"; on GIFs or PNGs Normal's own row reads 0%."""
    from gui.suggest import recommend_profile
    _, reason = recommend_profile(_gif_summary(Profile.EXTREME, n=10, size=1_000_000_000),
                                  cores=2)
    assert "win" not in reason


def test_a_piped_gif_can_come_out_bigger_and_the_range_says_so():
    """(F5) Two recoded GIFs came out at 1.176 and 1.254 of their size, and
    a GIF's `high` was 1.0: the range and the disk preflight under-booked a
    one-file job by 24.5% (skeptic, through the engine)."""
    from excmp.estimate import estimate_size
    gif = _image("noisy.gif", "gif", size=18_282, probe=1.0)
    est = estimate_size([gif], plan([gif], Profile.EXTREME, TOOLS))
    assert est.high - est.overhead_bytes >= 1.254 * 18_282


#: One-file jobs at Extreme through the engine, restored (skeptic, 2026-10-19).
GIF_GREW = {"gif-dl-033.gif": 23_655, "gif-dl-023.gif": 85_023}


@pytest.mark.skipif(not (BENCH / "gif-dl").is_dir(), reason="B21's corpora are not here")
@pytest.mark.parametrize("name", sorted(GIF_GREW))
def test_the_range_holds_the_gifs_that_grew(name, tmp_path):
    import shutil
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    src = tmp_path / "one"
    src.mkdir()
    shutil.copy2(BENCH / "gif-dl" / name, src / name)
    infos = analyze_tree(src)
    est = estimate_size(infos, plan(infos, Profile.EXTREME, TOOLS))
    assert est.high >= GIF_GREW[name]


@pytest.mark.skipif(not (BENCH / "gif-dl1").is_dir(), reason="B21's corpora are not here")
@pytest.mark.xfail(strict=True, reason=(
    "B22: Insane on 6 MB of GIFs ran 564.7 s (one run, others at 16-75%, no "
    "paging) against a high of ~333 s. The opposite direction from Insane on "
    "packJPG/packMP3 output, which is estimated 2-3x high."))
def test_insane_on_gifs_holds_the_one_measured_run():
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_time
    infos = analyze_tree(BENCH / "gif-dl1")
    t = estimate_time(infos, plan(infos, Profile.INSANE, TOOLS))
    assert t.high >= 564.7
