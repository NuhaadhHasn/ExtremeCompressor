"""B19: the media B18 left unmeasured, measured.

(a) MOV. B18's probe rule (`_PROBE_DECIDES`) pipes an MP3 or MP4 whose own
probe says it shrinks. MOV is the same ISO-BMFF family, and was left out
because nobody had looked at a MOV. Measured 2026-10-16 with B18's harness
(7-Zip `-mx9 -mmt2` and zstd 19 per file, every file restored and SHA-256
compared; docs/benchmarks/2026-10-16-b19-mov-jpeg.md):

    corpus                       probe flags it          probe doesn't
    Takeout MOVs (64, 909 MB)    8 files, 7z  -1.013%    56 files, -0.046%
    Downloads-1 MOVs (2, 62 MB)  none                    2 files,  -0.015%

The probe separates the groups on MOV as on MP4, so `.mov` joins the rule.
The stakes are small: phone MOVs are high-bitrate camera video, and the
flagged ones are under 1% of the bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, store_reason
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


def _media(name, category, probe_max, entropy=7.99):
    return FileInfo(path=Path(name), size=5_000_000, category=category,
                    entropy_bps=entropy, sample_ratio=probe_max,
                    sample_ratio_max=probe_max)


# -- (a) MOV -------------------------------------------------------------

@pytest.mark.parametrize("name", ["clip.mov", "CLIP.MOV", "Clip.Mov"])
def test_a_mov_the_probe_says_shrinks_is_piped(name):
    info = _media(name, Category.VIDEO, 0.9636)  # the best flagged Takeout MOV
    assert store_reason(info) is None
    for profile in Profile:
        routes = plan([info], profile, TOOLS).routes
        assert [r.action for r in routes] == ["pipeline"], (profile, routes)


def test_a_mov_the_probe_cannot_shrink_stays_stored():
    """Probe 1.0: 0.046% and 0.015% under 7-Zip on the two corpora."""
    info = _media("clip.mov", Category.VIDEO, 1.0)
    reason = store_reason(info)
    assert reason is not None and "already compressed" in reason
    for profile in Profile:
        assert [r.action for r in plan([info], profile, TOOLS).routes] == ["store"]


def test_a_mov_does_not_ride_along_to_precomp():
    """Precomp has no video codec. B18 measured Extreme no smaller than Normal
    on phone video; an incompressible MOV stays stored on its chain too."""
    info = _media("clip.mov", Category.VIDEO, 1.0)
    assert [r.action for r in plan([info], Profile.INSANE, TOOLS).routes] == ["store"]


# -- (b) JPEG: Precomp's packJPG takes what lepton refuses -------------------
#
# Every JPEG goes to the store route, where lepton packs it (B2). Precomp has
# a JPEG recoder too (packJPG: `-t` lists "J = JPG"). Per file, every output
# restored and SHA-256 compared, lepton's route against `precomp -cn
# -intense` then 7-Zip (Extreme's chain):
#
#     corpus                       lepton route   Precomp -> 7-Zip
#     web images (299, 20 MB)        21.40%           19.13%
#     phone photos (150, 49 MB)      22.27%           22.70%
#     design work (38, 151 MB)        3.49%           40.04%
#     other CMYK (2, 8.4 MB)          0.00%           44.69%
#
# The design gap is all in what lepton refuses: 4 colour channels (CMYK) or
# a side over 16,386 px. Those files are stored raw today; Precomp took
# 24.5-60.6% off every one. Both refusals are visible in the JPEG's frame
# header, so the planner can route them at plan time. The rest stay with
# lepton, which won on the web set (packJPG skipped 38 progressive files).

def _jpeg_bytes(components=3, width=640, height=480, padding=0):
    """A JPEG's marker chain up to its frame header: enough for the header
    walk, not a decodable image. `padding` bytes of APP2 segments sit before
    the frame, the way a CMYK ICC profile does (565 KB in the real files)."""
    import struct
    out = bytearray(b"\xff\xd8")
    while padding > 0:
        chunk = min(padding, 65533)
        out += b"\xff\xe2" + struct.pack(">H", chunk + 2) + b"\x00" * chunk
        padding -= chunk
    out += b"\xff\xc0" + struct.pack(">HBHHB", 8 + 3 * components, 8, height, width,
                                     components)
    out += b"\x01\x11\x00" * components
    out += b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x00" * 64 + b"\xff\xd9"
    return bytes(out)


@pytest.mark.parametrize("components, width, height, padding, refuses", [
    (3, 640, 480, 0, False),            # an ordinary photo
    (1, 640, 480, 0, False),            # grayscale: lepton accepts it
    (4, 2482, 3508, 0, True),           # CMYK
    (4, 2482, 3508, 565_000, True),     # CMYK behind a print ICC profile
    (3, 16386, 8, 0, False),            # lepton's largest side, accepted
    (3, 16387, 8, 0, True),             # one more, refused
    (3, 8, 16387, 0, True),             # either side
    (3, 27719, 9246, 0, True),          # the real oversized file
])
def test_the_frame_header_predicts_lepton_s_refusals(tmp_path, components, width,
                                                     height, padding, refuses):
    from excmp import jpeg
    p = tmp_path / "x.jpg"
    p.write_bytes(_jpeg_bytes(components, width, height, padding))
    assert jpeg.frame_header(p) == (components, width, height)
    assert jpeg.lepton_refuses(p) is refuses


@pytest.mark.parametrize("data", [
    b"",
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,       # a PNG named .jpg (43 real ones)
    b"\xff\xd8\xff\xe0\x00",                     # truncated in a length
    b"\xff\xd8\xff\xe2\xff\xff" + b"\x00" * 10,  # a segment running off the end
    b"\xff\xd8\x00\x00\x00",                     # not a marker
    b"\xff\xd8" + b"\xff\xfe\x00\x04ab" * 300,   # no frame within the bound
], ids=["empty", "png", "truncated-length", "overrun", "not-a-marker", "no-frame"])
def test_a_malformed_or_foreign_file_is_never_called_refused(tmp_path, data):
    """This runs during analysis, which K3 made incapable of failing a job: a
    file that isn't a readable JPEG gets no frame and the old route."""
    from excmp import jpeg
    p = tmp_path / "x.jpg"
    p.write_bytes(data)
    assert jpeg.frame_header(p) is None
    assert jpeg.lepton_refuses(p) is False


@pytest.mark.parametrize("mode, size", [
    ("RGB", (64, 64)), ("L", (64, 64)), ("CMYK", (64, 64)),
    ("RGB", (16386, 8)), ("RGB", (16387, 8)), ("RGB", (8, 16387)),
])
def test_the_prediction_matches_the_installed_lepton(tmp_path, mode, size):
    """Pins the header rule to lepton's real behaviour (both on CI: Pillow is
    a dev dependency, lepton a runtime one). If a lepton release starts to
    accept CMYK, this fails, and the rule should be revisited."""
    Image = pytest.importorskip("PIL.Image")
    from excmp import jpeg
    if not jpeg.available():
        pytest.skip("lepton wheel not installed")
    import io
    buf = io.BytesIO()
    Image.new(mode, size, 90).save(buf, "JPEG", quality=90)
    p = tmp_path / "x.jpg"
    p.write_bytes(buf.getvalue())
    try:
        jpeg._lepton.compress_bytes(buf.getvalue())
        lepton_refused = False
    except Exception:  # noqa: BLE001 - any refusal counts; the message varies
        lepton_refused = True
    assert jpeg.lepton_refuses(p) is lepton_refused


def test_the_analyzer_records_the_refusal(tmp_path):
    from excmp.analyzer import analyze_file
    cmyk, rgb, png = tmp_path / "a.jpg", tmp_path / "b.jpg", tmp_path / "c.jpg"
    cmyk.write_bytes(_jpeg_bytes(4, 2482, 3508, 565_000))
    rgb.write_bytes(_jpeg_bytes(3))
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert analyze_file(cmyk).lepton_refuses is True
    assert analyze_file(rgb).lepton_refuses is False
    assert analyze_file(png).lepton_refuses is False


def _jpg(lepton_refuses, name="scan.jpg"):
    return FileInfo(path=Path(name), size=12_000_000, category=Category.IMAGE,
                    entropy_bps=7.97, lepton_refuses=lepton_refuses)


@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
def test_a_jpeg_lepton_refuses_is_piped_when_precomp_is_in_the_chain(profile):
    routes = plan([_jpg(True)], profile, TOOLS).routes
    assert [r.action for r in routes] == ["pipeline"], routes
    assert "precomp" in routes[0].stages


@pytest.mark.parametrize("profile", list(Profile))
def test_a_jpeg_lepton_takes_stays_with_lepton(profile):
    """Lepton won on the web set (21.40% against 19.13%), and packJPG skipped
    38 progressive files there that lepton packed."""
    assert [r.action for r in plan([_jpg(False)], profile, TOOLS).routes] == ["store"]


def test_without_precomp_a_refused_jpeg_stays_stored():
    for profile in (Profile.FAST, Profile.NORMAL):
        assert [r.action for r in plan([_jpg(True)], profile, TOOLS).routes] == ["store"]
    no_precomp = {"7z": TOOLS["7z"]}
    assert [r.action for r in plan([_jpg(True)], Profile.EXTREME, no_precomp).routes] \
        == ["store"]


@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
def test_a_piped_refused_jpeg_is_predicted_at_packjpg_s_ratio(profile):
    """16 header-refused files from two corpora went to 0.394-0.755 of their
    size. `expected` is the worst of them: on a Precomp chain the GUI shows
    it as a ceiling ("≤ X"), B18's lesson. Before this the estimate read the
    file's probe (~1.0) and predicted no gain."""
    from excmp.estimate import estimate_size
    info = _jpg(True)
    est = estimate_size([info], plan([info], profile, TOOLS))
    payload = est.expected - est.overhead_bytes
    assert 0.74 * info.size < payload <= 0.76 * info.size, payload / info.size
    assert est.low - est.overhead_bytes <= 0.40 * info.size
    assert est.high - est.overhead_bytes == info.size


# -- end to end: through the engine, restored and compared -------------------

def _precomp_or_skip():
    from excmp.tools import find_tools
    if find_tools().get("precomp") is None:
        pytest.skip("Precomp not installed (it isn't on CI)")


def _extreme_round_trip(src: Path, tmp_path: Path):
    import hashlib
    import zipfile
    from excmp import engine
    from excmp.manifest import MANIFEST_NAME
    from excmp.stages.base import StageContext
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "m.excmp"
    result = engine.compress([src], out, Profile.EXTREME, ctx)
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    x = engine.extract(out, tmp_path / "x", ctx)
    back = next((tmp_path / "x").rglob(src.name))
    same = hashlib.sha256(back.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()
    return result, manifest, x, same


def test_a_cmyk_jpeg_goes_through_precomp_and_comes_back(tmp_path):
    """The route as a user meets it: a CMYK JPEG at Extreme is piped, comes
    out smaller than storing it (all lepton could offer), and restores byte
    for byte."""
    Image = pytest.importorskip("PIL.Image")
    _precomp_or_skip()
    src = tmp_path / "print.jpg"
    noise = Image.effect_noise((384, 384), 40)
    Image.merge("CMYK", [noise, noise.rotate(90), noise.rotate(180), noise]).save(
        src, "JPEG", quality=92)
    result, manifest, x, same = _extreme_round_trip(src, tmp_path)
    assert result.piped_bytes == src.stat().st_size
    assert "precomp" in json.dumps(manifest)
    assert result.final_bytes < src.stat().st_size * 0.95
    assert x.verified == 1 and same


# -- (c) the estimate sees lepton ---------------------------------------------
#
# Since B2 every JPEG on the store route is packed by lepton, and the estimate
# never knew: it billed stored bytes as an exact copy. End to end at Extreme
# (2026-10-16), all restored, the estimate's whole range sat ABOVE the archive:
#
#     corpus         estimate (low = expected = high)    archive
#     phone photos          49,159,101                  38,220,667   +28.6%
#     web images            20,478,832                  16,116,917   +27.1%
#     design work          151,296,675                 146,026,062    +3.6%
#
# And time: lepton packs and proves each file (pack + decode) and D9 decodes
# it again, where the estimate billed a disk copy at 100 MB/s.

def _photo(name="p.jpg", size=4_000_000, refuses=False, is_jpeg=True):
    return FileInfo(path=Path(name), size=size, category=Category.IMAGE,
                    entropy_bps=7.97, is_jpeg=is_jpeg, lepton_refuses=refuses)


def _rates(jpeg_pack):
    from excmp.estimate import Rates
    return Rates(ogg_pack=False, jpeg_pack=jpeg_pack)


@pytest.mark.parametrize("profile", list(Profile))
def test_a_stored_photo_is_predicted_at_lepton_s_ratio(profile):
    from excmp.estimate import estimate_size
    info = _photo()
    est = estimate_size([info], plan([info], profile, TOOLS), _rates(True))
    payload = lambda v: (v - est.overhead_bytes) / info.size  # noqa: E731
    assert est.packed_bytes == info.size
    assert payload(est.low) <= 0.666        # the best corpus measured (design)
    assert 0.786 <= payload(est.expected) <= 0.80   # the worst corpus (web)
    assert payload(est.high) == 1.0         # lepton declines: stored as it was


@pytest.mark.parametrize("info", [
    _photo(refuses=True),                   # CMYK: lepton will refuse it
    _photo(name="fake.jpg", is_jpeg=False), # a PNG named .jpg (43 real ones)
    _photo(size=900),                       # under jpeg.MIN_SIZE
], ids=["refused", "not-a-jpeg", "tiny"])
def test_a_jpeg_lepton_won_t_pack_stays_exact(info):
    from excmp.estimate import estimate_size
    est = estimate_size([info], plan([info], Profile.NORMAL, TOOLS), _rates(True))
    assert est.packed_bytes == 0
    assert est.low == est.expected == est.high == info.size + est.overhead_bytes


def test_without_the_wheel_photos_stay_exact():
    from excmp.estimate import estimate_size
    info = _photo()
    est = estimate_size([info], plan([info], Profile.NORMAL, TOOLS), _rates(False))
    assert est.packed_bytes == 0
    assert est.expected == info.size + est.overhead_bytes


#: End to end at Extreme, every file restored (b13-app-*-incumbent.jsonl):
#: (corpus bytes, archive bytes). `expected` is a ceiling over all of them.
JPEG_E2E = {"phone": (49_138_142, 38_220_667), "web": (20_437_711, 16_116_917)}


@pytest.mark.parametrize("corpus", sorted(JPEG_E2E))
def test_the_expected_figure_is_a_ceiling_for_photos(corpus):
    from excmp.estimate import _LEPTON_RATIO
    orig, archive = JPEG_E2E[corpus]
    assert archive <= orig * _LEPTON_RATIO[1]


def test_a_photo_folder_is_not_timed_as_a_copy():
    """150 phone photos, 49.1 MB: lepton's pack phase took 27.0 s and D9's
    decode 14.7 s, contended. A copy at 100 MB/s would say half a second."""
    from excmp.estimate import estimate_time, pack_cost
    infos = [_photo(f"p{i}.jpg", 327_588) for i in range(150)]
    the_plan = plan(infos, Profile.NORMAL, TOOLS)
    cost = pack_cost(infos, the_plan, _rates(True))
    assert cost.jpeg_bytes == 150 * 327_588 and cost.bytes == cost.jpeg_bytes
    assert 10 < cost.seconds < 60 and 3 < cost.verify_seconds < 30
    t = estimate_time(infos, the_plan, _rates(True))
    assert t.low < 27.0 + 14.7 < t.high
    assert estimate_time(infos, the_plan, _rates(False)).expected < 3


def test_the_summary_counts_photos_as_shrinking():
    """The card used to file lepton's JPEGs under "already compressed, stored
    bit-exact" beside the 0% the estimate showed. They shrink ~21-33%."""
    from gui.suggest import gain_note, summarize, store_explanations
    from excmp import jpeg as jpeg_mod
    infos = [_photo("a.jpg"), _photo("b.jpg"),
             FileInfo(path=Path("clip.mp4"), size=4_000_000, category=Category.VIDEO,
                      entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0)]
    import unittest.mock as m
    with m.patch.object(jpeg_mod, "available", lambda: True):
        the_plan = plan(infos, Profile.NORMAL, TOOLS)
        summary = summarize(infos, the_plan, TOOLS)
    assert summary.pack_jpeg_bytes == 8_000_000
    assert [name for name, _ in store_explanations(summary)] == ["clip.mp4"]
    note = gain_note(summary)
    assert "JPEG" in note and "already compressed" in note
    assert summary.pack_seconds > 0


def _photo_summary(infos, profile=Profile.NORMAL):
    import unittest.mock as m
    from excmp import jpeg as jpeg_mod
    from gui.suggest import strongest_profile, summarize
    with m.patch.object(jpeg_mod, "available", lambda: True):
        tools = {**TOOLS}
        return summarize(infos, plan(infos, profile, tools), tools,
                         reference_plan=plan(infos, strongest_profile(tools), tools))


def test_a_photo_folder_is_suggested_fast_not_extreme():
    """Rendering caught it: once lepton's JPEGs counted as shrinkable, a 47 MB
    photo folder looked small and compressible, and Extreme was suggested.
    Lepton packs a JPEG the same way under every profile - all four rows read
    37.0 MB and ~50 s - so Fast makes the same archive on the least RAM."""
    from gui.suggest import recommend_profile
    infos = [_photo(f"p{i}.jpg", 327_588) for i in range(150)]
    profile, reason = recommend_profile(_photo_summary(infos), cores=2)
    assert profile is Profile.FAST
    assert "JPEG" in reason and "~0%" not in reason


def test_an_ogg_folder_still_counts_as_profile_sensitive():
    """balrogg's effort rises with the profile (B13), so Ogg is not part of
    the floor the recommendation reads; that stays as it was."""
    import unittest.mock as m
    from excmp import oggpack
    with m.patch.object(oggpack, "available", lambda: True):
        infos = [FileInfo(path=Path(f"s{i}.ogg"), size=5_000_000, category=Category.AUDIO,
                          entropy_bps=7.97) for i in range(4)]
        summary = _photo_summary(infos)
    assert summary.floor_store_bytes == 0


def test_the_note_is_not_a_warning_for_photos():
    """The card coloured "worth compressing" as a warning: its tone read the
    store *route* share, and repacked files ride that route. It reads what
    can't shrink, the same figure the sentence uses."""
    photos = _photo_summary([_photo(f"p{i}.jpg") for i in range(5)])
    assert photos.fixed_fraction == 0.0
    video = _photo_summary([FileInfo(path=Path("v.mp4"), size=50_000_000,
                                     category=Category.VIDEO, entropy_bps=7.99)])
    assert video.fixed_fraction == 1.0


def test_a_stored_cmyk_jpeg_says_what_would_shrink_it():
    """On Fast/Normal a CMYK JPEG stays stored. Its reason should point at the
    profiles that shrink it, not call it compressed beyond help."""
    reason = store_reason(_photo(refuses=True))
    assert reason is not None
    assert "Extreme" in reason and "lepton" in reason


def test_the_analyzer_marks_jpegs_by_content(tmp_path):
    from excmp.analyzer import analyze_file
    real, fake = tmp_path / "a.png", tmp_path / "b.jpg"
    real.write_bytes(_jpeg_bytes(3))                      # a JPEG named .png
    fake.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # a PNG named .jpg
    assert analyze_file(real).is_jpeg is True
    assert analyze_file(fake).is_jpeg is False


BENCH = Path(r"C:\excmp-bench\b19")


@pytest.mark.skipif(not (BENCH / "jpg-phone").is_dir(), reason="B19's corpora are not here")
@pytest.mark.parametrize("corpus", sorted(JPEG_E2E))
def test_the_estimate_brackets_the_real_archive(corpus):
    """The real folders, analyzed as the app does, against the archive the app
    wrote (Extreme, lepton on the store route)."""
    from excmp import jpeg as jpeg_mod
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    if not jpeg_mod.available():
        pytest.skip("lepton wheel not installed")
    infos = analyze_tree(BENCH / f"jpg-{corpus}")
    est = estimate_size(infos, plan(infos, Profile.EXTREME, TOOLS), _rates(True))
    archive = JPEG_E2E[corpus][1]
    assert est.low <= archive <= est.high
    assert est.expected >= archive


# -- (d) the container overhead of stored files -------------------------------
#
# Found by checking B19's estimates against real archives: a store-only
# estimate is a zero-width range ("exact"), and 64 Takeout MOVs came out
# 3,173 B *bigger* than it, on main as on the branch. `_overhead` booked each
# file's basename once; the zip holds each stored member's full archive path,
# `stored/<root>/<path>`, twice (local header and central directory). Measured
# on a 4-deep synthetic tree of 12 files: 2,798 B under. Under-booking is the
# one direction this estimate may not err in: the disk preflight books it.

def _tree(base: Path, depth: int, n: int, size: int = 20_000) -> Path:
    import random
    root = base / f"Folder-depth{depth}"
    d = root
    for k in range(depth - 1):
        d = d / f"some_longer_subdirectory_name_{k}"
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"clip_{i:03d}.mp4").write_bytes(
            b"\x00\x00\x00\x20ftypisom" + random.Random(i).randbytes(size))
    return root


def test_archive_name_is_the_engine_s(tmp_path):
    from excmp.analyzer import archive_name
    from excmp.engine import _collect
    root = _tree(tmp_path, 3, 2)
    lone = tmp_path / "lone.mp4"
    lone.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"x" * 100)
    infos, relmap, _dirs, _skipped = _collect([root, lone])
    assert relmap  # both inputs collected
    for info in infos:
        root_of = lone if info.path == lone.resolve() else root.resolve()
        assert archive_name(root_of, info.path) == relmap[info.path]


def test_the_analyzer_records_the_archive_name_length(tmp_path):
    from excmp.analyzer import analyze_tree
    root = tmp_path / "Café"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "é.mp4").write_bytes(b"\x00" * 64)
    (info,) = analyze_tree(root)
    assert info.arc_name_bytes == len("Café/sub/é.mp4".encode("utf-8"))


def test_the_gui_s_analysis_records_it_too(tmp_path):
    """The GUI walks the dropped paths itself (AnalysisWorker), not through
    analyze_tree, so the root has to survive that walk as well."""
    from excmp.planner import Profile as P
    from gui.queue_manager import AnalysisWorker
    root = _tree(tmp_path, 2, 2)
    got = {}

    class _Sig:
        def __init__(self, name):
            self.name = name

        def emit(self, *args):
            got[self.name] = args

    class _Signals:
        ready, progress, failed, note = (_Sig("ready"), _Sig("progress"),
                                         _Sig("failed"), _Sig("note"))

    AnalysisWorker([root], P.FAST, {}, _Signals()).run()
    infos = got["ready"][0]
    assert {i.arc_name_bytes for i in infos} == {
        len(f"Folder-depth2/some_longer_subdirectory_name_0/clip_00{k}.mp4") for k in (0, 1)}


@pytest.mark.parametrize("depth, n", [(1, 3), (4, 12), (2, 64)])
def test_a_store_only_estimate_never_under_books_the_real_archive(tmp_path, depth, n):
    """Through the engine: random 'video' is stored, so the estimate's range
    has zero width and has to cover the archive the job really writes."""
    from excmp import engine
    from excmp.analyzer import analyze_tree
    from excmp.estimate import estimate_size
    from excmp.stages.base import StageContext
    root = _tree(tmp_path, depth, n)
    infos = analyze_tree(root)
    est = estimate_size(infos, plan(infos, Profile.FAST, TOOLS), _rates(False))
    assert est.low == est.high  # stored only: exact
    out = tmp_path / "m.excmp"
    engine.compress([root], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    archive = out.stat().st_size
    assert est.expected >= archive, est.expected - archive
    assert est.expected - archive <= 600 + 40 * n, est.expected - archive  # and close


SAMPLE = Path(r"C:\excmp-bench\b19\samples\cmyk-progressive.jpg")  # 52c0eb7f..., 12,112 B


@pytest.mark.skipif(not SAMPLE.is_file(), reason="B19's sample is not on this machine")
def test_a_real_cmyk_jpeg_round_trips_smaller(tmp_path):
    """A real progressive CMYK JPEG from an e-book tree: lepton refuses it,
    and `precomp -cn` then 7-Zip took it to 8,865 B (26.8% off)."""
    _precomp_or_skip()
    result, _, x, same = _extreme_round_trip(SAMPLE, tmp_path)
    assert result.piped_bytes == SAMPLE.stat().st_size
    assert result.final_bytes < SAMPLE.stat().st_size * 0.85
    assert x.verified == 1 and same
