"""Settings > Temporary folder has to be the one jobs use.

Found by the user guide: the Advanced panel's own "Temp folder" box started pre-filled with the default folder,
and a filled box always wins, so the Settings choice was never used. Extract and verify jobs did not read it at
all (they used the folder of the last compression, or the default).

Rule now: a folder typed in Advanced is a one-off override; otherwise Settings; otherwise the default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from gui import mainwindow as mw                       # noqa: E402
from gui.mainwindow import DEFAULT_TEMP, MainWindow     # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_the_advanced_box_starts_empty_and_shows_the_effective_folder_as_a_hint(window):
    box = window.advanced_panel.temp_dir
    assert box.text() == ""
    assert Path(box.placeholderText()) == window.settings_tab_temp()


def test_changing_the_setting_changes_the_hint_and_the_folder_used(window, tmp_path):
    window.settings_tab.temp_dir.setText(str(tmp_path / "big-drive"))
    assert window.settings_tab_temp() == tmp_path / "big-drive"
    assert Path(window.advanced_panel.temp_dir.placeholderText()) == tmp_path / "big-drive"
    assert window.effective_temp() == tmp_path / "big-drive"


def test_an_empty_setting_falls_back_to_the_default(window):
    window.settings_tab.temp_dir.setText("")
    assert window.effective_temp() == DEFAULT_TEMP


def test_a_folder_typed_in_advanced_is_a_one_off_override(window, tmp_path):
    window.settings_tab.temp_dir.setText(str(tmp_path / "from-settings"))
    window.advanced_panel.temp_dir.setText(str(tmp_path / "just-this-job"))
    assert window.effective_temp() == tmp_path / "just-this-job"
    assert window.settings_tab_temp() == tmp_path / "from-settings"     # the preference itself is untouched


def test_quotes_and_spaces_around_a_pasted_path_are_ignored(window, tmp_path):
    window.advanced_panel.temp_dir.setText(f'  "{tmp_path / "x"}"  ')
    assert window.effective_temp() == tmp_path / "x"


def test_extract_and_verify_jobs_use_the_settings_folder_too(window, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(window.queue, "add_extract", lambda *a, **k: seen.append(("extract", window.queue.temp_dir)))
    monkeypatch.setattr(window.queue, "add_verify", lambda *a, **k: seen.append(("verify", window.queue.temp_dir)))
    window.settings_tab.temp_dir.setText(str(tmp_path / "big-drive"))
    window._start_extract(tmp_path / "a.excmp", tmp_path / "out")
    window.start_verification(tmp_path / "a.excmp")
    assert seen == [("extract", tmp_path / "big-drive"), ("verify", tmp_path / "big-drive")]


def test_the_existing_job_state_helper_still_works_with_a_typed_folder(window, tmp_path):
    """tests/test_gui_job_state.py types a folder into Advanced: that must keep working."""
    window.advanced_panel.temp_dir.setText(str(tmp_path / "t"))
    assert window.effective_temp() == tmp_path / "t"
