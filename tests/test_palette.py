"""I10 — Ctrl+K over the window's own action registry.

The registry already existed; `_build_actions` was written as the seed for
this. So the palette is a *filter over it*, never a second list - a second
list is one that drifts the first time somebody adds an action and forgets.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from gui.widgets.palette import rank, score


class _FakeAction:
    def __init__(self, text: str, enabled: bool = True, shortcut: str = ""):
        self._text, self._enabled, self._shortcut = text, enabled, shortcut

    def text(self): return self._text
    def isEnabled(self): return self._enabled

    def shortcut(self):
        class _S:
            def __init__(self, v): self._v = v
            def toString(self): return self._v
        return _S(self._shortcut)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_an_exact_word_matches():
    assert score("add", "Add files…") is not None


def test_a_subsequence_matches(): 
    """"oa" finds "Open archive" - the whole reason to type instead of point."""
    assert score("oa", "Open archive (Extract)…") is not None


def test_letters_out_of_order_do_not_match():
    assert score("ao", "Open archive") is None


def test_something_absent_does_not_match():
    assert score("zzz", "Add files") is None


def test_an_empty_query_matches_everything():
    assert score("", "Anything at all") is not None


def test_matching_ignores_case():
    assert score("ADD", "add files") is not None


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def test_a_prefix_beats_a_scattered_match():
    actions = {"a": _FakeAction("Add files"),
               "b": _FakeAction("Clear the pad")}
    assert rank("ad", actions)[0][0] == "a"


def test_the_shorter_caption_wins_a_tie():
    actions = {"long": _FakeAction("Add folder to the queue right now"),
               "short": _FakeAction("Add files")}
    assert rank("add", actions)[0][0] == "short"


def test_a_disabled_action_is_not_offered():
    """Offering something that cannot run is worse than not offering it."""
    actions = {"on": _FakeAction("Compress now"),
               "off": _FakeAction("Compress later", enabled=False)}
    keys = [k for k, _a in rank("compress", actions)]
    assert keys == ["on"]


def test_the_ampersand_from_a_mnemonic_is_not_matched_against():
    actions = {"a": _FakeAction("&Add files")}
    assert rank("add", actions)


# ---------------------------------------------------------------------------
# The real window
# ---------------------------------------------------------------------------

def test_the_palette_opens_over_the_window(qtbot):
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        assert "command-palette" in win.actions
        assert win.actions["command-palette"].shortcut().toString() == "Ctrl+K"
        win._open_palette()
        assert win._palette.isVisible()
        assert win._palette.list.count() > 0, "the palette offered nothing"
        win._palette.close()
    finally:
        win.queue.shutdown()


def test_every_registered_action_is_reachable(qtbot):
    """The property that makes one registry worth having: nothing in the
    window's action list is invisible to the palette."""
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        enabled = {k for k, a in win.actions.items() if a.isEnabled()}
        offered = {k for k, _a in rank("", win.actions)}
        assert enabled == offered
    finally:
        win.queue.shutdown()
