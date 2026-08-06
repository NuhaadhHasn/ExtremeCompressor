"""The always-visible job queue.

HandBrake hides its queue behind a menu item, and its most-upvoted issue is
people asking where their jobs went. This one lives in the app's Activity tab
and never moves. Each row expands into the tool's real output, so a job that
takes an hour is never a mystery box.

Two shape decisions, both from UI v3 wave 2:

**Density (W2-7).** Profile and Size used to own two columns of two short
words each — more width than the progress bar itself — while the job name,
the only thing anyone scans for, was squeezed. They fold into a second line
under the name, and the progress column drops 150px to 110px. The whole table
now fits inside 860 logical pixels of width.

**It fills its host.** The old ``_adjust_height`` grew the table row by row
and capped it at 430px, because the queue shared one scrolling column with
the drop zone, the analysis card and the chooser — an empty queue would
otherwise have pushed the results panel off the bottom of the window. On its
own tab that arithmetic has nothing left to protect, so the table simply
takes the space it is given and scrolls internally.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QPlainTextEdit,
                               QProgressBar, QPushButton, QSizePolicy,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..format import fmt_duration, fmt_eta, fmt_size
from ..models import Job, JobKind, JobState
from ..theme import repolish

COL_NAME, COL_PROGRESS, COL_ETA, COL_STATE, COL_ACTIONS = range(5)

_PROGRESS_WIDTH = 110

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
    # (job_id, global QPoint). The table knows rows; the WINDOW knows jobs,
    # output paths and slots - so it builds the menu (W1-8).
    menuRequested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, _JobRow] = {}
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

        self.setColumnCount(5)
        # "Time", not "Time left": finished rows show elapsed time in this
        # column, and an honesty-first app must not mislabel a number.
        self.setHeaderLabels([
            self.tr("Job"), self.tr("Progress"), self.tr("Time"),
            self.tr("State"), "",
        ])
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(False)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setAccessibleName(self.tr("Job queue"))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # W2-7: an empty grid is the worst possible answer to "did my job
        # register?". Painted on the viewport, the same idiom the log
        # expander already uses via setPlaceholderText.
        self.empty_hint = self.tr(
            "Nothing running yet.\nJobs you start on the Compress tab appear "
            "here with live progress, and every row opens into the tool's own "
            "output.")

        header = self.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column in (COL_ETA, COL_STATE, COL_ACTIONS):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_PROGRESS, _PROGRESS_WIDTH)

    # -- rows --------------------------------------------------------------
    @staticmethod
    def _detail(job: Job) -> str:
        """The second line under the job name: what profile, and how big.

        Once a compress job finishes this is also where the before/after pair
        goes - it is the same fact, better told after the event.
        """
        kind = "extract" if job.kind is JobKind.EXTRACT else job.profile.value
        if job.state is JobState.DONE and job.kind is JobKind.COMPRESS and job.final_bytes:
            return (f"{kind}  ·  {fmt_size(job.orig_bytes)} → "
                    f"{fmt_size(job.final_bytes)}")
        return f"{kind}  ·  {fmt_size(job.orig_bytes)}" if job.orig_bytes else kind

    def _set_name(self, row_item: QTreeWidgetItem, job: Job) -> None:
        row_item.setText(COL_NAME, f"{job.display_name}\n{self._detail(job)}")

    def add_job(self, job: Job) -> None:
        item = QTreeWidgetItem(self)
        self._set_name(item, job)
        item.setToolTip(COL_NAME, "\n".join(str(p) for p in job.inputs))
        item.setText(COL_ETA, "—")
        item.setText(COL_STATE, job.state.label)

        # The bar goes in a centering holder, not straight into the cell.
        # Since W2-7 made rows two lines tall, an item widget dropped into the
        # cell stretches to fill it - the 10px bar rendered as a 55px slab of
        # flat colour. QSS `height` does not constrain a laid-out QProgressBar;
        # only setFixedHeight does.
        bar = QProgressBar(self)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setAccessibleName(self.tr("Progress for %s") % job.display_name)
        holder = QWidget(self)
        holder.setObjectName("Plain")
        holder_box = QVBoxLayout(holder)
        holder_box.setContentsMargins(0, 0, 8, 0)
        holder_box.addWidget(bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setItemWidget(item, COL_PROGRESS, holder)

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
        self.viewport().update()

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
        self._set_name(row.item, job)
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
                    COL_STATE, self.tr("Done · %d%% saved") % round(job.saved_fraction * 100))
        elif job.state in (JobState.FAILED, JobState.CANCELLED):
            row.item.setText(COL_ETA, "—")
            if job.error:
                row.item.setToolTip(COL_STATE, job.error)
                row.item.setExpanded(True)

    def _on_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        if item.parent() is not None:       # the log child row -> its job
            item = item.parent()
        for job_id, row in self._rows.items():
            if row.item is item:
                self.menuRequested.emit(job_id, self.viewport().mapToGlobal(pos))
                return

    def show_log(self, job_id: str) -> None:
        row = self._rows.get(job_id)
        if row is not None:
            row.item.setExpanded(True)
            self.scrollToItem(row.child)

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
        self.viewport().update()

    # -- the empty state (W2-7) ---------------------------------------------
    def _should_paint_hint(self) -> bool:
        return not self._rows

    def paintEvent(self, event) -> None:   # noqa: N802 - Qt naming
        super().paintEvent(event)
        if not self._should_paint_hint():
            return
        painter = QPainter(self.viewport())
        color = self.palette().text().color()
        color.setAlpha(150)                     # muted without a theme lookup
        painter.setPen(color)
        rect = self.viewport().rect().adjusted(32, 0, -32, 0)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter
                                   | Qt.TextFlag.TextWordWrap), self.empty_hint)
        painter.end()
