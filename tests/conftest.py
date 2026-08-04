"""Shared pytest setup.

The GUI tests must never pop a real window - on a developer machine that
steals focus mid-run, and on CI there is no display at all. Setting the Qt
platform plugin here works because pytest imports ``conftest.py`` before any
test module, and therefore before PySide6 is first imported.

QSettings is rerouted to a per-test temp directory (W1-1's other half): the
app persists window geometry now, and without this fixture the GUI tests
would read the developer's real stored geometry - machine-dependent,
order-dependent, and polluting the registry on every CI run.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
