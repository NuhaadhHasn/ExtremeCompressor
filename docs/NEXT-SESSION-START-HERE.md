# 🚦 START HERE — handoff for the next session (written 2026-08-02)

> Previous session (a long one): **Phase J part 1 → B11+D9 integrity fixes →
> UI v3 research → UI wave 1a.** All committed.
> Next session: **finish UI wave 1** (items listed in §3), from
> `docs/research/23-ui-v3-redesign.md` — the spec already has the adversarial
> review folded in; do not re-derive it.

---

## 1. State of the repo

**312 tests pass.** Three stacked branches await review, merge bottom-up:

```bash
git merge --no-ff phase-j-smart-advisor     # estimator + comparison UI (J1-J4, J8)
git merge --no-ff phase-b11-d9-integrity    # SREP removed; verify-before-publish
git merge --no-ff phase-ui-v3               # screen fit + wave 1a of the redesign
```

| branch | commits | what |
|---|---|---|
| `phase-j-smart-advisor` | `9620888`, `5675c90` | estimates + chooser table, visual-QA fixes |
| `phase-b11-d9-integrity` | `c6285df`, `d01c8ae` | chains SREP-free; full restore+verify gates every publish; estimator models the verify pass |
| `phase-ui-v3` | `c094ddf`, `4a25530` | window sized to screen; merged chooser, cascade/contrast/diet fixes |

Docs already on `main`: `3aff9e3` (B11+D9 benchmark), `bd02a03` (research/23,
the UI spec), plus this handoff. `docs/images/` lives on `phase-j`/`phase-ui-v3`.

## 2. What landed, one line each

- **B11**: Extreme/Insane = `precomp → sevenzip`. Old srep archives still
  extract (test-pinned). Measured cost: −3.5pp on dedup-friendly data, +31 s on
  the 721 MB corpus ([benchmarks/2026-08-02](benchmarks/2026-08-02-b11-d9-acceptance.md)).
- **D9**: nothing publishes without a full temp restore + ledger verification —
  the same `extract()` users run. A corrupting stage now blocks publication
  (`tests/test_publish_gate.py`). Estimator gained a per-chain verify term;
  preflight budgets the restore.
- **UI wave 1a** (`4a25530`): ONE profile chooser (radio rows; placeholders
  before analysis — it never hides, it is the only picker now); hero/tone QSS
  cascade fixed and pixel-tested; 6 WCAG AA failures fixed (2 found by the new
  test, not the audit); focus rings visible; diet (both 150px slabs gone, queue
  slab 120→64); results scroll into view; "Time left" mislabel fixed; category
  colors decoupled from semantic tokens.

## 3. The actual next job: UI wave 1, remaining items

Spec: `docs/research/23-ui-v3-redesign.md` §7 (amended — trust it, the critique
is already folded in). Done: W1-3/4/5/6/7/12/13 and the `initial_size()` half
of screen fit. **Remaining:**

| item | note |
|---|---|
| **W1-1** geometry persistence | QSettings org/app set in ONE place + a conftest fixture routing QSettings to tmp_path BEFORE any window exists — without it five GUI test files go machine-dependent. Clamp the restore to the current screen. |
| **W1-2** fixed action bar | Compress/Clear + Advanced toggle + "→ output\path.excmp" with an editable, safepath-validated name chip. The Advanced panel becomes a section expanding UPWARD from the bar (never `Qt.Popup` — its Browse dialogs would dismiss it). Kills the button-below-the-fold blocker. |
| **W1-8** context menus | queue rows (Cancel/Open output folder/Copy path/Copy as command/Show log/Remove) + results hero (Copy summary). Slots exist; §6 of the spec has the table. |
| **W1-9** action registry | hamburger QToolButton via `QTabWidget.setCornerWidget()` — NOT a QMenuBar row (the 150% budget has no ~23px to spare). QMenu QSS already landed in wave 1a. About = inline panel, never QMessageBox. |
| **W1-10** width word-wraps | results.py breakdown label + widest analysis warning; page minimum <800px. |
| **W1-11** regression gate | pytest-qt: scrollbar maximum == 0 pre-run at 1180×721 and 125% metrics; populated ≤300px at 150% only holds together with W2-1, so scope the assertion to what wave 1 ships. |

Then wave 2 (§7): Activity tab (behaviours already pinned: no auto-switch, tab
title increments), compact results, token sweep, Fluent SVG icons, dark title
bar, W2-9 Banner replacing the closeEvent modal (I9).

## 4. Findings worth not rediscovering

1. **QPushButton ignores child layouts in its sizeHint** — deleting the preset
   cards' `setMinimumHeight(150)` collapsed them to empty slivers. That is why
   W1-3 and W1-13 had to ship together (they did).
2. **The QSS cascade lies quietly**: ID selectors (101) beat attribute
   selectors (11). `tests/test_gui_theme.py` renders labels and samples pixels;
   it caught two AA failures the research audit missed. Extend it, don't
   bypass it.
3. **Render with real fonts before calling GUI work done** — offscreen Qt
   draws tofu unless `QT_QPA_FONTDIR` is set; `tools/shots.py` does it right.
   Run it, look at `docs/images/01-drop-analysis.png`.
4. **The merged chooser preserves both old APIs** — `window.presets` IS
   `window.compare_table` (one object). Don't "clean up" the alias: tests and
   tools/shots.py use both names.
5. Precomp remains unpredictable from samples (documented limitation, not a
   bug): the estimator's Precomp numbers are ceilings, ranges must contain
   both regimes, and a conditional "not worth it" flag warns but never demotes
   the recommendation. Measured both ways; don't relitigate.
6. **Verify throughput is cache-noisy** (identical extracts measured 50.3 s
   and 19.9 s minutes apart) — keep the verify model coarse.

## 5. Standing rules (unchanged)

- No AI attribution in commits — audit before committing. **Watch the audit
  grep**: the word "regenerated" matches a lazy `generated` pattern.
- Docs → `main`; code → branch, unmerged. One phase per session.
- 100% OSI-clean; never bundle SREP/lolz/oo2core/unrar.dll.
- Target hardware: 2-core i7-3540M, 16 GB, **1366×768 primary display** —
  every UI decision is calibrated to it (see research/23 §2.4 for the real
  viewport arithmetic: 698/544/432 logical client at 100/125/150%).
- Lossless is a hard guarantee; post-restore SHA-256 is the acceptance gate —
  and since D9, that sentence is enforced by `_verify_before_publish`, not
  aspiration.

## 6. Real test data

Unchanged: corpus A (721 MB, 6 files) and corpus B (163 MB, 5 files) as listed
in `docs/benchmarks/2026-08-02-b11-d9-acceptance.md`; the untested
"Programming Tutorials" tree remains a fresh out-of-sample candidate for J7.
