"""The preset catalogue + the Advanced expander.

The four-card PresetSelector that used to live here was merged into the
profile chooser (widgets/compare_table.py, W1-13 in research/23): the cards
and the estimate table rendered the same decision twice. What remains is the
catalogue the chooser renders from - honest one-liners, no silent degrading -
and the Advanced panel.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QGridLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox,
                               QToolButton, QWidget)

from excmp.planner import Profile

from ..theme import CARD_MARGINS


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


class AdvancedPanel(QFrame):
    """Progressive disclosure: everything here has a sane default."""

    def __init__(self, default_temp: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setVisible(False)

        grid = QGridLayout(self)
        grid.setContentsMargins(*CARD_MARGINS)
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
