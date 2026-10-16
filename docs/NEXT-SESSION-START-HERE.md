# 🚦 START HERE — handoff (written 2026-10-16, evening)

> **`main` is unchanged since `2d8b235`** apart from docs. **B19 is built,
> reviewed and pushed on branch `b19-media`** (worktree
> `..\ExtremeCompressor-b19`), **waiting only for the local full suite**,
> which the owner paused on 2026-10-16 along with all heavy CPU/RAM work.
> CI runs on the branch push.
>
> **Next session is an owner agenda**, in this order (§3 has each spec).
> Items 1–3 are heavy: start each only when the owner says the machine
> allows, and **never stop a heavy run that is already going** (owner,
> 2026-10-16: "pause" means start nothing new).
> 0. **Name the session** (`/rename`; the title tool isn't in this client).
> 1. **Full suite on `b19-media`, then merge it.**
> 2. **Insane on the design JPEGs** (branch and `main`), for the record.
> 3. **Quiet-machine re-measures**: Ogg restore, packMP3, and now packJPG and
>    lepton (all four are contended priors in the estimator).
> 4. **B20: zip-structured containers Extreme stores by mistake** (EPUB,
>    ODT/ODS/ODP, AAR, AAB, NuGet, APPX): measure, then route. Light to
>    build, needs a Precomp measurement first.
> 5. **B6**, only with an owner-provided Oodle sample.
>
> **The data limit is lifted** (owner, 2026-10-16): downloads are allowed
> again. Ask once per batch, as always.
>
> **The owner runs other sessions and Docker Desktop on this machine, and
> Docker and WSL must stay running.** `vmmem` took ~50% of the CPU on
> 2026-10-16; 2.8–4.6 GB was free. One heavy process at a time,
> below-normal priority (checked with `Get-Process`), rows logged as they
> land, and the full suite last.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **On a worktree use `C:\excmp-bench\b19\suite_wt.py <tree>`** (corpus guard
  around the suite, the main venv run inside the tree), below-normal from
  creation; its docstring has the exact command. `b17\suite.py` only works
  from a checkout with its own `.venv`.
- **A worktree has no `tools\bin`** (untracked): junction it, or tool tests
  skip and Insane silently runs as Extreme. `..\ExtremeCompressor-b19\tools\bin`
  is already a junction to the main checkout's.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the tree before
  starting.** Editing `docs/` mid-run is fine; nothing else is.

---

## 1. What B19 is (branch `b19-media`, 6 commits on `2d8b235`)

Record: `docs/benchmarks/2026-10-16-b19-mov-jpeg.md` (on the branch).
Every archive restored and SHA-256 compared; 0 mismatches anywhere.

| | what | result |
|---|---|---|
| (a) | `.mov` joins B18's probe rule | flagged MOVs 1.01% under 7-Zip, the rest 0.046%; 72 KB on 909 MB end to end |
| (b) | **JPEGs lepton refuses go to Precomp's packJPG** on Extreme/Insane | lepton refuses CMYK and any side > 16,386 px (measured on 0.5.8); the store route kept them raw. **Design folder 3.48% → 42.83%, other CMYK −0.01% → 44.67%** at Extreme. Piping *every* JPEG lost on web images (18.80% vs 21.14%) |
| (c) | **the estimate models lepton** | it had priced every photo folder at 0% (range +28.6% above the real archive); now a range with lepton's time, and the card no longer calls photos "already compressed" |
| (d) | container overhead | store-only estimates were *under* the real archive (3,173 B on 64 files): each stored name is now booked twice |
| (e) | **calibration wrote a ratio into B8's slope** | since 2026-09-08; this machine's store made Normal 33% pessimistic. Ratio learning removed; rates still learn |
| review | two lenses + a skeptic | ceilings now use each packer's worst file; **Precomp's packJPG/packMP3 time is modelled** (`recode_cost`); the Fast suggestion's sentences match the table; JPEG-named-`.ogg` double count; no integrity or lossless defects |

Tests: `tests/test_b19_media.py` (85), plus `test_calibrate.py`,
`test_b18_media_probe.py` and `test_b13_estimate.py` adjusted. The related
suites pass (351 tests in the last targeted run); **the full suite has not
run on the branch.** The GUI was rendered in both themes at each step
(`C:\excmp-bench\b19\render_b19.py`, images in `render\`).

---

## 2. Findings worth not rediscovering

### A JPEG's frame header can sit half a megabyte in

Print CMYK files carry their ICC profile first: the frame sat at 565 KB in
every one. `jpeg.frame_header` walks the markers. Never trust a fixed-size
head for JPEG structure.

### Under a ceiling, every term is a worst case

On a Precomp chain with anything piped, `expected` is shown as "≤ X". B18
learned it for MP3; B19's lepton term and B13's Ogg term still used means
until the Windows 4K wallpapers plus one text file came out 96 KB over.
Store-route packers now price at their worst file there
(`_LEPTON_CEILING`, `_PACK_CEILING`).

### Lepton has no effort setting, so it doesn't separate the profiles

Anything that ranks profiles must treat lepton's bytes as the same in every
row. Counting them as "shrinkable" once made a photo folder suggest Extreme
at 3× Fast's RAM for the same archive. They stay in the floor
`recommend_profile` reads; balrogg's Ogg doesn't (its effort rises).

### Check that a test asserts the outcome, not the mechanism

`test_the_achieved_ratio_is_learned_too` checked that the stored factor
moved and never looked at the estimate, so it pinned a backwards feedback
loop in place for five weeks.

### Files named `.jpg` aren't all JPEGs

53 of 6,686 here were PNG, WebP or macOS forks. The store route claims by
content; the estimate now does too (`FileInfo.is_jpeg`).

### Still true

- **The venv's `python.exe` is a launcher**; untyped ctypes
  `SetPriorityClass` silently fails; write test files with the Edit tool.
- **Measure the incumbent that fills the slot**, **two corpora** (B19's
  header-refused JPEGs are one scan of one drive, recorded as thin), **never
  pin a contended timing** (B19's lepton/packJPG/packMP3 rates are priors
  with wide ranges), **render the GUI** (both B19 GUI defects passed every
  test), **CI's runner is not the target**.

---

## 3. The agenda, in order

### 1. Full suite on `b19-media`, then merge (heavy: owner's go first)

`suite_wt.py C:\Users\nuhaa\PycharmProjects\ExtremeCompressor-b19`, below
normal. Every test must pass; the corpus guard must be clean. Expected
count: 1,549 passed on `main` plus B19's additions (`test_b19_media.py` has
85; a few skip without the bench samples in `C:\excmp-bench\b19\samples` or
the Windows wallpapers). **Watch for estimator tests that pinned the old
overhead or calibration behaviour** in files the targeted runs didn't cover
(e.g. `test_estimate_backtest.py`, which reads the real Programs corpus).
Then: CI green on the branch (`gh run list --branch b19-media`), `git merge
--no-ff b19-media` on `main`, push, delete the branch locally and on GitHub,
`git worktree remove ..\ExtremeCompressor-b19` (remove the `tools\bin`
junction first with `rmdir`, not a recursive delete, which would follow it
into the main checkout's binaries). Update CLAUDE.md's test count.

### 2. Insane on the design JPEGs (heavy)

`C:\excmp-bench\b19\run_e2e2.cmd` has the commands: `b19_app.py
<corpus> <out> <label> insane` with `EXCMP_REPO` set to the worktree for the
branch row, and without it for `main`. The branch's Extreme row exists
(42.829%); the Insane run was stopped in its self-test on 2026-10-16. Add
both rows to the B19 record.

### 3. Quiet-machine re-measures (only with the owner's say-so that it's quiet)

Each replaces a contended prior in `excmp/estimate.py`; re-pin only from a
median of three:
- **B13's Ogg restore rate** (`_PACK_DECODE_RATE`, 1.5 MB/s):
  `C:\excmp-bench\b13\b13_app.py C:\excmp-bench\b13\music <out> quiet normal`.
- **packMP3 and packJPG** (`_RECODE_RATE`, `_RECODE_VERIFY_RATE`): B18's
  `mp3_perfile.py`/`b18_app.py` and B19's `b19_app.py` on `jpg-cmyk2` and
  `jpg-design`, Extreme; the phase times come from the rows' `events`.
- **lepton** (`_LEPTON_PACK_RATE` etc.): `b19_app.py` on `jpg-phone` and
  `jpg-web`, any profile.

### 4. B20: zip-structured containers Extreme stores (owner's agenda item, new)

Found 2026-10-16. B5's structural probe (`analyzer.probe_expandable`) knows
`.epub/.odt/.ods/.odp` are zips with deflated members, but the planner pipes
by a suffix list (`_PRECOMP_EXPANDABLE`) that lacks them, so a real EPUB is
**stored at Extreme with "already compressed … ~0%"**. Reproduced with a
synthetic high-entropy EPUB/ODT/ODS/ODP. Zip-structured files under other
names (AAR, AAB, NuGet, APPX, VSIX, WHL, WAR, CBZ, XPI) aren't even probed.
On the owner's drives: 31 EPUB (326 MB), 102 AAR (114 MB), 2 AAB (121 MB),
10 NuGet (42 MB), 14 ODT/ODS (37 MB), 6 APPX (26 MB)
(`C:\excmp-bench\b20\zipfamily.tsv`).
**Measure first** (B18's lesson: the ceiling must be the worst file):
`precomp -cn -intense → 7z` per file on samples of EPUB and AAR at least,
two folders each, against storing. Then: probe any file whose head is a zip
local header, pipe `info.expandable` files on a Precomp chain *in addition
to* the suffix list (`.gz` relies on the list), and give the new types a
measured ratio. Keep the encrypted-zip case in mind (B5 §4: a 263 MB
encrypted `.zip` expands to nothing).

### 5. B6, only with an owner-provided Oodle sample

Unchanged. It also settles **`-intense`** (B18): measure both on real game
data.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Media not yet measured** | MKV (16 files, 2.07 GB in Downloads-1), WebM, M4A (26, 356 MB): still stored. HEIC/WebP: no lossless recompressor in the toolchain |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job |
| **Estimator** | per-file only: near-duplicate files make a corpus come out *under* its range (B18) |
| **Precomp memory** | grows with pixels, not file size (5000² CMYK: 220 MiB). 7-Zip's 3 GB still dominates Extreme's quoted peak; a very large print sheet could change that |
| **I11 leftovers** | zpaqfranz reports 100% at stage start (Insane's bar freezes); a store-only job's bar jumped (B19's lepton pack band may fix it: check) |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Lepton keeps every JPEG it accepts; Precomp gets only what lepton
  refuses** (B19): piping every JPEG lost on web images and cost 4.5× the
  time on photos.
- **Calibration learns rates, not the factor** (B19), until a slope can be
  fitted properly.
- **Precomp keeps `-intense`** (B18); B6's game data is the only thing that
  reopens it.
- **Every MP3 goes to Precomp on Extreme/Insane**; on Fast/Normal the probe
  decides, as for MP4, MOV and Ogg. MKV/WebM/M4A stay stored until measured.
- **zstd keeps `threads=-1`** by default; an explicit count is honoured and
  capped.
- **DArc is not integrated. LOLZ is not integrated. SREP stays out.**
- **Insane runs `-m58`, and balrogg `-9` on Insane.**
- **Default threads is one per physical core** for 7-Zip and zpaqfranz.
- **Code is merged after suite + review + CI green on its branch**, and the
  branch is deleted. The owner doesn't want to review diffs.
- **With balrogg installed, Ogg stays on the store route and is repacked.**
- **The repo is private and the OSI rule is retired**; the lossless
  guarantee matters more as a result. **Never weaken verification to fit a
  tool in.**
- **No AI attribution in commit messages, ever.**
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
