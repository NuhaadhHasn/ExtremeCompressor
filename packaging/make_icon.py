r"""Render assets/app-icon.svg to assets/app.ico (16-256 px, PNG-compressed entries).

    .venv\Scripts\python.exe packaging\make_icon.py

Needs only PySide6 (QtSvg), so there is nothing new to install. The .ico is committed; rerun this
after editing icon.svg. ``--preview`` also writes packaging\icon-preview.png (a 512 px render).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, px: int) -> QImage:
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for px, blob in pngs:
        dim = 0 if px >= 256 else px               # 0 means 256 in an ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return head + entries + blobs


def main() -> None:
    _app = QGuiApplication.instance() or QGuiApplication(["make_icon", "-platform", "offscreen"])
    renderer = QSvgRenderer(str(ASSETS / "app-icon.svg"))
    if not renderer.isValid():
        sys.exit("icon.svg did not parse")
    pngs = [(px, png_bytes(render(renderer, px))) for px in SIZES]
    out = ASSETS / "app.ico"
    out.write_bytes(build_ico(pngs))
    print(f"wrote {out} ({out.stat().st_size:,} B, sizes {SIZES})")
    if "--preview" in sys.argv:
        render(renderer, 512).save(str(HERE / "icon-preview.png"))
        sheet = QImage(16 + 24 + 32 + 48 + 64 + 6 * 12 + 12, 80, QImage.Format.Format_ARGB32)
        sheet.fill(Qt.GlobalColor.white)
        p = QPainter(sheet)
        x = 12
        for px in (16, 24, 32, 48, 64):
            p.drawImage(x, 8, render(renderer, px))
            x += px + 12
        p.end()
        sheet.scaled(sheet.width() * 4, sheet.height() * 4, Qt.AspectRatioMode.KeepAspectRatio).save(
            str(HERE / "icon-sizes.png"))


if __name__ == "__main__":
    main()
