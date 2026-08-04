"""The results screen.

Two rules govern what this panel is allowed to say.

**No invented numbers.** The pipeline produces one solid archive, so there
is no such thing as "movie.mp4 compressed to 4.1 MB" - that number does not
exist and will not be fabricated. Per-type bars therefore show *input*
bytes split into what was compressed and what was stored verbatim, and the
single real output figure is shown once, for the archive as a whole.

**Always explain the zeroes.** Every stored file gets the planner's own
one-line reason. This is the thing no other archiver does, and it is the
reason this project exists.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..format import fmt_duration, fmt_percent, fmt_size
from ..models import Job, JobKind, JobState
from ..suggest import CATEGORY_LABELS, AnalysisSummary, store_explanations
from ..theme import repolish, tokens
from .bars import CATEGORY_COLORS, BeforeAfterBar, StackedBar

_MAX_EXPLANATIONS = 6


class ResultsPanel(QFrame):
    """Shown when a job finishes; hidden the moment a new one is queued."""

    openFolderRequested = Signal(object)   # Path
    dismissed = Signal()

    def __init__(self, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("tone", "accent")
        self._tokens = tokens(theme)
        self._output: Path | None = None
        self.setAccessibleName(self.tr("Results"))

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.setSpacing(12)

        self.hero = QLabel("", self)
        self.hero.setObjectName("Hero")
        self.hero.setWordWrap(True)
        # W1-8: the headline is the thing people paste into chats - let them.
        self.hero.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hero.customContextMenuRequested.connect(self._hero_menu)
        column.addWidget(self.hero)

        self.subline = QLabel("", self)
        self.subline.setObjectName("HeroSub")
        self.subline.setWordWrap(True)
        column.addWidget(self.subline)

        self.bars = BeforeAfterBar(self)
        column.addWidget(self.bars)

        self._breakdown_title = QLabel(self.tr("Where the bytes went"), self)
        self._breakdown_title.setObjectName("Title")
        column.addWidget(self._breakdown_title)

        self._breakdown = QWidget(self)
        self._breakdown.setObjectName("Plain")
        self._breakdown_grid = QGridLayout(self._breakdown)
        self._breakdown_grid.setContentsMargins(0, 0, 0, 0)
        self._breakdown_grid.setHorizontalSpacing(12)
        self._breakdown_grid.setVerticalSpacing(8)
        self._breakdown_grid.setColumnStretch(2, 1)
        column.addWidget(self._breakdown)

        self._why_title = QLabel(self.tr("Why some files didn't shrink"), self)
        self._why_title.setObjectName("Title")
        column.addWidget(self._why_title)

        self._why = QWidget(self)
        self._why.setObjectName("Plain")
        self._why_column = QVBoxLayout(self._why)
        self._why_column.setContentsMargins(0, 0, 0, 0)
        self._why_column.setSpacing(6)
        column.addWidget(self._why)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton(self.tr("Open output folder"), self)
        self.open_button.setProperty("variant", "primary")
        self.open_button.clicked.connect(self._open_folder)
        self.again_button = QPushButton(self.tr("Compress something else"), self)
        self.again_button.clicked.connect(self.dismissed.emit)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.again_button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        self.setVisible(False)

    # -- public ------------------------------------------------------------
    def show_job(self, job: Job) -> None:
        self._output = job.out_path
        if job.state is JobState.FAILED:
            self._show_failure(job)
        elif job.kind is JobKind.EXTRACT:
            self._show_extract(job)
        else:
            self._show_compress(job)
        self.setVisible(True)

    def _hero_menu(self, pos) -> None:
        from PySide6.QtWidgets import QApplication, QMenu
        if not self.hero.text():
            return
        menu = QMenu(self)
        copy = menu.addAction(self.tr("Copy summary"))
        copy.triggered.connect(lambda: QApplication.clipboard().setText(
            f"{self.hero.text()} — {self.subline.text()}"))
        menu.exec(self.hero.mapToGlobal(pos))

    def hide_panel(self) -> None:
        self.setVisible(False)

    # -- variants ----------------------------------------------------------
    def _show_compress(self, job: Job) -> None:
        saved = job.saved_bytes
        self.hero.setText(
            self.tr("You saved %s (%s)") % (fmt_size(saved),
                                            fmt_percent(job.saved_fraction)))
        self.hero.setProperty("tone", "ok" if saved > 0 else "warn")
        repolish(self.hero)

        self.subline.setText(
            self.tr("%s → %s · %s profile · %s") % (
                fmt_size(job.orig_bytes), fmt_size(job.final_bytes),
                job.profile.value, fmt_duration(job.elapsed_s)))
        self.hero.setAccessibleName(f"{self.hero.text()}. {self.subline.text()}")

        self.bars.setVisible(True)
        self.bars.set_sizes(job.orig_bytes, job.final_bytes,
                            self._tokens["ok"], self._tokens["border_hi"])

        summary = job.summary if isinstance(job.summary, AnalysisSummary) else None
        self._fill_breakdown(summary)
        self._fill_reasons(summary)
        self.open_button.setVisible(True)

    def _show_extract(self, job: Job) -> None:
        restored = getattr(job.result, "files_restored", 0)
        verified = getattr(job.result, "verified", 0)
        self.hero.setText(self.tr("Restored 1 file") if restored == 1
                          else self.tr("Restored %d files") % restored)
        self.hero.setProperty("tone", "ok")
        repolish(self.hero)
        self.subline.setText(
            self.tr("%d SHA-256 hashes verified — byte-identical to the originals · %s")
            % (verified, fmt_duration(job.elapsed_s)))
        self.bars.setVisible(False)
        self._clear_breakdown()
        self._clear_reasons()
        self._breakdown_title.setVisible(False)
        self._why_title.setVisible(False)
        self.open_button.setVisible(True)

    def _show_failure(self, job: Job) -> None:
        self.hero.setText(self.tr("That job failed"))
        self.hero.setProperty("tone", "danger")
        repolish(self.hero)
        self.subline.setText(job.error or self.tr("No further detail was reported."))
        self.bars.setVisible(False)
        self._clear_breakdown()
        self._clear_reasons()
        self._breakdown_title.setVisible(False)
        self._why_title.setVisible(False)
        self.open_button.setVisible(False)

    # -- sections ----------------------------------------------------------
    def _clear_breakdown(self) -> None:
        while self._breakdown_grid.count():
            item = self._breakdown_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_reasons(self) -> None:
        while self._why_column.count():
            item = self._why_column.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _fill_breakdown(self, summary: AnalysisSummary | None) -> None:
        self._clear_breakdown()
        if summary is None or not summary.total_bytes:
            self._breakdown_title.setVisible(False)
            self._breakdown.setVisible(False)
            return
        self._breakdown_title.setVisible(True)
        self._breakdown.setVisible(True)

        note = QLabel(self.tr(
            "Input bytes by type. The archive is one solid block, so there is no "
            "honest per-file output size to quote — only the total above."), self)
        note.setObjectName("Subtitle")
        note.setWordWrap(True)
        self._breakdown_grid.addWidget(note, 0, 0, 1, 4)

        for row, (category, size) in enumerate(summary.ranked_categories(), start=1):
            stored = summary.store_by_category.get(category, 0)
            compressed = max(0, size - stored)
            color = CATEGORY_COLORS.get(category, self._tokens["accent"])
            label = CATEGORY_LABELS.get(category, str(category))

            name = QLabel(label, self)
            size_label = QLabel(fmt_size(size), self)
            size_label.setObjectName("Muted")

            bar = StackedBar(12, self)
            bar.set_segments([
                (f"{label}: {fmt_size(compressed)} compressed", float(compressed), color),
                (f"{label}: {fmt_size(stored)} stored as-is", float(stored),
                 self._tokens["surface3"]),
            ])

            if stored and not compressed:
                caption = self.tr("all stored as-is")
            elif stored:
                caption = self.tr("%s compressed · %s stored as-is") % (
                    fmt_size(compressed), fmt_size(stored))
            else:
                caption = self.tr("all compressed")
            detail = QLabel(caption, self)
            detail.setObjectName("Subtitle")
            # W1-10: the widest label in the app (899px unwrapped) - it alone
            # forced a horizontal scrollbar at 910px logical width.
            detail.setWordWrap(True)

            for widget in (name, size_label, bar, detail):
                widget.setAccessibleName(f"{label}, {fmt_size(size)}, {caption}")
            self._breakdown_grid.addWidget(name, row, 0)
            self._breakdown_grid.addWidget(size_label, row, 1)
            self._breakdown_grid.addWidget(bar, row, 2)
            self._breakdown_grid.addWidget(detail, row, 3)

    def _fill_reasons(self, summary: AnalysisSummary | None) -> None:
        self._clear_reasons()
        explanations = store_explanations(summary, _MAX_EXPLANATIONS) if summary else []
        if not explanations:
            self._why_title.setVisible(False)
            self._why.setVisible(False)
            return
        self._why_title.setVisible(True)
        self._why.setVisible(True)

        for name, reason in explanations:
            line = QLabel(f"ⓘ  <b>{name}</b> — {reason}", self)
            line.setTextFormat(Qt.TextFormat.RichText)
            line.setWordWrap(True)
            line.setObjectName("Subtitle")
            line.setAccessibleName(f"{name}: {reason}")
            self._why_column.addWidget(line)

        hidden = len(summary.store_files) - len(explanations) if summary else 0
        if hidden > 0:
            more = QLabel(
                self.tr("…and 1 more file stored for the same reason.") if hidden == 1
                else self.tr("…and %d more files stored for the same reasons.") % hidden,
                self)
            more.setObjectName("Muted")
            self._why_column.addWidget(more)

    # -- actions -----------------------------------------------------------
    def _open_folder(self) -> None:
        if self._output is not None:
            self.openFolderRequested.emit(self._output)
