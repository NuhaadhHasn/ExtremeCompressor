# I6 — measured preset comparison, and the two defects the render caught

**2026-09-20**, branch `phase-i6-measured-presets`, this laptop
(2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

The roadmap asked for one thing: *"run installed profiles on a ≤100 MB sample
as real queue jobs, print measured ratios onto the preset cards"*. The
implementation is about 400 lines. Almost all of the thinking went into two
questions the one-line spec does not answer — **which bytes** get measured, and
**what the resulting number is allowed to claim**.

---

## 1. What shipped

| piece | what it is |
|---|---|
| `excmp/sample.py` | Qt-free. Picks a representative ≤100 MB subset, and reports what it could not carry |
| `gui/compare_run.py` | Runs one **real queue job** per distinct chain, lands each result as it finishes |
| `gui/suggest.py` | `ComparisonRow` gains the measured fields; `measurement_caption()` |
| `gui/widgets/compare_table.py` | Renders them, speaks them, retitles the column |
| `gui/mainwindow.py` | The **Measure presets** button, the cache, and forgetting it |
| `tools/bench.py` | `--sample [BYTES]`, the same selection from the same module |

`excmp/planner.py` gained one public function, `resolved_chain()`, because the
run needs to know which profiles collapse onto the same stages.

---

## 2. The sample is the measurement

A ratio measured on the wrong bytes is worse than an estimate, because it
arrives with a measurement's authority. Four rules, each a test:

1. **Whole files, never a prefix.** A truncated file's deflate streams are cut
   mid-stream and it does not compress like the file.
2. **Every category present in the input is present in the sample.** 41.9% of
   the Programs corpus routes to `store` and contributes at exactly 1.0.
3. **Proportional to bytes, not to file count.**
4. **Across the size distribution.** `_spread()` is a breadth-first bisection
   over the size-sorted list — median first, then quartiles — so a budget that
   runs out early has still seen small, middling and large.

### Rule 3 cannot always be honoured, and the app says so

Measured on the real Programs corpus (**29 files, 4,992,790,741 B** as of
today — CLAUDE.md's "42 files, 6.4 GB" from 2026-08-07 is stale, the folder is
live):

| category | share of input | share of sample |
|---|---:|---:|
| `executable` | 48.5% | 60.6% |
| `compressed_archive` | **42.4%** | **3.9%** |
| `binary` | 9.1% | 35.5% |

Not a bug in the fill. That corpus keeps 2.1 GB of `.zip`/`.rar` in a handful
of files each larger than the whole 100 MB cap, so **no whole-file subset can
carry 42.4% of the sample.** Forcing the proportions would mean scaling every
other category down to that category's 5% fill rate and measuring 5 MB, which
trades a known bias for a worthless sample.

So the bias is reported — `Sample.under_represented` — and it sets the scope of
the claim the UI is allowed to make:

> Measured on 13 files — 55.7 MB, 1.1% of this input. Archives could not fit
> the sample in proportion, so this ranks the profiles rather than predicting
> the final size.

**A measured comparison ranks the profiles on identical bytes. It does not
forecast the job.** The estimate columns still do that, and a test asserts the
measurement never moves the recommendation.

### A defect in the first version, found by running it

The first sampler did the proportional pass first and only forced a missing
category in afterwards. On Silesia at a 20 MB cap that picked **2 of 12 files,
left 4 MB of budget unspent, and reported `executable` as missing** — when its
one 6.2 MB member would have fitted easily. The big categories had already
spent the budget.

Reserving one file per category *first*, cheapest first, fixes it:

| corpus | before | after |
|---|---|---|
| Silesia, 20 MB cap | 2 files, 15.9 MB, 79% of cap, `executable` missing | **3 files, 18.7 MB, 94% of cap, nothing missing** |
| Programs, 100 MB cap | 13 files, 55.7 MB | unchanged (the `.zip` files genuinely do not fit) |

---

## 3. Real queue jobs, and one job per *chain*

Not a private code path. The comparison enqueues through the same
`QueueManager`, so the jobs appear in Activity, show progress, cancel the same
way, and are extracted and SHA-256 verified before publication like every other
archive. A number produced by a path the product does not otherwise run is a
number about that path.

Two consequences, both deliberate:

- **One job per resolved chain, not per profile.** With Precomp absent, Extreme
  resolves to exactly Normal's stages; measuring both would spend twice the
  time to print one figure twice and invite the reader to believe they were
  independent. `resolved_chain()` groups them and every profile in a group
  reads the one result.
- **Each profile lands the moment it finishes.** Cancelling after two of four
  leaves two measured cards and two estimated ones, which is the honest state.

The archives are deleted as soon as their byte count is recorded — the number
was the product, not the file.

### Verified end to end, not mocked

`test_a_real_comparison_run_measures_real_archives` runs a live
`QueueManager` over 980,000 B of repetitive text:

| profile | archive | saved |
|---|---:|---:|
| Fast (zstd) | **960 B** | 99.9% |
| Normal (7-Zip) | 1,057 B | 99.9% |

**Note the direction: zstd beats 7-Zip here**, because at a kilobyte the `.7z`
container costs more than the codec saves. That is a real result, and it is why
the test asserts the two numbers *differ* rather than asserting that the
stronger profile wins. "The stronger profile wins" is an assumption, and
measuring it instead of assuming it is the entire point of I6.

---

## 4. Two defects the suite could not see

Both were found by `tools/qa_sweep.py` and looking at the PNG — which is the
fourth time in this project's history that has been the thing that caught it.

### (a) One row, two numbers that disagreed

The first render showed, in a single row: `Estimated size: about 225.9 KB` and
`Saved: 61% measured`. 61% of 371.5 KB is 144.9 KB. Two numbers in one row,
contradicting each other, both presented as facts about the same job.

Fixed by letting the measured archive size take the size column **only when the
sample was the whole input** — because then it is not a projection, it is the
answer. On a genuine subset the estimate keeps the column, since scaling a
sample's archive up to the folder's size would be an estimate wearing a
measurement's clothes.

### (b) A column titled "Estimated size" showing a measured size

Consequence of fixing (a). The header is now adaptive: it reads **"Size"** when
a measured size is in it, `"Estimated size"` otherwise. Only that column
changes — "Saved" was already neutral, and "Estimated time" stays estimated
because a sample's stopwatch says nothing about the whole job's duration.

### Still a reading hazard, stated rather than fixed

An unmeasured Precomp row reads `≤ 1.1 KB / 99% or better`, which *looks*
better than a measured `144.9 KB / 61%` beside it. That is the pre-existing
upper-bound wording (J8) doing its job — the estimate genuinely is a ceiling —
and the remedy is to measure that row too, which is what the button is for. Not
worth inventing a fifth kind of hedge for.

---

## 5. What a comparison costs, and what it touches

- **Four sequential compressions.** The queue pool is capped at one job by
  design, so a user's own Compress will queue behind a running comparison.
  The button becomes **Stop measuring** while it runs.
- **It feeds calibration.** `CompressWorker._calibrate()` runs on every
  finished job including these, so J7 learns from them. Left deliberately:
  they are real jobs on the user's real data, which is exactly what
  calibration wants.
- **It feeds history**, if the user clicks Clear finished. Same argument.
- **Over-cap inputs ask first.** When the smallest file is larger than the cap
  there is no small sample to take, so the banner says so with the real size
  and the number of runs, and waits.

---

## 6. `tools/bench.py --sample`

The same selection from the same module, so a number in a benchmark doc and a
number on a card mean the same thing. Measured today, Silesia at a 20 MB cap:

```
analysing C:\excmp-bench\silesia to choose a <= 19.1 MB sample ...
  3 of 12 files, 17.9 MB of 202.1 MB (8.8%)
```

| profile | original | compressed | saved | compress | extract+verify |
|---|---:|---:|---:|---:|---:|
| fast | 17.9 MB | 7.7 MB | 57.1% | 17.0s | 0.6s |
| normal | 17.9 MB | 6.6 MB | 63.1% | 8.8s | 1.2s |
| extreme | 17.9 MB | 6.6 MB | 63.1% | 11.9s | 1.8s |

Extreme ties Normal because Precomp finds nothing in raw Silesia — there is no
deflate in it to reconstruct. The disclosure lines print whenever the sample
drops or starves a category, and they print into the written markdown too.

---

## 7. Reproducing it

```
.venv\Scripts\python.exe -m pytest tests\test_sample.py tests\test_i6_measured_presets.py -q
.venv\Scripts\python.exe tools\bench.py C:/excmp-bench/silesia --sample 20000000
.venv\Scripts\python.exe tools\qa_sweep.py --out shots
```

`shots/*-05b-presets-measured.png` is the surface this document is about, in
both themes.
