# 07 — GUI / UX design blueprint (verified July 2026)

> Goal: the friendliest "extreme" compressor ever shipped. Lessons mined from
> HandBrake, 7-Zip/WinRAR, PeaZip, NanaZip, CompactGUI 3/4, Curtail, TinyPNG,
> WinDirStat — copy what works, fix what users complain about.

## What prior art teaches

| App | Copy this | Avoid this |
|---|---|---|
| HandBrake | presets + queue concept | **hidden queue window** (its #1 complaint), multi-file drop bugs |
| 7-Zip / WinRAR | power & reliability | dialog clutter, 1990s IA, jargon-first options |
| NanaZip | Fluent/Mica modern looks | — |
| CompactGUI 3/4 | **pre-scan size estimate before committing**, live ratio/ETA stats | — |
| Curtail | one simple lossless/lossy toggle | — |
| TinyPNG | drag-drop → instant % saved feedback | — |
| WinDirStat | treemap for "what's big?" | slow scans without progress |

## The single-window flow (no modal sub-windows)

```
┌────────────────────────────────────────────────────────────┐
│  ⬇ Drop files or folders here                              │
│         (dashed border, highlights on dragEnter)           │
├────────────────────────────────────────────────────────────┤
│  📊 Analysis card (appears after drop, worker thread)      │
│  "3.2 GB: 82% video, 12% game data, 6% text.               │
│   Lossless gain on the video part: ~0%.                    │
│   💡 Enable Shrink mode? (AV1 — slow on this CPU)"         │
├────────────────────────────────────────────────────────────┤
│  [⚡ Fast]  [⚖ Normal]  [🔥 Extreme]  [🌙 Insane]           │
│   preset CARDS with 1-line honest expectations each        │
│   ▸ Advanced (threads, temp dir, per-type overrides)       │
├────────────────────────────────────────────────────────────┤
│  Queue (ALWAYS visible — fixes HandBrake's #1 complaint)   │
│  name         profile  size→size   %    ETA    [⏸][✖]     │
│  ▸ per-job log expander                                    │
├────────────────────────────────────────────────────────────┤
│  ✅ Results: "You saved 11.8 GB (72%)"  [big number]        │
│  per-type before/after bars                                │
│  ⓘ "movie.mp4 didn't shrink: MP4 is already compressed;    │
│     lossless tools can't shrink it." (one sentence, always) │
└────────────────────────────────────────────────────────────┘
```

The **"why didn't X shrink" explainer is our differentiator** — no other
compressor tells the truth in plain language. `Route.reason` already provides
the copy.

## Implementation decisions (PySide6)

- **Theme**: hand-rolled QSS token theme (dark default + light), because
  PySide6-Fluent-Widgets is **GPLv3** — incompatible with our MIT repo.
  `pyqtdarktheme`/`qt-material` acceptable fallbacks (MIT).
- **Engine wiring**: a `QueueManager(QObject)` owns jobs; engine calls run in
  `QThreadPool` workers; stages already emit `progress_cb(stage, pct)` → wrap
  into Qt signals `jobProgress(id, stage, pct, eta)`. One active job at a time
  (2-core machine); pause = finish-current-stage-then-hold; cancel sets
  `StageContext.cancel` (already kills the subprocess).
- **ETA**: rolling throughput per stage; show "~" and round aggressively —
  honest ranges beat fake precision.
- **Windows polish**: taskbar progress via `ITaskbarList3` (comtypes — Qt6
  removed QWinTaskbarButton); completion toast via `Windows-Toasts` with an
  "Open folder" action; optional minimize-to-tray while a queue runs.
- **Drag-drop**: accept files AND folders, multiple at once, append to queue.
- **High-DPI**: Qt6 handles scaling; test at 125%/150%.

## Accessibility & i18n (day one, near-zero cost)

- Every user string wrapped in `self.tr()` from the first commit (enables
  translations later — e.g. Sinhala/Tamil like your other projects).
- `setAccessibleName` on all icon-only buttons; full keyboard tab order;
  never encode meaning in color alone (the per-type bars get labels).
- One NVDA screen-reader pass before each release.

## README/marketing shots (matching your repo style)

- Hero: dark-theme **results screen** with a dramatic saved-% number, ~800 px
  wide @2x, visible in the first screenful of the README.
- A <10-second, <5 MB GIF: drop → suggestion → compress → results.
- Script the screenshot so it can be regenerated every release.

## Sources (highlights)

- HandBrake issue tracker (#1087 hidden queue, #1584/#2443 drop bugs)
- github.com/IridiumIO/CompactGUI · apps.gnome.org/Curtail · tinypng.com
- pyqt-fluent-widgets license docs (GPLv3) · pypi: pyqtdarktheme, qt-material
- pythonguis.com QProcess/QThreadPool patterns · Windows-Toasts on PyPI
- Qt6 accessibility + Qt Linguist docs · NN/g progressive disclosure
