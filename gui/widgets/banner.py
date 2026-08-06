"""The inline notice strip that replaces every modal dialog (W2-9, I9).

A modal over a running job hides the queue that proves the job is still
alive, which is precisely the thing this app refuses to do (research/23 §2.2
lists Ark, File Roller and Xarchiver as the cautionary set). So the one
remaining ``QMessageBox`` — "a job is running, close anyway?" — becomes a
strip at the top of the window: the queue stays visible while the user
answers, and the answer is two ordinary buttons.

Modelled on WinUI's InfoBar: an icon, one sentence, verb-labelled actions,
and a dismiss ×. **Tone is always the second signal** — the sentence carries
the meaning on its own, so the strip works in greyscale and through a screen
reader. The same widget serves I4's first-run notice and the error surfaces
in wave 3; nothing here knows what a compression job is.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QWidget)

from ..theme import GAP_INTRA, GUTTER

# U+2139 / U+26A0 / U+2716 / U+2713 - all present in the Windows UI fonts.
# (dropzone.py's U+2B07 note is the standing reminder of what happens when a
# glyph is only in the emoji font.)
_GLYPHS = {"info": "ⓘ", "warn": "⚠", "danger": "✖", "ok": "✓"}
_SPOKEN = {"info": "Note", "warn": "Warning", "danger": "Error", "ok": "Done"}


class Banner(QFrame):
    """One-line notice with optional actions. Hidden costs zero height."""

    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("tone", "info")
        self._buttons: list[QPushButton] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(GUTTER, GAP_INTRA, GUTTER, GAP_INTRA)
        row.setSpacing(GAP_INTRA)

        self._glyph = QLabel(_GLYPHS["info"], self)
        self._glyph.setObjectName("BannerGlyph")
        # The glyph repeats what the sentence says; a screen reader that read
        # both would just stutter.
        self._glyph.setAccessibleName("")
        row.addWidget(self._glyph)

        self._text = QLabel("", self)
        self._text.setWordWrap(True)
        self._text.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Preferred)
        row.addWidget(self._text, 1)

        self._actions_at = row.count()
        row.addStretch(0)

        self._close = QPushButton("×", self)
        self._close.setObjectName("CancelJob")   # same 28px glyph geometry
        self._close.setFixedSize(28, 28)
        self._close.setAccessibleName(self.tr("Dismiss this message"))
        self._close.setToolTip(self._close.accessibleName())
        self._close.clicked.connect(self._on_dismiss)
        row.addWidget(self._close)

        self._row = row
        self.setVisible(False)

    # -- public ---------------------------------------------------------------
    def show_message(self, text: str, tone: str = "info",
                     actions: Sequence[tuple[str, Callable[[], None]]] = (),
                     closable: bool = True) -> None:
        """Replace whatever the strip was saying. ``actions`` are
        ``(verb label, callback)`` — "Close anyway", never "OK"."""
        from ..theme import repolish

        self._clear_actions()
        self._text.setText(text)
        self._glyph.setText(_GLYPHS.get(tone, _GLYPHS["info"]))
        self.setProperty("tone", tone)
        repolish(self)
        repolish(self._glyph)

        for label, callback in actions:
            button = QPushButton(label, self)
            if not self._buttons:
                button.setProperty("variant", "primary")
            button.clicked.connect(callback)
            self._row.insertWidget(self._actions_at + len(self._buttons), button)
            self._buttons.append(button)

        self._close.setVisible(closable)
        # One spoken sentence: severity, then the message. Read once, in order.
        self.setAccessibleName(f"{_SPOKEN.get(tone, 'Note')}. {text}")
        self.setVisible(True)
        if self._buttons:
            self._buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def hide_banner(self) -> None:
        self.setVisible(False)

    def text(self) -> str:
        return self._text.text()

    def action_labels(self) -> list[str]:
        return [b.text() for b in self._buttons]

    def trigger(self, label: str) -> bool:
        """Press an action by its label. The keyboard and mouse paths go
        through the same click, so tests exercise what users do."""
        for button in self._buttons:
            if button.text() == label:
                button.click()
                return True
        return False

    # -- internals ------------------------------------------------------------
    def _clear_actions(self) -> None:
        for button in self._buttons:
            self._row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._buttons.clear()

    def _on_dismiss(self) -> None:
        self.hide_banner()
        self.dismissed.emit()
