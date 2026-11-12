"""B18(c): the probe rule B13a proved on Ogg holds for MP3 and MP4 as well.

The rule used to be "media is stored: already compressed by its codec". B13a
made one exception: an Ogg file whose own probe (`sample_ratio_max`, zstd-3
over up to three 1 MiB samples) says it shrinks is piped. B18 measured the
same question on MP3 and MP4, four corpora, every file restored and SHA-256
compared under 7-Zip `-mx9 -mmt2` and zstd 19 (2026-10-15,
docs/benchmarks/2026-10-15-b18-settings.md):

    corpus                     probe flags it        probe doesn't
    MP3, music (5)             3 files, 7z  -4.17%   2 files, -0.35%
    MP3, misc (16)             5 files, 7z  -5.24%   11 files, -0.45%
    phone video, MP4 (51)      40 files, 7z -9.20%   11 files, -1.61%
    downloaded video (9, 1 GB) 6 files, 7z  -3.77%   3 files, -0.32%

Those are group totals; per file the groups overlap (a flagged file saved as
little as 0.17%, an unflagged one 5.81%). So `.mp3` and `.mp4` join Ogg.
Other containers (MKV, WebM, M4A) were not measured and keep the old rule;
MOV joined in B19 (tests/test_b19_media.py). An MP3 on a chain with Precomp
is a different case (below).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, store_reason
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


def _media(name, category, probe_max, entropy=7.9):
    return FileInfo(path=Path(name), size=5_000_000, category=category,
                    entropy_bps=entropy, sample_ratio=probe_max,
                    sample_ratio_max=probe_max)


@pytest.mark.parametrize("name, category", [
    ("song.mp3", Category.AUDIO),
    ("SONG.MP3", Category.AUDIO),
    ("clip.mp4", Category.VIDEO),
    ("Clip.MP4", Category.VIDEO),
])
def test_an_mp3_or_mp4_the_probe_says_shrinks_is_piped(name, category):
    info = _media(name, category, 0.96)
    assert store_reason(info) is None
    for profile in Profile:
        routes = plan([info], profile, TOOLS).routes
        assert [r.action for r in routes] == ["pipeline"], (profile, routes)


@pytest.mark.parametrize("name, category", [
    ("song.mp3", Category.AUDIO),
    ("clip.mp4", Category.VIDEO),
])
def test_an_mp3_or_mp4_the_probe_cannot_shrink_stays_stored(name, category):
    """Probe 1.0 was 0.32-1.61% under 7-Zip on the measured corpora: not
    worth the codec's time, which is the rule's whole trade. (On a chain
    with Precomp an MP3 is piped anyway: packMP3, below.)"""
    reason = store_reason(_media(name, category, 1.0, entropy=7.99))
    assert reason is not None and "already compressed" in reason


@pytest.mark.parametrize("name, category", [
    ("movie.avi", Category.VIDEO),
    ("movie.wmv", Category.VIDEO),
    ("tune.aac", Category.AUDIO),
    ("photo.jpg", Category.IMAGE),
])
def test_unmeasured_media_keeps_the_old_rule(name, category):
    """Measured means measured: a container that shares a codec with MP4
    (AAC) is still a different set of files nobody has looked at. (MOV was
    measured in B19 and joined the rule: tests/test_b19_media.py; MKV, WebM
    and M4A in B21: tests/test_b21_stored_formats.py.)"""
    assert store_reason(_media(name, category, 0.95)) is not None


# -- MP3 under Precomp: packMP3 -------------------------------------------
#
# Precomp v0.4.7 recompresses MP3 itself (`-t` lists "3 = MP3", packMP3), and
# the probe cannot see that: it measures what zstd finds, not what packMP3
# does. End to end at Extreme, every file restored (2026-10-16):
#
#                  Normal (probe)   Extreme (probe)   Extreme, every MP3 piped
#     MP3 music         2.98%           13.69%               18.02%
#     MP3 misc         11.22%            8.42%               15.87%
#
# So on a chain with Precomp every MP3 is piped, the way every PNG is (B3).
# Without Precomp the probe still decides.

NO_PRECOMP = {"7z": TOOLS["7z"]}


@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
@pytest.mark.parametrize("probe", [0.95, 1.0])
def test_every_mp3_is_piped_when_precomp_is_in_the_chain(profile, probe):
    info = _media("song.mp3", Category.AUDIO, probe, entropy=7.99)
    routes = plan([info], profile, TOOLS).routes
    assert [r.action for r in routes] == ["pipeline"], routes
    assert "precomp" in routes[0].stages


def test_without_precomp_an_incompressible_mp3_stays_stored():
    info = _media("song.mp3", Category.AUDIO, 1.0, entropy=7.99)
    for profile in (Profile.FAST, Profile.NORMAL):
        assert [r.action for r in plan([info], profile, TOOLS).routes] == ["store"]
    # Extreme degrades to Normal's chain when Precomp is missing.
    assert [r.action for r in plan([info], Profile.EXTREME, NO_PRECOMP).routes] == ["store"]


@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
@pytest.mark.parametrize("probe", [0.95, 1.0])
def test_an_mp3_under_precomp_is_predicted_at_packmp3s_ratio(profile, probe):
    """Precomp's chain took every one of 21 real MP3s to 0.741-0.900 of its
    size (byte-weighted 0.835). The estimate used to read an unflagged MP3 as
    no gain (its probe is 1.0), so the profile table showed Extreme no better
    than Normal on an MP3 folder, where it measured 16-19% smaller."""
    from excmp.estimate import estimate_size
    info = _media("song.mp3", Category.AUDIO, probe, entropy=7.99)
    est = estimate_size([info], plan([info], profile, TOOLS))
    assert est.upper_bound
    payload = est.expected - est.overhead_bytes
    assert 0.85 * info.size < payload <= 0.90 * info.size, payload / info.size
    assert est.high - est.overhead_bytes == info.size   # declined: stored size


#: End-to-end archives with every MP3 piped (b13-app-*-allmp3.jsonl), all
#: restored: (corpus bytes, archive bytes).
MP3_E2E = {"music, Extreme": (33_922_849, 27_809_897),
           "music, Insane": (33_922_849, 27_487_359),
           "misc, Extreme": (80_307_437, 67_564_664)}


@pytest.mark.parametrize("run", sorted(MP3_E2E))
def test_the_at_most_figure_is_a_real_ceiling_for_mp3(run):
    """Review, B18: on a Precomp chain the GUI shows `expected` as "≤ X". An
    average there (0.835) put "≤ 64.0 MB" over a 64.4 MB archive. `expected`
    is the worst ratio of 21 real files, so every measured run sits under it."""
    from excmp.estimate import _MP3_PRECOMP_RATIO
    orig, archive = MP3_E2E[run]
    assert archive <= orig * _MP3_PRECOMP_RATIO[1]


def test_without_precomp_an_mp3_is_predicted_from_its_probe():
    from excmp.estimate import estimate_size
    info = _media("song.mp3", Category.AUDIO, 0.95, entropy=7.99)
    est = estimate_size([info], plan([info], Profile.NORMAL, TOOLS))
    assert est.expected - est.overhead_bytes > 0.90 * info.size


def test_mp4_does_not_ride_along():
    """Precomp found nothing in MP4: Extreme 4.681% against Normal 4.682% on
    the phone-video corpus (51 MP4 + 6 MOV, the MOVs stored either way). An
    incompressible MP4 stays stored at Extreme."""
    info = _media("clip.mp4", Category.VIDEO, 1.0, entropy=7.99)
    assert [r.action for r in plan([info], Profile.EXTREME, TOOLS).routes] == ["store"]


def test_piped_media_is_not_told_only_re_encoding_helps(tmp_path):
    """Review, B18: the shrink hint counted every video/audio byte as
    unshrinkable. A video the probe flags is now piped and does shrink
    losslessly (25.7% on a real screen recording), so it must not be counted.
    The hint reads the stored media only, which is what it is about."""
    from excmp.analyzer import analyze_tree
    from gui.suggest import shrink_mode_hint, summarize
    root = tmp_path / "screen"
    root.mkdir()
    # A screen-recording-like MP4: a container header, then highly repetitive
    # frames. The probe reads it as compressible, so B18 pipes it.
    (root / "rec.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + b"frame-0001" * 60_000)
    (root / "notes.txt").write_text("hello\n" * 100)
    infos = analyze_tree(root)
    the_plan = plan(infos, Profile.NORMAL, TOOLS)
    summary = summarize(infos, the_plan, TOOLS)
    assert summary.pipeline_bytes > 0.9 * summary.total_bytes
    assert shrink_mode_hint(summary) is None


# -- end to end ---------------------------------------------------------

def _seven_zip_or_skip():
    from excmp.tools import find_tools
    if find_tools().get("7z") is None:
        pytest.skip("7-Zip not installed")


def _round_trip(src: Path, tmp_path: Path):
    from excmp import engine
    from excmp.stages.base import StageContext
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "m.excmp"
    result = engine.compress([src], out, Profile.NORMAL, ctx)
    x = engine.extract(out, tmp_path / "x", ctx)
    back = next((tmp_path / "x").rglob(src.name))
    same = hashlib.sha256(back.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()
    return result, x, same


def test_a_compressible_mp4_is_piped_and_restored(tmp_path):
    """Runs anywhere 7-Zip is (CI included): a screen-recording-like MP4, which
    the probe reads as compressible, goes through the chain, shrinks, and comes
    back byte-identical. The real-file tests below need the bench corpus."""
    _seven_zip_or_skip()
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"frame-0001" * 60_000)
    result, x, same = _round_trip(src, tmp_path)
    assert result.piped_bytes == src.stat().st_size
    assert result.final_bytes < src.stat().st_size // 2
    assert x.verified == 1 and same


#: Copies of real corpus files, under neutral names (B18 review: no downloaded
#: file's name in the repo). Hashes as measured.
SAMPLES = Path(r"C:\excmp-bench\b18\samples")
MP3 = SAMPLES / "song.mp3"                 # af50f361..., flagged, probe 0.9649
MP4 = SAMPLES / "screen-recording.mp4"     # c436e0e2..., flagged, probe 0.7401
needs_corpus = pytest.mark.skipif(not (MP3.is_file() and MP4.is_file()),
                                  reason="B18's media samples are not on this machine")


def test_malformed_mp3s_do_not_fail_an_extreme_job(tmp_path):
    """Review, B18: every MP3 now reaches Precomp on Extreme, so can one bad
    file fail the whole job? Measured 2026-10-16 with a truncated MP3, random
    bytes, an ID3 tag over garbage and a WAV, all named `.mp3`: the job
    succeeded and every file restored. Before B18 they never reached Precomp.
    (The D9 gate is what makes this safe either way: a wrong restore fails
    the job, it never publishes.)"""
    import math
    import random
    import struct
    from excmp import engine
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    if find_tools().get("precomp") is None or find_tools().get("7z") is None:
        pytest.skip("Precomp and 7-Zip are needed for the Extreme chain")
    root = tmp_path / "mp3s"
    root.mkdir()
    (root / "garbage.mp3").write_bytes(random.Random(4).randbytes(200_000))
    (root / "id3only.mp3").write_bytes(b"ID3\x04\x00\x00\x00\x00\x10\x00" + bytes(2048)
                                       + random.Random(5).randbytes(100_000))
    pcm = b"".join(struct.pack("<h", int(12000 * math.sin(i / 20))) for i in range(100_000))
    (root / "wav.mp3").write_bytes(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
                                   + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
                                   + b"data" + struct.pack("<I", len(pcm)) + pcm)
    if MP3.is_file():
        good = MP3.read_bytes()
        (root / "truncated.mp3").write_bytes(good[: len(good) // 3 + 417])
    want = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in root.iterdir()}
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    result = engine.compress([root], tmp_path / "m.excmp", Profile.EXTREME, ctx)
    assert result.piped_bytes == sum(p.stat().st_size for p in root.iterdir())
    x = engine.extract(tmp_path / "m.excmp", tmp_path / "x", ctx)
    assert x.verified == len(want)
    for name, digest in want.items():
        assert hashlib.sha256((tmp_path / "x" / "mp3s" / name).read_bytes()).digest() == digest


@needs_corpus
@pytest.mark.parametrize("src, saved_at_least", [(MP3, 0.03), (MP4, 0.20)])
def test_a_real_file_round_trips_smaller(tmp_path, src, saved_at_least):
    """7-Zip alone took 3.81% off the MP3 and 25.67% off the screen recording.
    Through the app, Normal, the archive must be smaller than storing by most
    of that, and byte-identical on the way out."""
    _seven_zip_or_skip()
    result, x, same = _round_trip(src, tmp_path)
    assert result.piped_bytes == src.stat().st_size
    assert result.final_bytes < src.stat().st_size * (1 - saved_at_least)
    assert x.verified == 1 and same


#: (file, measured 7z -mx9 -mmt2 bytes), 2026-10-15, both restored.
MEASURED_7Z = [
    (MP3, 2_529_596),
    (SAMPLES / "app-music.mp3", 7_191_401),
    (MP4, 498_578),
]


@needs_corpus
@pytest.mark.parametrize("src, measured", MEASURED_7Z)
def test_the_estimate_brackets_what_7zip_measured(src, measured):
    """A file that is now piped is now *predicted*, from its probe. The range
    the card shows has to contain what the codec actually did.

    This checks the range, not the point. The review measured how loose it
    is: for the MP3s `high` is the file's own size, and on the screen
    recording `expected` is 402,759 against 498,578 measured (19% low). Read
    the range as "could be this good, at worst no gain", not as a forecast."""
    from excmp.analyzer import analyze_file
    from excmp.estimate import estimate_size
    info = analyze_file(src)
    est = estimate_size([info], plan([info], Profile.NORMAL, TOOLS))
    assert est.piped_bytes == info.size
    low, high = est.low - est.overhead_bytes, est.high - est.overhead_bytes
    assert low <= measured <= high, (src.name, low, measured, high)
