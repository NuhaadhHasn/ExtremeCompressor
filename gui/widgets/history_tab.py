"""I3 — the History tab: what you compressed, and what it cost.

The queue forgets a job the moment you tidy it away. This does not, and it is
the one record the app is uniquely placed to keep: it knows the profile, the
resolved chain, the real elapsed time and the achieved ratio for every job that
has ever run on this machine.

Two things make it worth a tab rather than a log line:

**"Compress again" reproduces the settings**, not just the paths. A remembered
job without its profile is a job you rebuild by hand, which is most of the work
you were trying to avoid.

**Failed jobs are kept too.** Knowing what did not work, and why, is worth as
much as knowing what did - and a history that quietly drops the failures is a
history that flatters the tool.

An encrypted job shows that it *was* encrypted and nothing more. The password
is never recorded anywhere, so "Compress again" re-prompts; a history file that
outlives the session must not carry a secret that outlives it too.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..format import fmt_size
from ..history import HistoryEntry, clear, load

_COLUMNS = ("Archive", "Profile", "Size", "Saved", "Took", "When", "")


class HistoryTab(QWidget):
    """Past jobs, newest first."""

    #: Emitted with the entry the user wants to run again.
    compressAgain = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        self._caption = QLabel("", self)
        self._caption.setObjectName("Subtitle")
        self._caption.setWordWrap(True)
        head.addWidget(self._caption, 1)

        self.forget_button = QPushButton(self.tr("Forget all"), self)
        self.forget_button.setAccessibleDescription(
            self.tr("Delete every remembered job. The archives are untouched."))
        self.forget_button.clicked.connect(self._forget)
        head.addWidget(self.forget_button)
        layout.addLayout(head)

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels([self.tr(c) for c in _COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName(self.tr("Past jobs"))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.refresh()

    # -- data ---------------------------------------------------------------
    def refresh(self) -> None:
        entries = load()
        self.table.setRowCount(0)
        for entry in entries:
            self._add_row(entry)
        self.forget_button.setEnabled(bool(entries))
        self._caption.setText(
            self.tr("Nothing here yet. Finished jobs appear after you clear "
                    "them from the queue.") if not entries else
            self.tr("%d past job(s). Archives are never touched by anything "
                    "on this page.") % len(entries))

    def _add_row(self, entry: HistoryEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        name = entry.archive.replace("\\", "/").rsplit("/", 1)[-1]
        # The lock is a fact about the job, not a hint about the password -
        # which is not recorded and never will be.
        if entry.encrypted:
            name = f"{name}  " + self.tr("(encrypted)")
        cells = [
            name,
            entry.profile,
            # A failed job produced no archive, and "3.7 GB -> 0 B" reads as
            # though it compressed to nothing rather than as though it never
            # finished. Show only what went in.
            (f"{fmt_size(entry.orig_bytes)} → {fmt_size(entry.final_bytes)}"
             if entry.state == "done" and entry.final_bytes
             else fmt_size(entry.orig_bytes)),
            (f"{entry.saved_percent:.1f}%" if entry.state == "done"
             else self.tr("—")),
            f"{entry.elapsed_s:.0f}s" if entry.elapsed_s else self.tr("—"),
            entry.finished_at.replace("T", " "),
        ]
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if entry.state != "done":
                # Never colour alone: the state is spelled out in the tooltip
                # and the Saved column already reads as a dash.
                item.setToolTip(self.tr("This job %s: %s")
                                % (entry.state, entry.error or self.tr("no detail")))
            self.table.setItem(row, column, item)

        again = QPushButton(self.tr("Compress again"), self.table)
        again.setAccessibleDescription(
            self.tr("Queue this job again with the same settings"))
        again.clicked.connect(lambda _c=False, e=entry: self.compressAgain.emit(e))
        self.table.setCellWidget(row, len(_COLUMNS) - 1, again)

    def _forget(self) -> None:
        clear()
        self.refresh()
