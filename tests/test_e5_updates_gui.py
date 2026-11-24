"""E5 in the window: the Settings row, the banner, and starting the installer.

Everything runs with FAKE check/download functions and a fake launcher: no test reaches the network or
starts a real installer. The rules of this UI hold: no modal dialog, the state is said inline.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog                    # noqa: E402

from excmp import updater                                              # noqa: E402
from excmp.updater import UpdateError, UpdateInfo                      # noqa: E402
from gui.updatecontroller import AUTO_KEY, LAST_CHECK_KEY, UpdateController   # noqa: E402
from gui.widgets.settings_tab import SettingsTab                       # noqa: E402


def _info(version="0.2.0"):
    return UpdateInfo(version=version, tag="v" + version, installer_name=f"ExtremeCompressor-{version}-setup.exe",
                      installer_url="https://github.com/x", installer_size=3, sums_url="https://github.com/s",
                      sig_url="https://github.com/g")


def _controller(qtbot, check=None, download=None, current="0.1.0", tmp_path=None):
    c = UpdateController(check=check or (lambda cur: None), download=download or (lambda info, dest, progress=None: tmp_path / "setup.exe"),
                         current=current, dest=tmp_path)
    return c


def _wait(qtbot, ctrl, *states):
    qtbot.waitUntil(lambda: ctrl.state in states, timeout=5000)


def _tab(qtbot, ctrl):
    tab = SettingsTab({}, Path("."), shell_supported=False, updates=ctrl)
    qtbot.addWidget(tab)
    return tab


# -- the controller ---------------------------------------------------------------------------------

def test_a_check_that_finds_nothing_says_so(qtbot, tmp_path):
    c = _controller(qtbot, tmp_path=tmp_path)
    c.check()
    _wait(qtbot, c, "uptodate")
    assert "latest" in c.message and "0.1.0" in c.message


def test_a_check_that_finds_an_update_announces_it(qtbot, tmp_path):
    c = _controller(qtbot, check=lambda cur: _info(), tmp_path=tmp_path)
    with qtbot.waitSignal(c.available, timeout=5000) as sig:
        c.check()
    assert sig.args[0].version == "0.2.0" and c.state == "available" and "0.2.0" in c.message


def test_a_failed_check_is_an_error_message_not_an_exception(qtbot, tmp_path):
    def boom(cur):
        raise UpdateError("could not reach the update server: offline")
    c = _controller(qtbot, check=boom, tmp_path=tmp_path)
    c.check()
    _wait(qtbot, c, "error")
    assert "offline" in c.message


def test_an_unexpected_exception_in_the_thread_is_caught_too(qtbot, tmp_path):
    def boom(cur):
        raise RuntimeError("bug")
    c = _controller(qtbot, check=boom, tmp_path=tmp_path)
    c.check()
    _wait(qtbot, c, "error")
    assert "unexpected" in c.message


def test_a_silent_check_leaves_no_text_for_uptodate_or_error(qtbot, tmp_path):
    c = _controller(qtbot, tmp_path=tmp_path)
    c.check(silent=True)
    _wait(qtbot, c, "uptodate")
    assert c.message == ""

    def boom(cur):
        raise UpdateError("offline")
    c2 = _controller(qtbot, check=boom, tmp_path=tmp_path)
    c2.check(silent=True)
    _wait(qtbot, c2, "error")
    assert c2.message == ""


def test_install_downloads_then_announces_the_verified_file(qtbot, tmp_path):
    c = _controller(qtbot, check=lambda cur: _info(), tmp_path=tmp_path)
    c.check()
    _wait(qtbot, c, "available")
    with qtbot.waitSignal(c.readyToLaunch, timeout=5000) as sig:
        assert c.install()
    assert sig.args[0] == tmp_path / "setup.exe" and c.state == "ready"


def test_install_before_a_check_does_nothing(qtbot, tmp_path):
    c = _controller(qtbot, tmp_path=tmp_path)
    assert c.install() is False and c.state == "idle"


def test_a_failed_download_is_reported_and_can_be_retried(qtbot, tmp_path):
    calls = []

    def dl(info, dest, progress=None):
        calls.append(1)
        raise UpdateError("the downloaded installer's SHA-256 does not match the signed checksum")
    c = _controller(qtbot, check=lambda cur: _info(), download=dl, tmp_path=tmp_path)
    c.check()
    _wait(qtbot, c, "available")
    c.install()
    _wait(qtbot, c, "error")
    assert "SHA-256" in c.message and calls == [1]


def test_two_checks_do_not_overlap(qtbot, tmp_path):
    gate = []

    def slow(cur):
        while not gate:
            time.sleep(0.01)
        return None
    c = _controller(qtbot, check=slow, tmp_path=tmp_path)
    assert c.check() is True
    assert c.check() is False
    gate.append(1)
    _wait(qtbot, c, "uptodate")


def test_a_check_records_when_it_ran(qtbot, tmp_path):
    c = _controller(qtbot, tmp_path=tmp_path)
    assert c.due()
    c.check()
    _wait(qtbot, c, "uptodate")
    assert not c.due()
    assert float(QSettings().value(LAST_CHECK_KEY)) > 0


# -- the Settings row -------------------------------------------------------------------------------

def test_the_row_exists_with_the_daily_look_on_by_default(qtbot, tmp_path):
    tab = _tab(qtbot, _controller(qtbot, tmp_path=tmp_path))
    tab.load()
    assert tab.update_toggle.isChecked()
    assert tab.update_button.text() == "Check for updates"
    assert "0.1.0" in tab.update_state.text()


def test_turning_the_daily_look_off_is_remembered(qtbot, tmp_path):
    tab = _tab(qtbot, _controller(qtbot, tmp_path=tmp_path))
    tab.load()
    tab.update_toggle.setChecked(False)
    tab.save()
    assert str(QSettings().value(AUTO_KEY)).lower() == "false"
    tab2 = _tab(qtbot, _controller(qtbot, tmp_path=tmp_path))
    tab2.load()
    assert not tab2.update_toggle.isChecked()


def test_the_button_checks_then_offers_the_download(qtbot, tmp_path):
    ctrl = _controller(qtbot, check=lambda cur: _info(), tmp_path=tmp_path)
    tab = _tab(qtbot, ctrl)
    tab.update_button.click()
    _wait(qtbot, ctrl, "available")
    assert tab.update_button.text() == "Download and install 0.2.0"
    assert "0.2.0" in tab.update_state.text()
    with qtbot.waitSignal(ctrl.readyToLaunch, timeout=5000):
        tab.update_button.click()
    assert tab.update_button.text() == "Install now"


def test_the_button_is_disabled_while_checking(qtbot, tmp_path):
    gate = []

    def slow(cur):
        while not gate:
            time.sleep(0.01)
        return None
    ctrl = _controller(qtbot, check=slow, tmp_path=tmp_path)
    tab = _tab(qtbot, ctrl)
    tab.update_button.click()
    assert not tab.update_button.isEnabled() and "Checking" in tab.update_state.text()
    gate.append(1)
    _wait(qtbot, ctrl, "uptodate")
    assert tab.update_button.isEnabled()


def test_an_error_is_said_inline_without_a_dialog(qtbot, tmp_path):
    def boom(cur):
        raise UpdateError("could not reach the update server: offline")
    ctrl = _controller(qtbot, check=boom, tmp_path=tmp_path)
    tab = _tab(qtbot, ctrl)
    tab.update_button.click()
    _wait(qtbot, ctrl, "error")
    assert "offline" in tab.update_state.text()
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]


# -- the window -------------------------------------------------------------------------------------

@pytest.fixture()
def win(qtbot, tmp_path, monkeypatch):
    from gui.mainwindow import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    ctrl = _controller(qtbot, check=lambda cur: _info(), tmp_path=tmp_path)
    w.settings_tab.updates.stateChanged.disconnect()
    w.settings_tab.updates.available.disconnect()
    w.settings_tab.updates.readyToLaunch.disconnect()
    w.settings_tab.updates = ctrl
    ctrl.available.connect(w._update_available)
    ctrl.readyToLaunch.connect(w._launch_update)
    return w, ctrl


def test_a_found_update_raises_the_banner_with_a_download_action(qtbot, win):
    w, ctrl = win
    with qtbot.waitSignal(ctrl.available, timeout=5000):
        ctrl.check(silent=True)
    assert "0.2.0" in w.banner._text.text()
    assert [b.text() for b in w.banner._buttons] == ["Download and install", "Later"]
    assert w.banner.isVisibleTo(w)
    with qtbot.waitSignal(ctrl.readyToLaunch, timeout=5000):
        w.banner._buttons[0].click()            # the banner's own button starts the download


def test_a_verified_download_starts_the_installer_and_closes(qtbot, win, monkeypatch, tmp_path):
    w, ctrl = win
    launched = []
    monkeypatch.setattr(updater, "launch_installer", lambda p: launched.append(p))
    w._launch_update(tmp_path / "setup.exe")
    assert launched == [tmp_path / "setup.exe"] and w._force_close


def test_a_running_job_stops_the_update_from_closing_the_window(qtbot, win, monkeypatch, tmp_path):
    w, ctrl = win
    launched = []
    monkeypatch.setattr(updater, "launch_installer", lambda p: launched.append(p))
    monkeypatch.setattr(type(w.queue), "is_busy", property(lambda self: True))
    w._launch_update(tmp_path / "setup.exe")
    assert launched == [] and not w._force_close
    assert "running job" in w.banner._text.text()


def test_a_failing_launcher_says_so_and_keeps_the_window(qtbot, win, monkeypatch, tmp_path):
    w, ctrl = win

    def boom(p):
        raise OSError("blocked by antivirus")
    monkeypatch.setattr(updater, "launch_installer", boom)
    w._launch_update(tmp_path / "setup.exe")
    assert not w._force_close and "antivirus" in w.banner._text.text()


@pytest.mark.parametrize("toggle,env,due,expect", [(True, None, True, True), (False, None, True, False),
                                                   (True, "1", True, False), (True, None, False, False)])
def test_the_daily_check_runs_only_when_wanted(qtbot, win, monkeypatch, toggle, env, due, expect):
    w, ctrl = win
    w.settings_tab.update_toggle.setChecked(toggle)
    if env:
        monkeypatch.setenv("EXCMP_NO_UPDATE_CHECK", env)
    else:
        monkeypatch.delenv("EXCMP_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(ctrl, "due", lambda: due)
    calls = []
    monkeypatch.setattr(ctrl, "check", lambda silent=False: calls.append(silent))
    w.auto_update_check()
    assert calls == ([True] if expect else [])


def test_a_bare_window_never_starts_a_check_by_itself(qtbot, monkeypatch):
    """Only app.main() schedules the daily look, so a test (or anyone importing MainWindow) never
    reaches the network."""
    from gui.mainwindow import MainWindow
    calls = []
    monkeypatch.setattr(UpdateController, "check", lambda self, silent=False: calls.append(1))
    w = MainWindow()
    qtbot.addWidget(w)
    qtbot.wait(300)
    assert calls == []
