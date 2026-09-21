# 🚦 START HERE — handoff (written 2026-09-20)

> **One branch is awaiting review: `phase-i6-measured-presets`.** Docs are on
> `main`. Nothing else is outstanding.
>
> **Next phase: B12's implementation** — LOLZ now has the measurements it was
> gated on and they came back positive, but read §3 before writing a line,
> because the second corpus says something the first one does not.
>
> ⚠️ **Read §1 first.** Eight estimator tests are silently switching
> themselves off because one file was deleted from the live corpus.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** 1 h 07 m with 2.9 GB free on `C:`,
  14 m 52 s with 14 GB, **20 m 10 s with 101 GB free while a LOLZ benchmark had
  one of the two cores**. Free space and contention both move it. Measure it;
  do not quote any of these.
- **`pytest`'s elapsed time is not a measurement on this laptop, because it
  sleeps.** One run reported 11 h 28 m against a `ResumeCount: 3` in the System
  log. Hold the machine awake with
  `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)` —
  process-scoped, touches no power setting.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before starting.**
  Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run invalidates the run.
  Editing `docs/` does not — nothing in the suite reads it at runtime, which
  was checked rather than assumed.

---

## 0. State of the repo

| | |
|---|---|
| `main` | docs only this session: three benchmark records + the roadmap |
| branch | **`phase-i6-measured-presets`** — I6's code, **unmerged, awaiting review** |
| tests | **1,271 passed, 10 skipped, 1 xfailed** (was 1,229 / 2 / 1) |
| corpus guard | clean — nothing under either real corpus was touched |
| AI attribution | none, anywhere. Audited before each commit |

**+50 tests**: `tests/test_sample.py` (22) and
`tests/test_i6_measured_presets.py` (28).
**+8 skips**: all one problem, and it is the first thing to deal with.

---

## 1. ⚠️ Eight estimator tests are off, and the suite still says green

`tests/test_estimate_backtest.py` is gated on the 2026-08-01 benchmark corpus
being present **at its recorded sizes**. Five of its six pinned files are
there. One is not:

```
MISSING   lghub_installer.exe   58,146,712 B
```

That single deletion switches off **all eight** backtest tests — the ones that
score J1/J8's estimator against real measured data — and the suite reports
`1271 passed` without a hint. It is the project's own recurring lesson
("green is a claim about what the tests look at") happening again, this time
caused by the corpus folder being live rather than by anything in the code.

**The skip now names the file** rather than saying "the corpus is not present",
so `pytest -rs` is actionable — that one-line change rides on the
`phase-i6-measured-presets` branch with the rest of this session's code, since
a test edit is code and code does not go straight to `main` here.

Two ways to fix the underlying gap properly, and it is a judgement call:

- **restore `lghub_installer.exe`** to
  `Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programs\` — it is a
  Logitech G Hub installer, re-downloadable — and all eight re-arm as they are;
- or **re-pin `FILES`** in that test to a set that still exists, which means
  re-deriving its expected ratios. Do not simply drop the missing entry: the
  assertions were fitted to the whole six-file set.

**Also measured today:** that folder is now **29 files / 4,992,790,741 B**.
`CLAUDE.md` still says "6.4 GB across 42 files (2026-08-07)". The doc already
warns to re-measure before quoting it; this is that warning being right.

---

## 2. What shipped

### I6 — "compare presets on this input" ✅ (branch, awaiting review)

Full record:
[benchmarks/2026-09-20-i6](benchmarks/2026-09-20-i6-measured-presets.md).

A **Measure presets** button beside Compress runs every distinct chain on a
≤100 MB sample as **real queue jobs** and prints the measured saving onto the
cards as each one lands. New `excmp/sample.py` (Qt-free) and
`gui/compare_run.py`; `tools/bench.py` gained `--sample`.

The spec was one sentence. Everything hard was in the two questions it did not
answer — **which bytes get measured**, and **what the number is allowed to
claim** — and both answers are recorded in the module docstrings because they
are the feature.

### B12 — LOLZ, measured against the real route ✅ (measurement only, no code)

See §3.

### B13 — balrogg ❌ still blocked, both halves, re-checked by searching

See §4.

---

## 3. Next phase: B12's implementation, and the number to keep in view

Full record:
[benchmarks/2026-09-20-b12](benchmarks/2026-09-20-b12-lolz-vs-precomp-7z.md).

The 2026-09-11 session named the deciding measurement — LOLZ against
`precomp → 7z` rather than against 7-Zip alone. It has been run, on two
corpora, with every row restored and SHA-256 compared.

| corpus | best 7-Zip | `lolz -d64m` | delta | time cost |
|---|---:|---:|---:|---:|
| **deflate** (Silesia zip → precomp, 237 MB) | 51,820,126 | **50,233,466** | **−3.06%** | 7.3× |
| **real installers** (13 files / 55.7 MB → precomp) | 46,048,116 | **45,933,664** | **−0.249%** | 6.7× |

**Read those two rows together.** 3.06% is a deflate-stream result. On the data
this app is actually for, the win is **114,452 bytes out of 46 MB for 6.7× the
compression time.** One corpus would have shipped "the first specialist to beat
`precomp → 7z`".

It is **not** rejected the way B16's xtool was — smaller-at-any-speed is the
axis this project has said it optimises — so it qualifies as exactly what the
roadmap already specified: **an Insane-tier alternative to the 7-Zip stage,
never a default, degrading when absent.** Whether 0.25% buys 6.7× on installer
data is the owner's call; the numbers now exist to make it.

**Run this before writing the stage:** LOLZ has never been measured against
**zpaqfranz**. Insane's final codec is zpaqfranz, not 7-Zip, so that is the
comparison that decides where LOLZ actually belongs — and it is one afternoon.

**Three things the integration must carry**, all measured:

1. **`-mt2` costs LOLZ ratio** — 1.12% on the deflate corpus, 0.26% on the
   installers, enough to turn its win into a loss there. Its default `-mt1` is
   its best setting. Do not hand it the project's calibrated two threads.
2. **`cls-lolz_x64.exe` segfaults on corrupt input and still leaves a 0-byte
   output file**, and silently writes a 0-byte output for a missing input,
   printing nothing either time. A "did the output appear?" check — which is
   what `stages/precomp.py:57` does — passes both. The post-restore SHA-256
   gate is the only thing that catches it.
3. Both binaries exit **−1** on their usage path, which Bash reports as 127 —
   the same code as "command not found". `cls-lolz_x64.exe` prints no banner at
   all; its version comes from `lolz_x64.exe` or the file hashes.

Distribution pinned and verified today: `lolz22c4b.7z`, 437,444 B, sha256
`ac6730b3…93cb6`, extracted at `C:\excmp-bench\lolz\`.

---

## 4. B13 — blocked on both halves, and a defect found while proving it

Full record:
[benchmarks/2026-09-20-b13](benchmarks/2026-09-20-b13-vorbis-baseline.md).

**Do not spend another session re-searching for these. Both were re-checked
today by searching, not by reading the last note.**

- **No balrogg binary** anywhere plausible on this machine. The download is
  still behind a krinkels.org login. (An unbounded sweep timed out at 480 s, so
  the honest claim is "not in the plausible places".)
- **No game-audio corpus.** Zero `.opus`, `.wem`, `.fsb`, `.bnk` anywhere,
  including the F: volume and the external `Downloads-1` tree — and that tree
  was **fully enumerated, 412,055 files**, with an extension histogram over all
  of them, not sampled. That is the search B4's post-mortem asked for and the
  omission that made B4's original "blocked" verdict wrong. **No game is
  installed on this machine at all.** The only Vorbis is 39 UI sound effects
  (31 unique, 326,692 B) inside the odoo18/odoo19 source trees.

**One download of a real game's audio archive unblocks B13 and B6 together.**

**The defect found while establishing the gate.** On that Ogg corpus, through
`engine.compress` itself, the product writes an archive **6,625 bytes larger
than the input (−2.0%)** while telling the user the data is *"already
compressed by its codec"* — and the analyzer had already measured those same
files at `sample_ratio` **0.687–0.945**. Plain `7z -mx9` takes 21.4% off them
non-solid, 41.9% solid. Precomp prints `Recompressed streams: 0/0`.

**Nothing was changed on the strength of it**, and that is deliberate: 326 KB
of low-bitrate UI blips is not a corpus, most of the solid win is cross-file
redundancy between two versions of one product, and high-bitrate Vorbis music
is expected near 0%. The finding is recorded; the fix waits for data.

When the data arrives, the hook is **`_UNCOMPRESSED_AUDIO`**
(`planner.py:173`, B4's precedent) — **not** `_DEFLATE_MEDIA`, which throws the
file into a `precomp` that has now been measured to find nothing in it. And a
patch that edits only `analyzer._EXT` will be bypassed: the magic-byte rule at
`analyzer.py:52` catches `OggS` before the extension is ever consulted, which
was proven with a file called `named.dat`.

---

## 5. Findings worth not rediscovering

### Two corpora, not one — the whole B12 verdict lives in the gap between them

LOLZ at 3.06% on deflate and 0.249% on installers is the same binary, the same
flags, the same day. A specialist's headline number is a statement about the
corpus it was measured on, and B16 already taught this in the other direction
(xtool's `-mzlib` found *nothing* on 7-Zip-authored deflate because it only
matches streams zlib itself would have written). **Budget for the second
corpus or do not quote the first.**

### A number can be measured and still be the wrong number

I6's sampler is proportional by bytes. On the real Programs corpus it *cannot*
be: 42.4% of the bytes are in `.zip` files each larger than the entire 100 MB
cap, so the sample carries 3.9% of them. No whole-file subset fixes that, and
forcing the proportions would mean measuring 5 MB. So the bias is **reported**
(`Sample.under_represented`) and it bounds the claim — a measured comparison
**ranks the profiles on identical bytes, it does not forecast the job**. A test
asserts the measurement never moves the recommendation.

### Nine defects, and the test suite found none of them

I6 went green — 50 new tests, the full suite at 1,271 — and then **nine real
defects turned up anyway**, in two passes.

Two came from `tools/qa_sweep.py` and looking at the PNG (see below). The other
seven came from an **adversarial review of the already-committed diff**: three
reviewers on different lenses (object lifecycle / fuzz the sampler / "does the
UI ever state something untrue"), then every finding handed to a separate agent
told to refute it. Sixteen findings, **nine refuted, seven reproduced**.

The two worth remembering:

- **A cancelled job stranded the whole run.** `QueueManager` retires a
  cancellation through `_retire`, which emits `jobStateChanged` and *neither*
  `jobDone` nor `jobFailed`. Every measurement job has a visible **x** in
  Activity, so one click left the run listening forever, the button stuck on
  "Stop measuring", and the temp directory on disk. Closing the window does the
  same thing via `shutdown() -> cancel_all()`. The bug was not in the logic —
  it was in assuming a queue's vocabulary for "this job is over" was two words
  when it is three, on two channels.
- **Removing one pending file kept the old measurement.** `remove_selected_
  pending` mutates `_infos` in place and never re-analyses, so it was the one
  input-changing path `_forget_measurements` did not cover. One row's spoken
  sentence read *"about 860 B … measured archive 3.3 MB"*.

### ...and then the fixes exposed a tenth, in the test harness itself

Two pixel budgets went red after the fixes — `test_gui_compact` at 53px against
36, `test_gui_fit` at 487px against 447 — and **neither was about pixels.**
They also failed on the pre-I6 commit when run in isolation, which is what gave
it away.

`excmp/calibrate.py` writes J7's learned rates to `~/.excmp/calibration.json`,
a **global file `conftest.py` did not isolate**. I6's end-to-end tests run real
queue jobs, `CompressWorker._calibrate` wrote one zstd sample into it, that
changed `blended_rates()`, which changed Fast's estimate, which gave Normal a
"not worth it" note, which is a full-width prose line — 53px on a row budgeted
at 36, and 40px on a page budgeted at 447.

**The suite's result depended on whether anyone had ever run the app on this
machine.** CI, with a clean home directory, would never have seen it; a
developer who had used the app once would see two unexplainable pixel failures.
There is now an autouse fixture routing `calibrate.DEFAULT_PATH` to `tmp_path`
like QSettings, plus a test asserting the fixture is in force. The stray
`~/.excmp/calibration.json` the test runs created was deleted, restoring the
pre-session state.

**The lesson for the next feature: the refute-it pass is worth its cost.** Nine
of sixteen findings were wrong, and the review would have been noise without
it; the seven that survived included two that put a wrong number on screen with
a measurement's authority, which is the one thing this product must not do.

### Rendering caught two defects too, and the suite caught neither

`tools/qa_sweep.py`, 05b. A row showed `Estimated size: about 225.9 KB` beside
`Saved: 61% measured` — 61% of 371.5 KB is 144.9 KB, two numbers about one job
contradicting each other. Fixing it produced the second defect: a column titled
"Estimated size" carrying a measured one. **Fifth time this sweep has been the
thing that caught it.**

### Reserving the cheap thing first

I6's first sampler did the proportional pass first and forced missing
categories in afterwards. On Silesia at a 20 MB cap that took **2 of 12 files,
left 4 MB unspent and dropped a whole category** — the big categories had
already spent the budget. Reserving one file per category first, cheapest
first, takes 3 of 12 at 94% of the cap. Found by running it on real data, ten
minutes after the unit tests went green.

### `precomp -intense` is in the chain and it is not free

`stages/precomp.py:42` runs `-cn -intense`; B16 measured `-cn`. On the same
corpus that is **82,086 more bytes** in the final archive — 51,827,136 rather
than B16's 51,745,050. Anything comparing against "our route" must use the
larger figure. Whether `-intense` is worth its cost is an open Precomp
question nobody has looked at.

### Zstd beat 7-Zip, and that is why the test asserts difference

I6's end-to-end test compresses 980,000 B of repetitive text: Fast/zstd lands
at **960 B**, Normal/7-Zip at **1,057 B**. At a kilobyte the `.7z` container
costs more than the codec saves. The test asserts the two numbers *differ*
rather than that the stronger profile wins, because "the stronger profile wins"
is an assumption and measuring it is the point of I6.

### Everything already established, still true

- **A silent no-op looks exactly like a negative result.** Verify a
  precompressor actually did something; exit 0 is not evidence.
- **The specialists that win compete with `store`, not with the chain.** Five
  proposed, one won (B4's FLAC). LOLZ is the first to beat the chain at all,
  and it does so by 0.25% where it matters.
- **A factor plumbed through one of two sites is not plumbed** (F2's keyfile).
- **"Green" is a claim about what the tests look at** — see §1 for today's.
- **A test that treats a default as an invariant is a false alarm waiting.**
- **A pixel budget measured on one font stack is not a budget anywhere else.**
- **A full disk is not a per-file problem**; `ENOSPC` aborts, K3 skips the rest.
- **The archive is not byte-reproducible.** Compare payload size, never the
  archive digest. Silesia/normal payload is **48,688,221 B**.
- **XOR is not a way to combine hashes.** D5's tree hash is sort-then-hash.

---

## 6. Everything still open

### Small
| item | what |
|---|---|
| **corpus repair** | restore `lghub_installer.exe` or re-pin `FILES` — §1 |
| **B12 vs zpaqfranz** | one afternoon, and it decides where LOLZ belongs |

### Medium
| item | what |
|---|---|
| **B12 implementation** | **recommended next**; gates met, §3 has the constraints |
| **B13** | blocked on a krinkels.org download **and** a game-audio corpus |
| **B14** | DArc 3.04, the maintained FreeArc fork |
| **D6b** | more fuzz targets if wanted; the parser is covered |
| **I5** | Explorer context menu — **ask first**, writes to HKCU |
| **I10** | settings search, drag-out extract, jump list — the unfinished half |

### Large, or blocked
| item | status |
|---|---|
| **B6** | xtool + Oodle — blocked, no game corpus (same download as B13) |
| **B15** | ADDeX 0.1 — too early |
| **D4b** | the real-volume half — needs an elevated session for a VHDX |
| **Phase C** | C1–C7, the opt-in lossy phase |
| **Phase H** | H1–H6, Inno Setup generation |
| **E3–E5** | PyInstaller, signing, auto-update — only if this is ever shared |
| **I7** | ❌ won't do |

---

## 7. Things not to re-litigate

- **The repo is private and the OSI rule is retired.** Any tool may be used;
  the lossless guarantee matters *more* as a result.
- **Never weaken verification to fit a tool in.** LOLZ is today's example:
  its decompressor segfaults leaving a 0-byte file and reports nothing.
- **No AI attribution in commit messages, ever.**
- **`os.replace` needs no `unlink()` first.**
- **Windows cannot flush a directory.**
- **Extraction memory is controlled by `-mmt`, not the dictionary.**
- **Insane is data-dependent, not stronger.**
- **SREP stays out** — it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.** The
  estimate columns do that, and I6 deliberately keeps them separate.
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
