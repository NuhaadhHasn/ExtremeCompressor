# 🚦 START HERE — handoff (written 2026-09-27)

> **B17 is done, on branch `phase-b17-insane-m5`, pushed and awaiting
> review. Insane now runs zpaqfranz `-m58`** (method 5, 256 MiB blocks), per
> the owner's instruction: "whatever is best for compression". Merge with:
>
> ```
> git switch main && git merge --no-ff phase-b17-insane-m5 && git push
> ```
>
> **K6 is also done, on branch `phase-k6-cancel-silent-tool`**, pushed and
> awaiting review. Cancel now reaches a tool that prints nothing, which is
> zpaqfranz for the whole of a restore. The two branches are independent;
> merge K6 the same way:
>
> ```
> git switch main && git merge --no-ff phase-k6-cancel-silent-tool && git push
> ```
>
> **Next phase: I11 — progress through the D9 restore.** At `-m58` the
> restore is ~40% of an Insane job, the bar parks at 95%, and zpaqfranz
> prints nothing to parse (measured). §3 has the spec.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** 1 h 07 m with 2.9 GB free on `C:`,
  14 m 52 s with 14 GB, 20 m 10 s with 101 GB free while a benchmark had one
  of the two cores. Free space and contention both move it.
- **`pytest`'s elapsed time is not a measurement on this laptop, because it
  sleeps.** Hold the machine awake with
  `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)` —
  process-scoped, touches no power setting.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run
  invalidates the run. Editing `docs/` does not.

---

## 0. State of the repo

| | |
|---|---|
| `main` | docs-only commits on top of the I6 merge (`609bc07`); B12 closed there |
| branch | **`phase-b17-insane-m5`** — B17, pushed, **not merged** (merge command above) |
| branch | **`phase-k6-cancel-silent-tool`** — K6, pushed, **not merged**, independent of B17; both merge into `main` cleanly, in either order (checked with `git merge-tree`) |
| tests | B17 branch **1,336 passed, 2 skipped, 1 xfailed** (19 min 07 s). K6 branch **1,297 passed, 2 skipped, 1 xfailed** (19 min 14 s). Both 2026-09-27, machine held awake. `main` is 1,292 (2026-09-21) |
| corpus guard | clean around both runs: snapshot right before each, 154 files, 0 added / 0 removed / 0 modified |
| AI attribution | none, anywhere. Audited before each commit |

---

## 1. What shipped: B17

Full record:
[benchmarks/2026-09-27-b17](benchmarks/2026-09-27-b17-insane-m58.md).

**The choice.** Before switching Insane to `-m5`, one more question was
asked: does anything beat it? zpaq's method takes a block-size digit, and on
the 237 MB deflate `.pcf` bigger blocks compress better. Every archive was
restored and SHA-256 compared:

| setting | archive | vs `-m4` | peak RAM, two threads busy |
|---|---:|---:|---:|
| `-m4` (before) | 46,575,605 | — | 915 MiB |
| `-m5` (64 MiB blocks) | 43,194,463 | −7.26% | 1,819 MiB |
| `-m57` (128 MiB) | 42,933,026 | −7.82% | 2,903 MiB |
| **`-m58` (256 MiB)** | **42,852,397** | **−7.99%** | **4,916 MiB** |

`-m58` is the smallest setting measured anywhere in B12 or B17, and the
largest block whose two-thread peak fits `_RAM_BUDGET` (55% of 16 GB).

**End to end through `engine.compress`, D9 gate included:**

| corpus | `-m58` | `-m4` | |
|---|---:|---:|---|
| Silesia (212 MB) | **37,542,028** (82.29%), 3,810 s | 41,216,918 (B8), 16.7 min | **−8.92%** |
| installer sample (55.7 MB) | **45,951,032**, 745 s | 46,223,108 | −0.59% (one block: `-m5`'s gain) |

**What changed in code:**
- `excmp/stages/zpaqfranz.py`: `DEFAULT_METHOD = 58`. Nothing else needed:
  the engine builds the stage with no arguments, and a test pins that the
  two agree. `-m4` archives still restore, because extraction names no
  method. There's a real round-trip test for that.
- `excmp/ram.py`: a zpaqfranz model from the measured peaks, *shared + per
  busy thread*, scaled down for small blocks (1 MiB → 99 MiB, 16 MiB →
  314 MiB), plus `physical_cores()` and **`zpaqfranz_threads()`, which caps
  the thread count at `_RAM_BUDGET`** (3 on this laptop; default 2).
  zpaqfranz defaults to physical cores (`2T` here, `4T` only with `-ht`).
- **The stage always passes an explicit, capped `-t`**, for compress and
  restore, and `--low-memory` now reaches it as `-t1`. A failed restore
  cleans its scratch folder.
- `excmp/calibrate.py`: Insane entries are stamped with the zpaq method, so
  a rate learned at `-m4` before B17 can't override the measured one.
- `gui/suggest.py`: **the table's peak-RAM cell for Insane had always used
  7-Zip's LZMA2 formula** (7,084 MiB for a Silesia-sized job). It now
  follows the chain.
- `excmp/estimate.py`: **Insane's speed had never been measured.** With no
  rate key, the 2.5 MB/s fallback predicted 41–285 s for a job that took
  3,810 s. The new keys are 0.091 MB/s codec (two corpora 8% apart) and
  0.107 MB/s verify on piped bytes. Stored bytes are now billed at disk
  speed; at the chain's rate they had turned a 2 GB stored video into a
  four-hour estimate. The slope is re-anchored at `-m58` (0.945).
- `gui/progress.py`: zpaqfranz weight 50 → 400. It's 90–93% of an Insane
  compress on every corpus.
- README: Insane is no longer "WIP"; the stale roadmap ticks are fixed.

---

## 2. Findings worth not rediscovering

### Rendering caught what the new tests didn't

The first zpaqfranz RAM model quoted **2.7 GB for the 371.5 KB demo job**,
because it charged every job a full 256 MiB block. The suite was green. The
qa_sweep PNG showed it. This is the sixth defect that sweep has caught.

### The adversarial review earned its keep again

Two passes, three lenses plus a skeptic per lens, eight defects confirmed
and fixed test-first:
1. The thread count was never held to the two threads the RAM case was made
   for (8 threads ≈ 17 GB).
2. `--low-memory` never reached zpaqfranz.
3. A pre-B17 J7 rate would override the measured one.
4. A failed restore left its scratch folder.
5. **Stored bytes were billed at the chain's restore rate**, which put a
   2 GB stored video at four hours. B17's new rate caused this.
6. The RAM cell showed only the worst case. It's now a range on its second
   line.
7. The RAM inflation was averaged over stored files.
8. The cell ignored the Worker threads setting.

Only K6 (Cancel) was left open, because it predates B17 and touches every
stage.

### Honest numbers can move pixel budgets, so measure what moved

The measured Insane time made its "Extreme is ~24× quicker" note true on the
suite's fixture, and two layout guards failed (row 69 px against 56, page
504 px against 447). Before re-baselining, the page was measured with the
note suppressed: exactly 447 px, identical to `main`. So all of the growth
was the warning. Same precedent as B8. Moving a guard needs that proof
beside it, not a rounder number.

### Ask the question the options leave out

B17 was filed as "-m4 or -m5". The block-size digit wasn't in the question,
and it took another 0.79% off. When the owner says "best", check the knobs
the plan didn't list before choosing among the ones it did.

### Method-5 context mixing barely scales to a second thread here

`-m57` on two threads took 1,176 s, and `-m58` on one took 1,264 s. At `-m4`
a second thread bought 1.43×. The likely cause is memory bandwidth, and it's
unproven. It means `-m58`'s single-thread 256 MiB blocks cost little wall
time on this laptop.

### zpaqfranz reports no restore progress until the very end

Its extract printed its first percentage 52 s before finishing a 26-minute
Silesia restore. That's I11's real obstacle, and it also means per-stage
timings can't be read off the progress callback: tools print late.

### Timings: two unexplained, both recorded as such

- The 2026-09-23 `-m5` compress was about 541 s by file timestamps. Every
  timed method-5 run since took 1,070–1,264 s, and a 2026-09-27 `-m4` speed
  check matched 09-23 exactly (122.9 s against a 119.0 s median). The
  timestamp figure is treated as the outlier.
- The two-thread `-m58` RAM run was stopped during its restore on purpose,
  because only the peak was wanted. Its peak was read from the live process
  every 0.5 s until it exited, and that method is recorded in the JSONL.

### Still true from before

- **Measure the incumbent that fills the slot**, not the familiar tool (B12).
- **Two corpora, or don't quote the first.** B17's rates agree within 8%
  across two, which is why they shipped as a geometric mean.
- **Never pin a single timing run, and never pin the first one.**
- **A silent no-op looks exactly like a negative result.** Exit 0 is not
  evidence.
- **"Green" is a claim about what the tests look at.** Render the GUI.
- **`~/.excmp/calibration.json` is global state**, isolated in `conftest.py`.
- **The archive is not byte-reproducible.** Compare sizes, never digests.
- **CLAUDE.md says "Default threads is 2"; the code's default is 0 (each
  tool chooses).** zpaqfranz comes out at 2. 7-Zip's no-switch choice was
  never measured. Still open.

---

## 3. Next phase: I11 (K6 is done, on its branch)

**K6 — done 2026-09-27, branch `phase-k6-cancel-silent-tool`.** `run_tool`
gained a watcher thread that kills the child on Cancel and reports
"cancelled", not "exited with code 1". Before the fix, a silent 60 s child
with Cancel at 0.5 s held each of three new tests for the full 60 s. Full
suite on that branch: **1,297 passed, 2 skipped, 1 xfailed** (2026-09-27, corpus guard clean). The background, kept for the record:
`stages/base.run_tool` used to check `ctx.cancel` only when the tool
emitted a line. **Already measured, at the end of this session:** during
`zpaqfranz x` of a `-m58` archive, raw stdout is the header by 0.3 s, then
**nothing at all** until the summary at 151 s. `-verbose` is the same. So
Cancel and window-close can't be honoured during any Insane restore: 20+
minutes on a Silesia-sized job. The capture is in
`C:\excmp-bench\b17\k6\`. The fix is a watcher thread that waits on
`ctx.cancel` and kills the process (`run_capture` already has one), then
raises "cancelled". It touches every stage, so each stage's cancel path
needs a test. That's code: branch, TDD, full suite.

**I11 — progress through the D9 restore.** Spec: [ROADMAP.md, I11](ROADMAP.md)
(under I10). The same capture settles its design question: zpaqfranz prints
nothing during a restore, so there is nothing to parse. What's left is a
visible "verifying" phase with elapsed time against the estimate's D9 share.

`ChainProgress` (`gui/progress.py`) caps the pipeline at 95% and keeps its
peak. The D9 restore reports through the same stage ids, so the bar parks at
95% for the whole self-test. At `-m58` that is 1,556 s of a 3,810 s Silesia
job.

**Measure before designing:** what does zpaqfranz print during `x` with
`-verbose`, or any other switch, that could be parsed as progress? If it
prints nothing usable, the honest fallback is a visible "verifying" phase
with elapsed time, and the estimate's own D9 share: `_VERIFY_RATE` now has a
measured Insane key, so the expected verify duration is computable. Any GUI
change means running `tools/qa_sweep.py` and looking at the images, in both
themes.

Also open and small, from this session: 7-Zip's default thread count with no
`-mmt` switch, against CLAUDE.md's "2" (§2).

---

## 4. B13 — blocked on both halves (unchanged since 2026-09-20)

Full record:
[benchmarks/2026-09-20-b13](benchmarks/2026-09-20-b13-vorbis-baseline.md).
**Do not re-search for these**: no balrogg binary on this machine (the download
is behind a krinkels.org login), no game-audio corpus anywhere (the external
tree was fully enumerated, 412,055 files), no game installed.

**The defect found while establishing the gate still stands, unfixed on
purpose:** on the only Ogg on this machine (326 KB of UI blips), `engine.compress`
writes an archive 6,625 B *larger* than the input and tells the user the data is
"already compressed by its codec", while plain `7z -mx9` takes 21.4% off.
Nothing changed on 326 KB. When real data arrives the hook is
**`_UNCOMPRESSED_AUDIO`** (`planner.py:184`), not `_DEFLATE_MEDIA`. A patch to
`analyzer._EXT` alone is bypassed by the `OggS` magic-byte rule at
`analyzer.py:52`.

---

## 5. The downloads, in Chrome — needs the owner present

Unblocks B13 and B6, and gives LOLZ its only possible rematch (§1).

| target | unblocks | note |
|---|---|---|
| `balrogg` v1.1, krinkels.org resource `…-recompressor.601` | **B13** | behind a login. **Do not create or confirm an account.** If the address is still unconfirmed, that step is the owner's |
| genuine Ogg Vorbis / Opus **music**, not UI blips | **B13**'s gate | open-source games ship real libvorbis: 0 A.D., SuperTuxKart, Xonotic, OpenRA |
| `.wem` (Wwise) / `.fsb` (FMOD) banks | **B13 + B6** | Wwise's and FMOD's own free sample projects. **Not** repack or warez bundles |
| an Oodle/Kraken-compressed archive | **B6** | the untested half of B16 |

**Rules that do not bend:** confirm each download with the owner by name,
source and size before fetching; treat every binary as untrusted and pin its
SHA-256 on arrival; nothing measured on it moves routing until it has beaten
the shipped route **and** restored byte-identically through `verify_restore`.
High-bitrate Vorbis is *expected* near 0%. **B13 dying on real data is a
legitimate outcome**, and a cheaper one than keeping the item open.

---

## 6. Everything still open

### Small / medium
| item | what |
|---|---|
| **I11** | **recommended next**: progress through the D9 restore, §3 |
| **K6** | ✅ done 2026-09-27, branch `phase-k6-cancel-silent-tool`, awaiting review |
| **B13** | blocked on a krinkels.org download **and** a game-audio corpus (§5) |
| **B14** | DArc 3.04, the maintained FreeArc fork, now also carrying B12a (plain FreeArc, never measured). It must beat the *shipped* route, including zpaqfranz in Insane's slot, which is what sank LOLZ |
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
| **B12** | ❌ closed 2026-09-23. Reopens only on game/DXT data measured against `-m58`; condition (b) was resolved by B17 |
| **B17** | ✅ done 2026-09-27, on its branch awaiting review |
| **B16** | ❌ closed 2026-09-15 |

---

## 7. Things not to re-litigate

- **LOLZ is not being integrated.** zpaqfranz `-m5` and `-m58` both beat it
  on both corpora. It reopens only on game/DXT data, measured against `-m58`.
- **Insane runs `-m58`.** The owner chose "best for compression"; `-m4` is
  one argument away, and `-m59` was not measurable on these corpora.
- **The repo is private and the OSI rule is retired.** Any tool may be used;
  the lossless guarantee matters *more* as a result.
- **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **`os.replace` needs no `unlink()` first.**
- **Windows cannot flush a directory.**
- **Extraction memory is controlled by `-mmt`, not the dictionary.**
- **Insane is data-dependent, not stronger.** At `-m4` it lost to Extreme by
  0.31% on installers. At `-m5`/`-m58` it beats Extreme on both B12 corpora,
  but it's always the slowest by far.
- **SREP stays out** — it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
