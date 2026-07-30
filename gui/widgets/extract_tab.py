"""Restore tab: pick an .excmp, pick a destination, get proof it worked.

The verification is the feature. Extraction replays the stage chain in
reverse and re-checks the SHA-256 of every file against the ledger written
at compression time, so "restored" here means byte-identical, not
"the tool exited zero".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from ..format import fmt_eta, fmt_size
from .dropzone import paths_from_mime


class ExtractTab(QWidget):
    extractRequested = Signal(object, object)   # archive: Path, dest: Path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.setSpacing(14)

        card = QFrame(self)
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        title = QLabel(self.tr("Restore an archive"), card)
        title.setObjectName("Title")
        grid.addWidget(title, 0, 0, 1, 3)

        blurb = QLabel(self.tr(
            "Every file's SHA-256 was recorded when the archive was written. "
            "Restoring replays the stage chain backwards and re-checks each hash — "
            "if a single byte differs, this fails loudly instead of quietly."), card)
        blurb.setObjectName("Subtitle")
        blurb.setWordWrap(True)
        grid.addWidget(blurb, 1, 0, 1, 3)

        self.archive_edit = QLineEdit(card)
        self.archive_edit.setPlaceholderText(self.tr("…or drop an .excmp file here"))
        self.archive_edit.setAccessibleName(self.tr("Archive to restore"))
        archive_browse = QPushButton(self.tr("Browse…"), card)
        archive_browse.setAccessibleDescription(self.tr("Choose an .excmp archive"))
        archive_browse.clicked.connect(self._pick_archive)

        self.dest_edit = QLineEdit(card)
        self.dest_edit.setPlaceholderText(self.tr("where the files should go"))
        self.dest_edit.setAccessibleName(self.tr("Destination folder"))
        dest_browse = QPushButton(self.tr("Browse…"), card)
        dest_browse.setAccessibleDescription(self.tr("Choose the destination folder"))
        dest_browse.clicked.connect(self._pick_dest)

        grid.addWidget(QLabel(self.tr("Archive"), card), 2, 0)
        grid.addWidget(self.archive_edit, 2, 1)
        grid.addWidget(archive_browse, 2, 2)
        grid.addWidget(QLabel(self.tr("Restore to"), card), 3, 0)
        grid.addWidget(self.dest_edit, 3, 1)
        grid.addWidget(dest_browse, 3, 2)
        grid.setColumnStretch(1, 1)

        self.start_button = QPushButton(self.tr("Restore and verify"), card)
        self.start_button.setProperty("variant", "primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._emit_request)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addStretch(1)
        grid.addLayout(buttons, 4, 0, 1, 3)

        self.progress = QProgressBar(card)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setAccessibleName(self.tr("Restore progress"))
        grid.addWidget(self.progress, 5, 0, 1, 3)

        self.status = QLabel("", card)
        self.status.setObjectName("Subtitle")
        self.status.setWordWrap(True)
        grid.addWidget(self.status, 6, 0, 1, 3)

        column.addWidget(card)
        column.addStretch(1)

        self.archive_edit.textChanged.connect(self._revalidate)
        self.dest_edit.textChanged.connect(self._revalidate)
        self.setTabOrder(self.archive_edit, archive_browse)
        self.setTabOrder(archive_browse, self.dest_edit)
        self.setTabOrder(self.dest_edit, dest_browse)
        self.setTabOrder(dest_browse, self.start_button)

    # -- validation --------------------------------------------------------
    def _revalidate(self) -> None:
        archive = Path(self.archive_edit.text().strip('" '))
        dest = self.dest_edit.text().strip('" ')
        ok = bool(dest) and archive.is_file()
        self.start_button.setEnabled(ok)
        if self.archive_edit.text() and not archive.is_file():
            self.status.setText(self.tr("That archive does not exist."))
        elif archive.is_file():
            self.status.setText(self.tr("Archive is %s.") % fmt_size(archive.stat().st_size))

    def set_archive(self, path: Path) -> None:
        self.archive_edit.setText(str(path))
        if not self.dest_edit.text():
            self.dest_edit.setText(str(Path(path).with_suffix("")))

    # -- progress reporting ------------------------------------------------
    def set_running(self, percent: float, eta: float | None) -> None:
        self.progress.setVisible(True)
        self.progress.setValue(int(percent))
        self.start_button.setEnabled(False)
        self.status.setText(self.tr("Restoring… %s") % fmt_eta(eta))

    def set_finished(self, restored: int, verified: int) -> None:
        self.progress.setVisible(True)
        self.progress.setValue(100)
        # Deliberately not _revalidate(): it would overwrite the outcome with
        # the archive's file size. Only the button state needs restoring.
        self.start_button.setEnabled(True)
        self.status.setText(self.tr(
            "Restored %d file(s); %d hash(es) verified byte-identical.")
            % (restored, verified))

    def set_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.start_button.setEnabled(True)
        self.status.setText(self.tr("Restore failed: %s") % message)

    # -- pickers and drops -------------------------------------------------
    def _pick_archive(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select an archive"), str(Path.home()),
            self.tr("ExtremeCompressor archives (*.excmp);;All files (*)"))
        if name:
            self.set_archive(Path(name))

    def _pick_dest(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, self.tr("Restore to"), self.dest_edit.text() or str(Path.home()))
        if name:
            self.dest_edit.setText(name)

    def _emit_request(self) -> None:
        archive = Path(self.archive_edit.text().strip('" '))
        dest = Path(self.dest_edit.text().strip('" '))
        if archive.is_file() and str(dest):
            self.progress.setVisible(True)
            self.progress.setValue(0)
            self.extractRequested.emit(archive, dest)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [p for p in paths_from_mime(event.mimeData()) if p.is_file()]
        if paths:
            self.set_archive(paths[0])
            event.acceptProposedAction()
