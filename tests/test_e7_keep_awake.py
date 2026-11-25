"""E7: keep Windows awake while a job runs, and optionally sleep / hibernate / shut down when the queue ends.

A laptop that goes to sleep in the middle of a three-hour Insane job costs the user the hours (the same thing
cost the benchmark rows of B27/B28 theirs). Every system call here is replaced by a fake in the tests: no test
can put this machine to sleep or shut it down.

Rules: the display may still turn off (only the system is kept awake); an after-queue action happens only if
nothing failed, only after a 60 s countdown the user can cancel in the banner, and never while a job is running.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from gui import winintegration as wi                                     # noqa: E402
from gui.widgets.settings_tab import SettingsTab                         # noqa: E402

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


# -- the Windows calls ----------------------------------------------------------------------------

def test_keep_awake_asks_for_the_system_but_not_the_display(monkeypatch):
    calls = []
    monkeypatch.setattr(wi, "_set_execution_state", lambda flags: calls.append(flags) or 1)
    assert wi.keep_awake(True) is True
    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]
    assert not calls[0] & ES_DISPLAY_REQUIRED                  # the screen may still turn off


def test_keep_awake_off_clears_the_request(monkeypatch):
    calls = []
    monkeypatch.setattr(wi, "_set_execution_state", lambda flags: calls.append(flags) or 1)
    assert wi.keep_awake(False) is True
    assert calls == [ES_CONTINUOUS]


def test_a_failing_call_is_a_quiet_false_never_an_exception(monkeypatch):
    def boom(flags):
        raise OSError("no such API")
    monkeypatch.setattr(wi, "_set_execution_state", boom)
    assert wi.keep_awake(True) is False


@pytest.mark.parametrize("action,expected", [
    ("sleep", ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]),
    ("hibernate", ["shutdown.exe", "/h"]),
    ("shutdown", ["shutdown.exe", "/s", "/t", "0"]),
])
def test_each_action_is_one_fixed_command(action, expected):
    assert wi.power_command(action) == expected


@pytest.mark.parametrize("action", ["nothing", "", "reboot", None, "sleep; calc", 7])
def test_anything_else_is_no_command(action):
    assert wi.power_command(action) is None


def test_run_power_action_runs_exactly_the_fixed_command(monkeypatch):
    ran = []
    monkeypatch.setattr(wi.subprocess, "Popen", lambda cmd, **kw: ran.append(cmd))
    assert wi.run_power_action("hibernate") is True
    assert ran == [["shutdown.exe", "/h"]]
    assert wi.run_power_action("nothing") is False and len(ran) == 1


# -- the settings ---------------------------------------------------------------------------------

def _tab(qtbot):
    from pathlib import Path
    tab = SettingsTab({}, Path("."), shell_supported=False)
    qtbot.addWidget(tab)
    return tab


def test_keep_awake_is_on_by_default_and_the_after_action_is_nothing(qtbot):
    tab = _tab(qtbot)
    tab.load()
    assert tab.awake_toggle.isChecked()
    assert tab.after_combo.currentData() == "nothing"
    assert [tab.after_combo.itemData(i) for i in range(tab.after_combo.count())] == \
        ["nothing", "sleep", "hibernate", "shutdown"]


def test_both_choices_are_remembered(qtbot):
    tab = _tab(qtbot)
    tab.load()
    tab.awake_toggle.setChecked(False)
    tab.after_combo.setCurrentIndex(tab.after_combo.findData("hibernate"))
    tab.save()
    tab2 = _tab(qtbot)
    tab2.load()
    assert not tab2.awake_toggle.isChecked() and tab2.after_combo.currentData() == "hibernate"


def test_a_corrupt_stored_value_falls_back_to_nothing(qtbot):
    from PySide6.QtCore import QSettings
    QSettings().setValue("settings/after_queue", "format c:")
    tab = _tab(qtbot)
    tab.load()
    assert tab.after_combo.currentData() == "nothing"


def test_the_controls_have_accessible_names(qtbot):
    tab = _tab(qtbot)
    assert tab.awake_toggle.accessibleName() and tab.after_combo.accessibleName()


# -- the window -----------------------------------------------------------------------------------

@pytest.fixture()
def win(qtbot, monkeypatch):
    from gui import mainwindow as mw
    awake, ran = [], []
    monkeypatch.setattr(mw, "keep_awake", lambda on: awake.append(on) or True)
    monkeypatch.setattr(mw, "run_power_action", lambda a: ran.append(a) or True)
    monkeypatch.setattr(mw.MainWindow, "AFTER_QUEUE_DELAY_MS", 200)
    w = mw.MainWindow()
    qtbot.addWidget(w)
    w.settings_tab.load()
    return w, awake, ran


def _start(w):
    w.queue.jobStarted.emit("j1")


def _idle(w):
    w.queue.queueIdle.emit()


def test_a_running_job_keeps_the_pc_awake_and_idle_releases_it(qtbot, win):
    w, awake, _ran = win
    _start(w)
    assert awake == [True]
    _idle(w)
    assert awake == [True, False]


def test_turning_the_switch_off_never_requests_it(qtbot, win):
    w, awake, _ran = win
    w.settings_tab.awake_toggle.setChecked(False)
    _start(w)
    assert awake == []


def test_the_request_is_released_even_if_the_switch_is_turned_off_mid_job(qtbot, win):
    w, awake, _ran = win
    _start(w)
    w.settings_tab.awake_toggle.setChecked(False)
    _idle(w)
    assert awake[-1] is False


def test_nothing_happens_after_the_queue_by_default(qtbot, win):
    w, _awake, ran = win
    _start(w)
    _idle(w)
    qtbot.wait(400)
    assert ran == []


def test_the_chosen_action_runs_after_the_countdown(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("sleep"))
    _start(w)
    _idle(w)
    assert ran == [] and "sleep" in w.banner._text.text().lower()          # the countdown is announced
    qtbot.waitUntil(lambda: ran == ["sleep"], timeout=3000)


def test_cancel_in_the_banner_stops_it(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("shutdown"))
    _start(w)
    _idle(w)
    labels = [b.text() for b in w.banner._buttons]
    assert labels[0] == "Cancel"
    w.banner._buttons[0].click()
    qtbot.wait(500)
    assert ran == []


def test_a_failed_job_cancels_the_action(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("shutdown"))
    _start(w)
    w.queue.jobFailed.emit("j1", "disk full")
    _idle(w)
    qtbot.wait(500)
    assert ran == []
    assert "not" in w.banner._text.text().lower() or "fail" in w.banner._text.text().lower()


def test_a_new_job_during_the_countdown_cancels_it(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("sleep"))
    _start(w)
    _idle(w)
    _start(w)                                   # the user queued something else
    qtbot.wait(500)
    assert ran == []


def test_the_failure_flag_resets_for_the_next_run(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("sleep"))
    _start(w)
    w.queue.jobFailed.emit("j1", "x")
    _idle(w)
    _start(w)                                   # a later, clean run
    _idle(w)
    qtbot.waitUntil(lambda: ran == ["sleep"], timeout=3000)


def test_closing_the_window_cancels_a_pending_action(qtbot, win):
    w, _awake, ran = win
    w.settings_tab.after_combo.setCurrentIndex(w.settings_tab.after_combo.findData("sleep"))
    _start(w)
    _idle(w)
    w.close()
    qtbot.wait(500)
    assert ran == []
