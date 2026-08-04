"""The single window.

One vertical flow, no modal sub-windows: drop → analysis → presets → queue →
results, with Extract on its own tab. Everything the user needs to judge the
job is on screen at the same time, which is the whole point.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import (QAction, QCloseEvent, QIcon, QKeySequence, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox,
                               QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QSystemTrayIcon, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from excmp import __version__
from excmp.analyzer import FileInfo
from excmp.planner import Profile, plan as make_plan
from excmp.safepath import UnsafePathError, safe_relpath
from excmp.tools import find_tools

from .format import fmt_eta, fmt_size
from .models import Job, JobKind, JobState
from .queue_manager import AnalysisSignals, AnalysisWorker, QueueManager
from .suggest import (AnalysisSummary, profile_comparison, recommend_profile,
                      strongest_profile, summarize)
from .theme import GAP_BLOCK, GAP_INTRA, GUTTER, VGAP, qss, repolish
from .widgets.analysis_card import AnalysisCard
from .widgets.compare_table import CompareTable
from .widgets.dropzone import DropZone
from .widgets.extract_tab import ExtractTab
from .widgets.preset_cards import AdvancedPanel, AdvancedToggle
from .widgets.queue_table import QueueTable
from .widgets.results import ResultsPanel
from .winintegration import (TBPF_ERROR, TBPF_PAUSED, Notifier, TaskbarProgress,
                             open_in_explorer)

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

    def __init__(self, theme: str = "dark") -> None:
        super().__init__()
        self.theme_name = theme
        self.setWindowTitle(self.tr("ExtremeCompressor"))
        self._restore_geometry()

        self.tools = find_tools(with_versions=True)
        self.queue = QueueManager(DEFAULT_TEMP, self.tools, self)

        self._pending: list[Path] = []
        self._infos: list[FileInfo] = []
        self._summary: AnalysisSummary | None = None
        self._analysis_pool = QThreadPool(self)
        self._analysis_signals = AnalysisSignals(self)
        self._analysis_signals.ready.connect(self._on_analysis_ready)
        self._analysis_signals.failed.connect(self._on_analysis_failed)

        self._taskbar: TaskbarProgress | None = None
        self._notifier = Notifier()
        self._tray: QSystemTrayIcon | None = None

        self._build_ui()
        self._wire()
        self._apply_theme()
        self._refresh_actions()

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

        queue_header = QHBoxLayout()
        queue_title = QLabel(self.tr("Queue"), page)
        queue_title.setObjectName("Title")
        self.queue_status = QLabel("", page)
        self.queue_status.setObjectName("Muted")
        self.pause_button = QPushButton(self.tr("Pause queue"), page)
        self.pause_button.setToolTip(self.tr(
            "The running job finishes its current stage before holding — "
            "no work is thrown away."))
        self.pause_button.setAccessibleDescription(self.pause_button.toolTip())
        self.clear_done_button = QPushButton(self.tr("Clear finished"), page)
        queue_header.addWidget(queue_title)
        queue_header.addWidget(self.queue_status)
        queue_header.addStretch(1)
        queue_header.addWidget(self.clear_done_button)
        queue_header.addWidget(self.pause_button)
        column.addLayout(queue_header)

        self.queue_table = QueueTable(page)
        column.addWidget(self.queue_table)

        self.results = ResultsPanel(self.theme_name, page)
        column.addWidget(self.results)
        column.addStretch(1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(page)
        self.tabs.addTab(self._scroll, self.tr("Compress"))

        self.extract_tab = ExtractTab(self)
        self.tabs.addTab(self.extract_tab, self.tr("Extract"))

        # The window shell (W1-2): the action bar carrying the commit button
        # and the resolved destination NEVER scrolls - it sits between the tab
        # pages and the status bar. The Advanced panel expands upward from it,
        # outside the scrolling page, so opening it displaces no content.
        # (Not a Qt.Popup: its Browse buttons open QFileDialogs, which would
        # dismiss a popup, returning the user to a vanished panel.)
        self.advanced_panel = AdvancedPanel(DEFAULT_TEMP, self)
        self._build_action_bar()
        central = QWidget(self)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.tabs, 1)
        shell.addWidget(self.advanced_panel)
        shell.addWidget(self.action_bar)
        self.setCentralWidget(central)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._build_status_bar()
        self._build_actions()
        self._set_tab_order()

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
            box.setContentsMargins(16, 12, 16, 12)
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
            tools = ", ".join(
                f"{name} {info.version}".strip() if info else f"{name} (not found)"
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
        suffix = QLabel(".excmp", self.action_bar)
        suffix.setObjectName("Muted")
        self._name_error = QLabel(self.tr("invalid name"), self.action_bar)
        self._name_error.setProperty("tone", "danger")
        self._name_error.setVisible(False)

        self.advanced_toggle = AdvancedToggle(self.advanced_panel, self.action_bar)
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
        bar = self.statusBar()
        found = [name for name, info in self.tools.items() if info is not None]
        missing = [name for name in ("7z", "precomp") if self.tools.get(name) is None]
        text = self.tr("Tools found: %s") % (", ".join(found) or self.tr("none"))
        if missing:
            text += self.tr("  ·  missing: %s") % ", ".join(missing)
        self._tools_label = QLabel(text, self)
        self._tools_label.setObjectName("Muted")
        bar.addWidget(self._tools_label)

        self.theme_button = QPushButton(self.tr("Light mode"), self)
        self.theme_button.setFlat(True)
        self.theme_button.setAccessibleName(self.tr("Toggle light and dark theme"))
        self.theme_button.clicked.connect(self.toggle_theme)
        bar.addPermanentWidget(QLabel(f"v{__version__}", self))
        bar.addPermanentWidget(self.theme_button)

    def _set_tab_order(self) -> None:
        """Explicit keyboard path through the flow, top to bottom."""
        cards = self.presets.cards
        chain: list[QWidget] = [
            self.drop_zone.files_button, self.drop_zone.folder_button,
            *[cards[p] for p in
              (Profile.FAST, Profile.NORMAL, Profile.EXTREME, Profile.INSANE)
              if p in cards],
            self.advanced_toggle, self.clear_button, self.compress_button,
            self.clear_done_button, self.pause_button, self.queue_table,
        ]
        for first, second in zip(chain, chain[1:]):
            self.setTabOrder(first, second)

    def _wire(self) -> None:
        self.drop_zone.pathsAdded.connect(self.add_paths)
        self.presets.profileChanged.connect(self._on_profile_changed)
        self.compress_button.clicked.connect(self.start_compression)
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

        QShortcut(QKeySequence.StandardKey.Open, self, self.drop_zone._pick_files)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.start_compression)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss(self.theme_name))
        self.theme_button.setText(
            self.tr("Dark mode") if self.theme_name == "light" else self.tr("Light mode"))

    def toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
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
        self._refresh_actions()
        worker = AnalysisWorker(list(self._pending), self.presets.current_profile(),
                                self.tools, self._analysis_signals)
        self._analysis_pool.start(worker)

    def clear_pending(self) -> None:
        self._pending.clear()
        self._infos = []
        self._summary = None
        self.analysis_card.clear()
        self.compare_table.clear()
        self.results.hide_panel()
        self._refresh_actions()

    def _reset_flow(self) -> None:
        self.results.hide_panel()
        self.clear_pending()

    def _on_analysis_ready(self, infos: object, summary: object) -> None:
        if not isinstance(summary, AnalysisSummary):
            return
        self._infos = list(infos or [])
        self._summary = summary
        self.analysis_card.set_summary(summary)

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

    def _on_analysis_failed(self, message: str) -> None:
        self.analysis_card.set_error(message)
        self._summary = None
        self.compare_table.clear()
        self._refresh_actions()
        self.analysisFinished.emit()

    def _on_profile_changed(self, profile: object) -> None:
        """Re-plan without re-reading the files - entropy sampling is the
        expensive part and nothing about the input changed."""
        if not self._infos or not isinstance(profile, Profile):
            return
        the_plan = make_plan(self._infos, profile, self.tools)
        reference = make_plan(self._infos, strongest_profile(self.tools), self.tools)
        self._summary = summarize(self._infos, the_plan, self.tools, reference)
        self.analysis_card.set_summary(self._summary)
        self._refresh_estimates()
        self._refresh_actions()

    def _refresh_estimates(self) -> list:
        """Recompute the comparison table. Costs four ``planner.plan()`` calls
        and some arithmetic - no file is re-read."""
        if not self._infos or self._summary is None:
            self.compare_table.clear()
            return []
        rows = profile_comparison(self._infos, self.tools, self._summary)
        self.compare_table.set_rows(rows)
        return rows

    def _choose_profile(self, profile: object) -> None:
        """A click on a table row picks that preset - seeing that Normal is
        2.7x quicker is only useful if switching to it is one click away."""
        if isinstance(profile, Profile):
            self.presets.select(profile, emit=True)

    # -- running -----------------------------------------------------------
    def _output_folder_for(self, inputs: list[Path]) -> Path:
        folder_text = self.advanced_panel.output_dir.text().strip('" ')
        return Path(folder_text) if folder_text else inputs[0].parent

    def _output_path_for(self, inputs: list[Path]) -> Path:
        first = inputs[0]
        stem = self.name_edit.text().strip() if self._output_name_ok() else ""
        stem = stem or first.stem or first.name
        return unique_path(self._output_folder_for(inputs) / f"{stem}.excmp")

    def start_compression(self) -> None:
        if not self._pending:
            return
        inputs = list(self._pending)
        self.queue.temp_dir = Path(self.advanced_panel.temp_dir.text().strip('" ')
                                   or DEFAULT_TEMP)
        self.queue.threads = self.advanced_panel.threads.value()
        self.results.hide_panel()
        self.queue.add_compress(inputs, self._output_path_for(inputs),
                                self.presets.current_profile(), self._summary)
        self._pending = []
        self.analysis_card.clear()
        self.compare_table.clear()
        self._infos = []
        self._summary = None
        self._refresh_actions()

    def _start_extract(self, archive: object, dest: object) -> None:
        self.queue.add_extract(Path(archive), Path(dest))

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
        return (f'python -m excmp compress {quoted} -o "{job.out_path}" '
                f"-p {job.profile.value}")

    def _clear_finished(self) -> None:
        self.queue.clear_finished()
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
        # A finished job used to produce NO visible change: the results panel
        # appeared 660-1090px below every viewport. Bring it into view.
        self._scroll.ensureWidgetVisible(self.results, 0, VGAP)
        if job.kind is JobKind.EXTRACT:
            self.extract_tab.set_finished(getattr(result, "files_restored", 0),
                                          getattr(result, "verified", 0))
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
        if not self.advanced_panel.notify_toggle.isChecked():
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

        pending = self.queue.pending_count()
        active = next((j for j in self.queue.jobs if j.state is JobState.RUNNING), None)
        if active is not None:
            self.queue_status.setText(
                self.tr("%s · estimating…") % active.display_name
                if active.eta_s is None else
                self.tr("%s · %s left") % (active.display_name, fmt_eta(active.eta_s)))
        elif pending:
            self.queue_status.setText(
                self.tr("1 job waiting") if pending == 1
                else self.tr("%d jobs waiting") % pending)
        else:
            self.queue_status.setText(self.tr("idle"))
        self.pause_button.setEnabled(pending > 0 or self.queue.is_paused)
        self.clear_done_button.setEnabled(
            any(j.state.is_terminal for j in self.queue.jobs))
        repolish(self.compress_button)

    # -- lifecycle ---------------------------------------------------------
    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # setWindowTitle() fires this from inside __init__, before _build_ui.
        panel = getattr(self, "advanced_panel", None)
        if (panel is not None and panel.tray_toggle.isChecked()
                and event.type() == event.Type.WindowStateChange
                and self.isMinimized() and self.queue.is_busy):
            self._ensure_tray()
            if self._tray is not None:
                self.hide()
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        if self.queue.is_busy:
            answer = QMessageBox.question(
                self, self.tr("Stop the running job?"),
                self.tr("A job is still running. Closing will cancel it — the "
                        "originals are untouched and no partial archive is left "
                        "behind."),
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Close)
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return
        QSettings().setValue("window/geometry", self.saveGeometry())
        self.queue.shutdown()
        if self._taskbar is not None:
            self._taskbar.clear()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
