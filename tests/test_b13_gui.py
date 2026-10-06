"""B13: the job's bar and status know there is a packing phase.

The pack phase runs after the chain and before the D9 self-test, and for an
Ogg folder it is most of the job (an hour per gigabyte of Vorbis). Left as an
unplanned stage the bar would park, then rescale every weight when "pack"
turned up. With the estimate it gets its own band, between the chain's and the
self-test's, sized in seconds like theirs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import PackCost, time_split
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo
from gui.progress import (PACKING, PIPELINE_CEILING, VERIFY_STAGE, VERIFYING,
                          ChainProgress)

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


def _ogg(size, name="a.ogg"):
    return FileInfo(path=Path(name), size=size, category=Category.AUDIO,
                    entropy_bps=7.97, sample_ratio=1.0, sample_ratio_max=1.0)


# -- the summary ----------------------------------------------------------------

def test_the_summary_carries_the_pack_cost(monkeypatch):
    from excmp import oggpack
    from gui.suggest import summarize

    monkeypatch.setattr(oggpack, "available", lambda: True)
    infos = [_ogg(200_000_000)]
    summary = summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS)
    assert summary.pack_bytes == 200_000_000
    assert summary.pack_seconds > 60
    assert summary.pack_verify_seconds > 60


def test_without_balrogg_the_summary_has_no_pack_cost(monkeypatch):
    from excmp import oggpack
    from gui.suggest import summarize

    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    infos = [_ogg(200_000_000)]
    summary = summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS)
    assert (summary.pack_bytes, summary.pack_seconds) == (0, 0.0)


# -- the bar ----------------------------------------------------------------------

def _bar():
    # 100 s of chain, 300 s of packing, 100 s of self-test.
    return ChainProgress(["sevenzip"], compress_s=400.0, verify_s=100.0, pack_s=300.0)


def test_the_pack_band_sits_between_the_chain_and_the_self_test():
    bar = _bar()
    chain_top = PIPELINE_CEILING * 100 / 500
    pack_top = PIPELINE_CEILING * 400 / 500
    assert bar.update("sevenzip", 100.0) == pytest.approx(chain_top)
    assert bar.update("pack", 0.0) == pytest.approx(chain_top)
    assert bar.update("pack", 50.0) == pytest.approx((chain_top + pack_top) / 2)
    assert bar.update("pack", 100.0) == pytest.approx(pack_top)
    assert bar.verify(0.0) == pytest.approx(pack_top)
    assert bar.verify(1e9) < PIPELINE_CEILING
    assert bar.verify_done() == pytest.approx(PIPELINE_CEILING)


def test_the_bar_never_goes_backwards_across_the_three_bands():
    bar = _bar()
    seen = [bar.update("sevenzip", 40.0), bar.update("sevenzip", 100.0)]
    seen += [bar.update("pack", p) for p in (0, 30, 20, 100)]
    seen += [bar.verify(t) for t in (0, 10, 5, 50)]
    assert seen == sorted(seen)


def test_a_chainless_ogg_job_spends_its_bar_in_the_pack_band():
    """All-stored: no stage reports at all before the packing starts."""
    bar = ChainProgress([], compress_s=310.0, verify_s=60.0, pack_s=300.0)
    start = bar.update("pack", 0.0)
    assert start < PIPELINE_CEILING * 15 / 370 + 1e-9
    assert bar.update("pack", 100.0) == pytest.approx(PIPELINE_CEILING * 310 / 370)


def test_pack_without_an_estimate_is_an_unplanned_stage_as_before():
    bar = ChainProgress(["sevenzip"])
    bar.update("sevenzip", 100.0)
    before = bar.value
    assert bar.update("pack", 50.0) >= before
    assert "pack" in bar.chain


# -- the worker ---------------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _worker(tmp_path, summary):
    from gui.models import Job
    from gui.queue_manager import CompressWorker

    signals = SimpleNamespace(progress=_Recorder(), log=_Recorder(),
                              started=_Recorder(), done=_Recorder(),
                              failed=_Recorder(), cancelled=_Recorder())
    job = Job(inputs=[tmp_path], out_path=tmp_path / "o.excmp",
              profile=Profile.NORMAL, summary=summary)
    worker = CompressWorker(job, signals, tmp_path, tools={})
    worker._clock = _Clock()
    return worker, signals.progress


def _summary(monkeypatch):
    from excmp import oggpack
    from gui.suggest import summarize

    monkeypatch.setattr(oggpack, "available", lambda: True)
    infos = [_ogg(100_000_000)]
    return summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS)


def test_the_worker_sizes_the_bands_from_the_summary(tmp_path, monkeypatch):
    summary = _summary(monkeypatch)
    worker, progress = _worker(tmp_path, summary)
    assert worker._chain.pack_s == pytest.approx(summary.pack_seconds)

    worker._on_progress("pack", 0.0)
    _id, stage, pct0, _eta = progress.calls[-1]
    assert stage == PACKING
    worker._on_progress("pack", 100.0)
    _id, stage, pct1, _eta = progress.calls[-1]
    assert pct1 > pct0 + 20, "packing was most of this job and the bar barely moved"
    assert pct1 < PIPELINE_CEILING

    worker._on_progress(VERIFY_STAGE, 0.0)
    assert progress.calls[-1][1] == VERIFYING
    assert progress.calls[-1][2] >= pct1


def test_the_time_estimate_includes_packing(monkeypatch):
    from gui.queue_manager import _time_split

    summary = _summary(monkeypatch)
    compress_s, verify_s = _time_split(summary)
    plain_c, plain_v = time_split(summary.store_bytes, summary.pipeline_bytes,
                                  summary.chain)
    assert compress_s == pytest.approx(plain_c + summary.pack_seconds)
    assert verify_s == pytest.approx(plain_v + summary.pack_verify_seconds)
    assert isinstance(PackCost(), PackCost)


# -- what the strip says --------------------------------------------------------------

def test_the_strip_says_packing_with_the_time_left(tmp_path, qtbot):
    from gui.mainwindow import MainWindow
    from gui.models import Job, JobKind, JobState

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        win.queue.pause()
        job = Job(kind=JobKind.COMPRESS, inputs=[tmp_path],
                  out_path=tmp_path / "o.excmp", profile=Profile.NORMAL)
        win.queue.add_job(job)
        job.state = JobState.RUNNING
        win.queue._on_progress(job.id, PACKING, 40.0, 1500.0)
        text = win._job_status_text()
        assert "packing" in text and "left" in text and "estimating" not in text
    finally:
        win.queue.shutdown()
