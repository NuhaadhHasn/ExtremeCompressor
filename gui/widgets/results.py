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
from ..theme import CARD_MARGINS, GAP_INTRA, repolish, tokens
from .bars import CATEGORY_COLORS, BeforeAfterBar, StackedBar

# W2-3: three lines, then "show all N". Six wrapped explanations plus their
# heading were 180px of a panel that has to fit inside a ~320px viewport at
# 150% scaling - and the fourth reason is nearly always a repeat of the third.
_MAX_EXPLANATIONS = 3


class ResultsPanel(QFrame):
    """Shown when a job finishes; hidden the moment a new one is queued.

    Compact by construction (W2-3): the headline and its subline share a row,
    the before/after bars are a two-column grid rather than four stacked
    rows, and "Where the bytes went" starts collapsed. What never collapses
    is the list of files that did not shrink and why - that is the reason the
    project exists, and hiding it behind a click would be hiding the answer.
    """

    openFolderRequested = Signal(object)   # Path
    dismissed = Signal()

    def __init__(self, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._tokens = tokens(theme)
        self._output: Path | None = None
        self._explanations: list[tuple[str, str]] = []
        self._show_all = False
        self.setAccessibleName(self.tr("Results"))

        column = QVBoxLayout(self)
        column.setContentsMargins(*CARD_MARGINS)
        column.setSpacing(GAP_INTRA)

        # Headline and subline on ONE row (Windows title/subtitle pattern):
        # two stacked rows cost 28px that the 150% budget does not have.
        head = QHBoxLayout()
        head.setSpacing(GAP_INTRA)
        self.hero = QLabel("", self)
        self.hero.setObjectName("Hero")
        self.hero.setWordWrap(True)
        # W1-8: the headline is the thing people paste into chats - let them.
        self.hero.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hero.customContextMenuRequested.connect(self._hero_menu)
        head.addWidget(self.hero, 0, Qt.AlignmentFlag.AlignBottom)

        self.subline = QLabel("", self)
        self.subline.setObjectName("HeroSub")
        self.subline.setWordWrap(True)
        head.addWidget(self.subline, 1, Qt.AlignmentFlag.AlignBottom)
        column.addLayout(head)

        self.bars = BeforeAfterBar(self)
        column.addWidget(self.bars)

        # Collapsed by default: the per-category split is the "tell me more"
        # answer, not the answer.
        self.breakdown_toggle = QPushButton("", self)
        self.breakdown_toggle.setObjectName("SectionToggle")
        self.breakdown_toggle.setCheckable(True)
        self.breakdown_toggle.toggled.connect(self._set_breakdown_open)
        column.addWidget(self.breakdown_toggle)

        self._breakdown = QWidget(self)
        self._breakdown.setObjectName("Plain")
        self._breakdown_grid = QGridLayout(self._breakdown)
        self._breakdown_grid.setContentsMargins(0, 0, 0, 0)
        self._breakdown_grid.setHorizontalSpacing(12)
        self._breakdown_grid.setVerticalSpacing(GAP_INTRA)
        self._breakdown_grid.setColumnStretch(2, 1)
        self._breakdown.setVisible(False)
        column.addWidget(self._breakdown)

        why_head = QHBoxLayout()
        why_head.setSpacing(GAP_INTRA)
        self._why_title = QLabel(self.tr("Why some files didn't shrink"), self)
        self._why_title.setObjectName("Title")
        why_head.addWidget(self._why_title)
        why_head.addStretch(1)
        # The expander shares the heading's row - a button on its own line was
        # 28px spent on one word.
        self.more_button = QPushButton("", self)
        self.more_button.setObjectName("SectionToggle")
        self.more_button.clicked.connect(self._toggle_all_reasons)
        self.more_button.setVisible(False)
        why_head.addWidget(self.more_button)
        self._why_head = why_head
        column.addLayout(why_head)

        self._why = QWidget(self)
        self._why.setObjectName("Plain")
        self._why_column = QVBoxLayout(self._why)
        self._why_column.setContentsMargins(0, 0, 0, 0)
        self._why_column.setSpacing(4)
        column.addWidget(self._why)

        buttons = QHBoxLayout()
        buttons.setSpacing(GAP_INTRA)
        self.open_button = QPushButton(self.tr("Open output folder"), self)
        self.open_button.setProperty("variant", "primary")
        self.open_button.clicked.connect(self._open_folder)
        self.again_button = QPushButton(self.tr("Compress something else"), self)
        self.again_button.clicked.connect(self.dismissed.emit)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.again_button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        self._set_breakdown_open(False)
        self.setVisible(False)

    # -- public ------------------------------------------------------------
    def explanation_count(self) -> int:
        """How many "why it didn't shrink" lines are on screen right now."""
        return sum(1 for i in range(self._why_column.count())
                   if self._why_column.itemAt(i).widget() is not None
                   and self._why_column.itemAt(i).widget().property("explains"))

    def show_job(self, job: Job) -> None:
        self._output = job.out_path
        self._show_all = False
        if job.state is JobState.FAILED:
            self._show_failure(job)
        elif job.kind is JobKind.VERIFY:
            self._show_verify(job)
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
        self.again_button.setText(self.tr("Compress something else"))
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
        self.breakdown_toggle.setVisible(False)
        self._breakdown.setVisible(False)
        self._why_title.setVisible(False)
        self.more_button.setVisible(False)
        self.open_button.setVisible(True)

    def _show_verify(self, job: Job) -> None:
        """A verification that passed. The headline says how many files were
        actually re-read, not "OK" - the number is the evidence, and a bare
        "OK" is what every archiver already says without checking."""
        verified = getattr(job.result, "verified", 0)
        self.hero.setText(self.tr("Verified 1 file") if verified == 1
                          else self.tr("Verified %d files") % verified)
        self.hero.setProperty("tone", "ok")
        repolish(self.hero)
        self.subline.setText(self.tr(
            "Every file was restored to a temporary folder and its SHA-256 "
            "compared with the archive’s ledger · %s · nothing was written "
            "to disk") % fmt_duration(job.elapsed_s))
        self.hero.setAccessibleName(f"{self.hero.text()}. {self.subline.text()}")
        self.bars.setVisible(False)
        self._clear_breakdown()
        self._clear_reasons()
        self.breakdown_toggle.setVisible(False)
        self._breakdown.setVisible(False)
        self._why_title.setVisible(False)
        self.more_button.setVisible(False)
        # Nothing was produced, so there is no folder worth opening - and
        # "Compress something else" is a non-sequitur after a verification.
        self.open_button.setVisible(False)
        self.again_button.setText(self.tr("Done"))

    def _show_failure(self, job: Job) -> None:
        self.hero.setText(self.tr("That job failed"))
        self.hero.setProperty("tone", "danger")
        repolish(self.hero)
        self.subline.setText(job.error or self.tr("No further detail was reported."))
        self.bars.setVisible(False)
        self._clear_breakdown()
        self._clear_reasons()
        self.breakdown_toggle.setVisible(False)
        self._breakdown.setVisible(False)
        self._why_title.setVisible(False)
        self.more_button.setVisible(False)
        self.open_button.setVisible(False)

    # -- sections ----------------------------------------------------------
    def _set_breakdown_open(self, open_: bool) -> None:
        """Text carries the state (▸/▾ plus the word), never the arrow alone."""
        self.breakdown_toggle.setText(
            self.tr("▾  Where the bytes went") if open_
            else self.tr("▸  Where the bytes went"))
        self.breakdown_toggle.setAccessibleName(
            self.tr("Where the bytes went, expanded") if open_
            else self.tr("Where the bytes went, collapsed"))
        self._breakdown.setVisible(open_ and self._breakdown_grid.count() > 0)

    def _toggle_all_reasons(self) -> None:
        self._show_all = not self._show_all
        self._render_reasons()

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
            self.breakdown_toggle.setVisible(False)
            self._breakdown.setVisible(False)
            return
        self.breakdown_toggle.setVisible(True)

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
        self._set_breakdown_open(self.breakdown_toggle.isChecked())

    def _fill_reasons(self, summary: AnalysisSummary | None) -> None:
        self._explanations = (
            store_explanations(summary, len(summary.store_files)) if summary else [])
        self._render_reasons()

    def _render_reasons(self) -> None:
        """Three lines by default, all of them behind "Show all N".

        The cap is a height decision, not an honesty one: the total is always
        stated in the button, so nothing is ever silently dropped.
        """
        self._clear_reasons()
        total = len(self._explanations)
        if not total:
            self._why_title.setVisible(False)
            self.more_button.setVisible(False)
            self._why.setVisible(False)
            return
        self._why_title.setVisible(True)
        self._why.setVisible(True)

        shown = self._explanations if self._show_all \
            else self._explanations[:_MAX_EXPLANATIONS]
        for name, reason in shown:
            line = QLabel(f"ⓘ  <b>{name}</b> — {reason}", self)
            line.setTextFormat(Qt.TextFormat.RichText)
            line.setWordWrap(True)
            line.setObjectName("Subtitle")
            line.setProperty("explains", True)
            line.setAccessibleName(f"{name}: {reason}")
            self._why_column.addWidget(line)

        self.more_button.setVisible(total > _MAX_EXPLANATIONS)
        self.more_button.setText(
            self.tr("Show fewer") if self._show_all
            else self.tr("Show all %d") % total)
        self.more_button.setAccessibleName(
            self.tr("Showing %d of %d stored files") % (len(shown), total))

    # -- actions -----------------------------------------------------------
    def _open_folder(self) -> None:
        if self._output is not None:
            self.openFolderRequested.emit(self._output)
