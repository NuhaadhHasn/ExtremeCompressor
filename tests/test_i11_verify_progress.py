"""I11: the D9 self-test is a visible phase of the job, not a parked bar.

The pre-publish restore used to report through the muted context, so the bar
sat at 95% for the whole self-test - 1,556 s of a 3,810 s Insane job on
Silesia. zpaqfranz prints nothing between its header and its summary, so
there is no percentage to parse. What the app *does* know is how long the
self-test should take (``_VERIFY_RATE``), so the honest design is:

* the engine says when the self-test starts and ends, and keeps a heartbeat
  in between so the GUI can redraw without a timer of its own;
* the bar gives the self-test its estimated share of the job and moves
  through it by elapsed time against that estimate, never all the way;
* the remaining time is the estimate minus the elapsed time, and once the
  estimate is spent the app says so instead of inventing a new number.
"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from excmp.estimate import DEFAULT_RATES, estimate_time, time_split
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools
from gui.progress import (PIPELINE_CEILING, VERIFY_STAGE, VERIFY_TIME_CAP,
                          VERIFYING, VERIFYING_LATE, ChainProgress)

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")

INSANE = ["precomp", "zpaqfranz"]


# -- the estimate's two halves ----------------------------------------------

def test_time_split_is_compress_then_verify():
    rates = DEFAULT_RATES
    stored, piped = 10_000_000, 2_000_000
    compress_s, verify_s = time_split(stored, piped, INSANE, rates)
    assert compress_s == pytest.approx(stored / rates.io_rate
                                       + piped / rates.rate_for(INSANE))
    # Stored files restore by a zip copy, piped ones through the chain (B17).
    assert verify_s == pytest.approx(stored / rates.io_rate
                                     + piped / rates.verify_rate_for(INSANE))


def test_estimate_time_expected_is_the_sum_of_the_split():
    """One formula, two callers: the bar's share and the comparison table
    must never disagree about how long the self-test takes."""
    from excmp.analyzer import Category, FileInfo
    from excmp.planner import plan as make_plan

    infos = [FileInfo(path=Path(f"f{i}.txt"), size=5_000_000,
                      category=Category.TEXT, entropy_bps=4.0, sample_ratio=0.3,
                      sample_ratio_max=0.35)
             for i in range(3)]
    tools = find_tools()
    the_plan = make_plan(infos, Profile.NORMAL, tools)
    piped = sum(i.size for r in the_plan.routes if r.action == "pipeline"
                for i in infos if i.path in r.files)
    stored = sum(i.size for i in infos) - piped
    assert piped, "the fixture must exercise the codec term"
    stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])
    expected = estimate_time(infos, the_plan).expected
    assert expected == pytest.approx(sum(time_split(stored, piped, stages)))


# -- the bar -----------------------------------------------------------------

def _finish_compress(chain: ChainProgress) -> float:
    for stage in chain.chain:
        chain.update(stage, 100.0)
    return chain.value


def test_the_self_test_gets_its_estimated_share_of_the_bar():
    # Silesia at -m58 (B17): 2,254 s compressing, 1,556 s restoring.
    chain = ChainProgress(["tar", *INSANE], compress_s=2254.0, verify_s=1556.0)
    start = _finish_compress(chain)
    assert start == pytest.approx(PIPELINE_CEILING * 2254 / 3810)

    band = PIPELINE_CEILING - start
    assert chain.verify(0.0) == pytest.approx(start)
    assert chain.verify(778.0) == pytest.approx(start + band * 0.5)
    # Time alone never fills the band: a slow restore parks short of it.
    late = chain.verify(1556.0 * 10)
    assert late == pytest.approx(start + band * VERIFY_TIME_CAP)
    assert late < PIPELINE_CEILING
    # The engine's own "done" is what closes it.
    assert chain.verify_done() == pytest.approx(PIPELINE_CEILING)
    assert chain.finish() == 100.0


def test_verify_progress_never_goes_backwards():
    chain = ChainProgress(["tar", *INSANE], compress_s=100.0, verify_s=100.0)
    _finish_compress(chain)
    seen = [chain.verify(t) for t in (0, 10, 50, 40, 90, 200, 5)]
    assert seen == sorted(seen)


def test_remaining_is_the_estimate_minus_elapsed_then_unknown():
    chain = ChainProgress(["tar", *INSANE], compress_s=2254.0, verify_s=1556.0)
    assert chain.verify_remaining(500.0) == pytest.approx(1056.0)
    # Past the estimate there is no honest number left to show.
    assert chain.verify_remaining(1556.0) is None
    assert chain.verify_remaining(2000.0) is None


@pytest.mark.parametrize("kw", [{}, {"compress_s": 100.0, "verify_s": 0.0},
                                {"compress_s": None, "verify_s": 50.0}])
def test_without_an_estimate_the_old_behaviour_stands(kw):
    chain = ChainProgress(["sevenzip"], **kw)
    assert _finish_compress(chain) == pytest.approx(PIPELINE_CEILING)
    assert chain.verify(1000.0) == pytest.approx(PIPELINE_CEILING)
    assert chain.verify_remaining(10.0) is None


def test_verify_is_not_mistaken_for_an_unplanned_stage():
    """``update`` appends any stage it has not heard of. The self-test is not
    a stage of the chain, and appending it would rescale every weight."""
    chain = ChainProgress(["sevenzip"])
    chain.update("sevenzip", 50.0)
    before = chain.value
    chain.update(VERIFY_STAGE, 0.0)
    assert VERIFY_STAGE not in chain.chain
    assert chain.value == before


# -- the engine --------------------------------------------------------------

def _fake_verify(seconds: float, *, raises: bool = False, spy=None):
    def run(archive, quiet):
        if spy is not None:
            spy(quiet)
        time.sleep(seconds)
        if raises:
            raise RuntimeError("restore mismatch")
        return SimpleNamespace(files_restored=1, verified=1, elapsed_s=seconds)
    return run


def test_the_self_test_announces_itself_and_keeps_a_heartbeat(tmp_path, monkeypatch):
    from excmp import engine

    calls: list[tuple[str, float]] = []
    ctx = StageContext(temp_dir=tmp_path,
                       progress_cb=lambda s, p: calls.append((s, p)))
    monkeypatch.setattr(engine, "_VERIFY_HEARTBEAT_S", 0.05)

    def spy(quiet):
        # The restore's own stage reports stay muted: they describe the
        # restore, not the job, and would drag the bar back to the chain.
        quiet.progress_cb("zpaqfranz", 50.0)

    monkeypatch.setattr(engine, "verify_archive", _fake_verify(0.5, spy=spy))
    engine._verify_before_publish(tmp_path / "x.excmp", ctx)

    assert ("zpaqfranz", 50.0) not in calls
    assert calls[0] == (VERIFY_STAGE, 0.0)
    assert calls[-1] == (VERIFY_STAGE, 100.0)
    assert all(s == VERIFY_STAGE for s, _ in calls)
    beats = [c for c in calls[1:-1]]
    assert len(beats) >= 3, "no heartbeat: the GUI would have nothing to redraw on"
    assert all(p == 0.0 for _, p in beats), "a heartbeat is not a measurement"

    settled = len(calls)
    time.sleep(0.2)
    assert len(calls) == settled, "the heartbeat outlived the self-test"


def test_a_failed_self_test_stops_the_heartbeat_and_never_says_done(
        tmp_path, monkeypatch):
    from excmp import engine

    calls: list[tuple[str, float]] = []
    ctx = StageContext(temp_dir=tmp_path,
                       progress_cb=lambda s, p: calls.append((s, p)))
    monkeypatch.setattr(engine, "_VERIFY_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(engine, "verify_archive", _fake_verify(0.2, raises=True))
    threads_before = threading.active_count()

    with pytest.raises(RuntimeError):
        engine._verify_before_publish(tmp_path / "x.excmp", ctx)

    assert (VERIFY_STAGE, 100.0) not in calls
    settled = len(calls)
    time.sleep(0.2)
    assert len(calls) == settled
    assert threading.active_count() <= threads_before


@needs_7z
def test_a_real_job_reports_the_self_test_after_every_stage(tmp_path):
    """Through the public verb, the way the GUI calls it."""
    from excmp import engine

    src = tmp_path / "data"
    src.mkdir()
    (src / "text.txt").write_text("verify me. " * 5_000)
    (src / "blob.bin").write_bytes(random.Random(3).randbytes(4_000))

    calls: list[tuple[str, float]] = []
    ctx = StageContext(temp_dir=tmp_path / "t",
                       progress_cb=lambda s, p: calls.append((s, p)))
    engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)

    stages = [s for s, _ in calls]
    first = stages.index(VERIFY_STAGE)
    assert calls[first] == (VERIFY_STAGE, 0.0)
    assert calls[-1] == (VERIFY_STAGE, 100.0)
    assert set(stages[first:]) == {VERIFY_STAGE}, \
        "a chain stage reported after the self-test began"
    assert first > 0, "the chain itself reported nothing"


# -- the worker --------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def _worker(tmp_path, summary, clock):
    from gui.models import Job
    from gui.queue_manager import CompressWorker

    signals = SimpleNamespace(progress=_Recorder(), log=_Recorder(),
                              started=_Recorder(), done=_Recorder(),
                              failed=_Recorder(), cancelled=_Recorder())
    job = Job(inputs=[tmp_path], out_path=tmp_path / "o.excmp",
              profile=Profile.INSANE, summary=summary)
    worker = CompressWorker(job, signals, tmp_path, tools={})
    worker._clock = clock
    return worker, signals.progress


def _summary(store_bytes: int, pipeline_bytes: int, chain):
    from gui.suggest import AnalysisSummary

    return AnalysisSummary(
        total_bytes=store_bytes + pipeline_bytes, file_count=2, by_category={},
        store_by_category={}, store_bytes=store_bytes,
        pipeline_bytes=pipeline_bytes, store_files=[], warnings=[],
        chain=list(chain))


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_the_worker_shows_a_verifying_phase_against_its_estimate(tmp_path):
    summary = _summary(0, 50_000_000, ["tar", *INSANE])
    compress_s, verify_s = time_split(0, 50_000_000, INSANE)
    clock = _Clock()
    worker, progress = _worker(tmp_path, summary, clock)
    worker._t0 = 0.0

    for stage in ("tar", *INSANE):
        clock.now += compress_s / 3
        worker._on_progress(stage, 100.0)
    start = PIPELINE_CEILING * compress_s / (compress_s + verify_s)
    assert progress.calls[-1][2] == pytest.approx(start)

    worker._on_progress(VERIFY_STAGE, 0.0)
    _id, stage, pct, eta = progress.calls[-1]
    assert stage == VERIFYING
    assert pct == pytest.approx(start)
    assert eta == pytest.approx(verify_s)

    clock.now += verify_s / 2
    worker._on_progress(VERIFY_STAGE, 0.0)          # heartbeat
    _id, stage, pct, eta = progress.calls[-1]
    assert stage == VERIFYING
    assert start < pct < PIPELINE_CEILING
    assert eta == pytest.approx(verify_s / 2)

    clock.now += verify_s                           # well past the estimate
    worker._on_progress(VERIFY_STAGE, 0.0)
    _id, stage, pct, eta = progress.calls[-1]
    assert stage == VERIFYING_LATE
    assert eta is None
    assert pct < PIPELINE_CEILING

    worker._on_progress(VERIFY_STAGE, 100.0)
    assert progress.calls[-1][2] == pytest.approx(PIPELINE_CEILING)
    assert worker._verify_elapsed == pytest.approx(verify_s * 1.5)


def test_calibration_learns_the_codec_rate_without_the_self_test(
        tmp_path, monkeypatch):
    """J7 divided piped bytes by the whole job, self-test included, and
    ``estimate_time`` then added the self-test on top: after one Insane job
    the estimate would carry the restore twice."""
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record",
                        lambda *a, **kw: recorded.append((a, kw)))
    clock = _Clock()
    worker, _ = _worker(tmp_path, _summary(0, 50_000_000, ["tar", *INSANE]), clock)
    worker._on_progress(VERIFY_STAGE, 0.0)
    clock.now = 1556.0
    worker._on_progress(VERIFY_STAGE, 100.0)

    result = SimpleNamespace(piped_bytes=211_938_580, final_bytes=37_542_028,
                             orig_bytes=211_938_580, elapsed_s=3810.0,
                             routes=[{"action": "pipeline", "stages": INSANE}])
    worker._calibrate(result)
    (_args, kwargs), = recorded
    assert kwargs["elapsed_s"] == pytest.approx(3810.0 - 1556.0)


def test_a_job_with_no_analysis_still_runs_its_self_test_honestly(tmp_path):
    clock = _Clock()
    worker, progress = _worker(tmp_path, None, clock)
    worker._t0 = 0.0
    clock.now = 10.0
    worker._on_progress("sevenzip", 100.0)
    clock.now = 20.0
    worker._on_progress(VERIFY_STAGE, 0.0)
    _id, stage, pct, eta = progress.calls[-1]
    assert stage == VERIFYING
    assert pct == pytest.approx(PIPELINE_CEILING)
    assert eta is None


# -- the CLI -------------------------------------------------------------------

def test_the_cli_shows_the_self_test_as_elapsed_time_not_a_frozen_zero(capsys):
    from excmp import cli

    clock = _Clock()
    show = cli._progress_printer(SimpleNamespace(json=False), clock=clock)
    show("zpaqfranz", 100.0)
    show(VERIFY_STAGE, 0.0)
    clock.now = 75.0
    show(VERIFY_STAGE, 0.0)
    frames = capsys.readouterr().out.split("\r")
    assert "[zpaqfranz] 100.0%" in frames[1]
    assert "0.0%" not in frames[-1]
    assert "verify" in frames[-1] and "1m 15s" in frames[-1]
    # The line is overwritten with \r, so a shorter frame must blank the rest.
    assert len({len(f) for f in frames[1:]}) == 1


def test_the_cli_printer_is_silent_under_json(capsys):
    from excmp import cli

    show = cli._progress_printer(SimpleNamespace(json=True))
    show(VERIFY_STAGE, 0.0)
    assert capsys.readouterr().out == ""
