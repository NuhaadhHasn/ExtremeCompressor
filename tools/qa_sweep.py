"""Render every surface in both themes, so appearance gets reviewed too.

    .venv\\Scripts\\python.exe tools\\qa_sweep.py [--out DIR]

The test suite pins *behaviour*. It cannot see that a progress bar rendered as
a 55px slab, that a muted glyph is invisible on a dark surface, that a caveat
was sliced mid-word, or that the chooser was advertising "100% or better" - an
archive of zero bytes or smaller. Every one of those shipped past a green
suite during UI wave 2 and was caught by looking at a PNG.

So: 16 surfaces x 2 themes, including the ones no test and no README
screenshot ever renders - the banner, the Extract tab, the expanded pending
list, a failed-job results panel, everything-disclosed-at-once. Cheap to run,
and the only thing that has ever caught this class of defect here.

Offscreen, with the real Windows fonts. The offscreen plugin ships no font
database; without QT_QPA_FONTDIR every glyph is a tofu box of the wrong width
and the images are worthless (the same trap that made wave 1's height gates
measure fiction).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from excmp.planner import Profile  # noqa: E402
from gui.mainwindow import MainWindow  # noqa: E402
from gui.models import Job, JobKind, JobState  # noqa: E402


def settle(ms: int = 180) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(win: MainWindow, out: Path, name: str) -> None:
    settle(120)
    win.grab().save(str(out / f"{name}.png"), "PNG")


def build_corpus() -> list[Path]:
    root = Path(tempfile.mkdtemp()) / "data"
    root.mkdir()
    files = [root / "manual.txt", root / "assets.bin", root / "server.log"]
    files[0].write_text("compress me. " * 6000, encoding="utf-8")
    files[1].write_bytes(bytes(range(256)) * 900)
    files[2].write_text("line\n" * 12000, encoding="utf-8")
    return files


_ARCHIVES: dict[str, Path] = {}


def build_archives(files: list[Path]) -> None:
    """One of ours and one of theirs, so both labellings get reviewed."""
    import zipfile

    from excmp import engine
    from excmp.stages.base import StageContext

    work = Path(tempfile.mkdtemp(prefix="excmp-qa-arch-"))
    ours = work / "ours.excmp"
    engine.compress([files[0].parent], ours, Profile.FAST,
                    StageContext(temp_dir=work / "t"))
    theirs = work / "somebody-elses.zip"
    with zipfile.ZipFile(theirs, "w") as zf:
        zf.writestr("docs/guide.txt", "hello " * 400)
    _ARCHIVES.update(ours=ours, theirs=theirs)


def sweep(theme: str, files: list[Path], out: Path) -> None:
    win = MainWindow(theme=theme)
    win.resize(1180, 700)
    win.show()
    settle(250)

    # I4's first-run notice is showing on a fresh profile.
    shot(win, out, f"{theme}-00-first-run")
    win.banner.hide_banner()

    shot(win, out, f"{theme}-01-compress-empty")

    win.drop_zone._set_active(True)
    shot(win, out, f"{theme}-02-compress-drag")
    win.drop_zone._set_active(False)

    win.advanced_panel.setVisible(True)
    shot(win, out, f"{theme}-03-advanced-open")
    win.advanced_panel.setVisible(False)
    win.actions["about"].trigger()
    shot(win, out, f"{theme}-04-about")
    if win._about_card is not None:
        win._about_card.setVisible(False)

    done = {"v": False}
    win.analysisFinished.connect(lambda: done.__setitem__("v", True))
    win.add_paths(files)
    for _ in range(400):
        settle(40)
        if done["v"]:
            break
    settle(250)
    shot(win, out, f"{theme}-05-compress-populated")

    # Everything disclosed at once - the worst case for the height budget.
    win.drop_zone.toggle_pending()
    win.analysis_card.details_toggle.setChecked(True)
    win.compare_table.info_toggle.setChecked(True)
    shot(win, out, f"{theme}-06-compress-all-open")
    win.drop_zone.toggle_pending()
    win.analysis_card.details_toggle.setChecked(False)
    win.compare_table.info_toggle.setChecked(False)

    # G1/I2-lite: a real .excmp with the contents listing open, then a
    # foreign archive so the honesty labelling gets looked at too.
    win.tabs.setCurrentWidget(win.extract_tab)
    win.extract_tab.set_archive(_ARCHIVES["ours"])
    win.extract_tab.contents_toggle.setChecked(True)
    shot(win, out, f"{theme}-07-extract")
    win.extract_tab.contents_toggle.setChecked(False)
    win.extract_tab.set_archive(_ARCHIVES["theirs"])
    shot(win, out, f"{theme}-07b-extract-foreign")

    win.tabs.setCurrentWidget(win.settings_tab)
    shot(win, out, f"{theme}-07c-settings")

    win.tabs.setCurrentWidget(win.activity_page)
    shot(win, out, f"{theme}-08-activity-empty")

    win.queue.pause()
    job = Job(kind=JobKind.COMPRESS, inputs=[Path("C:/in/MyGame")],
              out_path=Path("C:/out/MyGame.excmp"), profile=Profile.EXTREME)
    win.queue.add_job(job)
    job.state = JobState.RUNNING
    job.percent, job.eta_s, job.stage = 42.0, 195.0, "precomp"
    job.orig_bytes = 1_900_000_000
    win._on_job_progress(job.id, "precomp", 42.0, 195.0)
    win.queue_table.update_state(job)
    shot(win, out, f"{theme}-09-activity-running")

    job.state = JobState.DONE
    job.final_bytes, job.elapsed_s = 700_000_000, 166.0
    job.summary = win._summary
    win._on_job_state(job.id, JobState.DONE)
    win.results.show_job(job)
    settle(150)
    shot(win, out, f"{theme}-10-activity-results")

    # The banner (W2-9): the only surface the app asks a question on.
    win.tabs.setCurrentWidget(win._scroll)
    win.queue._active_id = "pretend-this-is-running"
    win.close()
    shot(win, out, f"{theme}-11-banner")
    win.banner.trigger("Keep it running")
    win.queue._active_id = None

    # A passing verification - a results variant with no output folder.
    from excmp.engine import VerifyResult
    vjob = Job(kind=JobKind.VERIFY, inputs=[Path("C:/out/MyGame.excmp")],
               out_path=Path("C:/out/MyGame.excmp"), state=JobState.DONE,
               elapsed_s=34.0)
    vjob.result = VerifyResult(archive=Path("C:/out/MyGame.excmp"), ok=True,
                               files_restored=6, verified=6, elapsed_s=34.0)
    win.results.show_job(vjob)
    win.tabs.setCurrentWidget(win.activity_page)
    shot(win, out, f"{theme}-13-activity-verified")

    fail = Job(kind=JobKind.COMPRESS, inputs=[Path("C:/in/Bad")],
               out_path=Path("C:/out/Bad.excmp"), state=JobState.FAILED,
               error="precomp exited with code 1 while recompressing assets0.pak")
    win.results.show_job(fail)
    win.tabs.setCurrentWidget(win.activity_page)  # noqa: E501 - already there, kept explicit
    shot(win, out, f"{theme}-12-activity-failed")

    win.queue.shutdown()
    print(f"  {theme}: 16 surfaces")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="",
                        help="where to write the PNGs (default: a temp dir)")
    args = parser.parse_args()

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="excmp-qa-"))
    out.mkdir(parents=True, exist_ok=True)

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      tempfile.mkdtemp())

    QApplication([])
    corpus = build_corpus()
    build_archives(corpus)
    for theme in ("dark", "light"):
        sweep(theme, corpus, out)
    print(f"\nwrote {len(list(out.glob('*.png')))} images to {out}")
    # Qt's offscreen platform segfaults on interpreter teardown after the
    # queue's thread pool has been shut down; the images are already on disk.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
