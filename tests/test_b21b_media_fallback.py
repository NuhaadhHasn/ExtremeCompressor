"""B21b: piping the media the probe flags must never make a job impossible.

B21 measured MKV, WebM and M4A under B18's probe rule (`_PROBE_DECIDES`):
probe-flagged files shrink 3.7-7.4% under 7-Zip, the rest 0.6-2.2%. Review
then found the cost. The disk preflight's floor is `piped x 2 + total +
out`, so piping the owner's 16 MKVs (1.92 GiB) took it from 3.85 to 6.97
GiB, and with C: at 6.37 GiB free the job was refused at every profile,
where storing them had worked. MP4 and MOV have done the same since B18.

The way out: when the plan doesn't fit, the same files with the
probe-flagged media stored are tried; if that fits, the job runs and says
what was stored and why. Lossless either way. Only when even that doesn't
fit is the job refused, with the smaller (true) floor.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from excmp import engine
from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo, find_tools

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
_REAL_DISK_USAGE = shutil.disk_usage


def _media(name, category, probe_max, size=50_000_000):
    return FileInfo(path=Path(name), size=size, category=category, entropy_bps=7.97,
                    sample_ratio=probe_max, sample_ratio_max=probe_max)


def _text(name="notes.txt", size=1_000_000):
    return FileInfo(path=Path(name), size=size, category=Category.TEXT,
                    entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)


def _routes(the_plan):
    return {p.name: r.action for r in the_plan.routes for p in r.files}


# -- the planner: what the lean plan stores, and only that -------------------------

@pytest.mark.parametrize("name, category", [
    ("lesson.mkv", Category.VIDEO), ("clip.mp4", Category.VIDEO),
    ("phone.mov", Category.VIDEO), ("talk.m4a", Category.AUDIO),
    ("clip.webm", Category.VIDEO)])
def test_the_lean_plan_stores_what_only_the_probe_piped(name, category):
    info = _media(name, category, 0.97)
    for profile in Profile:
        assert _routes(plan([info], profile, TOOLS))[name] == "pipeline", profile
        lean = plan([info], profile, TOOLS, probe_media=False)
        assert _routes(lean)[name] == "store", profile
        reason = next(r.reason for r in lean.routes if r.action == "store")
        assert "disk" in reason and "space" in reason


def test_the_lean_plan_leaves_everything_else_where_it_was():
    """Text, PNGs and MP3s on a Precomp chain are not the probe's: an MP3 is
    worth 15-18% to packMP3, and they keep their route."""
    infos = [_text(), _media("song.mp3", Category.AUDIO, 0.97),
             FileInfo(path=Path("shot.png"), size=1_000_000, category=Category.IMAGE,
                      entropy_bps=7.95, image_format="png")]
    for profile in (Profile.EXTREME, Profile.INSANE):
        assert _routes(plan(infos, profile, TOOLS, probe_media=False)) == \
            _routes(plan(infos, profile, TOOLS)), profile
    # On Normal the MP3 is the probe's, and only it moves.
    normal = _routes(plan(infos, Profile.NORMAL, TOOLS, probe_media=False))
    assert normal == {"notes.txt": "pipeline", "song.mp3": "store", "shot.png": "store"}


# -- the engine: fall back, or refuse with the true floor ------------------------------

def _pretend_free(monkeypatch, free_bytes):
    def fake(path):
        real = _REAL_DISK_USAGE(path)
        return shutil._ntuple_diskusage(real.total, real.total - free_bytes, free_bytes)
    monkeypatch.setattr(engine.shutil, "disk_usage", fake)


def _floors(infos, profile, tools, out, tmp):
    full = engine.compress_space_needs(out, tmp, infos, plan(infos, profile, tools))
    lean = engine.compress_space_needs(out, tmp, infos,
                                       plan(infos, profile, tools, probe_media=False))
    return sum(f for _, f, _ in full), sum(f for _, f, _ in lean)


BENCH = Path(r"C:\excmp-bench\b21\media\mkv.jsonl")


@pytest.mark.skipif(not BENCH.is_file(), reason="B21's MKV rows are not here")
@pytest.mark.parametrize("profile", list(Profile))
def test_the_owners_mkv_folder_is_stored_rather_than_refused(profile, tmp_path, monkeypatch):
    """The reviewer's repro: the 16 MKVs, free space between the two floors."""
    infos = [FileInfo(path=Path(r["file"]), size=r["size"], category=Category.VIDEO,
                      entropy_bps=r["entropy"], sample_ratio=r["sample_ratio"],
                      sample_ratio_max=r["sample_ratio_max"])
             for r in map(json.loads, open(BENCH, encoding="utf-8")) if r["step"] == "probe"]
    out, tmp = tmp_path / "o.excmp", tmp_path
    full, lean = _floors(infos, profile, TOOLS, out, tmp)
    assert lean < full
    _pretend_free(monkeypatch, (lean + full) // 2)
    with pytest.raises(RuntimeError):
        engine._check_compress_space(out, tmp, infos, plan(infos, profile, TOOLS))
    the_plan = engine._plan_that_fits(infos, profile, TOOLS, out, tmp)
    assert all(a == "store" for a in _routes(the_plan).values())
    warning = next(w for w in the_plan.warnings if "stored as-is" in w)
    # (review E1) the floor counts piped bytes twice, so the gap is about twice
    # the files' size: quote the gap itself.
    assert f"Free about {(full - lean) >> 20} MiB more" in warning, warning


def _video_tree(root: Path) -> Path:
    """A Matroska file the probe flags (a repeating pattern compresses) and a
    text file, so both routes are in play."""
    src = root / "src"
    src.mkdir()
    pattern = random.Random(21).randbytes(4096)
    (src / "lesson.mkv").write_bytes(b"\x1a\x45\xdf\xa3" + pattern * 400)
    (src / "notes.txt").write_text("the quick brown fox. " * 4000)
    # A video the probe passes over: stored for its own reason, so the
    # archive holds two different store reasons.
    (src / "clip.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom"
                                   + random.Random(18).randbytes(102_400))
    return src


needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


@needs_7z
def test_a_job_that_only_fits_without_the_video_runs_and_says_so(tmp_path, monkeypatch):
    """Through the public API: the archive is written, the video is stored,
    the warning says why, and every file comes back byte for byte."""
    import hashlib

    from excmp.analyzer import analyze_tree
    from excmp.stages.base import StageContext
    src = _video_tree(tmp_path)
    tools = find_tools()
    infos = analyze_tree(src)
    assert _routes(plan(infos, Profile.NORMAL, tools))["lesson.mkv"] == "pipeline"
    out, tmp = tmp_path / "out.excmp", tmp_path / "t"
    tmp.mkdir()
    full, lean = _floors(infos, Profile.NORMAL, tools, out, tmp)
    _pretend_free(monkeypatch, (lean + full) // 2)

    result = engine.compress([src], out, Profile.NORMAL, StageContext(temp_dir=tmp))

    entries = {Path(e.name).name: e for e in engine.list_archive(out).entries}
    assert {n: e.route for n, e in entries.items()} == {
        "lesson.mkv": "store", "notes.txt": "pipeline", "clip.mp4": "store"}
    # (review E2) each stored file says why on its own, not a joined summary
    assert entries["lesson.mkv"].reason.startswith("compressed video/audio: stored as-is")
    assert entries["clip.mp4"].reason.startswith("media file")
    assert any("stored as-is" in w for w in result.warnings), result.warnings
    engine.extract(out, tmp_path / "x", StageContext(temp_dir=tmp_path / "t2"))
    for f in src.iterdir():
        back = tmp_path / "x" / "src" / f.name
        assert hashlib.sha256(back.read_bytes()).digest() == \
            hashlib.sha256(f.read_bytes()).digest(), f.name


@needs_7z
def test_a_job_that_cannot_fit_either_way_is_still_refused(tmp_path, monkeypatch):
    from excmp.analyzer import analyze_tree
    from excmp.stages.base import StageContext
    src = _video_tree(tmp_path)
    infos = analyze_tree(src)
    out, tmp = tmp_path / "out.excmp", tmp_path / "t"
    tmp.mkdir()
    full, lean = _floors(infos, Profile.NORMAL, find_tools(), out, tmp)
    _pretend_free(monkeypatch, lean // 2)
    with pytest.raises(RuntimeError) as excinfo:
        engine.compress([src], out, Profile.NORMAL, StageContext(temp_dir=tmp))
    # (review E3) The refusal is the chosen plan's own: the lean plan's floor
    # can name a different volume with a figure the job never needed there.
    assert f"{full >> 20} MiB" in str(excinfo.value), str(excinfo.value)
    assert not out.exists()


# -- the recommendation -------------------------------------------------------------
#
# A video folder is mostly probe-piped bytes, which `recommend_profile` read as
# "lots of compressible data" and sent to Extreme, while the table flagged
# Extreme as no smaller than Normal: Precomp has no video codec (B18 on MP4;
# B21's MKVs came out 4.530% at Extreme, 4.533% at Normal, 60% slower). An
# MP3 is the exception: packMP3 takes 15-18% on Extreme.

def _summary(infos):
    from gui.suggest import strongest_profile, summarize
    return summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS,
                     plan(infos, strongest_profile(TOOLS), TOOLS))


def test_a_video_folder_is_not_sent_to_extreme():
    from gui.suggest import recommend_profile
    vids = [_media(f"v{i}.mkv", Category.VIDEO, 0.98, size=200_000_000) for i in range(10)]
    profile, reason = recommend_profile(_summary(vids), cores=2)
    assert profile is Profile.NORMAL
    assert "compressible data" not in reason and "video" in reason


def test_an_mp3_folder_still_goes_to_extreme():
    from gui.suggest import recommend_profile
    songs = [_media(f"s{i}.mp3", Category.AUDIO, 0.98, size=20_000_000) for i in range(10)]
    profile, _ = recommend_profile(_summary(songs), cores=2)
    assert profile is Profile.EXTREME


def test_the_gain_note_does_not_oversell_video():
    """A folder of probe-flagged MKVs read "Nearly all of this is worth
    compressing" beside a table saying 3%."""
    from gui.suggest import gain_note
    vids = [_media(f"v{i}.mkv", Category.VIDEO, 0.98, size=20_000_000) for i in range(10)]
    note = gain_note(_summary(vids))
    assert "worth compressing" not in note
    assert "few percent" in note


def test_a_mixed_folder_is_not_called_mostly_video():
    """(review S1) 60 MB of MKV beside 40 MB of text was told "a few percent,
    no more"; the text alone takes a third off."""
    from gui.suggest import gain_note
    infos = ([_media(f"v{i}.mkv", Category.VIDEO, 0.98, size=6_000_000) for i in range(10)]
             + [_text(f"t{i}.txt", size=4_000_000) for i in range(10)])
    assert "no more" not in gain_note(_summary(infos))


NO_PRECOMP = {"7z": TOOLS["7z"], "precomp": None, "zpaqfranz": None}


def test_without_precomp_an_mp3_is_the_probes_too():
    """(review S2) MP3 is left out of the probe-only bytes because packMP3
    recodes it, which needs Precomp. Without it, an MP3 folder is a few
    percent like video."""
    from gui.suggest import gain_note, summarize
    songs = [_media(f"s{i}.mp3", Category.AUDIO, 0.98, size=5_000_000) for i in range(10)]
    s = summarize(songs, plan(songs, Profile.NORMAL, NO_PRECOMP), NO_PRECOMP,
                  plan(songs, Profile.NORMAL, NO_PRECOMP))
    assert s.floor_probe_bytes == 50_000_000
    assert "few percent" in gain_note(s)


def test_video_beside_pngs_is_not_told_extreme_adds_nothing():
    """(review S3) 71% video, 29% PNG: Normal is still the pick under the
    30% rule, but "Extreme adds only time" is false; it would take a third
    off the PNGs."""
    from gui.suggest import recommend_profile
    infos = ([_media(f"v{i}.mkv", Category.VIDEO, 0.98, size=71_000_000) for i in range(10)]
             + [FileInfo(path=Path(f"p{i}.png"), size=29_000_000, category=Category.IMAGE,
                         entropy_bps=7.95, image_format="png") for i in range(10)])
    _, reason = recommend_profile(_summary(infos), cores=2)
    assert "only time" not in reason


def test_with_room_nothing_changes(tmp_path):
    """No fallback, no warning, when the plan fits."""
    infos = [_media("lesson.mkv", Category.VIDEO, 0.97, size=10_000), _text(size=10_000)]
    the_plan = engine._plan_that_fits(infos, Profile.NORMAL, TOOLS,
                                      tmp_path / "o.excmp", tmp_path)
    assert _routes(the_plan)["lesson.mkv"] == "pipeline"
    assert not any("stored as-is" in w for w in the_plan.warnings)
