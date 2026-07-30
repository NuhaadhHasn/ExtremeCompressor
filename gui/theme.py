"""Design tokens and the QSS built from them.

Hand-rolled on purpose: the obvious Qt "Fluent" widget packs are GPLv3 and
this repo is MIT. Two palettes are defined from day one so a light-mode
toggle never means rewriting the stylesheet - only the token table changes.

Widgets opt into styling through ``objectName`` (``Card``, ``Hero``, ...) and
dynamic properties (``variant``, ``tone``, ``dragActive``). After changing a
dynamic property call :func:`repolish` or Qt will not restyle the widget.
"""

from __future__ import annotations

from string import Template

from PySide6.QtWidgets import QWidget

DARK: dict[str, str] = {
    "bg": "#12141a",
    "surface": "#1a1d26",
    "surface2": "#232733",
    "surface3": "#2b3040",
    "border": "#2e3342",
    "border_hi": "#3d445a",
    "text": "#e6e9f0",
    "muted": "#98a1b6",
    "accent": "#4c8dff",
    "accent_hi": "#6ba0ff",
    "accent_dim": "#1e3a6b",
    "ok": "#3ecf8e",
    "warn": "#f5a524",
    "danger": "#f04f5b",
    "shadow": "#0b0d12",
}

LIGHT: dict[str, str] = {
    "bg": "#f3f5f9",
    "surface": "#ffffff",
    "surface2": "#eceff5",
    "surface3": "#e0e5ee",
    "border": "#d5dae4",
    "border_hi": "#b9c1d0",
    "text": "#141821",
    "muted": "#5b6478",
    "accent": "#2f6fe0",
    "accent_hi": "#1f5bc4",
    "accent_dim": "#d6e3fb",
    "ok": "#15a06a",
    "warn": "#a86a00",
    "danger": "#cf2f3b",
    "shadow": "#c3c9d4",
}

# Non-colour tokens are shared by both palettes.
METRICS: dict[str, str] = {
    "radius": "10px",
    "radius_sm": "6px",
    "pad": "12px",
    "font": '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
}

_QSS = Template("""
QWidget {
    background: $bg;
    color: $text;
    font-family: $font;
    font-size: 10pt;
}
QToolTip {
    background: $surface3;
    color: $text;
    border: 1px solid $border_hi;
    padding: 6px 8px;
    border-radius: $radius_sm;
}

/* ---- surfaces -------------------------------------------------------- */
QFrame#Card {
    background: $surface;
    border: 1px solid $border;
    border-radius: $radius;
}
QFrame#Card[tone="accent"] { border-color: $accent; background: $surface2; }
QFrame#Divider { background: $border; max-height: 1px; border: none; }

/* Layout-only containers. The base QWidget rule paints $bg, which shows up
   as a dark band when such a container sits inside a lighter card - these
   opt out. Named rather than matched by descendant selector so it cannot
   accidentally out-specify the button and input rules below. */
QWidget#Plain { background: transparent; }

/* ---- typography ------------------------------------------------------ */
QLabel { background: transparent; }
QLabel#Hero {
    font-size: 30pt;
    font-weight: 700;
    color: $ok;
    padding: 2px 0;
}
QLabel#HeroSub  { font-size: 12pt; color: $muted; }
QLabel#Title    { font-size: 13pt; font-weight: 600; }
QLabel#Subtitle { font-size: 10pt; color: $muted; }
QLabel#Muted    { color: $muted; }
QLabel#Mono {
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 9pt;
    color: $muted;
}
QLabel[tone="ok"]     { color: $ok; }
QLabel[tone="warn"]   { color: $warn; }
QLabel[tone="danger"] { color: $danger; }

/* ---- drop zone ------------------------------------------------------- */
QFrame#DropZone {
    background: $surface;
    border: 2px dashed $border_hi;
    border-radius: $radius;
}
QFrame#DropZone[dragActive="true"] {
    border-color: $accent;
    background: $accent_dim;
}

/* ---- buttons --------------------------------------------------------- */
QPushButton {
    background: $surface2;
    border: 1px solid $border;
    border-radius: $radius_sm;
    padding: 7px 14px;
    color: $text;
}
QPushButton:hover:enabled  { background: $surface3; border-color: $border_hi; }
QPushButton:pressed        { background: $surface; }
QPushButton:disabled       { color: $muted; background: $surface; }
QPushButton[variant="primary"] {
    background: $accent;
    border-color: $accent;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover:enabled { background: $accent_hi; }
QPushButton[variant="primary"]:disabled {
    background: $surface2; border-color: $border; color: $muted;
}
QPushButton[variant="danger"]:hover:enabled { border-color: $danger; color: $danger; }

QToolButton {
    background: transparent;
    border: none;
    border-radius: $radius_sm;
    padding: 4px 6px;
    color: $muted;
}
QToolButton:hover  { background: $surface2; color: $text; }
QToolButton:focus  { border: 1px solid $accent; }

/* ---- preset cards ---------------------------------------------------- */
QPushButton#PresetCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: $radius;
    padding: 0px;
    text-align: left;
}
QPushButton#PresetCard:hover:enabled { border-color: $border_hi; background: $surface2; }
QPushButton#PresetCard:checked {
    border: 2px solid $accent;
    background: $surface2;
}

/* ---- inputs ---------------------------------------------------------- */
QLineEdit, QSpinBox, QComboBox {
    background: $surface2;
    border: 1px solid $border;
    border-radius: $radius_sm;
    padding: 6px 8px;
    selection-background-color: $accent;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled { color: $muted; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: $surface2;
    border: 1px solid $border_hi;
    selection-background-color: $accent;
}

QCheckBox { spacing: 8px; background: transparent; }
QCheckBox:disabled { color: $muted; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid $border_hi;
    border-radius: 4px;
    background: $surface2;
}
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:disabled { background: $surface; border-color: $border; }

/* ---- progress -------------------------------------------------------- */
QProgressBar {
    background: $surface3;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: $text;
}
QProgressBar::chunk { background: $accent; border-radius: 5px; }
QProgressBar[tone="ok"]::chunk     { background: $ok; }
QProgressBar[tone="danger"]::chunk { background: $danger; }

/* ---- queue ----------------------------------------------------------- */
QTreeWidget {
    background: $surface;
    border: 1px solid $border;
    border-radius: $radius;
    outline: none;
    alternate-background-color: $surface2;
}
QTreeWidget::item { padding: 6px 4px; border: none; }
QTreeWidget::item:selected { background: $accent_dim; color: $text; }
QHeaderView::section {
    background: $surface2;
    color: $muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 7px 6px;
    font-weight: 600;
}

QPlainTextEdit {
    background: $bg;
    border: 1px solid $border;
    border-radius: $radius_sm;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 9pt;
    color: $muted;
}

/* ---- tabs ------------------------------------------------------------ */
QTabWidget::pane { border: none; top: -1px; }
QTabBar::tab {
    background: transparent;
    color: $muted;
    padding: 9px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover     { color: $text; }
QTabBar::tab:selected  { color: $text; border-bottom: 2px solid $accent; }

/* ---- scrollbars ------------------------------------------------------ */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical   { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $border_hi; border-radius: 5px; min-height: 28px; min-width: 28px;
}
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---- focus ring: keyboard users must always see where they are ------- */
QPushButton:focus, QCheckBox:focus, QTreeWidget:focus, QTabBar::tab:focus {
    border: 1px solid $accent;
}
""")


def qss(theme: str = "dark") -> str:
    """Full stylesheet for ``"dark"`` (default) or ``"light"``."""
    tokens = dict(DARK if theme == "dark" else LIGHT)
    tokens.update(METRICS)
    return _QSS.substitute(tokens)


def tokens(theme: str = "dark") -> dict[str, str]:
    """Raw token table - for widgets that paint themselves (the type bars)."""
    merged = dict(DARK if theme == "dark" else LIGHT)
    merged.update(METRICS)
    return merged


def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changed.

    Qt caches the resolved style per widget; setting ``dragActive`` or
    ``variant`` at runtime has no visible effect until the style is asked
    to unpolish/polish the widget again.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
