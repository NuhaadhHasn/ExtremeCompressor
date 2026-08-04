"""The profile chooser: presets and their measured estimates, ONE widget (W1-13).

The window used to render the same four-way decision twice — a row of preset
cards with blurbs stacked directly above a table whose rows repeated the same
presets with better, measured data. That cost 400-500px of the ~430px that a
150%-scaled 1366x768 laptop has for the whole page, and produced three
competing "Suggested" assertions. The merge keeps both halves' contracts:

- selection (was PresetSelector): ``current_profile()``, ``select()``,
  ``set_tool_availability()``, ``set_recommendation()``, ``profileChanged``,
  and a ``cards`` mapping for the window's tab order;
- estimates (was CompareTable): ``set_rows()``, ``rows()``, ``profileChosen``,
  exactly one accent row, and the one-sentence accessible name per row that
  carries the reason AND the caveat — pinned by tests/test_gui_compare.py.

Before any files are dropped the chooser shows the four profiles with their
honest one-line blurbs and missing-tool notes ("estimates appear after you add
files") — it never blanks, because it is now the only place a profile can be
picked. Numbers arrive pre-formatted from ``gui.suggest.profile_comparison``;
no estimation, rounding or prose decisions live in this file. Selection is
carried by text (a filled/empty radio glyph), never by colour alone.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from excmp.planner import Profile
from excmp.tools import ToolInfo

from ..suggest import ComparisonRow, comparison_caption
from ..theme import CARD_MARGINS, GAP_INTRA, repolish

# (header, stretch). Shared by the header strip and every row, which is what
# keeps the columns lined up without a grid.
_COLUMNS: tuple[tuple[str, int], ...] = (
    ("Profile", 3),
    ("What runs", 3),
    ("Estimated size", 3),
    ("Saved", 2),      # 1 clipped "51% or better" - the honesty wording
    ("Estimated time", 3),
)

# U+25CF / U+25CB - in every Windows UI font, so never tofu.
_RADIO_ON, _RADIO_OFF = "●", "○"


def _cell(text: str, sub: str = "", parent: QWidget | None = None,
          bold: bool = False, tone: str = "") -> QWidget:
    """A two-line cell: the value, and underneath it the range or the caveat."""
    holder = QWidget(parent)
    holder.setObjectName("Plain")
    holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(1)

    # No wordWrap on cells: the values are short, and a wrapping QLabel
    # reports a minimum height that assumes wrapping at minimum width -
    # QScrollArea sizes the page by MINIMUM hint, so four rows of wrapped
    # labels manufactured a scrollbar the real layout never needed. Long text
    # clips at its column edge (the holder's Ignored width policy).
    main = QLabel(text, holder)
    if bold:
        main.setStyleSheet("font-weight: 600;")
    if tone:
        main.setProperty("tone", tone)
        repolish(main)
    box.addWidget(main)

    if sub:
        note = QLabel(sub, holder)
        note.setObjectName("Subtitle")
        box.addWidget(note)
    holder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return holder


class ProfileRow(QFrame):
    """One profile: radio selection plus its estimate (or its blurb, before
    analysis). Clickable and keyboard-reachable — seeing that a cheaper
    profile wins is only useful if picking it is one press away."""

    clicked = Signal(object)   # Profile

    def __init__(self, row: ComparisonRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = row.profile
        self._title_text = row.title
        self._selected = False
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if row.recommended:
            self.setProperty("tone", "accent")
            repolish(self)

        stack = QVBoxLayout(self)
        stack.setContentsMargins(12, 8, 12, 8)
        stack.setSpacing(4)

        values = QWidget(self)
        values.setObjectName("Plain")
        values.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        line = QHBoxLayout(values)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(14)

        name = self.tr("%s (suggested)") % row.title if row.recommended else row.title
        self._name = QLabel(f"{_RADIO_OFF}  {name}", values)
        self._name.setStyleSheet("font-weight: 600;")
        if row.recommended:
            self._name.setProperty("tone", "ok")
            repolish(self._name)
        name_holder = QWidget(values)
        name_holder.setObjectName("Plain")
        nbox = QVBoxLayout(name_holder)
        nbox.setContentsMargins(0, 0, 0, 0)
        nbox.addWidget(self._name)
        name_holder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)

        if row.size_text:
            cells = (
                name_holder,
                _cell(row.chain, row.caveat, values, tone="warn" if row.caveat else ""),
                _cell(row.size_text, row.size_range, values),
                _cell(row.saved_text, "", values),
                _cell(row.time_text, row.time_range, values,
                      tone="warn" if row.note else ""),
            )
            for cell, (_header, stretch) in zip(cells, _COLUMNS):
                line.addWidget(cell, stretch)
        else:
            # Placeholder mode (before analysis): no numbers exist, so the
            # blurb spans their columns on ONE line - four wrapped blurbs used
            # to cost the empty state 190px it does not have at 125% scaling.
            line.addWidget(name_holder, _COLUMNS[0][1])
            blurb = _cell(row.chain, row.caveat, values,
                          tone="warn" if row.caveat else "")
            line.addWidget(blurb, sum(stretch for _h, stretch in _COLUMNS[1:]))
        stack.addWidget(values)

        # The warning goes on its own full-width line, never inside a column -
        # wrapping prose into a 110px cell once made a row 600px tall. A row can
        # be both recommended AND conditionally warned; both must show.
        if row.note:
            prose = QLabel(row.note, self)
            prose.setObjectName("Subtitle")
            prose.setWordWrap(True)
            prose.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            prose.setProperty("tone", "warn")
            repolish(prose)
            stack.addWidget(prose)

        # One accessible sentence per row - a screen reader should not have to
        # stitch five cells together to learn what the row says.
        if row.size_text:
            spoken = self.tr("%s: %s, %s, saves %s, takes %s") % (
                row.title, row.chain, row.size_text, row.saved_text, row.time_text)
        else:
            spoken = f"{row.title}: {row.chain}"
            if row.caveat:
                spoken += " " + row.caveat
        if row.note:
            spoken += " " + row.note
        if row.recommended and row.reason:
            spoken += " " + self.tr("Suggested: %s") % row.reason
        self._spoken = spoken
        self.setAccessibleName(spoken)
        self.setAccessibleDescription(spoken)
        self.setToolTip(row.reason or row.note or row.caveat)

    # -- selection -----------------------------------------------------------
    def set_selected(self, selected: bool) -> None:
        """Radio state, carried by the glyph and the spoken text - the border
        colour is the second signal, never the only one."""
        self._selected = selected
        glyph = _RADIO_ON if selected else _RADIO_OFF
        base = self._name.text().split("  ", 1)[1]
        self._name.setText(f"{glyph}  {base}")
        self.setProperty("selected", "true" if selected else "false")
        repolish(self)
        prefix = self.tr("Selected. ") if selected else ""
        self.setAccessibleName(prefix + self._spoken)

    def is_selected(self) -> bool:
        return self._selected

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
    """The chooser panel. Always visible; the estimate columns fill in once
    analysis has run and revert to blurbs when the input is cleared."""

    profileChosen = Signal(object)    # Profile - any click on a row
    profileChanged = Signal(object)   # Profile - selection actually moved
    rowsRebuilt = Signal()            # rows are NEW widgets - re-apply tab order

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAccessibleName(self.tr("Choose a profile — estimated size and "
                                       "time for each"))
        self._current = Profile.NORMAL
        self._tools: dict[str, ToolInfo | None] = {}
        self._estimated = False

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(*CARD_MARGINS)
        self._column.setSpacing(GAP_INTRA)

        title = QLabel(self.tr("Pick a profile"), self)
        title.setObjectName("Title")
        self._column.addWidget(title)

        self._caption = QLabel("", self)
        self._caption.setObjectName("Subtitle")
        self._caption.setWordWrap(True)
        self._column.addWidget(self._caption)

        self._head = QWidget(self)
        self._head.setObjectName("Plain")
        head_line = QHBoxLayout(self._head)
        head_line.setContentsMargins(12, 0, 12, 0)
        head_line.setSpacing(14)
        for header, stretch in _COLUMNS:
            label = QLabel(self.tr(header), self._head)
            label.setObjectName("Muted")
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            head_line.addWidget(label, stretch)
        self._column.addWidget(self._head)

        self._rows: list[ProfileRow] = []
        self._footnote = QLabel(
            self.tr("Measured from samples of your files, not from a lookup table. "
                    "The ranges are the honest answer — the exact ratio is only "
                    "known once the data has been through the codec."), self)
        self._footnote.setObjectName("Subtitle")
        self._footnote.setWordWrap(True)
        self._column.addWidget(self._footnote)

        self.select(Profile.NORMAL)
        self._show_placeholders()

    # -- selection API (was PresetSelector) -----------------------------------
    def current_profile(self) -> Profile:
        return self._current

    def select(self, profile: Profile, emit: bool = False) -> None:
        changed = profile is not self._current
        self._current = profile
        for row in self._rows:
            row.set_selected(row.profile is profile)
        if emit and changed:
            self.profileChanged.emit(profile)

    def set_tool_availability(self, tools: dict[str, ToolInfo | None]) -> None:
        """Say up front what a preset will really do on this machine."""
        self._tools = dict(tools)
        if not self._estimated:
            self._show_placeholders()

    def set_recommendation(self, profile: Profile, reason: str) -> None:
        # The recommendation badge itself rides in on set_rows(); this hop
        # exists so the analysis handler can move the selection onto it —
        # emitting, because the plan shown was made against the OLD selection.
        self.select(profile, emit=True)

    @property
    def cards(self) -> dict[Profile, ProfileRow]:
        """Compat for the window's explicit tab order."""
        return {row.profile: row for row in self._rows}

    # -- population -----------------------------------------------------------
    def set_rows(self, rows: list[ComparisonRow]) -> None:
        if not rows:
            self._estimated = False
            self._show_placeholders()
            return
        self._estimated = True
        self._caption.setText(comparison_caption(rows))
        self._rebuild(rows)

    def rows(self) -> list[ProfileRow]:
        """The estimate rows — empty while the chooser shows placeholders, so
        tests can tell the two states apart."""
        return list(self._rows) if self._estimated else []

    def clear(self) -> None:
        """Back to the pre-analysis blurbs. The chooser never disappears — it
        is the only place a profile can be picked."""
        self._estimated = False
        self._show_placeholders()

    def _show_placeholders(self) -> None:
        from .preset_cards import PRESETS   # deferred: avoids an import cycle

        self._caption.setText(
            self.tr("Estimates for your files appear here after you add them."))
        placeholder_rows = []
        for profile, glyph, title, blurb, needed in PRESETS:
            missing = [n for n in needed if self._tools.get(n) is None]
            caveat = (self.tr("missing: %s") % ", ".join(missing)) if missing else ""
            placeholder_rows.append(ComparisonRow(
                profile=profile, title=f"{glyph} {title}", chain=blurb,
                size_text="", size_range="", saved_text="",
                time_text="", time_range="", caveat=caveat,
            ))
        self._rebuild(placeholder_rows)

    def _rebuild(self, rows: list[ComparisonRow]) -> None:
        for widget in self._rows:
            self._column.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._rows.clear()

        footnote_at = self._column.indexOf(self._footnote)
        for offset, row in enumerate(rows):
            widget = ProfileRow(row, self)
            widget.clicked.connect(self._on_row_clicked)
            self._column.insertWidget(footnote_at + offset, widget)
            self._rows.append(widget)
        self._footnote.setVisible(self._estimated)
        # Column headers describe the estimate columns; in placeholder mode
        # those show nothing, so the header row is pure height.
        self._head.setVisible(self._estimated)
        for row_widget in self._rows:
            row_widget.set_selected(row_widget.profile is self._current)
        self.setVisible(True)
        # Every rebuild deletes the old row widgets, which severs any explicit
        # tab order routed through them - the window re-applies it on this.
        self.rowsRebuilt.emit()

    def _on_row_clicked(self, profile: object) -> None:
        if isinstance(profile, Profile):
            self.profileChosen.emit(profile)
            self.select(profile, emit=True)
