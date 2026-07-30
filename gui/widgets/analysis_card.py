"""The analysis card: what you dropped, and what can actually happen to it.

This is where the app earns its keep. Before a single byte is compressed it
states the composition of the pile, how much of it is physically capable of
shrinking, and - when the answer is "not much" - says so in one sentence
instead of letting the user find out three hours later.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from ..suggest import CATEGORY_LABELS, AnalysisSummary, gain_note, headline, shrink_mode_hint
from ..theme import repolish
from .bars import CategoryBreakdown


class AnalysisCard(QFrame):
    """Populated from an :class:`AnalysisSummary` computed off-thread."""

    shrinkModeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAccessibleName(self.tr("Analysis summary"))

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(self.tr("What you dropped"), self)
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch(1)
        self._status = QLabel("", self)
        self._status.setObjectName("Muted")
        header.addWidget(self._status)
        column.addLayout(header)

        self._headline = QLabel("", self)
        self._headline.setWordWrap(True)
        column.addWidget(self._headline)

        self._breakdown = CategoryBreakdown(self)
        column.addWidget(self._breakdown)

        self._gain = QLabel("", self)
        self._gain.setWordWrap(True)
        column.addWidget(self._gain)

        self._hint = QLabel("", self)
        self._hint.setObjectName("Subtitle")
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)
        column.addWidget(self._hint)

        # Greyed out until Phase C ships the re-encoder. Shown rather than
        # hidden so the answer to "can it make my videos smaller?" is visible
        # and honest, instead of absent.
        self.shrink_toggle = QCheckBox(
            self.tr("Shrink mode: re-encode video/audio (coming later)"), self)
        self.shrink_toggle.setEnabled(False)
        self.shrink_toggle.setToolTip(self.tr(
            "Lossy AV1/Opus re-encoding. Not implemented yet — when it lands it "
            "will always be opt-in and will never touch your originals."))
        self.shrink_toggle.setAccessibleDescription(self.shrink_toggle.toolTip())
        column.addWidget(self.shrink_toggle)

        self._warnings = QLabel("", self)
        self._warnings.setObjectName("Mono")
        self._warnings.setWordWrap(True)
        self._warnings.setVisible(False)
        column.addWidget(self._warnings)

        self.setVisible(False)

    # -- states ------------------------------------------------------------
    def set_busy(self, count: int) -> None:
        self.setVisible(True)
        self._status.setText(self.tr("analyzing…"))
        self._headline.setText(
            self.tr("Reading 1 item: detecting types and sampling entropy…")
            if count == 1 else
            self.tr("Reading %d items: detecting types and sampling entropy…") % count)
        self._gain.setText("")
        self._hint.setVisible(False)
        self._warnings.setVisible(False)

    def set_error(self, message: str) -> None:
        self.setVisible(True)
        self._status.setText(self.tr("failed"))
        self._headline.setText(self.tr("Could not analyze these files."))
        self._gain.setText(message)
        self._gain.setProperty("tone", "danger")
        repolish(self._gain)

    def set_summary(self, summary: AnalysisSummary) -> None:
        self.setVisible(True)
        self._status.setText("")
        self._headline.setText(headline(summary))
        self._headline.setAccessibleName(headline(summary))
        self._breakdown.set_data(summary.ranked_categories(), summary.total_bytes,
                                 CATEGORY_LABELS)

        self._gain.setText(gain_note(summary))
        # The tone is a *second* signal on top of the sentence, never the
        # only one - the text says everything the colour does.
        self._gain.setProperty("tone", "warn" if summary.store_fraction >= 0.85 else "ok")
        repolish(self._gain)

        hint = shrink_mode_hint(summary)
        self._hint.setText(hint or "")
        self._hint.setVisible(bool(hint))

        if summary.warnings:
            self._warnings.setText("\n".join(f"· {w}" for w in summary.warnings))
            self._warnings.setVisible(True)
        else:
            self._warnings.setVisible(False)

    def clear(self) -> None:
        self.setVisible(False)
