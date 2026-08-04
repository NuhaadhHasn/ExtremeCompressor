"""Preset cards + the Advanced expander.

Four cards instead of a dropdown, because the choice is a real trade-off and
the user deserves to see what they are trading. Each card states its cost in
plain terms, and cards whose tools are missing say what will actually happen
rather than silently degrading at run time.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QToolButton, QVBoxLayout,
                               QWidget)

from excmp.planner import Profile
from excmp.tools import ToolInfo

from ..theme import repolish

# (profile, glyph, title, honest one-liner, tools it wants)
PRESETS: list[tuple[Profile, str, str, str, tuple[str, ...]]] = [
    (Profile.FAST, "⚡", "Fast",
     "Zstandard, single pass. Seconds per gigabyte, modest ratio.", ()),
    (Profile.NORMAL, "⚖️", "Normal",
     "7-Zip LZMA2 at maximum. The sensible everyday choice.", ("7z",)),
    (Profile.EXTREME, "🔥", "Extreme",
     "Precomp → LZMA2. Best ratio; slow, and hungry for temp space.",
     ("7z", "precomp")),
    (Profile.INSANE, "🌙", "Insane",
     "Extreme plus a stronger final codec — an overnight job.",
     ("7z", "precomp", "zpaqfranz")),
]


class PresetCard(QPushButton):
    """A checkable card. Labels are click-transparent so the whole tile is
    one big button - and one single tab stop for keyboard users."""

    def __init__(self, profile: Profile, glyph: str, title: str, blurb: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setObjectName("PresetCard")
        self.setCheckable(True)
        self.setMinimumHeight(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        column = QVBoxLayout(self)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._title = QLabel(f"{glyph}  {title}", self)
        self._title.setObjectName("Title")
        top.addWidget(self._title)
        top.addStretch(1)
        self._badge = QLabel(self.tr("Suggested"), self)
        self._badge.setProperty("tone", "ok")
        self._badge.setVisible(False)
        top.addWidget(self._badge)
        column.addLayout(top)

        self._blurb = QLabel(blurb, self)
        self._blurb.setObjectName("Subtitle")
        self._blurb.setWordWrap(True)
        column.addWidget(self._blurb)

        self._note = QLabel("", self)
        self._note.setObjectName("Subtitle")
        self._note.setWordWrap(True)
        self._note.setVisible(False)
        column.addWidget(self._note)
        column.addStretch(1)

        for label in (self._title, self._blurb, self._note, self._badge):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._base_description = blurb
        self.setAccessibleName(f"{title} preset")
        self.setAccessibleDescription(blurb)

    def set_note(self, note: str, tone: str = "warn") -> None:
        self._note.setText(note)
        self._note.setProperty("tone", tone if note else "")
        self._note.setVisible(bool(note))
        repolish(self._note)
        self.setAccessibleDescription(
            f"{self._base_description} {note}".strip())

    def set_recommended(self, recommended: bool, reason: str = "") -> None:
        self._badge.setVisible(recommended)
        if recommended and reason:
            self.setToolTip(reason)
            self.setAccessibleDescription(
                f"{self._base_description} Suggested: {reason}")
        elif not recommended:
            self.setToolTip("")


class PresetSelector(QWidget):
    """The four cards plus the recommendation line above them."""

    profileChanged = Signal(object)   # Profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        self._reason = QLabel("", self)
        self._reason.setObjectName("Subtitle")
        self._reason.setWordWrap(True)
        self._reason.setVisible(False)
        column.addWidget(self._reason)

        grid = QGridLayout()
        grid.setSpacing(10)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.cards: dict[Profile, PresetCard] = {}
        for index, (profile, glyph, title, blurb, _tools) in enumerate(PRESETS):
            card = PresetCard(profile, glyph, title, blurb, self)
            self._group.addButton(card, index)
            grid.addWidget(card, 0, index)
            self.cards[profile] = card
        column.addLayout(grid)

        self.cards[Profile.NORMAL].setChecked(True)
        self._group.idClicked.connect(self._emit_change)

    def _emit_change(self, index: int) -> None:
        self.profileChanged.emit(PRESETS[index][0])

    def current_profile(self) -> Profile:
        for profile, card in self.cards.items():
            if card.isChecked():
                return profile
        return Profile.NORMAL

    def select(self, profile: Profile, emit: bool = False) -> None:
        card = self.cards.get(profile)
        if card is not None and not card.isChecked():
            card.setChecked(True)
            if emit:
                self.profileChanged.emit(profile)

    def set_tool_availability(self, tools: dict[str, ToolInfo | None]) -> None:
        """Say up front what a preset will really do on this machine."""
        for profile, _glyph, _title, _blurb, needed in PRESETS:
            missing = [name for name in needed if tools.get(name) is None]
            card = self.cards[profile]
            if profile is Profile.INSANE:
                extra = self.tr("zpaqfranz isn't wired up yet — runs the "
                                "Extreme chain today.")
                card.set_note(extra)
                continue
            if missing:
                card.set_note(self.tr("Missing: %s — those stages are skipped.")
                              % ", ".join(missing))
            else:
                card.set_note("")

    def set_recommendation(self, profile: Profile, reason: str) -> None:
        for candidate, card in self.cards.items():
            card.set_recommended(candidate is profile, reason)
        self._reason.setText(self.tr("Suggested: %s") % reason)
        self._reason.setVisible(bool(reason))
        # emit=True matters: the analysis that produced this recommendation
        # was planned against the *previous* profile, so switching cards has
        # to trigger a re-plan or the routing shown would be for the wrong
        # preset.
        self.select(profile, emit=True)


class AdvancedPanel(QFrame):
    """Progressive disclosure: everything here has a sane default."""

    def __init__(self, default_temp: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setVisible(False)

        grid = QGridLayout(self)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        cores = os.cpu_count() or 2
        self.threads = QSpinBox(self)
        self.threads.setRange(0, max(2, cores * 4))
        self.threads.setValue(0)
        self.threads.setSpecialValueText(self.tr("auto (%d cores)") % cores)
        self.threads.setAccessibleName(self.tr("Worker threads"))
        self.threads.setToolTip(self.tr(
            "0 lets each tool pick. Lower it to keep the machine usable "
            "during a long job."))

        self.temp_dir = QLineEdit(str(default_temp), self)
        self.temp_dir.setAccessibleName(self.tr("Temporary directory"))
        self.temp_dir.setToolTip(self.tr(
            "Precomp can inflate data 2–5× mid-pipeline. Point this at a "
            "drive with room."))
        temp_browse = QPushButton(self.tr("Browse…"), self)
        temp_browse.setAccessibleDescription(self.tr("Choose the temporary directory"))
        temp_browse.clicked.connect(self._pick_temp)

        self.output_dir = QLineEdit("", self)
        self.output_dir.setPlaceholderText(self.tr("next to the first input"))
        self.output_dir.setAccessibleName(self.tr("Output folder"))
        out_browse = QPushButton(self.tr("Browse…"), self)
        out_browse.setAccessibleDescription(self.tr("Choose the output folder"))
        out_browse.clicked.connect(self._pick_output)

        self.tray_toggle = QCheckBox(self.tr("Minimize to the system tray while running"), self)
        self.notify_toggle = QCheckBox(self.tr("Show a notification when a job finishes"), self)
        self.notify_toggle.setChecked(True)

        grid.addWidget(QLabel(self.tr("Threads"), self), 0, 0)
        grid.addWidget(self.threads, 0, 1, 1, 2)
        grid.addWidget(QLabel(self.tr("Temp folder"), self), 1, 0)
        grid.addWidget(self.temp_dir, 1, 1)
        grid.addWidget(temp_browse, 1, 2)
        grid.addWidget(QLabel(self.tr("Output folder"), self), 2, 0)
        grid.addWidget(self.output_dir, 2, 1)
        grid.addWidget(out_browse, 2, 2)
        grid.addWidget(self.tray_toggle, 3, 1, 1, 2)
        grid.addWidget(self.notify_toggle, 4, 1, 1, 2)
        grid.setColumnStretch(1, 1)

    def _pick_temp(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Temporary folder"), self.temp_dir.text())
        if name:
            self.temp_dir.setText(name)

    def _pick_output(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Output folder"), self.output_dir.text() or str(Path.home()))
        if name:
            self.output_dir.setText(name)


class AdvancedToggle(QToolButton):
    """The ▸/▾ disclosure control for :class:`AdvancedPanel`."""

    def __init__(self, panel: AdvancedPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panel = panel
        self.setCheckable(True)
        self.setText("▸  " + self.tr("Advanced"))
        self.setAccessibleName(self.tr("Show advanced options"))
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, shown: bool) -> None:
        self._panel.setVisible(shown)
        self.setText(("▾  " if shown else "▸  ") + self.tr("Advanced"))
        self.setAccessibleName(
            self.tr("Hide advanced options") if shown
            else self.tr("Show advanced options"))
