"""I10 — Ctrl+K: every action in the app, one search box.

PeaZip's F12 picker and its Options search field are both fed by a single
caption-to-action dispatcher (research/17 §6), which is the right shape: build
the registry once and every surface that wants to find an action gets it free.
`MainWindow._build_actions` already *is* that registry — it was written as the
seed for this — so the palette is a filter over it rather than a second list
that can drift.

Filtering is a subsequence match, not a substring one: typing `oa` should find
"Open archive", which is what makes a palette faster than a menu. Ranking
prefers a prefix hit, then an earlier match, then a shorter caption, so the
obvious answer for one letter is the one people expect.

Inline, like everything else here. It is a frameless popup positioned over the
window rather than a modal dialogue - Escape closes it and the window
underneath is never blocked.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (QFrame, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)


def score(query: str, caption: str) -> tuple | None:
    """How well ``caption`` matches ``query``, or None for no match.

    Subsequence rather than substring: "oa" finds "Open archive", which is the
    whole reason to type instead of pointing. Lower sorts better.
    """
    needle, hay = query.strip().lower(), caption.lower()
    if not needle:
        return (0, 0, len(caption))
    position, first = 0, None
    for char in needle:
        found = hay.find(char, position)
        if found < 0:
            return None
        if first is None:
            first = found
        position = found + 1
    # A prefix hit beats a scattered one; then an earlier start; then the
    # shorter caption, because "Add files" should beat "Add folder to queue"
    # for "add".
    return (0 if hay.startswith(needle) else 1, first or 0, len(caption))


def rank(query: str, actions: dict[str, QAction]) -> list[tuple[str, QAction]]:
    """The matching actions, best first. Disabled ones are left out: offering
    something that cannot run is worse than not offering it."""
    scored = []
    for key, action in actions.items():
        if not action.isEnabled():
            continue
        caption = action.text().replace("&", "")
        result = score(query, caption)
        if result is not None:
            scored.append((result, key, action))
    scored.sort(key=lambda row: row[0])
    return [(key, action) for _s, key, action in scored]


class CommandPalette(QFrame):
    """A search box over the window's own action registry."""

    def __init__(self, actions: dict[str, QAction],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions = actions
        self.setObjectName("Card")
        self.setWindowFlag(Qt.WindowType.Popup, True)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText(self.tr("Type a command…"))
        self.search.setAccessibleName(self.tr("Command search"))
        self.search.textChanged.connect(self._refilter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget(self)
        self.list.setAccessibleName(self.tr("Matching commands"))
        self.list.itemActivated.connect(lambda _i: self._run())
        layout.addWidget(self.list)

        self.resize(420, 320)
        self._refilter("")

    # -- behaviour ----------------------------------------------------------
    def _refilter(self, query: str) -> None:
        self.list.clear()
        for key, action in rank(query, self._actions):
            item = QListWidgetItem(action.text().replace("&", ""))
            shortcut = action.shortcut().toString()
            if shortcut:
                item.setText(f"{item.text()}\t{shortcut}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        """Arrows move the selection while the cursor stays in the search box,
        which is what makes a palette usable with one hand on the keyboard."""
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run()
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _run(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        action = self._actions.get(key)
        self.close()
        if action is not None and action.isEnabled():
            action.trigger()

    def open_over(self, parent: QWidget) -> None:
        """Centre it on the window and take focus."""
        self.search.clear()
        self._refilter("")
        geometry = parent.geometry()
        self.move(geometry.center().x() - self.width() // 2,
                  geometry.top() + max(40, geometry.height() // 6))
        self.show()
        self.search.setFocus()
