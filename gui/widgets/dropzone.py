"""The drop target.

HandBrake's two most-reported intake bugs are (a) dropping a folder does
nothing and (b) dropping five files keeps one. Both are avoided the same
way: walk *every* URL in the mime data, accept files and directories
alike, and emit the whole list. There is no filtering by extension either -
the analyzer decides what things are, not the file name.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..theme import repolish


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
    """Dashed panel that highlights on drag and emits the dropped paths."""

    pathsAdded = Signal(list)     # list[Path] - files *and* folders

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self.setMinimumHeight(150)
        self.setAccessibleName(self.tr("Drop area for files and folders"))

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.setSpacing(6)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # U+2193, not U+2B07: the latter has no text-presentation glyph in
        # Segoe UI (it renders as tofu, or as a jarring blue emoji tile once
        # you force emoji presentation with U+FE0F).
        icon = QLabel("↓", self)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 30pt;")
        icon.setAccessibleName(self.tr("Drop indicator"))

        title = QLabel(self.tr("Drop files or folders here"), self)
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel(self.tr("Drop as many as you like — folders are added whole."), self)
        hint.setObjectName("Subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QWidget(self)
        buttons.setObjectName("Plain")
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_button = QPushButton(self.tr("Add files…"), buttons)
        self.folder_button = QPushButton(self.tr("Add folder…"), buttons)
        self.files_button.setAccessibleDescription(
            self.tr("Choose one or more files to add to the queue"))
        self.folder_button.setAccessibleDescription(
            self.tr("Choose a folder to add to the queue"))
        self.files_button.clicked.connect(self._pick_files)
        self.folder_button.clicked.connect(self._pick_folder)
        row.addWidget(self.files_button)
        row.addWidget(self.folder_button)

        for widget in (icon, title, hint, buttons):
            column.addWidget(widget)

    # -- drag and drop -----------------------------------------------------
    def _set_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
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
