"""B13, measured on real music: an Ogg file whose own probe says it shrinks is
piped, not stored.

The rule used to be "media is stored, already compressed by its codec". On 18
real Ogg Vorbis/Opus music files from Wikimedia Commons (169,975,314 B, every
restore SHA-256 checked, 2026-10-01) the app stored all of them and wrote an
archive 7,005 B *larger* than the input, while 7-Zip took 1.52% off and zstd
1.62%. The gain was concentrated exactly where the analyzer's probe already
saw it:

    probe max   7-Zip    file
    0.9487     -5.98%    Paul De Bra - Haydn 83
    0.9768     -4.47%    NBC - Toscanini/Horowitz
    0.9782     -3.93%    Victor Concert Orchestra 1917
    0.9894     -2.63%    Musopen - Mendelssohn
    0.9971     -1.68%    Evergreen - Haydn 104
    1.0        -1.24% .. +0.02%   the other 13, all five Opus files among them

So the probe decides, for Ogg only: it is the one media container measured.
Video, JPEG (lepton's route), MP3 and the rest keep the old rule until they
are measured too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, store_reason
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


@pytest.fixture(autouse=True)
def _without_balrogg(monkeypatch):
    """This file is the world *without* the specialist: the probe rule is the
    fallback for a machine that has not fetched balrogg. With it installed an
    Ogg file is packed on the store route instead (test_b13_pack_phase.py),
    and what these tests describe is no longer what that machine does - so they
    pin the machine they describe rather than depend on the one they run on."""
    from excmp import oggpack
    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)


def _media(name, category, probe_max, entropy=7.8):
    return FileInfo(path=Path(name), size=5_000_000, category=category,
                    entropy_bps=entropy, sample_ratio=probe_max,
                    sample_ratio_max=probe_max)


def test_an_ogg_the_probe_says_shrinks_is_piped():
    info = _media("haydn.ogg", Category.AUDIO, 0.9487)
    assert store_reason(info) is None
    for profile in Profile:
        routes = plan([info], profile, TOOLS).routes
        assert [r.action for r in routes] == ["pipeline"], (profile, routes)


def test_the_probe_wins_over_the_entropy_rule_for_ogg():
    """An Ogg page header makes the byte entropy look random; the probe is a
    measurement of this file and outranks a statistic about it."""
    assert store_reason(_media("x.oga", Category.AUDIO, 0.97, entropy=7.95)) is None


def test_an_ogg_the_probe_cannot_shrink_stays_stored():
    for name in ("mozart.ogg", "marine-band.opus"):
        reason = store_reason(_media(name, Category.AUDIO, 1.0, entropy=7.99))
        assert reason is not None and "already compressed" in reason


@pytest.mark.parametrize("name, category", [
    ("film.mp4", Category.VIDEO),
    ("photo.jpg", Category.IMAGE),
    ("song.mp3", Category.AUDIO),
])
def test_unmeasured_media_keeps_the_old_rule(name, category):
    """Only Ogg was measured. A probe below 1.0 on these changes nothing yet."""
    assert store_reason(_media(name, category, 0.95)) is not None


SAMPLE = Path(r"C:\excmp-bench\b13\music"
              r"\Paul De Bra - Haydn's Symphony No. 83 in G minor, Hob.I-83"
              r" - IV. Finale vivace (accordion orchestra).ogg")


@pytest.mark.skipif(not SAMPLE.is_file(), reason="B13's music corpus is not on this machine")
def test_a_real_ogg_round_trips_smaller(tmp_path):
    """End to end on the real file: smaller than stored, and byte-identical."""
    import hashlib
    from excmp import engine
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    if find_tools().get("7z") is None:
        pytest.skip("7-Zip not installed")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    out = tmp_path / "m.excmp"
    result = engine.compress([SAMPLE], out, Profile.NORMAL, ctx)
    assert result.piped_bytes == SAMPLE.stat().st_size
    assert result.final_bytes < SAMPLE.stat().st_size * 0.97
    x = engine.extract(out, tmp_path / "x", ctx)
    assert x.verified == 1
    back = next((tmp_path / "x").rglob("*.ogg"))
    assert hashlib.sha256(back.read_bytes()).hexdigest() == \
        hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
