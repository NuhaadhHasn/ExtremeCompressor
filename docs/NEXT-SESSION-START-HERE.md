# 🚦 START HERE — handoff (written 2026-09-07)

> **The whole K series is done.** All four confirmed defects from 2026-09-04
> plus a fifth found on the way are fixed, measured and merged. Nothing is
> awaiting review.
>
> **B5 is partly done and B4 is blocked** — read section 3 before picking
> anything. The next job is either finishing B5's qpdf question or B8.

**1,010 tests: 1,008 pass + 1 skip + 1 strict-xfail.**

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

## 3. Where B4 and B5 actually stand

**B4 (WAV/FLAC) is BLOCKED, and the previous version of this document was
wrong about it.** It said B4 and B5 both had test material on this machine.
Checked 2026-09-07: there is **no `.wav`, `.flac` or `.aiff` anywhere** — not
in either real corpus, not in the user profile — and no FLAC binary. Treat B4
like B6: it needs real audio before it is worth opening, because B3 is the
standing proof that a specialist judged on synthetic files tells you nothing.

**B5 is partly done, and it was not the job the roadmap describes.** Full
numbers: [benchmarks/2026-09-07-b5](benchmarks/2026-09-07-b5-pdf-office.md).

Measured on 238 real PDF/Office files, the baseline came first and reframed
everything:

| profile | chain | saved |
|---|---|---:|
| Normal | `7z` | 10.37% |
| Extreme | `precomp → 7z` | **50.36%** |

PDF/docx/xlsx/pptx were **already piped**, and Precomp already does 4.9x what
plain 7-Zip does. The defect was that the **estimator** predicted 13.78% for
Extreme, so `compare_profiles` showed it beating Normal by 4 points where the
truth is 40 — steering users past half their compression. Now 46.32%.

The fix is `analyzer.probe_expandable`, and the *reason* it has to be a probe
is the part worth not re-deriving: an extension list would have predicted a
large win on the 263 MB **encrypted** `.zip` that is 37% of the estimator's own
backtest corpus and measured 2.97%. Two real corpora, same extension, opposite
answers.

### What is left of B5

**qpdf is unmeasured**, and there is no binary on this machine. The prediction
is that it fails the lossless gate exactly as `oxipng` did in B3 —
`--recompress-flate` rewrites the file, and a SHA-256 ledger cannot be
satisfied by changed bytes — in which case it belongs in Phase C beside C6,
not here. It also has to beat **50.36%** to be worth having at all. Measure
before building.

**"Unpack docx members into the solid stage" is already achieved** by Precomp
for Extreme/Insane. Doing it explicitly would help only profiles *without*
Precomp, and would need B2's pack-immediately-unpack-compare-fall-back pattern
to stay byte-lossless, because rebuilding a zip bit-exactly is not guaranteed.

**So the honest next jobs are B8** (re-benchmark; the B5 work just replaced one
`(est.)` with a measurement and there are more) **or B5's qpdf question**, and
either wants a tool fetched first — which is E1.

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
