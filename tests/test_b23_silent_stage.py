"""B23: an Insane job's bar did not freeze at the top of the chain's band.

zpaqfranz prints ONE percentage line when it compresses, the scan line, at
0.1 s: `100.00% 00:00:00 (13.35 MB)=>(0.00 B)`, a 100% with nothing written.
Then nothing for the whole compress (measured 2026-11-17: 14 MB at -m58, one
thread, 82.5 s, 24 lines in all, that being the only one with a `%`). The stage
parsed the scan line as progress, `ChainProgress` took the stage as finished
(zpaqfranz is 400 of the chain's 440 weight), and the bar jumped to the top of
the chain's band and sat there for the hours Insane takes.

Two repairs: the scan line is not progress, and a stage known to be silent
moves the bar through its own band against the estimate, as the self-test
already does (`VERIFY_TIME_CAP`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from excmp.planner import Profile                    # noqa: E402
from excmp.stages.zpaqfranz import _parse_percent    # noqa: E402
from gui.progress import SILENT_TIME_CAP, ChainProgress  # noqa: E402

#: What zpaqfranz printed, captured 2026-11-17 (v64.8j, -m58 -t1, a 14 MB input).
SCAN_LINE = "       100.00% 00:00:00  (  13.35 MB)=>(   0.00  B)   13.35 MB/s"
CHAIN = ["tar", "precomp", "zpaqfranz"]


# -- the stage ----------------------------------------------------------------

def test_the_scan_line_is_not_progress():
    assert _parse_percent(SCAN_LINE) is None


def test_a_line_with_output_written_is_still_progress():
    line = "        42.00% 00:01:10  (  13.35 MB)=>(   6.20 MB)    1.20 MB/s"
    assert _parse_percent(line) == 42.0
    assert _parse_percent("  7z: 12% done") == 12.0
    assert _parse_percent("no percentage here") is None


# -- the bar -----------------------------------------------------------------

def _at_zpaqfranz(compress_s=600.0, verify_s=500.0):
    chain = ChainProgress(CHAIN, compress_s=compress_s, verify_s=verify_s)
    chain.update("tar", 100.0)
    chain.update("precomp", 100.0)
    return chain


def test_the_next_stage_of_a_chain_is_named_silent_when_it_is_zpaqfranz():
    assert _at_zpaqfranz().silent_stage() == "zpaqfranz"


def test_a_stage_that_reports_is_not_silent():
    chain = ChainProgress(["tar", "precomp", "sevenzip"], compress_s=60.0, verify_s=30.0)
    chain.update("tar", 100.0)
    chain.update("precomp", 100.0)
    assert chain.silent_stage() is None


def test_nothing_is_silent_before_the_stage_before_it_is_done():
    chain = ChainProgress(CHAIN, compress_s=600.0, verify_s=500.0)
    chain.update("tar", 100.0)
    chain.update("precomp", 40.0)
    assert chain.silent_stage() is None


def test_the_bar_moves_through_a_silent_stage_and_never_past_its_cap():
    chain = _at_zpaqfranz()
    start = chain.value
    top = chain._chain_top
    first, mid, late = chain.creep(5.0), chain.creep(300.0), chain.creep(100_000.0)
    assert start <= first < mid < late < top
    assert late <= start + SILENT_TIME_CAP * (top - start) + 1e-9
    # Monotonic: a shorter elapsed asked later never takes it back.
    assert chain.creep(10.0) == late


def test_the_stage_closing_banks_its_band_and_ends_the_creep():
    chain = _at_zpaqfranz()
    chain.creep(300.0)
    chain.update("zpaqfranz", 100.0)
    assert chain.silent_stage() is None
    assert chain.value == pytest.approx(chain._chain_top)


def test_without_an_estimate_the_bar_waits_where_it_was():
    chain = ChainProgress(CHAIN)
    chain.update("tar", 100.0)
    chain.update("precomp", 100.0)
    assert chain.silent_stage() == "zpaqfranz"
    assert chain.creep(300.0) == chain.value


def test_a_stage_skipped_over_counts_as_done_and_the_creep_never_goes_back():
    """A StageSkip jumps the report forward: the stages between are banked, so
    a stage that does report (a newer zpaqfranz, say) is simply followed, and
    the creep cannot take the bar back from where it put it."""
    chain = ChainProgress(CHAIN, compress_s=600.0, verify_s=500.0)
    chain.update("tar", 100.0)
    chain.update("zpaqfranz", 10.0)                   # precomp was skipped
    assert chain.silent_stage() == "zpaqfranz"
    reported = chain.value
    assert reported > chain.creep(0.0) - 1e-9
    assert chain.creep(1.0) >= reported


# -- the worker --------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _worker(tmp_path, clock):
    from gui.models import Job
    from gui.queue_manager import CompressWorker
    from gui.suggest import AnalysisSummary

    summary = AnalysisSummary(
        total_bytes=50_000_000, file_count=2, by_category={}, store_by_category={},
        store_bytes=0, pipeline_bytes=50_000_000, store_files=[], warnings=[],
        chain=list(CHAIN))
    signals = SimpleNamespace(progress=_Recorder(), log=_Recorder(),
                              started=_Recorder(), done=_Recorder(),
                              failed=_Recorder(), cancelled=_Recorder())
    job = Job(inputs=[tmp_path], out_path=tmp_path / "o.excmp",
              profile=Profile.INSANE, summary=summary)
    worker = CompressWorker(job, signals, tmp_path, tools={})
    worker._clock = clock
    worker._t0 = 0.0
    return worker, signals.progress


def test_the_worker_moves_the_bar_while_zpaqfranz_is_silent(tmp_path):
    clock = _Clock()
    worker, progress = _worker(tmp_path, clock)
    worker._on_progress("tar", 100.0)
    worker._on_progress("precomp", 100.0)
    clock.now = 0.0
    worker._heartbeat_once()            # the stage's clock starts; the bar is
    drawn = len(progress.calls)         # already at the stage's start, so no draw
    seen = []
    for t in (60.0, 300.0, 600.0):
        clock.now = t
        worker._heartbeat_once()
        seen.append(progress.calls[-1])
    assert len(progress.calls) == drawn + 3
    assert [c[1] for c in seen] == ["zpaqfranz"] * 3          # the stage's name
    bars = [c[2] for c in seen]
    assert bars == sorted(bars) and len(set(bars)) == 3, bars
    assert bars[-1] < 95.0                                     # never past the ceiling


def test_the_heartbeat_is_silent_when_no_stage_is_silent(tmp_path):
    clock = _Clock()
    worker, progress = _worker(tmp_path, clock)
    worker._heartbeat_once()                                   # nothing has run yet
    worker._on_progress("tar", 40.0)
    n = len(progress.calls)
    clock.now = 30.0
    worker._heartbeat_once()
    assert len(progress.calls) == n


def test_the_heartbeat_stops_when_the_stage_reports_its_end(tmp_path):
    clock = _Clock()
    worker, progress = _worker(tmp_path, clock)
    worker._on_progress("tar", 100.0)
    worker._on_progress("precomp", 100.0)
    clock.now = 100.0
    worker._heartbeat_once()
    worker._on_progress("zpaqfranz", 100.0)
    n = len(progress.calls)
    clock.now = 200.0
    worker._heartbeat_once()
    assert len(progress.calls) == n


# -- review: a skipped stage, a pause, a stop --------------------------------------

def test_the_bar_creeps_when_precomp_found_nothing_and_was_skipped(tmp_path):
    """A StageSkip passes the data through and the engine sends nothing more:
    the stage before the silent one never read as finished, so nothing crept
    through the whole zpaqfranz stage (review, reproduced on the real Precomp:
    events `[('precomp', 0.0), ('sevenzip', 0.0), ...]`). The skip now reads as
    the stage's end, which is what it is."""
    from excmp.engine import compress
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools

    tools = find_tools(with_versions=True)
    if not all(tools.get(n) for n in ("precomp", "7z")):
        pytest.skip("needs Precomp and 7-Zip")
    src = tmp_path / "in"
    src.mkdir()
    # Piped (it is not noise) but with no deflate stream for Precomp to open.
    (src / "data.bin").write_bytes(bytes((i * 7 + (i >> 8)) & 0xFF for i in range(1_500_000)))
    (src / "notes.txt").write_text("hello world " * 50_000)
    events = []
    ctx = StageContext(temp_dir=tmp_path / "t")
    ctx.progress_cb = lambda stage, pct: events.append((stage, pct))
    compress([src], tmp_path / "o.excmp", Profile.EXTREME, ctx, tools)
    assert ("precomp", 100.0) in events, events


def test_a_skipped_stage_banks_its_band_in_the_chain():
    chain = ChainProgress(CHAIN, compress_s=1000.0, verify_s=100.0)
    chain.update("tar", 100.0)
    chain.update("precomp", 0.0)                 # it started...
    chain.update("precomp", 100.0)               # ...and the engine says it is over
    assert chain.silent_stage() == "zpaqfranz"
    assert chain.creep(500.0) > chain.value - 1e-9


def test_the_heartbeat_does_not_creep_through_a_pause(tmp_path):
    """Pause holds the engine between stages, so after Precomp the next stage
    is "silent" and waiting: its clock must not run, and on resume it starts
    from where it stopped, not from the pause's length."""
    clock = _Clock()
    worker, progress = _worker(tmp_path, clock)
    worker._on_progress("tar", 100.0)
    worker._on_progress("precomp", 100.0)
    clock.now = 0.0
    worker._heartbeat_once()                     # the clock starts
    worker.ctx.pause.set()
    drawn = len(progress.calls)
    for t in (30.0, 60.0, 100.0):
        clock.now = t
        worker._heartbeat_once()
    assert len(progress.calls) == drawn          # nothing moved while paused
    worker.ctx.pause.clear()
    clock.now = 101.0
    worker._heartbeat_once()
    resumed = progress.calls[-1][2]
    clock2 = _Clock()
    worker2, progress2 = _worker(tmp_path, clock2)
    worker2._on_progress("tar", 100.0)
    worker2._on_progress("precomp", 100.0)
    worker2._heartbeat_once()
    clock2.now = 101.0
    worker2._heartbeat_once()
    unpaused = progress2.calls[-1][2]
    assert resumed < unpaused, (resumed, unpaused)


def test_a_stopped_heartbeat_draws_nothing_more(tmp_path):
    """A beat already in flight when the job ends must not overwrite the
    finished job's bar."""
    clock = _Clock()
    worker, progress = _worker(tmp_path, clock)
    worker._on_progress("tar", 100.0)
    worker._on_progress("precomp", 100.0)
    worker._heartbeat_once()
    import threading
    worker._stop_heartbeat(threading.Event())
    n = len(progress.calls)
    clock.now = 500.0
    worker._heartbeat_once()
    assert len(progress.calls) == n
