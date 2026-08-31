"""The Verify button (UI v3 wave 3).

Verification is the brand — "verifies a byte-identical restore before claiming
success" is the first sentence of the README — and until now the GUI could not
do it on demand. You could only get it as a side effect of compressing, on an
archive you had just made, which is the moment you need it least.

These tests pin the surface, not the algorithm: the engine half is covered in
test_verify_archive.py. What matters here is that a verify is a *job* like any
other — queued, cancellable, logged, reported — rather than a modal that locks
the window while it restores 700 MB.
"""

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from gui.mainwindow import MainWindow          # noqa: E402
from gui.models import Job, JobKind, JobState  # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def archive(tmp_path):
    """A real .excmp.

    Not a placeholder file: since G1 the Verify button correctly refuses
    anything without a manifest, because there would be no ledger to check
    against. A stub would now be testing the refusal, not the button.
    """
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 400, encoding="utf-8")
    out = tmp_path / "thing.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


def test_the_extract_tab_offers_to_verify(window):
    tab = window.extract_tab
    assert hasattr(tab, "verify_button")
    # Disabled until an archive is chosen - nothing to verify otherwise.
    assert not tab.verify_button.isEnabled()


def test_choosing_an_archive_enables_verify(window, archive):
    window.extract_tab.set_archive(archive)
    assert window.extract_tab.verify_button.isEnabled()


def test_verifying_queues_a_job_rather_than_blocking(window, qtbot, archive):
    """A 700 MB verify is a full restore. It belongs in the queue with a
    progress bar and a cancel button, exactly like the compress that made it."""
    window.queue.pause()
    window.extract_tab.set_archive(archive)
    window.extract_tab.verify_button.click()

    jobs = window.queue.jobs
    assert len(jobs) == 1
    assert jobs[0].kind is JobKind.VERIFY
    assert jobs[0].inputs == [archive]
    assert window.tabs.tabText(window._activity_index) == "Activity (1)"


def test_a_verify_row_says_what_it_is(window, tmp_path):
    from gui.widgets import queue_table as qt

    job = Job(kind=JobKind.VERIFY, inputs=[tmp_path / "thing.excmp"],
              out_path=tmp_path / "thing.excmp")
    window.queue_table.add_job(job)
    window.queue_table.update_state(job)
    text = window.queue_table.topLevelItem(0).text(qt.COL_NAME)
    assert "verify" in text.lower(), text


def test_a_passing_verify_says_so_in_the_results(window, tmp_path):
    from excmp.engine import VerifyResult

    job = Job(kind=JobKind.VERIFY, inputs=[tmp_path / "thing.excmp"],
              out_path=tmp_path / "thing.excmp", state=JobState.DONE,
              elapsed_s=12.5)
    job.result = VerifyResult(archive=tmp_path / "thing.excmp", ok=True,
                              files_restored=81, verified=81, elapsed_s=12.5,
                              problem="")
    window.results.show_job(job)
    hero = window.results.hero.text()
    assert "81" in hero
    assert window.results.hero.property("tone") == "ok"
    # The claim has to say what was actually checked, not just "OK".
    assert "sha-256" in window.results.subline.text().lower()


def test_a_failing_verify_is_never_dressed_up_as_a_warning(window, tmp_path):
    """A corrupt archive is the single worst news this app can deliver. It
    renders in $danger and says the word."""
    job = Job(kind=JobKind.VERIFY, inputs=[tmp_path / "thing.excmp"],
              out_path=tmp_path / "thing.excmp", state=JobState.FAILED,
              error="restore verification FAILED:\n  hash mismatch: data/a.bin")
    window.results.show_job(job)
    assert window.results.hero.property("tone") == "danger"
    assert "hash mismatch" in window.results.subline.text()


def test_verify_never_writes_into_the_destination_folder(window, qtbot, tmp_path,
                                                         archive):
    """The Extract tab has a destination field. Verify must ignore it - the
    whole point is that nothing is produced."""
    dest = tmp_path / "dest"
    dest.mkdir()
    window.queue.pause()
    window.extract_tab.set_archive(archive)
    window.extract_tab.dest_edit.setText(str(dest))
    window.extract_tab.verify_button.click()

    job = window.queue.jobs[0]
    assert job.out_path != dest, "a verify job aimed at the user's folder"
    assert list(dest.iterdir()) == []
