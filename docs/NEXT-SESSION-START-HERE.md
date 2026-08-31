# 🚦 START HERE — handoff for the next session (written 2026-08-07)

> **UI v3 is COMPLETE and merged to `main`** — waves 1, 2, 3a, 3b, 3c, and
> the level/dictionary knobs that finished research/23 §5.
> Next: **G2 foreign listing**, then **J5-J7**.
>
> Historical, for context — wave 2 was:
> 2a — Activity tab + status strip, compact results, queue density, scan
> progress, the last modal gone.
> 2b — the height compaction (intake chip, analysis-card disclosure, chooser
> diet), token sweep, Fluent SVG icons, dark title bar, pending-items list.

---

## 1. State of the repo

| where | what |
|---|---|
| `main` | **everything** — all of UI v3, merged 2026-08-07 |

Nothing is waiting for review.

**469 tests: 468 pass + 1 strict-xfail.** Baseline five sessions ago was 324.

### What wave 3c shipped

`.sha256` sidecar (**opt-in and remembered** — see §3), the **Settings tab**
and the first preferences this app has ever persisted, Ark's autosubfolder
heuristic for the extract destination, and I4's first-run notice.

### What wave 3b shipped

**G1** — the Extract tab opens zip/7z/rar/tar/iso/cab/msi/wim. **I2-lite** —
"What's inside" lists the whole ledger (name, size, SHA-256, route, *why
stored*) straight from the manifest, no extraction.

**The honesty boundary is the feature.** `ExtractResult.ledger_backed` exists
because `verified == 0` is ambiguous — "nothing to check against" vs "checked,
found zero good" — and the flag's first catch was the results panel rendering
*"0 SHA-256 hashes verified — byte-identical to the originals"* about a
foreign zip. `extract()` stays .excmp-only; `extract_any()` is the dispatcher.
`is_excmp()` trusts the manifest, never the extension.

**The listing corrected the manifest.** It recorded only a merged per-*route*
store reason, so the "why" column claimed each stored file measured *every*
stored file's entropy. `Manifest.store_reasons` is per-file now — defaulted,
so older archives load and fall back.

### What wave 3a shipped

`engine.verify_archive()` — the D9 publish gate, made public. `excmp verify`,
`excmp hash`, and a **Verify only** button on the Extract tab. A verify is a
queued job, not a modal, because at 721 MB it is a 34-second full restore.

**The rule it ships with: verification is a real restore of every byte
compared against the ledger — never a container self-test.** `7z t` checks
only the last stage's framing, which is exactly how srep64.exe once passed an
archive it had corrupted. `_verify_before_publish` now *calls* the public verb,
and `test_the_publish_gate_and_the_verb_are_the_same_code` fails if they ever
drift — because if the button and the gate mean different things, one is a lie.

Measured: one byte XORed with 0xFF inside a `stored/` entry of a 721 MB
archive (same length, zip CRC rewritten, so `7z t` passes it) → exit 1, names
the file. **A failing verify is slower than a passing one** (49.8s vs 34.4s):
it must restore everything before it can prove the mismatch. Do not let anyone
"optimise" that away.

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

## 4. The actual next job

**research/23 §5 is finished.** What remains:

- **G2 — foreign archive listing** (M). The pinned `7z l -slt` grammar plus
  the dummy `-p` hang guard (doc 17 §4). This is what makes "What's inside"
  work on a zip; wave 3b deliberately refuses rather than showing an empty
  list that would read as "this archive is empty". The
  password-on-demand banner pattern (File Roller's timing; distinguish
  encrypted from corrupt via stderr) lands with it.
- **J5-J7** — per-type memory, long-job confirm, self-calibration. J7 is what
  turns a cold-start prior into estimates fitted to this machine.
- Then the roadmap's own order: D1-D3/D7 (QA core + CI), B1-B3/B9-B10.

**The level/dict knobs are done** (`excmp/ram.py`, `StageOptions`), so J7's
self-calibration now has real settings to calibrate against, and B9's RAM
cap is enforced in code rather than described in a comment.

<details><summary>The wave-3c list, for reference</summary>

- **`.sha256` sidecar (G6)** (S) — publish is a single atomic `replace`, so
  hashing the container there is ~10 lines. **Decide opt-in vs default at the
  start of the session** — it is the QuickSFV/fitgirl transport habit, but it
  does put a second file beside every archive. (`excmp hash`, `excmp list`
  and Copy-as-command are already done.)
- **I1 Settings tab** (M) — CommunityToolkit SettingsCard geometry: 68px rows,
  16px padding, 20px icon, wrap below 476px.
- **Level/dict knobs + RAM column + Parameters line** (M) — needs plumbing
  through `_stage_factory` and `StageRecord.params`, which is always `{}` today.

</details>

## 3. The sidecar decision, so it is not re-litigated

**`.sha256` is opt-in and remembered.** Default-on was the other candidate —
it is the QuickSFV / fitgirl-bins convention and verification is the brand —
but a second file appearing beside every archive is an output nobody asked
for, and *"inputs are never modified; outputs are written to .tmp and
atomically renamed"* has been the engine's promise since its first commit.

Two more standing rules that came out of wave 3:

- **Advanced is per-job; Settings is remembered.** Adding Settings produced two
  "notify when a job finishes" checkboxes, and the one being read was not the
  one being saved. Notifications and tray left Advanced. Where both exist,
  Advanced wins for that job and does not rewrite the preference.
- **The status strip may elide the tools line** because Settings now carries
  the full inventory. That closes the wart the handoff has carried since 2a.

## 4b. Run the QA sweep before calling a UI phase done

`tools/qa_sweep.py` renders **13 surfaces x 2 themes** offscreen with real
fonts - including the ones no test and no README screenshot ever touches: the
banner, the Extract tab, the expanded pending list, a failed-job results panel,
the Advanced panel, About, and everything-disclosed-at-once.

```bash
.venv\Scripts\python.exe tools\qa_sweep.py --out .qa
```

It exists because wave 2 shipped four visual defects past a fully green suite,
and waves 3b, 3c and the knobs each added another —
and every single one was found by rendering a surface and looking at it:

| defect | how it read on screen |
|---|---|
| progress bars filled their cell | a 55px slab of flat colour, not a bar |
| tinted glyphs used `$muted` | three near-invisible ghosts beside one green flame |
| chooser cells hard-clipped | "zpaqfranz missing - runs as E:" - looks like a bug |
| `fmt_percent` rounded 99.6 to 100 | **"100% or better"** - an archive of zero bytes |
| the Extract card's standing blurb | promised a SHA-256 ledger directly above "this one has none" |
| Settings' threads control | "auto (4 cores)" beside a line calling this a two-core laptop |
| the new Peak RAM column | **6.0 GB quoted for a 371 KB job** — it ignored LZMA2's `reduceSize` clamp |

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
5. **A number can be true and still be wrong.** The RAM column's 6.0 GB was
   the correct output of the correct formula — for a dictionary LZMA2 would
   never have allocated on that input. Any figure derived from a *setting*
   has to be recomputed against the *data*, or it is arithmetic rather than
   information.
6. **`verified == 0` needed a companion flag.** "Nothing to check against"
   and "checked, found zero good" are different facts, and one boolean is
   cheaper than discovering the difference in a bug report. Any time a count
   of zero could mean two things, carry the reason beside it.
7. **A route-level summary is not a per-file fact.** `planner.store_reason`
   had said so in its own docstring for months; the listing was the first
   surface to render the joined string per file and make it obviously wrong.
8. **A rounded percentage can become a lie.** `fmt_percent(0.996)` is "100%",
   and "100% or better" promises a zero-byte archive. `gui.suggest._saved_words`
   caps the *wording* at 99% and leaves the estimator's number untouched.
   Anywhere a percentage is rendered near a superlative, check the rounding.
9. **Tinted SVGs need `$text`, not `$muted`.** A muted glyph on `$surface` in
   dark mode is very nearly invisible — the first icon render was three ghosts
   beside one green flame, worse than the emoji it replaced.
10. **"Fill the host" and "size to your hint" are contradictory**, which is why
   the Activity page is deliberately not a `QScrollArea`.
11. **Grep is the wrong tool for "no modals left"** — the comments explaining
   why the modals went name `QMessageBox`. The test tokenises.
12. Word-wrapping QLabels poison QScrollArea sizing; the chooser's
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
