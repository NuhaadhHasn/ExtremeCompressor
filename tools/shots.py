"""Regenerate the README screenshots and demo GIF from the real app.

Usage:
    .venv\\Scripts\\python.exe tools\\shots.py [--corpus DIR] [--profile extreme]

Nothing here is mocked. The script builds a reproducible repack-style corpus,
drives the actual :class:`MainWindow` through drop -> analyse -> compress ->
results, and grabs the real widget tree at each beat. Every number in the
README is therefore something the app genuinely produced on the machine that
ran this script - re-run it each release and the shots stay true.

Runs on Qt's ``offscreen`` platform, so it never steals focus, and at 2x
scale so the PNGs stay crisp on high-DPI displays.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
import zlib
from pathlib import Path

# Must be set before PySide6 is imported anywhere.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")
# Qt's offscreen plugin ships no font database of its own; without this every
# glyph renders as a tofu box. Point it at the system fonts.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):     # the console is cp1252 by default
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from excmp.planner import Profile  # noqa: E402
from gui.app import build_app  # noqa: E402
from gui.mainwindow import MainWindow  # noqa: E402

IMAGES_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"
WINDOW_SIZE = (1000, 1010)     # logical pixels; doubled by QT_SCALE_FACTOR
# Tall enough that the "Before you start" estimates panel (Phase J) is fully in
# frame on the drop/analysis shot - it is the newest thing worth showing, and at
# 830 it was cut off mid-table.

GIF_WIDTH = 900
GIF_FRAME_MS = 100             # 10 fps playback
GIF_MAX_FRAMES = 90            # <= 9 s
GIF_SAMPLE_MS = 140


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
def _pak_payload(seed: int, records: int) -> bytes:
    """Structured binary that deflate handles badly and LZMA2 handles well.

    This is the shape that makes game repacks work: the pak is *already*
    zlib-wrapped, so a plain archiver sees high entropy and gives up, but the
    data underneath is extremely regular once Precomp unwraps it.
    """
    rng = _Lcg(seed)
    chunks: list[bytes] = []
    for i in range(records):
        chunks.append(struct.pack("<IIHH", i, i * 7919, i % 512, 0xBEEF))
        chunks.append(b"MESH_NODE/material_" + str(i % 32).encode() + b"/lod0" + b"\x00" * 12)
        chunks.append(bytes(rng.byte() for _ in range(24)))
    return b"".join(chunks)


class _Lcg:
    """Tiny deterministic PRNG so the corpus is identical on every machine
    and every Python version (``random`` makes no such promise)."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF

    def byte(self) -> int:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return (self.state >> 16) & 0xFF


def make_corpus(root: Path) -> Path:
    """A ~12 MB stand-in for a game folder. Deterministic and disposable."""
    if root.exists():
        shutil.rmtree(root)
    (root / "data").mkdir(parents=True)
    (root / "config").mkdir(parents=True)

    shared = _pak_payload(seed=1, records=60_000)      # reused across paks
    for i in range(6):
        unique = _pak_payload(seed=100 + i, records=12_000)
        # Level 1: weak deflate, exactly like a shipped asset bundle.
        (root / "data" / f"assets{i}.pak").write_bytes(
            zlib.compress(shared + unique, 1))

    (root / "config" / "settings.ini").write_text(
        "\n".join(f"[section_{i}]\nquality=high\nvsync=1\nshadow_cascades=4"
                  for i in range(4_000)), encoding="utf-8")
    (root / "config" / "strings.json").write_text(
        "[\n" + ",\n".join(f'  {{"id": {i}, "text": "Press any key to continue"}}'
                           for i in range(9_000)) + "\n]", encoding="utf-8")

    # Already-compressed files, so the "why didn't this shrink" panel has two
    # genuinely different reasons to explain.
    rng = _Lcg(777)
    (root / "intro.mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom" + bytes(rng.byte() for _ in range(1_400_000)))
    (root / "voice_pack.rar").write_bytes(bytes(rng.byte() for _ in range(500_000)))
    return root


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------
class Recorder:
    """Samples the window on a timer for the whole scripted run."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self.frames: list[QImage] = []
        self._timer = QTimer()
        self._timer.timeout.connect(self._grab)

    def start(self) -> None:
        self._timer.start(GIF_SAMPLE_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _grab(self) -> None:
        self.frames.append(self.window.grab().toImage())


def spin(app, predicate, timeout_ms: int = 900_000, label: str = "") -> bool:
    """Pump the event loop until ``predicate`` is true (or we give up)."""
    loop = QEventLoop()
    elapsed = {"ms": 0}

    def tick() -> None:
        elapsed["ms"] += 40
        if predicate() or elapsed["ms"] >= timeout_ms:
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(40)
    loop.exec()
    timer.stop()
    ok = bool(predicate())
    print(f"  · {label}: {'ok' if ok else 'TIMED OUT'} ({elapsed['ms'] / 1000:.1f}s)")
    return ok


def settle(app, ms: int = 400) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def save_png(window: MainWindow, name: str) -> Path:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGES_DIR / name
    window.grab().save(str(target), "PNG")
    print(f"  · wrote {target.relative_to(IMAGES_DIR.parent.parent)} "
          f"({target.stat().st_size / 1024:.0f} KB)")
    return target


def qimage_to_pil(image: QImage):
    from PIL import Image

    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    return Image.frombytes(
        "RGB", (converted.width(), converted.height()),
        bytes(converted.constBits()), "raw", "RGB", converted.bytesPerLine())


def write_gif(frames: list[QImage], target: Path) -> tuple[bool, int]:
    """Assemble the sampled frames. Returns (time_lapsed, frame_count)."""
    from PIL import Image  # noqa: F401 - imported for the side-effect check

    if not frames:
        return False, 0
    time_lapsed = len(frames) > GIF_MAX_FRAMES
    if time_lapsed:
        step = len(frames) / GIF_MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(GIF_MAX_FRAMES)]

    pil_frames = []
    for frame in frames:
        image = qimage_to_pil(frame)
        ratio = GIF_WIDTH / image.width
        image = image.resize((GIF_WIDTH, int(image.height * ratio)))
        pil_frames.append(image.quantize(colors=128, dither=0))

    target.parent.mkdir(parents=True, exist_ok=True)
    pil_frames[0].save(target, save_all=True, append_images=pil_frames[1:],
                       duration=GIF_FRAME_MS, loop=0, optimize=True, disposal=2)
    return time_lapsed, len(pil_frames)


def scroll_to(window: MainWindow, widget) -> None:
    """Bring a widget into view inside the Compress tab's scroll area."""
    area = window.tabs.widget(0)
    area.ensureWidgetVisible(widget, 0, 40)


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="", help="use this folder instead of "
                                                     "generating a demo corpus")
    parser.add_argument("--profile", default="extreme",
                        choices=[p.value for p in Profile])
    parser.add_argument("--keep", action="store_true",
                        help="keep the generated corpus and archive")
    args = parser.parse_args()

    work = Path(__file__).resolve().parent.parent / ".shots-work"
    corpus = Path(args.corpus) if args.corpus else make_corpus(work / "SampleGame")
    out_dir = work / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = sum(p.stat().st_size for p in corpus.rglob("*") if p.is_file())
    print(f"corpus: {corpus}  ({total / 1024 / 1024:.1f} MB)")

    app = build_app([])
    window = MainWindow(theme="dark")
    window.resize(*WINDOW_SIZE)
    window.show()
    window.advanced_panel.output_dir.setText(str(out_dir))
    window.advanced_panel.notify_toggle.setChecked(False)
    settle(app, 300)

    recorder = Recorder(window)
    recorder.start()

    print("1/4  empty state")
    save_png(window, "00-empty.png")

    print("2/4  drop + analysis")
    window.add_paths([corpus])
    spin(app, lambda: window._summary is not None, 600_000, "analysis")
    window.presets.select(Profile(args.profile), emit=True)
    settle(app, 500)
    scroll_to(window, window.analysis_card)
    settle(app, 200)
    save_png(window, "01-drop-analysis.png")

    print("3/4  compressing")
    window.start_compression()
    job = window.queue.jobs[-1]
    spin(app, lambda: job.percent > 25, 600_000, "past 25%")
    window.queue_table.expandAll()
    scroll_to(window, window.queue_table)
    settle(app, 300)
    save_png(window, "02-queue-running.png")

    spin(app, lambda: job.state.is_terminal, 900_000, "job finished")
    print(f"     {job.state.value}: {job.orig_bytes} -> {job.final_bytes} "
          f"({job.saved_fraction:.1%}) in {job.elapsed_s:.1f}s")

    print("4/4  results")
    window.queue_table.collapseAll()
    settle(app, 400)
    scroll_to(window, window.results)
    settle(app, 600)
    save_png(window, "03-results.png")

    recorder.stop()
    lapsed, count = write_gif(recorder.frames, IMAGES_DIR / "demo.gif")
    gif = IMAGES_DIR / "demo.gif"
    if gif.exists():
        print(f"  · wrote docs/images/demo.gif ({gif.stat().st_size / 1024 / 1024:.2f} MB, "
              f"{count} frames{', time-lapsed' if lapsed else ''})")

    if not args.keep and not args.corpus:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\nheadline: {window.results.hero.text()}")
    print(f"subline:  {window.results.subline.text()}")
    return 0 if job.state.value == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
