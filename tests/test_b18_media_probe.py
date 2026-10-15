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
    phone video (57)           42 files, 7z -8.99%   15 files, -1.12%
    downloaded video (9, 1 GB) 6 files, 7z  -3.77%   3 files, -0.32%

So `.mp3` and `.mp4` join Ogg. Other containers (MKV, WebM, MOV, M4A) and
JPEG were not measured and keep the old rule.
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
    """Probe 1.0 was 0.32-1.12% under 7-Zip on the measured corpora: not
    worth the codec's time, which is the rule's whole trade."""
    reason = store_reason(_media(name, category, 1.0, entropy=7.99))
    assert reason is not None and "already compressed" in reason


@pytest.mark.parametrize("name, category", [
    ("movie.mkv", Category.VIDEO),
    ("movie.webm", Category.VIDEO),
    ("movie.mov", Category.VIDEO),
    ("tune.m4a", Category.AUDIO),
    ("photo.jpg", Category.IMAGE),
])
def test_unmeasured_media_keeps_the_old_rule(name, category):
    """Measured means measured: a container that shares a codec with MP4
    (MOV, M4A) is still a different set of files nobody has looked at."""
    assert store_reason(_media(name, category, 0.95)) is not None


# -- the real files, end to end ------------------------------------------

B18 = Path(r"C:\excmp-bench\b18")
MP3 = B18 / "mp3-misc" / "Narama-Sandun-Perera-Ft-Smokio-www.song.lk.mp3"
MP4 = B18 / "video-sample" / "screen-recording.mp4"
needs_corpus = pytest.mark.skipif(not (MP3.is_file() and MP4.is_file()),
                                  reason="B18's media corpus is not on this machine")


@needs_corpus
@pytest.mark.parametrize("src, saved_at_least", [(MP3, 0.03), (MP4, 0.20)])
def test_a_real_file_round_trips_smaller(tmp_path, src, saved_at_least):
    """7-Zip alone took 3.81% off the MP3 and 25.67% off the screen recording.
    Through the app, Normal, the archive must be smaller than storing by most
    of that, and byte-identical on the way out."""
    from excmp import engine
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    if find_tools().get("7z") is None:
        pytest.skip("7-Zip not installed")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "m.excmp"
    result = engine.compress([src], out, Profile.NORMAL, ctx)
    assert result.piped_bytes == src.stat().st_size
    assert result.final_bytes < src.stat().st_size * (1 - saved_at_least)
    x = engine.extract(out, tmp_path / "x", ctx)
    assert x.verified == 1
    back = next((tmp_path / "x").rglob(src.name))
    assert hashlib.sha256(back.read_bytes()).hexdigest() == \
        hashlib.sha256(src.read_bytes()).hexdigest()


#: (file, measured 7z -mx9 -mmt2 bytes), 2026-10-15, both restored.
MEASURED_7Z = [
    (MP3, 2_529_596),
    (B18 / "mp3-misc" / "31df8c51-music.mp3", 7_191_401),
    (MP4, 498_578),
]


@needs_corpus
@pytest.mark.parametrize("src, measured", MEASURED_7Z)
def test_the_estimate_brackets_what_7zip_measured(src, measured):
    """A file that is now piped is now *predicted*, from its probe. The range
    the card shows has to contain what the codec actually did."""
    from excmp.analyzer import analyze_file
    from excmp.estimate import estimate_size
    info = analyze_file(src)
    est = estimate_size([info], plan([info], Profile.NORMAL, TOOLS))
    assert est.piped_bytes == info.size
    low, high = est.low - est.overhead_bytes, est.high - est.overhead_bytes
    assert low <= measured <= high, (src.name, low, measured, high)
