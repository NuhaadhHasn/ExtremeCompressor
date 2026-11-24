"""The application icon: one SVG source, an .ico built from it, and every place that must show it."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "assets" / "app.ico"
SVG = ROOT / "assets" / "app-icon.svg"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _entries():
    raw = ICO.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", raw, 0)
    assert (reserved, kind) == (0, 1), "not an ICO"
    out = []
    for i in range(count):
        w, h, _c, _r, _planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", raw, 6 + 16 * i)
        out.append((w or 256, h or 256, bpp, raw[offset:offset + size]))
    return raw, out


def test_the_ico_holds_every_size_windows_asks_for_as_png():
    _raw, entries = _entries()
    assert sorted(w for w, *_ in entries) == [16, 24, 32, 48, 64, 128, 256]
    for w, h, bpp, blob in entries:
        assert w == h and bpp == 32 and blob.startswith(PNG_MAGIC), (w, h)


def test_each_png_is_really_that_size():
    _raw, entries = _entries()
    for w, h, _bpp, blob in entries:
        pw, ph = struct.unpack(">II", blob[16:24])
        assert (pw, ph) == (w, h)


def test_the_svg_source_parses_and_is_not_blank():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["t"])      # a QApplication: other tests need the widgets one
    r = QSvgRenderer(str(SVG))
    assert r.isValid()
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    r.render(p)
    p.end()
    assert img.pixelColor(32, 32).alpha() == 255      # the white block in the middle
    assert img.pixelColor(0, 0).alpha() == 0          # a rounded tile on a transparent ground


def test_the_window_has_an_icon():
    from gui.app import build_app
    app = build_app(["t"])
    assert not app.windowIcon().isNull()
    assert not app.windowIcon().pixmap(32, 32).isNull()


def test_both_programs_carry_the_icon_in_the_spec():
    text = (ROOT / "packaging" / "ExtremeCompressor.spec").read_text(encoding="utf-8")
    assert text.count("icon=") >= 2 and "app.ico" in text


def test_the_installer_and_uninstaller_use_the_icon():
    text = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "SetupIconFile=" in text and "app.ico" in text


def test_the_icon_is_bundled_into_the_frozen_app():
    """The spec ships the whole assets folder, so the window's SVG travels with it."""
    text = (ROOT / "packaging" / "ExtremeCompressor.spec").read_text(encoding="utf-8")
    assert '(str(ROOT / "assets"), "assets")' in text
