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

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QToolButton, QWidget)

from excmp.planner import Profile

from excmp.ram import (MIB, dict_choices as _dict_choices, fmt_dict,
                       lzma2_compress_ram, lzma2_decompress_ram)

from ..format import fmt_size
from ..theme import CARD_MARGINS


def _parse_dict(text: str) -> int:
    """"256m" -> bytes. The inverse of excmp.ram.fmt_dict."""
    text = text.strip().lower()
    unit = text[-1:]
    number = int(text[:-1] or 0)
    return number * (1 << 30) if unit == "g" else number * MIB


# (profile, glyph, title, honest one-liner, tools it wants)
#
# W2-5: `glyph` is retained as the accessible-text fallback and for the CLI,
# but the GUI no longer renders it - gui/icons.py paints a theme-tinted Fluent
# SVG instead. Emoji rendered as Windows 10's 2016 flat set beside Windows
# 11's Fluent set, could not follow the theme, and made a screen reader say
# "high voltage Fast".
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
        self.threads.setSpecialValueText(self.tr("auto (%d available)") % cores)
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

        # The level/dictionary knobs (research/23 section 5). Both default to
        # "profile decides" so the common path is unchanged; the dictionary
        # list is capped by B9's RAM rule, because a choice the machine cannot
        # run is not a choice.
        self.level = QSpinBox(self)
        self.level.setRange(0, 9)
        self.level.setValue(0)
        self.level.setSpecialValueText(self.tr("profile default"))
        self.level.setAccessibleName(self.tr("Compression level"))
        self.level.setToolTip(self.tr(
            "Higher is smaller and slower. The profile already picks a sane "
            "one; this overrides it for this job only."))

        self.dict_size = QComboBox(self)
        self.dict_size.addItem(self.tr("profile default"), "")
        for size in _dict_choices():
            self.dict_size.addItem(fmt_dict(size), fmt_dict(size))
        self.dict_size.setAccessibleName(self.tr("LZMA2 dictionary size"))
        self.dict_size.setToolTip(self.tr(
            "Bigger finds matches further apart, and costs roughly 13x its "
            "own size in RAM while compressing. The list stops where this "
            "machine would run out."))
        self.dict_size.currentIndexChanged.connect(self._show_ram)

        self.params = QLineEdit("", self)
        self.params.setPlaceholderText(self.tr("extra 7-Zip switches, e.g. -mqs"))
        self.params.setAccessibleName(self.tr("Extra parameters"))
        self.params.setToolTip(self.tr(
            "Method switches only. -p, -o, -w and @listfile are refused: they "
            "would move the output or put a password in the log, and the "
            "verified publish depends on knowing where the file went."))
        self.params.textChanged.connect(self._show_ram)

        self.ram_note = QLabel("", self)
        self.ram_note.setObjectName("Subtitle")
        self.ram_note.setWordWrap(True)

        self.output_dir = QLineEdit("", self)
        self.output_dir.setPlaceholderText(self.tr("next to the first input"))
        self.output_dir.setAccessibleName(self.tr("Output folder"))
        out_browse = QPushButton(self.tr("Browse…"), self)
        out_browse.setAccessibleDescription(self.tr("Choose the output folder"))
        out_browse.clicked.connect(self._pick_output)

        # Notifications and the tray moved to Settings in wave 3c. Advanced is
        # for *per-job overrides* - threads, temp folder, where this archive
        # goes. "Do you want a toast when jobs finish" is an app preference and
        # was being asked in two places, only one of which was remembered.

        grid.addWidget(QLabel(self.tr("Threads"), self), 0, 0)
        grid.addWidget(self.threads, 0, 1, 1, 2)
        grid.addWidget(QLabel(self.tr("Temp folder"), self), 1, 0)
        grid.addWidget(self.temp_dir, 1, 1)
        grid.addWidget(temp_browse, 1, 2)
        grid.addWidget(QLabel(self.tr("Output folder"), self), 2, 0)
        grid.addWidget(self.output_dir, 2, 1)
        grid.addWidget(out_browse, 2, 2)
        grid.addWidget(QLabel(self.tr("Level"), self), 3, 0)
        grid.addWidget(self.level, 3, 1, 1, 2)
        grid.addWidget(QLabel(self.tr("Dictionary"), self), 4, 0)
        grid.addWidget(self.dict_size, 4, 1, 1, 2)
        grid.addWidget(QLabel(self.tr("Parameters"), self), 5, 0)
        grid.addWidget(self.params, 5, 1, 1, 2)
        grid.addWidget(self.ram_note, 6, 1, 1, 2)
        grid.setColumnStretch(1, 1)

    def _show_ram(self) -> None:
        """Say what the current dictionary will cost before the job starts."""
        chosen = self.dict_size.currentData() or ""
        if not chosen:
            self.ram_note.setText("")
            return
        size = _parse_dict(chosen)
        threads = self.threads.value() or (os.cpu_count() or 2)
        self.ram_note.setText(self.tr(
            "About %s of memory while compressing, %s to extract.")
            % (fmt_size(lzma2_compress_ram(size, threads)),
               fmt_size(lzma2_decompress_ram(size))))

    def stage_options(self):
        """The engine's StageOptions for this panel, or raise ValueError with
        a reason the Parameters line can show."""
        from excmp.engine import StageOptions
        from excmp.ram import parse_extra_args

        return StageOptions(
            level=self.level.value() or None,
            dict_size=self.dict_size.currentData() or None,
            extra_args=tuple(parse_extra_args(self.params.text())),
        )

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
