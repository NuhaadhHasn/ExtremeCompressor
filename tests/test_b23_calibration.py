"""B23: calibration must not learn a chain rate from pass-through media.

One MKV job (B21b, 2026-11-12) taught Extreme 3.1 MB/s against its 1.41 prior:
the video is piped only because its own probe says it shrinks a few percent,
Precomp finds nothing in it and streams it straight through, and that is the
chain's no-op regime, not its rate. The next job with streams Precomp can open
then ran 2-3x over its estimate. `_calibrate` already left out jobs made mostly
of media Precomp *recodes* (B19); this is the same for media it only passes.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

pytest.importorskip("PySide6")

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


def _video(name, size):
    """Compressed video whose probe says it shrinks a few percent."""
    return FileInfo(path=Path(name), size=size, category=Category.VIDEO,
                    entropy_bps=7.99, sample_ratio=0.97, sample_ratio_max=0.98)


def _text(name, size):
    return FileInfo(path=Path(name), size=size, category=Category.TEXT,
                    entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)


def _summary(infos, profile=Profile.EXTREME):
    from gui.suggest import strongest_profile, summarize
    return summarize(infos, plan(infos, profile, TOOLS), TOOLS,
                     reference_plan=plan(infos, strongest_profile(TOOLS), TOOLS))


def _worker(tmp_path, summary, profile=Profile.EXTREME):
    from gui.models import Job
    from gui.queue_manager import CompressWorker

    class _Rec:
        def emit(self, *a):
            pass

    signals = SimpleNamespace(progress=_Rec(), log=_Rec(), started=_Rec(), done=_Rec(),
                              failed=_Rec(), cancelled=_Rec())
    job = Job(inputs=[tmp_path], out_path=tmp_path / "o.excmp", profile=profile,
              summary=summary)
    return CompressWorker(job, signals, tmp_path, tools={})


def _result(piped, elapsed):
    return SimpleNamespace(piped_bytes=piped, final_bytes=1, orig_bytes=2,
                           elapsed_s=elapsed,
                           routes=[{"action": "pipeline",
                                    "stages": ["precomp", "sevenzip"]}])


def test_the_summary_counts_the_bytes_the_probe_alone_pipes():
    infos = [_video("lesson.mkv", 40_000_000), _video("clip.mp4", 20_000_000),
             _text("notes.txt", 5_000_000)]
    summary = _summary(infos)
    assert summary.probe_piped_bytes == 60_000_000


def test_text_alone_has_no_probe_piped_bytes():
    assert _summary([_text("a.txt", 5_000_000)]).probe_piped_bytes == 0


def test_a_job_that_is_mostly_pass_through_video_teaches_nothing(tmp_path, monkeypatch):
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    infos = [_video("lesson.mkv", 80_000_000), _text("notes.txt", 5_000_000)]
    worker = _worker(tmp_path, _summary(infos))
    # 85 MB in 27 s is 3.1 MB/s: the pass-through regime, not the chain.
    worker._calibrate(_result(85_000_000, 27.0))
    assert recorded == []


def test_a_job_with_a_little_pass_through_video_still_teaches(tmp_path, monkeypatch):
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    infos = [_video("clip.mp4", 5_000_000)] + [_text(f"t{i}.txt", 20_000_000)
                                               for i in range(5)]
    worker = _worker(tmp_path, _summary(infos))
    worker._calibrate(_result(105_000_000, 80.0))
    assert len(recorded) == 1


def test_recoded_and_pass_through_bytes_count_together(tmp_path, monkeypatch):
    """20% video and 20% MP3 is 40% of the job running at neither the chain's
    pace nor a modelled one."""
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    mp3 = FileInfo(path=Path("m.mp3"), size=20_000_000, category=Category.AUDIO,
                   entropy_bps=7.99)
    infos = [_video("v.mkv", 20_000_000), mp3, _text("t.txt", 60_000_000)]
    worker = _worker(tmp_path, _summary(infos))
    worker._calibrate(_result(100_000_000, 60.0))
    assert recorded == []


def test_the_threshold_is_the_one_the_recoders_use(tmp_path, monkeypatch):
    """A quarter of the piped bytes, together with the recoded ones: 24% of
    video learns, 25% does not."""
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    for video, expect in ((24_000_000, 1), (25_000_000, 0)):
        recorded.clear()
        infos = [_video("v.mkv", video), _text("t.txt", 100_000_000 - video)]
        worker = _worker(tmp_path, _summary(infos))
        worker._calibrate(_result(100_000_000, 60.0))
        assert len(recorded) == expect, (video, recorded)
