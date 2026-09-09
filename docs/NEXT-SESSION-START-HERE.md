# 🚦 START HERE — handoff (written 2026-09-09)

> **D8 is done, and the defect was in the half that already existed.** The
> publish path had a `.tmp` twin, a rename, and since D9 a full verified
> restore in front of them — and it still deleted the destination *before*
> renaming onto it. A failure at that one step left the user with neither
> yesterday's archive nor today's. Fixed, measured, pinned.
>
> **Next phase: D7 (CI on `windows-latest`).** Section 3 has the one decision
> to make before starting it, because D7 is the first item in this project
> whose acceptance gate does not live on this machine.

**1,077 tests: 1,074 pass + 2 skip + 1 strict-xfail.** (+18 from D8.)

```
.venv\Scripts\python.exe -m pytest -q
```

Two things about that command, both learned this session:

- **A clean full pass took 1 h 07 m**, measured 2026-09-09, not the few
  minutes the count suggests — and `pytest -q` buffers everything when stdout
  is not a terminal, so it looks hung for the whole hour. Check it is alive
  with `Get-Process python | Select Name,Id,CPU` rather than waiting on
  output. (An earlier 31-minute figure was a run where two tests failed early
  on ENOSPC and never did their work — see below.)
- **Serialise it against any benchmark.** Still true, still the rule from the
  K series: a 2-core machine running both produces allocation failures in
  compression tests that look exactly like real defects.
- **Clear `%TEMP%\pytest-of-nuhaa` before a run.** Measured this session: the
  suite leaves **400-770 MB per run** there and pytest keeps the last three,
  and an *aborted* run leaves its tree behind on top of those. Four leftovers
  had eaten 2 GB, `C:` fell to 0.92 GB free, and the suite failed with
  `OSError: [Errno 28] No space left on device` inside
  `tests/test_zstd_window.py` — which reads exactly like a real defect in the
  K4 window code and is not one. All 13 passed on a re-run with space free.

The only xfail left is research/23 §2.4's 300px page budget, which §2.4 and
§3.3 contradict each other about — not a to-do. The skip is the 57,020-file
corpus walk (`set EXCMP_SLOW_CORPUS=1`).

---

## 0. What is on `main`, and what is not

`main` carries everything through B8. **`phase-d8-atomic-publish` is the one
branch awaiting review**:

```
git merge --no-ff phase-d8-atomic-publish
```

The docs commit (this file, the ROADMAP tick, the benchmark) went straight to
`main` per the working agreement; the code is on the branch.

---

## 1. What D8 shipped

New module `excmp/atomic.py` — `publish()`, `atomic_write_text/bytes()`,
`fsync_file()`, `hash_and_size()` — now behind **every** output the program
writes: both archive publishes (`.excmp` and the plain `.7z`/`.zip` export),
both sidecars, the volume parts, the calibration store and the history file.

| what | before | after |
|---|---|---|
| durability | `os.replace` only, bytes still in the OS cache | `fsync` **then** rename |
| verification | nothing re-read the artifact | SHA-256 read back off the filesystem after the flush |
| the destination | `unlink()` then `replace()` — a window with neither file | `os.replace` alone, which overwrites atomically |
| the digest | the sidecar re-read the whole archive | the read-back's digest, in `CompressResult.sha256` |

**Measured cost, Silesia/normal** (48.7 MB archive, 116 s job, full numbers in
[benchmarks/2026-09-09-d8](benchmarks/2026-09-09-d8-atomic-publish.md)):

- flush **5.3 ms**, read-back **266.5 ms** (182.7 MB/s) → **0.234%** of the job
- **0.0046% with `--sidecar`**, because the read-back replaces a hash the
  sidecar was already paying for
- the volumes sidecar got **13.9× cheaper** (218.2 ms → 15.7 ms), because
  `split_file` now records each part's digest from the bytes it writes

Restore verified 12/12 byte-identical.

---

## 2. Four findings worth not rediscovering

### The archive is not byte-reproducible, and that is by design

B8 recorded Silesia/normal at 48,689,445 B. This session measured
**48,689,446** — one byte, on the corpus that exists to make comparisons
possible. It took three measurements to close:

1. The container is `manifest.json` (2,299 B raw, ~1,005 deflated) plus
   `payload.7z` (48,688,221 B, **stored**) plus 220 B of zip overhead. All the
   compression is in the payload.
2. Substituting only `created_utc` moves the deflated manifest by up to 3
   bytes. Sweeping all 86,400 timestamps of 2026-09-08: **67 of them deflate
   to exactly 1,004 B, giving exactly B8's 48,689,445.**
3. Two runs today: same total, same payload size, **different payload CRC32**
   (`f516777a` vs `5f4ddd7c`). 7-Zip's output here is length-deterministic and
   not byte-deterministic.

**So: compare payload size, never the archive digest, across benchmark runs.**
A few bytes of difference is a clock. Payload size is the number that means
something and it was not being recorded before this session — record it.
`result.sha256` is the identity of one file for verification, **not** a build
fingerprint.

### An `fsync` costs what the file's *recency* costs, not its size

| file | bytes | fsync |
|---|---:|---:|
| the archive | 48,689,446 | 5.3 ms |
| its 80-byte sidecar | 80 | **26.3 ms** |

The archive's pages had been draining to disk for two minutes; the sidecar was
milliseconds old and paid the whole barrier. Do not reason about where a flush
is "too expensive" from file size.

### A check can be mechanically vacuous in one branch and load-bearing in the other

The first version of D8 hashed the archive after the D9 gate and passed that
digest to `publish` for the read-back to compare — two full passes to compare a
file with itself, since nothing runs between them and Python raises on a full
volume rather than short-writing. Removed: it would have doubled D8's cost for
zero detection.

The identical check is kept **with a password**, where a second pass really
does read the plaintext out of temp and write a different file. `encrypt_file`
now takes `expect_src_sha256` (free — it streams those bytes anyway) and
reports the ciphertext digest, which the publish read-back verifies. That
closed a hole nothing had covered: **the D9 gate proves a plaintext restores,
and what ships is a ciphertext produced afterwards by something the gate never
saw.**

This is B8's rule from the other side. B8: a mechanically *correct* proxy can
cost more than it buys. D8: a check can be *mechanically empty* in one branch
while being essential in the branch beside it, and the resemblance between the
two is exactly what makes it look uniformly worthwhile.

### Adding a check to a path adds a failure mode to it

Caught by auditing the finished work, not by the suite. `calibrate.record()`
and `history.append()` both promise **never to raise** — they run after a job
has already succeeded — and both caught `(OSError, ValueError, TypeError)`.
`PublishError` is a **RuntimeError**, so D8's own read-back had quietly given a
finished job a new way to be reported as failed. Two tests now pin it
(`*_never_raises_on_a_bad_readback`).

The write site was the obvious thing to review; the callers catching **by
exception type** were the thing that actually broke. If you route another
write through `excmp.atomic`, re-read what its caller catches.

---

## 3. The next phase: D7 — CI on `windows-latest`

`docs/ROADMAP.md` D7: GitHub Actions `windows-latest` (7-Zip preinstalled),
matrix Python 3.11–3.13, `setup-python` pip cache, SHA-keyed tool cache, badge
in README.

### The one question to settle first

**D7 is the first item whose acceptance gate is not on this machine.** A
workflow file that has never run is not evidence of anything, and this
project's rule is not to write down a behaviour that has not been reproduced.
Proving it means **pushing the branch to GitHub and reading the run** — an
outward-facing action on a private repo that also spends Actions minutes.

So decide at the start: **push the D7 branch to see it run, or land it
unproven with that stated in the commit message?** If the answer is "not
yet", do **E2** instead (below) — it is docs-only, needs nothing off this
machine, and is the item that has become *more* necessary rather than less.

### Things already known about D7

- 7-Zip is preinstalled on `windows-latest`, so the core suite can run without
  `toolfetch`. Precomp, zstd, zpaqfranz and `flac` are not — E1's hash-pinned
  fetcher exists and its cache key should be the `exe_dir_sha256` already in
  source, not a version string.
- **Three tests read the user's real corpora** and must be skipped or gated in
  CI; they are already corpus-gated, but confirm that the gate is an
  environment check and not a path that happens to be absent.
- The suite takes **1 h 07 m** here on 2 cores. A 3-version matrix will not
  fit comfortably in one job each — GitHub's default job timeout is 6 h, but
  three hour-long jobs per push is a lot of minutes on a private repo.
  Consider splitting the slow tests behind a marker and running the full set
  on a schedule rather than on every push.
- `tools/corpus_guard.py` has nothing to guard in CI and should not run there.

### After D7, in order

**E2** — THIRD-PARTY-NOTICES.md. Genuinely needed now: E1 downloads GPL
`flac` and Apache `qpdf`. Docs-only, straight to `main`.
**D4** — disk-full simulation on a VHDX/`subst` volume. D8 raised its value:
`publish()`'s short-write refusal has a unit test but has never met a real
ENOSPC, and **C: has 2.9 GB free**, so a VHDX is the only way to test it
without endangering the machine.
**I6** — "compare presets on this input"; the estimator is trustworthy enough
since B8 to make it honest.

---

## 4. Verify before you believe anything here

```
.venv\Scripts\python.exe -m pytest tests\test_atomic_publish.py -q   # D8, 18 tests
.venv\Scripts\python.exe -m pytest tests\test_publish_gate.py -q     # D9
.venv\Scripts\python.exe -m pytest tests\test_volumes.py -q          # G3 + both sidecars
.venv\Scripts\python.exe -m pytest tests\test_crypto.py -q           # F1/F2
```

And your data is not at risk from the suite — verified this session, not
assumed:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

165 files under `Programs` and `My Graphical Projects`, clean.

If a number here disagrees with what you measure, **trust your measurement and
correct the doc.**

---

## 5. Session mechanics

**Corpora kept on disk — do not re-download or rebuild:**

| path | what | why keep |
|---|---|---|
| `C:\excmp-bench\silesia` | 202 MB, 12 files, **211,938,580 B** | the anchor. Payload size for normal is **48,688,221 B** — compare *that*, not the archive digest |
| `...\Downloads-1\Songs` | 610 `.flac`, 110 `.wav` (5.07 GiB) | B4's material; the 610 FLACs are still an unexamined question |
| `Downloads-1\PalluVaapaHDD\0No Need To Check\Programs` | 721 MB, 42 installers | the estimator backtest pins exact sizes |

**Disk space is now a constraint.** `C:` has **2.9 GB** free; `D:` has 13 GB.
The Silesia job does not fit on `C:` with its temp — put `StageContext(temp_dir=...)`
on `D:` and only the archive on `C:`. That also means the total job time is not
comparable to B8's 2.5 m (this session measured 116 s with temp on `D:`).

**Plan mode is NOT needed for the normal `/next` flow.** Turn it on for
exactly two things: **B6** (its DLL-bootstrap flaw is an architecture decision
touching the lossless guarantee) and **Phase H** (large, and H5 conflicts with
B6). Skip it for D7, E2, D4, F5, I6.

**Re-judge B6's size.** The "3-4 sessions" estimate was made when context
could not hold its five sub-items at once. Read the audit note, then size it —
this project does not carry a number forward on plausibility.

---

## 6. Everything still open

**Nothing left is a defect.** D8 closed the last one found by inspection. What
remains is hardening, polish, or a big optional phase.

### Small, self-contained

| item | what |
|---|---|
| **E2** | THIRD-PARTY-NOTICES.md — needed now that E1 fetches GPL `flac` and Apache `qpdf` |
| **D5** | `excmp verify --deep`: zpaqfranz-style `t` + `v -ssd` split, plus an order-independent tree hash |
| **G7** | RAM-limited extraction mode (mirror FitGirl's "limit to 2 GB") |
| **F5** | honest UI copy for encryption: "lost password = lost data" |
| **E6** | CONTRIBUTING.md, issue templates, CHANGELOG |
| **B10** | already satisfied by B2's wheel; confirm and close |

### Medium

| item | what | note |
|---|---|---|
| **D7** | CI on `windows-latest` | **next phase** — see section 3 |
| **D4** | disk-full simulation on a VHDX/`subst` volume | D8 gave it a specific target: `publish()`'s short-write refusal has never met a real ENOSPC |
| **D6** | fuzzing the `.excmp` parser (HypoFuzz on Windows) | D0 hardened it by hand; nothing has fuzzed it |
| **I6** | "compare presets on this input" | the estimator is trustworthy enough since B8 |
| **I7** | i18n pipeline (`.ts` + Language menu) | **do not invent Dhivehi** — build the pipeline |
| **B9** | finish the RAM estimator formula | `-md=192m` and `-mqs` settled; only the formula is left |
| **B12** | LOLZ as an optional final codec | unverified ~5-10%; **measure the baseline first** |

### Large, or blocked

| item | what | status |
|---|---|---|
| **B6** | xtool + Oodle | **blocked on test material.** No Oodle game folder here; the DLL-bootstrap flaw means archives would only restore on the machine that made them |
| **Phase C** | C1-C7: FFmpeg fetch, ffprobe, AV1 encode, honest ETA, `oxipng`, `qpdf` | the whole opt-in lossy phase; C6/C7 measured and waiting |
| **Phase H** | H1-H6: Inno Setup installer generation | large, and H5 conflicts with B6 |
| **E3-E5** | PyInstaller build, signing, auto-update | **only if this is ever shared**; E4 retired while private |
| **D0.6** | Windows process mitigations for subprocesses | deferred to its own session by design |
| **I5** | Explorer context menu | **ask first** — writes to HKCU |

---

## 7. Things not to re-litigate

- **The repo is private and the OSI rule is retired** (2026-09-01). Any tool
  may be used; the lossless guarantee is *more* important as a result, not
  less.
- **Never weaken verification to fit a tool in.**
- **`os.replace` needs no `unlink()` first**, on Windows or POSIX. It
  overwrites atomically. Adding one back would restore the D8 defect.
- **The read-back is not paired with an expectation on the plain path**, and
  that is measured, not an omission. See section 2.
- **Windows cannot flush a directory.** Contents are flushed; rename metadata
  durability is the filesystem's. Stated in `excmp/atomic.py`'s docstring.
- **`split_file` writes parts at their final names, not through `.tmp`** — the
  numbering and the sidecar already reject an incomplete set, and its failure
  path removes what it wrote.
- **`publish()`'s `(st_dev, st_ino, st_size)` check never refuses on its own.**
  `st_ino` is a real file index on NTFS and synthesised on FAT32/exFAT, which
  is what a USB stick arrives formatted as. A disagreement re-hashes the
  destination; only differing *content* refuses.
- **zpaqfranz is not tree-capable here**, deliberately.
- **SREP stays out.** Permitted now, but it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **`MAX_MANIFEST_BYTES` is 64 MiB and that number is measured.**
- **`manifest.json` is the one DEFLATED member of the container**, written with
  `ensure_ascii=False`. Both are load-bearing — and its `created_utc` is why
  the archive is not byte-reproducible.
- **The manifest preflight is deliberately pessimistic.** If you add a manifest
  field, add it to `test_the_size_estimate_*` in `tests/test_manifest_v2.py`.
- **`verify_restore` does not compare timestamps**, on purpose.
- **The zstd window is fitted to the input, not pinned at 31**, and the *read*
  ceiling stays independent of the write setting — that coupling was K4's bug.
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
