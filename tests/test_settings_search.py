"""A search box on the Settings page.

Settings has grown to a dozen cards (threads, temp folder, notifications, sleep, the Explorer menu, updates, the tools
list...). A person looking for "sleep" or "tray" should not have to read all of them. The field narrows the cards by what
they say (title and description), every word has to match, and it never brings back a card that is absent on purpose
(the Explorer row on a PC with no Explorer).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from gui.widgets.settings_tab import SettingsRow, SettingsTab            # noqa: E402


class _Shell:
    def status(self):
        from excmp.shellmenu import Status
        return Status(installed=False, stale=False, missing=["x"], found=[])


def _tab(qtbot, windows=True, tools=None):
    tab = SettingsTab(tools or {}, Path("."), shell=_Shell(), shell_supported=windows)
    qtbot.addWidget(tab)
    return tab


def _shown(tab) -> list[str]:
    """Titles of the setting cards that are not hidden (the tools card is reported as 'tools')."""
    out = [c.title for c in tab.findChildren(SettingsRow) if not c.isHidden()]
    if not tab.tools_card.isHidden():
        out.append("tools")
    return out


def test_an_empty_search_shows_every_card(qtbot):
    tab = _tab(qtbot)
    assert tab.search.text() == ""
    assert "Worker threads" in _shown(tab) and "Updates" in _shown(tab) and "tools" in _shown(tab)
    assert tab.search_empty.isHidden()


def test_a_word_narrows_the_cards_to_those_that_say_it(qtbot):
    tab = _tab(qtbot)
    tab.search.setText("sleep")
    shown = _shown(tab)
    assert "Keep the PC awake while a job runs" in shown          # its description says "sleeping"
    assert "When the whole queue has finished" in shown            # the Sleep choice
    assert "Worker threads" not in shown and "Updates" not in shown and "tools" not in shown
    assert tab.search_empty.isHidden()


def test_it_ignores_case_and_every_word_must_match(qtbot):
    tab = _tab(qtbot)
    tab.search.setText("TRAY minimize")
    assert _shown(tab) == ["Minimize to the system tray while running"]
    tab.search.setText("tray temporary")                          # no card says both
    assert _shown(tab) == []


def test_nothing_found_says_so_and_clearing_brings_everything_back(qtbot):
    tab = _tab(qtbot)
    tab.search.setText("zzzz")
    assert _shown(tab) == []
    assert not tab.search_empty.isHidden() and "zzzz" in tab.search_empty.text()
    tab.search.clear()
    assert tab.search_empty.isHidden()
    assert "Worker threads" in _shown(tab) and "tools" in _shown(tab)


def test_a_card_that_is_absent_on_purpose_stays_absent(qtbot):
    tab = _tab(qtbot, windows=False)                                # no Explorer: the menu row is not offered
    assert "Explorer right-click menu" not in _shown(tab)
    tab.search.setText("explorer")
    assert "Explorer right-click menu" not in _shown(tab)
    tab.search.clear()
    assert "Explorer right-click menu" not in _shown(tab)


def test_the_explorer_row_is_found_where_there_is_an_explorer(qtbot):
    tab = _tab(qtbot, windows=True)
    tab.search.setText("explorer")
    assert "Explorer right-click menu" in _shown(tab)


def test_the_tools_card_is_found_by_a_tool_name(qtbot):
    tab = _tab(qtbot, tools={"precomp": None, "zpaqfranz": None})
    tab.search.setText("precomp")                                   # (zpaqfranz is also named in the threads card)
    assert _shown(tab) == ["tools"]
    tab.search.setText("zpaqfranz")
    assert set(_shown(tab)) == {"Worker threads", "tools"}
    tab.search.setText("tools machine")
    assert _shown(tab) == ["tools"]


def test_the_tools_card_follows_a_changed_tool_list(qtbot):
    tab = _tab(qtbot, tools={})
    tab.search.setText("balrogg")
    assert _shown(tab) == []
    tab.set_tools({"balrogg": None})
    tab.search.setText("balrogg")                                   # the filter reads the card's text as it is now
    assert _shown(tab) == ["tools"]


def test_the_field_has_a_name_for_a_screen_reader(qtbot):
    tab = _tab(qtbot)
    assert tab.search.accessibleName() and tab.search.placeholderText()
    assert tab.search.isClearButtonEnabled()


def test_the_words_on_a_rows_control_are_searched_too(qtbot):
    """A person who types "theme" wants the "Switch theme" button, whose card is titled "Appearance"."""
    tab = _tab(qtbot)
    for word, card in (("theme", "Appearance"), ("browse", "Temporary folder"),
                       ("check for updates", "Updates"), ("look once", "Updates"),
                       ("hibernate", "When the whole queue has finished")):
        tab.search.setText(word)
        assert card in _shown(tab), (word, _shown(tab))


def test_what_is_typed_is_never_read_as_markup(qtbot):
    tab = _tab(qtbot)
    tab.search.setText("<b>x</b>")
    assert tab.search_empty.text().count("<b>x</b>") == 1 and tab.search_empty.textFormat().name == "PlainText"
