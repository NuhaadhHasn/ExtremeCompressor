"""The application icon: one 512 px master PNG, an .ico built from it, and every place that must show it."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "assets" / "app.ico"
MASTER = ROOT / "assets" / "app-icon-512.png"
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


def test_the_master_is_a_square_transparent_png_with_a_solid_tile():
    from PySide6.QtGui import QImage
    img = QImage(str(MASTER))
    assert not img.isNull() and img.width() == img.height() == 512
    assert img.hasAlphaChannel()
    assert img.pixelColor(0, 0).alpha() == 0 and img.pixelColor(511, 511).alpha() == 0     # rounded corners are clear
    assert img.pixelColor(256, 256).alpha() == 255                                         # the tile is solid
    assert img.pixelColor(256, 40).alpha() == 255


def test_the_small_sizes_are_not_blank_or_flat():
    """Every size must carry the tile and some contrast (a flat square would mean the downscale lost the design)."""
    _raw, entries = _entries()
    from PySide6.QtGui import QImage
    for w, _h, _bpp, blob in entries:
        img = QImage.fromData(blob, "PNG")
        assert img.width() == w
        centre = img.pixelColor(w // 2, w // 2)
        assert centre.alpha() == 255
        lums = {img.pixelColor(x, y).lightness() // 24 for x in range(w // 4, w - w // 4) for y in range(w // 4, w - w // 4)}
        assert len(lums) >= 3, w


def test_the_old_vector_placeholder_is_gone():
    assert not (ROOT / "assets" / "app-icon.svg").exists()


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
