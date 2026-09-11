# B9, G7 and B12 — three items, one afternoon of measuring

**2026-09-11**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).
Peak RAM read from `GetProcessMemoryInfo` on each child process *after* it
exits, so the figure is `PeakWorkingSetSize` for the whole run rather than a
sampled poll that can miss an allocation spike. Harness:
`tools/ram_backtest.py`.

Every one of the three items turned out to be describing something other than
what was actually true.

---

## 1. G7 — the lever was never the dictionary

The roadmap said: *"cap dict/window/threads and spill to temp when RAM is
short"*. Two thirds of that is not available to an extractor. The LZMA2
dictionary is fixed by whoever **created** the archive, and the zstd window
comes out of the frame header — which is exactly what K4's read ceiling is
about. Neither is the extractor's to choose.

The thread count is, and it is worth more than the other two would have been:

| extract flags | peak working set |
|---|---:|
| none — **what shipped** | **255 MiB** |
| `-mmt=1` | **71 MiB** |
| `-mmt=2` | 255 MiB |
| `-mmt=4` | 255 MiB |

**3.6×**, on a 64 MiB-dictionary archive. Each LZMA2 decoder thread holds its
own dictionary buffer, so the flag that looks like a speed knob is really the
memory knob.

Note that `-mmt=2` and `-mmt=4` are identical to no switch at all. Whatever
7-Zip's decoder does with the number, it is not "one buffer per requested
thread" — only `1` changes anything. A formula that tried to predict the
thread count from the core count would have been fitting noise.

### And on this hardware it is free

| extract | peak | run 1 | run 2 |
|---|---:|---:|---:|
| default | 255 MiB | 3.0 s | 2.9 s |
| `-mmt=1` | 71 MiB | **2.7 s** | **2.5 s** |

Single-threaded extraction was *faster*, twice, because on two cores the extra
decoder threads cost more in contention than they win back.

**That is not a reason to make it the default, and it is not claimed as one.**
One corpus, one 2-core machine. An 8-core machine would very likely go the
other way, and generalising a speed result from a single sample is the exact
mistake B8 caught in the estimator. So `--low-memory` is opt-in, and the
honest claim is "costs nothing measurable on the target hardware".

---

## 2. B9 — the formula was not unfinished, it was unreachable

The roadmap said *"only the exact formula is left"*. The formula was already
there and already source-pinned to `CompressDialog.cpp:3016`:
`decompressMemory = dict + 2 MiB`, which is 66 MiB at `-md=64m`.

Measured single-threaded: **71 MiB**. The formula was right all along — for a
*single-threaded* decode. And `build_extract_cmd` passed no `-mmt`, so the
real decode used 255 MiB and **the number the app computed was 3.9× optimistic
against what 7-Zip actually did**, on the one path where optimism costs most:
an archive is extracted on whatever machine it lands on, which is routinely
weaker than the one that packed it.

So B9's "finish the formula" turned out to be **"make the formula's
precondition true"**, which is what G7 now does.

### The compression side under-booked too

| job | model said | measured | ratio |
|---|---:|---:|---:|
| `-md=16m`, mmt=2 | 176 MiB | **198 MiB** | **1.12** |
| `-md=64m`, mmt=2 | 680 MiB | **686 MiB** | **1.01** |
| `-md=192m`, mmt=2 | 2,024 MiB | 2,006 MiB | 0.99 |
| 300 KB input, mmt=4 | 32.7 MiB | 15.8 MiB | 0.48 |

Under-booking is the dangerous direction: it is what lets a job be accepted
that then thrashes.

**The first fix was wrong, and the fourth measurement is what caught it.**
Fitting only the three large rows gives `10.25 × dict + 34 MiB` against the
model's `10.5 × dict + 8 MiB` — which reads like a missing *constant*: the
process, its DLLs, the heap 7-Zip needs regardless, none of which
`CompressDialog` has any reason to count. Adding a flat 32 MiB fixed all
three rows, broke an existing test, and on measurement predicted **64.7 MiB
for a job that measures 15.8** — re-creating the precise failure
`effective_dict` exists to prevent, where a 371 KB job was once quoted 6.0 GB
in the one panel that must never frighten anyone.

The margin is proportional instead (`_SAFETY_MARGIN = 1.15`). Every measured
row now over-books, and a small job stays small:

| job | model now | measured | ratio |
|---|---:|---:|---:|
| `-md=16m` | 203 MiB | 198 MiB | 0.98 |
| `-md=64m` | 782 MiB | 686 MiB | 0.88 |
| `-md=192m` | 2,328 MiB | 2,006 MiB | 0.86 |
| 300 KB input | 37.6 MiB | 15.8 MiB | 0.42 |

**The lesson is the one this project keeps relearning:** a plausible model fitted
to three points, all from the same regime, was wrong in the regime nobody had
sampled. The existing test that broke was right to break.

---

## 3. B12 — LOLZ exists, and I had written down that it did not

**This corrects a conclusion committed earlier the same day.** Having searched
four repack toolsets and found `LOLZ` only in a credits line — `ISDONE, LOLZ,
UELR, MSC (ProFrager)` at `Mini-Compressor/README.md:122` — I recorded in the
roadmap that LOLZ was an installer component, not a codec, and deferred it to
Phase H.

The owner then produced the actual binary. It is a real command-line codec:

```
lolz v22c4b [Dec 30 2018  16:44:58]
```

Compress is `lolz_x64.exe {options} <in> <out>` (confirmed from the shipped
`arc.ini`); decompress is `cls-lolz_x64.exe d <in> <out>`. Adaptive rANS, with
dedicated models for DXT textures and raw graphics, a `-d16..2047` MB
dictionary, and `-mt1..16` / `-mtt0..1` threading.

**Absence of evidence in four repos was not evidence of absence**, and the
roadmap entry stated the stronger claim. Corrected.

### It round-trips, and it is a specialist

Byte-identical on a 3,000,000 B sample:
`92526da991c5cc1e…` both ways.

Same input, same dictionary, `-mx9` against `-d64m`:

| data | 7-Zip mx9 | LOLZ | LOLZ vs 7-Zip |
|---|---:|---:|---:|
| `x-ray` (medical image) | 4,479,879 | **3,945,563** | **+11.93%** |
| `sao` (star catalogue, floats) | 4,413,934 | **4,286,259** | **+2.89%** |
| `mozilla` (binary executable) | 4,993,294 | **4,882,426** | **+2.22%** |
| `osdb` (database) | 2,851,804 | **2,823,379** | **+1.00%** |
| `dickens` (English text) | **871,193** | 896,746 | **−2.93%** |

So the roadmap's unverified "~5-10% over LZMA2 on game data per scene reports"
is now measured, and it is real on the data it was claimed for: **+1.00% to
+11.93% on structured binary, −2.93% on prose.**

That shape matters more than the headline. LOLZ is not "better than LZMA2" —
it is a *per-category specialist*, exactly like B4's FLAC (43% on WAV, useless
elsewhere) and exactly the thing the analyzer's per-file routing already
exists to exploit. It belongs behind a category test, never as a blanket
default.

### What has not been established

- **Nothing bigger than 12 MB has been through it.** These were prefixes.
- **No game data.** Its DXT models are the headline claim and there is no
  Oodle/DXT corpus on this machine — the same gap that blocks B6.
- **Provenance is a forum download.** SHA-256 recorded
  (`ac6730b3041a3a05b62ec6a033e9447f7dc87171751c19704ee10d7eb0093cb6`), 2018
  binary, closed source. It gets the treatment every untrusted stage gets: no
  trust in its exit code, and the post-restore SHA-256 comparison decides
  whether an archive publishes.
- **It was not compared against the real route.** 7-Zip alone is not what this
  app ships — `precomp → 7z` is. Three of four proposed specialists have
  already lost to that chain, and LOLZ has not yet been measured against it.
  That is the next measurement, and it is the one that decides whether any of
  this becomes code.

---

## How to reproduce

```
.venv\Scripts\python.exe tools\ram_backtest.py C:\excmp-bench\silesia --dicts 16,64,192
.venv\Scripts\python.exe -m pytest tests\test_ram_limited_extract.py -q
```

The RAM harness prints both the compression and extraction tables. The LOLZ
figures came from `lolz_x64.exe -d64m` and `7z a -t7z -mx9 -md=64m -mmt=2`
over 12 MB prefixes of the named Silesia members.
