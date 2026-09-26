"""UI v3 wave 2b: the compaction that makes the Compress page fit.

Wave 2a moved the queue and the results panel off this page (869 -> 748px).
What is left is the page's own three widgets, and research/23 §2.4's budget
depends on all three shrinking:

    drop zone   116px  ->  an intake chip once files are in
    analysis    200px  ->  headline + bar + gain, details behind a toggle
    chooser     401px  ->  32px rows, footnote behind the (i) disclosure
                           that W1-13 specified and never built

Every assertion here is about *what stays visible*, not just about pixels.
The rules that survive compaction: the gain note is never collapsed, colour
never becomes the only signal, and nothing honest is demoted to a tooltip.
"""

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from excmp.planner import Profile          # noqa: E402
from gui.mainwindow import MainWindow      # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def populated(window, qtbot, tmp_path):
    """Three *items*, dropped individually.

    The pending list is a list of what the user handed over, not of every file
    underneath it - removing one item removes it from the compression input,
    which is a promise the engine can keep today. Per-file exclusion inside a
    dropped folder would need include/exclude globs in `_collect`, which
    research/23 §5 lists as an engine addition, not free glue.
    """
    src = tmp_path / "data"
    src.mkdir()
    files = [src / "a.txt", src / "b.bin", src / "c.log"]
    files[0].write_text("compress me. " * 4000)
    files[1].write_bytes(bytes(range(256)) * 500)
    files[2].write_text("line\n" * 9000)
    window.resize(910, 512)
    window.show()
    qtbot.waitExposed(window)
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths(files)
    qtbot.wait(50)
    return window


# ---------------------------------------------------------------------------
# The intake chip
# ---------------------------------------------------------------------------

def test_the_drop_zone_collapses_to_a_chip_once_files_are_in(populated, qtbot,
                                                             reference_fonts):
    """A 116px "drop files here" panel is worth its space exactly once. After
    that it is a receipt, and a receipt is one line."""
    zone = populated.drop_zone
    assert zone.is_compact()
    assert zone.height() <= 52, zone.height()
    summary = zone.summary_text()
    assert "1 item" in summary or "item" in summary
    assert "KB" in summary or "MB" in summary, summary


def test_the_chip_still_offers_every_intake_action(populated):
    zone = populated.drop_zone
    for button in (zone.files_button, zone.folder_button, zone.clear_button):
        assert button.isVisibleTo(zone), button.text()


def test_clearing_brings_the_full_drop_zone_back(populated, qtbot):
    populated.clear_pending()
    qtbot.wait(20)
    assert not populated.drop_zone.is_compact()


def test_dragging_over_the_chip_re_expands_it(populated, qtbot):
    """You cannot aim at a 36px strip. The moment a drag enters, the target
    becomes the full panel again."""
    zone = populated.drop_zone
    assert zone.is_compact()
    zone._set_active(True)
    assert not zone.is_compact(), "the chip stayed small mid-drag"
    zone._set_active(False)
    assert zone.is_compact()


# ---------------------------------------------------------------------------
# W2-10: reviewing and removing before committing
# ---------------------------------------------------------------------------

def test_the_pending_list_starts_collapsed_and_costs_nothing(populated):
    assert not populated.pending_list.isVisibleTo(populated.drop_zone)


def test_removing_one_file_re_summarises_without_re_reading_it(populated, qtbot,
                                                               monkeypatch):
    """The FileInfo list is already in memory - re-running the planner over it
    is free, and re-reading three files from a slow drive is not."""
    populated.drop_zone.toggle_pending()
    assert populated.pending_list.isVisibleTo(populated.drop_zone)
    assert populated.pending_list.count() == 3

    import excmp.analyzer

    def explode(*a, **k):
        raise AssertionError("the analyzer re-read the files")

    monkeypatch.setattr(excmp.analyzer, "analyze_file", explode)

    before = populated._summary.total_bytes
    populated.pending_list.setCurrentRow(0)
    populated.remove_selected_pending()
    qtbot.wait(30)

    assert populated.pending_list.count() == 2
    assert populated._summary.total_bytes < before


def test_removing_the_last_file_returns_to_the_empty_state(populated, qtbot):
    populated.drop_zone.toggle_pending()
    for _ in range(3):
        populated.pending_list.setCurrentRow(0)
        populated.remove_selected_pending()
    qtbot.wait(30)
    assert not populated.drop_zone.is_compact()
    assert not populated.compress_button.isEnabled()


# ---------------------------------------------------------------------------
# The analysis card
# ---------------------------------------------------------------------------

def test_the_analysis_card_keeps_its_promise_while_shrinking(populated,
                                                             reference_fonts):
    """Compaction may not touch the two sentences the product exists for:
    what this pile is, and how much of it can actually shrink."""
    card = populated.analysis_card
    assert card.headline_text()
    assert card.gain_text()
    assert card._gain.isVisibleTo(card), "the gain note was collapsed"
    assert card.height() <= 110, card.height()


def test_the_analysis_details_are_a_disclosure_not_a_deletion(populated):
    card = populated.analysis_card
    assert not card._details.isVisibleTo(card)
    card.details_toggle.click()
    assert card._details.isVisibleTo(card)
    # Everything that used to be permanently on the card is still reachable.
    assert card._legend_holder.isVisibleTo(card)


def test_the_breakdown_bar_is_never_the_only_signal(populated):
    """The colour legend moves into the details expander, so the headline has
    to carry the same shares in words - otherwise a collapsed card is a row of
    unexplained colours, which is the one thing this app does not ship."""
    card = populated.analysis_card
    assert "%" in card.headline_text(), card.headline_text()


def test_the_dead_shrink_mode_checkbox_became_a_sentence(populated):
    """A permanently disabled checkbox is a promise the UI cannot keep. The
    answer to "can it re-encode my videos?" is now prose, in the details."""
    card = populated.analysis_card
    assert not hasattr(card, "shrink_toggle"), "the dead checkbox is still there"
    populated.analysis_card.details_toggle.click()
    assert "re-encod" in card._shrink_note.text().lower()


# ---------------------------------------------------------------------------
# The chooser
# ---------------------------------------------------------------------------

def test_the_footnote_is_the_disclosure_w1_13_specified(populated):
    """W1-13 said "click-to-toggle (i) disclosure, not a tooltip". It shipped
    as a permanently visible 68px paragraph. This is the missing half."""
    chooser = populated.compare_table
    assert chooser.info_toggle.isVisibleTo(chooser)
    assert not chooser._footnote.isVisibleTo(chooser)
    chooser.info_toggle.click()
    assert chooser._footnote.isVisibleTo(chooser)
    assert "measured" in chooser._footnote.text().lower()


def test_the_disclosure_is_not_a_tooltip(populated):
    """Keyboard users and screenshots both lose tooltips."""
    chooser = populated.compare_table
    assert chooser.info_toggle.focusPolicy() != 0


#: One line of a profile row's trade-off note: 69 - 50 px, measured B17.
NOTE_LINE_PX = 19


def test_profile_rows_are_compact_where_they_honestly_can_be(populated,
                                                             reference_fonts):
    """§2.4 budgeted every row at 32px. That holds for a row whose estimate is
    a single number (Fast, Normal) - they land on 33px. It does NOT hold for
    Extreme and Insane, whose cells carry a second line because their real
    answer is a *range*: Precomp's gain is unknowable until it runs. Inlining
    that range clips it in a 178px column, and hiding it is exactly the kind
    of false precision this app exists to refuse. So those rows are ~51px on
    purpose, and the extra height sits precisely where the uncertainty is.
    """
    chooser = populated.compare_table
    rows = chooser.rows()
    assert len(rows) == 4

    point_estimates = [r for r in rows if not r.shows_range()]
    assert point_estimates, "no single-number row to measure"
    for row in point_estimates:
        assert row.height() <= 36, f"{row.profile.value} row is {row.height()}px"

    for row in rows:
        if row.shows_range():
            # B17: a range row that also carries a trade-off note is one line
            # taller. Measured 2026-09-27: Insane 69px against the other
            # rows' 50 once its measured time made the "Extreme is ~24x
            # quicker" note true. The note's own visibility is asserted below.
            limit = 56 + (NOTE_LINE_PX if row.has_note() else 0)
            assert row.height() <= limit, f"{row.profile.value} row is {row.height()}px"
        if row.has_note():
            assert row._note_label.isVisibleTo(row), (
                f"{row.profile.value} lost its warning to the diet")


def test_the_recommended_row_still_says_so_in_words(populated):
    chooser = populated.compare_table
    suggested = [r for r in chooser.rows()
                 if "suggested" in r.accessibleName().lower()]
    assert len(suggested) == 1, "exactly one Suggested assertion, in text"


# ---------------------------------------------------------------------------
# W2-4: the token sweep
# ---------------------------------------------------------------------------

def test_the_radii_follow_the_windows_geometry_tokens():
    from gui.theme import METRICS

    assert METRICS["radius"] == "8px"        # OverlayCornerRadius
    assert METRICS["radius_sm"] == "4px"     # ControlCornerRadius


def test_selection_does_not_reflow_the_row():
    """A 1px resting border becoming 2px on selection moved every cell by a
    pixel. The border is 2px always; only the colour changes."""
    from gui.theme import qss as build_qss

    qss = build_qss("dark")
    resting = [line for line in qss.splitlines() if "#ProfileRow {" in line]
    assert resting, "ProfileRow has no rule of its own"
    block = qss.split("#ProfileRow {", 1)[1].split("}", 1)[0]
    assert "border: 2px solid" in block, block


def test_controls_have_an_explicit_minimum_height(reference_fonts):
    from gui.theme import qss as build_qss

    qss = build_qss("dark")
    button_block = qss.split("QPushButton {", 1)[1].split("}", 1)[0]
    assert "min-height" in button_block, button_block


# ---------------------------------------------------------------------------
# W2-6: the title bar
# ---------------------------------------------------------------------------

def test_the_titlebar_helper_is_safe_to_call_anywhere(window):
    """It is a Win32 DWM call behind ctypes. On a non-Windows box, or an old
    Windows 10 build without the attribute, it must no-op rather than raise."""
    from gui.winintegration import set_dark_titlebar

    assert set_dark_titlebar(0, True) is False          # bogus hwnd
    assert set_dark_titlebar(int(window.winId()), True) in (True, False)


def test_toggling_the_theme_repaints_the_titlebar(window, qtbot, monkeypatch):
    calls = []
    import gui.mainwindow as mw

    monkeypatch.setattr(mw, "set_dark_titlebar",
                        lambda hwnd, dark: calls.append(dark) or True)
    window.show()
    qtbot.waitExposed(window)
    before = window.theme_name
    window.toggle_theme()
    assert calls, "the title bar was never told the theme changed"
    assert calls[-1] is (window.theme_name == "dark")
    assert window.theme_name != before


# ---------------------------------------------------------------------------
# W2-5: Fluent SVGs instead of emoji
# ---------------------------------------------------------------------------

def test_every_preset_has_a_vendored_icon():
    from gui.icons import ICON_DIR, PRESET_ICONS

    for profile in Profile:
        assert profile.value in PRESET_ICONS, profile.value
    for stem in PRESET_ICONS.values():
        assert (ICON_DIR / f"{stem}.svg").is_file(), stem
    # OSI-clean is a hard repo rule: vendored assets ship their licence.
    licence = (ICON_DIR / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Microsoft" in licence


def test_icons_are_tinted_with_the_theme_token():
    from gui.icons import icon

    dark = icon("flash", "#ff0000", 16)
    light = icon("flash", "#00ff00", 16)
    assert not dark.isNull() and not light.isNull()
    a = dark.pixmap(16, 16).toImage()
    b = light.pixmap(16, 16).toImage()
    assert a != b, "the tint did not reach the rendered pixels"


def test_a_missing_icon_never_breaks_the_app():
    from gui.icons import icon

    assert icon("no-such-glyph", "#ffffff").isNull()


def test_the_glyphs_repaint_when_the_theme_flips(populated, qtbot):
    row = populated.compare_table.rows()[0]
    before = row.glyph.pixmap().toImage()
    populated.toggle_theme()
    qtbot.wait(20)
    after = row.glyph.pixmap().toImage()
    assert before != after, "an emoji could not do this; an SVG must"


def test_no_emoji_glyph_reaches_the_chooser_labels(populated):
    """The catalogue keeps its emoji for text fallbacks, but nothing paints
    them into the window any more."""
    for row in populated.compare_table.rows():
        assert not any(ch in row._name.text() for ch in "⚡🔥🌙"), row._name.text()


def test_a_clipped_caveat_ends_in_an_ellipsis_not_mid_word(populated, qtbot):
    """"zpaqfranz missing - runs as E:" read as a rendering bug. Truncation
    has to look like truncation, and the full sentence stays reachable."""
    from gui.widgets.compare_table import _ElidingLabel

    insane = next(r for r in populated.compare_table.rows()
                  if r.profile is Profile.INSANE)
    subs = [w for w in insane.findChildren(_ElidingLabel) if "zpaqfranz" in w._full]
    assert subs, "the missing-tool caveat vanished"
    label = subs[0]
    label.setFixedWidth(80)
    label.grab()                      # force a paint at the narrow width
    assert label.text().endswith("…"), label.text()
    assert label.toolTip() == label._full
    assert "zpaqfranz" in insane.accessibleName()
