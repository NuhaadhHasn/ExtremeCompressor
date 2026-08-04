"""Proportional bars for the analysis and results screens.

Built from plain ``QFrame``s with layout stretch factors rather than a
``paintEvent`` - it costs nothing, scales correctly on HiDPI, and each
segment keeps a real accessible name.

Every bar is paired with a text legend. Colour alone never carries meaning
here: a user with deuteranopia, or one looking at a greyscale screenshot,
reads exactly the same information from the labels.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from excmp.analyzer import Category

from ..format import fmt_percent, fmt_size

# Distinct in both palettes and distinguishable in greyscale by lightness.
# CATEGORY_COLORS must not intersect theme tokens: TEXT used to equal the `ok`
# green and BINARY the `accent` blue, so an 86%-binary breakdown bar read as a
# progress bar and a text-heavy one as a success banner.
CATEGORY_COLORS: dict[Category, str] = {
    Category.VIDEO: "#8b5cf6",
    Category.AUDIO: "#ec4899",
    Category.IMAGE: "#f59e0b",
    Category.COMPRESSED_ARCHIVE: "#64748b",
    Category.EXECUTABLE: "#06b6d4",
    Category.TEXT: "#14b8a6",
    Category.BINARY: "#818cf8",
}
FALLBACK_COLOR = "#94a3b8"

_STRETCH_SCALE = 10_000


class StackedBar(QWidget):
    """One horizontal bar split into proportional coloured segments."""

    def __init__(self, height: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = height
        self.setObjectName("Plain")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(2)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_segments(self, segments: list[tuple[str, float, str]]) -> None:
        """``segments`` is ``[(accessible label, value, css colour), ...]``."""
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total = sum(max(0.0, value) for _label, value, _color in segments)
        if total <= 0:
            return
        for label, value, color in segments:
            if value <= 0:
                continue
            block = QFrame(self)
            block.setStyleSheet(
                f"background:{color}; border:none; border-radius:{self._height // 2}px;")
            block.setAccessibleName(label)
            block.setToolTip(label)
            block.setFixedHeight(self._height)
            self._row.addWidget(block, max(1, int(value / total * _STRETCH_SCALE)))


class CategoryBreakdown(QWidget):
    """A stacked bar plus its legend - what is in this pile of files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self._bar = StackedBar(14, self)
        column.addWidget(self._bar)
        self._legend = QWidget(self)
        self._legend.setObjectName("Plain")
        self._legend_row = QHBoxLayout(self._legend)
        self._legend_row.setContentsMargins(0, 0, 0, 0)
        self._legend_row.setSpacing(14)
        column.addWidget(self._legend)

    def set_data(self, ranked: list[tuple[Category, int]], total: int,
                 labels: dict[Category, str], limit: int = 4) -> None:
        from ..theme import repolish  # local import keeps this module Qt-only

        self._bar.set_segments([
            (f"{labels.get(c, str(c))}: {fmt_size(n)}", float(n),
             CATEGORY_COLORS.get(c, FALLBACK_COLOR))
            for c, n in ranked
        ])

        while self._legend_row.count():
            item = self._legend_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for category, size in ranked[:limit]:
            share = size / total if total else 0.0
            entry = QWidget(self._legend)
            entry.setObjectName("Plain")
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            swatch = QFrame(entry)
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background:{CATEGORY_COLORS.get(category, FALLBACK_COLOR)};"
                "border:none; border-radius:5px;")
            text = QLabel(f"{labels.get(category, str(category))} "
                          f"{fmt_percent(share)}", entry)
            text.setObjectName("Muted")
            row.addWidget(swatch)
            row.addWidget(text)
            entry.setAccessibleName(
                f"{labels.get(category, str(category))}: {fmt_size(size)}, "
                f"{fmt_percent(share)} of the total")
            self._legend_row.addWidget(entry)
            repolish(text)
        self._legend_row.addStretch(1)


class BeforeAfterBar(QWidget):
    """Two stacked rows: original size, then what the archive weighs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        grid = QVBoxLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self._before_label = QLabel(self)
        self._before_label.setObjectName("Muted")
        self._before = StackedBar(16, self)
        self._after_label = QLabel(self)
        self._after_label.setObjectName("Muted")
        self._after = StackedBar(16, self)
        for widget in (self._before_label, self._before,
                       self._after_label, self._after):
            grid.addWidget(widget)

    def set_sizes(self, before: int, after: int, accent: str, muted: str) -> None:
        self._before_label.setText(f"Before   {fmt_size(before)}")
        self._after_label.setText(f"After     {fmt_size(after)}")
        self._before.set_segments([("original size", float(before or 1), muted)])
        # The "after" bar is drawn to scale against "before" - a shrunken
        # archive should *look* shrunken, so the empty remainder is a real
        # transparent segment rather than a full-width bar.
        remainder = max(0, (before or 0) - (after or 0))
        self._after.set_segments([
            ("archive size", float(after), accent),
            ("space saved", float(remainder), "transparent"),
        ])
        self.setAccessibleName(
            f"{fmt_size(before)} before, {fmt_size(after)} after")

