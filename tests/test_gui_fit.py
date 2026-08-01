"""The window must fit the screen it opens on. (UI v3, wave 1 blocker.)

The target machine's primary display is 1366x768. The window used to open at a
hard-coded 1080x900 - 132px taller than that entire screen - which is the
loudest UI complaint on record: "its too big for screen". No design decision
can override this; whatever layout ships, it ships inside the display.
"""

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.mainwindow import MainWindow       # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_the_window_opens_inside_the_available_screen(window):
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()

    assert window.width() <= avail.width(), (
        f"window {window.width()}px wide on a {avail.width()}px screen")
    assert window.height() <= avail.height(), (
        f"window {window.height()}px tall on a {avail.height()}px screen")


def test_the_window_never_hardcodes_a_size_taller_than_small_laptops(window):
    """768 logical pixels of height is the floor this app targets (i7-3540M-era
    panels). Whatever the screen under test reports, the *requested* size must
    stay under that floor when the screen is small - pin the arithmetic."""
    from gui.mainwindow import initial_size

    w, h = initial_size(1366, 768)
    assert h <= 768 and w <= 1366
    # And with the taskbar eating ~40px, still no clipping.
    w, h = initial_size(1366, 728)
    assert h <= 728

    # A big desktop monitor should not get a postage stamp either.
    w, h = initial_size(2560, 1440)
    assert h >= 900 and w >= 1100


def test_the_window_has_a_sane_minimum_so_scaling_cannot_trap_it(window):
    """At 125-150% Windows scaling the logical screen shrinks to ~910x512. A
    minimumSize larger than that makes the window unresizable into view."""
    assert window.minimumWidth() <= 900
    assert window.minimumHeight() <= 520
