"""I8 — the "what's inside?" treemap.

A folder that is 4 GB of video and 40 MB of source is not the same job as one
the other way round, and the numbers alone do not land the way an area does.

The tests are mostly about the two rules it must not break: never colour
alone, and never claim anything about the *output* - it is a picture of what
you handed over, which is why it needs no engine change.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("squarify")

from excmp.analyzer import Category


@pytest.fixture
def treemap(qtbot):
    from gui.widgets.treemap import Treemap

    w = Treemap()
    qtbot.addWidget(w)
    return w


def test_it_hides_itself_when_there_is_nothing_to_show(treemap):
    """An empty treemap is a box of nothing."""
    treemap.set_breakdown({})
    assert not treemap.isVisible()
    assert treemap.legend_rows() == []


def test_it_appears_once_there_is_something(treemap, qtbot):
    treemap.set_breakdown({Category.VIDEO: 4_000_000_000,
                           Category.TEXT: 40_000_000})
    assert treemap.legend_rows()


def test_every_block_is_named_in_the_legend(treemap):
    """The colour is never the only carrier - the same rule the results bars
    follow."""
    treemap.set_breakdown({Category.VIDEO: 700, Category.IMAGE: 200,
                           Category.TEXT: 100})
    labels = [row[0] for row in treemap.legend_rows()]
    assert "video" in labels and "image" in labels and "text" in labels


def test_the_legend_carries_share_and_size_in_words(treemap):
    treemap.set_breakdown({Category.VIDEO: 750, Category.TEXT: 250})
    rows = dict((r[0], (r[1], r[2])) for r in treemap.legend_rows())
    assert rows["video"][0] == "75%"
    assert "B" in rows["video"][1]


def test_the_biggest_category_comes_first(treemap):
    treemap.set_breakdown({Category.TEXT: 100, Category.VIDEO: 900})
    assert treemap.legend_rows()[0][0] == "video"


def test_slivers_are_collapsed_rather_than_drawn_unlabelled(treemap):
    """Forty unlabellable slivers is a texture, not an answer."""
    breakdown = {Category.VIDEO: 10_000}
    for i, cat in enumerate([Category.TEXT, Category.IMAGE, Category.AUDIO,
                             Category.EXECUTABLE, Category.BINARY]):
        breakdown[cat] = 5      # each far below the 2% floor
    treemap.set_breakdown(breakdown)
    labels = [row[0] for row in treemap.legend_rows()]
    assert "other" in labels
    assert len(labels) < len(breakdown)


def test_the_whole_thing_is_available_as_a_sentence(treemap):
    """What a screen reader gets, and proof the picture is never the only
    copy of the information."""
    treemap.set_breakdown({Category.VIDEO: 750, Category.TEXT: 250})
    text = treemap.summary()
    assert "video" in text and "75%" in text
    assert treemap.accessibleDescription() == text


def test_it_paints_without_raising(treemap, qtbot):
    """squarify is doing real geometry on real numbers; a division by zero in
    a paintEvent takes the window with it."""
    treemap.set_breakdown({Category.VIDEO: 1, Category.TEXT: 1_000_000_000})
    treemap.resize(400, 160)
    treemap.show()
    qtbot.waitExposed(treemap)
    treemap.grab()          # forces a real paint


def test_a_single_category_is_fine(treemap, qtbot):
    treemap.set_breakdown({Category.VIDEO: 500})
    treemap.resize(300, 120)
    treemap.show()
    qtbot.waitExposed(treemap)
    treemap.grab()
    assert treemap.legend_rows()[0][1] == "100%"


def test_zero_sized_categories_are_ignored(treemap):
    treemap.set_breakdown({Category.VIDEO: 0, Category.TEXT: 100})
    assert [r[0] for r in treemap.legend_rows()] == ["text"]


# -- B23: one block says nothing ---------------------------------------------------

def test_a_single_category_is_not_drawn_as_one_huge_block(treemap, qtbot):
    """With one category the treemap was a box filling the Details panel and
    saying "text 100%", which the headline and the legend already say. It stays
    hidden; its legend rows and its sentence are still there."""
    treemap.set_breakdown({Category.TEXT: 500})
    assert not treemap.isVisibleTo(treemap.parent() or treemap)
    assert treemap.minimumHeight() == 0
    assert treemap.legend_rows()[0][:2] == ("text", "100%")
    assert "text 100%" in treemap.summary()


def test_a_folder_that_is_all_one_thing_bar_slivers_is_not_drawn_either(treemap):
    treemap.set_breakdown({Category.TEXT: 990_000, Category.IMAGE: 10_000})
    assert not treemap.isVisibleTo(treemap.parent() or treemap)
    assert len(treemap.legend_rows()) == 2


def test_two_real_categories_are_still_drawn(treemap):
    treemap.set_breakdown({Category.VIDEO: 600, Category.TEXT: 400})
    assert treemap.isVisibleTo(treemap.parent() or treemap)
    assert treemap.minimumHeight() == 120
