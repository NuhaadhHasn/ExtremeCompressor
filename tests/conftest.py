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
def _isolated_calibration(tmp_path, monkeypatch):
    """Route J7's learned rates to tmp_path, like QSettings above.

    ``excmp.calibrate.DEFAULT_PATH`` is ``~/.excmp/calibration.json`` and every
    finished GUI job writes to it (`CompressWorker._calibrate`). Nothing
    isolated it, so the suite's result depended on whether a real compression
    had ever run on the machine — and the layout budgets are downstream of the
    estimator, which is downstream of those rates.

    Found on 2026-09-20 by I6's own end-to-end tests: they run real queue jobs,
    which wrote a single zstd sample into that file, which changed Fast's
    estimate, which gave Normal a "not worth it" note, which put a
    point-estimate row at 53px against its 36px budget and the populated page
    at 487px against 447. Two pixel gates failing for a reason that was not
    about pixels — and the same two tests pass or fail depending on the order
    they run in, which is the worst shape a guard test can have.
    """
    from excmp import calibrate

    monkeypatch.setattr(calibrate, "DEFAULT_PATH",
                        tmp_path / "calibration.json")


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


# ---------------------------------------------------------------------------
# The pixel budgets are only meaningful against the fonts they were measured
# with. D7's first real CI run is what established that.
# ---------------------------------------------------------------------------

#: `QFontMetrics(app.font()).height()` and the advance of one canonical string,
#: measured on the development machine 2026-09-10 with the real Windows fonts.
#:
#: **Why this exists.** `test_gui_fit.py` and `test_gui_compact.py` assert
#: layout budgets in *pixels*, deliberately: "measured with the REAL Windows
#: fonts ... that matters more than it sounds", because Qt's offscreen plugin
#: ships no font database and tofu boxes make every measurement fiction.
#:
#: What that reasoning did not account for is a *different* real font
#: environment. `windows-latest` has a `C:\Windows\Fonts` - so
#: `QT_QPA_FONTDIR` is set and the glyphs are real - holding a Windows Server
#: font set with larger metrics. D7's first CI run measured the populated
#: Compress page at **464px against a 447px ceiling**, a profile row at
#: **50px against 36px**, and the empty page scrolling at 910x512. None of the
#: three is a layout regression; all three are the same font stack difference.
#:
#: So the budgets are gated rather than loosened. Raising a ceiling to
#: accommodate an unknown font would destroy the thing it protects - these
#: gates caught a 132px-too-tall window and a 55px progress slab that no other
#: test saw - and a gate that fails for a reason unrelated to the code is one
#: nobody reads twice.
REFERENCE_FONT_PROBE = (13, 129)
_FONT_PROBE_STRING = "Compress Extract Activity Settings"


def measure_font_probe() -> tuple[int, int]:
    """This process's font metrics, as the pair REFERENCE_FONT_PROBE records.

    Requires a QApplication to exist, which is why this is a function rather
    than a module-level constant: `pytest.mark.skipif` is evaluated at import
    time, long before pytest-qt has built one.
    """
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None, "measure_font_probe needs a QApplication"
    metrics = QFontMetrics(app.font())
    return (metrics.height(),
            metrics.horizontalAdvance(_FONT_PROBE_STRING))


def font_gate_verdict(probe: tuple[int, int], reference: tuple[int, int],
                      on_ci: bool) -> str:
    """``"run"``, ``"skip"`` or ``"fail"`` - the whole decision, in one place.

    Separated from the fixture so it can be tested directly. The rule it
    encodes is small and easy to get backwards, and getting it backwards in
    the *quiet* direction (skip on the reference machine) disables every
    layout budget in the suite without anybody noticing.
    """
    if probe == reference:
        return "run"
    return "skip" if on_ci else "fail"


@pytest.fixture
def reference_fonts(qapp):
    """Guard any test that asserts a pixel size.

    Skips on a foreign font stack - and **fails** on this one, which is the
    half that matters. A skip-gate can quietly disable the tests it guards: if
    a Windows update shifted the metrics on the development machine, a plain
    `pytest.skip` would switch off every layout budget in the suite and report
    green, which is the exact "a green suite proves nothing about what it does
    not look at" failure these gates exist to prevent.

    So the two cases are told apart by ``CI``, which GitHub Actions sets:

    - **On a runner** a mismatch is expected and uninteresting, because the
      budgets were never measured there. Skip, and say why.
    - **Anywhere else** a mismatch means the recorded reference is stale, and
      that is worth stopping for: re-measure it and update
      REFERENCE_FONT_PROBE in the same commit as whatever new ceilings the new
      metrics imply.
    """
    probe = measure_font_probe()
    verdict = font_gate_verdict(probe, REFERENCE_FONT_PROBE,
                                bool(os.environ.get("CI")))
    if verdict == "run":
        return probe
    if verdict == "skip":
        pytest.skip(
            f"pixel budgets were measured with font metrics "
            f"{REFERENCE_FONT_PROBE}; this runner reports {probe}, so an "
            f"absolute px assertion here would measure the font rather than "
            f"the layout (see REFERENCE_FONT_PROBE in tests/conftest.py)")
    pytest.fail(
        f"this machine's font metrics are {probe}, but the layout budgets in "
        f"test_gui_fit.py and test_gui_compact.py were measured against "
        f"{REFERENCE_FONT_PROBE}. Every one of those ceilings would now be "
        f"measuring a different font, so they are neither meaningful nor "
        f"safe to loosen. Re-measure the probe, update REFERENCE_FONT_PROBE, "
        f"and re-derive the ceilings in the same commit.\n\n"
        f"Deliberately a failure rather than a skip: skipping here would "
        f"switch off every layout gate in the suite and still report green.")
