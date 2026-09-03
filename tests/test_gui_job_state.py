"""The remaining GUI findings from the 2026-09-03 audit.

Four defects that share a shape: the window remembers or reports something
that is no longer true of the job in front of it.

- **The password fields were never cleared.** Type one, compress, drop a
  different folder, press Compress again — and that archive is encrypted too,
  with a password the user typed once and can no longer read back. The field
  shows dots, so there is nothing on screen to notice.
- **The output name always ended `.excmp`**, whatever the Format box said, so
  choosing `.zip` wrote a zip named `holiday.excmp`.
- **"Copy as command" stopped reproducing the job** the moment the job could
  carry a format, a password, a split size or recovery records.
- **A post-publish failure marked the whole job failed**, so a split that ran
  out of disk reported "failed" for an archive that is written, verified and
  sitting on disk — sending the user to re-run a job that already succeeded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")


@pytest.fixture
def panel(qtbot, tmp_path):
    from gui.widgets.preset_cards import AdvancedPanel

    p = AdvancedPanel(tmp_path)
    qtbot.addWidget(p)
    return p


# ---------------------------------------------------------------------------
# The password must not outlive the job it was typed for
# ---------------------------------------------------------------------------

def test_the_password_is_forgotten_after_it_is_read(panel):
    """Otherwise every later archive is silently encrypted with a password
    the user cannot see and may not remember typing."""
    panel.password.setText("hunter2")
    panel.password_confirm.setText("hunter2")
    assert panel.job_extras()["password"] == "hunter2"

    panel.forget_password()
    assert panel.password.text() == ""
    assert panel.password_confirm.text() == ""
    assert panel.job_extras()["password"] is None


def test_forgetting_clears_the_warning_too(panel):
    panel.password.setText("pw")
    panel.password_confirm.setText("pw")
    assert panel.protect_note.text()
    panel.forget_password()
    assert panel.protect_note.text() == ""


def test_forgetting_leaves_the_other_settings_alone(panel):
    """Recovery, split and format are ordinary preferences somebody may well
    want for the next job. Only the secret is per-job."""
    panel.split.setText("100m")
    panel.recovery.setCurrentIndex(2)
    panel.format_box.setCurrentIndex(1)
    panel.password.setText("pw")
    panel.password_confirm.setText("pw")

    panel.forget_password()
    assert panel.split.text() == "100m"
    assert panel.recovery.currentIndex() == 2
    assert panel.format_box.currentIndex() == 1


def test_starting_a_job_forgets_the_password(qtbot, tmp_path):
    """The wiring, not just the method: the window has to call it."""
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_bytes(b"content " * 100)

        win.advanced_panel.password.setText("hunter2")
        win.advanced_panel.password_confirm.setText("hunter2")
        win._pending = [src]
        win.advanced_panel.output_dir.setText(str(tmp_path / "out"))
        win.advanced_panel.temp_dir.setText(str(tmp_path / "t"))
        win.start_compression()

        assert win.advanced_panel.password.text() == "", (
            "the password survived into the next job")
    finally:
        win.queue.shutdown()


# ---------------------------------------------------------------------------
# The output name has to match the format
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fmt, suffix", [
    ("excmp", ".excmp"), ("7z", ".7z"), ("zip", ".zip"),
])
def test_the_output_extension_follows_the_format(qtbot, tmp_path, fmt, suffix):
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        for i in range(win.advanced_panel.format_box.count()):
            if win.advanced_panel.format_box.itemData(i) == fmt:
                win.advanced_panel.format_box.setCurrentIndex(i)
                break
        win.advanced_panel.output_dir.setText(str(tmp_path))
        out = win._output_path_for([tmp_path / "holiday"])
        assert out.suffix == suffix, f"{fmt} produced {out.name}"
    finally:
        win.queue.shutdown()


# ---------------------------------------------------------------------------
# Copy as command has to reproduce the job it is copied from
# ---------------------------------------------------------------------------

def _job(tmp_path: Path, **kw):
    from excmp.planner import Profile
    from gui.models import Job, JobKind

    return Job(inputs=[tmp_path / "src"], out_path=tmp_path / "out.excmp",
               profile=Profile.EXTREME, kind=JobKind.COMPRESS, **kw)


def test_the_command_carries_the_new_options(qtbot, tmp_path):
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        cmd = win._job_as_command(_job(tmp_path, split=100 * (1 << 20),
                                       recovery=5, archive_format="zip"))
        assert "--split" in cmd
        assert "--recovery 5" in cmd
        assert "--format zip" in cmd
    finally:
        win.queue.shutdown()


def test_the_command_never_contains_the_password_value(qtbot, tmp_path):
    """It may say a password is needed. It must never say which one - the
    whole reason the CLI refuses one on argv is that argv is visible in the
    process table and lands in shell history."""
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        cmd = win._job_as_command(_job(tmp_path, password="hunter2"))
        assert "hunter2" not in cmd
        assert "--password" in cmd, (
            "the copied line would silently produce an UNENCRYPTED archive")
    finally:
        win.queue.shutdown()


def test_an_ordinary_job_still_produces_a_short_command(qtbot, tmp_path):
    """The defaults must not clutter it - the point of the feature is that
    somebody can read the line."""
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        cmd = win._job_as_command(_job(tmp_path))
        for absent in ("--split", "--recovery", "--format", "--password"):
            assert absent not in cmd, f"{absent} appeared for a default job"
    finally:
        win.queue.shutdown()


def test_the_visible_extension_matches_the_one_that_gets_written(qtbot, tmp_path):
    """The action bar showed a fixed ".excmp" beside the name box. Choosing
    "plain .zip" then promised one extension on screen and wrote another to
    disk - and the label is the only place the extension is visible before the
    job runs."""
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        win.advanced_panel.output_dir.setText(str(tmp_path))
        for fmt, suffix in (("excmp", ".excmp"), ("7z", ".7z"), ("zip", ".zip")):
            for i in range(win.advanced_panel.format_box.count()):
                if win.advanced_panel.format_box.itemData(i) == fmt:
                    win.advanced_panel.format_box.setCurrentIndex(i)
                    break
            qtbot.wait(10)
            assert win._suffix_label.text() == suffix, f"label wrong for {fmt}"
            assert win._output_path_for([tmp_path / "holiday"]).suffix == suffix
    finally:
        win.queue.shutdown()
