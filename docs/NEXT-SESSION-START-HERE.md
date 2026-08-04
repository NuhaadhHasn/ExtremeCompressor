# 🚦 START HERE — handoff for the next session (written 2026-08-02)

> Previous session (a long one): **Phase J part 1 → B11+D9 integrity fixes →
> UI v3 research → UI wave 1 COMPLETE** (all 13 items). All committed.
> Next session: **UI wave 2** from `docs/research/23-ui-v3-redesign.md` §7 —
> the spec already has the adversarial review folded in; do not re-derive it.

---

## 1. State of the repo

**323 tests pass.** Three stacked branches await review, merge bottom-up:

```bash
git merge --no-ff phase-j-smart-advisor     # estimator + comparison UI (J1-J4, J8)
git merge --no-ff phase-b11-d9-integrity    # SREP removed; verify-before-publish
git merge --no-ff phase-ui-v3               # screen fit + wave 1a of the redesign
```

| branch | commits | what |
|---|---|---|
| `phase-j-smart-advisor` | `9620888`, `5675c90` | estimates + chooser table, visual-QA fixes |
| `phase-b11-d9-integrity` | `c6285df`, `d01c8ae` | chains SREP-free; full restore+verify gates every publish; estimator models the verify pass |
| `phase-ui-v3` | `c094ddf`..`b40f2ef` | screen fit, merged chooser, cascade/contrast fixes, action bar, menus, persistence, fit gate |

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

## 3. The actual next job: UI wave 2

**Wave 1 is COMPLETE** — all 13 items, finished in `b40f2ef` (wave 1b: fixed
action bar with the safepath-validated editable archive name and the resolved
destination shown before commit; Advanced panel expanding upward from the bar;
geometry persistence with the QSettings conftest isolation; hamburger action
registry with 8 window-wide shortcuts; queue-row + results-hero context menus,
including "Copy as command"; the fit regression gate; width wraps).

Wave 2 next, from `docs/research/23-ui-v3-redesign.md` §7:

| item | note |
|---|---|
| **W2-1** Activity tab | queue + results move out of Compress; persistent status strip on every tab. Behaviours already pinned: NO auto-switch on Compress; the tab title increments ("Activity (2)"); job status wins the strip's elision. Queue cap becomes viewport-relative. Populated-page ≤300px @150% gate lands here. |
| **W2-3** compact results | hero already 21pt; explanations cap 3 + expander; "Where the bytes went" collapsed by default. |
| **W2-4** token sweep | 4px grid constants exist in theme.py (GUTTER/VGAP/GAP_*); sweep the remaining ad-hoc paddings/radii. |
| **W2-5** Fluent SVG icons | replace the ⚡⚖️🔥🌙 emoji; MIT, tint-by-token via QtSvg. |
| **W2-6** dark title bar + follow-system | DWMWA_USE_IMMERSIVE_DARK_MODE next to the existing COM code in winintegration.py; QStyleHints.colorScheme hook. |
| **W2-8** analysis busy progress | "scanning 34/81" — the HDD corpus reads as a hang today. |
| **W2-9** Banner widget | replaces the closeEvent QMessageBox (I9) — the last modal. |
| **W2-10** pending-items list | review/remove inputs before compressing; re-summarize from cached FileInfo. |

Then wave 3 (expose the engine: Verify button, foreign-archive extract, flat
`.excmp` listing, sidecars, level/dict knobs + RAM column) — §5 of the spec is
the inventory, and J5–J7 remain on the roadmap.

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
4. **Word-wrapping QLabels poison QScrollArea sizing**: a wrapped label's
   minimum height assumes wrapping at minimum width, and the scroll area
   sizes pages by MINIMUM hint - four wrapped rows manufactured a 45px
   scrollbar the real layout never needed. Chooser cells clip instead of
   wrapping now; only full-width prose wraps.
5. **The merged chooser preserves both old APIs** — `window.presets` IS
   `window.compare_table` (one object). Don't "clean up" the alias: tests and
   tools/shots.py use both names.
6. Precomp remains unpredictable from samples (documented limitation, not a
   bug): the estimator's Precomp numbers are ceilings, ranges must contain
   both regimes, and a conditional "not worth it" flag warns but never demotes
   the recommendation. Measured both ways; don't relitigate.
7. **Verify throughput is cache-noisy** (identical extracts measured 50.3 s
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
