"""Restore tab: pick an archive, pick a destination, get proof it worked.

The verification is the feature. Extracting one of ours replays the stage
chain in reverse and re-checks the SHA-256 of every file against the ledger
written at compression time, so "restored" means byte-identical, not "the
tool exited zero".

**G1 (wave 3b): it opens other people's archives too** - zip/7z/rar/tar/iso/
cab/msi/wim, anything `7z x` handles. That was always possible; only a file
filter stopped it. What matters is that the tab says, *before* you press
anything, which of the two you are holding: a foreign archive carries no
ledger, so nothing can be checked against one, and pretending otherwise would
hollow out the single guarantee this project sells.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..format import fmt_eta, fmt_size
from .dropzone import paths_from_mime


class ExtractTab(QWidget):
    extractRequested = Signal(object, object)   # archive: Path, dest: Path
    verifyRequested = Signal(object)           # archive: Path

    COL_NAME, COL_SIZE, COL_ROUTE, COL_WHY = range(4)

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

        # Rewritten per archive kind: since G1 this tab opens foreign archives
        # too, and a standing promise about SHA-256 ledgers sitting above a
        # status line saying "this one has no ledger" is a contradiction on
        # screen. Found by the QA sweep, not by a test.
        self._blurb = blurb = QLabel(self._blurb_text(ours=True), card)
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
        # Verification without extraction: the honest answer to "is this
        # archive still good?" about a file that has been sitting on a drive
        # for a year. It needs no destination, and writes nothing.
        self.verify_button = QPushButton(self.tr("Verify only"), card)
        self.verify_button.setEnabled(False)
        self.verify_button.setToolTip(self.tr(
            "Restore every file to a temporary folder, check it against the "
            "archive’s SHA-256 ledger, then delete it again. Nothing is "
            "written to your destination folder."))
        self.verify_button.setAccessibleDescription(self.verify_button.toolTip())
        self.verify_button.clicked.connect(self._emit_verify)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.verify_button)
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

        # I2-lite: the whole ledger is a zip-directory read plus one JSON
        # parse, so "what is in here?" costs nothing even on a 700 GB archive.
        # Collapsed by default - it answers a question, it is not the answer.
        self.contents_toggle = QPushButton("", card)
        self.contents_toggle.setObjectName("SectionToggle")
        self.contents_toggle.setCheckable(True)
        self.contents_toggle.setEnabled(False)
        self.contents_toggle.toggled.connect(self._set_contents_open)
        grid.addWidget(self.contents_toggle, 7, 0, 1, 3)

        self.contents = QTreeWidget(card)
        self.contents.setColumnCount(4)
        self.contents.setHeaderLabels([self.tr("File"), self.tr("Size"),
                                       self.tr("Route"),
                                       self.tr("Why it was stored")])
        self.contents.setRootIsDecorated(False)
        self.contents.setAlternatingRowColors(True)
        self.contents.setMaximumHeight(220)
        self.contents.setAccessibleName(self.tr("Archive contents"))
        self.contents.header().setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.contents.setVisible(False)
        grid.addWidget(self.contents, 8, 0, 1, 3)
        self._set_contents_open(False)

        column.addWidget(card)
        column.addStretch(1)

        self.archive_edit.textChanged.connect(self._revalidate)
        self.dest_edit.textChanged.connect(self._revalidate)
        self.setTabOrder(self.archive_edit, archive_browse)
        self.setTabOrder(archive_browse, self.dest_edit)
        self.setTabOrder(self.dest_edit, dest_browse)
        self.setTabOrder(dest_browse, self.start_button)
        self.setTabOrder(self.start_button, self.verify_button)

    # G1: `extract()` has always been able to hand anything to `7z x`. The only
    # thing stopping people was this filter. Ours first, because that is the
    # case with guarantees attached.
    _FOREIGN = ("*.zip *.7z *.rar *.tar *.gz *.tgz *.bz2 *.xz *.zst "
                "*.iso *.cab *.msi *.wim *.lzh *.arj")

    def archive_filter(self) -> str:
        return self.tr(
            "Archives (*.excmp {foreign});;"
            "ExtremeCompressor archives (*.excmp);;"
            "Other archives ({foreign});;"
            "All files (*)").format(foreign=self._FOREIGN)

    def _emit_verify(self) -> None:
        archive = Path(self.archive_edit.text().strip('" '))
        if archive.is_file():
            self.verifyRequested.emit(archive)

    # -- validation --------------------------------------------------------
    def _revalidate(self) -> None:
        archive = Path(self.archive_edit.text().strip('" '))
        dest = self.dest_edit.text().strip('" ')
        exists = archive.is_file()
        self.start_button.setEnabled(bool(dest) and exists)

        from excmp.engine import is_excmp
        ours = exists and is_excmp(archive)
        self._ours = ours

        # Verify means "compare against the ledger". A foreign archive has
        # none, so the button is off AND says why - a greyed control that never
        # explains itself is the thing this UI keeps refusing to ship.
        self.verify_button.setEnabled(ours)
        self.verify_button.setToolTip(self.tr(
            "Restore every file to a temporary folder, check it against the "
            "archive’s SHA-256 ledger, then delete it again. Nothing is "
            "written to your destination folder.") if ours else self.tr(
            "Only ExtremeCompressor archives can be verified: this one carries "
            "no SHA-256 ledger to check against."))
        self.verify_button.setAccessibleDescription(self.verify_button.toolTip())

        self.contents_toggle.setEnabled(ours)
        self.contents_toggle.setToolTip("" if ours else self.tr(
            "Listing other formats needs 7-Zip’s own listing support, which "
            "is not wired up yet."))
        if not ours:
            self.contents_toggle.setChecked(False)
        self._set_contents_open(self.contents_toggle.isChecked())

        self._blurb.setText(self._blurb_text(ours or not exists))

        if self.archive_edit.text() and not exists:
            self.status.setText(self.tr("That archive does not exist."))
        elif ours:
            self.status.setText(self.tr(
                "Archive is %s. Every file will be checked against its SHA-256 "
                "ledger as it is restored.") % fmt_size(archive.stat().st_size))
        elif exists:
            self.status.setText(self.tr(
                "Archive is %s. This one was not created by ExtremeCompressor, "
                "so it has no SHA-256 ledger — the files can be extracted, but "
                "nothing can be checked against one.")
                % fmt_size(archive.stat().st_size))

    def _blurb_text(self, ours: bool) -> str:
        if ours:
            return self.tr(
                "Every file's SHA-256 was recorded when the archive was written. "
                "Restoring replays the stage chain backwards and re-checks each "
                "hash — if a single byte differs, this fails loudly instead of "
                "quietly.")
        return self.tr(
            "This tab also opens archives made by other tools — zip, 7z, rar, "
            "tar, iso and the rest. Those carry no SHA-256 ledger, so the files "
            "come out but nothing can be checked against one.")

    def _set_contents_open(self, open_: bool) -> None:
        self.contents_toggle.setText(self.tr("▾  What’s inside") if open_
                                     else self.tr("▸  What’s inside"))
        self.contents_toggle.setAccessibleName(
            self.tr("Archive contents, expanded") if open_
            else self.tr("Archive contents, collapsed"))
        if open_ and self.contents.topLevelItemCount() == 0:
            self._fill_contents()
        self.contents.setVisible(open_ and self.contents.topLevelItemCount() > 0)

    def _fill_contents(self) -> None:
        """Straight from the manifest - no extraction, no worker thread. A zip
        directory read plus one JSON parse is fast even on a huge archive."""
        from excmp.engine import list_archive

        self.contents.clear()
        archive = Path(self.archive_edit.text().strip('" '))
        try:
            listing = list_archive(archive)
        except Exception as exc:                      # noqa: BLE001
            self.status.setText(self.tr("Could not read the contents: %s") % exc)
            return
        for entry in listing.entries:
            item = QTreeWidgetItem(self.contents)
            item.setText(self.COL_NAME, entry.name)
            item.setText(self.COL_SIZE, fmt_size(entry.size))
            item.setText(self.COL_ROUTE, entry.route)
            item.setText(self.COL_WHY, entry.reason)
            # The SHA-256 is the evidence; it is too wide for a column but it
            # belongs one hover away, not nowhere.
            item.setToolTip(self.COL_NAME,
                            f"{entry.name}\nSHA-256 {entry.sha256}")
            # One spoken sentence per row, so a screen reader does not have to
            # stitch four columns together to learn what the row says.
            spoken = self.tr("%s, %s, %s") % (entry.name, fmt_size(entry.size),
                                              entry.reason or entry.route)
            item.setData(self.COL_NAME, Qt.ItemDataRole.AccessibleTextRole, spoken)

    def set_archive(self, path: Path) -> None:
        self.contents.clear()
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
            self.archive_filter())
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
