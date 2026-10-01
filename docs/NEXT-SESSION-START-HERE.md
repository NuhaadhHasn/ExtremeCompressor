# 🚦 START HERE — handoff (written 2026-10-01)

> **Everything is merged into `main` and pushed; CI is green on `main`. No
> branch exists besides `main`.**
>
> **Next session is an owner agenda, not a single phase.** The owner asked on
> 2026-10-01 for these, **in this order** (§3 has each spec):
>
> 0. **Name the session**, then **open the download tabs** for the owner.
> 1. **Fetch balrogg 1.4 and DArc 3.0.4 from GitHub**, with one approval.
> 2. **I11**: progress through the D9 restore.
> 3. **B13**: balrogg against the 1.112% music gate.
> 4. **B14**: DArc against the shipped route.
> 5. **B18**: the small unmeasured settings.
> 6. **B6**, only if the owner has provided an Oodle sample by then.
>
> Each code item gets its own branch, merged after suite + review + CI green
> (CLAUDE.md, Commits).
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. **Timings recorded before 2026-10-01 are i7-3540M numbers.** Run
> `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** On this i5-7200U the full suite has
  taken 30 min 38 s and 20 min 28 s on the same day (2026-10-01). On the old
  i7-3540M it ranged from 14 m 52 s to 1 h 07 m. Measure it; don't quote it.
- **`pytest`'s elapsed time is not a measurement on a laptop that sleeps.**
  `C:\excmp-bench\b17\suite.py` holds the machine awake
  (`SetThreadExecutionState`) and wraps the corpus guard around the run.
  **Use it.**
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run
  invalidates the run. Editing `docs/` does not.

---

## 0. State of the repo

| | |
|---|---|
| `main` | everything merged: B17, K6, K7 (threads), B13a (Ogg routing), the CI test fix. Pushed |
| branches | only `main`, locally and on GitHub |
| tests | **1,359 passed, 2 skipped, 1 xfailed** locally (2026-10-01, 20 min 28 s, corpus guard clean) |
| CI | **green on `main`** (1,319 passed, 42 skipped on the runner; the skips are pixel-budget tests on the runner's fonts, plus real-corpus tests) |
| AI attribution | none, anywhere. Audited before each commit |

---

## 1. What shipped (B12 → 2026-10-01)

| item | what | record |
|---|---|---|
| **B12** ❌ | LOLZ measured, not integrated: zpaqfranz `-m5` beats it on both corpora | [2026-09-23](benchmarks/2026-09-23-b12-lolz-vs-zpaqfranz.md) |
| **B17** ✅ | Insane runs zpaqfranz **`-m58`**: Silesia 37,542,028 B (−8.92% vs `-m4`) | [2026-09-27](benchmarks/2026-09-27-b17-insane-m58.md) |
| **K6** ✅ | Cancel reaches a tool that prints nothing | ROADMAP K6 |
| **K7** ✅ | Default threads = one per physical core, RAM-capped: 0.14% smaller, 2,702 vs 5,549 MiB peak | [2026-10-01](benchmarks/2026-10-01-threads-and-ogg.md) |
| **B13a** ✅ | Ogg piped when its own probe says it shrinks: real music **1.112% saved** (was +0.004%) | [2026-10-01](benchmarks/2026-10-01-threads-and-ogg.md) |

---

## 2. Findings worth not rediscovering

### The machine under the repo can change

Windows reported an i7-3540M until 2026-09-27 and an i5-7200U on 2026-10-01.
The disk and profile moved, so `C:\excmp-bench` survived. A timing is a
statement about a CPU. Sizes and peak RAM don't depend on the CPU.

### Both B13 and B14 tools are on GitHub, with published hashes

The handoff used to say balrogg needed a krinkels.org login. **It doesn't.**
The krinkels page says balrogg is GPL-3 and hosted at
`github.com/iczelia/balrogg`, which has CI-built releases with a SHA-256 per
asset. DArc's krinkels page links `github.com/DavidLee18/DArc` (GPL-3.0), which
has the same. Prefer those over forum downloads: a published digest to pin
against, and an E1-style fetch.

### "The docs say X" and "the code does X" are two claims

CLAUDE.md said default threads is 2 for months; the code let 7-Zip take 4.
Measuring what the tool did settled it.

### Passing a switch can turn off a tool's own safety

Forcing `-mmt` disables 7-Zip's built-in fitting of threads to RAM. Auto is
now capped by `ram.lzma2_auto_threads`. **Before forcing any switch, check
what the tool does without it.**

### The probe was right about music; the rule ignored it

Where a measurement and a category rule disagree, the measurement should win,
but only for formats you've measured. That's why B13a is Ogg-only, and why
B18 (c) measures MP3 and video before touching them.

### CI's runner is not the target

Two B17 tests assumed the target's RAM and failed on CI (`'2.7 GB' !=
'2.7 GB'`): the RAM-aware thread cap gave the smaller runner one thread.
**Tests that depend on cores or RAM must pin the machine they describe.** CI
runs on every branch push, so a fix goes green on its branch before `main`.

### Reviews: two lenses plus a skeptic keep paying

17 real defects were confirmed across B17 and 2026-10-01, all after a green
suite, and every one was reproduced before it was fixed.

### Still true

- **Measure the incumbent that fills the slot**, not the familiar tool (B12).
  For B14 that's `precomp → zpaqfranz -m58` (Insane) and `precomp → 7z`
  (Extreme), not plain 7-Zip.
- **Two corpora, or don't quote the first.**
- **Never pin a single timing run, and never the first one.**
- **A silent no-op looks exactly like a negative result.** Exit 0 isn't
  evidence. balrogg's own exit codes are documented (0 ok, 1 refused, 4
  internal error); still trust only `verify_restore`.
- **Render the GUI** (`tools/qa_sweep.py`, both themes) before calling a GUI
  change done.
- **`~/.excmp/calibration.json` is global state**, isolated in `conftest.py`.
- **The archive is not byte-reproducible.** Compare sizes, never digests.

---

## 3. The agenda, in order

### 0. Name the session, then open the download tabs

`/next` step 0 names the session (`set_session_title` is a deferred tool, so
load it with ToolSearch first). Then open these in the built-in browser pane
**for the owner**. They're signed in to krinkels.org already, and sign in to
the others themselves. **Never type credentials or create accounts.**

| tab | what the owner downloads | for |
|---|---|---|
| `https://www.audiokinetic.com/en/download/` | a Wwise **sample project** (it contains `.wem` / `.bnk` banks) | B13 + B6 corpus |
| `https://www.fmod.com/download` | FMOD's **example/sample banks** (`.fsb` / `.bank`) | B13 + B6 corpus |
| `https://krinkels.org/resources/darc-distended-arc.602/` | nothing needed (GitHub has it); for reference | B14 |
| `https://krinkels.org/resources/balrogg-lossless-vorbis-opus-recompressor.601/` | nothing needed (GitHub has it); for reference | B13 |

The owner's downloads land in their Downloads folder: pick them up from
there, pin each SHA-256 on arrival, and copy them into `C:\excmp-bench\`. For
**Oodle (B6)**, use only a copy from a legitimate source the owner has, such as
a game they own installed on this machine. Never a third-party DLL site.

### 1. Fetch the two GitHub tools (one approval)

Ask once, naming file, source and size, then fetch and verify the digest:

| file | size | SHA-256 (GitHub's published digest) |
|---|---:|---|
| `github.com/iczelia/balrogg` release **1.4** (2026-09-10): `balrogg-x86_64.exe` | 247,315 B | `b3a52670bf37eaf941933bf67fbfdcd140638240fa3d20bb9e9bd6c923097db2` |
| `github.com/DavidLee18/DArc` release **v3.0.4** (2026-08-27): `darc-3.0.4-windows-amd64.zip` | 5,032,728 B | `112d021f2ffc981bddb4a94f34f56118ae48f8d40b4e18772a27892a4747b83a` |

Both are GPL-3. That's fine: the repo is private, and they're driven as
subprocesses. If either is to become an app stage, add it to
`excmp/toolfetch.py`'s `TOOL_MANIFEST` with `exe_dir_sha256`, like flac and
qpdf.

### 2. I11 — progress through the D9 restore

Spec: [ROADMAP.md, I11](ROADMAP.md). `ChainProgress` (`gui/progress.py`) caps
at 95% and keeps its peak, so the bar parks there for the whole self-test:
1,556 s of a 3,810 s Silesia job at `-m58`. **Measured: zpaqfranz `x` prints
nothing between its header and its summary**, `-verbose` included (capture in
`C:\excmp-bench\b17\k6\`). There's nothing to parse, so the honest design is a
visible "verifying" phase with elapsed time against the estimate's own D9
share (`_VERIFY_RATE` has a measured Insane key, 0.107 MB/s). TDD,
`tools/qa_sweep.py` in both themes, full suite.

### 3. B13 — balrogg against the 1.112% gate

Corpus: `C:\excmp-bench\b13\music`, 18 files (13 Vorbis, 5 Opus,
169,975,314 B), plus any `.wem`/`.fsb` the owner downloads. Gate: the app
**today** saves **1.112%** end to end (Normal), with 7-Zip per file at 1.52%.
balrogg claims 8–12% on `.ogg` and 3–8% on `.opus`. Usage from its page:
`balrogg e in.ogg out.blr`, `balrogg d out.blr in.ogg`, `-b` for batch,
`-1`…`-9` effort (default `-9`). It refuses files it can't reproduce exactly
(exit 1), so a refusal must fall back to the existing route. **If it wins and
restores every file byte-identically**, it becomes a store-route specialist
like FLAC (B4) and lepton (B2). Measure first, two corpora (music, plus the
game banks if they arrive).

### 4. B14 — DArc against the shipped route

DArc is now a Rust rewrite of FreeArc (`darc` and `unarc`). It must beat what
ships, on both B12 corpora (`C:\excmp-bench\b12\fresh.pcf` and
`programs.pcf`) and Silesia: **Extreme** `precomp → 7z` and **Insane**
`precomp → zpaqfranz -m58` (deflate `.pcf`: 42,852,397 B). Every archive is
restored and SHA-256 compared. FreeArc's strongest methods are the thing to
try.

### 5. B18 — three unmeasured settings

Spec: [ROADMAP.md, B18](ROADMAP.md).
(a) **zstd threads**: `ZstdStage` uses `threads=-1` (all logical). Compare it
against 2 on size, time and RAM.
(b) **`precomp -intense`**: it cost 82,086 B on B16's corpus. Measure with and
without on both corpora.
(c) **MP3 and video**: does the analyzer's probe predict a real gain, as it did
for Ogg? Find a corpus first (search read-only, e.g. the `Downloads-1` tree).
Change routing only if measured.

### 6. B6 — only with an owner-provided Oodle sample

xtool + Oodle. Blocked until a legitimate sample exists (§3, step 0).

---

## 4. Everything else still open

| item | what |
|---|---|
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Insane runs `-m58`.** The owner chose "best for compression".
- **Default threads is one per physical core**, measured and RAM-capped.
- **Code is merged after suite + review + CI green on its branch**, and the
  branch is deleted. The owner doesn't want to review diffs.
- **LOLZ is not integrated.** It reopens only on game/DXT data, against `-m58`.
- **Ogg is piped only when its own probe says it shrinks**, and only Ogg until
  B18 (c) measures more.
- **The repo is private and the OSI rule is retired**; the lossless guarantee
  matters more as a result. **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **SREP stays out**: it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
