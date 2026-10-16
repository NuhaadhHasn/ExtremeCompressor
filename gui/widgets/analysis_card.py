"""The analysis card: what you dropped, and what can actually happen to it.

This is where the app earns its keep. Before a single byte is compressed it
states the composition of the pile, how much of it is physically capable of
shrinking, and - when the answer is "not much" - says so in one sentence
instead of letting the user find out three hours later.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from ..suggest import CATEGORY_LABELS, AnalysisSummary, gain_note, headline, shrink_mode_hint
from ..theme import GAP_INTRA, repolish
from .bars import CategoryBreakdown
from .treemap import Treemap


class AnalysisCard(QFrame):
    """Populated from an :class:`AnalysisSummary` computed off-thread.

    Compacted in wave 2b from 200px to ~86px. Three things stay permanently
    on screen because they are the reason the app exists:

    * the headline - what this pile is, *including the per-type shares in
      words*, which is what lets the colour legend move into the expander
      without the bar becoming a colour-only signal;
    * the breakdown bar;
    * the gain note - how much can actually shrink.

    Everything else (the swatch legend, the shrink-mode answer, warnings)
    lives behind "Details". A "What you dropped" title also went: the headline
    beneath it said the same thing better, in the same 22px.
    """

    shrinkModeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAccessibleName(self.tr("Analysis summary"))

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 8, 16, 8)
        column.setSpacing(GAP_INTRA)

        # Headline, scan status and the details toggle share one row.
        header = QHBoxLayout()
        header.setSpacing(GAP_INTRA)
        self._headline = QLabel("", self)
        self._headline.setWordWrap(True)
        header.addWidget(self._headline, 1)
        self._status = QLabel("", self)
        self._status.setObjectName("Muted")
        header.addWidget(self._status)
        self.details_toggle = QPushButton("", self)
        self.details_toggle.setObjectName("SectionToggle")
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(self._set_details_open)
        header.addWidget(self.details_toggle)
        column.addLayout(header)

        # W2-8: the scan of the real HDD corpus takes minutes. Without a moving
        # bar and a file count the card looked identical from second one to
        # second two hundred, which reads as a hang - the single most common
        # reason people kill a working process.
        self.progress = QProgressBar(self)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.progress.setAccessibleName(self.tr("Analysis progress"))
        self.progress.setVisible(False)
        column.addWidget(self.progress)

        self._breakdown = CategoryBreakdown(self)
        column.addWidget(self._breakdown)

        self._gain = QLabel("", self)
        self._gain.setWordWrap(True)
        column.addWidget(self._gain)

        # -- the details disclosure -------------------------------------------
        self._details = QWidget(self)
        self._details.setObjectName("Plain")
        details = QVBoxLayout(self._details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(GAP_INTRA)

        self._legend_holder = self._breakdown.take_legend(self._details)
        details.addWidget(self._legend_holder)

        # I8: the same breakdown as an area, behind the same disclosure. It
        # answers the question people actually ask when told an archive saved
        # 3% - "what IS all this?" - and the bar above cannot, because a bar
        # 2% wide is invisible whatever it is labelled.
        self._treemap = Treemap(self._details)
        details.addWidget(self._treemap)

        self._hint = QLabel("", self._details)
        self._hint.setObjectName("Subtitle")
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)
        details.addWidget(self._hint)

        # Was a permanently disabled QCheckBox. A checkbox that can never be
        # ticked is a promise the UI cannot keep; the honest answer to "can it
        # make my videos smaller?" is a sentence, and it belongs next to the
        # per-type breakdown that prompts the question.
        self._shrink_note = QLabel(self.tr(
            "Shrink mode (lossy AV1/Opus re-encoding of video and audio) is not "
            "implemented yet. When it lands it will always be opt-in and will "
            "never touch your originals."), self._details)
        self._shrink_note.setObjectName("Subtitle")
        self._shrink_note.setWordWrap(True)
        details.addWidget(self._shrink_note)

        self._warnings = QLabel("", self._details)
        # Two sources feed one label, and they arrive at different times.
        self._notes: list[str] = []
        self._plan_warnings: list[str] = []
        self._warnings.setObjectName("Mono")
        self._warnings.setWordWrap(True)
        self._warnings.setVisible(False)
        details.addWidget(self._warnings)

        self._details.setVisible(False)
        column.addWidget(self._details)

        self._set_details_open(False)
        self.setVisible(False)

    # -- the disclosure ------------------------------------------------------
    def _set_details_open(self, open_: bool) -> None:
        self.details_toggle.setText(self.tr("Details ▾") if open_
                                    else self.tr("Details ▸"))
        self.details_toggle.setAccessibleName(
            self.tr("Analysis details, expanded") if open_
            else self.tr("Analysis details, collapsed"))
        self._details.setVisible(open_)

    # -- states ------------------------------------------------------------
    def status_text(self) -> str:
        return self._status.text()

    def headline_text(self) -> str:
        return self._headline.text()

    def gain_text(self) -> str:
        return self._gain.text()

    def set_busy(self, count: int) -> None:
        self.setVisible(True)
        # Indeterminate until the tree walk has counted the files: a bar that
        # claims 0 of 0 is worse than one that admits it does not know yet.
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._status.setText(self.tr("looking for files…"))
        self._headline.setText(
            self.tr("Reading 1 item: detecting types and sampling entropy…")
            if count == 1 else
            self.tr("Reading %d items: detecting types and sampling entropy…") % count)
        self._gain.setText("")
        self._hint.setVisible(False)
        self._warnings.setVisible(False)
        self.details_toggle.setVisible(False)

    def set_progress(self, done: int, total: int) -> None:
        """One tick per handful of files read. ``total`` is exact - it comes
        from the tree walk, not an estimate."""
        if total <= 0:
            return
        self.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self._status.setText(self.tr("scanning %d/%d") % (done, total))
        self.progress.setAccessibleDescription(
            self.tr("%d of %d files read") % (done, total))

    def set_error(self, message: str) -> None:
        self.setVisible(True)
        self.progress.setVisible(False)
        self.details_toggle.setVisible(False)
        self._status.setText(self.tr("failed"))
        self._headline.setText(self.tr("Could not analyze these files."))
        self._gain.setText(message)
        self._gain.setProperty("tone", "danger")
        repolish(self._gain)

    def set_summary(self, summary: AnalysisSummary) -> None:
        self.setVisible(True)
        self.progress.setVisible(False)
        self.details_toggle.setVisible(True)
        self._status.setText("")
        self._headline.setText(headline(summary))
        self._headline.setAccessibleName(headline(summary))
        self._treemap.set_breakdown(summary.by_category)
        self._breakdown.set_data(summary.ranked_categories(), summary.total_bytes,
                                 CATEGORY_LABELS)

        self._gain.setText(gain_note(summary))
        # The tone is a *second* signal on top of the sentence, never the
        # only one - the text says everything the colour does. So it reads
        # the sentence's own figure: what is stored as-is, not the store
        # route, which repacked Ogg and JPEGs ride too (B19 render check).
        self._gain.setProperty("tone", "warn" if summary.fixed_fraction >= 0.85 else "ok")
        repolish(self._gain)

        hint = shrink_mode_hint(summary)
        self._hint.setText(hint or "")
        self._hint.setVisible(bool(hint))

        self._plan_warnings = list(summary.warnings)
        self._render_warnings()

    def set_note(self, message: str) -> None:
        """A note from the analysis pass itself, not from the plan (K3).

        Kept apart from ``summary.warnings`` because the two arrive at
        different times: notes are emitted *while* files are being read and
        `set_summary` lands afterwards, so a single shared label meant the
        summary silently erased the fact that a file could not be read.
        """
        self._notes = [message] if message else []
        self._render_warnings()

    def _render_warnings(self) -> None:
        lines = [*self._notes, *self._plan_warnings]
        if lines:
            self._warnings.setText("\n".join(f"· {w}" for w in lines))
            self._warnings.setVisible(True)
        else:
            self._warnings.setVisible(False)

    def clear(self) -> None:
        self._notes = []
        self._plan_warnings = []
        self.setVisible(False)
