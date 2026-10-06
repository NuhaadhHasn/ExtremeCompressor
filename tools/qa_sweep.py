"""Render every surface in both themes, so appearance gets reviewed too.

    .venv\\Scripts\\python.exe tools\\qa_sweep.py [--out DIR]

The test suite pins *behaviour*. It cannot see that a progress bar rendered as
a 55px slab, that a muted glyph is invisible on a dark surface, that a caveat
was sliced mid-word, or that the chooser was advertising "100% or better" - an
archive of zero bytes or smaller. Every one of those shipped past a green
suite during UI wave 2 and was caught by looking at a PNG.

So: 18 surfaces x 2 themes, including the ones no test and no README
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
    with zipfile.ZipFile(theirs, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 400)
        zf.writestr("docs/data.csv", "a,b,c\n" * 300)
        zf.writestr("bin/tool.exe", b"MZ" + bytes(2000))
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

    # I6: the same page after a comparison run. Two profiles measured and two
    # not, because that half-and-half state is the one a cancelled run leaves
    # behind and the one where "which of these numbers is which" has to be
    # legible without reading the caption.
    from excmp.sample import MeasuredRun, pick_sample
    from gui.suggest import measurement_caption

    sample = pick_sample(win._infos, cap_bytes=2_000_000)
    win._measured = {
        Profile.FAST: MeasuredRun(Profile.FAST, sample.total_bytes,
                                  int(sample.total_bytes * 0.71), 41.0),
        Profile.NORMAL: MeasuredRun(Profile.NORMAL, sample.total_bytes,
                                    int(sample.total_bytes * 0.39), 194.0),
    }
    win._measured_caption = measurement_caption(sample, 2)
    win._refresh_estimates()
    # `_refresh_estimates` reads `_comparison` to decide whether the measured
    # archive size may take the size column, and there is no run object here.
    # Re-render through profile_comparison directly for the whole-input case.
    from excmp.calibrate import blended_rates
    from gui.suggest import profile_comparison
    win.compare_table.set_rows(
        profile_comparison(win._infos, win.tools, win._summary,
                           rates=blended_rates(), measured=win._measured,
                           measured_whole_input=sample.is_whole_input),
        win._measured_caption)
    settle(150)
    shot(win, out, f"{theme}-05b-presets-measured")
    win._measured = {}
    win._measured_caption = ""
    win._refresh_estimates()

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

    # G2: the foreign listing itself. This is the surface where our four
    # columns would silently be pointed at an archive that cannot fill three
    # of them, and where the CRC-32/SHA-256 substitution would show up.
    win.extract_tab.contents_toggle.setChecked(True)
    for _ in range(200):
        settle(40)
        if win.extract_tab.contents.topLevelItemCount():
            break
    settle(150)
    shot(win, out, f"{theme}-07d-extract-foreign-listing")

    # ...and with rows ticked, so the selection affordance is reviewed too.
    win.extract_tab.check_row(0)
    settle(80)
    shot(win, out, f"{theme}-07e-extract-selection")
    win.extract_tab.contents_toggle.setChecked(False)

    # G2: the password prompt, which is a Banner state nothing else renders.
    win.banner.ask_secret(
        "locked.7z keeps its file names encrypted. Enter its password to "
        "see what is inside.", "Unlock", lambda _pw: None)
    settle(120)
    shot(win, out, f"{theme}-07f-password-prompt")
    win.banner.hide_banner()

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

    # I11: the D9 self-test, on its estimate and then past it.
    from gui.progress import VERIFYING, VERIFYING_LATE
    job.percent, job.eta_s, job.stage = 71.0, 1260.0, VERIFYING
    win._on_job_progress(job.id, VERIFYING, 71.0, 1260.0)
    shot(win, out, f"{theme}-09b-activity-verifying")
    job.percent, job.eta_s, job.stage = 92.0, None, VERIFYING_LATE
    win._on_job_progress(job.id, VERIFYING_LATE, 92.0, None)
    shot(win, out, f"{theme}-09c-activity-verifying-late")

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
    print(f"  {theme}: 18 surfaces")


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
