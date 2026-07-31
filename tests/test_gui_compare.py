"""The comparison table, driven through Qt (J3).

Two things matter here and neither is cosmetic: the window must not advise a
preset the table has flagged as a bad trade, and clicking a row must actually
switch the preset - a cheaper option the user cannot take in one click is just
a reproach.
"""

import random

import pytest

from excmp.planner import Profile

pytest.importorskip("pytestqt")

from gui.mainwindow import MainWindow          # noqa: E402
from gui.suggest import ComparisonRow          # noqa: E402
from gui.widgets.compare_table import CompareTable  # noqa: E402


def _mixed_tree(root):
    """A folder with something worth compressing and something that is not."""
    root = root / "mixed"
    root.mkdir()
    (root / "notes.txt").write_text("the quick brown fox. " * 40_000)
    rng = random.Random(7)
    (root / "clip.mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom" + bytes(rng.getrandbits(8) for _ in range(400_000)))
    return root


def _row(profile=Profile.NORMAL, **kw):
    base = dict(profile=profile, title=profile.value.title(), chain="7-Zip",
                size_text="701.0 MB", size_range="667 MB – 710 MB",
                saved_text="3%", time_text="~1 min", time_range="34s – 2 min")
    base.update(kw)
    return ComparisonRow(**base)


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


# -- the widget on its own -------------------------------------------------

def test_the_table_hides_itself_when_there_is_nothing_to_estimate(qtbot):
    table = CompareTable()
    qtbot.addWidget(table)
    assert not table.isVisible()

    table.set_rows([_row()])
    assert table.rows() and len(table.rows()) == 1

    table.set_rows([])
    assert not table.isVisible()
    assert table.rows() == []


def test_rebuilding_the_table_does_not_accumulate_rows(qtbot):
    """It is repopulated on every profile change, so a leak here would grow the
    window a row at a time."""
    table = CompareTable()
    qtbot.addWidget(table)
    for _ in range(4):
        table.set_rows([_row(p) for p in Profile])
    assert len(table.rows()) == len(list(Profile))


def test_clicking_a_row_asks_for_that_profile(qtbot):
    table = CompareTable()
    qtbot.addWidget(table)
    table.set_rows([_row(p) for p in Profile])

    chosen = []
    table.profileChosen.connect(chosen.append)
    next(r for r in table.rows() if r.profile is Profile.FAST).clicked.emit(Profile.FAST)
    assert chosen == [Profile.FAST]


def test_every_row_is_readable_as_one_sentence(qtbot):
    """A screen reader should not have to stitch five cells together, and the
    flag has to survive into the spoken text - not just the colour."""
    table = CompareTable()
    qtbot.addWidget(table)
    table.set_rows([_row(Profile.EXTREME, note="Normal gets there 2.7x quicker.",
                         time_text="~3 min")])
    spoken = table.rows()[0].accessibleName()
    assert "Extreme" in spoken and "~3 min" in spoken
    assert "quicker" in spoken


def test_a_recommended_row_still_shows_its_caveat(qtbot):
    """A Precomp row is routinely both suggested and conditionally flagged. If
    the badge swallowed the warning the table would be worse than silent."""
    table = CompareTable()
    qtbot.addWidget(table)
    table.set_rows([_row(Profile.EXTREME, recommended=True,
                         reason="lots of compressible data",
                         note="If Precomp cannot open these streams, Normal wins.")])
    spoken = table.rows()[0].accessibleName()
    assert "lots of compressible data" in spoken
    assert "If Precomp cannot open these streams" in spoken


# -- wired into the window -------------------------------------------------

def test_analysis_fills_the_table_and_the_badge_agrees_with_it(window, qtbot, tmp_path):
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([_mixed_tree(tmp_path)])

    rows = window.compare_table.rows()
    assert len(rows) == len(list(Profile))
    assert window.compare_table.isVisibleTo(window)

    suggested = [r for r in rows if r.property("tone") == "accent"]
    assert len(suggested) == 1
    # The preset cards must be showing the same profile the table highlights.
    assert window.presets.current_profile() is suggested[0].profile


def test_the_window_never_suggests_an_unconditionally_bad_trade(window, qtbot, tmp_path):
    """A Precomp row may be suggested while carrying its "if Precomp cannot open
    these streams" caveat - that ambiguity is real and measured. What must never
    happen is suggesting a profile whose extra time buys nothing at all."""
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([_mixed_tree(tmp_path)])

    from gui.suggest import profile_comparison
    rows = profile_comparison(window._infos, window.tools, window._summary)
    for row in rows:
        if row.recommended and row.note:
            assert row.note.startswith("If Precomp cannot open"), row.note


def test_choosing_a_row_switches_the_preset_and_replans(window, qtbot, tmp_path):
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([_mixed_tree(tmp_path)])

    target = next(p for p in Profile if p is not window.presets.current_profile())
    window._choose_profile(target)
    assert window.presets.current_profile() is target
    # Re-planning is what keeps the analysis card honest about the new chain.
    assert window._summary is not None
    assert len(window.compare_table.rows()) == len(list(Profile))


def test_clearing_the_input_clears_the_table(window, qtbot, tmp_path):
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([_mixed_tree(tmp_path)])
    assert window.compare_table.rows()

    window.clear_pending()
    assert window.compare_table.rows() == []
    assert not window.compare_table.isVisible()
