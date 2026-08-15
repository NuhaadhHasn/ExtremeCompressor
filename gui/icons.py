"""Theme-tinted SVG icons (W2-5).

Emoji were the single biggest "not a native app" tell in the whole window.
The preset glyphs (⚡⚖️🔥🌙) rendered as Windows 10's 2016 flat set next to
Windows 11's Fluent set, three saturated oranges beside one dim grey pair of
scales, and a screen reader announced "high voltage Fast". They were also
undefeatable by the theme: an emoji is a colour bitmap, so it stayed orange
in a blue-accented dark UI and orange again in light.

The replacements are vendored from **Fluent UI System Icons** (MIT,
github.com/microsoft/fluentui-system-icons) - Microsoft's own icon language,
so they match the platform rather than imitate it, and the licence keeps the
repo OSI-clean for SignPath. ``assets/icons/LICENSE`` is the upstream MIT
text and must stay next to the SVGs.

**Tinting.** Qt has no "recolour this QIcon" call, so the SVG source is
string-substituted before it is handed to the renderer: Fluent's icons ship
as ``fill="none"`` on the root with unfilled paths that inherit
``currentColor``-ish behaviour, so injecting an explicit ``fill`` on every
path is what makes them take the theme token. Results are cached per
(name, colour, size) because a QIcon is rebuilt on every theme toggle and on
every chooser rebuild.

Rejected: the Segoe Fluent Icons *font*. Its EULA permits use "solely to
design, develop and test... on a Microsoft Platform" with no redistribution
right, and it is not preinstalled on Windows 10 19045 - tofu on exactly the
target hardware.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

# Preset glyph -> vendored file stem. Kept here rather than in preset_cards so
# the catalogue stays Qt-free prose.
PRESET_ICONS: dict[str, str] = {
    "fast": "flash",
    "normal": "scales",
    "extreme": "fire",
    "insane": "moon",
}

_FILL_ATTR = re.compile(r'\sfill="(?!none)[^"]*"')
_cache: dict[tuple[str, str, int], QIcon] = {}


def _tinted_source(raw: str, color: str) -> str:
    """Force every painted path to ``color``.

    Existing fills are stripped first - some Fluent glyphs (fire) ship
    multi-tone paths, and leaving one behind means an icon that is half the
    theme colour and half whatever the designer chose.
    """
    body = _FILL_ATTR.sub("", raw)
    return body.replace("<path", f'<path fill="{color}"')


def icon(name: str, color: str, size: int = 16) -> QIcon:
    """A theme-coloured QIcon, or an empty one if the asset is missing.

    Never raises: a missing SVG must not stop the app from compressing, and
    every place an icon appears also carries its text.
    """
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    path = ICON_DIR / f"{name}.svg"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return QIcon()

    from PySide6.QtSvg import QSvgRenderer      # local: keeps import cost off startup

    renderer = QSvgRenderer(QByteArray(_tinted_source(raw, color).encode("utf-8")))
    if not renderer.isValid():
        return QIcon()

    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    built = QIcon(pixmap)
    _cache[key] = built
    return built


def preset_icon(profile_value: str, color: str, size: int = 16) -> QIcon:
    """The glyph for a profile, by its ``Profile`` value string."""
    name = PRESET_ICONS.get(profile_value)
    return icon(name, color, size) if name else QIcon()
