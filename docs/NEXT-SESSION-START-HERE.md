# 🚦 START HERE — handoff for the next session (written 2026-08-06)

> Previous session: **UI v3 wave 2a** — W2-1 (Activity tab + status strip),
> W2-3 (compact results), W2-7 (queue density), W2-8 (scan progress),
> W2-9 (the last modal is gone). On a branch, **not merged**.
> Next session: **UI wave 2b** — W2-4/5/6/10 **plus the three compaction items
> that §2.4's ≤300px budget actually depends on and no W2 number owned.**

---

## 1. State of the repo

| where | what |
|---|---|
| `main` | wave 1 and everything before it, pushed. Untouched this session. |
| **`ui-v3-wave2a`** | this session's work, **unmerged, waiting for review** |

```
git checkout main && git merge --no-ff ui-v3-wave2a
```

**346 tests: 344 pass + 2 strict-xfail.** Baseline before this session was 324.

## 2. What landed

- **W2-1 Activity tab.** Queue, queue header and results panel left the
  Compress column for their own tab. A one-line status strip at the bottom of
  the window carries the queue onto every tab (job text + a 90×10 mini bar),
  clicks through to Activity, and the tab title counts unfinished jobs —
  "Activity (2)". Compress does **not** auto-switch tabs, by design.
- **W2-3 compact results.** Hero and subline share a row; before/after bars are
  a real two-column grid instead of four rows aligned with literal spaces;
  "Where the bytes went" starts collapsed; explanations cap at 3 behind
  "Show all N". Measured **285px** laid out on the real corpus.
- **W2-7 queue density.** 7 columns → 5. Profile and size fold into a second
  line under the job name; progress column 150 → 110px; an empty queue paints
  a hint on its viewport instead of showing a blank grid.
- **W2-8 scan progress.** `analyze_tree` split into `iter_files` +
  `analyze_file` so the worker knows the denominator before the expensive
  pass. Indeterminate bar while walking, then "scanning 34/81".
- **W2-9 Banner.** `gui/widgets/banner.py` — WinUI InfoBar shape, tone-tinted,
  verb-labelled actions. Replaces the close-mid-job `QMessageBox`. **Zero
  QMessageBox left in `gui/`**, pinned by a tokenised test.

## 3. The thing that matters most: the tests were measuring tofu

`tests/conftest.py` never set `QT_QPA_FONTDIR`. Qt's offscreen plugin has no
font database, so every GUI test measured tofu boxes of the wrong width, and
**every height gate wave 1 shipped was checked against fiction**. Only
`tools/shots.py` set it, which is why the screenshots looked right.

conftest sets it now. Real numbers, 910×512:

| | before wave 2a | after |
|---|---|---|
| populated Compress page | **869 px** | **748 px** |
| the same, measured with tofu | — | 669 px |

Do not undo this. Every budget claim in research/23 §1–§2.4 predates it.

## 4. The actual next job: UI wave 2b

§2.4's ≤300px budget needs **three compaction items that no W2 number owned** —
this was the plan's biggest gap and it is now written down in research/23 §7
under "What wave 2a corrected in this plan":

| what | now | target | notes |
|---|---|---|---|
| **intake chip** | drop zone 116px always | ~36px once files are in | §2.3's wireframe has it; re-expands on drag-enter / when empty. Pairs naturally with **W2-10**'s pending-items list |
| **analysis card collapse** | 200px | ~96px (≤80 at 150 %) | fold the detail line into an expander |
| **chooser diet** | 401px | ~172px | 32px rows; **and W1-13's ⓘ disclosure, which was specified but never built** — `compare_table.py` shows the 68px footnote unconditionally (`self._footnote.setVisible(self._estimated)`) |

Plus the numbered remainder: **W2-4** token sweep (type ramp, radii 8/4,
control min-heights, delete `shadow`/`pad`), **W2-5** Fluent SVG icons,
**W2-6** dark title bar + follow-system, **W2-10** pending-items list.

**Two strict-xfail gates in `tests/test_gui_fit.py` will fail the suite the
moment this lands.** That is deliberate — delete the xfail marker and the
assertion underneath is already the real gate. They are:

- `test_the_populated_compress_page_meets_the_150_percent_budget` (≤300px)
- `test_the_empty_compress_page_needs_no_scrolling_at_150_percent` (overflows
  by 35px today)

Then wave 3 (expose the engine: Verify button, foreign-archive extract, flat
`.excmp` listing, sidecars, level/dict knobs + RAM column) — §5 of the spec is
the inventory, and J5–J7 remain on the roadmap.

## 5. Findings worth not rediscovering

1. **QSS `height` does not constrain a laid-out `QProgressBar`.** Both new bars
   first shipped as fat slabs — 55px in the two-line queue cell, 40px in the
   status bar — because a tree item widget fills its cell and a status-bar
   permanent widget takes the bar's height. Only `setFixedHeight`/`setFixedSize`
   works, and in the tree cell the bar needs a centering holder widget around
   it. Caught by *looking at the screenshots*, not by any test.
2. **"Fill the host" and "size to your hint" are contradictory**, which is why
   the Activity page is deliberately not a `QScrollArea`. Making it one would
   bring back the height cap the queue no longer needs.
3. **The queue's `_adjust_height` and its 430px cap were deleted, not ported.**
   §7 asked for `min(_MAX, viewport*0.5)` and `visualItemRect` measurement;
   both existed only to stop an empty queue pushing the results panel off the
   shared Compress column. On its own tab the table just fills and scrolls
   internally — ~30 lines of heuristic gone.
4. **A fixed progress tick is wrong at both ends.** Every-5-files still left a
   4.7s freeze on big installers; the tick is now `max(1, total // 200)`.
5. **Grep is the wrong tool for "no modals left".** The comments explaining why
   the modals went name `QMessageBox`; the test tokenises and only counts NAME
   tokens.
6. Findings 1–7 from the previous handoff all still hold, in particular
   **word-wrapping QLabels poison QScrollArea sizing** and **the chooser's
   `window.presets` / `window.compare_table` alias must not be "cleaned up"**.

## 6. Two warts spotted, deliberately not fixed

- **The status bar advertises `srep`.** B11 removed SREP from every chain, but
  `find_tools` still probes for it, so the strip reads "Tools found: 7z,
  precomp, srep" on a machine that has it installed. Nothing bundles it — the
  OSI rule is intact — but the app is naming a tool it will never run.
- **`CLAUDE.md`'s corpus description has drifted.** The Programs folder is now
  **6.4 GB across 42 files**, not "5.76 GB", and measures **41.9 %** stored
  under the default profile, not 81 %. Re-measure before quoting it.

## 7. Standing rules (unchanged)

- No AI attribution in commits — audit before committing. **Watch the audit
  grep**: the word "regenerated" matches a lazy `generated` pattern.
- Docs → `main`; code → branch, unmerged. One phase per session.
- 100% OSI-clean; never bundle SREP/lolz/oo2core/unrar.dll.
- Target hardware: 2-core i7-3540M, 16 GB, **1366×768 primary display** —
  698/544/432 logical client at 100/125/150 % (research/23 §2.4).
- Lossless is a hard guarantee; post-restore SHA-256 is the acceptance gate,
  enforced by `_verify_before_publish`.

## 8. Real test data

Corpus A (721 MB, 6 files) re-run this session and byte-identical to
2026-08-02: **700,884,250 bytes, 6/6 independently verified**. Full numbers in
[`benchmarks/2026-08-06-ui-wave2a.md`](benchmarks/2026-08-06-ui-wave2a.md).
Timings on that external drive are cache-noisy — see finding #7 of the previous
handoff before quoting any throughput from it.
