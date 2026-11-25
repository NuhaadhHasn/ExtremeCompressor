r"""Build assets/app.ico (16-256 px, PNG-compressed entries) from the 512 px master assets/app-icon-512.png.

    .venv\Scripts\python.exe packaging\make_icon.py

Needs only PySide6, so there is nothing new to install. The .ico is committed; rerun this after replacing the
master. ``--preview`` also writes packaging\icon-sizes.png (the small sizes enlarged, to look at).

The master is a design made with Gemini on 2026-11-25 (a document squeezed from both sides, with a lightning bolt
for "extreme"), cut out of its white background and saved as a transparent 512 px PNG. Windows only ever scales an
icon down from the 256 px entry, which is why the master is bigger than anything shipped.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
MASTER = ASSETS / "app-icon-512.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def scaled(master: QImage, px: int) -> QImage:
    """Smooth downscale in halving steps (one big jump from 512 to 16 loses the edges)."""
    img = master
    while img.width() > px * 2:
        img = img.scaled(img.width() // 2, img.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img.scaled(px, px, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


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
    master = QImage(str(MASTER))
    if master.isNull() or master.width() != master.height():
        sys.exit(f"{MASTER} is missing or not square")
    master = master.convertToFormat(QImage.Format.Format_ARGB32)
    pngs = [(px, png_bytes(scaled(master, px))) for px in SIZES]
    out = ASSETS / "app.ico"
    out.write_bytes(build_ico(pngs))
    print(f"wrote {out} ({out.stat().st_size:,} B, sizes {SIZES})")
    if "--preview" in sys.argv:
        sheet = QImage(900, 260, QImage.Format.Format_ARGB32)
        sheet.fill(Qt.GlobalColor.white)
        p = QPainter(sheet)
        x = 10
        for px in (16, 24, 32, 48, 64, 128):
            small = scaled(master, px)
            p.drawImage(x, 10, small.scaled(px * 3, px * 3, Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.FastTransformation))
            x += px * 3 + 14
        p.end()
        sheet.save(str(HERE / "icon-sizes.png"))


if __name__ == "__main__":
    main()
