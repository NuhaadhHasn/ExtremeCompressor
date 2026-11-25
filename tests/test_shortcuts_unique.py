"""No two things may claim the same keyboard shortcut.

Found by the user guide: Ctrl+O was bound twice (a QAction "Add files…" and a QShortcut for the standard Open
key, which is also Ctrl+O). Qt answers an ambiguous shortcut by firing neither, so the key did nothing. A key
test with an offscreen platform cannot see that; counting the claims can.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtGui import QAction, QKeySequence, QShortcut      # noqa: E402
from PySide6.QtWidgets import QWidget                            # noqa: E402

from gui.mainwindow import MainWindow                            # noqa: E402


def _claims(window) -> dict[str, list[str]]:
    claims: dict[str, list[str]] = defaultdict(list)
    for action in window.findChildren(QAction):
        for seq in action.shortcuts():
            if not seq.isEmpty():
                claims[seq.toString(QKeySequence.SequenceFormat.PortableText)].append(f"action:{action.text()}")
    for sc in window.findChildren(QShortcut):
        seq = sc.key()
        if not seq.isEmpty():
            claims[seq.toString(QKeySequence.SequenceFormat.PortableText)].append(f"shortcut:{sc.objectName() or sc.parent().__class__.__name__}")
    return claims


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    w.queue.shutdown()


def test_every_shortcut_has_exactly_one_owner(window):
    shared = {k: v for k, v in _claims(window).items() if len(v) > 1}
    assert shared == {}, f"these keys are claimed twice, so Qt fires neither: {shared}"


def test_ctrl_o_still_has_an_owner(window):
    assert len(_claims(window).get("Ctrl+O", [])) == 1


def test_every_shortcut_the_hint_line_promises_exists(window):
    """The status hint names Ctrl+O and Ctrl+Shift+O; both must be real."""
    claims = _claims(window)
    assert "Ctrl+O" in claims and "Ctrl+Shift+O" in claims
