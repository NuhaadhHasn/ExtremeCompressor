"""UI v3 wave 2a: the Activity tab, the status strip, and the last modal.

Three structural claims are pinned here.

1. **Running jobs have their own home.** The queue and the results panel used
   to sit at the bottom of the same scrolling column as the drop zone, the
   analysis card and the chooser - four lifecycle stages competing for one
   ~390px viewport. They move to an Activity tab, and a one-line status strip
   carries the queue's state onto every other tab so nothing is hidden.
2. **Density is not decoration.** The queue's Profile and Size columns fold
   under the job name; an empty queue explains itself instead of showing a
   blank grid.
3. **No modal survives.** The close-mid-job question was the last
   ``QMessageBox`` in the package; it becomes an inline banner.
"""

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from excmp.planner import Profile                  # noqa: E402
from gui.mainwindow import MainWindow              # noqa: E402
from gui.models import Job, JobKind, JobState      # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def _queued_job(window, name="MyGame") -> Job:
    """A job parked in the queue without starting the engine."""
    window.queue.pause()
    job = Job(kind=JobKind.COMPRESS, inputs=[Path("C:/in") / name],
              out_path=Path("C:/out") / f"{name}.excmp", profile=Profile.NORMAL)
    window.queue.add_job(job)
    return job


def _is_descendant(widget, ancestor) -> bool:
    parent = widget.parent()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.parent()
    return False


def _summary(total=1000, stored=(), by_category=None):
    """A minimal AnalysisSummary - it is frozen with nine required fields."""
    from gui.suggest import AnalysisSummary

    store_bytes = sum(size for _n, size, _w in stored)
    return AnalysisSummary(
        total_bytes=total, file_count=max(1, len(stored)),
        by_category=dict(by_category or {}), store_by_category={},
        store_bytes=store_bytes, pipeline_bytes=max(0, total - store_bytes),
        store_files=list(stored), warnings=[], chain=["sevenzip"])


# ---------------------------------------------------------------------------
# W2-1: the Activity tab
# ---------------------------------------------------------------------------

def test_the_queue_and_results_left_the_compress_page(window):
    """The Compress tab is the *decision* surface: what you dropped, what it
    is, which profile. Everything about work in flight belongs elsewhere."""
    compress_page = window._scroll.widget()
    assert not _is_descendant(window.queue_table, compress_page)
    assert not _is_descendant(window.results, compress_page)
    assert _is_descendant(window.queue_table, window.activity_page)
    assert _is_descendant(window.results, window.activity_page)


def test_the_tabs_are_compress_extract_activity(window):
    labels = [window.tabs.tabText(i).split(" (")[0] for i in range(window.tabs.count())]
    assert labels == ["Compress", "Extract", "Activity"]
    assert window.tabs.widget(window._activity_index) is window.activity_page


def test_queueing_a_job_never_yanks_the_user_off_compress(window, qtbot):
    """Pinned behaviour: people queue several jobs in a row. Stealing the tab
    after each one would make the second job a fight with the app."""
    window.show()
    qtbot.waitExposed(window)
    assert window.tabs.currentWidget() is window._scroll
    _queued_job(window)
    assert window.tabs.currentWidget() is window._scroll


def test_the_activity_tab_title_counts_unfinished_jobs(window):
    assert window.tabs.tabText(window._activity_index) == "Activity"
    job = _queued_job(window)
    assert window.tabs.tabText(window._activity_index) == "Activity (1)"
    _queued_job(window, "Second")
    assert window.tabs.tabText(window._activity_index) == "Activity (2)"

    job.state = JobState.DONE
    window._on_job_state(job.id, JobState.DONE)
    assert window.tabs.tabText(window._activity_index) == "Activity (1)"


def test_the_status_strip_reports_the_queue_from_any_tab(window, qtbot):
    window.show()
    qtbot.waitExposed(window)
    assert window.job_status.text() == "idle"

    job = _queued_job(window)
    window.tabs.setCurrentWidget(window.extract_tab)
    assert window.job_status.isVisible(), "the strip vanished with the Compress tab"
    assert window.job_status.text() == "1 job waiting"

    job.state = JobState.RUNNING
    job.eta_s = 62.0
    job.percent = 40.0
    window._on_job_progress(job.id, "sevenzip", 40.0, 62.0)
    assert "MyGame" in window.job_status.text()
    assert window.status_progress.isVisible()
    assert window.status_progress.value() == 40


def test_a_finished_job_is_visible_without_switching_tabs(window, qtbot):
    """W1-4's promise, kept now that the results panel is on another tab: a
    job that finishes must change something the user can see from here."""
    window.show()
    qtbot.waitExposed(window)
    window.tabs.setCurrentWidget(window.extract_tab)

    job = _queued_job(window)
    job.state = JobState.DONE
    job.orig_bytes, job.final_bytes = 1000, 400
    window._on_job_state(job.id, JobState.DONE)

    text = window.job_status.text()
    assert "MyGame" in text and "60%" in text, text
    assert window.tabs.currentWidget() is window.extract_tab, "it switched tabs"


def test_clicking_the_status_strip_opens_activity(window, qtbot):
    window.show()
    qtbot.waitExposed(window)
    window.job_status.click()
    assert window.tabs.currentWidget() is window.activity_page


def test_the_tools_line_elides_before_the_job_status_does(window, qtbot):
    """Strip priority at 910 logical px: what the queue is doing wins. The
    tools inventory is reference material and is fully readable in About.

    The tools text is pinned rather than read from the machine - what is
    under test is the priority, not which archivers happen to be installed.
    """
    window.resize(910, 512)
    window.show()
    qtbot.waitExposed(window)
    window._tools_text = ("Tools found: " +
                          ", ".join(f"archiver{i} 24.0{i}" for i in range(8)))
    job = _queued_job(window, "Some Very Long Game Folder 2026 Deluxe Edition")
    job.state = JobState.RUNNING
    job.eta_s = 3720.0
    window._on_job_progress(job.id, "sevenzip", 5.0, 3720.0)

    assert window._tools_label.text() != window._tools_text, "the tools line never elided"
    assert window._tools_label.text().endswith("…")
    assert window._tools_label.toolTip().startswith("Tools found:")
    assert window.job_status.text() == window._job_status_text(), "the job line was cut"


# ---------------------------------------------------------------------------
# W2-7: queue table density
# ---------------------------------------------------------------------------

def test_the_queue_row_carries_profile_and_size_under_the_job_name(window):
    """Two columns of two short words each cost more width than the whole
    progress bar. They fold into a second line under the name."""
    from gui.widgets import queue_table as qt

    assert window.queue_table.columnCount() == 5
    job = _queued_job(window)
    job.orig_bytes = 1_900_000_000
    window.queue_table.update_state(job)

    text = window.queue_table.topLevelItem(0).text(qt.COL_NAME)
    first, _, second = text.partition("\n")
    assert first == "MyGame"
    assert "normal" in second and "GB" in second, second
    assert window.queue_table.columnWidth(qt.COL_PROGRESS) == 110


def test_an_empty_queue_explains_itself(window, qtbot):
    """A blank grid is the worst possible answer to "did my job register?"."""
    window.show()
    qtbot.waitExposed(window)
    assert window.queue_table.empty_hint
    assert window.queue_table._should_paint_hint() is True
    _queued_job(window)
    assert window.queue_table._should_paint_hint() is False
    # The painter path must survive a real render, hint or not.
    window.queue_table.grab()


def test_the_queue_fills_the_activity_tab_instead_of_capping_itself(window, qtbot):
    """The 430px cap existed to stop the queue pushing the results panel off
    the Compress page. It owns a tab now, so it fills it."""
    window.resize(1180, 721)
    window.show()
    qtbot.waitExposed(window)
    window.tabs.setCurrentWidget(window.activity_page)
    qtbot.wait(50)
    assert window.queue_table.maximumHeight() > 1000, "still capped"
    assert window.queue_table.height() > 300, window.queue_table.height()


# ---------------------------------------------------------------------------
# W2-3: the results panel stays compact
# ---------------------------------------------------------------------------

def test_the_results_panel_fits_a_150_percent_viewport(window, qtbot, tmp_path):
    from excmp.analyzer import Category

    job = Job(kind=JobKind.COMPRESS, inputs=[tmp_path / "d"],
              out_path=tmp_path / "d.excmp", profile=Profile.EXTREME,
              state=JobState.DONE, orig_bytes=2_000_000_000,
              final_bytes=700_000_000, elapsed_s=166.0)
    job.summary = _summary(
        total=2_000_000_000,
        stored=[(f"clip{i}.mp4", 10_000, "already compressed") for i in range(9)],
        by_category={Category.VIDEO: 1_400_000_000, Category.BINARY: 600_000_000})
    window.results.show_job(job)
    window.results.adjustSize()
    assert window.results.sizeHint().height() <= 300, window.results.sizeHint().height()


def test_the_explanations_cap_at_three_with_an_expander(window, tmp_path):
    job = Job(kind=JobKind.COMPRESS, inputs=[tmp_path / "d"],
              out_path=tmp_path / "d.excmp", state=JobState.DONE,
              orig_bytes=1000, final_bytes=500)
    job.summary = _summary(
        stored=[(f"clip{i}.mp4", 100, "already compressed") for i in range(9)])
    window.results.show_job(job)

    assert window.results.explanation_count() == 3
    assert window.results.more_button.isVisibleTo(window.results)
    assert "9" in window.results.more_button.text()
    window.results.more_button.click()
    assert window.results.explanation_count() == 9


def test_where_the_bytes_went_starts_collapsed(window, tmp_path):
    from excmp.analyzer import Category

    job = Job(kind=JobKind.COMPRESS, inputs=[tmp_path / "d"],
              out_path=tmp_path / "d.excmp", state=JobState.DONE,
              orig_bytes=1000, final_bytes=500)
    job.summary = _summary(by_category={Category.TEXT: 1000})
    window.results.show_job(job)
    assert not window.results._breakdown.isVisibleTo(window.results)
    window.results.breakdown_toggle.click()
    assert window.results._breakdown.isVisibleTo(window.results)


# ---------------------------------------------------------------------------
# W2-8: the analysis scan is not a hang
# ---------------------------------------------------------------------------

def test_the_analysis_card_ticks_through_the_files(window):
    """On the real HDD corpus a scan takes minutes. An unmoving card reads as
    a crash - so the card counts the files it has actually read."""
    card = window.analysis_card
    card.set_busy(3)
    assert card.progress.isVisibleTo(card)
    assert card.progress.maximum() == 0, "the counting pass must be indeterminate"

    card.set_progress(34, 81)
    assert "34" in card.status_text() and "81" in card.status_text()
    assert (card.progress.value(), card.progress.maximum()) == (34, 81)


def test_the_worker_reports_progress_while_it_scans(qtbot, tmp_path):
    from excmp.tools import find_tools
    from gui.queue_manager import AnalysisSignals, AnalysisWorker

    root = tmp_path / "tree"
    root.mkdir()
    for i in range(7):
        (root / f"f{i}.txt").write_text("data " * 200)

    signals = AnalysisSignals()
    seen: list[tuple[int, int]] = []
    signals.progress.connect(lambda done, total: seen.append((done, total)))
    with qtbot.waitSignal(signals.ready, timeout=30_000):
        AnalysisWorker([root], Profile.NORMAL, find_tools(), signals).run()

    assert seen, "the scan reported nothing"
    assert seen[-1] == (7, 7)
    assert all(total == 7 for _done, total in seen)


# ---------------------------------------------------------------------------
# W2-9: the last modal
# ---------------------------------------------------------------------------

def test_no_qmessagebox_survives_in_the_gui_package():
    """The no-modal rule is the product's, not a style preference: a modal
    over a running job hides the queue that proves the job is still alive.

    Tokenised rather than grepped - the comments that explain *why* the
    modals went are allowed to name the class they replaced.
    """
    import tokenize

    import gui

    def uses_it(path: Path) -> bool:
        with path.open("rb") as handle:
            return any(token.type == tokenize.NAME and token.string == "QMessageBox"
                       for token in tokenize.tokenize(handle.readline))

    offenders = [p.name for p in Path(gui.__file__).parent.rglob("*.py")
                 if uses_it(p)]
    assert offenders == [], f"QMessageBox still used in {offenders}"


def test_closing_mid_job_asks_inline_and_the_answer_sticks(window, qtbot):
    window.show()
    qtbot.waitExposed(window)
    window.queue._active_id = "pretend-this-is-running"
    assert window.queue.is_busy

    window.close()
    assert window.isVisible(), "the window closed without asking"
    assert window.banner.isVisibleTo(window)
    assert "cancel" in window.banner.text().lower()

    labels = window.banner.action_labels()
    assert len(labels) == 2 and any("Close" in t for t in labels)

    window.banner.trigger("Keep it running")
    assert not window.banner.isVisibleTo(window)
    assert window.isVisible()

    window.close()
    window.banner.trigger("Close anyway")
    assert not window.isVisible()


def test_the_banner_is_reusable_and_carries_meaning_in_words(window, qtbot):
    """It serves I4's first-run notice and error surfaces later, so tone is
    the second signal - the sentence always says it too."""
    window.show()
    qtbot.waitExposed(window)
    window.banner.show_message("Precomp is not installed.", tone="warn")
    assert window.banner.isVisibleTo(window)
    assert window.banner.property("tone") == "warn"
    assert window.banner.text() == "Precomp is not installed."
    assert window.banner.accessibleName().endswith("Precomp is not installed.")

    window.banner.hide_banner()
    assert not window.banner.isVisibleTo(window)
