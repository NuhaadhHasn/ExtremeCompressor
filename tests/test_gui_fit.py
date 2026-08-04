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


# ---------------------------------------------------------------------------
# W1-11: the fit regression gate. This class of bug shipped once already.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size", [(1180, 721), (1092, 614)],
                         ids=["1366x768@100%", "1366x768@125%"])
def test_the_empty_compress_page_needs_no_scrolling(window, qtbot, size):
    """Before a single file is dropped there is nothing that can justify a
    scrollbar - yet at 125% the old layout overflowed even when empty."""
    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    assert window._scroll.verticalScrollBar().maximum() == 0, (
        f"empty state scrolls at {size}")


def test_the_page_fits_910_logical_pixels_of_width(window, qtbot):
    """150% scaling leaves 910 logical px. The widest label used to force the
    page minimum to 939px and grow a horizontal scrollbar."""
    page = window._scroll.widget()
    assert page.minimumSizeHint().width() <= 900, (
        f"page minimum width {page.minimumSizeHint().width()}px")


def test_the_commit_button_never_scrolls_away(window, qtbot, tmp_path):
    """W1-2: the action bar lives outside the scrolling page, so the Compress
    button is on screen in EVERY configuration - it used to sit 428-860px
    below the fold as soon as analysis populated."""
    window.resize(1180, 721)
    window.show()
    qtbot.waitExposed(window)
    assert window.compress_button.isVisible()
    # The button must NOT be a descendant of the scroll area.
    parent = window.compress_button.parent()
    while parent is not None:
        assert parent is not window._scroll.widget()
        parent = parent.parent()


def test_the_action_bar_follows_the_compress_tab(window, qtbot):
    window.show()
    qtbot.waitExposed(window)
    assert window.action_bar.isVisible()
    window.tabs.setCurrentWidget(window.extract_tab)
    assert not window.action_bar.isVisible()
    window.tabs.setCurrentWidget(window._scroll)
    assert window.action_bar.isVisible()


def test_a_hostile_archive_name_blocks_compression_with_words(window, qtbot, tmp_path):
    """The editable name goes through safepath - the app must not create a
    file it would refuse to read - and the refusal is textual, not a colour."""
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("x" * 1000)
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])
    assert window.compress_button.isEnabled()

    window.name_edit.setText("evil:name")
    assert not window.compress_button.isEnabled()
    assert window._name_error.isVisibleTo(window.action_bar)

    window.name_edit.setText("fine name")
    assert window.compress_button.isEnabled()
    out = window._output_path_for(window._pending)
    assert out.name == "fine name.excmp"


def test_the_action_registry_exists_and_fires_the_same_slots(window, qtbot):
    """W1-9: QActions behind the tab-corner hamburger - no QMenuBar row, the
    150% height budget has no room for one."""
    assert window.tabs.cornerWidget() is window.menu_button
    for key in ("add-files", "add-folder", "open-archive", "pause",
                "clear-finished", "theme", "about", "exit"):
        assert key in window.actions, f"missing action {key}"

    before = window.theme_name
    window.actions["theme"].trigger()
    assert window.theme_name != before

    window.actions["about"].trigger()
    assert window._about_card is not None
    assert window._about_card.isVisibleTo(window)
    assert "v0" in window._about_card.findChild(type(window.queue_status)).text()


def test_copy_as_command_reproduces_the_job(window):
    from gui.models import Job, JobKind
    from excmp.planner import Profile
    from pathlib import Path as P

    job = Job(kind=JobKind.COMPRESS, inputs=[P("C:/in/data")],
              out_path=P("C:/out/data.excmp"), profile=Profile.EXTREME)
    cmd = window._job_as_command(job)
    assert cmd == ('python -m excmp compress "C:\\in\\data" '
                   '-o "C:\\out\\data.excmp" -p extreme')


# ---------------------------------------------------------------------------
# W1-1: geometry persistence (the first QSettings in the app)
# ---------------------------------------------------------------------------

def _fresh_window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_window_geometry_survives_a_relaunch(qtbot, tmp_path):
    # 640x480 fits every screen including the offscreen platform's default -
    # anything bigger would (correctly) trip the clamp and hide the point.
    first = _fresh_window(qtbot)
    first.resize(640, 480)
    first.close()
    first.queue.shutdown()

    second = _fresh_window(qtbot)
    try:
        assert (second.width(), second.height()) == (640, 480)
    finally:
        second.queue.shutdown()


def test_settings_land_in_the_isolated_ini_not_the_registry(qtbot, tmp_path):
    win = _fresh_window(qtbot)
    win.resize(700, 500)
    win.close()
    win.queue.shutdown()
    ini_files = list(tmp_path.rglob("*.ini"))
    assert ini_files, "geometry was not written through the isolated QSettings"


def test_a_stored_geometry_bigger_than_the_screen_is_clamped(qtbot):
    """A window remembered from a big monitor must not reopen 900px tall on a
    1366x768 laptop - that is the original bug wearing a QSettings coat."""
    from PySide6.QtCore import QSettings

    first = _fresh_window(qtbot)
    first.resize(700, 500)
    first.close()
    first.queue.shutdown()
    # Sabotage the stored size to something no screen here can show.
    settings = QSettings()
    assert settings.contains("window/geometry")
    first2 = _fresh_window(qtbot)
    first2.resize(5000, 4000)
    first2.close()
    first2.queue.shutdown()

    second = _fresh_window(qtbot)
    try:
        avail = QApplication.primaryScreen().availableGeometry()
        assert second.width() <= avail.width()
        assert second.height() <= avail.height()
    finally:
        second.queue.shutdown()
