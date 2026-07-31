"""All four profiles side by side, before anything is compressed (J3).

The preset cards say what each profile *does*; this says what each one will
*cost on this input*. That is the difference between a choice and a guess, and
it is the whole reason Phase J exists: on a real 721 MB corpus Extreme cost 2.7x
Normal's time for 0.17 extra percentage points, and until now nothing told the
user that until after they had waited.

Rows are clickable - seeing that Normal is 2.7x quicker is only useful if
choosing it is one click away.

Layout note: each row owns its own cells and every row shares one set of column
stretch factors with the header. The obvious alternative - one QGridLayout with
a highlight frame spanning each row - puts the cells and the frame in the same
grid cells as siblings, which makes hit-testing depend on stacking order. Not
worth the fragility for five columns.

Numbers arrive pre-formatted from ``gui.suggest.profile_comparison`` - no
estimation, no rounding and no prose decisions live in this file.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from excmp.planner import Profile

from ..suggest import ComparisonRow, comparison_caption
from ..theme import repolish

# (header, stretch). Shared by the header strip and every row, which is what
# keeps the columns lined up without a grid.
_COLUMNS: tuple[tuple[str, int], ...] = (
    ("Profile", 3),
    ("What runs", 3),
    ("Estimated size", 3),
    ("Saved", 1),
    ("Estimated time", 3),
)


def _cell(text: str, sub: str = "", parent: QWidget | None = None,
          bold: bool = False, tone: str = "") -> QWidget:
    """A two-line cell: the value, and underneath it the range or the caveat."""
    holder = QWidget(parent)
    holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(1)

    main = QLabel(text, holder)
    main.setWordWrap(True)
    if bold:
        main.setStyleSheet("font-weight: 600;")
    if tone:
        main.setProperty("tone", tone)
        repolish(main)
    box.addWidget(main)

    if sub:
        note = QLabel(sub, holder)
        note.setObjectName("Subtitle")
        note.setWordWrap(True)
        box.addWidget(note)
    holder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return holder


class ProfileRow(QFrame):
    """One profile's estimate. Clickable and keyboard-reachable, because the
    point of showing a cheaper option is to make picking it trivial."""

    clicked = Signal(object)   # Profile

    def __init__(self, row: ComparisonRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = row.profile
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if row.recommended:
            self.setProperty("tone", "accent")
            repolish(self)

        stack = QVBoxLayout(self)
        stack.setContentsMargins(12, 10, 12, 10)
        stack.setSpacing(4)

        values = QWidget(self)
        values.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        line = QHBoxLayout(values)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(14)

        name = self.tr("%s (suggested)") % row.title if row.recommended else row.title
        cells = (
            _cell(name, "", values, bold=True,
                  tone="ok" if row.recommended else row.tone),
            _cell(row.chain, "", values, tone="warn" if row.caveat else ""),
            _cell(row.size_text, row.size_range, values),
            _cell(row.saved_text, "", values),
            _cell(row.time_text, row.time_range, values,
                  tone="warn" if row.note else ""),
        )
        for cell, (_header, stretch) in zip(cells, _COLUMNS):
            line.addWidget(cell, stretch)
        stack.addWidget(values)

        # All the prose goes on its own full-width line, never inside a column:
        # the cells hold short values only. A row can be both recommended *and*
        # carrying a conditional warning - that is the honest state for a Precomp
        # chain - so both are shown. Wrapping either into a 110px cell made the
        # row 600px tall.
        detail = " ".join(part for part in (row.reason, row.note, row.caveat) if part)
        if detail:
            prose = QLabel(detail, self)
            prose.setObjectName("Subtitle")
            prose.setWordWrap(True)
            prose.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            if row.note and not row.recommended:
                prose.setProperty("tone", "warn")
                repolish(prose)
            stack.addWidget(prose)

        # One accessible sentence per row - a screen reader should not have to
        # stitch five cells together to learn what the row says.
        # No "about" in the template: size_text already says whether the figure
        # is an estimate or a ceiling, and "about at most" reads like a shrug.
        spoken = self.tr("%s: %s, %s, saves %s, takes %s") % (
            row.title, row.chain, row.size_text, row.saved_text, row.time_text)
        if row.note:
            spoken += " " + row.note
        if row.recommended and row.reason:
            spoken += " " + self.tr("Suggested: %s") % row.reason
        self.setAccessibleName(spoken)
        self.setAccessibleDescription(spoken)
        self.setToolTip(row.reason or row.note or row.caveat)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.profile)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.profile)
            return
        super().keyPressEvent(event)


class CompareTable(QFrame):
    """The estimates panel. Hidden until there is something to estimate."""

    profileChosen = Signal(object)   # Profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAccessibleName(self.tr("Estimated size and time per profile"))

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(16, 14, 16, 14)
        self._column.setSpacing(8)

        title = QLabel(self.tr("Before you start"), self)
        title.setObjectName("Title")
        self._column.addWidget(title)

        self._caption = QLabel("", self)
        self._caption.setObjectName("Subtitle")
        self._caption.setWordWrap(True)
        self._column.addWidget(self._caption)

        head = QWidget(self)
        head_line = QHBoxLayout(head)
        head_line.setContentsMargins(12, 0, 12, 0)
        head_line.setSpacing(14)
        for header, stretch in _COLUMNS:
            label = QLabel(self.tr(header), head)
            label.setObjectName("Muted")
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            head_line.addWidget(label, stretch)
        self._column.addWidget(head)

        self._rows: list[ProfileRow] = []
        self._footnote = QLabel(
            self.tr("Measured from samples of your files, not from a lookup table. "
                    "The ranges are the honest answer — the exact ratio is only "
                    "known once the data has been through the codec."), self)
        self._footnote.setObjectName("Subtitle")
        self._footnote.setWordWrap(True)
        self._column.addWidget(self._footnote)

        self.setVisible(False)

    # -- population --------------------------------------------------------
    def set_rows(self, rows: list[ComparisonRow]) -> None:
        self._drop_rows()
        if not rows:
            self.setVisible(False)
            return

        self._caption.setText(comparison_caption(rows))
        footnote_at = self._column.indexOf(self._footnote)
        for offset, row in enumerate(rows):
            widget = ProfileRow(row, self)
            widget.clicked.connect(self.profileChosen.emit)
            self._column.insertWidget(footnote_at + offset, widget)
            self._rows.append(widget)
        self.setVisible(True)

    def rows(self) -> list[ProfileRow]:
        """Exposed for the GUI tests and the screenshot script."""
        return list(self._rows)

    def _drop_rows(self) -> None:
        for widget in self._rows:
            self._column.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._rows.clear()

    def clear(self) -> None:
        self._drop_rows()
        self._caption.setText("")
        self.setVisible(False)
