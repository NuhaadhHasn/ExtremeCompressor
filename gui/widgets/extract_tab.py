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

import tempfile
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
    # G2. The tab never owns the password field: it says it needs one and the
    # window's Banner asks, so the secret lives in exactly one widget.
    passwordRequired = Signal(object)              # archive: Path
    extractSelectedRequested = Signal(object, object)  # archive, names

    COL_NAME, COL_SIZE, COL_ROUTE, COL_WHY = range(4)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._listing = None
        self._reading = False
        self._password: str | None = None
        self._temp_dir = Path(tempfile.gettempdir()) / "excmp"

        # One at a time: listing is cheap, and two 7-Zip launches racing to
        # fill the same tree would interleave rows from different archives.
        from PySide6.QtCore import QThreadPool
        from ..queue_manager import ListingSignals
        self._listing_pool = QThreadPool(self)
        self._listing_pool.setMaxThreadCount(1)
        self._listing_signals = ListingSignals(self)
        self._listing_signals.ready.connect(self._on_listing_ready)
        self._listing_signals.failed.connect(self._on_listing_failed)

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

        # G2: the caveat that only a foreign listing carries. Kept separate
        # from the card's standing blurb so it appears with the listing and
        # vanishes with it - a permanent disclaimer above a ledger-backed
        # table would be the wave-3b blurb contradiction one widget down.
        self.contents_caption = QLabel("", card)
        self.contents_caption.setObjectName("Subtitle")
        self.contents_caption.setWordWrap(True)
        self.contents_caption.setVisible(False)
        grid.addWidget(self.contents_caption, 8, 0, 1, 3)

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
        self.contents.itemChanged.connect(lambda *_: self._refresh_selection())
        grid.addWidget(self.contents, 9, 0, 1, 3)

        self.extract_selected_button = QPushButton(
            self.tr("Extract selected"), card)
        self.extract_selected_button.setEnabled(False)
        self.extract_selected_button.setToolTip(self.tr(
            "Restore only the ticked files. In a solid archive that still "
            "replays the whole chain to reach them — you will be told how "
            "much before it starts."))
        self.extract_selected_button.setAccessibleDescription(
            self.extract_selected_button.toolTip())
        self.extract_selected_button.clicked.connect(self._emit_selected)
        grid.addWidget(self.extract_selected_button, 10, 0, 1, 3)
        self.extract_selected_button.setVisible(False)

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

    # I5: the same doors the buttons use, for the Explorer verbs - including the question each
    # button asks before it is enabled (Verify is off for an archive with no SHA-256 ledger).
    def request_extract(self) -> bool:
        if not self.start_button.isEnabled():
            return False
        self._emit_request()
        return True

    def request_verify(self) -> bool:
        if not self.verify_button.isEnabled():
            return False
        self._emit_verify()
        return True

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

        # G2: anything 7-Zip can open can now be listed. Before this phase
        # the toggle was disabled for foreign archives and said so, because
        # an empty list reads as "this archive is empty" - the refusal was
        # honest, and this is what makes it unnecessary.
        self.contents_toggle.setEnabled(exists)
        self.contents_toggle.setToolTip("" if exists else self.tr(
            "Choose an archive first."))
        if not exists:
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
        showing = open_ and self.contents.topLevelItemCount() > 0
        self.contents.setVisible(showing)
        self.contents_caption.setVisible(
            showing and self._listing is not None
            and not self._listing.ledger_backed)
        self.extract_selected_button.setVisible(showing)

    def _fill_contents(self) -> None:
        """Ours synchronously, anyone else's on a worker (G2).

        The asymmetry is real rather than tidy: our listing is a zip-directory
        read plus one JSON parse and is genuinely instant even on a 700 GB
        archive, while a foreign one launches `7z l -slt` against a file that
        might be an ISO on an external drive.
        """
        from excmp.engine import is_excmp, list_archive

        self.contents.clear()
        archive = Path(self.archive_edit.text().strip('" '))
        if not archive.is_file():
            return
        if is_excmp(archive):
            try:
                self._apply_listing(list_archive(archive))
            except Exception as exc:                      # noqa: BLE001
                self.status.setText(
                    self.tr("Could not read the contents: %s") % exc)
            return
        self._start_foreign_listing(archive)

    # -- G2: the foreign path ----------------------------------------------
    def _start_foreign_listing(self, archive: Path) -> None:
        from ..queue_manager import ListingWorker

        self._reading = True
        self.status.setText(self.tr("Reading the archive’s contents…"))
        self._listing_pool.start(ListingWorker(
            archive, self._password, self._temp_dir, self._listing_signals))

    def _on_listing_ready(self, listing: object) -> None:
        self._apply_listing(listing)

    def _on_listing_failed(self, message: str, needs_password: bool) -> None:
        self._reading = False
        if needs_password:
            # File Roller's timing: ask when the operation needs the answer,
            # not when the file was chosen. The Banner owns the field; this
            # tab never sees the secret until it is handed one.
            self.passwordRequired.emit(Path(self.archive_edit.text().strip('" ')))
            return
        self.status.setText(self.tr("Could not read the contents: %s") % message)

    def unlock_with(self, password: str) -> None:
        """Retry the listing with the password the Banner collected."""
        self._password = password or None
        archive = Path(self.archive_edit.text().strip('" '))
        if archive.is_file():
            self._start_foreign_listing(archive)

    def current_password(self) -> str | None:
        return self._password

    # -- rendering ---------------------------------------------------------
    def _apply_listing(self, listing) -> None:
        """Fill the tree, with the columns each kind of archive can honestly
        fill.

        Ours knows the route it chose and *why* it stored a file, and carries
        a SHA-256. A foreign archive knows none of those and carries a CRC-32
        instead. Pointing our headings at its numbers would repeat the defect
        the QA sweep already caught once, when a foreign extract borrowed the
        verified-restore wording.
        """
        self._listing = listing
        self.contents.clear()
        ours = listing.ledger_backed

        self.contents.setHeaderLabels(
            [self.tr("File"), self.tr("Size"), self.tr("Route"),
             self.tr("Why it was stored")] if ours else
            [self.tr("File"), self.tr("Size"), self.tr("Packed"),
             self.tr("Modified")])

        self.contents_caption.setVisible(not ours)
        if not ours:
            # Deliberately NOT another "this was not created by
            # ExtremeCompressor" - the status line five rows up already says
            # that, and Phase J's own notes record printing one warning three
            # times in a single panel as a defect. This caption earns its
            # place by explaining the *columns*, which is the one thing the
            # status line cannot.
            note = self.tr(
                "Sizes and checksums as the archive itself records them. The "
                "CRC-32 on each row (hover a name) is an error check, not the "
                "SHA-256 a verified restore compares against.")
            if listing.encrypted:
                note += self.tr(" Some entries are encrypted; extracting "
                                "those will ask for the password.")
            if listing.truncated:
                note += self.tr(" Showing the first %d entries only — this "
                                "archive holds more.") % len(listing.entries)
            self.contents_caption.setText(note)

        for entry in listing.entries:
            item = QTreeWidgetItem(self.contents)
            name = entry.name + ("/" if entry.is_dir else "")
            item.setText(self.COL_NAME, name)
            item.setText(self.COL_SIZE, fmt_size(entry.size))
            if ours:
                item.setText(self.COL_ROUTE, entry.route)
                item.setText(self.COL_WHY, entry.reason)
                # The SHA-256 is the evidence; too wide for a column, but it
                # belongs one hover away rather than nowhere.
                item.setToolTip(self.COL_NAME,
                                f"{entry.name}\nSHA-256 {entry.sha256}")
                spoken = self.tr("%s, %s, %s") % (
                    entry.name, fmt_size(entry.size),
                    entry.reason or entry.route)
            else:
                # Blank, not "0 B": 7-Zip leaves the packed size empty for
                # every member of a solid block after the first, and a zero
                # there would claim the file costs nothing to store.
                item.setText(self.COL_ROUTE,
                             fmt_size(entry.packed_size)
                             if entry.packed_size is not None else "")
                item.setText(self.COL_WHY, entry.modified[:19])
                item.setToolTip(self.COL_NAME, self.tr(
                    "%s\nCRC-32 %s (an error check, not a SHA-256)")
                    % (entry.name, entry.crc or self.tr("not recorded")))
                spoken = self.tr("%s, %s") % (name, fmt_size(entry.size))

            item.setData(self.COL_NAME, Qt.ItemDataRole.AccessibleTextRole, spoken)
            item.setData(self.COL_NAME, Qt.ItemDataRole.UserRole, entry.name)
            if entry.is_dir:
                # A directory is archive bookkeeping. Offering it as a
                # selectable file invites a request that returns nothing.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(self.COL_NAME, Qt.CheckState.Unchecked)

        showing = (self.contents_toggle.isChecked()
                   and self.contents.topLevelItemCount() > 0)
        self.contents.setVisible(showing)
        self.extract_selected_button.setVisible(showing)
        # The foreign path sets a "Reading..." status before launching 7-Zip.
        # Leaving it up beside a loaded table says the job is still running.
        if self._reading:
            self._reading = False
            self._revalidate()
        self._refresh_selection()

    # -- selection ---------------------------------------------------------
    def selected_names(self) -> list[Path]:
        names = []
        for i in range(self.contents.topLevelItemCount()):
            item = self.contents.topLevelItem(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and \
                    item.checkState(self.COL_NAME) == Qt.CheckState.Checked:
                names.append(item.data(self.COL_NAME, Qt.ItemDataRole.UserRole))
        return names

    def check_row(self, row: int) -> None:
        self.contents.topLevelItem(row).setCheckState(
            self.COL_NAME, Qt.CheckState.Checked)

    def check_named(self, name: str) -> None:
        for i in range(self.contents.topLevelItemCount()):
            item = self.contents.topLevelItem(i)
            if item.data(self.COL_NAME, Qt.ItemDataRole.UserRole) == name:
                item.setCheckState(self.COL_NAME, Qt.CheckState.Checked)
                return
        raise KeyError(name)

    def _refresh_selection(self) -> None:
        count = len(self.selected_names())
        self.extract_selected_button.setEnabled(count > 0)
        self.extract_selected_button.setText(
            self.tr("Extract %d selected") % count if count
            else self.tr("Extract selected"))

    def _emit_selected(self) -> None:
        names = self.selected_names()
        archive = Path(self.archive_edit.text().strip('" '))
        if names and archive.is_file():
            self.extractSelectedRequested.emit(archive, names)

    def current_listing(self):
        return self._listing

    def set_archive(self, path: Path) -> None:
        self.contents.clear()
        self._listing = None
        self._reading = False
        # A password was given for one archive. Carrying it to the next
        # silently tries a user's secret against a file they never offered
        # it for.
        self._password = None
        self.archive_edit.setText(str(path))
        if not self.dest_edit.text():
            self.dest_edit.setText(str(self._suggest_destination(Path(path))))

    @staticmethod
    def _suggest_destination(archive: Path) -> Path:
        """Ark's autosubfolder rule, which our manifest can answer exactly.

        If everything in the archive already lives under a single top-level
        folder, extracting *beside* the archive is right - inventing another
        folder produces `bundle/src/...`, a wrapper nobody asked for. If the
        archive has several things at the top level, they would spray across
        the destination, so they get a folder named after the archive.

        Other archivers guess at this from a listing; here it is a set
        comprehension over the ledger. A foreign archive has no ledger, so it
        takes the safe branch.
        """
        from excmp.engine import list_archive

        try:
            listing = list_archive(archive)
        except Exception:                                    # noqa: BLE001
            return archive.with_suffix("")
        tops = {name.split("/", 1)[0] for name in
                (e.name.replace("\\", "/") for e in listing.entries)}
        # One top-level name, and it is a folder (something lives under it).
        nested = any("/" in e.name.replace("\\", "/") for e in listing.entries)
        if len(tops) == 1 and nested:
            return archive.parent
        return archive.with_suffix("")

    @staticmethod
    def safe_here_destination(archive: Path) -> Path:
        """Where "Extract here" (the Explorer verb) may write WITHOUT replacing anything.

        The Extract button shows its destination before the click, so a user who sees that it
        is their Downloads folder, with their edited copy of a file in it, can choose. The verb
        shows nothing: one right-click went straight to ``extract`` and put an edited ``a.txt``
        back to its archived text (found by the I5 review). So the suggested destination is used
        only if none of the archive's top-level names exists in it already; otherwise the
        restore goes to a fresh folder named after the archive, ``name (2)``, ``name (3)``...
        An archive that cannot be listed gets a fresh folder too.
        """
        from excmp.engine import list_archive

        dest = ExtractTab._suggest_destination(archive)
        try:
            tops = {e.name.replace("\\", "/").split("/", 1)[0]
                    for e in list_archive(archive).entries}
        except Exception:                                    # noqa: BLE001
            tops = set()
        if tops and not any((dest / t).exists() for t in tops):
            return dest
        base = archive.with_suffix("")
        candidate, n = base, 2
        while candidate.exists():
            candidate = base.with_name(f"{base.name} ({n})")
            n += 1
        return candidate

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
