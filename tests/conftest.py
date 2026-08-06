"""Shared pytest setup.

The GUI tests must never pop a real window - on a developer machine that
steals focus mid-run, and on CI there is no display at all. Setting the Qt
platform plugin here works because pytest imports ``conftest.py`` before any
test module, and therefore before PySide6 is first imported.

**The font directory is part of that setup, not a nicety.** Qt's offscreen
plugin ships no font database; without ``QT_QPA_FONTDIR`` every glyph is a
tofu box of the wrong width, so every layout measurement a test makes is
fiction. The height gates in test_gui_fit.py were quietly measuring tofu and
under-reporting the populated page by ~80px until this was set (tools/shots.py
had it right all along - that is where this line comes from).

QSettings is rerouted to a per-test temp directory (W1-1's other half): the
app persists window geometry now, and without this fixture the GUI tests
would read the developer's real stored geometry - machine-dependent,
order-dependent, and polluting the registry on every CI run.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    """Route every QSettings() in the test process to tmp_path, as INI files.

    Must run before any window is constructed. setPath applies to settings
    objects created *after* the call, which autouse guarantees per-test.
    """
    from PySide6.QtCore import QCoreApplication, QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(tmp_path))
    # Tests build windows without gui.app.build_app (the one production place
    # that names the app), so name it here or QSettings falls back to noise.
    if not QCoreApplication.organizationName():
        QCoreApplication.setOrganizationName("NuhaadhHasn")
    if not QCoreApplication.applicationName():
        QCoreApplication.setApplicationName("ExtremeCompressor")
    yield
