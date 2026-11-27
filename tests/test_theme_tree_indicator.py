"""The tick boxes inside a list (the Restore tab's "What's inside") are styled like every other check box.

Only ``QCheckBox`` was styled; a tick box in a tree fell back to the platform's drawing, which on the dark theme was a dark
square on a dark row, almost invisible (seen when the Restore list was rendered for the drag-out work).
"""

from __future__ import annotations

import re

from gui import theme


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} is not styled"
    return m.group(1)


def test_tree_tick_boxes_have_a_visible_border_and_fill_in_both_themes():
    for name in ("dark", "light"):
        css, tok = theme.qss(name), theme.tokens(name)
        plain = _rule(css, "QTreeView::indicator")
        assert tok["border_hi"] in plain and tok["surface2"] in plain
        ticked = _rule(css, "QTreeView::indicator:checked")
        assert tok["accent"] in ticked


def test_they_match_the_check_box_rule():
    css = theme.qss("dark")
    box = _rule(css, "QCheckBox::indicator")
    tree = _rule(css, "QTreeView::indicator")
    for part in ("width: 16px", "height: 16px", "border-radius: 4px"):
        assert part in box and part in tree
