# 🚦 START HERE — handoff (written 2026-09-07)

> **The whole K series is done.** All four confirmed defects from 2026-09-04
> plus a fifth found on the way are fixed, measured and merged. Nothing is
> awaiting review.
>
> **B5 and E1 are done. Start with B4** — the test material is there after
> all (610 FLAC, 110 WAV) and E1 can now fetch the FLAC binary. Section 3.

**1,030 tests: 1,028 pass + 1 skip + 1 strict-xfail.**

The only xfail left is research/23 §2.4's 300px page budget, which §2.4 and
§3.3 contradict each other about - not a to-do. K4's estimator xfail is gone:
it was fixed rather than deferred to B8, see section 2.

```
.venv\Scripts\python.exe -m pytest -q
```

The skip is the 57,020-file corpus walk, ~20 s of drive metadata latency:

```
set EXCMP_SLOW_CORPUS=1
.venv\Scripts\python.exe -m pytest tests\test_manifest_v2.py -q -k 57k -s
```

---

## 0. The working rule, and the thing it caught three times

**Confirm, do not hypothesise.** Every claim here was reproduced on this
machine before it was written down.

The K series produced the sharpest version of this lesson so far, and it is
worth reading before touching the manifest again. **The preflight kept
modelling something other than the artifact it protects** — three times, in
three different ways, across two sessions:

| where | the estimate missed | measured error |
|---|---|---|
| K1, `same_as` | keys `write_container` adds *after* the estimate | 0.758× |
| K1, non-ASCII | `json.dumps` escaping to `\uXXXX`, 6 B per char | 0.55× |
| **K2, `dirs`** | a whole new top-level field | **0.009×** |

The third is the instructive one: K1 had *written the rule down* beside the
constant — "any new ledger key has to be added here" — and K2 followed it to
the letter for `mtime_ns` while adding a second, unbounded field the rule did
not name. A 100-fold under-read, predicted before it was looked for, caught
before the commit.

**So the durable defence is not another constant.** It is the three tests that
now compare the estimate against a *genuinely serialised* manifest
(`test_the_size_estimate_*` in `tests/test_manifest_v2.py`). If you add a
manifest field, add it to those.

### Things that were measured and turned out different from the plan

Five, this session. Full detail in
[benchmarks/2026-09-07-k2-k5](benchmarks/2026-09-07-k2-k5-defects.md):

- K4's "half the size and 2.1× faster" is **49.9% and 1.54×** synthetically,
  **4.40% and no speedup** on two real installer versions, and **0%** in the
  real pipeline, where already-compressed input is routed to `store` and never
  reaches zstd at all.
- K4's "peak working set fell" was wrong in direction: pinned at window 31 it
  **rose** 1,002 → 1,813 MiB. Fitting the window to the input gets the identical
  output for 1,045 MiB.
- K3's fix does not belong where the plan implies (the copy); it belongs in
  `analyze_file`, which opens every file long before the copy exists.
- K2's fix does not belong in the store route; it belongs after MOTW
  propagation, which rewrites the timestamp you just restored.

### Your data is not at risk from the suite — verified, not assumed

Three tests read from the real corpora, read-only, and `tools/corpus_guard.py`
proves it rather than asking you to trust it:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

165 files under `Programs` and `My Graphical Projects`. Clean on every run this
session.

### One process rule, learned the hard way

**Do not run memory benchmarks and the test suite at the same time.** The suite
failed once with `zstd decompress error: Allocation error : not enough memory`
on a *tiny* file; it passes in isolation. The cause was this session's own
1.8 GiB benchmark plus a 642 MiB end-to-end on a 2-core machine. A transient
allocation failure in a compression test is exactly the kind of thing that gets
misdiagnosed as a real defect. Serialise the heavy runs.

---

## 1. What is on `main`

Everything. `main` now carries I3/I8/I10, K1, and K2–K5; nothing is unmerged and
nothing is awaiting review.

The app does: verified byte-identical restore · per-file routing with reasons ·
duplicate-file dedup · split volumes · PAR2 recovery records · AES-256-GCM +
Argon2id encryption with keyfiles · Mark-of-the-Web propagation ·
foreign-archive listing and extraction · convert-and-shrink · plain
`.7z`/`.zip` export · self-calibrating time estimates · persisted history ·
treemap · Ctrl+K · **preserved timestamps and empty directories** ·
**locked files skipped and reported** · **a manifest that scales to a
`node_modules` tree**.

---

## 2. What the K series shipped

| item | what it fixes | proof |
|---|---|---|
| **K1** | a 57k-file folder could not be archived at all | 55,477 files, 71.39% saved, byte-identical |
| **K2** | stored files came back dated today; empty folders vanished | real installers restored to 2023-11-14 and 2025-08-10, exact |
| **K3** | one locked file destroyed the whole job | 5 of 6 archived, the 6th reported by name |
| **K4** | zstd could not see past 128 MiB, and could not *read* wider than it writes | window fitted to input; read ceiling decoupled |
| **K5** | every job touching a `.git` leaked a temp directory | `rmtree_force` at all 11 sites |

Benchmarks: [K1](benchmarks/2026-09-04-k1-manifest-v2.md) ·
[K2–K5](benchmarks/2026-09-07-k2-k5-defects.md).

---

## 3. The next job: B4, and measure the baseline first

**B4 (WAV/FLAC) is ready and I was wrong to call it blocked.** The previous
version of this document said there was no audio on this machine. There is:
`C:\Users\nuhaa\Desktop\Downloads-1` holds **610 `.flac` and 110 `.wav`**,
including a `Songs` folder. The earlier search only looked under the two corpus
folders and `~/Music` and never checked `Downloads-1` itself. No
`.aiff`/`.ape`/`.wv`; no FLAC binary yet, and **E1 can now fetch one** (ask
first - the user wants the site, the size, the hash and the destination before
any download).

### The one rule that matters here

**Measure the existing route before building the specialist.** This has now
been decided by measurement three times, and the specialist lost every time:

| item | proposed specialist | result | the existing lossless route |
|---|---|---|---|
| B3 | `oxipng` | 31.79%, **0/10 byte-identical** | `precomp -> 7z` 38.41% |
| B5 | `qpdf` | 7.14%, **0/10 byte-identical** | `precomp -> 7z` 49.5% |
| K4 | wide zstd window | 49.9% synthetic, **0%** real | unchanged |

**B4 is the one where a specialist plausibly wins outright**, and the reason is
structural rather than hopeful: raw PCM is *genuinely uncompressed*, unlike a
PDF or a docx whose bytes are already deflate output one layer down. FLAC
should beat `precomp -> 7z` on `.wav` by a wide margin.

But two things still have to be measured, not assumed:

1. **The `.wav` baseline.** What does `precomp -> 7z` already get on those 110
   files? That is the number FLAC has to beat.
2. **Byte-identity.** `flac -8` then `flac -d` must reproduce the input
   **exactly**, or it cannot satisfy the ledger and belongs in Phase C like
   `oxipng` and `qpdf`. FLAC is designed to be lossless, so this should hold -
   which is precisely why it should be checked rather than trusted.
   `excmp/jpeg.py`'s `pack()` is the pattern: compress, immediately
   decompress, compare, and store raw if it does not match.

**The 610 `.flac` files are a different job** and worth separating: they are
*already* FLAC, so the question for them is not "can we compress this" but
"does anything beat storing it" - which is where the analyzer currently routes
them, correctly.

---

## 4. Verify before you believe anything here

```
# the K series, each with its own suite
.venv\Scripts\python.exe -m pytest tests\test_manifest_v2.py -q     # K1
.venv\Scripts\python.exe -m pytest tests\test_timestamps.py -q      # K2
.venv\Scripts\python.exe -m pytest tests\test_locked_files.py -q    # K3
.venv\Scripts\python.exe -m pytest tests\test_zstd_window.py -q     # K4
.venv\Scripts\python.exe -m pytest tests\test_tempclean.py -q       # K5
```

If a number here disagrees with what you measure, **trust your measurement and
correct the doc.** That happened nine times across the last two sessions.

---

## 5. Still open, in the order they are worth doing

1. **B4** (WAV/FLAC), **B5** (PDF/Office) — right-sized, test material present
2. **B8** — re-benchmark and replace every `(est.)` with a measurement. No
   longer carries a failing test: K4's estimator gap was **fixed**, not
   deferred here. `_long_range_discount` credits duplicate candidates by exact
   size, which contains the truth without widening the range on selections
   that hold no duplicates. If B8 re-derives `_CODEC_FACTOR["zstd"]` from a
   fresh benchmark, re-check that discount against it rather than assuming it
   still fits
3. **B6** (Oodle/AAA games) — biggest gap, blocked on test material
4. **I6** (compare presets on a real sample), **I7** (translations — the loader
   exists, a `.ts` file does not; **do not invent Dhivehi**, set up the pipeline
   and let the user translate)
5. **I5** (Explorer context menu) — **ask first**, it writes to HKCU
6. **B12** (LOLZ), **C** (video shrink, needs ~90 MB FFmpeg), **D4–D8**,
   **E1–E5** (only if this is ever shared)

### From the tool survey, still unevaluated

`preflate-rs` (Microsoft, Apache-2.0) as a Precomp alternative · `eXdupe 4.0`
for unlimited-distance dedup · **Precomp MP3 support, which is already
installed and switched off** by `_MEDIA` routing · par2cmdline's >2000-file
bug · incremental/versioned archives.

---

## 6. Things not to re-litigate

- **The repo is private and the OSI rule is retired** (2026-09-01). Any tool
  may be used. The lossless guarantee is *more* important as a result, not
  less — several newly-permitted tools are known-unreliable.
- **Never weaken verification to fit a tool in.** The D9 gate caught a broken
  archive on the first codec added after the rules relaxed.
- **zpaqfranz is not tree-capable here**, deliberately — absolute paths, and
  `add` has no relative-path switch.
- **SREP stays out.** Permitted now, but zpaqfranz buys the same points and
  SREP failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **`MAX_MANIFEST_BYTES` is 64 MiB and that number is measured.** Do not trim it
  back on principle; measure again if it must move.
- **`manifest.json` is the one DEFLATED member of the container**, written with
  `ensure_ascii=False`. Both are load-bearing — see section 0.
- **The manifest preflight is deliberately pessimistic** (2.08× on an
  all-stored tree, 1.09× on the real end-to-end job). Refusing a job that would
  have worked is bad; accepting one that cannot finish is the defect K1 exists
  to fix.
- **`verify_restore` does not compare timestamps**, on purpose. Every pre-K2
  archive lacks them, and failing those archives' verification would be far
  worse than a wrong date.
- **The zstd window is fitted to the input, not pinned at 31.** Byte-identical
  output at 29/30/31 on the same corpus, for 769 MiB less memory. The *read*
  ceiling is a separate constant and must stay independent of the write
  setting — that coupling was K4's actual bug.
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done. It has caught defects no test could.
