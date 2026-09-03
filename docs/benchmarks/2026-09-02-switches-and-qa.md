# Benchmark: the 7-Zip switches, measured on three corpora (B7 / B9)

- Machine: Nuhaadh-Laptop, i7-3540M (2C/4T), 16 GB, `-mmt2`
- 7-Zip **26.02**, `-mx9`
- Date: 2026-09-02

Both switches were in the roadmap as assertions. Neither had ever been
measured on this machine, and one of them turns out not to be worth what the
plan claimed.

## The table

| variant | 23.5 MB DLLs/EXEs | 163 MB installers | 3.2 MB source+docs |
|---|---|---|---|
| baseline (`-mx9`) | 5,840,099 | 151,290,710 | 2,024,463 |
| `+ -mqs` | −0.026% | **0.000%** | **−0.130%** |
| `+ -mf=BCJ2` | **−1.296%** | +0.000% | +0.043% |
| `+ both` | **−1.353%** | −0.002% | −0.088% |
| `+ -md=192m` | 0.000% | 0.000% | 0.000% |
| `+ -md=192m -mqs` | −0.026% | 0.000% | −0.130% |

## What it means

**`-mqs` is free money and is now always on.** It never cost anything on any
corpus and was worth 0.13% on a source tree. 7-Zip leaves solid type-sorting
**off** by default (research/19 §5), so not passing it was a choice we were
making by accident rather than on purpose.

**`-mf=BCJ2` is real but conditional.** 1.3% on actual executable code; a
slight *loss* on text. So it is applied only when ≥25% of the **piped bytes**
are executables — by bytes, not by file count, because one 50 MB DLL beside a
hundred small text files is an executable job. Note this also shows 7-Zip was
**not** auto-selecting BCJ2 despite mx9 + the MT mixer, which the
documentation suggests it should.

**The roadmap's "5-10% on x86" is not supported.** Measured: **1.3%**. The
item itself flagged that number as benchmark-derived with no source-level
basis, so this replaces it rather than contradicting a source.

**`-md=192m` is worth exactly zero bytes** on all three corpora, and costs up
to 27% more time. It stays reachable as a user knob and stays out of the
defaults. This is the more useful half of the result: a change that looks
obviously good and measures as pure cost.

**Why the installer corpus barely moves at all:** it is 92% *stored*. Almost
nothing reaches 7-Zip, so almost nothing a 7-Zip switch does can matter. That
same fact is what G9 exploited to take that class of data from 5% to 51%.

---

# QA hardening shipped alongside (D1 / D2 / D3)

| item | what | result |
|---|---|---|
| **D1** | Property-based round-trip (Hypothesis) | 3 properties; **120-tree deep hunt found no counterexample** |
| **D2** | Awkward-but-legitimate file matrix | **25 cases, all passed first time** |
| **D3** | Crash consistency under cancellation | 8 cases |

**No bugs were found by any of them**, which is worth stating plainly rather
than dressing up: these classes were simply untested before, and now the
absence of bugs is a measurement instead of an assumption.

D1 states the product's whole claim as one executable property —
`extract(compress(T)) == T` — plus "the input is never modified" and "the
ledger accounts for every file". D2 is the deliberate complement to D0:
`test_safepath.py` pins what we refuse, D2 pins what we must accept, including
Dhivehi and emoji filenames and names that merely *contain* a reserved word
(`CONTENTS.txt`, `console.log`).

**One correction D3 forced.** Its first version asserted `pytest.raises` on a
cancelled job and failed on the Fast profile — because the corpus finished
before the cancel landed. Whether a cancel wins is a race, so the tests now
assert the invariant that holds either way: if the job finished it must have
published a genuinely restorable archive; if it stopped it must have published
nothing. Both are correct outcomes; a partial archive is not.
