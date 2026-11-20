"""I5, the Settings tab's switch for the Explorer menu.

The CLI (`excmp shell install`) and the installer could already add the menu; a person inside the
app had no way to. These tests drive the row with a FAKE shell backend, so no test can write to the
real `HKCU\\Software\\Classes` (the one place a test must never edit), and check the project's rules:
no modal dialog (failures are said inline), and the row is absent where there is no Explorer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox      # noqa: E402

from excmp.shellmenu import Status                                    # noqa: E402
from gui.widgets.settings_tab import SettingsTab                      # noqa: E402


class FakeShell:
    """Records what the tab asks for; holds the 'registry' state in a dict."""

    def __init__(self, installed=False, stale=False, fail=None, partial=False):
        self.installed, self.stale, self.fail = installed, stale, fail
        self.partial = partial
        self.calls = []

    def status(self):
        return Status(installed=self.installed, stale=self.stale and self.installed,
                      missing=[] if self.installed else ["x"],
                      found=["k"] if (self.installed or self.partial) else [])

    def install(self, *a, **k):
        self.calls.append("install")
        if self.fail:
            raise self.fail
        self.installed, self.stale, self.partial = True, False, False
        return ["k"]

    def uninstall(self, *a, **k):
        self.calls.append("uninstall")
        if self.fail:
            raise self.fail
        was, self.installed = self.installed, False
        return ["k"] if was else []


def _tab(qtbot, shell, windows=True):
    tab = SettingsTab({}, Path("."), shell=shell, shell_supported=windows)
    qtbot.addWidget(tab)
    return tab


def test_off_by_default_the_button_offers_to_add_it(qtbot):
    tab = _tab(qtbot, FakeShell())
    assert tab.explorer_button.text() == "Add"
    assert "not" in tab.explorer_state.text().lower()


def test_clicking_add_installs_and_the_button_becomes_remove(qtbot):
    shell = FakeShell()
    tab = _tab(qtbot, shell)
    tab.explorer_button.click()
    assert shell.calls == ["install"]
    assert tab.explorer_button.text() == "Remove"
    assert "on" in tab.explorer_state.text().lower()


def test_clicking_remove_uninstalls_and_goes_back(qtbot):
    shell = FakeShell(installed=True)
    tab = _tab(qtbot, shell)
    assert tab.explorer_button.text() == "Remove"
    tab.explorer_button.click()
    assert shell.calls == ["uninstall"]
    assert tab.explorer_button.text() == "Add"


def test_a_menu_that_points_at_another_copy_offers_to_repair_it(qtbot):
    shell = FakeShell(installed=True, stale=True)
    tab = _tab(qtbot, shell)
    assert tab.explorer_button.text() == "Repair"
    assert "another" in tab.explorer_state.text().lower() or "different" in tab.explorer_state.text().lower()
    tab.explorer_button.click()
    assert shell.calls == ["install"]
    assert tab.explorer_button.text() == "Remove"


def test_a_failure_is_said_inline_and_nothing_pops_up(qtbot, monkeypatch):
    """The project's rule: no modal dialog, ever."""
    popped = []
    monkeypatch.setattr(QMessageBox, "exec", lambda *a, **k: popped.append("box") or 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: popped.append("warn") or 0)
    monkeypatch.setattr(QDialog, "exec", lambda *a, **k: popped.append("dlg") or 0)
    shell = FakeShell(fail=PermissionError("registry is locked by policy"))
    tab = _tab(qtbot, shell)
    tab.explorer_button.click()
    assert popped == []
    assert "registry is locked by policy" in tab.explorer_state.text()
    assert tab.explorer_button.text() == "Add"              # still offers to try again
    assert tab.explorer_button.isEnabled()


def test_the_row_is_hidden_where_there_is_no_explorer(qtbot):
    tab = _tab(qtbot, FakeShell(), windows=False)
    assert tab.explorer_row.isHidden()


def test_the_buttons_name_says_what_it_does_for_a_screen_reader(qtbot):
    tab = _tab(qtbot, FakeShell())
    assert "explorer" in tab.explorer_button.accessibleName().lower()
    assert tab.explorer_button.accessibleDescription()


def test_the_row_refreshes_when_the_menu_changed_behind_its_back(qtbot):
    """Installed from the command line while the app is open: Refresh reads the registry again."""
    shell = FakeShell()
    tab = _tab(qtbot, shell)
    shell.installed = True
    tab.refresh_explorer_menu()
    assert tab.explorer_button.text() == "Remove"


def test_building_the_tab_never_writes_to_the_registry(qtbot):
    shell = FakeShell()
    _tab(qtbot, shell)
    assert shell.calls == []


def test_the_real_default_backend_is_read_only_on_construction(qtbot, monkeypatch):
    """Without an injected backend the tab reads the real registry's state (harmless) and only ever
    writes when the button is clicked."""
    from excmp import shellmenu
    wrote = []
    monkeypatch.setattr(shellmenu, "install", lambda *a, **k: wrote.append("install"))
    monkeypatch.setattr(shellmenu, "uninstall", lambda *a, **k: wrote.append("uninstall"))
    tab = SettingsTab({}, Path("."))
    qtbot.addWidget(tab)
    assert wrote == []


def test_a_half_installed_menu_is_not_called_absent(qtbot):
    """Review: an install that failed on its 4th write left the compress verb live, yet the label
    said "Not in the Explorer menu." The button (Add completes it) was right; the label was not."""
    tab = _tab(qtbot, FakeShell(partial=True))
    assert "part" in tab.explorer_state.text().lower()
    assert "not in" not in tab.explorer_state.text().lower()
    assert tab.explorer_button.text() == "Repair"
    tab.explorer_button.click()
    assert tab.explorer_button.text() == "Remove"


@pytest.mark.parametrize("shell", [FakeShell(), FakeShell(installed=True), FakeShell(installed=True, stale=True)])
def test_a_screen_reader_hears_what_the_button_does(qtbot, shell):
    """Review: a fixed accessible name hid "Add", "Remove" and "Repair" behind the row's title."""
    tab = _tab(qtbot, shell)
    name = tab.explorer_button.accessibleName()
    assert tab.explorer_button.text() in name
    assert "Explorer" in name
