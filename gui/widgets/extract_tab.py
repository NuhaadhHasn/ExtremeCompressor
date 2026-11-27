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

import os
import re
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from excmp import engine
from excmp.stages.base import StageContext

from ..format import fmt_eta, fmt_size
from .dropzone import paths_from_mime

#: Dragging files out unpacks them while the mouse button is held, on the window's own thread, so it is capped twice: by
#: bytes, and by the TIME the estimate gives for the archive's own stage chain (a byte count alone let a 128 MB Insane
#: archive freeze the window for twenty minutes). Past either, the drag is refused and "Restore selected" (a queued job
#: with progress) is the way.
DRAG_LIMIT = 128 * 1024 * 1024
DRAG_SECONDS = 8.0
#: The cap above trusts the sizes the archive lists, and an archive can lie. So the unpack is also watched: if what actually
#: lands on disk passes the limit (plus a quarter, for the solid replay's working files), or it runs past this many seconds,
#: the unpack is cancelled (the running tool is killed) and the drag is refused.
DRAG_DEADLINE_S = 30.0
#: Staging folders are kept briefly after a drop (Explorer may still be copying out of them): the next drag removes only
#: the old ones, never more than this many are kept, and closing the app removes all.
_STAGE_MAX_AGE_S = 120.0
_KEEP_STAGES = 3
_VOLUME_NAME = re.compile(r"\.\d{3}$")
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")

#: Where the files being dragged are unpacked. Explorer copies from here after the drop, perhaps for a while, so a
#: folder is never deleted right after a drop: the next drag removes it, so does closing the app, and a stale one is
#: swept at start-up.
_DRAG_TEMP_ROOT = Path(tempfile.gettempdir()) / "excmp-drag"
_DRAG_PREFIX = "excmp-drag-"


class DragRefused(Exception):
    """The files cannot be dragged out; the message says why, in words for the person."""


def sweep_stale_drag_folders(root: Path, max_age_s: float = 86400.0) -> None:
    """Remove staging folders an earlier run left behind (it was killed, or the PC lost power). Only
    ``excmp-drag-*`` folders directly under ``root`` and older than ``max_age_s`` are touched."""
    from excmp.tempclean import is_reparse_point, rmtree_force
    if is_reparse_point(root):               # not a plain folder: whatever it leads to is not ours to clean
        return
    try:
        children = list(Path(root).iterdir())
    except OSError:
        return
    now = time.time()
    for child in children:
        try:
            if child.name.startswith(_DRAG_PREFIX) and not is_reparse_point(child) and child.is_dir() \
                    and now - child.stat().st_mtime > max_age_s:
                rmtree_force(child)
        except OSError:
            continue


def _tree_bytes(path: Path) -> int:
    """Bytes in the files under ``path`` (links are not followed; anything unreadable counts as nothing)."""
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class _DragGuard:
    """Watches an unpack from another thread (the unpacking itself blocks the window's) and cancels it, through the
    stage context's ``cancel`` event, when the real bytes written or the time pass their limits. ``reason`` says which."""

    def __init__(self, cancel, stage: Path, scratch: Path, limit: int, deadline_s: float) -> None:
        """``stage`` is where the files are written and ``scratch`` is the unpack's PRIVATE working folder (made for this
        drag alone, so everything in it is this unpack's: nothing is guessed from folder names)."""
        self.cancel, self.stage, self.scratch = cancel, stage, scratch
        self.limit, self.deadline_s = limit, deadline_s
        self.reason = ""
        self._done = threading.Event()
        self._started = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._done.set()
        self._thread.join(2.0)

    def _written(self) -> int:
        """Bytes this unpack has written: the staging folder and its whole private working folder."""
        return _tree_bytes(self.stage) + _tree_bytes(self.scratch)

    def _run(self) -> None:
        while not self._done.wait(0.2):
            if time.time() - self._started > self.deadline_s:
                self.reason = "time"
            elif self._written() > self.limit + self.limit // 4:
                self.reason = "size"
            if self.reason:
                self.cancel.set()
                return


class _DragOutTree(QTreeWidget):
    """The archive's file list. Rows can be dragged out, copy only; nothing can be dropped on it."""

    def __init__(self, parent: QWidget, make_mime) -> None:
        super().__init__(parent)
        self._make_mime = make_mime
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def drag_actions(self):
        return Qt.DropAction.CopyAction             # never Move: nothing is ever taken out of the archive or the staging copy

    def startDrag(self, supported_actions) -> None:      # noqa: N802 (Qt name)
        super().startDrag(self.drag_actions())

    def mimeData(self, items):                           # noqa: N802 (Qt name)
        return self._make_mime(list(items))


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
        self._listing_for: Path | None = None    # the archive the rows in the list were read from
        self._reading = False
        self._password: str | None = None
        self._locked = False            # our own password-protected .excmp (not a zip until decrypted)
        self._pending: str | None = None        # what the user asked for while the password was missing
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
        self.verify_button = QPushButton(self.tr("Check without restoring"), card)
        self.verify_button.setEnabled(False)
        self.verify_button.setToolTip(self.tr(
            "Restore every file to a temporary folder, check it against the "
            "archive’s saved fingerprints (SHA-256), then delete it again. Nothing is "
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

        self.contents = _DragOutTree(card, self._drag_mime)
        self.contents.setColumnCount(4)
        self.contents.setHeaderLabels([self.tr("File"), self.tr("Size"),
                                       self.tr("How"),
                                       self.tr("Why it was not compressed")])
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
            self.tr("Restore selected"), card)
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

        # Under the list: how to use it, and (in place of that) why a drag was refused. Never a dialog.
        self.drag_note = QLabel("", card)
        self.drag_note.setObjectName("Subtitle")
        self.drag_note.setWordWrap(True)
        self.drag_note.setTextFormat(Qt.TextFormat.PlainText)
        self.drag_note.setVisible(False)
        grid.addWidget(self.drag_note, 11, 0, 1, 3)
        self._drag_stages: list[tuple[Path, float]] = []     # (staging folder, when), oldest first
        sweep_stale_drag_folders(_DRAG_TEMP_ROOT)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cleanup_drag)

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
            if self._needs_password():
                self._ask_password("verify", archive)
                return
            self.verifyRequested.emit(archive)

    def _needs_password(self) -> bool:
        return self._locked and not self._password

    def _ask_password(self, action: str, archive: Path) -> None:
        """Ask inline (the Banner owns the field) and remember what was asked for: the job starts as soon as
        the password arrives, so the user does not press the same button twice."""
        self._pending = action
        self.passwordRequired.emit(archive)

    def is_locked(self) -> bool:
        return self._locked

    def take_password(self) -> str | None:
        """Hand the password to the job that is starting, and forget it here: a protected archive's
        password lives only as long as the one job it was typed for."""
        pw, self._password = self._password, None
        return pw

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

        from excmp.crypto import is_encrypted
        from excmp.engine import is_excmp
        # A password-protected .excmp is one of ours but is not a zip until it is decrypted, so is_excmp
        # cannot see it: it used to be treated as a foreign archive (Verify off, "not created by us", and a
        # restore that never asked for the password).
        locked = exists and is_encrypted(archive)
        self._locked = locked
        # A split archive's first part (name.excmp.001, with our .volumes.sha256 beside it) is a slice of the
        # container, not a zip: is_excmp cannot see it either. Somebody else's .001 has no such sidecar.
        from excmp.volumes import is_first_part, missing_parts, part_paths, sidecar_for
        split = exists and is_first_part(archive) and sidecar_for(archive).is_file()
        self._split_parts = part_paths(archive) if split else []
        ours = exists and (locked or split or is_excmp(archive))
        self._ours = ours

        # Verify means "compare against the ledger". A foreign archive has
        # none, so the button is off AND says why - a greyed control that never
        # explains itself is the thing this UI keeps refusing to ship.
        self.verify_button.setEnabled(ours)
        self.verify_button.setToolTip(self.tr(
            "Restore every file to a temporary folder, check it against the "
            "archive’s saved fingerprints (SHA-256), then delete it again. Nothing is "
            "written to your destination folder.") if ours else self.tr(
            "Only ExtremeCompressor archives can be verified: this one carries "
            "no saved fingerprints to check against."))
        self.verify_button.setAccessibleDescription(self.verify_button.toolTip())

        # G2: anything 7-Zip can open can now be listed. Before this phase
        # the toggle was disabled for foreign archives and said so, because
        # an empty list reads as "this archive is empty" - the refusal was
        # honest, and this is what makes it unnecessary.
        self.contents_toggle.setEnabled(exists and not locked)
        self.contents_toggle.setToolTip(
            self.tr("Choose an archive first.") if not exists else
            self.tr("A password-protected archive cannot be listed here: restore or verify it, and you will be "
                    "asked for the password.") if locked else "")
        if not exists:
            self.contents_toggle.setChecked(False)
        self._set_contents_open(self.contents_toggle.isChecked())

        self._blurb.setText(self._blurb_text(ours or not exists))

        if self.archive_edit.text() and not exists:
            self.status.setText(self.tr("That archive does not exist."))
        elif split:
            gap = missing_parts(archive)
            size = sum(p.stat().st_size for p in self._split_parts)
            if gap:
                self.status.setText(self.tr(
                    "Archive is split into parts, but %s is missing: put every part in this folder first.")
                    % ", ".join(gap))
            else:
                self.status.setText(self.tr(
                    "Archive is %s in %d parts. Every file will be checked against its saved fingerprint as it "
                    "is restored.") % (fmt_size(size), len(self._split_parts)))
        elif locked:
            self.status.setText(self.tr(
                "Archive is %s and password-protected: you will be asked for the password. Every file is then "
                "checked against its saved fingerprint as it is restored.") % fmt_size(archive.stat().st_size))
        elif ours:
            self.status.setText(self.tr(
                "Archive is %s. Every file will be checked against its saved "
                "fingerprint as it is restored.") % fmt_size(archive.stat().st_size))
        elif exists:
            self.status.setText(self.tr(
                "Archive is %s. This one was not created by ExtremeCompressor, "
                "so it has no saved fingerprints: the files can be restored, but "
                "nothing can be checked.")
                % fmt_size(archive.stat().st_size))

    def _blurb_text(self, ours: bool) -> str:
        if ours:
            return self.tr(
                "Every file is checked against the fingerprint saved when the "
                "archive was made. If even one byte differs, the restore fails "
                "and says so.")
        return self.tr(
            "This tab also opens archives made by other tools — zip, 7z, tar "
            "and the rest (rar and iso need the full 7-Zip installed). They "
            "carry no saved fingerprints, so the files can be restored but "
            "not checked.")

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
        self._show_drag_hint(showing)

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
        self._listing_for = archive
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
        self._listing_for = archive
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
        """Use the password the Banner collected: carry on with what was asked for (a protected .excmp), or
        retry the listing (a foreign archive whose names are encrypted)."""
        self._password = password or None
        archive = Path(self.archive_edit.text().strip('" '))
        if self._locked:
            pending, self._pending = self._pending, None
            if self._password and pending == "extract":
                self._emit_request()
            elif self._password and pending == "verify":
                self._emit_verify()
            return
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
            [self.tr("File"), self.tr("Size"), self.tr("How"),
             self.tr("Why it was not compressed")] if ours else
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
                # plain words for what the engine calls the route (the data keeps its own names)
                item.setText(self.COL_ROUTE, {"store": self.tr("Kept as is"),
                                              "pipeline": self.tr("Compressed")}.get(entry.route, entry.route))
                item.setText(self.COL_WHY, entry.reason or "—")
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
        self._show_drag_hint(showing)
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
            self.tr("Restore %d selected") % count if count
            else self.tr("Restore selected"))

    def _selected_archive(self) -> Path:
        """The archive the list on screen was read from. Not the Archive field: that can be retyped while the rows still
        show the old archive, and files must come from the archive whose rows were picked."""
        return self._listing_for or Path(self.archive_edit.text().strip('" '))

    def _emit_selected(self) -> None:
        names = self.selected_names()
        archive = self._selected_archive()
        if names and archive.is_file():
            self.extractSelectedRequested.emit(archive, names)

    def current_listing(self):
        return self._listing

    # -- dragging files out ----------------------------------------------------
    def _show_drag_hint(self, showing: bool) -> None:
        self.drag_note.setText(self.tr("Drag files out of this list into a folder to restore just those, or tick them "
                                       "and press “Restore selected”."))
        self.drag_note.setVisible(showing)

    def _say_drag(self, text: str) -> None:
        self.drag_note.setText(text)
        self.drag_note.setHidden(False)

    def _drag_cost(self, chosen, archive: Path) -> tuple[int, float]:
        """(bytes to unpack, estimated seconds) to reach ``chosen``.

        A file kept as is (ours) or a member of a zip is read on its own, so only its own size counts; anything else is
        in a solid block, and reaching it replays the whole chain. The seconds use the estimate's rate for the
        archive's own stage chain, so a slow chain (Insane) is priced as slow."""
        from excmp.estimate import DEFAULT_RATES

        def size(entry) -> int:
            return int(entry.size or 0)
        everything = sum(size(e) for e in self._listing.entries if not e.is_dir)
        if self._listing.ledger_backed:
            independent = all(e.route == "store" for e in chosen)
            stages = [] if independent else list(self._listing.stages)
        else:
            independent, stages = True, ["sevenzip"]               # a zip member (the only foreign kind accepted)
        work = sum(size(e) for e in chosen) if independent else everything
        return work, work / max(DEFAULT_RATES.verify_rate_for(stages), 1.0)

    def _check_foreign_dragable(self, archive: Path) -> None:
        """Only a plain zip, whose members are unpacked one by one and whose list is complete. Anything else is one solid
        block with no honest size to price (a forged size trailer cost a real unpack before it failed), and a cut-off
        list cannot show that a name is unique."""
        if self._listing.truncated:
            raise DragRefused(self.tr("This archive has too many files to list in full, so they cannot be dragged out. "
                                      "Tick them and press “Restore selected”."))
        try:
            with open(archive, "rb") as fh:
                head = fh.read(4)
        except OSError:
            head = b""
        if head not in _ZIP_MAGICS:
            raise DragRefused(self.tr("Files can be dragged out of a zip, or of an archive made here, but not out of "
                                      "this kind of archive. Tick them and press “Restore selected”."))

    def stage_for_drag(self, names: list[str]) -> list[Path]:
        """Unpack ``names`` into a fresh staging folder and return the unpacked files, in order.

        Our own archives are checked against their SHA-256 ledger by the engine, exactly as "Restore selected" is.
        Raises :class:`DragRefused` (with a message for the person) when there is nothing to drag or it is too much.
        """
        from excmp.tempclean import is_reparse_point, rmtree_force

        archive = self._selected_archive()
        if self._listing is None or not archive.is_file():
            raise DragRefused(self.tr("Open the archive’s contents first."))
        if _VOLUME_NAME.search(archive.name):
            raise DragRefused(self.tr("An archive in several parts has to be joined first, which is too much to do "
                                      "while you hold the mouse button. Tick the files and press “Restore selected”."))
        by_name = {e.name: e for e in self._listing.entries}
        chosen = [by_name[n] for n in dict.fromkeys(names) if n in by_name and not by_name[n].is_dir]
        if not chosen:
            raise DragRefused(self.tr("Only files can be dragged out, not folders."))
        base_names = [Path(e.name).name.casefold() for e in chosen]
        twice = sorted({Path(e.name).name for e, b in zip(chosen, base_names) if base_names.count(b) > 1})
        if twice:
            raise DragRefused(self.tr("Two of these files are both called %s, so they cannot be dropped together. "
                                      "Drag them one at a time.") % ", ".join(twice))
        if not self._listing.ledger_backed:
            self._check_foreign_dragable(archive)
        work, seconds = self._drag_cost(chosen, archive)
        if work > DRAG_LIMIT or seconds > DRAG_SECONDS:
            raise DragRefused(self.tr(
                "Dragging these out would unpack %(size)s first (about %(time)s), too much to do while you hold the "
                "mouse button. Tick them and press “Restore selected” instead.")
                % {"size": fmt_size(work), "time": fmt_eta(max(seconds, 1.0))})
        if is_reparse_point(_DRAG_TEMP_ROOT):
            raise DragRefused(self.tr("The folder used for dragging files out is not an ordinary folder, so nothing "
                                      "was unpacked into it."))
        self._prune_drag_stages()
        _DRAG_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=_DRAG_PREFIX, dir=_DRAG_TEMP_ROOT))
        self._drag_stages.append((stage, time.time()))
        # The unpack's working files go in a folder of its own, so the guard can count all of them (a shared temp folder
        # also holds other jobs' files, and an unpack makes folders of several names). Removed when the unpack ends.
        scratch = Path(tempfile.mkdtemp(prefix=_DRAG_PREFIX + "work-", dir=_DRAG_TEMP_ROOT))
        ctx = StageContext(temp_dir=scratch)
        guard = _DragGuard(ctx.cancel, stage, scratch, DRAG_LIMIT, DRAG_DEADLINE_S)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with guard:
                engine.extract_selected(archive, [e.name for e in chosen], stage, ctx, self._password)
            if guard.reason:                     # it finished just as the guard tripped: do not trust it
                raise DragRefused("")
        except BaseException as exc:
            self._drag_stages = [(p, t) for p, t in self._drag_stages if p != stage]
            rmtree_force(stage)                  # no half-unpacked folder is left behind
            if guard.reason:                     # stopped by the guard: say so, whatever error the cancel caused
                raise DragRefused(self.tr(
                    "Unpacking these files was stopped: it was taking too long or writing far more than the archive "
                    "says. Tick them and press “Restore selected” instead.")) from exc
            raise
        finally:
            QApplication.restoreOverrideCursor()
            rmtree_force(scratch)
        from excmp.safepath import resolve_within
        paths = [resolve_within(stage, e.name) for e in chosen]
        if not all(p.is_file() for p in paths):
            raise DragRefused(self.tr("Some of the files could not be unpacked."))
        return paths

    def _drag_mime(self, items) -> QMimeData | None:
        """What Qt hands Explorer when rows are dragged: the unpacked files, as file URLs. None (nothing is dragged)
        when it cannot be done; the reason is said under the list."""
        names = [it.data(self.COL_NAME, Qt.ItemDataRole.UserRole) for it in items
                 if it.flags() & Qt.ItemFlag.ItemIsUserCheckable]            # folder rows are not checkable
        try:
            if not names:
                raise DragRefused(self.tr("Only files can be dragged out, not folders."))
            paths = self.stage_for_drag(names)
        except DragRefused as exc:
            self._say_drag(str(exc))
            return None
        except Exception as exc:                                              # noqa: BLE001 (say it, never crash a drag)
            first = next((ln.strip() for ln in str(exc).splitlines() if ln.strip()), type(exc).__name__)
            self._say_drag(self.tr("Could not unpack these files for dragging: %s Try “Restore selected”.")
                           % first[:240].rstrip(".") + ".")
            return None
        self._show_drag_hint(True)                     # an earlier refusal no longer applies
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        return mime

    def _prune_drag_stages(self) -> None:
        """Before a new drag: remove staging folders that are old, and keep few. A recent one stays, because Explorer may
        still be copying out of it (deleting it under the copy lost a file in review)."""
        from excmp.tempclean import rmtree_force
        now = time.time()
        keep = []
        for stage, made in self._drag_stages:
            if now - made > _STAGE_MAX_AGE_S:
                rmtree_force(stage)
            else:
                keep.append((stage, made))
        while len(keep) > _KEEP_STAGES - 1:            # room for the one about to be made
            rmtree_force(keep.pop(0)[0])
        self._drag_stages = keep

    def cleanup_drag(self) -> None:
        """Remove every staging folder this tab made (the app is closing, or the tab is going). Safe to call twice."""
        from excmp.tempclean import rmtree_force
        stages, self._drag_stages = self._drag_stages, []
        for stage, _made in stages:
            rmtree_force(stage)

    def set_archive(self, path: Path) -> None:
        self.contents.clear()
        self._listing = None
        self._listing_for = None
        self._reading = False
        # A password was given for one archive. Carrying it to the next
        # silently tries a user's secret against a file they never offered
        # it for.
        self._password = None
        self._pending = None
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
            if self._needs_password():
                self._ask_password("extract", archive)
                return
            self.progress.setVisible(True)
            self.progress.setValue(0)
            self.extractRequested.emit(archive, dest)

    def _is_own_drag(self, event) -> bool:
        """Our own drag-out released over our own window: the files are staged copies, not an archive to open."""
        return event.source() is self.contents

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_own_drag(event):
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._is_own_drag(event):
            return
        paths = [p for p in paths_from_mime(event.mimeData()) if p.is_file()]
        if paths:
            self.set_archive(paths[0])
            event.acceptProposedAction()
