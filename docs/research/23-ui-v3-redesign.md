# 23 — UI v3: fit the screen, expose the engine

Status: design pinned, 2026-08-02. Inputs: two measurement passes over the live
GUI (offscreen-rendered, populated state, three DPI configurations), source
studies [07](07-ui-ux-design.md), [11](11-ui-v2-plan.md),
[08](08-archiver-product-features.md), [14](14-source-study-nanazip.md),
[17](17-source-study-peazip.md), [19](19-source-study-7zip.md),
[22](22-feature-parity-master.md), and pattern extraction from 7-Zip, NanaZip,
PeaZip, Ark, File Roller, Xarchiver, and the WinUI design system. Every claim
below carries its file:line or URL. Where a research-pass line number has
drifted against current source, the current line is used and the drift is noted.

The two complaints this answers, verbatim: **"its too big for screen"** and the
app **"looks cheap"**. The first is a measured geometry failure; the second is
the sum of ~20 small defects plus an engine whose real capabilities the UI
hides. Both are fixable without a rewrite.

---

## 1. Diagnosis, in numbers

### 1.1 The screen-fit failure (the loudest complaint)

Target display: 1366×768 physical, 40px taskbar → work area 1366×728, max
client height ≈ 697px after the 31px title bar. Qt6 PassThrough DPI makes that
1092×614 logical at 125% scaling and 910×512 at 150% — and i7-3540M-era
1366×768 panels commonly run 125%.

**Partially fixed already:** the old `self.resize(1080, 900)` (measured in the
research pass at the then-current mainwindow.py:68; that build opened ≥203px
below the work area and swallowed the entire 34px status bar carrying the
"Tools found: … missing: …" honesty line) has been replaced by `initial_size()`
(gui/mainwindow.py:43-55, applied at :83-88), which clamps to
`availableGeometry`. **Still missing:** geometry persistence — zero `QSettings`
hits in the repo — and, decisively, the *content* was never resized to match.

Measured against the real populated MainWindow (analysis summary, 4 compare
rows, 2 queue jobs, results shown):

| Configuration | Viewport (logical px) | Page height | Visible fraction |
|---|---|---|---|
| 100 %, maximized, 1366×697 client | 631 | 1883 | **33.5 %** |
| 125 % | 477 | 1989 | **24 %** |
| 150 % | 365 | 2185 | **16.7 %** |
| + advanced panel open + one expanded log | 631 | 2156 | 29 % |
| at 910px width | 365 | 2458 | 15 % |

The root container choice: one `QVBoxLayout` column inside one `QScrollArea`
(gui/mainwindow.py:111-178) stacking DropZone → AnalysisCard → PresetSelector →
CompareTable → advanced/buttons → queue header → QueueTable → ResultsPanel.
The mainwindow docstring's promise ("everything the user needs to judge the job
is on screen at the same time", mainwindow.py:1-5) is false by a factor of three
on the hardware CLAUDE.md says to calibrate to.

Downstream consequences, all measured:

- **The Compress button lands 428–860px below the fold** the moment analysis
  populates: y=1059 vs 631px viewport at 100% (428px under), y=1165 vs 477 at
  125% (688px), y=1225 vs 365 at 150% (860px). Cause: toggle_row is added after
  CompareTable (gui/mainwindow.py:133-148) and the compare card alone measures
  432–538px.
- **A finished job produces no visible change**: results y=1291/1397/1457 vs
  viewports 631/477/365 — entirely off-screen in every configuration. The only
  scroll call in gui/ is queue_table.py:120 `scrollToItem` (queue rows);
  `ResultsPanel.show_job` (gui/widgets/results.py:103-111) just
  `setVisible(True)` and `MainWindow._on_job_done` (mainwindow.py:398-409) never
  calls `ensureWidgetVisible`.
- **At 125% even the EMPTY launch state overflows** a maximized window: page
  600px vs 477px viewport (queue table shows 17 of its 120px). At 150% the
  Compress button bottom (y=433) is below the 375px viewport **before a single
  file is dropped**.
- **Width fails too**: page `minimumSizeHint().width()` = 939px; at 150%
  (910 logical) the flow grows a 39px horizontal scrollbar. Attribution:
  ResultsPanel 899 (non-wrapped per-category caption labels,
  gui/widgets/results.py:222), AdvancedPanel 774, AnalysisCard 751, DropZone 707.
  Separately, queue columns sum to 990px ([17,107,261,150,133,222,100], progress
  fixed at 150, queue_table.py:72-73), hiding the State column and cancel button
  behind an internal scrollbar below ~1030px of window.

### 1.2 Where the pixels go

| Contributor | Measured height | Evidence |
|---|---|---|
| CompareTable card | 432–538px (68–147 % of viewport) | rows with a note pay two-line cells (compare_table.py:44-68) + full-width warn line (:121-127); ~120px fixed chrome incl. 3-line footnote (:169-196); ProfileRow heights [49, 50, 111, 111]–[49, 50, 141, 111] |
| ResultsPanel | 572–708px (up to 194 % of viewport) | 30pt hero (theme.py:94-99), two 16px bars, 4-row breakdown (results.py:191-230), `_MAX_EXPLANATIONS=6` why-lines + "…and N more" (results.py:30, 232-257), 20/18 margins + 12px spacing (:48-49) |
| DropZone + PresetSelector, empty | 165 + 165 = 330px (52 % of viewport at 100 %, 88 % at 150 %) | both `setMinimumHeight(150)` (dropzone.py:55, preset_cards.py:50); populated PresetSelector grows to 188–218px |
| Fixed chrome + padding | 215px/screen (28 % at 100 %, 42 % at 150 %) | tab bar 33 + status bar 34; margins (20,16,20,20) + spacing 14 × 8 gaps (mainwindow.py:118-119) |
| QueueTable growth cap | 430px = 90 % of the 125 % viewport | `_MAX_TABLE_HEIGHT=430` (queue_table.py:23); height math at :131 assumes 42px/row + 150px/expansion but the log widget alone allows 140px (:114) + 6px item padding (theme.py:221) |
| AdvancedPanel, opened | +199px inserted *between* the Compress button and the queue (mainwindow.py:147-148) | pushes everything below it 213px further down a page that already scrolls 1252px |

And the same 4-way preset decision is rendered **twice** — 4 cards with
blurbs/notes stacked directly above a table whose rows repeat the presets with
better, measured data (mainwindow.py:127-134); compare_table.py:117-119 even
documents fighting the resulting triple "Suggested" assertion
(preset_cards.py:170-179 reason line, :63-66 badge, compare_table.py:84+97 row).

### 1.3 The "looks cheap" defects (non-layout)

- **QSS specificity bug, two variants**: `QLabel#Hero { color: $ok }`
  (theme.py:94-99, ID specificity 101) beats `QLabel[tone="danger"]`
  (theme.py:109-111, specificity 11), so a **failure headline renders in 30pt
  celebratory green** — results.py:157-160 sets a dead property; same for the
  saved==0 warn hero (results.py:122). Identically, `QLabel#Subtitle`
  (theme.py:102) swallows every toned note — the Insane card's "zpaqfranz isn't
  wired up" warning renders ordinary muted grey (preset_cards.py:88-94,
  compare_table.py:121-127).
- **WCAG AA failures in both palettes**: white on accent #4c8dff = 3.2:1 (every
  dark-mode primary button, theme.py:27 + 135-140); light ok #15a06a on white =
  3.35:1 (:48); light warn #a86a00 = 4.4:1 (:49). All at 10pt body size
  (threshold 4.5:1). All four repo screenshots are dark-only — the light
  palette has never been visually reviewed.
- **Invisible keyboard focus where it matters most**: `QPushButton:focus` draws
  a 1px $accent border (theme.py:264-267) but the primary button's *resting*
  border is already $accent (:135-140) — Tab onto "Compress" shows nothing.
  `QToolButton:focus` adds a border where base has none (:147-155), shifting
  content 1px; the tab focus box fights the underline idiom.
- **The cancel "×" renders as an empty pill**: `setFixedWidth(30)`
  (queue_table.py:101) minus QSS padding 7px 14px (theme.py:129) leaves a 0px
  content box; and the danger variant styles only `:hover` (theme.py:145), so
  its danger-ness is invisible until hovered — color-only-on-hover skirts the
  no-colour-only rule.
- **"Time left" column shows elapsed time on finished jobs**: header at
  queue_table.py:56, `fmt_duration(job.elapsed_s)` written into COL_ETA on DONE
  at :157-159 — the honesty-first app mislabels a number. (Research pass cited
  :158-159; verified current at :157-159.)
- **Category palette collides with semantic colors**: TEXT #3ecf8e ==
  the `ok` token, BINARY #4c8dff == `accent` (gui/widgets/bars.py:21-29 vs
  theme.py:27,30) — the 86 % blue breakdown bar reads as a progress bar.
- **Literal emoji as iconography** (⚡⚖️🌊🔥 — preset_cards.py:26-36): fixed-color
  glyphs that ignore both palettes; Win10 flat vs Win11 fluent emoji make the
  app look different per machine; the repo already hit the tofu minefield once
  (dropzone.py:64-66, U+2B07).
- **Ad-hoc spacing and geometry**: six distinct card paddings (16/14, 20/18,
  14/12, 12/10, 16/16, 20/16 — analysis_card.py:31, results.py:48,
  preset_cards.py:54, compare_table.py:88, extract_tab.py:37,
  mainwindow.py:118); the `pad: 12px` token defined but never referenced
  (theme.py:57); six corner radii in play (4, 5, 6, 7, 8, 10 —
  theme.py:56-57, 194, 205-209; bars.py:63 `height//2`, :114); type scale
  9/10/12/13/30pt with a 2.3× cliff to the Hero (theme.py:94-108); the `shadow`
  token defined in both palettes and referenced nowhere (theme.py:33, 51);
  checked preset cards jiggle 1px (border 1px→2px, theme.py:158-169);
  Before/After bar labels aligned with literal runs of spaces (bars.py:148-149);
  cards nested in cards with double borders (compare_table.py:80+162,
  results.py:41-42).
- **Prototype-grade chrome**: no menu bar, no toolbar, no Help/About (grep for
  `menuBar|QToolBar|QAction` in gui/: 0 hits), no right-click menu anywhere
  (grep for `QMenu|contextMenuEvent|customContextMenuRequested|addAction`:
  0 hits — only two QShortcuts, mainwindow.py:239-240), nothing persisted
  (0 QSettings hits; theme hardcoded "dark" at gui/app.py:48,
  mainwindow.py:79), no way to name the output archive
  (`_output_path_for()`, mainwindow.py:339-343; AdvancedPanel offers folder
  only, preset_cards.py:214-219), a permanently disabled "Shrink mode (coming
  later)" checkbox on every analysis (analysis_card.py:65-72), an empty queue
  that is a featureless 120px slab, and a static "Reading 10 items…" sentence
  that will sit unchanged for minutes on the 5.76 GB HDD corpus and read as a
  hang (analysis_card.py:83-92).
- The one already-recorded design-rule violation: closeEvent's modal
  `QMessageBox` (mainwindow.py:506-513, current lines; ROADMAP I9).

---

## 2. Navigation and layout

### 2.1 Decision

**Keep the single window and the no-modal rule. Split the one column into four
top tabs — `Compress | Extract | Activity | Settings` — on the existing,
already-styled QTabWidget, with a persistent one-line job-status strip visible
on every tab, and rebuild the Compress page so its populated height budget is
≤ 300 logical px.**

Rationale, in order:

1. WinUI's own criterion for top navigation — 5 or fewer equally-important
   categories, maximize content space
   (learn.microsoft.com/windows/apps/develop/ui/controls/navigationview, "Top"
   display mode) — fits exactly. Tabs cost ~33px of height once; the widget is
   already shipped and styled (mainwindow.py:112-113, theme.py:241-251).
2. 7-Zip's whole UX proves the ceiling: task-scoped surfaces of ~500-600px each
   run happily on 1366×768 (7-Zip FM + Add dialog,
   https://7zip.bugaco.com/7zip/MANUAL/fm/menu.htm,
   https://documentation.help/7-Zip/add.htm). We adopt the principle — only the
   current step's controls on screen — without adopting modality.
3. Ark and File Roller never show two lifecycle stages at once
   (docs.kde.org/trunk_kf6/en/ark/ark/using-ark.html; GNOME help
   archive-create.page). Applied here: completed flow stages collapse; results
   replace the decision UI they made obsolete instead of appending below it.
4. The queue-always-visible rule (doc 07, HandBrake's #1 complaint; the
   queue_table.py docstring is load-bearing) is preserved by *promoting* the
   status line MainWindow already computes in `_refresh_actions()`
   (mainwindow.py:479-488: "name · 3m 12s left" / "2 jobs waiting" / "idle")
   into the status bar with a mini progress bar, click-through to Activity.
   Text carries the state — no colour-only meaning.

### 2.2 Rejected alternatives (with reasons, so they stay rejected)

- **Status quo single scrolling column** — rejected by measurement (§1.1:
  16.7–33.5 % visible).
- **Left nav rail (Win11 Settings/PowerToys)** — at our 1180px window WinUI's
  auto behavior (ExpandedModeThresholdWidth 1008,
  learn.microsoft.com/uwp/api/windows.ui.xaml.controls.navigationview.*) yields
  an expanded 320px pane eating 27 % of width for four items; a 48px compact
  rail needs a custom QListWidget+QStackedWidget shell, icon assets, and
  keyboard plumbing QTabBar gives free. Revisit only if destinations grow
  past 5.
- **Wizard/stepper** — trivially fits 768px but hides the queue and the honesty
  card behind steps, the exact failure doc 07 was written to avoid; WinRAR's
  Wizard mode is the cautionary precedent (novices use it once, then it is
  dead UI).
- **Two-pane file manager (7-Zip FM F9, PeaZip)** — rejected twice already with
  reasons recorded (doc 08 skip list: "dilutes the drop→analyze→queue identity;
  doubles GUI surface"; doc 11 competitive scan; doc 17). Two panes exist to
  move files between places; this app moves files between *states*
  (original ↔ verified archive). Re-recorded per the CLAUDE.md re-litigation
  rule.
- **Modal progress dialogs** (Ark KJob, File Roller, Xarchiver) — all three are
  single-job apps; we already have the strictly better shape (visible queue,
  per-row bars, log expanders, ITaskbarList3), and any modal recreates the I9
  violation.

### 2.3 Wireframe (maximized, 1366×768 @ 100 %; identical structure at 150 %)

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⣿ ExtremeCompressor                                        ─  □  ×  │ 31px (OS, dark via DWM)
├──────────────────────────────────────────────────────────────────────┤
│  Compress   Extract   Activity (1)   Settings                       │ 33px tab bar
├──────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 3 items · 1.9 GB   [Add files]  [Add folder]  [Clear]      (36) │ │  intake chip; re-expands
│ └──────────────────────────────────────────────────────────────────┘ │  to full drop zone on
│ ┌──────────────────────────────────────────────────────────────────┐ │  drag-enter / when empty
│ │ Should compress well — mostly text and binaries.           (96) │ │
│ │ [██████████ text ███ binary ▓ media ░ archives]  86% / 9% / 5%  │ │  analysis card, compact
│ │ 2 files will be stored as-is (already compressed)  [details ▸]  │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ Pick a preset — estimates for THIS input          ⓘ estimates   │ │
│ │ ( ) ⚡ Fast      zstd        ~820 MB   ~40 s      RAM ~1.2 GB   │ │  ONE chooser table
│ │ (•) ⚖ Normal    7z          ~700 MB   ~62 s      RAM ~2.5 GB   │ │  (radio rows, merged
│ │ ( ) 🔥 Extreme   precomp+7z  ~698 MB   ~166 s ⚠   RAM ~3.4 GB   │ │  presets + compare),
│ │ ( ) 🌙 Insane    zpaq…       —  not installed                   │ │  4×32px + 44px chrome
│ └──────────────────────────────────────────────────────────────────┘ │  = 172px
├──────────────────────────────────────────────────────────────────────┤
│ → D:\stuff\MyGame.excmp [✎]      [Advanced ▾]   [Clear] [Compress ▸] │ 44px FIXED action bar
├──────────────────────────────────────────────────────────────────────┤  (never scrolls)
│ Tools: 7z 24.08, zstd · missing: precomp │ MyGame · 62s left ▂▄▆ │ v │ 30px status strip,
└──────────────────────────────────────────────────────────────────────┘  job text → Activity tab
```

Activity tab: queue header (Pause / Clear finished) + QueueTable at full width
and full height (the 430px cap becomes viewport-relative), with per-job results
folding into the row expander the table already owns (queue_table.py:110-117);
ResultsPanel shows the most recent result above the table until that fold-in
lands. Extract tab: unchanged card + destination split-button. Settings tab:
I1, SettingsCard geometry (§3).

### 2.4 The height budget, and how it holds at 150 %

**(Rewritten after adversarial review — the first draft's arithmetic was
optimistic twice: it derived the 150 % client as 768/1.5−48, under-counting the
DPI-scaled caption and taskbar, and it forgot the menu bar row it was itself
proposing.)**

Client heights, backed out of the *measured* viewports (631/477/365 plus the
67px of tab+status chrome present at measurement time): **698 / 544 / 432**
logical at 100/125/150 %. Fixed chrome in v3: 33 (tabs) + 44 (action bar) + 34
(status strip — its measured height today; 30 only after a restyle proves it)
= 111px → page viewports **587 / 433 / 321**.

No menu-bar row: the W1-9 actions live behind a hamburger `QToolButton`
installed with `QTabWidget.setCornerWidget()` — QActions fire without a visible
QMenuBar, shortcuts and mnemonics survive, and the ~23px row is never spent.
(theme.py has zero `QMenu` rules today, so the menu itself gets styled in the
same item.)

`GUTTER = 24` is **horizontal only**; vertical page margins are pinned at 12.
Populated Compress page budget: intake chip 36 + analysis card 96 + chooser 172
+ 2 gaps × 8 + vertical margins 24 = **344px** against 433 (125 %) — but at
150 % the analysis card must collapse its detail line into the expander
(card ≤ 80px) *and* the chooser gives up its footnote row to the ⓘ disclosure,
bringing the page to **≤ 300px against 321**. That is the enforced budget: the
Wave-1 regression gate (§7, W1-11) asserts ≤300 populated at 150 %, not the
first draft's 344-vs-357 near-miss built from stacked optimism.

The Advanced panel is **not a popover** (a `Qt.Popup` auto-closes when its own
Browse buttons open `QFileDialog` — the user would return to a vanished panel).
It is a collapsible section that expands *upward from the fixed action bar*,
outside the scrolling page: never displaces the queue, no popup focus dance,
keyboard-safe. It ships as part of W1-2, not as an unassigned promise.

The empty state budgets to ~290px only after W1-3 also collapses the empty
queue's 120px minimum slab to a ~60px hint row (the hint W2-7 wanted anyway).

Width: word-wrap the two widest labels (results.py:222 and the widest
analysis-card warning line) to drop the page minimum below 800px; queue columns
merge Profile+Size into a second line under Job and progress shrinks 150→110
(queue_table.py:72-73, :79) — the Activity tab gives the table the full 1180px
anyway.

---

## 3. Design tokens — an evolution of `gui/theme.py`

The token table + `Template` QSS approach stays (theme.py:18-60, 271-283); so
does objectName/dynamic-property styling with `repolish()`. Changes are to the
values, plus exporting layout constants so `setContentsMargins`/`setSpacing`
calls stop inventing numbers.

### 3.1 Type ramp (Windows ramp mapped to QSS pt at 96 dpi; source:
learn.microsoft.com/windows/apps/design/signature-experiences/typography)

| Token / selector | Today | v3 | Windows step | Notes |
|---|---|---|---|---|
| `QLabel#Hero` | 30pt / 700 | **21pt / 600** | title 28px | Bold→Semibold per ramp (Bold deliberately excluded, aligns with the a11y day-one rule); saves ~30px; default color **$text**, tones via explicit rules (§3.4) |
| `QLabel#HeroSub` | 12pt | 12pt | — | unchanged |
| page section (`Queue`, tab-page titles) | 13pt / 600 (shared with card headers) | **15pt / 600**, new `#PageTitle` | subtitle 20px | ends the flat hierarchy |
| `QLabel#Title` (card headers) | 13pt / 600 | **10.5pt / 600** (body-strong) | body-strong 14px | card headers stop competing with sections |
| body (base QWidget) | 10pt | 10pt | body 14px≈10.5pt | close enough; not worth a global reflow |
| `#Subtitle`, `#Muted` | 10pt muted | 10pt muted | body | tone rules added (§3.4) |
| caption / `#Mono` | 9pt | 9pt | caption 12px | at the 12px legibility minimum, keep regular weight |

Delete the inline `font-size: 30pt` at dropzone.py:68 — all sizes come from
named tokens.

### 3.2 Spacing (4px grid; source:
learn.microsoft.com/windows/apps/develop/ui/alignment-margin-padding — "all
dimensions, margins, and padding should be in increments of 4 epx"; 24px
gutters, 12px under 640px width)

Export from theme.py as Python constants and sweep every layout call:

| Constant | Value | Replaces |
|---|---|---|
| `GUTTER` | 24 (12 below 640px width) | page margins (20,16,20,20) at mainwindow.py:118 |
| `GAP_BLOCK` | 12 | `column.setSpacing(14)` at mainwindow.py:119 |
| `GAP_INTRA` | 8 | per-card 10/12/14 spacings |
| `CARD_MARGINS` | (16, 12, 16, 12) | the six coexisting paddings (§1.3) |

The dead `pad` token (theme.py:57) is deleted; these constants replace it.
Net effect on §1.2's 215px of chrome: roughly −60px per screen.

### 3.3 Radii and control geometry (source: Windows geometry —
ControlCornerRadius = 4, OverlayCornerRadius = 8,
learn.microsoft.com/windows/apps/design/signature-experiences/geometry; touch
floor: learn.microsoft.com/windows/apps/develop/input/touch-interactions,
"minimum of 40×40 epx, or 32 epx tall if the width is at least 120 epx")

| Token | Today | v3 |
|---|---|---|
| `radius` (containers: Card, DropZone, PresetCard, QTreeWidget) | 10px | **8px** |
| `radius_sm` (buttons, inputs, checkbox, progress incl. chunk) | 6px (chunk 5, checkbox 4) | **4px** everywhere |
| StackedBar | `height//2` pill (bars.py:63) | keep the pill but standardize bar heights to one value (bars.py:114) |
| control min-height | ~32-34px by accident (theme.py:125-130) | **32px** explicit; icon-only QToolButton **32×32 min** (today ~26px, theme.py:147-155), hit area 36-40px |
| cancel "×" | fixedWidth 30, clipped (§1.3) | `setFixedSize(28,28)` + `padding: 2px` danger rule; danger variant gets a **resting** border/color, not hover-only |
| PresetCard checked | 1px→2px border jiggle (theme.py:158-169) | constant 2px border, only the color changes |
| `shadow` token (theme.py:33, 51) | defined, unused | **deleted** (elevation via layout, not fake shadows) |

### 3.4 Colour roles (both palettes; token names unchanged)

| Role | Dark today → v3 | Light today → v3 | Why |
|---|---|---|---|
| primary button | #4c8dff fill + **white** text (3.2:1, fails AA) → #4c8dff fill + **#0b0d12 text** (≈6.5:1) | #2f6fe0 + white (passes) | Win11 idiom is dark text on accent in dark mode; passes AA without dulling the accent |
| `ok` | #3ecf8e (fine on dark) | #15a06a (3.35:1) → **#0e7a52** | AA at 10pt |
| `warn` | #f5a524 | #a86a00 (4.4:1) → **#8a5700** | AA at 10pt |
| Hero/Subtitle tones | dead (specificity, §1.3) | | add explicit `QLabel#Hero[tone="ok"/"warn"/"danger"]` and `QLabel#Subtitle[tone=…]` rules; smoke test asserts the hero's palette color after `set_property` |
| focus ring | 1px $accent, invisible on primary (§1.3) | | **2px $accent_hi + background shift** for primary; tabs thicken the underline instead of boxing; QToolButton gets a permanent 1px transparent border so focus never reflows |
| category palette (bars.py:21-29) | TEXT==ok, BINARY==accent | | recolor to unclaimed hues — text **#14b8a6** teal, binary **#818cf8** indigo — plus a comment: `CATEGORY_COLORS must not intersect theme tokens` |

Follow-system theme: read `QStyleHints.colorScheme()` at startup, map
Unknown→dark, connect `colorSchemeChanged` → re-apply `qss()`; three-way
System/Light/Dark setting once I1's QSettings exists (Qt 6.5 API + 6.8
`setColorScheme`, both in the shipped PySide6 6.11.1;
qt.io/blog/dark-mode-on-windows-11-with-qt-6.5 — its two caveats don't apply
because every color already comes from the token table). Dark title bar via
`DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE=20)` in
gui/winintegration.py next to the existing raw-COM ITaskbarList3 code,
degrading to no-op; **no Mica under content** (doc 14 §7 — Qt paints opaque;
NanaZip's HDR guard noted). The white title bar over a #12141a window is
currently the most visible seam on the target Win10 19045 machine.

Screenshot coverage: tools/shots.py gains light-mode and
QT_SCALE_FACTOR=1.25/1.5 captures — all four current screenshots are dark-only
at 100 %.

---

## 4. Iconography

**Decision: vendor SVGs from Fluent UI System Icons
(github.com/microsoft/fluentui-system-icons, MIT) — Microsoft's own Fluent
icon language, OSI-clean for SignPath — loaded via QtSvg (already shipped in
pyside6_essentials), tinted by string-substituting the SVG `fill` with the
theme token before QIcon construction, `filled` variant for selected state,
`regular` otherwise.** Fallbacks if a glyph is missing: Lucide (ISC) or Tabler
(MIT) — but one family per surface; mixing sets reads as clutter.

**Emoji stays short-term, is replaced in Wave 2.** The current glyphs
(⚡⚖️🔥🌙, preset_cards.py:26-36) are legally clean and always sit next to text,
so no information is lost — but they are the single biggest "not a native app"
tell: Win10 renders the 2016 flat set vs Win11's Fluent set, three saturated
orange glyphs sit against one dim scales glyph in 00-empty.png, variation
selectors are a minefield the repo already hit (dropzone.py:64-66), and screen
readers speak "high voltage Fast". Preset cards convert first — they are the
marquee screenshot.

**Rejected: Segoe Fluent Icons font.** Two independent disqualifiers: the EULA
permits use "solely to design, develop and test… on a Microsoft Platform" with
no redistribution right (bundling the .ttf breaks the 100 % OSI-clean
requirement the moment it enters the repo), and it is not preinstalled on
Windows 10 19045 — tofu on exactly the target hardware
(github.com/microsoft/fluentui-system-icons/issues/202; Microsoft Learn Segoe
Fluent Icons page).

---

## 5. What becomes visible that the engine can already do

The direct answer to "looks cheap": the engine outclasses the UI. Everything
below is **already implemented and unexposed** (glue only) unless marked.

| Capability | Engine evidence | UI exposure |
|---|---|---|
| **Verify archive on demand** | `_verify_before_publish` does a full restore + per-file SHA-256 (excmp/engine.py:333-360; excmp/verify.py:23-49); `SevenZipStage.test` exists, never called from GUI (excmp/stages/sevenzip.py:57-58); cli.py:105-135 has only analyze/compress/extract | "Verify" button on the Extract tab + `excmp verify` subcommand. Highest credibility-per-line in the inventory — verification IS the brand, yet today it only happens implicitly |
| **Open foreign archives** (zip/7z/rar/tar/iso/cab/msi/wim) | `extract()` already shells `7z x` on any path (sevenzip.py:50-55); `_MAGIC` already fingerprints zip/7z/rar/gzip/zstd/xz (excmp/analyzer.py:46-62) | widen the Extract filter (today `*.excmp` only, extract_tab.py:148) + honest label: no SHA-256 ledger, verification limited to `7z t`. ROADMAP G1 — "the single feature that turns a compressor into an archiver" |
| **List archive contents** | `read_container`/`_read_manifest` is a free zip+JSON read (excmp/manifest.py:147-200); ledger carries relpath → size, SHA-256, route; routes carry store *reasons* | I2 browser tab, flat view first (File Roller's flat list, help/C/archive-view.page) — richer columns than 7-Zip can render (kPropIdToName, doc 19 §6): hash, route, and *why stored*. Foreign archives via the pinned `7z l -slt` grammar + dummy `-p` hang guard (doc 17 §4) come with G2 |
| **Selective extract of stored entries** | `extract_stored` already streams stored/ entries individually (manifest.py:203-268); 81 % of bytes on the real corpus are stored | add a name filter; solid-payload members get the honest "one file replays the whole chain" warning (G2 wording) |
| **Hash tool** | `hash_file` (verify.py:15-20), used everywhere internally | `excmp hash` verb + drop-target panel (G8) |
| **Transport sidecar** | publish is a single atomic `tmp_out.replace` (engine.py:310-314) — hashing the container there is ~10 lines | emit `<archive>.sha256` (G6), the QuickSFV/fitgirl-bins.md5 habit with a modern hash |
| **Standard-format export** | the 7z stage already produces a bare .7z before `write_container` wraps it (sevenzip.py:36-48; engine.py:291-308) | "plain .7z/.zip (compatible)" checkbox (G4), labelled: loses the ledger and verified-restore guarantee |
| **Level / dictionary knobs** | `SevenZipStage(level=9, dict_size=None)` with `-md=` plumbing (sevenzip.py:22-44); `ZstdStage(level=19, long_log=27)` (zstdstage.py:23-36) — but `_stage_factory()` hard-codes defaults (engine.py:169-182) and `StageRecord.params` is always `{}` (:281-286) | Advanced rows with B9's RAM-capped bounds (never past `-md=512m` on 16 GB/2-core), always `-mqs`; threads proves the pattern end-to-end already (preset_cards.py:196 → ctx.threads → `-mmt`, sevenzip.py:39-40). *Needs plumbing, not new engine features* |
| **Peak-RAM per preset** | exact per-block estimator pinned from 7-Zip source: ≈13×dict per block thread at mx9, decode = dict + 2 MiB (doc 19 §3 + ADOPT 7, CompressDialog.cpp:2942-3017) | a RAM column in the chooser table — nobody else surfaces this before the job starts except 7-Zip's dialog; critical on the 16 GB target |
| **Copy as command** | the full CLI already exists: `python -m excmp {analyze\|compress\|extract} -p … --temp … --json` (cli.py:105-135) | "Copy as command" on the queue row context menu — pure string formatting, the cheapest "this tool is powerful" signal for scripters |
| **Per-file routing with reasons** | `planner.store_reason` + per-file routing (excmp/planner.py:90-144); `store_files` already carries (name, size, why) to the card, which shows only totals (analysis_card.py:102-124) | expandable per-file routing table — the automation reads as power instead of a black box; out-does WinRAR's manual store masks; feeds I8's treemap later |
| **Destination before commit** | `_output_path_for()` computes silently (mainwindow.py:339-343) | the action bar shows "→ D:\stuff\name.excmp" with an editable name chip (validated against excmp.safepath) — 7-Zip puts the Archive field first for a reason (documentation.help/7-Zip/add.htm); also surfaces `unique_path()`'s " (2)" rename before it surprises anyone |
| **Extra 7z flags escape hatch** | subprocess arg lists, no shell-injection surface | one free-text "Parameters" line (7-Zip's pattern), token-allowlisted, never echoing password-bearing args into logs (PeaZip's redaction rule, doc 17 §4) |
| Small engine additions (honest about the work) | mtime restore for stored entries (manifest.py:253-267 writes with no `utime` — the two routes currently disagree, piped files ride tar PAX); optional manifest `comment` field (Manifest at manifest.py:45-78; `from_json`'s `cls(**data)` makes unknown keys a hard error, so this is a versioned-schema change); include/exclude globs on `_collect`/`analyze_tree` (engine.py:207-219, analyzer.py:200-205) with excluded files shown in the analysis card | S/M each; listed so they are not mistaken for free glue |

Also folded into the layout work because they are honesty features, not
decoration: the archive-dominant inline chip ("This is an archive — extract
it, or Convert & shrink instead?") when the analyzer already knows
(add_paths does no type routing, mainwindow.py:254-268; DropZone deliberately
accepts everything, dropzone.py:1-8), and the "Shrink mode" dead checkbox
folded into the hint line as text (analysis_card.py:56-60, 65-72).

---

## 6. Context menus

In-app `QMenu`s are cheap (reuse existing slots; grep shows zero today, §1.3)
and completely separate from Explorer shell integration (ROADMAP I5, which
needs the CLI contract now and a signed sparse MSIX post-E4 — doc 14 §2, thin
launcher, never extract in Explorer's process, plus the
AllowSetForegroundWindow dance NanaZip had to ship as a fix). The in-app menus
are Wave 1; I5 is Wave 4.

| Surface | Menu items (all existing slots or trivial) |
|---|---|
| QueueTable row | Cancel · Retry failed job · Open output folder (`winintegration.open_in_explorer`) · Copy output path · Copy as command · Show log · Remove row. Closes the per-row gaps: today only the LAST job's output is reachable, via ResultsPanel (results.py:90) |
| Pending-items list (new, Wave 2) | Remove (also Del key) · Show in Explorer. Removal re-runs `summarize()` from the cached FileInfo list (mainwindow.py:283-301) — no file re-read, same trick `_on_profile_changed` uses (:310-320) |
| Results hero | Copy summary |
| Archive browser rows (Wave 3) | Extract selected · Copy SHA-256 · Copy path · Properties (inline expander row, reusing the queue's item-widget pattern, queue_table.py:110-117 — details-on-demand without Ark's side panel stealing width) |
| Extract/Advanced line edits | Qt's default edit menu (free) |

Every menu action is a QAction from the menu-bar registry (Wave 1), so the
same objects later seed I10's Ctrl+K palette and settings search — PeaZip's
single caption→action dispatcher pattern (doc 17 §6, F12 `runfunctions` →
`do_pmfun`; LGPLv3, reimplement the concept, never translate the Pascal).

---

## 7. Implementation plan, in waves

Verification baseline for every wave: `.venv\Scripts\python.exe -m pytest -q`
stays green (**324 tests as of 2026-08-04**, merged; the first draft said 302,
itself correcting a stale CLAUDE.md 223) and tools/shots.py is re-captured (dark + light,
100/125/150 %).

### Wave 1 — cheap, class-changing (13 items) ✅ SHIPPED 2026-08-02/04

(`4a25530` wave 1a, `b40f2ef` wave 1b, `45e8110` audit fixes — merged to main.)

**Honest scope (amended after review): Wave 1 makes the flow *operable* on
1366×768 — the commit action, the chooser and the results are always reachable
— and W1-13 (the chooser merge, promoted from Wave 2) delivers the single
biggest height reclaim. Full *fit* of the populated page inside one viewport
still needs W2-1's Activity tab; the first draft's "contains every blocker"
claim was false by its own tables.**

| # | What | Files | Effort | Verify |
|---|---|---|---|---|
| W1-1 | Persist window geometry: `saveGeometry`/`restoreGeometry` via QSettings (first slice of I1); `initial_size()` (mainwindow.py:43-55) stays as the no-stored-state fallback, and the restore is clamped to the current screen. **Ships WITH test isolation**: org/app name set in exactly one place, plus a conftest fixture routing QSettings to `tmp_path` (IniFormat + setPath) before any window exists — otherwise five GUI test files become machine- and order-dependent and CI pollutes the developer's registry | gui/mainwindow.py, gui/app.py, tests/conftest.py | S | resize, relaunch, geometry kept; first launch still fits 1366×768; suite passes twice in a row with different stored geometry |
| W1-2 | **Fixed action bar** between the page and the status bar: Compress/Clear + Advanced toggle + "→ output\path.excmp" label with editable name chip (safepath-validated). Buttons leave the scrolling page. **Includes the Advanced panel's new home**: a collapsible section expanding upward from the bar, outside the scroll (never a Qt.Popup — its Browse dialogs would dismiss it) | gui/mainwindow.py:133-148, 175-178, 339-343, widgets/preset_cards.py (panel) | M | populated state at 100/125/150 %: compress button always on screen (kills the 428–860px-below-fold blocker); opening Advanced displaces nothing |
| W1-3 | Layout diet: delete both `setMinimumHeight(150)` (dropzone.py:55, preset_cards.py:50); dropzone glyph 30pt→18pt, merge title+hint (dropzone.py:64-68); spacing 14→12, margins →GUTTER horizontal / 12 vertical (mainwindow.py:118-119); **empty queue's 120px minimum slab collapses to a ~60px hint row** (queue_table.py:23 area) | gui/widgets/dropzone.py, preset_cards.py, queue_table.py, mainwindow.py | S | empty state fits the 125 % viewport; no truncation at 910px width |
| W1-4 | Scroll to results: keep a reference to the QScrollArea, call `ensureWidgetVisible(self.results)` after `results.show_job` (interim until Activity tab) | gui/mainwindow.py:398-409 | S | finishing a job visibly changes the screen |
| W1-5 | QSS specificity fixes: `#Hero` defaults to $text + explicit `#Hero[tone=…]` and `#Subtitle[tone=…]` rules; smoke test asserting hero palette color per tone | gui/theme.py:94-111; new test | S | failure hero renders $danger; Insane card note renders $warn |
| W1-6 | WCAG + focus + danger: dark primary text →#0b0d12; light ok→#0e7a52, warn→#8a5700; 2px $accent_hi focus; danger resting color; cancel × `setFixedSize(28,28)`+padding rule | gui/theme.py:27, 48-49, 135-145, 264-267; queue_table.py:100-102 | S | contrast script ≥4.5:1 for all text-role pairs; Tab onto Compress visibly rings |
| W1-7 | "Time left" → "Time"; keep `fmt_eta` for RUNNING only, "took 11.4s" phrasing on DONE | gui/widgets/queue_table.py:56, 140, 157-159 | S | Done row no longer mislabels a number |
| W1-8 | In-app context menus on queue rows + results hero (§6), via `customContextMenuRequested` | gui/widgets/queue_table.py, results.py | S | right-click a finished row → Open output folder works; Shift+F10 too |
| W1-9 | The action registry, **behind a hamburger QToolButton in the tab-bar corner** (`QTabWidget.setCornerWidget`) — no QMenuBar row, the height is never spent (§2.4). Same QActions: File (Add files… Ctrl+O, Add folder…, Open archive…, Exit), Queue (Pause/Resume, Clear finished), View (theme), Help (About — an **inline panel, never a QMessageBox**, which would violate the no-modal rule in the same wave W2-9 enforces it). All `self.tr()`; QActions seed the I10 registry. **Includes QMenu/QMenuBar QSS** — theme.py has zero rules today, so an unstyled menu renders system-light against the dark theme | gui/mainwindow.py, gui/theme.py | S | every action fires the same slot as its button; menu matches the theme; About shows inline |
| W1-10 | Width fixes: `setWordWrap(True)` on the breakdown detail label (results.py:222) + widest analysis warning; page minimum <800px | gui/widgets/results.py, analysis_card.py | S | no horizontal scrollbar at 910px logical |
| W1-11 | **1366×768 regression gate**: pytest-qt builds the window headless, resizes to 1180×721 (and 125 % metrics), asserts `scroll_area.verticalScrollBar().maximum() == 0` for the pre-run state. The 150 % *empty-state* assertion is only satisfiable once W1-3's queue-slab collapse lands, and the *populated* ≤300px assertion only with W1-13 — gate and diet ship together | tests/ | S | the fix set cannot silently regress — it already regressed once |
| W1-12 | Decouple category colors from semantic tokens (text→#14b8a6, binary→#818cf8) + the no-intersection comment | gui/widgets/bars.py:21-29 | S | breakdown bar no longer reads as a progress bar |
| W1-13 | **Chooser merge, promoted from Wave 2** (it is the single biggest height reclaim, ~400–500px, and touches files W1-3 already edits): PresetSelector + CompareTable become one radio-row chooser. **API-compat is part of the item**: `rows()`, `row.profile`, `profileChosen`, `current_profile()`, a named home for `set_tool_availability`'s missing-tool notes, exactly one accent row, and the one-sentence `accessibleName` carrying reason *and* caveat — tests/test_gui_compare.py and 5 window-wired tests pin all of it. **No honesty demoted to hover**: the footnote becomes a click-to-toggle ⓘ disclosure (not a tooltip — keyboard users and screenshots lose tooltips), and the caveat stays visibly rendered on the recommended row | gui/widgets/compare_table.py, preset_cards.py, mainwindow.py | M | chooser ≤200px for 4 rows; one "Suggested" assertion on screen; suite stays green without rewriting the compare tests |

### Wave 2 — structure + visual system (the rest of the height blocker)

| # | What | Files | Effort | Verify |
|---|---|---|---|---|
| W2-1 | **Activity tab**: queue header + QueueTable + results move out of Compress; persistent status strip (promote the `_refresh_actions` text, mainwindow.py:479-488, + mini bar) on all tabs, click→Activity; queue cap becomes `min(_MAX, viewport*0.5)` and `_adjust_height` measures with `visualItemRect` instead of the 42/150 constants (queue_table.py:23, 131). **Pinned behaviours** (decided here, not ad hoc): clicking Compress does NOT auto-switch tabs — users queue several jobs; the tab title increments ("Activity (2)") and the strip updates. Strip elision priority at 910px: job status wins, the tools line elides with its full text available in Settings/About | gui/mainwindow.py, widgets/queue_table.py | L | populated Compress page ≤300px (§2.4); queue status visible on every tab; W1-11 gate extended to the populated state |
| W2-2 | ~~Merge PresetSelector + CompareTable~~ **promoted into Wave 1 as W1-13** (adversarial review: it is the biggest single reclaim and Wave 1 without it delivers operability, not fit) | — | — | — |
| W2-3 | Compact ResultsPanel: hero 21pt/600, explanations capped at 3 + "show all N" expander (results.py:30, 232-257), "Where the bytes went" collapsed by default, drop `tone="accent"` on the frame (results.py:41-42), grid-align Before/After labels (bars.py:148-149) | gui/widgets/results.py, bars.py, theme.py | M | panel ≤300px populated |
| W2-4 | Token sweep: type ramp, 4px spacing constants, radii 8/4, control min-heights, constant 2px preset border, delete `shadow` + `pad` (§3) | gui/theme.py + one pass over layout calls | M | shots diff shows uniform padding/radii; no 1px selection jiggle |
| W2-5 | Fluent SVG icons replace emoji, preset cards first; QtSvg tint-by-token; regular/filled pair for tab selection | gui/theme.py or new gui/icons.py + assets/ | M | icons recolor on theme toggle; Win10 == Win11 rendering |
| W2-6 | Dark title bar (DWMWA_USE_IMMERSIVE_DARK_MODE) + follow-system scheme hook (§3.4) | gui/winintegration.py, app.py | S | dark titlebar on Win10 19045; toggling OS theme restyles live |
| W2-7 | Queue table density: merge Profile+Size under Job, progress 150→110 (queue_table.py:72-73, 79); empty-state hint painted on the viewport (matching the placeholder idiom at :115) | gui/widgets/queue_table.py | M | full table visible at 860px of width; empty queue explains itself |
| W2-8 | Analysis busy progress: indeterminate bar + per-file tick ("scanning 34/81") | gui/widgets/analysis_card.py:83-92, queue_manager.py | S | HDD corpus scan no longer reads as a hang |
| W2-9 | I9: reusable InfoBar-style `Banner(QFrame)` (icon + text + verb-labeled actions, 48px, tone-tinted, text carries meaning) replaces the closeEvent modal; same widget later serves I4 and error surfaces | new gui/widgets/banner.py; mainwindow.py:506-513 | S | closing mid-job shows an inline banner; zero QMessageBox left in gui/ |
| W2-10 | Pending-items list (review/remove before compressing) + Del key + context menu (§6); drop the dead Shrink-mode checkbox into the hint text (analysis_card.py:56-72) | new widget; mainwindow.py, analysis_card.py | M | removing one file re-summarizes without re-reading |

### Wave 3 — expose the engine + Settings (the "looks cheap" payload, §5)

I1 Settings tab with SettingsCard geometry (68px rows, 16px padding, 20px icon,
wrap <476px — CommunityToolkit SettingsCard.xaml defaults) — M. Verify button +
`excmp verify` — S. G1 foreign-archive extract — S. `.excmp` flat listing
(I2-lite, manifest read only) with the properties strip — M. `.sha256` sidecar
(G6) — S. `excmp hash` (G8) — S. Copy-as-command — S. Archive-dominant chip —
S. Output-name field polish + Ark autosubfolder heuristic (set_archive
currently always proposes `archive.with_suffix('')`, extract_tab.py:117-120 —
the manifest makes "single top-level folder?" a set comprehension) — S.
"Open folder after extraction" checkbox, default OFF, + extract split-button
with recent destinations (needs QSettings) — S. Level/dict knobs + RAM column
+ Parameters line (plumbing through `_stage_factory` and `StageRecord.params`)
— M. I4 first-run banner (reusing W2-9's Banner) — S. In-app Recent (File >
Recent + empty-dropzone chips) — S. Password-on-demand inline banner pattern
pinned for G2 (File Roller timing + PeaZip dummy `-p`; distinguish encrypted
vs corrupt from stderr) — lands with G2.

### Wave 4 — power surface

I3 queue reorder/Run-next/History tab — M. I5 Explorer verbs: argv intake +
CLI contract + HKCU verbs + `.excmp` ProgID/file association +
SetForegroundWindow fix (extract verb opens the slim progress surface; the
compress verb ALWAYS opens the full window with analysis — Ark's batch split,
adopted asymmetrically on purpose) — M. I10 Ctrl+K palette + settings search
from the W1-9 QAction registry — M. I8 treemap — M. G4 export UI — S.
Archive-browser keyboard subset (Enter/Alt+Enter/Backspace/Ctrl+PgDn) — S.
I6 measure-on-this-input benchmark feeding the chooser — M.

---

## 8. Explicitly NOT being done (and why, so it stays decided)

- **Becoming a file manager** (7-Zip FM two-panel F9, F2/F5/F6/F7 verbs,
  PeaZip's 80k-line browser): rejected three times with reasons recorded —
  doc 08 skip list, doc 11 Tier-skip, doc 17. Explorer plus I5's context menu
  covers the filesystem half better than we would.
- **PySide6-Fluent-Widgets or any GPL/commercial widget library**: GPLv3 vs
  MIT repo; breaks the SignPath OSI-clean requirement. Already rejected;
  hand-rolled QSS + the DWM titlebar attribute is the whole "modern feel"
  budget (theme.py:1-10, doc 14 §7).
- **Segoe Fluent Icons font**: EULA + absent on Win10 (§4).
- **Left nav rail / wizard mode**: §2.2.
- **Update-in-place modes** (7-Zip u, WinRAR fresh/sync): wrong for a solid
  multi-stage container; "repack to update" is the honest contract (doc 08,
  doc 22 §1, ROADMAP Phase G notes). Surface the *reason* in a tooltip, not
  the feature.
- **Password manager**: storing users' passwords is a liability that
  contradicts the trust identity (doc 08; revisit OS-keyring only after F1).
- **Secure delete**: ineffective on SSDs (wear leveling) — shipping it would
  sell a false promise (doc 08).
- **RAR creation**: legally impossible forever (unRAR license forbids
  reimplementing the compressor); reading stays free via user-installed
  7z.exe (doc 08 legal findings).
- **Generic MIPS benchmark** (7-Zip Tools→Benchmark): answers a question
  nobody asked; I6 benchmarks the user's actual data instead (the 2026-08-01
  measurement — Extreme = 2.7× Normal's time for +0.17pp — is exactly what a
  synthetic score can never say).
- **Modal progress dialogs** (Ark/File Roller/Xarchiver): §2.2; the visible
  queue is load-bearing.
- **Mica/backdrop under content, XAML islands**: Qt paints opaque; titlebar
  ambience only, Win11 only, HDR-guarded (doc 14 §7).
- **SFX before code signing lands** (Phase H): an unsigned per-archive exe is
  SmartScreen-flagged forever (doc 16 §2); faking it with generated stubs
  would torch the trust brand. At most a greyed "Installer output (coming
  after signing)" label.
- **Xarchiver as a reference**: validates the subprocess architecture we
  already have, offers nothing for the UI (recorded so nobody mines it again).
- **Hiding or softening the honesty surfaces to save pixels**: the analysis
  card's store-reasons, the missing-tool notes, and the estimate caveats
  compress into tooltips/expanders but never disappear — pixels come out of
  duplication and dead chrome (§1.2), not out of the product's identity.
