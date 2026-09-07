"""I8 — "what's inside?", as a picture.

A folder that is 4 GB of video and 40 MB of source code is not the same job as
one that is the other way round, and the numbers alone do not land the way an
area does. The treemap answers the question people actually ask when a
compressor tells them it saved 3% — *what is all this?*

Two rules it does not break:

**Never colour alone.** Every block is labelled where it fits, and the legend
below repeats the category, its share and its size in words. Somebody who
cannot distinguish two of the colours still gets the whole answer. The same
reason the results bars carry text.

**It is a picture of the input, not a claim about the output.** The store/pipe
split already has its own honest bar; this one is only ever "here is what you
gave me", which is why it needs no engine change at all.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..format import fmt_size
from ..theme import tokens

#: Below this share a block is too small to label, and a treemap of forty
#: slivers is a texture rather than an answer. The rest is collapsed into one
#: honest "other" block.
MIN_SHARE = 0.02

#: Deliberately not a rainbow. These are picked to stay distinguishable in both
#: themes and under the commonest colour-vision deficiencies - and every one is
#: paired with a label anyway.
_PALETTE = ("#4C8DFF", "#2FB8A0", "#E0A93B", "#B07CE8", "#E4735E",
            "#6FA8DC", "#8FCF7A", "#C98BB9")


class Treemap(QWidget):
    """Area-proportional breakdown of the input, by category."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, int, str]] = []   # (label, bytes, colour)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setAccessibleName(self.tr("What is inside"))
        self.setVisible(False)

    # -- data ---------------------------------------------------------------
    def set_breakdown(self, by_category: dict) -> None:
        """``{category: bytes}``. Anything falsy hides the widget entirely -
        an empty treemap is a box of nothing, which helps nobody."""
        rows = [(str(getattr(k, "value", k)), int(v))
                for k, v in (by_category or {}).items() if v > 0]
        total = sum(v for _n, v in rows)
        if not rows or total <= 0:
            self._rows = []
            self.setVisible(False)
            self.updateGeometry()
            return

        rows.sort(key=lambda kv: -kv[1])
        # Collapse the slivers rather than drawing forty unlabellable ones.
        big = [(n, v) for n, v in rows if v / total >= MIN_SHARE]
        rest = total - sum(v for _n, v in big)
        if rest > 0:
            big.append((self.tr("other"), rest))

        self._rows = [(name, value, _PALETTE[i % len(_PALETTE)])
                      for i, (name, value) in enumerate(big)]
        self.setMinimumHeight(120)
        self.setVisible(True)
        self.updateGeometry()
        self.update()
        self.setAccessibleDescription(self.summary())

    def summary(self) -> str:
        """The same information as words. This is what a screen reader gets,
        and what the legend prints - the picture is never the only copy."""
        total = sum(v for _n, v, _c in self._rows)
        if not total:
            return ""
        parts = [f"{name} {100 * value / total:.0f}% ({fmt_size(value)})"
                 for name, value, _c in self._rows]
        return self.tr("Inside: ") + ", ".join(parts)

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._rows:
            return
        import squarify

        palette = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        area = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        total = sum(v for _n, v, _c in self._rows)
        sizes = squarify.normalize_sizes(
            [v for _n, v, _c in self._rows], area.width(), area.height())
        blocks = squarify.squarify(sizes, area.x(), area.y(),
                                   area.width(), area.height())

        label_font = QFont(self.font())
        label_font.setPointSizeF(max(7.5, label_font.pointSizeF() - 0.5))
        painter.setFont(label_font)

        for (name, value, colour), box in zip(self._rows, blocks):
            rect = QRectF(box["x"], box["y"], max(0.0, box["dx"] - 2),
                          max(0.0, box["dy"] - 2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(colour)))
            painter.drawRoundedRect(rect, 3, 3)

            # Label inside the block only where it genuinely fits; the legend
            # carries the rest, so nothing depends on a label that is not
            # there.
            text = f"{name}  {100 * value / total:.0f}%"
            metrics = painter.fontMetrics()
            if (rect.width() > metrics.horizontalAdvance(text) + 12
                    and rect.height() > metrics.height() + 8):
                painter.setPen(QPen(QColor(palette.get("on_accent", "#0B1220"))))
                painter.drawText(rect.adjusted(6, 4, -6, -4),
                                 int(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignTop), text)
        painter.end()

    def legend_rows(self) -> list[tuple[str, str, str]]:
        """``(label, share, size)`` for the caller to render as text.

        Returned rather than drawn so the legend is real selectable text in the
        layout - a picture of a legend is not something you can copy, and not
        something a screen reader can read.
        """
        total = sum(v for _n, v, _c in self._rows)
        if not total:
            return []
        return [(name, f"{100 * value / total:.0f}%", fmt_size(value))
                for name, value, _c in self._rows]
