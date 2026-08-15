# 🚦 START HERE — handoff for the next session (written 2026-08-07)

> Previous session: **UI v3 wave 2, both halves.**
> 2a — Activity tab + status strip, compact results, queue density, scan
> progress, the last modal gone.
> 2b — the height compaction (intake chip, analysis-card disclosure, chooser
> diet), token sweep, Fluent SVG icons, dark title bar, pending-items list.
> All on one branch, **not merged**.
> Next session: **UI wave 3 — expose the engine** (research/23 §5).

---

## 1. State of the repo

| where | what |
|---|---|
| `main` | wave 1 and everything before it, pushed. Untouched by this work. |
| **`ui-v3-wave2a`** | waves 2a **and** 2b, **unmerged, waiting for review** |

```bash
git checkout main && git merge --no-ff ui-v3-wave2a
```

**373 tests: 372 pass + 1 strict-xfail.** Baseline two sessions ago was 324.

`excmp/` is unchanged by wave 2b — the whole wave is `gui/`, `assets/` and
tests, so the compression path provably did not move.

## 2. The headline numbers

Populated Compress page at 910×512 (1366×768 @ 150 %), real fonts:

| | px |
|---|---|
| before wave 2a | **869** |
| after 2a (queue + results moved to Activity) | **748** |
| after 2b (compaction + QA pass) | **415** |

The **empty** Compress page now fits a 150 %-scaled display with zero scroll —
the first time in the project's history. That gate was a strict xfail at the
end of 2a; it started passing, which *failed the suite* (strict=True), which is
exactly what forced it to be promoted into the real parametrized gate rather
than quietly forgotten. That mechanism works; keep using it.

## 3. Two things wave 2 settled that must not be re-litigated

1. **research/23 §2.4's ≤300px budget is unreachable, and §3.3 wins.** Four
   profile rows at the Windows 32px touch floor are 128px on their own; §2.4
   budgeted the whole chooser at 172px. With everything compacted the page
   floors at **415px**, and the missing 115px only exists in things the product
   has decided to keep: four comparable rows, an always-visible analysis card,
   the touch floor. The ≤300 assertion stays in `test_gui_fit.py` as a
   `strict=True` xfail. **Do not "fix" it by shrinking controls below 32px.**
   Full arithmetic: `benchmarks/2026-08-07-ui-wave2b.md`.
2. **Row height encodes uncertainty.** Fast/Normal are 34px because their
   estimate is one number; Extreme/Insane are 51px because theirs is a *range*
   (Precomp's gain is unknowable until it runs). Inlining the range needs
   ~210px in a 178px column. The extra height is where the honesty lives.

## 4. The actual next job: UI wave 3 — expose the engine

research/23 §5 is the inventory, and it is the direct answer to "looks cheap":
the engine already does all of this and the UI hides it. In rough value order:

- **Verify button + `excmp verify`** (S) — `_verify_before_publish` already does
  a full restore + per-file SHA-256 (`excmp/engine.py`, `excmp/verify.py`);
  `SevenZipStage.test` exists and is never called from the GUI. Highest
  credibility-per-line in the whole inventory: verification *is* the brand, yet
  today it only ever happens implicitly.
- **G1 foreign-archive extract** (S) — `extract()` already shells `7z x` on any
  path; the Extract tab filter is `*.excmp` only. Widen it, and label it
  honestly: no SHA-256 ledger, verification limited to `7z t`.
- **`.excmp` flat listing** (M, I2-lite) — `read_container`/`_read_manifest` is
  a free zip+JSON read; the ledger already carries relpath → size, SHA-256,
  route, and *why stored*. Richer columns than 7-Zip can render.
- **`.sha256` sidecar (G6)** (S) — publish is a single atomic `replace`;
  hashing the container there is ~10 lines.
- **`excmp hash` (G8)**, **Copy-as-command** (both S) — `hash_file` exists; the
  full CLI already exists.
- **I1 Settings tab** (M) — CommunityToolkit SettingsCard geometry: 68px rows,
  16px padding, 20px icon, wrap below 476px.
- **Level/dict knobs + RAM column + Parameters line** (M) — needs plumbing
  through `_stage_factory` and `StageRecord.params`, which is always `{}` today.

The Settings tab is also the natural home for the tools inventory that the
status strip elides at narrow widths.

## 4b. Run the QA sweep before calling a UI phase done

`tools/qa_sweep.py` renders **12 surfaces x 2 themes** offscreen with real
fonts - including the ones no test and no README screenshot ever touches: the
banner, the Extract tab, the expanded pending list, a failed-job results panel,
the Advanced panel, About, and everything-disclosed-at-once.

```bash
.venv\Scripts\python.exe tools\qa_sweep.py --out .qa
```

It exists because wave 2 shipped four visual defects past a fully green suite,
and every single one was found by rendering a surface and looking at it:

| defect | how it read on screen |
|---|---|
| progress bars filled their cell | a 55px slab of flat colour, not a bar |
| tinted glyphs used `$muted` | three near-invisible ghosts beside one green flame |
| chooser cells hard-clipped | "zpaqfranz missing - runs as E:" - looks like a bug |
| `fmt_percent` rounded 99.6 to 100 | **"100% or better"** - an archive of zero bytes |

That last one is the one to remember. It was the most over-promising sentence
the app has ever rendered, in the one panel whose entire job is not to
over-promise, and 371 passing tests had nothing to say about it. **Tests pin
behaviour; rendering pins appearance. A UI phase needs both.**

## 5. Findings worth not rediscovering

1. **`QT_QPA_FONTDIR` in `tests/conftest.py` is load-bearing.** Qt's offscreen
   plugin ships no font database; without it every GUI test measures tofu boxes
   of the wrong width, and every height gate is fiction. Wave 1's gates were
   all measured against tofu. **Never remove this line.**
2. **QSS `height` does not constrain a laid-out `QProgressBar`** — only
   `setFixedHeight`/`setFixedSize` does. Both new bars first shipped as fat
   slabs. Caught by *looking at the screenshots*, not by a test.
3. **A cell that cannot wrap must elide, not clip.** Chooser cells cannot
   word-wrap (a wrapped QLabel's minimum height assumes wrapping at minimum
   width, and QScrollArea sizes pages by minimum hint — that manufactured a
   phantom scrollbar). They used to hard-clip mid-word: "zpaqfranz missing —
   runs as E:" read as a rendering bug. `_ElidingLabel` in `compare_table.py`
   is the fix; the full text stays in the tooltip and the spoken name.
4. **The caveat used to vanish from the accessible sentence** the moment
   estimates arrived — `ProfileRow` only appended `row.caveat` in placeholder
   mode, so a screen-reader user was never told that Insane degrades to
   Extreme. Fixed. Found by a test written for something else entirely; worth
   remembering that the accessible strings need their own assertions.
5. **A rounded percentage can become a lie.** `fmt_percent(0.996)` is "100%",
   and "100% or better" promises a zero-byte archive. `gui.suggest._saved_words`
   caps the *wording* at 99% and leaves the estimator's number untouched.
   Anywhere a percentage is rendered near a superlative, check the rounding.
6. **Tinted SVGs need `$text`, not `$muted`.** A muted glyph on `$surface` in
   dark mode is very nearly invisible — the first icon render was three ghosts
   beside one green flame, worse than the emoji it replaced.
7. **"Fill the host" and "size to your hint" are contradictory**, which is why
   the Activity page is deliberately not a `QScrollArea`.
8. **Grep is the wrong tool for "no modals left"** — the comments explaining
   why the modals went name `QMessageBox`. The test tokenises.
9. Word-wrapping QLabels poison QScrollArea sizing; the chooser's
   `window.presets` / `window.compare_table` alias must not be "cleaned up".

## 6. Two warts spotted, still deliberately not fixed

- **The status bar advertises `srep`.** B11 removed SREP from every chain, but
  `find_tools` still probes for it, so the strip reads "Tools found: 7z,
  precomp, srep". Nothing bundles it — the OSI rule is intact — but the app
  names a tool it will never run. Natural cleanup alongside wave 3's Settings
  tab, which is where the full inventory will live.
- **`CLAUDE.md`'s corpus description has drifted.** The Programs folder is now
  **6.4 GB across 42 files**, not "5.76 GB", and measures **41.9 %** stored
  under the default profile, not 81 %. Re-measure before quoting it.

## 7. Standing rules (unchanged)

- No AI attribution in commits — audit before committing.
- Docs → `main`; code → branch, unmerged. One phase per session.
- **100 % OSI-clean.** `assets/icons/` now vendors Fluent UI System Icons
  (MIT); the upstream `LICENSE` sits beside the SVGs and must stay there.
  Never bundle SREP/lolz/oo2core/unrar.dll/Segoe Fluent Icons (EULA).
- Target hardware: 2-core i7-3540M, 16 GB, **1366×768 primary display**.
- Lossless is a hard guarantee; post-restore SHA-256 is the acceptance gate.

## 8. Real test data

Corpus A (721 MB, 6 files) verified in wave 2a: **700,884,250 bytes,
6/6 independently byte-identical**, matching the 2026-08-02 record exactly.
`excmp/` unchanged since, so that stands. Wave 2b's end-to-end evidence is
`tools/shots.py` driving the real window and engine: 17.2 MB → 5.0 MB
(71.3 % saved) with a verified restore. Details in
[`benchmarks/2026-08-07-ui-wave2b.md`](benchmarks/2026-08-07-ui-wave2b.md).
Timings on that external drive are cache-noisy — never quote throughput from
a single run.
