# 11 — UI v2 plan (verified 2026-07-31)

> Doc 07 was the v1 blueprint; Phase A shipped it. This is the v2 plan, grounded in
> the shipped code (`gui/mainwindow.py`, `gui/widgets/`, `gui/queue_manager.py`,
> `gui/winintegration.py`, `excmp/manifest.py`) and a fresh competitive scan.
> Constraint carried forward: dark QSS token theme, single window, no modal dialogs,
> Widgets not QML, lossless-first untouched.

## What the GUI is today (read from code, not memory)

- **Single window, two tabs** (Compress / Extract), one vertical flow: `DropZone` →
  `AnalysisCard` → 4 `PresetCard`s with honesty notes → `AdvancedPanel` (threads,
  temp dir, output dir, tray/notify toggles) → always-visible `QueueTable` (7
  columns, per-job log expander, per-row cancel) → `ResultsPanel` (hero number,
  before/after bar, per-type stacked bars, "why didn't X shrink" lines).
- **Theme**: hand-rolled QSS token theme (`theme.py`, dark + light, `repolish()`).
  **Nothing is persisted** — there is no `QSettings` anywhere in the repo. Theme
  resets to dark, advanced options reset, every launch.
- **i18n**: every string is already in `self.tr()` and `gui/app.py` has a working
  `QTranslator` loader for `gui/translations/excmp_<locale>.qm` — but **no `.ts`/`.qm`
  files exist and no lupdate pipeline is set up**. Strings are set at construction,
  so live language switching would need a restart.
- **Queue**: strict FIFO, one job at a time (pool max=1), pause = finish-stage-then-hold,
  cancel kills the child. **No reorder, no priority, no persistence** —
  `clear_finished()` deletes jobs forever; closing the app loses all history.
- **Extract tab**: whole-archive restore only. No way to see what is inside an
  `.excmp` without extracting everything.
- **`.excmp` container**: a STORED zip = `manifest.json` + one solid payload blob +
  individually-readable `stored/<relpath>` entries. The manifest carries the full
  `inputs` ledger (relpath → SHA-256) and per-file `routes` — so **listing contents
  is a free manifest read**, extracting a single *stored* file is a free zip read,
  but extracting a single *pipelined* file requires replaying the whole chain.
- **Windows integration**: taskbar progress (comtypes `ITaskbarList3`), toasts, tray,
  and `SetCurrentProcessExplicitAppUserModelID` already called (the prerequisite a
  jump list needs). No shell/context-menu integration, no jump list, no `.excmp`
  file association.
- **Design-rule violation to fix**: `closeEvent` uses a modal `QMessageBox.question`
  — the one place the app breaks its own "no modal dialogs" rule. Swap for an inline
  confirm banner (S).

## Competitive scan — what we lack (verified July 2026)

**7-Zip File Manager**: double-click into any archive and browse it like a folder,
extract only selected files, drag files *out* into Explorer (extract-to-temp at drag
time), built-in benchmark. The archive-as-browsable-folder model is the single
biggest thing our Extract tab lacks.

**PeaZip 11.2.0** (2026-07-12): the standout new idea is the **F12 function picker —
a command palette for an archiver** (type to search every function, apply to
selection). Also: drag-drop with an explicit action menu, password manager,
**two-factor archives** (password + keyfile), saved compression profiles, sequential
task queue. Its UI is famously dense — our single-flow layout is the deliberate
opposite. **Adopt features, not layout.**

**NanaZip**: Windows 11 Fluent (Mica title bar, rounded corners, system theme
following) and the reference implementation of the **Win11 cascade context menu**
(`IExplorerCommand` + sparse MSIX). Being MIT, its context-menu code is legally
readable for our own implementation.

**WinRAR 7.x**: named **compression profiles** (save/restore full option sets —
"email attachment", "backup"), recovery record (engine feature, see doc 10), and a
Q&A Wizard mode for novices. Profiles map cleanly onto our Advanced panel.

**Keka (macOS)**: compress-with-defaults by dropping on the Dock icon; advanced
overrides apply only to that drop and never silently overwrite defaults. Windows
taskbar buttons can't accept action-drops, so the transferable ideas are "remembered
defaults + per-job override that doesn't stick" and shell-level entry points.

**PySide6 stance checks (all verified):**
- **Widgets vs QML**: stay on Widgets. Dense, keyboard-and-screen-reader desktop
  utility with an established QSS token theme and 52 pytest-qt tests; QML buys
  animation, not function.
- **Fluent look**: PySide6-Fluent-Widgets is still dual GPLv3 + paid commercial —
  incompatible with MIT, as decided in A1. Instead get the modern feel free:
  Qt ≥ 6.5 `QStyleHints.colorScheme()` gives OS dark/light detection, zero new deps.
- **Qt Linguist workflow** (the only missing i18n piece): `pyside6-lupdate gui/*.py
  gui/widgets/*.py -ts gui/translations/excmp_<locale>.ts` → translate → 
  `pyside6-lrelease` → `.qm`. The runtime loader already exists; both CLI tools ship
  inside the PySide6 wheel we already depend on.
- **Jump list**: `QWinJumpList` was removed in Qt 6 with no replacement (QTBUG-94007)
  → raw COM `ICustomDestinationList` via comtypes, the exact pattern
  `winintegration.py` already uses for `ITaskbarList3`.
- **Win11 context menu**: top-level entries need a signed sparse MSIX +
  `IExplorerCommand`. Classic HKCU registry verbs still work on Windows 10 (the
  actual dev/user machine, 10.0.19045) and appear under Win11's "Show more options".
  **Registry now; MSIX only after E3/E4 produce a signed installer.**
- **Treemap**: `squarify` on PyPI is a tiny pure-Python squarified-treemap layout,
  **Apache-2.0** (MIT-compatible) — compute rects with it, paint them in a custom
  QWidget using the existing `CATEGORY_COLORS`. The analyzer already returns per-file
  sizes, so **no engine change**.

## The v2 plan, prioritized

### Tier 1 — must-have: fix the trust and retention gaps

1. **Settings page + persistence** (effort M). The app currently forgets everything
   between launches. `QSettings`-backed Settings tab: theme (+ optional follow-system
   via `QStyleHints.colorScheme()`), language, default output dir, default temp dir,
   **tool-path overrides** for 7z/precomp/zpaqfranz/xtool **[SOURCE-STUDY ⚠ srep
   removed from the list — dropped from all plans, doc 21 §5]**, notification/tray defaults,
   remembered last preset. Engine change: one additive parameter so `find_tools()`
   accepts user override paths. *Why must-have: tool-path overrides unblock every
   user whose tools aren't in `C:\Program Files`.*
2. **Archive browser** (effort M; listing alone is S). Open an `.excmp` and see the
   ledger: tree of contents from `manifest.json` (free read) with per-file size,
   SHA-256, and route (compressed vs stored-as-is *with its reason*). Selective
   extract: `stored/` entries restore instantly; payload members get an honest
   "this archive is solid — restoring one file replays the whole chain" warning
   before a full temp unpack + copy. Engine: additive `list_archive()` (S) +
   `extract_selected()` (M). *This is also a trust feature — it makes the SHA-256
   manifest visible.*

### Tier 2 — should-have: parity and differentiation

3. **Queue upgrades** (effort M, no engine changes). Up/Down reorder buttons (simpler
   and more accessible than drag on a QTreeWidget carrying item-widgets) + "Run next"
   priority + a **persisted History tab** (JSON in appdata: date, inputs, profile,
   sizes, saved %, duration, with "Compress again"). `QueueManager` already owns an
   `_order` list — add `move_job()`/`promote()`.
4. **First-run onboarding card** (effort S). Dismissable inline banner gated by a
   QSettings flag: which tools were found, what each missing tool unlocks ("Install
   Precomp to enable the Extreme chain"), links to official downloads. Upgrades to
   one-click install when the E1 downloader lands — **don't block on it**.
5. **Explorer context menu, Windows 10 path** (effort S-M). Opt-in Settings toggle
   writing HKCU `*/shell` + `Directory/shell` verbs (no admin) launching
   `pythonw -m gui "%1"`; needs small argv intake in `gui/app.py` that pre-fills the
   drop zone. Win11 top-level cascade deferred to post-E4.
6. **"Compare presets on this input" sample benchmark** (effort M-L). Button on the
   analysis card: pick a ≤100 MB planner-aware sample, run installed profiles on it
   as ordinary queue jobs (Fast/Normal by default; Extreme opt-in — a full-chain
   sample still takes minutes on 2 cores), then print **measured** ratio and
   projected time onto each preset card. `tools/bench.py` already has the harness.
   *Extends the honesty brand from estimate to measurement.*
7. **i18n pipeline rollout** (effort S for the pipeline). Commit the lupdate/lrelease
   workflow (`tools/i18n.py`), generate the first `.ts`, add a Language combo in
   Settings with a "takes effect after restart" note (no retranslate plumbing exists
   and it isn't worth building). Unlocks Dhivehi/Sinhala/Tamil locales.
8. **Input treemap "What's inside?"** (effort M). Expander on the analysis card
   rendering a squarified treemap colored by category, with tooltips **and an
   adjacent labeled legend** so color is never the sole carrier (the A10 rule).
   Data already exists in `FileInfo`. Great README material.

### Tier 3 — nice-to-have

9. **Command palette (Ctrl+K)** (effort M) — frameless non-modal popup with fuzzy
   filter over registered actions. PeaZip 11.2's F12 picker validated the pattern for
   archivers. Write our own; never copy PeaZip (LGPLv3) code.
10. **Drag-out extract** (effort M, rides on item 2) — QDrag needs real files, so
    extract-to-temp at drag start (7-Zip's own trick). **Restrict to `stored/`
    entries** — dragging a solid-payload member would silently trigger a full chain
    replay on a 2-core CPU.
11. **Jump list** (effort M, ~150 lines COM) — recent archives + "Pause queue" via
    `ICustomDestinationList` in `winintegration.py`; degrade to no-op like the rest
    of that module. Most valuable after file association + installer exist.

### Skip (with reasons, so the decision stays made)

- **QML migration / Fluent-Widgets** — no functional gain; GPLv3 conflict unchanged.
  Use `QStyleHints.colorScheme()` for the modern feel instead.
- **Password manager UI** — blocked on engine encryption (doc 10 designs it as
  Phase F); a stored-password vault is a liability we shouldn't own.
- **Recovery record UI** — engine/container feature first (doc 10), then a checkbox.
- **Keka dock-drop analog** — impossible on Windows; the context menu covers the
  same "no-window fast path" need.
- **PeaZip-style two-pane file manager** — deliberately rejected; the single-flow
  layout is the product's identity (doc 07).

All Tier 1–2 items respect the existing constraints: new widgets consume
`tokens()`/`CATEGORY_COLORS`, browser and settings are **tabs**, onboarding is an
inline card, the palette is a popup not a dialog.

## Sources (highlights)

- ntcompatible.com PeaZip 11.2.0 release notes · peazip.github.io/peazip-help
- nanazip.org · neowin/windowsforum NanaZip 3.0/6 preview coverage
- techshelps.github.io/WinRAR (profiles) · keka.io + Keka wiki
- doc.qt.io: pyside-lupdate, pyside-lrelease, translations tutorial, extras-changes-qt6
- learn.microsoft.com/windows/msix legacy context menus · pypi.org/project/squarify
- github.com/zhiyiYo/PyQt-Fluent-Widgets (license) · github.com/5yutan5/PyQtDarkTheme
