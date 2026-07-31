# Benchmark: scoring the Phase J estimator (J1/J2/J8)

- Machine: Nuhaadh-Laptop, Intel i7-3540M (2C/4T), 16 GB
- Date: 2026-08-01
- Tools present: 7-Zip, Precomp, SREP. No zpaqfranz (so Insane runs the Extreme chain).
- Regenerate the scoring table with `python tools/estimate_report.py --backtest`;
  regenerate a prediction for any path with `python tools/estimate_report.py <path>`.

Purpose: an estimator nobody scored is a guess with a progress bar. Two corpora
are used, and **which is which matters more than any number below**:

| corpus | role | why |
|---|---|---|
| **A** — 721 MB installers/archives | **in-sample** | the shipped size factors were fitted on it; a check against it is a regression guard, not evidence |
| **B** — 163 MB installers | **out-of-sample** | predictions were recorded *before* it was ever compressed |

**All sizes below are decimal MB (10^6).** Note `tools/bench.py` and the GUI's
`fmt_size` print 1024-based units labelled "MB", so their figures read ~4.9%
smaller than the ones here. Byte counts are given wherever it matters.

---

## Corpus A — in-sample (the calibration set)

Same six files as
[`2026-08-01-real-programs-folder.md`](2026-08-01-real-programs-folder.md), from
`Downloads-1\PalluVaapaHDD\0No Need To Check\Programs`. Total **721,076,752 bytes**.

| file | bytes | entropy | mean ratio | worst ratio |
|---|---|---|---|---|
| `R-4.5.1-win.exe` | 90,111,968 | 7.78 | 0.8231 | 1.0000 |
| `Windows-KB890830-x64-V5.129.exe` | 76,629,432 | 7.93 | 0.9594 | 1.0000 |
| `lghub_installer.exe` | 58,146,712 | 6.51 | 0.4411 | 0.7772 |
| `DB.Browser.for.SQLite-v3.13.0-win64.msi` | 19,783,680 | 7.99 | 0.9690 | 1.0000 |
| `Winxvideo.AI.3.5.0.0.w64.rar` | 212,734,622 | 8.00 | 1.0000 | 1.0000 |
| `Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip` | 263,670,338 | 8.00 | 1.0000 | 1.0000 |

### The routing correction that changes everything downstream

The previous handoff derived Extreme's throughput from Normal's routing. That was
wrong, and it mattered:

| profile | piped bytes | stored bytes |
|---|---|---|
| fast / normal | 148,258,680 (20.6%) | 572,818,072 |
| **extreme / insane** | **431,712,698 (59.9%)** | 289,364,054 |

With Precomp installed, the `.zip` and the `.msi` get the Precomp override and
move into the pipeline. So Extreme pipes **2.9× more bytes** than Normal, and:

- Extreme's real codec rate is **2.642 MB/s**, not the 0.9 MiB/s previously
  recorded — that figure came from dividing Extreme's *time* by Normal's *bytes*;
- **Extreme is not slower per byte than Normal** (2.642 vs 2.616 MB/s here). Its
  extra 104 seconds are entirely explained by routing 283 MB more data through the
  chain on the chance Precomp could open it. It could not.

That is a better explanation of the phase's motivating fact than "Extreme is
slow", and the two-rate model reproduces it structurally.

### Recovering the truth the estimator has to hit

Stored bytes are copied verbatim, so every saved byte came from the piped set:

| profile | measured saved | ⇒ piped chain ratio |
|---|---|---|
| normal | 2.80% of total = 20,190,149 B | **0.8638** |
| extreme | 2.97% of total = 21,415,980 B | **0.9504** |

### Why the estimate follows the *worst* sample, not the mean

The single most useful measurement of this phase. Predicting the piped chain
ratio from a zstd-3 probe of the analyzer's existing samples:

| predictor | predicted ratio | correction factor needed |
|---|---|---|
| mean of the samples | 0.6733 | **1.283** (normal) / 1.071 (extreme) |
| **worst single sample** | 0.9127 | **0.947** (normal) / 0.980 (extreme) |

The mean needs a large fudge factor that *disagrees between profiles* — the sign
of a broken model. The worst sample needs a correction near 1.0 that is stable,
which is the sign the structure is right.

The cause is visible per sample. `R-4.5.1-win.exe` reads head 0.469, middle 1.000,
tail 1.000: a compressible stub in front of an incompressible payload — the shape
of every installer. The mean believes the stub; the worst sample resembles the
bulk, which is what actually drives the archive. When head/middle/tail agree (a
uniformly compressible file, or any file under 3 MiB where there is only one
sample) the two are identical and no correction applies.

### Scored, in-sample

| profile | measured | predicted | err | measured time | predicted | err | range holds? |
|---|---|---|---|---|---|---|---|
| normal | 700.9 MB | 701.0 MB | **+0.01%** | 62.4 s | 51.4 s | −17.7% | yes |
| extreme | 699.7 MB | 700.0 MB | **+0.05%** | 166.3 s | 292.4 s | +75.9% | yes |

Size is near-exact **by construction** — do not read it as accuracy. The
honest content of this table is that one model structure fits both profiles with
correction factors of 0.947 and 0.980, and that both ranges contain the truth.

---

## Corpus B — out-of-sample (the real test)

Five different files from the same folder, copied to local disk. Total
**163,234,432 bytes**. Predictions were printed and recorded *before* compressing.

| file | bytes | entropy | mean ratio | worst ratio |
|---|---|---|---|---|
| `BlueScreen microsoft.zip` | 63,833 | 7.98 | 1.0000 | 1.0000 |
| `Composer-Setup.exe` | 1,804,192 | 6.79 | 0.4699 | 0.4699 |
| `HandBrake-1.8.2-x86_64-Win_GUI.exe` | 23,779,832 | 8.00 | 0.9942 | 1.0000 |
| `Intel-HD-and-HD-4000-Graphics-Driver_KK9J0_WIN_10.18.10.5059_A20.exe` | 136,899,248 | 7.52 | 0.7471 | 0.9648 |
| `RAMMap.zip` | 687,327 | 7.99 | 1.0000 | 1.0000 |

Routing: fast/normal pipe 138,703,440 B; extreme pipes 139,454,600 B.

### Result, as predicted before the run

| profile | predicted size | measured size | **size err** | predicted time | measured time | **time err** |
|---|---|---|---|---|---|---|
| fast | 152,146,432 | 152,034,477 | **+0.07%** | 108.6 s | 38.5 s | +182% |
| normal | 150,418,335 | 151,327,334 | **−0.60%** | 53.3 s | 34.7 s | +54% |
| extreme | 149,487,669 | **95,678,980** | **+56.2%** | 53.0 s | 165.8 s | −68% |

**Size prediction on the non-Precomp chains is excellent: +0.07% and −0.60% on
data the model had never seen.** That is the worst-sample method working.

The two failures are both real and both instructive.

**1. Precomp cannot be predicted from samples.** Extreme delivered 41.4% saved
where 8.4% was predicted. Precomp found deflate streams *inside* the Intel driver
installer; a zstd probe reads raw bytes and cannot see structure. The damning
detail is that this file is **probe-indistinguishable** from corpus A's
`R-4.5.1-win.exe`, where Precomp found nothing:

| file | entropy | worst ratio | Precomp's actual yield |
|---|---|---|---|
| `R-4.5.1-win.exe` (A) | 7.78 | 1.0000 | ~nothing |
| `Intel-HD…A20.exe` (B) | 7.52 | 0.9648 | a further ~33 points |

No cheap signal separates them. This is recorded as a **limitation, not a bug**.

**2. The Precomp chain has two throughput regimes.** 2.642 MB/s when Precomp finds
nothing and streams through; **0.842 MB/s** when it does find something and the
inflated data lands on SREP and LZMA2. A 3.1× spread, selected by the same unknown
as above.

### What was changed in response, and what it cost

Time rates were re-derived as geometric means of *every* measurement, rather than
trusting one run:

| chain | before | after | from |
|---|---|---|---|
| `zstd` | 1.28 MB/s | **3.407** | 3.2 (2026-07-18) and 3.627 (B) |
| `sevenzip` | 2.616 MB/s | **3.247** | 2.616 (A, external HDD) and 4.031 (B, local disk) |
| `precomp+srep+sevenzip` | 2.642 MB/s | **1.491** | 2.642 (A, no-op) and 0.842 (B, working) |

Post-retune time errors: normal −17.7% (A) and +23.6% (B); fast +6.8% (B) — all
inside ±40%. The Precomp chain is ±76% / −43% and **cannot be brought inside ±40%
by any single rate**, so `tests/test_estimate_backtest.py` gates it at ±80% with
the reason written down rather than quietly widening the number.

Corpus B's *time* measurements are now in-sample too. Its *size* results
(+0.07%, −0.60%, +56.2%) remain genuinely out-of-sample — nothing about the size
model was changed in response to them except the low bound.

Two model changes followed, both about not lying:

- **`expected` for a Precomp chain is a ceiling, not a prediction** — it assumes
  Precomp finds nothing. `SizeEstimate.upper_bound` says so and the UI prints
  "≤ 142.6 MB" and "8% or better", never "about".
- **`low` for a Precomp chain reaches down to 0.30** so the range contains the
  case where Precomp works. Before this, corpus B's measured 95.7 MB fell
  *outside* the predicted range, and a range that excludes the truth is worse than
  no range at all.

### An earlier design that measurement killed

The estimate-aware recommendation originally **overruled** the routing heuristic
whenever it flagged a bad trade. On corpus A that is right (Extreme wasted 104
seconds). On corpus B it demoted Extreme — which then delivered **41.4% against
Normal's 7.3%**. Overruling there would have cost the user 34 percentage points to
save two minutes.

So the rule is now: overrule only on an **unconditional** flag; when the flag
depends on Precomp's unknowable yield, keep the recommendation and show the
condition on the row. The roadmap asked for a bad trade to be *visible before it
is paid for* — visible, not silently avoided on evidence we have labelled unknown.

---

## Two findings that are not about the estimator

### SREP failed a restore, intermittently — 1 run in 3

On the first Extreme run over corpus B, `srep64.exe` exited 4 during **extraction**:

```
ERROR! Decompression problem: checksum of decompressed data is not the same
       as checksum of original data
```

Two later runs over byte-identical input restored 5/5 files with all hashes
verified. So it is intermittent, which is worse than deterministic.

Two things this exposes, neither of them Phase J's to fix:

1. **`compress()` published an archive it could not restore.** `engine._self_test`
   tests only the *last* stage's container layer (`7z t`), so a broken SREP layer
   underneath is not detected until someone extracts. The engine did fail loudly at
   extract time — the integrity gate worked — but the archive had already been
   reported as a success.
2. **The Extreme chain still runs SREP**, which the source study already decided to
   drop (`research/20` §4, `research/21` §5: not OSI-clean, replaced by zpaqfranz
   long-range dedup). `planner._CHAINS` has not caught up with that decision.

### The J1 analysis cost budget is missed, but not by the new probe

J1 budgeted ≤1 s for a few hundred files. Measured: **300 files / 20.2 MB in
4.95 s** (16.5 ms/file). Attribution, measured separately:

| cost | per 300 × 120 KB |
|---|---|
| `Counter.update` for Shannon entropy (**pre-existing**) | 1.57 s |
| new zstd-3 compressibility probe | **0.07 s** |

The probe is ~1.4% of analysis time — the budget was already unmet by entropy
sampling at ~53 ms/MiB. The obvious stdlib alternative is worse:
`bytes.count()` × 256 took **167 ms/MiB against `Counter.update`'s 53 ms** (3×
slower, identical entropy to 10 decimal places). A real fix needs `numpy` or a C
extension, i.e. a dependency decision, so nothing was changed here.

---

## Shipped constants

`excmp/estimate.py`, keyed on the **resolved chain** rather than the profile name
— so an Extreme that silently degrades to zstd for want of Precomp predicts what
it will really do:

| chain | codec factor | rate (MB/s) | time spread |
|---|---|---|---|
| `zstd` | 0.960 | 3.407 | 2.0× |
| `sevenzip` | 0.947 | 3.247 | 2.0× |
| `srep+sevenzip` | 0.944 | 3.10 | 2.0× |
| `precomp+sevenzip` | 0.942 | 1.55 | 3.2× |
| `precomp+srep+sevenzip` | 0.940 | 1.491 | 3.2× |

`io_rate` = 100 MB/s for verbatim copies. The model is insensitive to it: moving
it to 60 MB/s shifts the derived codec rates by ~7%.

These are a **cold-start prior**, not a truth. Corpus A and corpus B disagreed by
2.5× on 7-Zip's throughput alone, purely because one lived on an external HDD.
J7's self-calibration — recording real throughput per completed job and blending
it in — is the actual answer, and `Rates` is an injected argument so it can be
dropped in without touching the model.
