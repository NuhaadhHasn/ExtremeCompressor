# 🚦 START HERE — handoff for the next session (written 2026-08-01)

> Previous session: **Phase J part 1 (J1-J4, J8) — implemented, tested, on a branch.**
> Next session: **J5-J7** to finish Phase J. Read this file, then
> `docs/ROADMAP.md` → Phase J.
>
> ⚠️ **But read §4 first.** The J8 run turned up two integrity faults (`B11`, `D9`).
> One of them means the engine can publish an archive it cannot restore. Decide
> whether those jump the queue before starting J5 — the argument for doing so is
> the same one that put D0 ahead of everything.

---

## 1. State of the repo

The J1-J4+J8 code is on branch **`phase-j-smart-advisor`**, unmerged, waiting for
review — **two commits**:

| commit | what |
|---|---|
| `9620888` | the estimator, the comparison table, the preflight, the backtest |
| `5675c90` | copy and layout fixes found by rendering the window with real fonts |

```bash
git merge --no-ff phase-j-smart-advisor
```

Docs (`ROADMAP.md`, this file, `docs/benchmarks/2026-08-01-estimator-backtest.md`)
went straight to `main` per the working agreement. `docs/images/` is on the
**branch**, not main, because those screenshots show UI that is not merged yet.

**290 tests pass** (`.venv\Scripts\python.exe -m pytest -q`), up from 223.

Two stale branches remain, both verified **strictly behind** `main` — their only
diff is the absence of files main already has. Safe to delete whenever:
`claude/pyside6-gui-phase-a-f8af25` (remote gone) and `backup/pre-claude-strip`.
Compare trees, never `git log`: Phase A was replayed onto main with fresh SHAs, so
there is no merge base and `git log main..<branch>` proves nothing.
`git diff --stat main <branch>` is the check.

## 2. What shipped

| file | what |
|---|---|
| `excmp/estimate.py` | **new.** `Rates` (injected — the J7 seam), `estimate_size`, `estimate_time`, `compare_profiles`, the "not worth it" flag |
| `excmp/analyzer.py` | `sample_stats()` measures compressibility in the pass that already samples for entropy; `FileInfo` gains `sample_ratio` + `sample_ratio_max` |
| `excmp/engine.py` | `compress_space_needs()` / `_check_compress_space()` — J4 preflight, called from `compress()` |
| `gui/suggest.py` | `profile_comparison()`, `comparison_caption()`, `recommend_with_estimates()`. `recommend_profile()` untouched |
| `gui/widgets/compare_table.py` | **new.** The four-row table, clickable rows |
| `gui/mainwindow.py` | mounts the table between presets and Compress; `_refresh_estimates()`, `_choose_profile()` |
| `tools/estimate_report.py` | **new.** `--backtest` scores the estimator; bare path prints the table without Qt |
| tests | `test_estimate.py`, `test_estimate_backtest.py` (corpus-gated), `test_gui_compare.py`, `test_preflight.py`, plus additions to `test_analyzer.py` / `test_gui_suggest.py` |

## 3. Findings worth not rediscovering

Full evidence: [`docs/benchmarks/2026-08-01-estimator-backtest.md`](benchmarks/2026-08-01-estimator-backtest.md).
The five that would cost the most to relearn:

1. **Estimate from the worst sample, never the mean.** An installer is a
   compressible stub in front of an incompressible payload, so the mean of
   head/middle/tail over-promises. The mean needed a 1.28× fudge that disagreed
   between profiles; the worst sample needs 0.947, stable. Out-of-sample size error
   on the zstd and 7-Zip chains: **+0.07% and −0.60%**.
2. **Sampling cannot predict Precomp, and no cheap probe will.** Two installers,
   near-identical probe readings (entropy 7.78 / 7.52, worst ratio 1.00 / 0.96):
   Precomp found nothing in one, a further ~33 points in the other. Hence
   `SizeEstimate.upper_bound` — for Precomp chains `expected` is a *ceiling* that
   assumes Precomp fails, and `low` reaches 0.30 so the range still contains the
   good case. **Do not "fix" this by tuning a constant.** J7 learning
   `codec_factor` from completed jobs is the only real answer.
3. **A conditional flag must never demote the recommendation.** Overruling the
   heuristic outright was tried and measured: right on the 721 MB corpus, and on a
   163 MB one it demoted Extreme, which then delivered **41.4% against Normal's
   7.3%**. Now it overrules only on an unconditional flag. This is pinned by
   `test_a_conditional_flag_warns_but_does_not_demote_the_recommendation`.
4. **Extreme is not slower per byte than Normal** — measured 2.642 vs 2.616 MB/s.
   With Precomp installed it pipes **431.7 MB where Normal pipes 148.3 MB**, and
   that routing difference is the whole of its extra time. The previous handoff's
   "extreme ≈ 0.9 MiB/s" was Extreme's time divided by Normal's bytes.
5. **The Precomp chain has two throughput regimes**, 2.642 and 0.842 MB/s, chosen
   by the same unknown as #2. No single rate fits both inside ±40%, so J8 gates
   Precomp chains at ±80% and asserts range containment for every chain.

Smaller ones: rates are keyed on the **resolved chain**, not the profile, so a
degraded Extreme predicts what it will really run. ZstdStage's level 19 is *not*
half 7-Zip's speed (within 11% — the earlier figure was a 16 MB-corpus artifact).
The 2026-07-18 benchmark **cannot be backtested** at all: its corpus was a temp
dir and the doc lists no files.

### 3a. Always render the GUI with real fonts before believing it is finished

The J3 table passed 9 pytest-qt tests and was only ever *rendered* headless.
Qt's offscreen platform draws every glyph as a tofu box, so the screenshots
looked fine as geometry and told me nothing about the copy. **`tools/shots.py`
already had the fix and I did not read it:**

```python
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")   # tools/shots.py:31
```

Rendered properly, four defects were obvious in seconds and *not one* was
reachable by a unit test: the same warning printed three times in one panel, the
recommendation reason printed twice, the planner's log sentence leaking into the
UI verbatim, and a collapsed range restating the value above it. All fixed in
`5675c90`.

**So: for any GUI change, run `python tools/shots.py` and look at
`docs/images/01-drop-analysis.png` before calling it done.** It regenerates the
whole set from the real widget tree with real fonts, and it is the cheapest QA in
the repo. Copy assertions were also rewritten to test *meaning* rather than exact
wording, so the next rewording does not break five tests.

## 4. ⚠️ Decide this before starting J5

Two faults found while running J8, both recorded as roadmap items:

- **`B11` — SREP failed a restore, 1 run in 3 over byte-identical input**
  ("checksum of decompressed data is not the same as checksum of original data").
  Intermittent, which is worse than deterministic. SREP was *already* slated for
  removal (not OSI-clean, replaced by B1 zpaqfranz) but `planner._CHAINS` still has
  it, so every Extreme run uses it. Deleting the stage fixes the fault and the
  licence problem at once; the chain becomes `precomp -> sevenzip`, whose estimator
  constants are already shipped.
- **`D9` — `compress()` can publish an archive it cannot restore.**
  `engine._self_test` only tests the *last* stage's container (`7z t`), so a broken
  stage underneath is invisible until extract. That is how the SREP fault got past
  a "success". The extract-time gate did fire, so nothing was silently corrupt —
  but the user was told the archive was good. This **contradicts the stated
  guarantee** ("post-restore SHA-256 comparison is the acceptance gate for every
  stage"), so either the self-test replays the chain or the guarantee gets reworded.
  Replaying doubles Extreme's compress time, so it may need to be opt-in — that is
  the judgement call to make.

My recommendation: **do B11 + D9 first** (they are one session together, and B11 is
mostly a deletion), then J5-J7. Security and integrity before features is the
principle that already put D0 ahead of Phase A's polish. But it is your call, and
J5-J7 is the smaller, more predictable session if you would rather finish Phase J.

## 5. Decisions already made — do not re-litigate

- **Persistence lands as an injected `Rates`**, agreed at the start of this session.
  `excmp/estimate.py` already takes `rates: Rates = DEFAULT_RATES` everywhere, so
  J5/J7 add a thin QSettings-backed implementation and I1's settings page later
  reads the same keys. No QSettings exists yet — J5 or J7 introduces it.
- **J7 records per resolved chain, not per profile.** A degraded Extreme and a Fast
  run identical stages and should share calibration data.
- **`recommend_profile()` stays as it is.** It is the routing judgement and is
  correct on its own terms. `recommend_with_estimates()` layers on top.
- **`estimate.py` returns numbers only.** All prose and rounding live in `gui/`
  (`gui.format.fmt_eta`, `gui.suggest`). `excmp/` must not import `gui/`.
- **No cache in `estimate.py`.** J1 asked for one; nothing needs it, because the
  ratio rides on `FileInfo` and the GUI re-plans from cached `_infos`.

## 6. What J5-J7 actually need

Spec: `docs/ROADMAP.md` → Phase J, items J5, J6, J7.

- **J5** — QSettings map `dominant category -> profile`. Needs the QSettings
  bootstrap (see §5). `AnalysisSummary.ranked_categories()` already gives the
  dominant category.
- **J6** — inline confirm past ~45 min estimated. `estimate_time` already returns
  the seconds. **Inline banner, not a modal** — I9 is removing the one existing
  modal violation; do not add a second.
- **J7** — EMA per chain into QSettings, shipped constants as the cold-start prior.
  `_EngineWorker` already times jobs (`job.elapsed_s`), and
  `estimate_size(...).piped_bytes` gives the denominator. Extend
  `tools/estimate_report.py --backtest` to score before *and* after calibration, or
  there is no evidence it helped.

Known-missed target worth deciding on: **J1's ≤1 s analysis budget is not met** —
300 files took 4.95 s. The new probe is only 0.07 s of that; Shannon entropy's
`Counter.update` is 1.57 s (~53 ms/MiB). `bytes.count()`×256 measured **3× slower**,
so a real fix needs numpy or a C extension. That is a dependency decision for you,
not something to slip in.

## 7. Standing rules (do not relearn these)

- **No AI attribution in commit messages** — no `Co-Authored-By`, no "Generated
  with Claude Code". Public portfolio repo. Audit before committing.
- **Docs-only commits go straight to `main`; code goes on a branch** left unmerged
  for review. Pending files often sit in the **main** checkout even when the session
  runs from a worktree — check `git status` there too.
- **The repo stays 100% OSI-clean** (SignPath signing). Never bundle SREP, lolz,
  oo2core/Oodle DLLs, unrar.dll, or xtool Patreon builds. (SREP is installed
  *locally* on this machine and shelled out to — it must never be redistributed,
  which is half of why B11 deletes the stage.)
- **Target hardware is weak on purpose**: 2-core i7-3540M, 16 GB. Default threads 2.
- **Lossless is a hard guarantee; lossy is always opt-in.**
- **Post-restore SHA-256 comparison is the acceptance gate for every stage** — tool
  exit codes cannot be trusted. See `D9`: we are not currently living up to this on
  the compress side.

## 8. Real test data on this machine

Both on a slow external drive — never run recursive `du`, it times out.

```
C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programs
    Corpus A (6 files, 721,076,752 B) - the D0 acceptance + estimator calibration
    set. Exact file list in docs/benchmarks/2026-08-01-real-programs-folder.md.
    Corpus B (5 files, 163,234,432 B) - the out-of-sample estimator set. Exact list
    in docs/benchmarks/2026-08-01-estimator-backtest.md. Same folder, no overlap
    with A. This is the one that found the Precomp blind spot and the SREP fault.
C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programming Tutorials, Guides, Course, and Files
    deep tree, course material - still untested, likely more compressible. Would be
    a genuinely new out-of-sample corpus for J7.
```

`tests/test_estimate_backtest.py` skips itself unless corpus A is present **at its
recorded byte sizes**, so the suite still runs anywhere.
