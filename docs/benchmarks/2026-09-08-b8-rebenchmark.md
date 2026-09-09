# B8 — the re-benchmark, and what it found in the estimator

**2026-09-08**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

B8's brief was "re-benchmark everything on Silesia + a real game folder; update
the README table — this is also what replaces every *(est.)* in the doc 09
comparison table".

The benchmark half went as planned. The estimator half did not: running the
numbers showed **the estimator's range excluded the truth on 3 of 4 profiles**,
and the cause was a constant that had been fitted on one corpus and mistaken
for a property of the codec.

---

## 1. Silesia, all four profiles

12 files, **211,938,580 B**, every restore verified byte-identical.

| profile | chain | archive | saved | compress | restore |
|---|---|---:|---:|---:|---|
| fast | `zstd` | 52,596,355 | **75.18%** | 2.4m | identical |
| normal | `sevenzip` | 48,689,445 | **77.03%** | 2.5m | identical |
| extreme | `precomp → sevenzip` | 46,521,346 | **78.05%** | 8.8m | identical |
| **insane** | `precomp → zpaqfranz` | **41,216,918** | **80.55%** | 16.7m | identical |

**Insane is worth having, and this is the first evidence of it.** B1 measured
it *losing* to Extreme on the installer corpus — 40.77% against 41.75%, at 2.3×
the time — and concluded the CDC dedup had nothing to find once Precomp had
separated five distinct installers. On text it wins by **2.50 points over
Extreme** and 3.52 over Normal. So the honest summary of Insane is not "worse"
or "better" but *"it depends on the data, and here is which way"*: it pays on
compressible, self-similar material and does not on already-compressed blobs.

The time cost is real and worth quoting beside the ratio: 16.7 min against
Extreme's 8.8 for 2.5 points.

---

## 2. The estimator was wrong by 14-19 points, and why

Predicted against measured, before any change:

| profile | est. low | expected | est. high | actual | in range | err |
|---|---:|---:|---:|---:|:--:|---:|
| fast | 21,195,140 | 82,350,995 | 90,071,281 | 52,596,355 | yes | −14.04 |
| normal | 66,102,620 | 81,235,843 | 90,071,281 | 48,689,445 | **NO** | −15.36 |
| extreme | 53,031,141 | 80,721,157 | 90,071,281 | 46,521,346 | **NO** | −16.14 |
| insane | 53,241,801 | 81,493,185 | 90,071,281 | 41,216,918 | **NO** | −19.00 |

`_CODEC_FACTOR` was a single multiplier per chain, all near 1.0, turning the
zstd-3 sample probe into the chain's real ratio. Silesia's implied factors:

```
zstd               probe 0.4047   real 0.2482   implied factor 0.613
sevenzip           probe 0.4047   real 0.2297   implied factor 0.568
precomp+sevenzip   probe 0.4047   real 0.2195   implied factor 0.542
precomp+zpaqfranz  probe 0.4047   real 0.1945   implied factor 0.481
```

**The constant was not wrong so much as it was a measurement of one corpus.**
It was fitted on the 721 MB Programs corpus, which is installers: the probe
reads 0.91-0.97 there, almost nothing is left to compress, and a real chain
*cannot* do better than the probe. Near 1.0 was correct for that data and was
generalised into a property of the chain.

### The fit is anchored by physics, not only by points

At probe = 1.0 the data is incompressible, so no codec can beat the probe and
the factor **must** be 1.0. That is not a fitted parameter, it is arithmetic.
Measuring the installer anchor and drawing a line through both corpora:

```
normal    installers  probe 0.9126 -> factor 0.9465
          silesia     probe 0.4047 -> factor 0.5676
          => factor(r) = 0.2657 + 0.7460 r      at r=1.0 -> 1.0117

extreme   installers  probe 0.9700 -> factor 0.9798
          silesia     probe 0.4047 -> factor 0.5424
          => factor(r) = 0.2292 + 0.7738 r      at r=1.0 -> 1.0030
```

**Two independent corpora produced lines passing within 1.2% of that point
without being told to.** That is the check that mattered — it says the *shape*
is right, not merely that two numbers can be joined.

So the shipped model is the anchored form, `factor(r) = (1 − k) + k·r`, with
`k` from the Silesia anchor and the installer measurement kept as the
cross-check it turned out to be:

| chain | k | predicted at installer probe | measured | anchors |
|---|---:|---:|---:|---|
| `zstd` | 0.650 | — | — | Silesia only |
| `sevenzip` | 0.726 | 0.937 | 0.9465 | two, agree to 1.1% |
| `precomp+sevenzip` | 0.769 | 0.977 | 0.9798 | two, agree to 0.3% |
| `precomp+zpaqfranz` | 0.873 | — | — | Silesia only |

Applied **per file**, at that file's own probe reading, rather than to the
aggregate: a file the probe calls incompressible now gets factor 1.0 and is
predicted not to shrink, and a mixed selection is no longer averaged into one
wrong slope.

### Result

| profile | actual | in range | err before | err after |
|---|---:|:--:|---:|---:|
| fast | 52,596,355 | yes | −14.04 | **+2.63** |
| normal | 48,689,445 | yes | −15.36 | **+2.94** |
| extreme | 46,521,346 | yes | −16.14 | **+3.11** |
| insane | 41,216,918 | yes | −19.00 | **+3.52** |

**1/4 → 4/4 in range**, and the sign flipped to conservative, which is the bias
this file requires throughout. The Programs backtest — the corpus the old
constant came from — passes unchanged.

---

## 3. A six-shape stress matrix, and two fixes that had to be undone

Silesia is one corpus. Six synthetic shapes were built to attack the model
from directions a single corpus cannot. They found three further gaps — and
then rejected the fixes for two of them, which is the more useful result.

| shape | actual saved | verdict |
|---|---:|---|
| A 4×20 MiB text, no duplicates | 76.63% | in range |
| B 30 MiB duplicated across a 120 MiB gap | 67.56% | **out by 7.56 pts** |
| C 20 MiB duplicated adjacently | 49.99% | **out by 50.00 pts** |
| D 3×20 MiB random | 0.00% | out by 2,093 B (0.0017%) |
| E 6×20 MiB random, identical sizes | 0.00% | out by 2,093 B |
| F 40 MiB shared body, 3 different sizes | 87.84% | in range |

### C: fixed, then reverted, because it broke a bigger promise

C is the largest single error in the matrix. 20 MiB of random data duplicated
once was predicted to compress by *nothing* — random bytes route to `store`,
so every ratio in the model is 1.0 — while the real archive came out at exactly
half, because `write_container` writes one copy per SHA-256 and points the rest
at it. The estimator has no term for G9 dedup at all.

The fix credited stored files sharing a size, on the low bound only. It closed
all 50 points. **It also broke the exactness guarantee**: five 10,000,000-byte
videos that are *not* duplicates came out with `low = 10 MB` against a true
50 MB.

"Stored bytes are exact, not estimated" is a documented product property, and
the first test in `tests/test_estimate.py` calls it load-bearing — it is the
one number in this file that is arithmetic rather than prediction. **A
store-only estimate that says "exactly this" and is right is worth more than
one that says "between half and all of it" to cover a case that may not
occur.** So the credit was reverted and `_dedup_credit` survives only as the
docstring explaining why it is unused.

Worth noting this is the *second* time the same proxy has been wrong, for a
different reason each time: against zstd it failed because zstd matches
substrings, so equal length implies nothing. Against G9 the mechanism is
right — G9 really does match whole files — and the **cost** is wrong.

### B: fixed, then reverted, because the common case matters more

7-Zip at mx9 uses a 256 MiB dictionary, which is a long-range window under
another name, and it found the 30 MiB duplicate 120 MiB away. Extending the
long-range floor to `sevenzip` chains brought B into range.

It also set `low` to 10% of the piped bytes for **every ordinary 7-Zip
estimate**. That is a far worse statement in the common case than the miss it
repaired in a rare one: it destroyed the exactness of a uniform file's
estimate, collapsed the distinction between Normal's and Extreme's optimistic
ends, and widened ranges enough to push the Compress page to 447px. Reverted;
the floor stays zstd-only, where K4 made long-range matching a deliberate
feature with the window fitted to the input.

### D and E: the fix was tried and measurement contradicted it

2,093 bytes on a 125 MB archive. `_ZIP_ENTRY_BYTES` was raised 76 → 160 on the
assumption the container was under-booked. Then it was measured:

```
6 ×  2 MiB random:  real overhead 1,429   modelled 1,460
6 × 20 MiB random:  real overhead 1,455   modelled 1,460
```

The model already **over**-books, by 5–30 bytes. The guess was wrong in the
opposite direction and was reverted. The stress harness reports 3,553 bytes of
real overhead for the same 6×20 MiB shape where a direct measurement gives
1,455, which implicates **the harness**, not the estimator — start there.

### So: 3/6, deliberately

B, C and D/E are recorded as known limitations with their measurements. Two of
the three had working fixes that were thrown away because they cost more than
they bought. **The shapes earned their keep by killing fixes, not by
motivating them.**

---

## 4. What could not be measured, and why it stays `(est.)`

Doc 09's comparison table has two rows marked `(est.)` that B8 was supposed to
replace. They **cannot** be, and saying so is the point:

| row | status |
|---|---|
| Older zlib-era game (UE3, indies) | still `(est.)` — no such game folder on this machine |
| Modern Oodle/zstd AAA game | still `(est.)` — **and blocked for the same reason B6 is** |

There is no game with Oodle data here, which is exactly the blocker that keeps
B6 shut. Filling those cells from Silesia would be inventing a number for a
data type that behaves nothing like text, and the whole reason B8 exists is
that a figure carried on plausibility turned out to be wrong by 2×.

**One thing in that table was corrected**: it described our chain as
`precomp→srep→7z`. SREP came out of every chain in B11, on 2026-08-02. The
table had been describing a pipeline that has not existed for a month.

The rows that *could* be measured now have real numbers: mixed personal data
and text are covered by Silesia above, PDFs/Office by
[B5](2026-09-07-b5-pdf-office.md), WAV by [B4](2026-09-07-b4-wav-flac.md), and
installers by the 721 MB Programs corpus.

---

## 5. Reproducing this

```
.venv\Scripts\python.exe -m pytest tests\test_estimate.py -q
.venv\Scripts\python.exe -m pytest tests\test_estimate_backtest.py -q
```

The Silesia corpus is not in the repo (202 MB). The backtest is corpus-gated
and skips where the Programs folder is absent.
