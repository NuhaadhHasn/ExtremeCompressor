"""I6: "compare presets on this input", from the run down to the card.

The feature replaces an estimate with a measurement, so the tests are mostly
about the seam between those two claims rather than about the plumbing:

- a measured saving must reach the card AND the spoken sentence, because the
  one defect this panel has already shipped was a number a screen reader could
  not hear (see ``compare_table.py``'s own note about the caveat);
- a measurement must **not** move the recommendation. It is taken from a
  sample and the recommendation is about the whole input, and quietly letting
  56 MB decide a 5 GB job is the failure mode the honest wording exists to
  prevent;
- a run that produced no bytes is a failed run, not a 100% saving. Both LOLZ's
  decompressor and Precomp are on record exiting 0 with nothing to show for
  it, which is why nothing here trusts a job's completion over its numbers.

The last test runs the thing for real - a live ``QueueManager``, two profiles,
a real archive written and verified - because every defect this project has
shipped behind a green suite was found by running the product instead.
"""

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, resolved_chain
from excmp.sample import MeasuredRun, pick_sample
from excmp.tools import ToolInfo

pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, Signal            # noqa: E402

from gui.compare_run import ComparisonRun             # noqa: E402
from gui.suggest import (ComparisonRow, measurement_caption,  # noqa: E402
                         profile_comparison, summarize)
from gui.widgets.compare_table import CompareTable, ProfileRow  # noqa: E402
from excmp.planner import plan as make_plan           # noqa: E402

ALL_TOOLS = {
    "7z": ToolInfo("7z", "7z.exe"),
    "precomp": ToolInfo("precomp", "precomp.exe"),
    "zpaqfranz": ToolInfo("zpaqfranz", "zpaqfranz.exe"),
}
NO_PRECOMP = {"7z": ToolInfo("7z", "7z.exe")}


def _infos():
    return [
        FileInfo(path=Path("app.exe"), size=40_000_000,
                 category=Category.EXECUTABLE, entropy_bps=7.1,
                 sample_ratio=0.62, sample_ratio_max=0.80),
        FileInfo(path=Path("notes.txt"), size=4_000_000,
                 category=Category.TEXT, entropy_bps=4.4,
                 sample_ratio=0.28, sample_ratio_max=0.34),
    ]


def _rows(measured=None, tools=ALL_TOOLS):
    infos = _infos()
    the_plan = make_plan(infos, Profile.NORMAL, tools)
    summary = summarize(infos, the_plan, tools)
    return profile_comparison(infos, tools, summary, measured=measured)


def _run(profile=Profile.NORMAL, orig=10_000_000, final=4_000_000):
    return MeasuredRun(profile=profile, orig_bytes=orig, final_bytes=final,
                       elapsed_s=12.0)


# -- the data contract -----------------------------------------------------

def test_without_a_measurement_nothing_changes():
    for row in _rows():
        assert row.measured_saved_text == ""
        assert row.measured_note == ""


def test_a_measured_profile_carries_its_real_saving_and_says_it_is_measured():
    rows = _rows(measured={Profile.NORMAL: _run(Profile.NORMAL,
                                                10_000_000, 4_000_000)})
    normal = next(r for r in rows if r.profile is Profile.NORMAL)
    assert normal.measured_saved_text == "60%"
    assert normal.measured_note == "measured"


def test_only_the_profiles_that_were_run_are_marked():
    rows = _rows(measured={Profile.FAST: _run(Profile.FAST)})
    marked = [r.profile for r in rows if r.measured_saved_text]
    assert marked == [Profile.FAST]


def test_an_unverified_run_never_reaches_a_card():
    """The engine verifies before publishing, so this cannot happen today.
    It is asserted anyway: the one rule that must not acquire an exception is
    that an unverified byte count is not a result."""
    run = MeasuredRun(profile=Profile.NORMAL, orig_bytes=100, final_bytes=40,
                      verified=False)
    rows = _rows(measured={Profile.NORMAL: run})
    assert all(r.measured_saved_text == "" for r in rows)


def test_a_measurement_does_not_move_the_recommendation():
    """A sample ranks the profiles; it does not re-decide the job. Letting a
    measured row take the badge would turn a ranking into a forecast without
    saying so."""
    before = {r.profile: r.recommended for r in _rows()}
    absurd = {p: MeasuredRun(profile=p, orig_bytes=10_000_000, final_bytes=1)
              for p in (Profile.INSANE, Profile.EXTREME)}
    after = {r.profile: r.recommended for r in _rows(measured=absurd)}
    assert before == after


def test_a_measurement_does_not_rewrite_the_estimate_columns():
    plain = {r.profile: (r.size_text, r.size_range, r.time_text)
             for r in _rows()}
    marked = {r.profile: (r.size_text, r.size_range, r.time_text)
              for r in _rows(measured={Profile.NORMAL: _run()})}
    assert plain == marked


# -- the caption -----------------------------------------------------------

def _sample(n_files, size, cap, category=Category.BINARY):
    infos = [FileInfo(path=Path(f"f{i}"), size=size, category=category,
                      entropy_bps=7.0) for i in range(n_files)]
    return pick_sample(infos, cap_bytes=cap)


def test_no_caption_before_anything_has_been_measured():
    assert measurement_caption(_sample(50, 1_000_000, 10_000_000), 0) == ""


def test_the_caption_says_how_much_of_the_input_was_measured():
    caption = measurement_caption(_sample(500, 1_000_000, 10_000_000), 4)
    assert "9.5 MB" in caption      # fmt_size is binary MiB, labelled MB
    assert "2.0%" in caption


def test_the_caption_names_a_category_the_sample_could_not_carry():
    infos = ([FileInfo(path=Path(f"big{i}.zip"), size=200_000_000,
                       category=Category.COMPRESSED_ARCHIVE, entropy_bps=8.0)
              for i in range(4)]
             + [FileInfo(path=Path("small.zip"), size=1_000_000,
                         category=Category.COMPRESSED_ARCHIVE, entropy_bps=8.0)]
             + [FileInfo(path=Path(f"e{i}.exe"), size=2_000_000,
                         category=Category.EXECUTABLE, entropy_bps=7.0)
                for i in range(300)])
    caption = measurement_caption(pick_sample(infos, cap_bytes=50_000_000), 4)
    assert "Archives" in caption
    assert "ranks the profiles" in caption


def test_measuring_the_whole_input_says_so_without_hedging():
    caption = measurement_caption(_sample(3, 100, 10_000_000), 4)
    assert "all 3 files" in caption
    assert "real numbers" in caption.lower()


# -- the widget ------------------------------------------------------------

def _row(**kw):
    base = dict(profile=Profile.NORMAL, title="Normal", chain="7-Zip",
                size_text="701.0 MB", size_range="", saved_text="3%",
                time_text="~1 min", time_range="")
    base.update(kw)
    return ComparisonRow(**base)


def test_the_card_prints_the_measured_saving_where_the_estimate_was(qtbot):
    from PySide6.QtWidgets import QLabel

    widget = ProfileRow(_row(measured_saved_text="61%", measured_note="measured"))
    qtbot.addWidget(widget)
    texts = [label.text() for label in widget.findChildren(QLabel)]
    assert "61%" in texts
    assert "measured" in texts
    assert "3%" not in texts, "the estimate and the measurement both claiming"


def test_a_measured_row_is_spoken_as_measured(qtbot):
    widget = ProfileRow(_row(measured_saved_text="61%", measured_note="measured"))
    qtbot.addWidget(widget)
    assert "measured at 61%" in widget.accessibleName()


def test_a_measured_row_declares_its_second_line(qtbot):
    """The 36px point-row budget applies to rows with one line. A measured
    row has two, and must say so or it trips the compactness gate."""
    widget = ProfileRow(_row(measured_saved_text="61%", measured_note="measured"))
    qtbot.addWidget(widget)
    assert widget.shows_range()


def test_the_measurement_caption_outranks_the_flagged_row_pointer(qtbot):
    table = CompareTable()
    qtbot.addWidget(table)
    rows = [_row(note="Fast is 4x quicker and lands within 1.0 points of this.")]
    table.set_rows(rows, "Measured on 13 files — 55.7 MB, 1.1% of this input.")
    assert table._caption.isVisibleTo(table)
    assert "Measured on 13 files" in table._caption.text()


def test_without_a_measurement_the_old_caption_behaviour_is_untouched(qtbot):
    table = CompareTable()
    qtbot.addWidget(table)
    table.set_rows([_row(note="Fast is 4x quicker.")])
    assert "Read the note on" in table._caption.text()
    table.set_rows([_row()])
    assert not table._caption.isVisibleTo(table)


# -- the run ---------------------------------------------------------------

class _FakeQueue(QObject):
    """Just enough QueueManager to drive ComparisonRun without compressing."""

    jobDone = Signal(str, object)
    jobFailed = Signal(str, str)
    # The signal the real queue uses to retire a CANCELLED job, and the only
    # one it emits on that path. Omitting it here is what let the defect ship.
    jobStateChanged = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.added: list = []
        self.cancelled: list[str] = []
        self.extras: list = []

    def add_compress(self, inputs, out_path, profile, summary=None,
                     sidecar=False, options=None, extras=None):
        class _Job:
            pass
        job = _Job()
        job.id = f"job{len(self.added)}"
        job.profile = profile
        job.out_path = Path(out_path)
        self.added.append(job)
        self.extras.append(dict(extras or {}))
        return job

    def cancel(self, job_id):
        """What the real queue does: retire it with a state change, and emit
        neither jobDone nor jobFailed."""
        self.cancelled.append(job_id)
        from gui.models import JobState
        self.jobStateChanged.emit(job_id, JobState.CANCELLED)


class _Result:
    def __init__(self, orig, final, archive=None):
        self.orig_bytes = orig
        self.final_bytes = final
        self.elapsed_s = 3.0
        self.archive = archive


def test_two_profiles_that_resolve_to_one_chain_are_measured_once(tmp_path):
    """Without Precomp, Extreme runs exactly Normal's stages. Measuring both
    would spend the time twice and print one number as if it were two."""
    assert resolved_chain(Profile.EXTREME, NO_PRECOMP) == \
        resolved_chain(Profile.NORMAL, NO_PRECOMP)
    run = ComparisonRun(_FakeQueue(), NO_PRECOMP, _infos(), tmp_path / "compare")
    assert run.job_count < 4


def test_every_profile_in_a_shared_chain_gets_the_shared_result(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, NO_PRECOMP, _infos(), tmp_path / "compare")
    run.start()
    for job in list(queue.added):
        queue.jobDone.emit(job.id, _Result(10_000_000, 3_000_000))
    assert set(run.results) == {Profile.FAST, Profile.NORMAL,
                                Profile.EXTREME, Profile.INSANE}
    assert run.results[Profile.EXTREME].saved_fraction == pytest.approx(0.7)


def test_all_four_are_separate_jobs_when_every_tool_is_present(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    run.start()
    assert run.job_count == 4
    assert len(queue.added) == 4


def test_a_run_that_produced_no_bytes_is_a_failure_not_a_hundred_percent(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    failures = []
    run.failed.connect(lambda p, m: failures.append(p))
    run.start()
    queue.jobDone.emit(queue.added[0].id, _Result(0, 0))
    assert run.results == {}
    assert failures


def test_a_failed_job_leaves_the_card_on_its_estimate(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    seen = []
    run.failed.connect(lambda p, m: seen.append((p, m)))
    run.start()
    queue.jobFailed.emit(queue.added[0].id, "7-Zip exited 2")
    assert run.results == {}
    assert seen and seen[0][1] == "7-Zip exited 2"


def test_somebody_elses_job_is_ignored(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    run.start()
    queue.jobDone.emit("a-job-the-user-started", _Result(10, 1))
    assert run.results == {}
    assert run.is_running()


def test_cancelling_keeps_what_finished_and_stops_the_rest(tmp_path):
    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    done = []
    run.finished.connect(lambda: done.append(True))
    run.start()
    queue.jobDone.emit(queue.added[0].id, _Result(10_000_000, 5_000_000))
    run.cancel()
    assert len(run.results) == 1
    assert len(queue.cancelled) == 3
    assert not run.is_running()
    assert done


def test_cancelling_one_row_in_activity_does_not_strand_the_run(tmp_path):
    """The defect the 2026-09-20 review found. Every measurement job has a
    visible x in Activity, and QueueManager retires a cancelled job through
    `_retire`, which emits only `jobStateChanged` — so a run listening to
    jobDone and jobFailed alone waited forever for a job the queue had
    already finished with, leaving the button on "Stop measuring" and the
    temp directory on disk."""
    from gui.models import JobState

    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    done = []
    run.finished.connect(lambda: done.append(True))
    run.start()
    victim = queue.added[0].id
    queue.jobStateChanged.emit(victim, JobState.CANCELLED)
    for job in queue.added[1:]:
        queue.jobDone.emit(job.id, _Result(10_000_000, 5_000_000))
    assert not run.is_running(), "the cancelled job was never released"
    assert done, "finished never fired, so the button stays on Stop measuring"
    assert len(run.results) == 3


def test_a_running_or_finished_state_is_not_mistaken_for_a_cancellation(tmp_path):
    from gui.models import JobState

    queue = _FakeQueue()
    run = ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare")
    run.start()
    for state in (JobState.RUNNING, JobState.PAUSED, JobState.DONE):
        queue.jobStateChanged.emit(queue.added[0].id, state)
    assert run.is_running()
    queue.jobDone.emit(queue.added[0].id, _Result(10_000_000, 4_000_000))
    assert run.results[Profile.FAST].saved_fraction == pytest.approx(0.6)


def test_measurement_jobs_are_marked_so_they_stay_out_of_the_history(tmp_path):
    """Their archives are deleted the moment the number is read, so a history
    row would point at a file that does not exist."""
    queue = _FakeQueue()
    ComparisonRun(queue, ALL_TOOLS, _infos(), tmp_path / "compare").start()
    assert queue.extras and all(e.get("measurement") for e in queue.extras)


def test_the_queue_really_keeps_marked_jobs_out_of_the_history(qtbot, tmp_path,
                                                               monkeypatch):
    from gui import history
    from gui.models import Job, JobKind, JobState
    from gui.queue_manager import QueueManager

    written: list = []
    monkeypatch.setattr(history, "append", lambda entry: written.append(entry))
    manager = QueueManager(tmp_path / "t", {})
    qtbot.addWidget(type("W", (), {})) if False else None
    real = Job(inputs=[tmp_path / "a"], out_path=tmp_path / "a.excmp",
               kind=JobKind.COMPRESS)
    fake = Job(inputs=[tmp_path / "b"], out_path=tmp_path / "b.excmp",
               kind=JobKind.COMPRESS, measurement=True)
    for job in (real, fake):
        job.state = JobState.DONE
        manager._jobs[job.id] = job
        manager._order.append(job.id)
    manager.clear_finished()
    assert len(written) == 1
    assert written[0].archive.endswith("a.excmp")
    manager.shutdown()


def test_the_run_reports_the_sample_it_chose(tmp_path):
    run = ComparisonRun(_FakeQueue(), ALL_TOOLS, _infos(), tmp_path / "compare")
    assert run.sample.source_bytes == 44_000_000
    assert run.sample.is_whole_input


# -- the real thing --------------------------------------------------------

def test_a_real_comparison_run_measures_real_archives(qtbot, tmp_path):
    """No fakes: a live QueueManager, real compressions, real verified
    archives, real numbers on the cards.

    Only Fast and Normal, because the point is the wiring rather than the
    codecs, and Extreme on a two-core laptop is not a unit test.
    """
    import time

    from excmp.analyzer import analyze_tree
    from excmp.tools import find_tools
    from gui.queue_manager import QueueManager

    tools = find_tools()
    if tools.get("7z") is None:
        pytest.skip("Normal needs 7-Zip and this machine has none")

    source = tmp_path / "input"
    source.mkdir()
    (source / "notes.txt").write_text("the quick brown fox. " * 20_000)
    (source / "more.txt").write_text("lorem ipsum dolor sit amet. " * 20_000)

    queue = QueueManager(tmp_path / "qtmp", tools)
    run = ComparisonRun(queue, tools, analyze_tree(source),
                        work_dir=tmp_path / "qtmp" / "compare",
                        profiles=(Profile.FAST, Profile.NORMAL))
    done = []
    run.finished.connect(lambda: done.append(True))
    try:
        run.start()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not done:
            qtbot.wait(100)
        assert done, "the comparison never finished"
    finally:
        queue.shutdown()

    assert set(run.results) == {Profile.FAST, Profile.NORMAL}
    for profile, measured in run.results.items():
        assert measured.orig_bytes > 0
        assert measured.final_bytes > 0
        assert 0.5 < measured.saved_fraction < 1.0, (
            f"{profile.value} saved {measured.saved_fraction:.0%} on plain text")
    # Two profiles, two different archives. Equal byte counts would mean both
    # cards were reading one run - which is exactly what the chain-dedupe does
    # on purpose elsewhere, and exactly what must NOT happen when the chains
    # genuinely differ.
    #
    # Measured here: 980,000 B of repetitive text goes to 960 B under Fast and
    # 1,057 B under Normal. Note the direction - zstd BEATS 7-Zip on this
    # input, because at a kilobyte the .7z container costs more than the codec
    # saves. That is a real result and the reason this asserts difference
    # rather than an ordering: "the stronger profile wins" is an assumption,
    # and measuring it is the entire point of I6.
    assert (run.results[Profile.NORMAL].final_bytes
            != run.results[Profile.FAST].final_bytes)
    # The archives were the means, not the product.
    assert not (tmp_path / "qtmp" / "compare").exists()


# -- the window ------------------------------------------------------------

@pytest.fixture
def window(qtbot):
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_there_is_nothing_to_measure_before_files_are_added(window):
    assert not window.measure_button.isEnabled()
    assert window.measure_button.text() == "Measure presets"


def test_measuring_becomes_available_once_an_input_is_analysed(window, qtbot,
                                                               tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("hello " * 5_000)
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([source])
    assert window.measure_button.isEnabled()


def test_clearing_the_input_forgets_the_measurement(window, qtbot, tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("hello " * 5_000)
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([source])
    window._measured = {Profile.NORMAL: _run()}
    window._measured_caption = "Measured on 1 file"
    rows = window._refresh_estimates()
    assert any(r.measured_saved_text for r in rows), "nothing was on the card"
    window.clear_pending()
    assert window._measured == {}
    assert window._measured_caption == ""


def test_a_new_input_does_not_inherit_the_last_ones_numbers(window, qtbot,
                                                            tmp_path):
    """The sharpest way to lie with this feature: leave a measured ratio on
    the card after the bytes it was measured on are gone."""
    first = tmp_path / "one"
    first.mkdir()
    (first / "a.txt").write_text("hello " * 5_000)
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([first])
    window._measured = {Profile.NORMAL: _run()}

    second = tmp_path / "two"
    second.mkdir()
    (second / "b.txt").write_text("world " * 5_000)
    window.clear_pending()
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([second])
    assert window._measured == {}
    rows = window._refresh_estimates()
    assert all(not r.measured_saved_text for r in rows)


def test_removing_one_file_forgets_a_measurement_taken_on_the_old_set(window,
                                                                      qtbot,
                                                                      tmp_path):
    """The sharpest version of the stale-number defect, because it does not go
    back through analysis: Remove mutates _infos in place, so nothing else on
    the input-changed path cleans up after it. Found by review, reproduced
    with a real window before the fix."""
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("hello " * 5_000)
    (source / "b.txt").write_text("world " * 5_000)
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([source / "a.txt", source / "b.txt"])
    window._measured = {Profile.NORMAL: _run()}
    window._measured_caption = "Measured on all 2 files"
    assert any(r.measured_saved_text for r in window._refresh_estimates())

    window.pending_list.setCurrentRow(0)
    window.remove_selected_pending()
    assert window._measured == {}
    assert window._measured_caption == ""
    assert all(not r.measured_saved_text for r in window._refresh_estimates())


def test_declining_the_over_cap_question_keeps_the_measurement_you_had(window,
                                                                      qtbot,
                                                                      tmp_path):
    """toggle_measurement used to clear the cards before asking, so answering
    "Not now" destroyed a completed measurement to run nothing."""
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("hello " * 20_000)
    with qtbot.waitSignal(window.analysisFinished, timeout=30_000):
        window.add_paths([source])
    window._measured = {Profile.NORMAL: _run()}
    window._measured_caption = "Measured on all 1 file"

    # Force the over-cap branch: a cap below the input's only file.
    import gui.mainwindow as mw
    original = mw.ComparisonRun

    def tiny(*args, **kwargs):
        kwargs["cap_bytes"] = 1
        return original(*args, **kwargs)

    mw.ComparisonRun = tiny
    try:
        window.toggle_measurement()
        assert window._comparison is not None
        assert window._comparison.sample.over_cap
        assert window._measured, "cleared the cards before asking"
        window._abandon_measurement()
        assert window._measured, "answering 'Not now' destroyed the numbers"
    finally:
        mw.ComparisonRun = original


def test_measure_anyway_is_never_a_dead_button(window, qtbot, tmp_path):
    """The banner does not dismiss itself, so a bail-out that skipped
    hide_banner left a visible button that did nothing when pressed."""
    window._comparison = None
    window.banner.show_message("pretend over-cap question", tone="warn")
    assert window.banner.isVisibleTo(window)
    window._begin_measurement()          # the bail-out path
    assert not window.banner.isVisibleTo(window)


def test_profiles_that_pack_ogg_at_different_efforts_are_measured_apart(tmp_path, monkeypatch):
    """B13: without Precomp, Extreme runs Normal's chain - but with Ogg audio
    in the sample Normal packs at -4 and Extreme at -5, so one measured number
    for both would describe neither (review, B13)."""
    from excmp import oggpack

    monkeypatch.setattr(oggpack, "available", lambda: True)
    infos = _infos() + [FileInfo(path=Path("theme.ogg"), size=3_000_000,
                                 category=Category.AUDIO, entropy_bps=7.97)]
    run = ComparisonRun(_FakeQueue(), NO_PRECOMP, infos, tmp_path / "compare")
    keys = {tuple(group) for _key, group in run._groups}
    assert (Profile.NORMAL,) in keys and (Profile.EXTREME,) in keys


def test_without_ogg_in_the_sample_the_grouping_is_unchanged(tmp_path, monkeypatch):
    from excmp import oggpack

    monkeypatch.setattr(oggpack, "available", lambda: True)
    run = ComparisonRun(_FakeQueue(), NO_PRECOMP, _infos(), tmp_path / "compare")
    assert run.job_count < 4
