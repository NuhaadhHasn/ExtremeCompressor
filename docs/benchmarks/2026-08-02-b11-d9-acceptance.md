# Benchmark: the SREP-free chain and the pre-publish verify gate (B11 + D9)

- Machine: Nuhaadh-Laptop, Intel i7-3540M (2C/4T), 16 GB
- Date: 2026-08-02 (runs started late 2026-08-01 local)
- Code: branch `phase-b11-d9-integrity` (`c6285df` + `d01c8ae`), stacked on
  `phase-j-smart-advisor`
- Reproduce with `scratchpad`-style harness or
  `python tools/estimate_report.py --backtest` after merging.

Two changes landed together and both change what a benchmark *means*:

- **B11**: the Extreme/Insane chain is now `precomp → sevenzip`. SREP is gone
  from everything we create (intermittent restore corruption — 1 failure in 3
  runs over byte-identical input — plus it was closed freeware in an OSI-clean
  repo). Old archives with an srep stage still extract; a test proves it.
- **D9**: `compress()` now fully restores the archive in temp and verifies every
  ledger hash **before** the atomic rename. **"Compress time" in every table
  below therefore includes the verification the user now always waits for.**
  Numbers here are not comparable to pre-D9 tables without splitting the phases,
  which is why both phases are recorded.

## Corpus A — 721 MB installers/archives (6 files, external HDD)

Same files as [`2026-08-01-real-programs-folder.md`](2026-08-01-real-programs-folder.md)
(721,076,752 bytes). Predictions printed before each run.

| profile | piped | predicted size | measured | err | predicted total | measured total | err |
|---|---|---|---|---|---|---|---|
| normal | 148.3 MB | 700,954,821 | 700,884,250 | **+0.01%** | 77.2 s | **103.8 s** (53.5 c + 50.3 v) | −25.7% |
| extreme | 431.7 MB | ≤ 700,142,836 | 699,648,205 | **+0.07%** | 396.0 s | **254.3 s** (197.5 c + 56.8 v) | +55.7% |

Both ranges contained the truth. Extreme's user-side extract+verify: 53.9 s, 6/6
hashes. (Post-recalibration, the shipped rates predict 83.9 s / 420 s for these
runs → −19% / +65%, inside the ±40% / ±80% gates.)

## Corpus B — 163 MB installers (5 files, local disk)

Same files as in [`2026-08-01-estimator-backtest.md`](2026-08-01-estimator-backtest.md).

| profile | predicted size | measured | err | predicted total | measured total | err |
|---|---|---|---|---|---|---|
| fast | 152,146,432 | 152,034,477 | **+0.07%** | 51.8 s | 40.6 s (38.0 c + 2.6 v) | +27.8% |
| normal | 150,418,335 | 151,327,334 | **−0.60%** | 53.8 s | 40.2 s (35.0 c + 5.2 v) | +33.8% |
| extreme | ≤ 149,620,600 | **101,345,044** (37.91% saved) | +47.6% (ceiling) | 101.1 s | 203.3 s (156.8 c + 46.5 v) | −50.3% |

All ranges contained the truth, including Extreme's — the size range's low end
(65.6 MB) was added precisely because the probe cannot see what Precomp will
find, and Precomp found plenty here.

## What dropping SREP actually cost, measured

| | with srep (recorded) | without srep | delta |
|---|---|---|---|
| corpus B saved | 41.39% | 37.91% | **−3.5 points** |
| corpus A saved | 2.97% | 2.97% | none (no cross-file dups) |
| corpus A compress phase | 166.3 s | 197.5 s | **+31 s** |

Two things worth not forgetting: SREP's dedup *shrank 7-Zip's input*, so
removing it costs throughput as well as ratio on dedup-friendly data; and the
price bought the end of an intermittent restore corruption plus one less
non-OSI tool. B1 (zpaqfranz) is the planned way to win the points back.

## What the verify gate costs, measured

| corpus / profile | verify seconds | share of total |
|---|---|---|
| A normal | 50.3 s | 48% |
| A extreme | 56.8 s | 22% |
| B fast | 2.6 s | 6% |
| B normal | 5.2 s | 13% |
| B extreme | 46.5 s | 23% |

Verify throughput is chain-dependent because the gate replays the chain's own
restore: 62.8 MB/s (zstd), 31.4/14.3 (7-Zip), 12.7 vs 3.5 MB/s (Precomp no-op
vs working regime). It is also **cache-noisy**: the identical extract measured
50.3 s inside the gate and 19.9 s user-side minutes later. The model stays
coarse on purpose (per-chain single rates, wide honesty ranges).

Reliability under the new gate: **four Extreme round-trips today (two corpora ×
gate + user extract), every hash verified, zero faults.** The run that motivated
B11 failed 1 in 3.

## Shipped calibration after these runs

| chain | codec MB/s | verify MB/s | evidence |
|---|---|---|---|
| `zstd` | 3.50 | 58 | 3.2 / 3.627 / 3.677 · 62.8 |
| `sevenzip` | 3.38 | 21 | 2.616 / 4.031 / 3.985 / 3.104 · 31.4 / 14.3 |
| `precomp+sevenzip` | 1.41 | 6.5 | regimes 2.218 / 0.891 · 12.7 / 3.5 |

Store-only archives verify at the io rate (copy + hash). All of these remain
cold-start priors for J7's self-calibration; geometric means across every real
measurement, never a single flattering run.
