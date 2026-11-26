"""The time estimate's per-file term (2026-11-25).

The rates are bytes per second, fitted on big files, so a tree of small ones
was promised the codec's time and nothing else: 1,801 Python files at Fast
were quoted a quarter of what they took. Every run below went through
`engine.compress` (D9 included) on the i5-7200U with real-time protection on
and a second job on the machine; the record is
docs/benchmarks/2026-11-25-small-files.md.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import (_PER_FILE_FREE, Rates, estimate_time, pack_cost,
                            per_file_seconds, time_split)
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
PLAIN = Rates(ogg_pack=False, jpeg_pack=False)


def _tree(piped: int, piped_bytes: int, stored: int = 0, stored_bytes: int = 0):
    infos = [FileInfo(path=Path(f"p{i}.py"), size=piped_bytes // piped,
                      category=Category.TEXT, entropy_bps=4.5, sample_ratio=0.3,
                      sample_ratio_max=0.35) for i in range(piped)]
    infos += [FileInfo(path=Path(f"s{i}.mp4"), size=stored_bytes // stored,
                       category=Category.VIDEO, entropy_bps=7.99, sample_ratio=1.0,
                       sample_ratio_max=1.0) for i in range(stored)]
    return infos


#: (tree, profile) -> (files as the planner routed them, the runs in seconds).
MEASURED = {
    ("python 1,801", Profile.FAST): (lambda: _tree(1801, 43_402_379), [22.4, 18.1, 19.6]),
    ("python 1,801", Profile.NORMAL): (lambda: _tree(1801, 43_402_379), [30.2, 27.2, 26.7]),
    ("node 3,912", Profile.FAST): (lambda: _tree(2580, 12_425_865, 1332, 8_126_113), [35.1, 36.2, 38.6]),
    ("node 3,912", Profile.NORMAL): (lambda: _tree(2580, 12_425_865, 1332, 8_126_113), [47.4, 42.9, 56.8]),
    ("python 2,245", Profile.FAST): (lambda: _tree(2245, 21_371_967), [23.9, 16.0, 20.0]),
    ("python 2,245", Profile.NORMAL): (lambda: _tree(2245, 21_371_967), [22.6, 20.3, 28.3]),
    ("repo 307", Profile.FAST): (lambda: _tree(302, 3_873_713, 5, 1_934_650), [3.9, 3.2, 4.8]),
    ("repo 307", Profile.NORMAL): (lambda: _tree(302, 3_873_713, 5, 1_934_650), [4.9, 4.2, 4.9]),
    ("png+gif 238 stored", Profile.FAST): (lambda: _tree(1, 1000, 237, 52_399_944), [6.0, 5.2, 5.1]),
    ("photos 150 stored", Profile.FAST): (lambda: _tree(1, 1000, 149, 49_137_142), [6.5, 5.9, 5.2]),
}


@pytest.mark.parametrize("key", sorted(MEASURED, key=str))
def test_every_measured_run_sits_in_the_range(key):
    make, runs = MEASURED[key]
    infos = make()
    t = estimate_time(infos, plan(infos, key[1], TOOLS), PLAIN)
    assert t.low <= min(runs) and max(runs) <= t.high, (key, t, runs)


@pytest.mark.parametrize("key", [k for k in sorted(MEASURED, key=str) if "stored" not in k[0]])
def test_the_figure_is_not_a_fraction_of_the_wait(key):
    """The unsafe direction: it was 0.1-0.5x of the wait on these trees. Now
    0.83-1.22x of the median run (the long side is the safe one)."""
    make, runs = MEASURED[key]
    infos = make()
    t = estimate_time(infos, plan(infos, key[1], TOOLS), PLAIN)
    assert 0.8 <= t.expected / statistics.median(runs) <= 1.25, (key, t.expected, runs)


def test_without_the_term_the_figure_was_a_fraction_of_the_wait():
    infos = _tree(1801, 43_402_379)
    t = estimate_time(infos, plan(infos, Profile.FAST, TOOLS), PLAIN)
    per_file = sum(per_file_seconds(1801))
    assert (t.expected - per_file) / 19.6 < 0.25
    assert per_file == pytest.approx((1801 - _PER_FILE_FREE) * 0.0087)


def test_a_job_of_a_few_files_is_priced_exactly_as_before():
    """B22's fixed second was fitted on jobs of 1 to 24 files and holds their
    per-file cost, so the big-file anchors and B22's own cells do not move."""
    assert per_file_seconds(0) == per_file_seconds(13) == per_file_seconds(24) == (0.0, 0.0)
    assert sum(per_file_seconds(25)) == pytest.approx(0.0087)
    infos = _tree(13, 55_733_142)
    stages = ["sevenzip"]
    t = estimate_time(infos, plan(infos, Profile.NORMAL, TOOLS), PLAIN)
    assert t.expected == pytest.approx(sum(time_split(0, sum(i.size for i in infos), stages)))


def test_the_bar_and_the_table_agree_about_the_per_file_cost():
    infos = _tree(2580, 12_425_865, 1332, 8_126_113)
    the_plan = plan(infos, Profile.NORMAL, TOOLS)
    piped = sum(i.size for i in infos if i.category == Category.TEXT)
    stored = sum(i.size for i in infos) - piped
    compress, verify = time_split(stored, piped, ["sevenzip"], PLAIN, files=len(infos))
    assert compress + verify == pytest.approx(estimate_time(infos, the_plan, PLAIN).expected)
    bare = time_split(stored, piped, ["sevenzip"], PLAIN)
    assert compress - bare[0] == pytest.approx((3912 - 24) * 0.003)
    assert verify - bare[1] == pytest.approx((3912 - 24) * 0.0057)


def test_files_a_specialist_packs_are_not_charged_twice():
    """Lepton's per-file constants were fitted on whole jobs."""
    photos = [FileInfo(path=Path(f"p{i}.jpg"), size=327_588, category=Category.IMAGE,
                       entropy_bps=7.97, is_jpeg=True) for i in range(150)]
    rates = Rates(ogg_pack=False, jpeg_pack=True)
    the_plan = plan(photos, Profile.NORMAL, TOOLS)
    cost = pack_cost(photos, the_plan, rates)
    assert cost.files == 150
    stored = sum(i.size for i in photos)
    assert estimate_time(photos, the_plan, rates).expected == pytest.approx(
        sum(time_split(stored, 0, [], rates, pack=cost)))


def test_the_per_file_cost_is_not_multiplied_by_the_chain_s_spread():
    infos = _tree(1801, 43_402_379)
    t = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS), PLAIN)
    bare = _tree(24, 43_402_379)
    b = estimate_time(bare, plan(bare, Profile.EXTREME, TOOLS), PLAIN)
    per_file = sum(per_file_seconds(1801))
    assert t.high - b.high == pytest.approx(per_file * 2.5, rel=0.02)
    assert t.low - b.low == pytest.approx(per_file * 0.3, rel=0.02)


def _worker(tmp_path, monkeypatch, count):
    from excmp.tools import find_tools
    from gui.models import Job
    from gui.queue_manager import CompressWorker, WorkerSignals
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append(kw))
    worker = CompressWorker(Job(inputs=[tmp_path], out_path=tmp_path / "x.excmp",
                                profile=Profile.NORMAL),
                            WorkerSignals(), tmp_path / "t", find_tools())
    worker._per_file_count = count
    return worker, recorded


def test_calibration_takes_the_per_file_cost_out_of_the_learned_rate(tmp_path, monkeypatch):
    worker, recorded = _worker(tmp_path, monkeypatch, 1024)
    worker._calibrate(SimpleNamespace(piped_bytes=50_000_000, elapsed_s=30.0,
                                      routes=[{"action": "pipeline", "stages": ["sevenzip"]}]))
    assert recorded[0]["elapsed_s"] == pytest.approx(30.0 - 1.0 - 1000 * 0.003)


def test_a_job_paced_by_its_file_count_teaches_no_rate(tmp_path, monkeypatch):
    """4,024 files in 14 s: 12 s is the modelled per-file cost, and what is
    left is that model's error, not 7-Zip's speed."""
    worker, recorded = _worker(tmp_path, monkeypatch, 4024)
    worker._calibrate(SimpleNamespace(piped_bytes=50_000_000, elapsed_s=14.0,
                                      routes=[{"action": "pipeline", "stages": ["sevenzip"]}]))
    assert recorded == []


# -- calibration must still learn from a job that has no per-file term (CI caught this on a faster machine) --------

def _worker_and_result(tmp_path, monkeypatch, per_file_count, elapsed_s):
    import dataclasses

    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    from gui.models import Job
    from gui.queue_manager import CompressWorker, WorkerSignals

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello " * 3000)
    (src / "b.txt").write_text("world " * 3000)
    result = engine.compress([src], tmp_path / "c.excmp", Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    result = dataclasses.replace(result, elapsed_s=elapsed_s)
    recorded = []
    monkeypatch.setattr("excmp.calibrate.record", lambda *a, **kw: recorded.append((a, kw)))
    worker = CompressWorker(Job(inputs=[src], out_path=tmp_path / "c.excmp", profile=Profile.NORMAL),
                            WorkerSignals(), tmp_path / "t", find_tools())
    worker._per_file_count = per_file_count
    return worker, result, recorded


def test_a_job_with_no_per_file_term_is_still_recorded_however_short_it_was(tmp_path, monkeypatch):
    """Without a summary the per-file term is 0. A very fast job leaves a zero or negative remainder after the fixed
    second is taken off; `0 >= that` used to read as 'dominated by the per-file cost' and the job fed nothing to the
    estimator (calibrate.record drops a non-positive time itself). The guard is for a term that was really subtracted."""
    worker, result, recorded = _worker_and_result(tmp_path, monkeypatch, per_file_count=0, elapsed_s=0.01)
    worker._calibrate(result)
    assert recorded, "a job with no per-file term must reach calibrate.record as before"


def test_a_job_paced_by_its_file_count_is_not_learned(tmp_path, monkeypatch):
    worker, result, recorded = _worker_and_result(tmp_path, monkeypatch, per_file_count=50_000, elapsed_s=2.0)
    worker._calibrate(result)
    assert recorded == []
