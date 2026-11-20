"""Application bootstrap: QApplication, theme, translations, main window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from excmp.intake import parse_intake

from .mainwindow import MainWindow
from .singleinstance import IntakeBatcher, IntakeServer, acquire, mark_running
from .theme import qss
from .winintegration import set_app_id

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"


def _install_translator(app: QApplication) -> QTranslator | None:
    """Load ``gui/translations/excmp_<locale>.qm`` if one exists.

    Nothing ships translated yet, but every string went through ``tr()`` from
    the first commit, so adding a ``.qm`` here is the only remaining step.
    """
    translator = QTranslator(app)
    locale = QLocale.system().name()
    if TRANSLATIONS_DIR.is_dir() and translator.load(f"excmp_{locale}", str(TRANSLATIONS_DIR)):
        app.installTranslator(translator)
        return translator
    return None


def build_app(argv: list[str] | None = None) -> QApplication:
    """Create (or reuse) the QApplication with our theme applied."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ExtremeCompressor")
    app.setOrganizationName("NuhaadhHasn")
    app.setApplicationDisplayName("ExtremeCompressor")
    app.setStyleSheet(qss("dark"))
    _install_translator(app)
    return app


def main(argv: list[str] | None = None) -> int:
    """Start the window - or, when Explorer started this process to hand files over (I5) and a
    window is already running, give it the files and exit."""
    set_app_id()
    argv = list(sys.argv if argv is None else argv)
    intake = parse_intake(argv[1:])
    app = build_app(argv)
    server = IntakeServer(parent=app)
    if not acquire(server, intake):
        return 0                                    # the running window has the files
    mark_running()                                  # the installer will not touch a running program
    window = MainWindow(theme="dark")
    batcher = IntakeBatcher(window.handle_intake, parent=window)
    server.received.connect(batcher.push)
    window.show()
    if intake is not None:
        batcher.push(intake)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
