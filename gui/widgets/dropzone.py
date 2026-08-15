"""The drop target, and the receipt it turns into.

HandBrake's two most-reported intake bugs are (a) dropping a folder does
nothing and (b) dropping five files keeps one. Both are avoided the same
way: walk *every* URL in the mime data, accept files and directories
alike, and emit the whole list. There is no filtering by extension either -
the analyzer decides what things are, not the file name.

**The intake chip (W2-b).** A 116px "drop files here" panel earns its space
exactly once. After that it is a receipt - "3 items · 1.9 GB" - and a receipt
is one line, which is 80px the 150%-scaled page gets back. It re-expands the
instant a drag enters, because nobody can aim at a 36px strip, and whenever
the list empties.

The chip's item count is also the handle for reviewing what is queued: it
toggles a list with per-row removal (W2-10), collapsed by default so it costs
nothing until asked for.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..format import fmt_size
from ..theme import GAP_INTRA, GAP_TIGHT, repolish


def paths_from_mime(mime) -> list[Path]:
    """Every existing local path in a mime bundle, order preserved.

    Kept as a free function so the drop behaviour can be tested without
    constructing a widget.
    """
    if not mime.hasUrls():
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for url in mime.urls():
        local = url.toLocalFile()
        if not local:
            continue                      # http:// drags, clipboard oddities
        path = Path(local)
        key = str(path).lower()           # Windows paths are case-insensitive
        if key in seen or not path.exists():
            continue
        seen.add(key)
        out.append(path)
    return out


class DropZone(QFrame):
    """Dashed panel that highlights on drag and emits the dropped paths.

    Two states, one widget: the full invitation while empty, and a one-line
    chip once something is pending. ``set_pending()`` drives the switch.
    """

    pathsAdded = Signal(list)     # list[Path] - files *and* folders
    clearRequested = Signal()
    pendingToggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        # No minimum height: the old 150px floor plus the preset cards' twin
        # floor spent 330px of a 432px (150%-scaled) client saying "drop here".
        self.setAccessibleName(self.tr("Drop area for files and folders"))
        self._compact = False
        self._dragging = False

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 2, 16, 2)
        column.setSpacing(GAP_TIGHT)
        self._column = column

        # -- the buttons exist once and move between the two states ---------
        self._buttons = QWidget(self)
        self._buttons.setObjectName("Plain")
        row = QHBoxLayout(self._buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_INTRA)
        self.files_button = QPushButton(self.tr("Add files…"), self._buttons)
        self.folder_button = QPushButton(self.tr("Add folder…"), self._buttons)
        self.clear_button = QPushButton(self.tr("Clear"), self._buttons)
        self.files_button.setAccessibleDescription(
            self.tr("Choose one or more files to add to the queue"))
        self.folder_button.setAccessibleDescription(
            self.tr("Choose a folder to add to the queue"))
        self.clear_button.setAccessibleDescription(
            self.tr("Remove everything from the pending list"))
        self.files_button.clicked.connect(self._pick_files)
        self.folder_button.clicked.connect(self._pick_folder)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        for button in (self.files_button, self.folder_button, self.clear_button):
            row.addWidget(button)

        # -- full state ------------------------------------------------------
        self._full = QWidget(self)
        self._full.setObjectName("Plain")
        full = QVBoxLayout(self._full)
        full.setContentsMargins(0, 6, 0, 6)
        full.setSpacing(4)
        full.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # U+2193, not U+2B07: the latter has no text-presentation glyph in
        # Segoe UI (it renders as tofu, or as a jarring blue emoji tile once
        # you force emoji presentation with U+FE0F). Glyph and title share a
        # line now - a 30pt arrow on its own row bought nothing but height.
        title = QLabel("↓  " + self.tr("Drop files or folders here"), self._full)
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(self.tr("Drop as many as you like — folders are added whole."),
                      self._full)
        hint.setObjectName("Subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._full_slot = QHBoxLayout()
        self._full_slot.setContentsMargins(0, 0, 0, 0)
        self._full_slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        full.addWidget(title)
        full.addWidget(hint)
        full.addLayout(self._full_slot)
        column.addWidget(self._full)

        # -- chip state ------------------------------------------------------
        self._chip = QWidget(self)
        self._chip.setObjectName("Plain")
        chip = QHBoxLayout(self._chip)
        chip.setContentsMargins(0, 0, 0, 0)
        chip.setSpacing(GAP_INTRA)
        # The summary is the disclosure handle for the pending list (W2-10):
        # a button, so it focuses and announces itself as one.
        self.pending_toggle = QPushButton("", self._chip)
        self.pending_toggle.setObjectName("SectionToggle")
        self.pending_toggle.setCheckable(True)
        self.pending_toggle.toggled.connect(self._on_pending_toggled)
        chip.addWidget(self.pending_toggle)
        chip.addStretch(1)
        self._chip_slot = QHBoxLayout()
        self._chip_slot.setContentsMargins(0, 0, 0, 0)
        chip.addLayout(self._chip_slot)
        self._chip.setVisible(False)
        column.addWidget(self._chip)

        # -- the pending list, collapsed by default --------------------------
        self.pending_list = QListWidget(self)
        self.pending_list.setObjectName("PendingList")
        self.pending_list.setAccessibleName(self.tr("Files waiting to be compressed"))
        self.pending_list.setMaximumHeight(120)
        self.pending_list.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Maximum)
        self.pending_list.setVisible(False)
        column.addWidget(self.pending_list)

        self._full_slot.addWidget(self._buttons)

    # -- the two states ----------------------------------------------------
    def is_compact(self) -> bool:
        return self._compact and not self._dragging

    def summary_text(self) -> str:
        return self.pending_toggle.text()

    def set_pending(self, count: int, total_bytes: int) -> None:
        """Called by the window whenever the pending list changes."""
        self._compact = count > 0
        self.pending_toggle.setText(
            self.tr("%d item · %s") % (count, fmt_size(total_bytes)) if count == 1
            else self.tr("%d items · %s") % (count, fmt_size(total_bytes)))
        self.pending_toggle.setAccessibleName(
            self.tr("%s. Show or hide the list.") % self.pending_toggle.text())
        if not self._compact:
            self.pending_toggle.setChecked(False)
        self._apply_state()

    def toggle_pending(self) -> None:
        self.pending_toggle.setChecked(not self.pending_toggle.isChecked())

    def _on_pending_toggled(self, open_: bool) -> None:
        self.pending_list.setVisible(open_ and self._compact)
        self.pendingToggled.emit(open_)

    def _apply_state(self) -> None:
        compact = self.is_compact()
        self._full.setVisible(not compact)
        self._chip.setVisible(compact)
        self.pending_list.setVisible(compact and self.pending_toggle.isChecked())
        slot = self._chip_slot if compact else self._full_slot
        slot.addWidget(self._buttons)      # addWidget reparents; one call moves it

    # -- drag and drop -----------------------------------------------------
    def _set_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        # Re-expand while a drag is in flight: a 36px chip is not a target
        # anyone can hit, and the app should get bigger when you aim at it.
        self._dragging = active
        self._apply_state()
        repolish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        paths = paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.pathsAdded.emit(paths)
        else:
            event.ignore()

    # -- pickers -----------------------------------------------------------
    def _pick_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select files to compress"), str(Path.home()))
        paths = [Path(n) for n in names if n]
        if paths:
            self.pathsAdded.emit(paths)

    def _pick_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Select a folder to compress"), str(Path.home()))
        if name:
            self.pathsAdded.emit([Path(name)])
