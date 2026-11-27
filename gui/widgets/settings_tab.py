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
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from excmp.tools import ToolInfo

from ..theme import CARD_MARGINS, GAP_BLOCK, GAP_INTRA, GUTTER, VGAP


class SettingsRow(QFrame):
    """One setting: title, what it does, and its control. ``status`` is an optional line that goes
    under the description, in the text column where it has the row's width (a state or an error
    put in the control's narrow column wrapped badly and was clipped)."""

    def __init__(self, title: str, description: str, control: QWidget,
                 parent: QWidget | None = None, status: QLabel | None = None) -> None:
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
        if status is not None:
            status.setParent(self)
            text.addWidget(status)
        row.addLayout(text, 1)
        row.addWidget(control, 0)
        # The description is the accessible description, so a screen reader
        # gets the "what does this do" line without hunting for it.
        control.setAccessibleDescription(description)


class SettingsTab(QScrollArea):
    """Every persisted preference, and the tool inventory."""

    themeToggled = Signal()

    def __init__(self, tools: dict[str, ToolInfo | None], default_temp: Path,
                 parent: QWidget | None = None, *, shell=None,
                 shell_supported: bool | None = None, updates=None) -> None:
        super().__init__(parent)
        self._tools = dict(tools)
        # I5: the Explorer menu's backend (excmp.shellmenu), injectable so a test can never write to
        # the real HKCU\Software\Classes; and whether this platform has an Explorer at all.
        from excmp import shellmenu
        self._shell = shell if shell is not None else shellmenu
        self._shell_supported = (sys.platform == "win32" if shell_supported is None
                                 else shell_supported)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        page = QWidget(self)
        column = QVBoxLayout(page)
        column.setContentsMargins(GUTTER, VGAP, GUTTER, VGAP)
        column.setSpacing(GAP_INTRA)

        from excmp.ram import physical_cores
        cores = os.cpu_count() or 2
        self.threads = QSpinBox(page)
        self.threads.setRange(0, max(2, cores * 4))
        # os.cpu_count() reports LOGICAL processors: the target machine is a
        # 2-core i7-3540M that reports 4, and "auto (4 cores)" once sat beside
        # a line calling it a two-core laptop. Auto now gives 7-Zip and
        # zpaqfranz one thread per physical core (Fast's in-process zstd keeps
        # its own default), so the label names physical_cores().
        self.threads.setSpecialValueText(
            self.tr("auto (%d cores)") % physical_cores())
        self.threads.setAccessibleName(self.tr("Worker threads"))
        column.addWidget(SettingsRow(
            self.tr("Worker threads"),
            self.tr("Auto gives 7-Zip and zpaqfranz one thread per physical "
                    "core. Lower it to keep the machine usable during a long "
                    "job."),
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
            self.tr("Work files go here while a job runs. They can be several "
                    "times the size of your files, so choose a drive with free "
                    "space."),
            temp_row, page))

        # G6. Opt-in, and remembered: a second file appearing beside every
        # archive is a surprise, and this engine has never written an output
        # nobody asked for.
        self.sidecar_toggle = QCheckBox(page)
        self.sidecar_toggle.setAccessibleName(self.tr("Write a .sha256 file"))
        column.addWidget(SettingsRow(
            self.tr("Write a .sha256 file beside the archive"),
            self.tr("Lets anyone check the archive arrived intact after a "
                    "download or a copy, without this app. Off by default; "
                    "nothing extra is written unless you ask."),
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

        # E7. A long job must not be cut short by the laptop going to sleep, and an overnight one may end with
        # the PC putting itself away. Both are explained inline; the action only ever follows a clean run.
        self.awake_toggle = QCheckBox(page)
        self.awake_toggle.setAccessibleName(self.tr("Keep the PC awake while a job runs"))
        column.addWidget(SettingsRow(
            self.tr("Keep the PC awake while a job runs"),
            self.tr("Stops Windows sleeping in the middle of a long job (the screen may still turn off). "
                    "Released as soon as the queue is empty."),
            self.awake_toggle, page))

        self.after_combo = QComboBox(page)
        for label, key in ((self.tr("Do nothing"), "nothing"), (self.tr("Sleep"), "sleep"),
                           (self.tr("Hibernate"), "hibernate"), (self.tr("Shut down"), "shutdown")):
            self.after_combo.addItem(label, key)
        self.after_combo.setAccessibleName(self.tr("When the whole queue has finished"))
        column.addWidget(SettingsRow(
            self.tr("When the whole queue has finished"),
            self.tr("Sleep, hibernate or shut down the PC after the last job, so an overnight run can end by "
                    "itself. Only if every job succeeded, after a 60-second countdown you can cancel."),
            self.after_combo, page))

        self.theme_button = QPushButton(self.tr("Switch theme"), page)
        self.theme_button.clicked.connect(self.themeToggled.emit)
        column.addWidget(SettingsRow(
            self.tr("Appearance"),
            self.tr("Switch between dark and light."),
            self.theme_button, page))

        # I5. The switch for the Explorer right-click menu (the CLI and the installer could already
        # add it). Per user, no administrator. No modal dialog - a rule of this UI - so what
        # happened is said inline, under the button.
        self.explorer_button = QPushButton(page)
        self.explorer_button.setAccessibleDescription(self.tr(
            "Adds or removes “Compress with ExtremeCompressor” on files and folders, and "
            "“Extract here” and “Verify archive” on .excmp archives, in the Explorer menu."))
        self.explorer_button.clicked.connect(self._toggle_explorer_menu)
        self.explorer_state = QLabel("", page)
        self.explorer_state.setWordWrap(True)
        self.explorer_state.setStyleSheet("font-weight: 600;")
        self.explorer_row = SettingsRow(
            self.tr("Explorer right-click menu"),
            self.tr("“Compress with ExtremeCompressor” on files and folders; “Extract here” and "
                    "“Verify archive” on .excmp archives. Per user: no administrator needed. "
                    "Windows 11 shows it under “Show more options”."),
            self.explorer_button, page, status=self.explorer_state)
        self.explorer_row.setVisible(self._shell_supported)
        column.addWidget(self.explorer_row)
        self.refresh_explorer_menu()

        # E5. Updates: a daily background look at this project's GitHub releases (opt out here), and
        # a button to look now. Signed releases only (excmp/updater.py); no modal dialog, the state is
        # said inline under the button, and finding one raises the window's banner.
        from ..updatecontroller import UpdateController
        self.updates = updates if updates is not None else UpdateController(self)
        self.update_toggle = QCheckBox(self.tr("Look once a day"), page)
        self.update_toggle.setAccessibleName(self.tr("Look for updates once a day"))
        self.update_button = QPushButton(self.tr("Check for updates"), page)
        self.update_button.clicked.connect(self._update_clicked)
        self.update_state = QLabel(self.tr("Version %s.") % self.updates.current, page)
        self.update_state.setWordWrap(True)
        self.update_state.setTextFormat(Qt.TextFormat.PlainText)      # server text is never markup
        self.update_state.setStyleSheet("font-weight: 600;")
        update_control = QWidget(page)
        update_box = QVBoxLayout(update_control)
        update_box.setContentsMargins(0, 0, 0, 0)
        update_box.setSpacing(GAP_INTRA)
        update_box.addWidget(self.update_button)
        update_box.addWidget(self.update_toggle)
        column.addWidget(SettingsRow(
            self.tr("Updates"),
            self.tr("Looks at this project's GitHub releases and installs a newer version only if it carries the "
                    "owner's signature. It sends nothing but a normal web request."),
            update_control, page, status=self.update_state))
        self.updates.stateChanged.connect(self._refresh_updates)

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

    # -- the Explorer menu (I5) -----------------------------------------------
    def _set_explorer_button(self, text: str) -> None:
        """The button's text is its name for a screen reader too: say what it does, to what."""
        self.explorer_button.setText(text)
        self.explorer_button.setAccessibleName(self.tr("%s the Explorer right-click menu") % text)

    def refresh_explorer_menu(self, message: str | None = None) -> None:
        """Read the registry again and show what is there. ``message`` (a failure) replaces the
        state line, and the button keeps offering whatever is true now."""
        if not self._shell_supported:
            return
        try:
            st = self._shell.status()
        except Exception as exc:                              # noqa: BLE001
            self._set_explorer_button(self.tr("Add"))
            self.explorer_state.setText(message or self.tr("Could not read the menu: %s") % exc)
            return
        if not st.installed and st.found:
            # An install that failed part-way leaves some entries live: not "absent", and Add finishes it.
            self._set_explorer_button(self.tr("Repair"))
            state = self.tr("Partly in the Explorer menu: some entries are missing.")
        elif not st.installed:
            self._set_explorer_button(self.tr("Add"))
            state = self.tr("Not in the Explorer menu.")
        elif st.stale:
            self._set_explorer_button(self.tr("Repair"))
            state = self.tr("On, but it starts a different copy of ExtremeCompressor.")
        else:
            self._set_explorer_button(self.tr("Remove"))
            state = self.tr("On: right-click a file or a folder.")
        self.explorer_state.setText(message or state)

    def _toggle_explorer_menu(self) -> None:
        try:
            st = self._shell.status()
            if st.installed and not st.stale:
                self._shell.uninstall()
            else:
                self._shell.install()
        except Exception as exc:                              # noqa: BLE001
            self.refresh_explorer_menu(self.tr("Could not change it: %s") % exc)
            return
        self.refresh_explorer_menu()

    # -- updates (E5) ----------------------------------------------------------
    def _update_clicked(self) -> None:
        if self.updates.state in ("available", "ready"):
            self.updates.install()
        else:
            self.updates.check()

    def _refresh_updates(self) -> None:
        u = self.updates
        busy = u.state in ("checking", "downloading")
        self.update_button.setEnabled(not busy)
        if u.state == "available" and u.info is not None:
            self.update_button.setText(self.tr("Download and install %s") % u.info.version)
        elif u.state == "ready":
            self.update_button.setText(self.tr("Install now"))
        else:
            self.update_button.setText(self.tr("Check for updates"))
        if u.message or u.state in ("error", "uptodate"):
            self.update_state.setText(u.message or self.tr("Version %s.") % u.current)

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
        from excmp.tools import (IN_PROCESS, IN_PROCESS_WHEEL, LEGACY_ONLY,
                                 below_floor, floor_reason, is_bundled)

        self._tools = dict(tools)
        stale = {name: (found, needed) for name, found, needed in below_floor(tools)}
        lines = []
        for name, info in sorted(self._tools.items()):
            if info is None and name in IN_PROCESS:
                # B10. This codec ships as a wheel, so there is no executable
                # to find and "not installed" was simply false - said about the
                # codec that runs the entire Fast profile. Telling someone to
                # go and install zstd.exe is telling them to fix something
                # that is not broken.
                lines.append(
                    self.tr("%(tool)s — built in, no executable needed "
                            "(in-process via the %(wheel)s wheel)")
                    % {"tool": name,
                       "wheel": IN_PROCESS_WHEEL.get(name, name)})
                continue
            if info is None:
                lines.append(self.tr("%s — not installed") % name)
                continue
            version = getattr(info, "version", "") or self.tr("version unknown")
            line = f"{name} {version} — {getattr(info, 'path', '')}"
            if is_bundled(getattr(info, "path", "")):
                line += self.tr("  [included with the app]")
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
        "settings/update_check": ("update_toggle", bool, True),
        "settings/keep_awake": ("awake_toggle", bool, True),
        "settings/after_queue": ("after_combo", "combo", "nothing"),
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
            elif kind == "combo":
                found = widget.findData(raw if isinstance(raw, str) else default)
                widget.setCurrentIndex(found if found >= 0 else widget.findData(default))
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
                              else widget.currentData() if kind == "combo"
                              else widget.value() if kind is int
                              else widget.text())

    def _pick_temp(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Temporary folder"), self.temp_dir.text())
        if name:
            self.temp_dir.setText(name)
