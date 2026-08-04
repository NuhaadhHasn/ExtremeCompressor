"""The always-visible job queue.

HandBrake hides its queue behind a menu item, and its most-upvoted issue is
people asking where their jobs went. This one lives in the main window and
never moves. Each row expands into the tool's real output, so a job that
takes an hour is never a mystery box.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QPlainTextEdit,
                               QProgressBar, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QWidget)

from ..format import fmt_duration, fmt_eta, fmt_size
from ..models import Job, JobKind, JobState
from ..theme import repolish

COL_NAME, COL_PROFILE, COL_SIZE, COL_PROGRESS, COL_ETA, COL_STATE, COL_ACTIONS = range(7)

# The empty queue used to reserve a 120px featureless slab; on the 1366x768
# target that is a third of the 150%-scaled viewport spent saying nothing.
_MIN_TABLE_HEIGHT = 64
_MAX_TABLE_HEIGHT = 430

_STATE_TONE = {
    JobState.DONE: "ok",
    JobState.FAILED: "danger",
    JobState.CANCELLED: "warn",
}


class _JobRow:
    """Widgets belonging to one job, so updates don't rebuild the tree."""

    __slots__ = ("item", "child", "bar", "log", "cancel")

    def __init__(self, item: QTreeWidgetItem, child: QTreeWidgetItem,
                 bar: QProgressBar, log: QPlainTextEdit, cancel: QPushButton) -> None:
        self.item = item
        self.child = child
        self.bar = bar
        self.log = log
        self.cancel = cancel


class QueueTable(QTreeWidget):
    cancelRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, _JobRow] = {}

        self.setColumnCount(7)
        # "Time", not "Time left": finished rows show elapsed time in this
        # column, and an honesty-first app must not mislabel a number.
        self.setHeaderLabels([
            self.tr("Job"), self.tr("Profile"), self.tr("Size"),
            self.tr("Progress"), self.tr("Time"), self.tr("State"), "",
        ])
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(False)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setAccessibleName(self.tr("Job queue"))
        self.setMinimumHeight(_MIN_TABLE_HEIGHT)
        self.setMaximumHeight(_MIN_TABLE_HEIGHT)
        self.itemExpanded.connect(lambda _i: self._adjust_height())
        self.itemCollapsed.connect(lambda _i: self._adjust_height())

        header = self.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column in (COL_PROFILE, COL_SIZE, COL_ETA, COL_STATE, COL_ACTIONS):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_PROGRESS, 150)

    # -- rows --------------------------------------------------------------
    def add_job(self, job: Job) -> None:
        item = QTreeWidgetItem(self)
        item.setText(COL_NAME, job.display_name)
        item.setToolTip(COL_NAME, "\n".join(str(p) for p in job.inputs))
        item.setText(COL_PROFILE, self.tr("extract") if job.kind is JobKind.EXTRACT
                     else job.profile.value)
        item.setText(COL_SIZE, fmt_size(job.orig_bytes) if job.orig_bytes else "—")
        item.setText(COL_ETA, "—")
        item.setText(COL_STATE, job.state.label)

        bar = QProgressBar(self)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setAccessibleName(self.tr("Progress for %s") % job.display_name)
        self.setItemWidget(item, COL_PROGRESS, bar)

        actions = QWidget(self)
        actions.setObjectName("Plain")
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(4)
        # U+00D7, not a dingbat: it exists in every Windows UI font, so the
        # button never renders as an empty box.
        cancel = QPushButton("×", actions)
        # 28x28 with its own 2px padding rule (theme.py #CancelJob): the global
        # button padding of 7px 14px left a 0px content box in the old
        # fixedWidth(30), rendering the x as an empty pill.
        cancel.setObjectName("CancelJob")
        cancel.setFixedSize(28, 28)
        cancel.setProperty("variant", "danger")
        cancel.setAccessibleName(self.tr("Cancel %s") % job.display_name)
        cancel.setToolTip(self.tr("Cancel this job"))
        cancel.clicked.connect(lambda _=False, jid=job.id: self.cancelRequested.emit(jid))
        row.addStretch(1)
        row.addWidget(cancel)
        self.setItemWidget(item, COL_ACTIONS, actions)

        child = QTreeWidgetItem(item)
        child.setFirstColumnSpanned(True)
        log = QPlainTextEdit(self)
        log.setReadOnly(True)
        log.setMaximumHeight(140)
        log.setPlaceholderText(self.tr("Tool output appears here once the job starts."))
        log.setAccessibleName(self.tr("Log for %s") % job.display_name)
        self.setItemWidget(child, 0, log)

        self._rows[job.id] = _JobRow(item, child, bar, log, cancel)
        self.scrollToItem(item)
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Grow with the queue instead of leaving a slab of empty table.

        The queue is permanently on screen, so an empty one must not push the
        results panel off the bottom of the window.
        """
        rows = len(self._rows)
        expanded = sum(1 for row in self._rows.values() if row.item.isExpanded())
        wanted = self.header().height() + rows * 42 + expanded * 150 + 16
        self.setMaximumHeight(max(_MIN_TABLE_HEIGHT, min(wanted, _MAX_TABLE_HEIGHT)))

    def update_progress(self, job: Job) -> None:
        row = self._rows.get(job.id)
        if row is None:
            return
        row.bar.setValue(int(job.percent))
        row.bar.setAccessibleDescription(f"{int(job.percent)} percent")
        row.item.setText(COL_ETA, fmt_eta(job.eta_s) if job.state is JobState.RUNNING else "—")
        if job.stage:
            row.item.setText(COL_STATE, f"{job.state.label} · {job.stage}")

    def update_state(self, job: Job) -> None:
        row = self._rows.get(job.id)
        if row is None:
            return
        row.item.setText(COL_STATE, job.state.label)
        # Hidden, not merely disabled: a dead grey box in every finished row
        # is visual noise that means nothing.
        row.cancel.setVisible(not job.state.is_terminal)

        tone = _STATE_TONE.get(job.state, "")
        row.bar.setProperty("tone", tone)
        repolish(row.bar)

        if job.state is JobState.DONE:
            row.bar.setValue(100)
            row.item.setText(COL_ETA, self.tr("took %s") % fmt_duration(job.elapsed_s))
            if job.kind is JobKind.COMPRESS and job.final_bytes:
                row.item.setText(
                    COL_SIZE, f"{fmt_size(job.orig_bytes)} → {fmt_size(job.final_bytes)}")
                row.item.setText(
                    COL_STATE, self.tr("Done · %d%% saved") % round(job.saved_fraction * 100))
        elif job.state in (JobState.FAILED, JobState.CANCELLED):
            row.item.setText(COL_ETA, "—")
            if job.error:
                row.item.setToolTip(COL_STATE, job.error)
                row.item.setExpanded(True)

    def append_log(self, job_id: str, line: str) -> None:
        row = self._rows.get(job_id)
        if row is None:
            return
        row.log.appendPlainText(line)

    def clear_jobs(self, keep: set[str]) -> None:
        for job_id in [i for i in self._rows if i not in keep]:
            row = self._rows.pop(job_id)
            index = self.indexOfTopLevelItem(row.item)
            if index >= 0:
                self.takeTopLevelItem(index)
        self._adjust_height()
