"""Settings (I1) — and the first time this app remembers anything.

Until now exactly one thing survived a relaunch: the window geometry. Threads,
temp folder, theme, notifications — all reset on every launch, which the
roadmap has called "the loudest daily annoyance" for four phases running.

Layout follows CommunityToolkit's `SettingsCard`: a row per setting, icon and
title on the left, the control on the right, a description line underneath
that says what the setting actually *does* rather than restating its own
label. 68px rows, 16px padding.

It is also where the tool inventory lives in full. The status strip elides
that line at narrow widths by design (W2-1 decided job state wins), and this
page is what made eliding acceptable rather than lossy.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from excmp.tools import ToolInfo

from ..theme import CARD_MARGINS, GAP_BLOCK, GAP_INTRA, GUTTER, VGAP


class SettingsRow(QFrame):
    """One setting: title, what it does, and its control."""

    def __init__(self, title: str, description: str, control: QWidget,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        row = QHBoxLayout(self)
        row.setContentsMargins(*CARD_MARGINS)
        row.setSpacing(GAP_BLOCK)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(title, self)
        name.setStyleSheet("font-weight: 600;")
        blurb = QLabel(description, self)
        blurb.setObjectName("Subtitle")
        blurb.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(blurb)
        row.addLayout(text, 1)
        row.addWidget(control, 0)
        # The description is the accessible description, so a screen reader
        # gets the "what does this do" line without hunting for it.
        control.setAccessibleDescription(description)


class SettingsTab(QScrollArea):
    """Every persisted preference, and the tool inventory."""

    themeToggled = Signal()

    def __init__(self, tools: dict[str, ToolInfo | None], default_temp: Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tools = dict(tools)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget(self)
        column = QVBoxLayout(page)
        column.setContentsMargins(GUTTER, VGAP, GUTTER, VGAP)
        column.setSpacing(GAP_INTRA)

        cores = os.cpu_count() or 2
        self.threads = QSpinBox(page)
        self.threads.setRange(0, max(2, cores * 4))
        # os.cpu_count() reports LOGICAL processors: the target machine is a
        # 2-core i7-3540M that reports 4. Saying "4 cores" beside a line about
        # a two-core laptop was a contradiction on screen.
        self.threads.setSpecialValueText(
            self.tr("auto (%d available)") % cores)
        self.threads.setAccessibleName(self.tr("Worker threads"))
        column.addWidget(SettingsRow(
            self.tr("Worker threads"),
            self.tr("0 lets each tool choose. Lower it to keep the machine "
                    "usable during a long job — the compressors will happily "
                    "take every thread you have."),
            self.threads, page))

        temp_row = QWidget(page)
        temp_box = QHBoxLayout(temp_row)
        temp_box.setContentsMargins(0, 0, 0, 0)
        temp_box.setSpacing(GAP_INTRA)
        self.temp_dir = QLineEdit(str(default_temp), temp_row)
        self.temp_dir.setAccessibleName(self.tr("Temporary folder"))
        self.temp_dir.setMinimumWidth(220)
        browse = QPushButton(self.tr("Browse…"), temp_row)
        browse.clicked.connect(self._pick_temp)
        temp_box.addWidget(self.temp_dir)
        temp_box.addWidget(browse)
        column.addWidget(SettingsRow(
            self.tr("Temporary folder"),
            self.tr("Precomp can inflate data 2–5× mid-pipeline, and the "
                    "pre-publish self-test restores the whole archive here. "
                    "Point it at a drive with room."),
            temp_row, page))

        # G6. Opt-in, and remembered: a second file appearing beside every
        # archive is a surprise, and this engine has never written an output
        # nobody asked for.
        self.sidecar_toggle = QCheckBox(page)
        self.sidecar_toggle.setAccessibleName(self.tr("Write a .sha256 file"))
        column.addWidget(SettingsRow(
            self.tr("Write a .sha256 file beside the archive"),
            self.tr("Lets anyone check the archive arrived intact after a "
                    "download or a copy, using sha256sum or QuickSFV — no need "
                    "for this app. Off by default; nothing extra is written "
                    "unless you ask."),
            self.sidecar_toggle, page))

        self.open_after_extract = QCheckBox(page)
        self.open_after_extract.setAccessibleName(
            self.tr("Open the folder after extracting"))
        column.addWidget(SettingsRow(
            self.tr("Open the folder after extracting"),
            self.tr("Shows the restored files in Explorer as soon as a "
                    "restore finishes."),
            self.open_after_extract, page))

        self.notify_toggle = QCheckBox(page)
        self.notify_toggle.setChecked(True)
        self.notify_toggle.setAccessibleName(self.tr("Notify when a job finishes"))
        column.addWidget(SettingsRow(
            self.tr("Notify when a job finishes"),
            self.tr("A desktop notification with an “Open folder” button. "
                    "Long jobs are meant to be walked away from."),
            self.notify_toggle, page))

        self.tray_toggle = QCheckBox(page)
        self.tray_toggle.setAccessibleName(self.tr("Minimize to the tray"))
        column.addWidget(SettingsRow(
            self.tr("Minimize to the system tray while running"),
            self.tr("Keeps a running job out of the taskbar. The queue keeps "
                    "going either way."),
            self.tray_toggle, page))

        self.theme_button = QPushButton(self.tr("Switch theme"), page)
        self.theme_button.clicked.connect(self.themeToggled.emit)
        column.addWidget(SettingsRow(
            self.tr("Appearance"),
            self.tr("Dark and light are both first-class — the token table "
                    "changes, not the stylesheet."),
            self.theme_button, page))

        # The inventory the status strip elides at narrow widths.
        self._tools_label = QLabel("", page)
        self._tools_label.setObjectName("Subtitle")
        self._tools_label.setWordWrap(True)
        tools_card = QFrame(page)
        tools_card.setObjectName("Card")
        tools_box = QVBoxLayout(tools_card)
        tools_box.setContentsMargins(*CARD_MARGINS)
        tools_box.setSpacing(GAP_INTRA)
        heading = QLabel(self.tr("Tools on this machine"), tools_card)
        heading.setStyleSheet("font-weight: 600;")
        tools_box.addWidget(heading)
        tools_box.addWidget(self._tools_label)
        column.addWidget(tools_card)
        self.set_tools(tools)

        column.addStretch(1)
        self.setWidget(page)

    # -- tools ---------------------------------------------------------------
    def set_tools(self, tools: dict[str, ToolInfo | None]) -> None:
        """The full inventory — and what we will actually do with each entry.

        Two qualifiers earn their place here. A **legacy** tool is one we find
        and can still run, but will never choose for a new archive (SREP: not
        OSI-licensed, and it once failed its own restore checksum). Listing it
        bare said the app would use a tool it never will; hiding it would
        leave someone restoring a pre-B11 archive unable to see it was found.
        A tool **below its security floor** gets the CVE named, because "it is
        old" without a reason is not something a user can act on.
        """
        from excmp.tools import LEGACY_ONLY, below_floor, floor_reason

        self._tools = dict(tools)
        stale = {name: (found, needed) for name, found, needed in below_floor(tools)}
        lines = []
        for name, info in sorted(self._tools.items()):
            if info is None:
                lines.append(self.tr("%s — not installed") % name)
                continue
            version = getattr(info, "version", "") or self.tr("version unknown")
            line = f"{name} {version} — {getattr(info, 'path', '')}"
            if name in LEGACY_ONLY:
                line += self.tr("  [legacy: only used to open archives made "
                                "before it was dropped; never used to compress]")
            if name in stale:
                found, needed = stale[name]
                line += self.tr("  [update it: %(found)s is below %(needed)s, "
                                "which fixes %(why)s]") % {
                    "found": found, "needed": needed,
                    "why": floor_reason(name) or self.tr("a known issue")}
            lines.append(line)
        self._tools_label.setText("\n".join(lines))

    def tools_text(self) -> str:
        return self._tools_label.text()

    # -- persistence (I1) ----------------------------------------------------
    _KEYS = {
        "settings/threads": ("threads", int, 0),
        "settings/temp_dir": ("temp_dir", str, ""),
        "settings/sidecar": ("sidecar_toggle", bool, False),
        "settings/open_after_extract": ("open_after_extract", bool, False),
        "settings/notify": ("notify_toggle", bool, True),
        "settings/tray": ("tray_toggle", bool, False),
    }

    @staticmethod
    def _as_bool(value: object, default: bool) -> bool:
        """QSettings INI round-trips booleans as the strings "true"/"false"."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes"}

    def load(self) -> None:
        settings = QSettings()
        for key, (attr, kind, default) in self._KEYS.items():
            raw = settings.value(key)
            widget = getattr(self, attr)
            if kind is bool:
                widget.setChecked(self._as_bool(raw, default))
            elif kind is int:
                try:
                    widget.setValue(int(raw) if raw is not None else default)
                except (TypeError, ValueError):
                    widget.setValue(default)
            elif raw:
                widget.setText(str(raw))

    def save(self) -> None:
        settings = QSettings()
        for key, (attr, kind, _default) in self._KEYS.items():
            widget = getattr(self, attr)
            settings.setValue(key, widget.isChecked() if kind is bool
                              else widget.value() if kind is int
                              else widget.text())

    def _pick_temp(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Temporary folder"), self.temp_dir.text())
        if name:
            self.temp_dir.setText(name)
