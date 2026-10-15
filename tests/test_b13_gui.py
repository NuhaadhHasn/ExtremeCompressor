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


def test_pack_without_an_estimate_banks_the_chain_and_never_rescales_it():
    """JPEG and WAV packing report "pack" too, with no estimate behind them.
    Appending it as an unplanned stage rescaled every weight; reported
    halfway through a stage, that moved the bar backwards (review, B13)."""
    bar = ChainProgress(["tar", "precomp", "sevenzip"])
    bar.update("sevenzip", 100.0)
    before = bar.value
    assert bar.update("pack", 50.0) == pytest.approx(before)
    assert bar.update("pack", 100.0) == pytest.approx(before)
    assert "pack" not in bar.chain


def test_an_early_pack_report_without_an_estimate_does_not_move_the_bar_back():
    bar = ChainProgress(["tar", "precomp", "sevenzip"])
    mid = bar.update("precomp", 50.0)
    after = bar.update("pack", 0.0)
    assert after >= mid


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
        # A fixed input name: tmp_path's own name contains "packing" (pytest
        # names it after the test), which let a substring check pass with
        # the feature removed.
        job = Job(kind=JobKind.COMPRESS, inputs=[tmp_path / "album"],
                  out_path=tmp_path / "o.excmp", profile=Profile.NORMAL)
        win.queue.add_job(job)
        job.state = JobState.RUNNING
        win.queue._on_progress(job.id, PACKING, 40.0, 1500.0)
        assert win._job_status_text() == "album · repacking media · ~25 min left"
    finally:
        win.queue.shutdown()


# -- the analysis card ------------------------------------------------------------------

def test_the_gain_note_does_not_call_packed_audio_stored_bit_exact(monkeypatch):
    """Found by rendering the page: an Ogg folder read "99% of this is already
    compressed and will be stored bit-exact; only 8.6 KB can actually shrink"
    beside a table promising 15% saved. The audio is packed, not stored."""
    from excmp import oggpack
    from gui.suggest import gain_note, summarize

    monkeypatch.setattr(oggpack, "available", lambda: True)
    infos = [_ogg(300_000_000), _ogg(2_000_000, "notes.ogg")]
    summary = summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS)
    note = gain_note(summary)
    assert "stored bit-exact" not in note and "~0%" not in note
    assert "repacked" in note and "Ogg" in note


def test_the_gain_note_is_unchanged_without_balrogg(monkeypatch):
    from excmp import oggpack
    from gui.suggest import gain_note, summarize

    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    infos = [_ogg(300_000_000)]
    summary = summarize(infos, plan(infos, Profile.NORMAL, TOOLS), TOOLS)
    assert "repacked" not in gain_note(summary)


def test_calibration_leaves_the_pack_phase_out_of_the_codec_rate(tmp_path, monkeypatch):
    """Packing Ogg audio runs at ~0.1 MB/s on bytes that are not piped.
    Counted as codec time it taught J7 a rate several times too slow for the
    chain (review, B13)."""
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record",
                        lambda *a, **kw: recorded.append((a, kw)))
    worker, _ = _worker(tmp_path, _summary(monkeypatch))
    clock = worker._clock
    worker._on_progress("sevenzip", 100.0)
    clock.now = 100.0
    worker._on_progress("pack", 0.0)
    clock.now = 700.0
    worker._on_progress("pack", 100.0)
    result = SimpleNamespace(piped_bytes=50_000_000, final_bytes=1, orig_bytes=2,
                             elapsed_s=800.0,
                             routes=[{"action": "pipeline", "stages": ["sevenzip"]}])
    worker._calibrate(result)
    (_args, kwargs), = recorded
    assert kwargs["elapsed_s"] == pytest.approx(800.0 - 600.0)


# -- review findings whose skeptic checks were lost to an API outage, re-checked here ----

def _ogg_summary(monkeypatch, available=True):
    from excmp import oggpack
    from excmp.planner import Profile as P
    from excmp.planner import plan as make_plan
    from gui.suggest import summarize

    if available:
        monkeypatch.setattr(oggpack, "available", lambda: True)
    else:
        monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    infos = [_ogg(150_000_000, "music.ogg"), _ogg(60_000_000, "speech.ogg")]
    return summarize(infos, make_plan(infos, P.NORMAL, TOOLS), TOOLS,
                     make_plan(infos, P.INSANE, TOOLS))


def test_an_ogg_folder_is_not_called_already_compressed(monkeypatch):
    """With balrogg the folder shrinks 4-15%; the card used to recommend Fast
    because "the slow profiles would spend hours to save the same ~0%"."""
    from gui.suggest import recommend_profile

    _profile, reason = recommend_profile(_ogg_summary(monkeypatch))
    assert "~0%" not in reason and "already compressed" not in reason


def test_an_ogg_folder_is_not_told_only_re_encoding_helps(monkeypatch):
    from gui.suggest import shrink_mode_hint

    assert shrink_mode_hint(_ogg_summary(monkeypatch)) is None


def test_repacked_audio_is_not_listed_as_a_file_that_did_not_shrink(monkeypatch):
    summary = _ogg_summary(monkeypatch)
    assert summary.store_files == []
    assert summary.store_by_category.get(Category.AUDIO, 0) == 0
    # ...while the route itself is unchanged: the files still take the store
    # route, which is what the time arithmetic reads.
    assert summary.store_bytes == 210_000_000


def test_without_balrogg_an_ogg_folder_reads_as_before(monkeypatch):
    from gui.suggest import shrink_mode_hint

    summary = _ogg_summary(monkeypatch, available=False)
    assert summary.store_by_category.get(Category.AUDIO, 0) > 0
    assert shrink_mode_hint(summary) is not None


def test_the_first_pack_report_is_never_throttled_away(tmp_path, monkeypatch):
    """The chain's last report and "pack" 0.0 land on the same bar value a
    moment apart, so the throttle dropped the label change: the job said
    "sevenzip" for the whole first file, which can be minutes of Vorbis."""
    worker, progress = _worker(tmp_path, _summary(monkeypatch))
    worker._on_progress("sevenzip", 100.0)
    worker._on_progress("pack", 0.0)                 # same instant, same value
    assert progress.calls[-1][1] == PACKING
