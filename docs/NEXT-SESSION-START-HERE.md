# 🚦 START HERE — handoff (written 2026-10-01)

> **Everything is merged into `main` and pushed. No branch is awaiting
> review**, and the old feature branches are deleted, locally and on GitHub.
>
> **Next phase: I11 — progress through the D9 restore.** At Insane's `-m58`
> the pre-publish restore is about 40% of the job, the bar sits at 95% the
> whole time, and zpaqfranz prints nothing to parse (measured). §3 has the
> spec.
>
> **The target machine changed.** It's now a Dell Inspiron 15-3567,
> i5-7200U (2 cores / 4 threads), 15.9 GB, confirmed by the owner. **Every
> timing recorded before 2026-10-01 is an i7-3540M number.** Run
> `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** On the old i7-3540M it ran from
  14 m 52 s to 1 h 07 m depending on free disk space and contention. On this
  i5-7200U the first full run (2026-10-01, 1,361 tests) took 30 min 38 s.
  Measure it; don't quote it.
- **`pytest`'s elapsed time is not a measurement on a laptop that sleeps.**
  Hold the machine awake with
  `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)`.
  `C:\excmp-bench\b17\suite.py` does that and wraps the corpus guard around
  the run.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run
  invalidates the run. Editing `docs/` does not.

---

## 0. State of the repo

| | |
|---|---|
| `main` | everything merged: B17, K6, and 2026-10-01's threads + Ogg fixes. Pushed |
| branches | **none** besides `main`. `phase-b17-insane-m5`, `phase-k6-cancel-silent-tool`, `phase-threads-default` and `phase-i6-measured-presets` were merged and deleted (local and remote) |
| tests | **1,358 passed, 2 skipped, 1 xfailed** on the merged tree (2026-10-01, 30 min 38 s on the i5-7200U, machine held awake) |
| corpus guard | clean: fresh snapshot right before the run, 154 files, 0 added / 0 removed / 0 modified |
| CI | last seen green at the I6 merge. The 2026-10-01 push runs it again, so check the Actions tab |
| AI attribution | none, anywhere. Audited before each commit |

---

## 1. What shipped since the last handoff

| item | what | record |
|---|---|---|
| **B12** ❌ | LOLZ measured against zpaqfranz and **not integrated**: `-m5` beats it on both corpora | [2026-09-23](benchmarks/2026-09-23-b12-lolz-vs-zpaqfranz.md) |
| **B17** ✅ | **Insane runs zpaqfranz `-m58`** (256 MiB blocks): 7.99% under `-m4` on deflate data, Silesia 37,542,028 B (−8.92%). RAM model, thread cap, measured estimator rates | [2026-09-27](benchmarks/2026-09-27-b17-insane-m58.md) |
| **K6** ✅ | **Cancel reaches a tool that prints nothing.** zpaqfranz is silent for an entire restore, and Cancel used to wait it out | ROADMAP K6 |
| **K7** ✅ | **Default threads = one per physical core, now in the code.** 7-Zip used to take all 4 logical threads: 0.14% larger archive, 5,549 vs 2,702 MiB peak RAM. RAM-capped, and a user's own `-mmt`/`-mmemuse` is respected | [2026-10-01](benchmarks/2026-10-01-threads-and-ogg.md) |
| **B13a** ✅ | **Real music measured; Ogg routing fixed.** An Ogg file whose probe says it shrinks is piped: 18 real Vorbis/Opus files went from +0.004% to **1.112% saved**, 18/18 verified | [2026-10-01](benchmarks/2026-10-01-threads-and-ogg.md) |

The 18 music files are in `C:\excmp-bench\b13\music` (Wikimedia Commons,
SHA-1 verified, owner-approved). That's B13's corpus, and balrogg now has a
gate to beat.

---

## 2. Findings worth not rediscovering

### The machine under the repo can change

Windows reported an i7-3540M until 2026-09-27 and an i5-7200U on 2026-10-01.
The disk and profile moved, so `C:\excmp-bench` survived. A timing is a
statement about a CPU, and nothing in the repo records which one unless you
write it down. Sizes and peak RAM don't depend on the CPU.

### "The docs say X" and "the code does X" are two claims

CLAUDE.md said default threads is 2 for months. The code's default was 0, and
7-Zip then took 4. A reviewer can't see that from either file alone. Measuring
what the tool did settled it: `-mmt` none = `-mmt4`, byte for byte.

### Passing a switch can turn off a tool's own safety

Forcing `-mmt` disables 7-Zip's built-in fitting of threads to 80% of RAM. On
the 2-core target that's harmless; on a 6-core 8 GB machine it would have
asked for about 9 GB. The adversarial review caught it, and auto is now capped
by `ram.lzma2_auto_threads`. **Before forcing any switch, check what the tool
does when it's absent.**

### The probe was right about music; the rule ignored it

"Media is stored, already compressed by its codec" overrode an analyzer that
had measured 0.9487 on a file 7-Zip then took 5.98% off. Where a measurement
and a category rule disagree, the measurement should win, but only for formats
you've measured. That's why the change is Ogg-only.

### Reviews: two lenses plus a skeptic keep paying

B17's two code reviews confirmed 8 defects, and 2026-10-01's confirmed 9
more (3 in code, 6 in user-facing text and comments), all after the suite was
green. Among them: a RAM cell quoting the wrong codec, a thread cap that
wasn't enforced, a calibration entry that would have overridden a
measurement, a forced switch that disabled 7-Zip's own memory fitting, a
note that didn't refresh, and RAM figures in mixed units. Every one was
reproduced before it was fixed.

### Still true

- **Measure the incumbent that fills the slot**, not the familiar tool (B12).
- **Two corpora, or don't quote the first.**
- **Never pin a single timing run, and never the first one.** Extreme's three
  runs on the backtest spread 1.42×.
- **A silent no-op looks exactly like a negative result.** Exit 0 isn't
  evidence.
- **"Green" is a claim about what the tests look at.** Render the GUI:
  `tools/qa_sweep.py`, both themes, and look at the PNGs. It caught the 2.7 GB
  RAM figure for a 371 KB job.
- **Honest numbers can move pixel budgets.** Re-baseline only with the proof
  beside it (B17's layout guards).
- **`~/.excmp/calibration.json` is global state**, isolated in `conftest.py`.
  J7 entries for zpaqfranz chains are stamped with the zpaq method.
- **The archive is not byte-reproducible.** Compare sizes, never digests.

---

## 3. Next phase: I11 — progress through the D9 restore

Spec: [ROADMAP.md, I11](ROADMAP.md) (under I10).

`ChainProgress` (`gui/progress.py`) caps the pipeline at 95% and keeps its
peak. The D9 restore reports through the same stage ids, so the bar parks at
95% for the whole self-test, which is 1,556 s of a 3,810 s Silesia job at
`-m58`. **Measured already: zpaqfranz `x` prints nothing between its header
and its summary, `-verbose` included** (capture in `C:\excmp-bench\b17\k6\`).
There is nothing to parse. The honest design is a visible "verifying" phase
with elapsed time, set against the estimate's own D9 share: `_VERIFY_RATE`
has a measured Insane key (0.107 MB/s), so the expected verify time is
computable. It's a GUI change, so TDD, then `tools/qa_sweep.py` in both themes
and look, then the full suite.

---

## 4. Waiting on the owner (they've offered)

The owner said they can sign in, or create accounts, for the sites below. **The
session never types credentials or creates accounts**; the owner signs in in
the browser pane, then the session downloads with per-file approval (name,
source, size) and pins the hash on arrival.

| target | unblocks | how |
|---|---|---|
| `balrogg` v1.1, krinkels.org | **B13** | owner signs in; the gate to beat is 1.112% on the music corpus |
| Wwise / FMOD sample banks (`.wem` / `.fsb`) | B13, B6 | owner signs in to Audiokinetic / FMOD; their own sample projects only |
| an Oodle-compressed archive, plus `oo2core` | **B6** | only from a legitimate source the owner has, e.g. a game they own installed on this machine. Never a third-party DLL site |

---

## 5. Everything still open

| item | what |
|---|---|
| **I11** | **recommended next**, §3 |
| **B13** | balrogg vs the 1.112% gate, after the owner signs in (§4) |
| **B6** | xtool + Oodle, needs a legitimate Oodle sample (§4) |
| **B14** | DArc 3.04 (FreeArc fork; also carries B12a). It must beat the shipped route *including zpaqfranz `-m58`* |
| — | zstd's own thread default (`threads=-1`, all logical) has never been measured against 2 |
| — | `precomp -intense` cost 82 KB on B16's corpus; nobody has measured it on game data |
| — | other compressed media (MP3, video): the Ogg probe rule waits until each is measured |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 6. Things not to re-litigate

- **Insane runs `-m58`.** The owner chose "best for compression". `-m4` is one
  argument away, and `-m59` couldn't be told apart from `-m58` on these inputs.
- **Default threads is one per physical core**, measured and capped. Don't
  "helpfully" go back to tool defaults.
- **LOLZ is not integrated.** It reopens only on game/DXT data, measured
  against `-m58`.
- **Ogg is piped only when its own probe says it shrinks**, and only Ogg.
- **The repo is private and the OSI rule is retired**; the lossless guarantee
  matters more as a result. **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **Insane is data-dependent and always the slowest**; that's the trade.
- **SREP stays out**: it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
