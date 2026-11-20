"""The single window.

No modal sub-windows, and one tab per *lifecycle stage* rather than one long
scrolling column (UI v3 wave 2). Compress is where you decide - drop →
analysis → profile; Activity is where work in flight lives - queue, logs,
results; Extract is its own thing. A one-line status strip at the bottom
carries the queue's state onto every tab, so promoting the queue out of the
Compress page never means hiding it: the strip says what is running, the tab
title counts what is waiting, and one click goes there.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import (QAction, QCloseEvent, QFontMetrics, QIcon,
                           QKeySequence, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidgetItem, QMainWindow, QMenu,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSystemTrayIcon, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from excmp import __version__
from excmp.analyzer import FileInfo
from excmp.intake import Intake
from excmp.planner import Profile, plan as make_plan
from excmp.safepath import UnsafePathError, safe_relpath
from excmp.sample import MeasuredRun
from excmp.tools import find_tools

from .compare_run import ComparisonRun
from .format import fmt_eta, fmt_size
from .progress import FINISHING, PACKING, VERIFYING, VERIFYING_LATE
from .models import Job, JobKind, JobState
from .queue_manager import AnalysisSignals, AnalysisWorker, QueueManager
from .suggest import (AnalysisSummary, profile_comparison, recommend_profile,
                      strongest_profile, summarize)
from .theme import (CARD_MARGINS, GAP_BLOCK, GAP_INTRA, GUTTER, VGAP, qss,
                    repolish)
from .widgets.analysis_card import AnalysisCard
from .widgets.banner import Banner
from .widgets.compare_table import CompareTable
from .widgets.dropzone import DropZone
from .widgets.extract_tab import ExtractTab
from .widgets.history_tab import HistoryTab
from .widgets.preset_cards import AdvancedPanel, AdvancedToggle
from .widgets.queue_table import QueueTable
from .widgets.results import ResultsPanel
from .widgets.settings_tab import SettingsTab
from .winintegration import (TBPF_ERROR, TBPF_PAUSED, Notifier, TaskbarProgress,
                             open_in_explorer, set_dark_titlebar)

DEFAULT_TEMP = Path.home() / ".excmp" / "tmp"


def initial_size(avail_w: int, avail_h: int) -> tuple[int, int]:
    """The window size for a given available screen area.

    The target machine is a 1366x768 laptop, and the old hard-coded 1080x900
    opened 132px taller than that entire display. Rule: take most of a small
    screen (leaving breathing room and the taskbar's cut, which is already out
    of ``availableGeometry``), and stop growing at a comfortable reading width
    on big monitors. Pure function so the arithmetic is testable without a
    screen.
    """
    width = min(1180, int(avail_w * 0.92))
    height = min(940, int(avail_h * 0.94))
    return max(width, 640), max(height, 480)


def _is_under(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or lives inside it. Used to drop a
    removed item's cached FileInfos without touching the disk."""
    if path == root:
        return True
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def unique_path(path: Path) -> Path:
    """``out.excmp`` → ``out (2).excmp`` if needed.

    The engine deliberately replaces its output path atomically, so the
    guard against clobbering last week's archive has to live up here.
    """
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for n in range(2, 1000):
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    return path


class MainWindow(QMainWindow):
    """Owns the flow state: what was dropped, what it is, what to do with it."""

    analysisFinished = Signal()   # for tests and the screenshot script

    def __init__(self, theme: str | None = None) -> None:
        super().__init__()
        # Remembered across launches (I1). An explicit argument still wins, so
        # tools/shots.py and the tests can pin a theme.
        stored = QSettings().value("settings/theme")
        self.theme_name = theme or (str(stored) if stored in ("dark", "light")
                                    else "dark")
        self.setWindowTitle(self.tr("ExtremeCompressor"))
        self._restore_geometry()

        self.tools = find_tools(with_versions=True)
        self.queue = QueueManager(DEFAULT_TEMP, self.tools, self)

        self._pending: list[Path] = []
        self._infos: list[FileInfo] = []
        self._summary: AnalysisSummary | None = None
        # I6. Held on the window rather than on the rows, because every
        # profile click rebuilds and deletes every ProfileRow widget - a
        # measured number parked on one would survive exactly until the next
        # click. Cleared whenever the input changes, for the obvious reason.
        self._measured: dict[Profile, MeasuredRun] = {}
        self._measured_caption = ""
        self._comparison: ComparisonRun | None = None
        self._analysis_pool = QThreadPool(self)
        self._analysis_notes: list[str] = []
        self._analysis_signals = AnalysisSignals(self)
        self._analysis_signals.ready.connect(self._on_analysis_ready)
        self._analysis_signals.failed.connect(self._on_analysis_failed)
        self._analysis_signals.progress.connect(self._on_analysis_progress)
        self._analysis_signals.note.connect(self._on_analysis_note)
        # Set by the banner's "Close anyway": the second closeEvent must not
        # ask the same question again.
        self._force_close = False

        self._taskbar: TaskbarProgress | None = None
        self._notifier = Notifier()
        self._tray: QSystemTrayIcon | None = None

        self._build_ui()
        self._wire()
        self._apply_theme()
        self._refresh_actions()
        self._maybe_first_run()

    def _maybe_first_run(self) -> None:
        """I4, on W2-9's Banner: say what this app will and will not do to
        your files, once. A notice repeated every launch is a notice nobody
        reads, and this one is a promise rather than a tip."""
        settings = QSettings()
        if settings.value("settings/seen_first_run"):
            return
        settings.setValue("settings/seen_first_run", True)
        self.banner.show_message(
            self.tr("Your originals are never modified — archives are written "
                    "to a temporary file and only renamed into place once a "
                    "full restore has verified every SHA-256. Anything that "
                    "cannot shrink is stored byte-for-byte, and the app tells "
                    "you why."),
            tone="info",
            actions=[(self.tr("Got it"), self.banner.hide_banner)])

    # -- geometry (W1-1: the app's first persisted state) --------------------
    def _restore_geometry(self) -> None:
        """Last session's size and position, clamped to the current screen.

        The clamp matters as much as the restore: a geometry remembered from a
        big monitor must not reopen 900px tall on the 1366x768 target laptop -
        that would be the original screen-fit bug wearing a QSettings coat.
        """
        stored = QSettings().value("window/geometry")
        if stored is not None:
            self.restoreGeometry(stored)
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        if stored is None or (self.width() > avail.width()
                              or self.height() > avail.height()):
            self.resize(*initial_size(avail.width(), avail.height()))
        # Fully off-screen (a monitor that is no longer attached) → bring back.
        if screen is not None and not avail.intersects(self.frameGeometry()):
            self.move(avail.topLeft())

    # -- construction ------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)

        page = QWidget(self)
        column = QVBoxLayout(page)
        column.setContentsMargins(GUTTER, VGAP, GUTTER, VGAP)
        column.setSpacing(GAP_BLOCK)
        self._page_column = column   # the About card inserts itself here
        self._about_card: QFrame | None = None

        self.drop_zone = DropZone(page)
        # The pending list belongs to the chip that discloses it; the window
        # owns the model (`_pending`) and every mutation, so it holds the alias.
        self.pending_list = self.drop_zone.pending_list
        self.pending_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        column.addWidget(self.drop_zone)

        self.analysis_card = AnalysisCard(page)
        column.addWidget(self.analysis_card)

        # ONE chooser (W1-13): the four preset cards and the estimate table
        # used to render the same decision twice, costing 400-500px of a
        # 150%-scaled laptop's ~430px client. `presets` stays as an alias so
        # every caller and test keeps its contract.
        self.compare_table = CompareTable(page)
        self.compare_table.set_tool_availability(self.tools)
        self.presets = self.compare_table
        column.addWidget(self.compare_table)
        column.addStretch(1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(page)
        self.tabs.addTab(self._scroll, self.tr("Compress"))

        self.extract_tab = ExtractTab(self)
        self.tabs.addTab(self.extract_tab, self.tr("Extract"))

        self._build_activity_tab()

        # I1: every persisted preference, plus the tool inventory the status
        # strip has to elide at narrow widths.
        self.settings_tab = SettingsTab(self.tools, DEFAULT_TEMP, self)
        self.settings_tab.load()
        self.tabs.addTab(self.settings_tab, self.tr("Settings"))

        # The window shell (W1-2): the action bar carrying the commit button
        # and the resolved destination NEVER scrolls - it sits between the tab
        # pages and the status bar. The Advanced panel expands upward from it,
        # outside the scrolling page, so opening it displaces no content.
        # (Not a Qt.Popup: its Browse buttons open QFileDialogs, which would
        # dismiss a popup, returning the user to a vanished panel.)
        self.advanced_panel = AdvancedPanel(DEFAULT_TEMP, self)
        self.advanced_panel.fallback_threads = self.settings_tab.threads.value
        self.settings_tab.threads.valueChanged.connect(
            lambda _value: self.advanced_panel._show_ram())
        self.advanced_panel.format_box.currentIndexChanged.connect(
            lambda _i: self._sync_suffix_label())
        self._build_action_bar()
        central = QWidget(self)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        # W2-9: the banner sits above everything and costs zero height while
        # hidden. It is the app's only way of asking a question now.
        self.banner = Banner(central)
        shell.addWidget(self.banner)
        shell.addWidget(self.tabs, 1)
        shell.addWidget(self.advanced_panel)
        shell.addWidget(self.action_bar)
        self.setCentralWidget(central)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._build_status_bar()
        self._build_actions()
        self._set_tab_order()

    def _build_activity_tab(self) -> None:
        """Everything about work in flight, on one page (W2-1).

        Deliberately NOT a QScrollArea: the queue table is the content, so it
        takes the height that is left and scrolls internally. That is also why
        its old 430px cap could go - the cap only ever existed to stop an
        empty queue pushing the results panel off the Compress column.
        """
        self.activity_page = QWidget(self)
        column = QVBoxLayout(self.activity_page)
        column.setContentsMargins(GUTTER, VGAP, GUTTER, VGAP)
        column.setSpacing(GAP_BLOCK)

        header = QHBoxLayout()
        header.setSpacing(GAP_INTRA)
        title = QLabel(self.tr("Queue"), self.activity_page)
        title.setObjectName("Title")
        self.queue_status = QLabel("", self.activity_page)
        self.queue_status.setObjectName("Muted")
        self.pause_button = QPushButton(self.tr("Pause queue"), self.activity_page)
        self.pause_button.setToolTip(self.tr(
            "The running job finishes its current stage before holding — "
            "no work is thrown away."))
        self.pause_button.setAccessibleDescription(self.pause_button.toolTip())
        self.clear_done_button = QPushButton(self.tr("Clear finished"),
                                             self.activity_page)
        header.addWidget(title)
        header.addWidget(self.queue_status)
        header.addStretch(1)
        header.addWidget(self.clear_done_button)
        header.addWidget(self.pause_button)
        column.addLayout(header)

        # The most recent result sits above the table until wave 3 folds it
        # into the row expander the table already owns.
        self.results = ResultsPanel(self.theme_name, self.activity_page)
        column.addWidget(self.results)

        self.queue_table = QueueTable(self.activity_page)
        column.addWidget(self.queue_table, 1)

        # I3: past jobs live *inside* Activity rather than in a fifth tab.
        # Four top-level destinations is WinUI's ceiling and the reason this
        # app has a tab bar rather than a nav rail (research/23 section 2.3);
        # adding a fifth to hold "the same thing, but finished" would spend
        # that budget on a distinction the user does not draw. Behind a
        # disclosure, so the running queue keeps the space by default.
        self.history_toggle = QToolButton(self.activity_page)
        self.history_toggle.setText(self.tr("Past jobs"))
        self.history_toggle.setCheckable(True)
        self.history_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.history_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.history_toggle.setAccessibleDescription(
            self.tr("Show jobs that have already finished"))
        column.addWidget(self.history_toggle)

        self.history_tab = HistoryTab(self.activity_page)
        self.history_tab.compressAgain.connect(self._compress_again)
        self.history_tab.setVisible(False)
        self.history_toggle.toggled.connect(self._toggle_history)
        column.addWidget(self.history_tab, 1)

        self._activity_index = self.tabs.addTab(self.activity_page,
                                                self.tr("Activity"))

    def _build_actions(self) -> None:
        """The QAction registry (W1-9): one action per capability, shared by
        the corner menu and the window-wide shortcuts, and later the seed for
        I10's Ctrl+K palette. Behind a hamburger button in the tab-bar corner,
        never a QMenuBar row - the 150%-scaling height budget has no ~23px to
        spare (research/23 §2.4). QActions fire fine without a visible menu bar.
        """
        self.actions: dict[str, QAction] = {}

        def act(key: str, text: str, slot, shortcut: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)          # shortcuts work window-wide
            self.actions[key] = action
            return action

        act("command-palette", self.tr("Find a command…"),
            self._open_palette, "Ctrl+K")
        act("add-files", self.tr("Add files…"), self.drop_zone._pick_files, "Ctrl+O")
        act("add-folder", self.tr("Add folder…"), self.drop_zone._pick_folder,
            "Ctrl+Shift+O")
        act("open-archive", self.tr("Open archive (Extract)…"),
            lambda: self.tabs.setCurrentWidget(self.extract_tab), "Ctrl+E")
        act("pause", self.tr("Pause/resume queue"), self._toggle_pause, "Ctrl+P")
        act("clear-finished", self.tr("Clear finished jobs"), self._clear_finished)
        act("theme", self.tr("Toggle light/dark theme"), self.toggle_theme)
        act("about", self.tr("About ExtremeCompressor"), self._show_about, "F1")
        act("exit", self.tr("Exit"), self.close, "Ctrl+Q")

        # U+2261, present in every Windows UI font - the repo has been burned
        # by fancier glyphs before (see dropzone.py's U+2B07 note).
        button = QToolButton(self)
        button.setText("≡")
        button.setAccessibleName(self.tr("Application menu"))
        button.setToolTip(self.tr("Application menu"))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for key in ("add-files", "add-folder", "open-archive"):
            menu.addAction(self.actions[key])
        menu.addSeparator()
        for key in ("pause", "clear-finished"):
            menu.addAction(self.actions[key])
        menu.addSeparator()
        for key in ("theme", "about", "exit"):
            menu.addAction(self.actions[key])
        button.setMenu(menu)
        self.menu_button = button
        self.tabs.setCornerWidget(button, Qt.Corner.TopRightCorner)

    def _show_about(self) -> None:
        """About as an INLINE card, never a QMessageBox - the no-modal rule
        does not have a Help exception."""
        if getattr(self, "_about_card", None) is None:
            card = QFrame(self)
            card.setObjectName("Card")
            box = QVBoxLayout(card)
            box.setContentsMargins(*CARD_MARGINS)
            box.setSpacing(GAP_INTRA)
            head = QHBoxLayout()
            title = QLabel(self.tr("ExtremeCompressor v%s") % __version__, card)
            title.setObjectName("Title")
            head.addWidget(title)
            head.addStretch(1)
            close = QPushButton(self.tr("Close"), card)
            close.clicked.connect(lambda: self._about_card.setVisible(False))
            head.addWidget(close)
            box.addLayout(head)
            # The status strip elides its tool list by design and says so;
            # this is where the full answer lives, so the qualifiers belong
            # here too rather than only in Settings.
            from excmp.tools import LEGACY_ONLY, below_floor
            _stale = {n for n, _got, _need in below_floor(self.tools)}
            tools = ", ".join(
                (f"{name} {info.version}".strip()
                 + (" (legacy)" if name in LEGACY_ONLY else "")
                 + (" — update it" if name in _stale else ""))
                if info else f"{name} (not found)"
                for name, info in self.tools.items())
            body = QLabel(self.tr(
                "Analyzes every file, routes it to the pipeline that suits it, "
                "and verifies a byte-identical restore before claiming success.\n"
                "Tools: %s\n"
                "Shortcuts: Ctrl+O add files · Ctrl+Shift+O add folder · "
                "Ctrl+E extract · Ctrl+P pause · Ctrl+Return compress · F1 this card"
            ) % tools, card)
            body.setObjectName("Subtitle")
            body.setWordWrap(True)
            box.addWidget(body)
            self._about_card = card
            self._page_column.insertWidget(0, card)
        else:
            self._about_card.setVisible(not self._about_card.isVisible())
        if self._about_card.isVisible():
            self.tabs.setCurrentWidget(self._scroll)
            self._scroll.ensureWidgetVisible(self._about_card, 0, VGAP)

    def _build_action_bar(self) -> None:
        self.action_bar = QFrame(self)
        self.action_bar.setObjectName("ActionBar")
        row = QHBoxLayout(self.action_bar)
        row.setContentsMargins(GUTTER, 6, GUTTER, 6)
        row.setSpacing(GAP_INTRA)

        # Destination, visible BEFORE committing: folder + an editable name.
        # 7-Zip puts the Archive field first in its dialog for the same reason;
        # ours also surfaces unique_path()'s " (2)" rename before it surprises.
        self._dest_label = QLabel("", self.action_bar)
        self._dest_label.setObjectName("Muted")
        # Long paths clip rather than stretch the window; full path in tooltip.
        self._dest_label.setSizePolicy(QSizePolicy.Policy.Maximum,
                                       QSizePolicy.Policy.Preferred)
        self._dest_label.setMaximumWidth(430)
        self.name_edit = QLineEdit(self.action_bar)
        self.name_edit.setPlaceholderText(self.tr("archive name"))
        self.name_edit.setAccessibleName(self.tr("Archive name"))
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setMaximumWidth(220)
        self.name_edit.textChanged.connect(lambda _t: self._refresh_actions())
        # Kept in sync with the Format box below. A fixed ".excmp" here would
        # promise one extension while `_output_path_for` wrote another.
        self._suffix_label = QLabel(".excmp", self.action_bar)
        self._suffix_label.setObjectName("Muted")
        suffix = self._suffix_label
        self._name_error = QLabel(self.tr("invalid name"), self.action_bar)
        self._name_error.setProperty("tone", "danger")
        self._name_error.setVisible(False)

        self.advanced_toggle = AdvancedToggle(self.advanced_panel, self.action_bar)
        # I6: stop estimating and go and find out. Beside Compress rather than
        # inside Advanced, because it is the answer to the question the whole
        # Compress page is asking, and secondary-styled because it costs
        # minutes — the estimate is still the default way to decide.
        self.measure_button = QPushButton(self.tr("Measure presets"),
                                          self.action_bar)
        self.measure_button.setAccessibleName(
            self.tr("Measure presets — run every profile on a sample of these "
                    "files and report what each really saved"))
        self.measure_button.setEnabled(False)
        self.clear_button = QPushButton(self.tr("Clear"), self.action_bar)
        self.compress_button = QPushButton(self.tr("Compress"), self.action_bar)
        self.compress_button.setProperty("variant", "primary")
        self.compress_button.setEnabled(False)

        row.addWidget(self._dest_label)
        row.addWidget(self.name_edit)
        row.addWidget(suffix)
        row.addWidget(self._name_error)
        row.addStretch(1)
        row.addWidget(self.advanced_toggle)
        row.addWidget(self.measure_button)
        row.addWidget(self.clear_button)
        row.addWidget(self.compress_button)

    def _on_tab_changed(self, index: int) -> None:
        """The action bar commits compress jobs; other tabs have their own."""
        on_compress = self.tabs.widget(index) is self._scroll
        self.action_bar.setVisible(on_compress)
        if not on_compress:
            self.advanced_panel.setVisible(False)
            self.advanced_toggle.setChecked(False)

    def _output_name_ok(self) -> bool:
        """The editable name goes through the same validator archive entries
        do - the app must not create a file it would refuse to read."""
        text = self.name_edit.text().strip()
        if not text:
            return True   # empty = default name, always fine
        try:
            parts = safe_relpath(text + ".excmp")
        except UnsafePathError:
            return False
        return len(parts.parts) == 1

    def _build_status_bar(self) -> None:
        """The persistent job strip (W2-1) plus the tool inventory.

        Priority when the window is narrow: **what the queue is doing wins**.
        The tool list is reference material and is repeated in full in About,
        so it is the half that elides.
        """
        from excmp.tools import LEGACY_ONLY, below_floor

        bar = self.statusBar()
        # A legacy tool is found and runnable but never chosen for a new
        # archive. Listing it bare made the strip advertise a tool the app
        # will never run, which is the wart docs/NEXT-SESSION-START-HERE.md
        # recorded; the qualifier is cheaper than either hiding or lying.
        found = [f"{name} (legacy)" if name in LEGACY_ONLY else name
                 for name, info in self.tools.items() if info is not None]
        missing = [name for name in ("7z", "precomp") if self.tools.get(name) is None]
        text = self.tr("Tools found: %s") % (", ".join(found) or self.tr("none"))
        if missing:
            text += self.tr("  ·  missing: %s") % ", ".join(missing)
        for name, got, needed in below_floor(self.tools):
            text += self.tr("  ·  %(tool)s %(got)s is below %(needed)s — update it") % {
                "tool": name, "got": got, "needed": needed}
        self._tools_text = text
        self._tools_label = QLabel(text, self)
        self._tools_label.setObjectName("Muted")
        self._tools_label.setToolTip(text)
        # Ignored width: the strip must never be the reason the window has a
        # minimum width. The elision is done by hand so it ends in an ellipsis
        # rather than a hard clip.
        self._tools_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Preferred)
        bar.addWidget(self._tools_label, 1)

        self.job_status = QPushButton("", self)
        self.job_status.setObjectName("StatusJob")
        self.job_status.setFlat(True)
        self.job_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.job_status.setToolTip(self.tr("Show the queue"))
        self.job_status.clicked.connect(self._show_activity)

        self.status_progress = QProgressBar(self)
        self.status_progress.setRange(0, 100)
        self.status_progress.setTextVisible(False)
        # Fixed BOTH ways: the status bar stretches a permanent widget to its
        # own height, and QSS `height` does not stop it - the mini bar came
        # out as a 40px slab.
        self.status_progress.setFixedSize(90, 10)
        self.status_progress.setAccessibleName(self.tr("Current job progress"))
        self.status_progress.setVisible(False)

        self.theme_button = QPushButton(self.tr("Light mode"), self)
        self.theme_button.setFlat(True)
        self.theme_button.setAccessibleName(self.tr("Toggle light and dark theme"))
        self.theme_button.clicked.connect(self.toggle_theme)
        self._version_label = QLabel(f"v{__version__}", self)
        for widget in (self.job_status, self.status_progress,
                       self._version_label, self.theme_button):
            bar.addPermanentWidget(widget)

    def _show_activity(self) -> None:
        self.tabs.setCurrentWidget(self.activity_page)

    def _elide_tools(self) -> None:
        reserved = 56 + sum(
            widget.sizeHint().width() for widget in
            (self.job_status, self._version_label, self.theme_button))
        if self.status_progress.isVisibleTo(self):
            reserved += self.status_progress.width()
        available = max(48, self.statusBar().width() - reserved)
        metrics = QFontMetrics(self._tools_label.font())
        self._tools_label.setText(metrics.elidedText(
            self._tools_text, Qt.TextElideMode.ElideRight, available))

    def _set_tab_order(self) -> None:
        """Explicit keyboard path through the flow, top to bottom."""
        cards = self.presets.cards
        chain: list[QWidget] = [
            self.drop_zone.files_button, self.drop_zone.folder_button,
            *[cards[p] for p in
              (Profile.FAST, Profile.NORMAL, Profile.EXTREME, Profile.INSANE)
              if p in cards],
            self.advanced_toggle, self.measure_button, self.clear_button,
            self.compress_button,
            self.clear_done_button, self.pause_button, self.queue_table,
        ]
        for first, second in zip(chain, chain[1:]):
            self.setTabOrder(first, second)

    def _wire(self) -> None:
        self.drop_zone.pathsAdded.connect(self.add_paths)
        self.drop_zone.clearRequested.connect(self.clear_pending)
        self.pending_list.customContextMenuRequested.connect(self._pending_menu)
        # Del removes the highlighted item, scoped to the list so it cannot
        # fire while the archive-name field has focus.
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.pending_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_selected_pending)
        self.presets.profileChanged.connect(self._on_profile_changed)
        # The chooser's rows are destroyed and recreated on every analysis;
        # without this, the keyboard path through them dies the first time
        # estimates arrive (found by the pre-merge audit).
        self.presets.rowsRebuilt.connect(self._set_tab_order)
        self.compress_button.clicked.connect(self.start_compression)
        self.measure_button.clicked.connect(self.toggle_measurement)
        self.clear_button.clicked.connect(self.clear_pending)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.clear_done_button.clicked.connect(self._clear_finished)

        self.queue.jobAdded.connect(self._on_job_added)
        self.queue.jobStateChanged.connect(self._on_job_state)
        self.queue.jobProgress.connect(self._on_job_progress)
        self.queue.jobLog.connect(self.queue_table.append_log)
        self.queue.jobDone.connect(self._on_job_done)
        self.queue.jobFailed.connect(self._on_job_failed)
        self.queue.queueIdle.connect(self._on_queue_idle)
        self.queue.pausedChanged.connect(self._on_paused_changed)

        self.queue_table.cancelRequested.connect(self.queue.cancel)
        self.queue_table.menuRequested.connect(self._show_queue_menu)
        self.results.openFolderRequested.connect(open_in_explorer)
        self.results.dismissed.connect(self._reset_flow)
        self.extract_tab.extractRequested.connect(self._start_extract)
        self.extract_tab.verifyRequested.connect(self.start_verification)
        self.extract_tab.passwordRequired.connect(self._ask_archive_password)
        self.extract_tab.extractSelectedRequested.connect(
            self._start_selected_extract)

        QShortcut(QKeySequence.StandardKey.Open, self, self.drop_zone._pick_files)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.start_compression)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss(self.theme_name))
        self.theme_button.setText(
            self.tr("Dark mode") if self.theme_name == "light" else self.tr("Light mode"))
        # W2-5: the SVG glyphs are tinted with theme tokens, so they have to be
        # repainted here. This is the thing emoji could not do.
        self.compare_table.retint(self.theme_name)
        # W2-6: Qt paints its client area but never the OS caption, so a dark
        # app under a light title bar reads as half-finished. No-ops silently
        # off Windows and on builds that do not know the DWM attribute.
        set_dark_titlebar(int(self.winId()), self.theme_name == "dark")

    def toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        QSettings().setValue("settings/theme", self.theme_name)
        self._apply_theme()

    # -- intake ------------------------------------------------------------
    def add_paths(self, paths: list[Path]) -> None:
        """Append dropped/picked paths and (re)run the analysis."""
        known = {str(p).lower() for p in self._pending}
        for path in paths:
            if str(path).lower() not in known:
                self._pending.append(Path(path))
                known.add(str(path).lower())
        if not self._pending:
            return
        self.results.hide_panel()
        self.analysis_card.set_busy(len(self._pending))
        self._refresh_pending_view()
        self._refresh_actions()
        self._analysis_notes.clear()
        worker = AnalysisWorker(list(self._pending), self.presets.current_profile(),
                                self.tools, self._analysis_signals)
        self._analysis_pool.start(worker)

    def handle_intake(self, intake: Intake) -> None:
        """What an Explorer verb, or a second launch, asked for (I5).

        Files named but gone are *said*, not skipped: a menu click that does nothing looks like
        a broken menu. An archive path that is a folder is refused for the same reason it
        would be on the Extract tab. ``extract-here`` and ``verify`` go through the signals the
        buttons emit, so they get the checks the buttons get.
        """
        found = [p for p in intake.paths if p.exists()]
        gone = [p for p in intake.paths if not p.exists()]
        if gone:
            shown = ", ".join(p.name or str(p) for p in gone[:3])
            more = f" (+{len(gone) - 3})" if len(gone) > 3 else ""
            self.banner.show_message(self.tr("Not found: %s%s") % (shown, more), tone="warn")
        self._bring_to_front()
        if not found:
            return
        if intake.action == "compress":
            self.tabs.setCurrentWidget(self._scroll)
            self.add_paths(found)
            return
        archive = found[0]
        if not archive.is_file():
            self.banner.show_message(self.tr("%s is a folder, not an archive.") % archive.name,
                                     tone="warn")
            return
        tab = self.extract_tab
        tab.dest_edit.setText("")           # set_archive suggests one only for an empty field
        tab.set_archive(archive)
        self.tabs.setCurrentWidget(tab)
        if intake.action == "extract-here":
            # No destination is shown before this runs, so it never goes anywhere it could
            # replace something (see ExtractTab.safe_here_destination).
            tab.dest_edit.setText(str(tab.safe_here_destination(archive)))
            if not tab.request_extract():
                self.banner.show_message(
                    self.tr("%s cannot be extracted from here.") % archive.name, tone="warn")
        elif intake.action == "verify":
            if not tab.request_verify():
                self.banner.show_message(
                    self.tr("%s cannot be verified: only ExtremeCompressor archives carry the "
                            "SHA-256 ledger a verification compares against.") % archive.name,
                    tone="warn")

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self)            # Windows may refuse focus; this flashes the taskbar

    def clear_pending(self) -> None:
        self._pending.clear()
        self._infos = []
        self._summary = None
        self._forget_measurements()
        self.analysis_card.clear()
        self.compare_table.clear()
        self.results.hide_panel()
        self._refresh_pending_view()
        self._refresh_actions()

    # -- W2-10: review and remove before committing --------------------------
    def _refresh_pending_view(self) -> None:
        """Keep the chip and the list in step with ``_pending``."""
        self.pending_list.clear()
        for path in self._pending:
            item = QListWidgetItem(path.name or str(path), self.pending_list)
            item.setToolTip(str(path))
        total = self._summary.total_bytes if self._summary is not None else 0
        self.drop_zone.set_pending(len(self._pending), total)
        self.drop_zone.fit_pending_list()

    def remove_selected_pending(self) -> None:
        """Drop one item and re-plan from the FileInfo list already in memory.

        The same trick as `_on_profile_changed`: entropy sampling is the
        expensive part, and removing an item changes none of the samples that
        survive. On the real HDD corpus this is the difference between instant
        and another full scan.
        """
        row = self.pending_list.currentRow()
        if not 0 <= row < len(self._pending):
            return
        removed = self._pending.pop(row)
        if not self._pending:
            self.clear_pending()
            return
        self._infos = [info for info in self._infos
                       if not _is_under(Path(info.path), removed)]
        # I6: different bytes, different answer. This path mutates the input
        # without going back through analysis, so it is the one input change
        # that `_on_analysis_ready` does not clean up after — and leaving the
        # measurement here attributed a measured archive size to a folder that
        # no longer contains the files it was measured on.
        self._forget_measurements()
        self._refresh_pending_view()
        self._resummarize()

    def _pending_menu(self, pos) -> None:
        item = self.pending_list.itemAt(pos)
        if item is None:
            return
        self.pending_list.setCurrentItem(item)
        path = self._pending[self.pending_list.currentRow()]
        menu = QMenu(self.pending_list)
        menu.addAction(self.tr("Remove"), self.remove_selected_pending)
        menu.addAction(self.tr("Show in Explorer"),
                       lambda: open_in_explorer(path))
        menu.exec(self.pending_list.viewport().mapToGlobal(pos))

    def _reset_flow(self) -> None:
        self.results.hide_panel()
        self.clear_pending()

    def _on_analysis_ready(self, infos: object, summary: object) -> None:
        if not isinstance(summary, AnalysisSummary):
            return
        self._infos = list(infos or [])
        self._summary = summary
        self._forget_measurements()
        self.analysis_card.set_summary(summary)
        # B21b: the chip's total comes from the summary. It was refreshed only
        # when the recommendation moved the selected profile, so a drop that
        # kept the same recommendation showed the previous total (or 0 B).
        self._refresh_pending_view()

        # The table's recommendation is the estimate-aware one, so take the badge
        # from there rather than calling recommend_profile() again - otherwise the
        # card could suggest a preset the table has flagged as not worth it.
        rows = self._refresh_estimates()
        suggested = next((r for r in rows if r.recommended), None)
        if suggested is not None:
            self.presets.set_recommendation(suggested.profile, suggested.reason)
        else:
            profile, reason = recommend_profile(summary)
            self.presets.set_recommendation(profile, reason)
        self._refresh_actions()
        self.analysisFinished.emit()

    def _on_analysis_progress(self, done: int, total: int) -> None:
        self.analysis_card.set_progress(done, total)

    def _on_analysis_note(self, message: str) -> None:
        """A file the analysis could not read (K3).

        Deliberately not a failure: before this, `analyze_file` raising on an
        open Excel or Outlook document painted the whole analysis card red with
        the raw "[Errno 13] Permission denied" and the user lost the size
        estimate, the route breakdown and the profile recommendation for the
        entire selection because of one file.
        """
        self._analysis_notes.append(message)
        self.analysis_card.set_note("; ".join(self._analysis_notes[:3]))

    def _on_analysis_failed(self, message: str) -> None:
        self.analysis_card.set_error(message)
        self._summary = None
        self._forget_measurements()
        self.compare_table.clear()
        self._refresh_actions()
        self.analysisFinished.emit()

    def _on_profile_changed(self, profile: object) -> None:
        """Re-plan without re-reading the files - entropy sampling is the
        expensive part and nothing about the input changed."""
        if not self._infos or not isinstance(profile, Profile):
            return
        # J5: once the user picks for themselves, stop re-suggesting. `select()`
        # defaults to emit=False precisely so offering a remembered profile
        # does not look like a manual choice.
        self._profile_touched = True
        self._resummarize(profile)

    def _resummarize(self, profile: Profile | None = None) -> None:
        """Re-plan and repaint from the cached FileInfo list. No file is read."""
        if not self._infos:
            return
        profile = profile or self.presets.current_profile()
        self._summary = self._summary_for(profile)
        self.analysis_card.set_summary(self._summary)
        self._refresh_estimates()
        self._refresh_pending_view()
        self._refresh_actions()

    def _summary_for(self, profile: Profile) -> AnalysisSummary:
        """The analysis as ``profile`` would route it. Pure: no file is read
        and nothing is repainted."""
        the_plan = make_plan(self._infos, profile, self.tools)
        reference = make_plan(self._infos, strongest_profile(self.tools), self.tools)
        return summarize(self._infos, the_plan, self.tools, reference)

    def _refresh_estimates(self) -> list:
        """Recompute the comparison table. Costs four ``planner.plan()`` calls
        and some arithmetic - no file is re-read."""
        if not self._infos or self._summary is None:
            self.compare_table.clear()
            return []
        # J7: whatever this machine has taught us, with the shipped defaults
        # as the cold-start prior. The two corpora behind those defaults
        # disagreed by 2.5x on 7-Zip alone, purely because one was on an
        # external drive - no constant is right for every machine.
        from excmp.calibrate import blended_rates
        whole = (self._comparison is not None
                 and self._comparison.sample.is_whole_input)
        rows = profile_comparison(self._infos, self.tools, self._summary,
                                  rates=blended_rates(),
                                  measured=self._measured,
                                  measured_whole_input=whole,
                                  zpaq_threads=(self.advanced_panel.threads.value()
                                                or self.settings_tab.threads.value()))
        self.compare_table.set_rows(rows, self._measured_caption)
        self._offer_remembered_profile()
        self._warn_if_long(rows)
        return rows

    # -- I6: measuring instead of estimating ---------------------------------
    def _forget_measurements(self) -> None:
        """Different bytes, different answer. Anything else would leave last
        folder's measured ratio sitting on this folder's card."""
        if self._comparison is not None and self._comparison.is_running():
            self._comparison.cancel()
        self._comparison = None
        self._measured = {}
        self._measured_caption = ""
        self._refresh_measure_button()

    def _refresh_measure_button(self) -> None:
        running = (self._comparison is not None
                   and self._comparison.is_running())
        self.measure_button.setText(
            self.tr("Stop measuring") if running else self.tr("Measure presets"))
        self.measure_button.setEnabled(running or bool(self._infos))

    def toggle_measurement(self) -> None:
        """Start a comparison run, or stop the one in flight."""
        if self._comparison is not None and self._comparison.is_running():
            self._comparison.cancel()
            return
        if not self._infos:
            return
        try:
            options = self.advanced_panel.stage_options()
        except ValueError:
            # A bad Parameters line is the compress path's problem to report;
            # measuring with the shipped defaults still answers the question.
            options = None
        run = ComparisonRun(self.queue, self.tools, self._infos,
                            work_dir=Path(self.queue.temp_dir) / "compare",
                            options=options, parent=self)
        if not run.sample.files:
            return
        self._comparison = run
        run.measured.connect(self._on_profile_measured)
        run.failed.connect(self._on_profile_measure_failed)
        run.finished.connect(self._on_measurement_finished)

        # The price, before it is paid. A comparison is four compressions of
        # up to 100 MB on a two-core laptop; starting one without saying so
        # is how a deliberate measurement becomes a mystery hang.
        sample = run.sample
        if sample.over_cap:
            self.banner.show_message(
                self.tr("The smallest file here is %s, so there is no small "
                        "sample to take — measuring will compress all of it, "
                        "%d times.") % (fmt_size(sample.total_bytes),
                                        run.job_count),
                tone="warn",
                actions=[(self.tr("Measure anyway"), self._begin_measurement),
                         (self.tr("Not now"), self._abandon_measurement)])
            return
        self._begin_measurement()

    def _begin_measurement(self) -> None:
        # Unconditionally, and first: this is a banner action, and the banner
        # does not dismiss itself. Bailing out below without hiding it left a
        # "Measure anyway" button on screen that did nothing when pressed.
        self.banner.hide_banner()
        run = self._comparison
        if run is None or run.is_running():
            return
        # Everything on the panel belongs to exactly one run — but the old
        # numbers are cleared HERE, not when the button is pressed. Clearing
        # them before the over-cap question was answered threw away a
        # completed measurement for a run the user then declined.
        self._measured = {}
        self._measured_caption = ""
        run.start()
        self._refresh_estimates()
        self._refresh_measure_button()
        self._refresh_actions()

    def _abandon_measurement(self) -> None:
        self.banner.hide_banner()
        self._comparison = None
        self._refresh_measure_button()

    def _on_profile_measured(self, profile: object) -> None:
        """One profile landed. Repaint now rather than at the end — a run
        stopped half way should leave behind the half it earned."""
        run = self._comparison
        if run is None or not isinstance(profile, Profile):
            return
        from .suggest import measurement_caption

        self._measured = dict(run.results)
        self._measured_caption = measurement_caption(run.sample,
                                                     len(self._measured))
        self._refresh_estimates()

    def _on_profile_measure_failed(self, profile: object, message: str) -> None:
        if not isinstance(profile, Profile):
            return
        # No number is invented for a profile that did not finish: the card
        # keeps its estimate and the banner says which one dropped out.
        self.banner.show_message(
            self.tr("%s could not be measured: %s") % (profile.value, message),
            tone="warn")

    def _on_measurement_finished(self) -> None:
        self._refresh_measure_button()
        self._refresh_actions()

    def _dominant_category(self):
        """The category holding the most bytes, which is the judgement a
        person actually repeats ("this is a folder of video")."""
        if self._summary is None or not self._summary.by_category:
            return None
        return max(self._summary.by_category.items(), key=lambda kv: kv[1])[0]

    def _offer_remembered_profile(self) -> None:
        """J5: pre-select what was chosen last time for this kind of content.

        It **suggests**; it never overrides. Applied once per drop, and only
        while the user has not touched the chooser - a remembered choice that
        silently outranked the analyser would make the recommendation
        unpredictable, which is worse than the occasional extra click.
        """
        from .prefs import remembered_profile

        category = self._dominant_category()
        if category is None or getattr(self, '_profile_touched', False):
            return
        remembered = remembered_profile(category)
        if remembered is None or remembered == self.compare_table.current_profile():
            return
        self.compare_table.select(remembered)
        self.banner.show_message(
            self.tr("Using %s, which you picked last time for mostly %s "
                    "files.") % (remembered.value, category.value),
            tone="info")

    def _warn_if_long(self, rows) -> None:
        """J6: say how long this will take before it is paid for.

        Inline, never a dialog - see the no-modal rule. The comparison table
        already shows the *relative* cost; this is the absolute one, because
        "about 3 hours" means something to a person that "0.842 MB/s" does not.
        """
        from .suggest import long_job_warning

        chosen = self.compare_table.current_profile()
        row = next((r for r in rows if r.profile == chosen), None)
        seconds = getattr(row, "time_seconds", None) if row else None
        if seconds is None:
            return
        warning = long_job_warning(seconds)
        if warning:
            self.banner.show_message(warning, tone="warn")


    # -- running -----------------------------------------------------------
    def _output_folder_for(self, inputs: list[Path]) -> Path:
        folder_text = self.advanced_panel.output_dir.text().strip('" ')
        return Path(folder_text) if folder_text else inputs[0].parent

    def _output_path_for(self, inputs: list[Path]) -> Path:
        first = inputs[0]
        stem = self.name_edit.text().strip() if self._output_name_ok() else ""
        stem = stem or first.stem or first.name
        # The extension follows the Format box. Hard-coding .excmp meant
        # choosing "plain .zip" wrote a zip called holiday.excmp - a file
        # Explorer would not open and no other tool would recognise.
        return unique_path(
            self._output_folder_for(inputs) / f"{stem}{self._output_suffix()}")

    def _output_suffix(self) -> str:
        """The extension the chosen format actually produces."""
        return {"excmp": ".excmp", "7z": ".7z", "zip": ".zip"}.get(
            self.advanced_panel.archive_format(), ".excmp")

    def _sync_suffix_label(self) -> None:
        label = getattr(self, "_suffix_label", None)
        if label is not None:
            label.setText(self._output_suffix())

    def start_compression(self) -> None:
        if not self._pending:
            return
        inputs = list(self._pending)
        # Advanced (per-job) wins over Settings (the remembered default), so a
        # one-off override does not silently rewrite the preference.
        self.queue.temp_dir = Path(self.advanced_panel.temp_dir.text().strip('" ')
                                   or self.settings_tab.temp_dir.text().strip('" ')
                                   or DEFAULT_TEMP)
        self.queue.threads = (self.advanced_panel.threads.value()
                              or self.settings_tab.threads.value())
        # A bad Parameters line stops the job here, in the banner, rather than
        # failing three minutes into a chain with 7-Zip's own error.
        try:
            options = self.advanced_panel.stage_options()
        except ValueError as exc:
            self.banner.show_message(
                self.tr("That Parameters line was not accepted: %s") % exc,
                tone="warn",
                actions=[(self.tr("Edit it"), self._focus_params)])
            return
        # The same treatment for the protect/split/format controls: a
        # mismatched password or an unreadable volume size stops the job here,
        # in the banner, rather than three minutes into a chain.
        try:
            extras = self.advanced_panel.job_extras()
        except ValueError as exc:
            self.banner.show_message(
                self.tr("That job could not be started: %s") % exc,
                tone="warn",
                actions=[(self.tr("Open Advanced"), self._focus_params)])
            return
        self.results.hide_panel()
        # The job's bar and self-test estimate read its summary's chain, so it
        # has to describe the profile that will actually run. The one on screen
        # was built for whatever was selected when the folder was dropped, and
        # a remembered choice offered afterwards (select() does not emit)
        # leaves the two different.
        profile = self.presets.current_profile()
        summary = self._summary
        if summary is not None and self._infos:
            summary = self._summary_for(profile)
        self.queue.add_compress(inputs, self._output_path_for(inputs),
                                profile, summary,
                                sidecar=self.settings_tab.sidecar_toggle.isChecked(),
                                options=options, extras=extras)
        # The password belongs to the job that just started, not to the next
        # folder somebody drops. Cleared here, beside the other per-job state.
        # J5: remember what was chosen for this kind of content, so the next
        # folder of the same shape starts on it.
        category = self._dominant_category()
        if category is not None:
            from .prefs import remember_profile
            remember_profile(category, self.presets.current_profile())
        self.advanced_panel.forget_password()
        self._profile_touched = False
        self._pending = []
        self._forget_measurements()
        self.analysis_card.clear()
        self.compare_table.clear()
        self._infos = []
        self._summary = None
        self._refresh_actions()

    def _start_extract(self, archive: object, dest: object) -> None:
        self.queue.add_extract(Path(archive), Path(dest))

    # -- G2 --------------------------------------------------------------
    def _ask_archive_password(self, archive: object) -> None:
        """Ask inline, when the archive turns out to need it (File Roller's
        timing). The Banner owns the field and wipes it on submit, so this
        window never holds the secret in a widget of its own.
        """
        self.banner.ask_secret(
            self.tr("%s keeps its file names encrypted. Enter its password to "
                    "see what is inside.") % Path(archive).name,
            self.tr("Unlock"),
            self.extract_tab.unlock_with)

    def _start_selected_extract(self, archive: object, names: object) -> None:
        """Quote the price of a solid archive before charging it.

        Ticking one 3 KB file out of a 4 GB solid archive replays the whole
        chain. That is inherent to solid compression, not a bug - but a
        progress bar that runs for twenty minutes after a user asked for one
        small file is indistinguishable from a hang unless they were told.
        """
        archive, names = Path(archive), list(names)
        dest = Path(self.extract_tab.dest_edit.text().strip('" '))
        if not str(dest):
            self.banner.show_message(
                self.tr("Choose where the files should go first."), tone="warn")
            return

        listing = self.extract_tab.current_listing()
        solid = bool(listing is not None and listing.solid)
        replay = 0
        if solid and listing is not None and listing.ledger_backed:
            from excmp.engine import selection_cost
            cost = selection_cost(archive, names)
            solid, replay = cost.solid, cost.bytes_to_replay
        if solid:
            note = (self.tr(
                "%(n)d file(s) selected, but this archive is solid: reaching "
                "them replays %(bytes)s of compressed data.")
                % {"n": len(names), "bytes": fmt_size(replay)} if replay else
                self.tr("%d file(s) selected, but this archive is solid: "
                        "reaching them means decompressing the whole stream.")
                % len(names))
            self.banner.show_message(
                note, tone="warn",
                actions=[(self.tr("Extract anyway"),
                          lambda: self._run_selected(archive, names, dest)),
                         (self.tr("Cancel"), self.banner.hide_banner)])
            return
        self._run_selected(archive, names, dest)

    def _run_selected(self, archive: Path, names: list, dest: Path) -> None:
        self.banner.hide_banner()
        self.queue.add_extract_selected(
            archive, dest, names, self.extract_tab.current_password())

    def _focus_params(self) -> None:
        self.banner.hide_banner()
        self.advanced_panel.setVisible(True)
        self.advanced_panel.params.setFocus()
        self.advanced_panel.params.selectAll()

    def start_verification(self, archive: object) -> None:
        """Queue a verify. Deliberately ignores the destination field - the
        whole promise of this verb is that nothing is produced."""
        self.queue.add_verify(Path(archive))

    def _toggle_pause(self) -> None:
        self.queue.toggle_pause()

    # -- context menus (W1-8) ------------------------------------------------
    def _show_queue_menu(self, job_id: str, global_pos) -> None:
        """Right-click (or the menu key / Shift+F10) on a queue row. Every
        item reuses an existing slot; before this, only the LAST job's output
        was reachable, through the results panel."""
        job = self.queue.job(job_id)
        if job is None:
            return
        menu = QMenu(self)

        cancel = menu.addAction(self.tr("Cancel"))
        cancel.setEnabled(not job.state.is_terminal)
        cancel.triggered.connect(lambda: self.queue.cancel(job_id))

        show_log = menu.addAction(self.tr("Show log"))
        show_log.triggered.connect(lambda: self.queue_table.show_log(job_id))
        menu.addSeparator()

        done = job.state is JobState.DONE and job.out_path is not None
        open_folder = menu.addAction(self.tr("Open output folder"))
        open_folder.setEnabled(done)
        open_folder.triggered.connect(lambda: open_in_explorer(job.out_path))

        copy_path = menu.addAction(self.tr("Copy output path"))
        copy_path.setEnabled(job.out_path is not None)
        copy_path.triggered.connect(
            lambda: QApplication.clipboard().setText(str(job.out_path)))

        copy_cmd = menu.addAction(self.tr("Copy as command"))
        copy_cmd.setEnabled(job.kind is JobKind.COMPRESS)
        copy_cmd.triggered.connect(lambda: QApplication.clipboard().setText(
            self._job_as_command(job)))

        menu.exec(global_pos)

    @staticmethod
    def _job_as_command(job: Job) -> str:
        """The CLI line that reproduces this job - the cheapest 'this tool is
        scriptable' signal there is. The CLI has existed all along."""
        quoted = " ".join(f'"{p}"' for p in job.inputs)
        line = (f'python -m excmp compress {quoted} -o "{job.out_path}" '
                f"-p {job.profile.value}")
        # Only the non-defaults, so an ordinary job still yields a line
        # somebody can read - which is the entire point of the feature.
        if getattr(job, "archive_format", "excmp") != "excmp":
            line += f" --format {job.archive_format}"
        if getattr(job, "recovery", None):
            line += f" --recovery {job.recovery}"
        if getattr(job, "split", None):
            line += f" --split {job.split}"
        if getattr(job, "password", None):
            # The switch, never the value. `--password` takes no argument
            # precisely because argv is visible in the process table and lands
            # in shell history; pasting the secret here would undo that. And
            # omitting the switch entirely would hand somebody a line that
            # quietly produces an UNENCRYPTED archive.
            line += " --password"
        return line

    def _toggle_history(self, open_: bool) -> None:
        self.history_toggle.setArrowType(
            Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        if open_:
            self.history_tab.refresh()
        self.history_tab.setVisible(open_)

    def _open_palette(self) -> None:
        """I10: every action in the app behind one search box.

        Built over `self.actions` rather than a second list, so a new action
        appears here the moment it is registered and the two can never drift.
        """
        from .widgets.palette import CommandPalette

        if getattr(self, "_palette", None) is None:
            self._palette = CommandPalette(self.actions, self)
        self._palette.open_over(self)

    def _compress_again(self, entry) -> None:
        """I3: re-queue a past job with the settings it actually used.

        Missing inputs are reported rather than skipped - silently compressing
        three of the four folders somebody asked for is the kind of helpfulness
        nobody wants. An encrypted job re-prompts, because the password was
        never written down.
        """
        inputs = [Path(p) for p in entry.inputs]
        missing = [p for p in inputs if not p.exists()]
        if missing:
            self.banner.show_message(
                self.tr("Cannot repeat that job: %s is no longer there.")
                % missing[0].name, tone="warn")
            return
        self.tabs.setCurrentIndex(0)
        try:
            self.presets.select(Profile(entry.profile))
        except ValueError:
            pass
        self.advanced_panel.split.setText(
            str(entry.split) if entry.split else "")
        if entry.encrypted:
            self.banner.show_message(
                self.tr("That job was encrypted. Type the password again in "
                        "Advanced - it was never saved."), tone="info")
        # add_paths is the one entry point that analyses, refreshes the
        # pending view and the action bar together - re-implementing any of
        # that here would drift from it.
        self._pending = []
        self.add_paths(inputs)

    def _clear_finished(self) -> None:
        self.queue.clear_finished()
        self.history_tab.refresh()
        self.queue_table.clear_jobs({j.id for j in self.queue.jobs})
        self._refresh_actions()

    # -- queue signals -----------------------------------------------------
    def _on_job_added(self, job_id: str) -> None:
        job = self.queue.job(job_id)
        if job is not None:
            self.queue_table.add_job(job)
        self._refresh_actions()

    def _on_job_state(self, job_id: str, _state: object) -> None:
        job = self.queue.job(job_id)
        if job is not None:
            self.queue_table.update_state(job)
        self._refresh_actions()

    def _on_job_progress(self, job_id: str, _stage: str, pct: float, eta: object) -> None:
        job = self.queue.job(job_id)
        if job is None:
            return
        self.queue_table.update_progress(job)
        self._ensure_taskbar()
        if self._taskbar is not None:
            self._taskbar.set_progress(pct)
        if job.kind is JobKind.EXTRACT:
            self.extract_tab.set_running(pct, job.eta_s)
        self._refresh_actions()

    def _on_job_done(self, job_id: str, result: object) -> None:
        job = self.queue.job(job_id)
        if job is None:
            return
        self.queue_table.update_state(job)
        self.results.show_job(job)
        # No tab switch: people queue several jobs, and yanking the window to
        # Activity after each one turns the second job into a fight with the
        # app (research/23 §7, W2-1's pinned behaviours). What makes the
        # finish visible from anywhere is the status strip and the tab count,
        # both refreshed below.
        if job.kind is JobKind.EXTRACT:
            self.extract_tab.set_finished(getattr(result, "files_restored", 0),
                                          getattr(result, "verified", 0))
            # Off by default (I1): opening Explorer unasked steals focus from
            # whatever the user moved on to during a long restore.
            if self.settings_tab.open_after_extract.isChecked():
                open_in_explorer(job.out_path)
        else:
            self._notify_done(job)
        self._refresh_actions()

    def _on_job_failed(self, job_id: str, message: str) -> None:
        job = self.queue.job(job_id)
        if job is None:
            return
        self.queue_table.update_state(job)
        self.results.show_job(job)
        if job.kind is JobKind.EXTRACT:
            self.extract_tab.set_failed(message)
        if self._taskbar is not None:
            self._taskbar.set_state(TBPF_ERROR)
        self._refresh_actions()

    def _on_queue_idle(self) -> None:
        if self._taskbar is not None:
            self._taskbar.clear()
        self._refresh_actions()

    def _on_paused_changed(self, paused: bool) -> None:
        self.pause_button.setText(
            self.tr("Resume queue") if paused else self.tr("Pause queue"))
        if self._taskbar is not None and paused:
            self._taskbar.set_state(TBPF_PAUSED)
        self._refresh_actions()

    # -- chrome ------------------------------------------------------------
    def _ensure_taskbar(self) -> None:
        if self._taskbar is None and self.windowHandle() is not None:
            self._taskbar = TaskbarProgress(int(self.winId()))

    def _notify_done(self, job: Job) -> None:
        if not self.settings_tab.notify_toggle.isChecked():
            return
        title = self.tr("Compression finished")
        body = self.tr("%s: saved %s (%d%%)") % (
            job.display_name, fmt_size(job.saved_bytes),
            round(job.saved_fraction * 100))
        if not self._notifier.notify(title, body, job.out_path):
            # No Windows notification stack available - fall back to the tray
            # balloon rather than dropping the message on the floor.
            self._ensure_tray()
            if self._tray is not None:
                self._tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information)

    def _ensure_tray(self) -> None:
        if self._tray is not None or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        if icon.isNull():
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            icon = QIcon(pixmap)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(self.tr("ExtremeCompressor"))
        self._tray.activated.connect(lambda _reason: self.showNormal())
        self._tray.show()

    def _refresh_actions(self) -> None:
        name_ok = self._output_name_ok()
        self._name_error.setVisible(not name_ok)
        self.compress_button.setEnabled(bool(self._pending) and name_ok)
        count = len(self._pending)
        self.compress_button.setText(
            self.tr("Compress") if not count else
            self.tr("Compress 1 item") if count == 1 else
            self.tr("Compress %d items") % count)
        self.clear_button.setEnabled(bool(self._pending))

        # The destination is shown BEFORE the user commits, " (2)" rename and
        # all. The label carries the resolved truth; the edit field holds only
        # what the user typed (writing the resolved name back would feed
        # unique_path its own output and grow " (2) (2)..." on every refresh).
        if self._pending and name_ok:
            resolved = self._output_path_for(self._pending)
            self._dest_label.setText("→  " + str(resolved))
            self._dest_label.setToolTip(str(resolved))
            first = self._pending[0]
            self.name_edit.setPlaceholderText(first.stem or first.name)
        elif not self._pending:
            self._dest_label.setText(self.tr("add files to choose a destination"))
            self.name_edit.setPlaceholderText(self.tr("archive name"))

        self._refresh_measure_button()
        pending = self.queue.pending_count()
        status = self._job_status_text()
        self.queue_status.setText(status)
        self.job_status.setText(status)
        self.job_status.setAccessibleName(
            self.tr("Queue: %s. Opens the Activity tab.") % status)

        active = self._active_job()
        self.status_progress.setVisible(active is not None)
        if active is not None:
            self.status_progress.setValue(int(active.percent))
            self.status_progress.setAccessibleDescription(
                self.tr("%d percent") % int(active.percent))

        # The tab title is the second half of "the queue is never hidden":
        # promoting it off the Compress page only works if leaving that page
        # still tells you how much is waiting.
        self.tabs.setTabText(self._activity_index,
                             self.tr("Activity") if not pending
                             else self.tr("Activity (%d)") % pending)

        self.pause_button.setEnabled(pending > 0 or self.queue.is_paused)
        self.clear_done_button.setEnabled(
            any(j.state.is_terminal for j in self.queue.jobs))
        repolish(self.compress_button)
        self._elide_tools()

    def _active_job(self) -> Job | None:
        return next((j for j in self.queue.jobs if j.state is JobState.RUNNING), None)

    def _job_status_text(self) -> str:
        """One line for the strip, the Activity header and the tab tooltip.

        A finished job has to leave a trace here: with the results panel on
        another tab, this sentence is the only thing that changes on screen
        when a job completes while the user is elsewhere.
        """
        active = self._active_job()
        if active is not None and active.stage == VERIFYING_LATE:
            return self.tr("%s · verifying, past estimate") % active.display_name
        if active is not None and active.stage == PACKING:
            return (self.tr("%s · repacking media") % active.display_name
                    if active.eta_s is None else
                    self.tr("%s · repacking media · %s left") % (
                        active.display_name, fmt_eta(active.eta_s)))
        if active is not None and active.stage == FINISHING:
            return self.tr("%s · finishing") % active.display_name
        if active is not None and active.stage == VERIFYING:
            # No estimate (a job with no analysis) is still a self-test; it
            # must not read as "estimating…", which promises a number.
            return (self.tr("%s · verifying") % active.display_name
                    if active.eta_s is None else
                    self.tr("%s · verifying · %s left") % (active.display_name,
                                                           fmt_eta(active.eta_s)))
        if active is not None:
            return (self.tr("%s · estimating…") % active.display_name
                    if active.eta_s is None else
                    self.tr("%s · %s left") % (active.display_name,
                                               fmt_eta(active.eta_s)))
        pending = self.queue.pending_count()
        if pending:
            return (self.tr("1 job waiting") if pending == 1
                    else self.tr("%d jobs waiting") % pending)

        last = next((j for j in reversed(self.queue.jobs) if j.state.is_terminal), None)
        if last is None:
            return self.tr("idle")
        if last.state is JobState.DONE:
            if last.kind is JobKind.COMPRESS and last.orig_bytes:
                return self.tr("%s · done, saved %d%%") % (
                    last.display_name, round(last.saved_fraction * 100))
            return self.tr("%s · done") % last.display_name
        return self.tr("%s · %s") % (last.display_name, last.state.label.lower())

    # -- lifecycle ---------------------------------------------------------
    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # setWindowTitle() fires this from inside __init__, before _build_ui.
        panel = getattr(self, "settings_tab", None)
        if (panel is not None and panel.tray_toggle.isChecked()
                and event.type() == event.Type.WindowStateChange
                and self.isMinimized() and self.queue.is_busy):
            self._ensure_tray()
            if self._tray is not None:
                self.hide()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if hasattr(self, "_tools_label"):
            self._elide_tools()

    def _confirm_close(self) -> None:
        self._force_close = True
        self.banner.hide_banner()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        # W2-9: this was the last QMessageBox in the package. A modal here is
        # exactly backwards - it covers the queue that proves the job is
        # still alive, at the one moment the user is asking about it.
        if self.queue.is_busy and not self._force_close:
            self.banner.show_message(
                self.tr("A job is still running. Closing will cancel it — your "
                        "originals are untouched and no partial archive is left "
                        "behind."),
                tone="warn",
                actions=[(self.tr("Close anyway"), self._confirm_close),
                         (self.tr("Keep it running"), self.banner.hide_banner)],
                closable=False)
            event.ignore()
            return
        self.settings_tab.save()
        QSettings().setValue("window/geometry", self.saveGeometry())
        self.queue.shutdown()
        if self._taskbar is not None:
            self._taskbar.clear()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
