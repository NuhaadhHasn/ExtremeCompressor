# 🚦 START HERE — handoff (written 2026-10-17, early morning)

> **The owner's measurement agenda is done.** `main` is at `7b698f0` plus docs:
> **B19 and B20 merged** after one full suite on the B20 tree; **Insane on
> the design JPEGs** and **B20's big containers** measured and recorded;
> and the **quiet-machine re-measure** done and merged (`quiet-rates`): the
> contended time priors replaced from medians of three, the range given a
> slow-side spread for Precomp's recoders, and a suggestion defect fixed on
> the way. Tests: **1,709 passed, 1 skipped, 3 xfailed** locally, corpus guard clean; CI green on the branch (`c7835a7`).
>
> **Only B6 is left of the old agenda, and it waits on the owner's Oodle
> sample.** So the next session starts **B21** (§3): the formats still
> stored that nobody has measured, baseline first.
>
> **The owner runs other sessions and Docker Desktop on this machine, and
> Docker and WSL must stay running.** (They were stopped on the night of
> 2026-10-16, by the owner, which is what made the re-measure quiet. Never
> stop them yourself.) One heavy process at a time, below-normal priority,
> rows logged as they land, the full suite last. **Claude Code's low-memory
> reaper stopped a run that night with 4.1 GB free 30 s earlier**; when it
> fires, report it and ask before restarting.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- The full suite with the corpus guard: `C:\excmp-bench\b17\suite.py` from
  a checkout with its own `.venv`; on a worktree,
  `C:\excmp-bench\b19\suite_wt.py <tree>` (it needs `tools\bin` junctioned).
  Clear `%TEMP%\pytest-of-<you>` first, and freeze the tree while it runs.
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU
  share against everything else's, the free RAM and the bench's largest
  working set. Run it beside any timing you mean to pin. Defender's process
  is protected and doesn't appear in it.
- A detached worktree `..\ExtremeCompressor-pre-b19` at `2d8b235` (the
  `main` B19 started from) was used for incumbent rows and removed after the merge (junction unlinked first). No worktrees are left.

---

## 1. What shipped (2026-10-16 night – 10-17)

| item | result | record |
|---|---|---|
| **B19 + B20 merged** | one suite on the B20 tree: 1,684 passed, 1 skipped, 1 xfailed, corpus guard clean | `73024bb`, `763f046` |
| **Insane, design JPEGs** | **42.827%** against Extreme's 42.829%: Insane gains nothing on packJPG output; the incumbent stores them (3.48%) | B19 record, "Insane, measured that night" |
| **B20, big containers** | two AABs (121 MB) **−0.001% → 65.56%**, the 36.8 MB ODT **→ 24.55%**; all restored. Per file 0.668/0.672/0.754, under the 0.89 ceiling | B20 record §8 |
| **Quiet re-measure** | 37 rows, 0 mismatches. **packJPG/packMP3 had been 2.5–3.4× slow** (now 1.03/1.18 MB/s compress, 1.02/1.49 self-test); lepton 3.25 MB/s + 0.043 s/file pack, 6.2 + 0.036 decode; **balrogg's decode had been 1.6× fast** (1.5 → 0.94 MB/s); the container rate (0.46) stands | `docs/benchmarks/2026-10-17-quiet-remeasure.md` |
| **The range** | the recoders' paced time widens the **high** side by `_RECODE_SPREAD = 4.0`; the low side stays the chain's; quiet rows outside their range 12 → 4 of 35, contended rows unchanged (2 of 13) | same |
| **Suggestion defect** | "the full chain costs seconds" was told to CMYK-, MP3- and Ogg-heavy small folders beside a table saying minutes; it reads the whole job's expected time now | same, §3 |

Tests added: `tests/test_quiet_rates.py` (27: 25 pass, 2 strict xfails).

---

## 2. Findings worth not rediscovering

### Contended priors are wrong by a factor, not a margin

The B19 afternoon (WSL's `vmmem` near 50% of the CPU) put Precomp's recoders
at a third of their quiet speed, and balrogg's decode the other way (the CLI
per-file rate was faster than the app's D9). **Pin from quiet medians, and
let the range's high side carry contention.** Spreading both ways emptied
the low end (design: 71.5 s low, fastest run 279 s).

### An "extra over the chain" is not "how long these files take"

`RecodeCost` holds what the recoders add beyond the chain's rate. At the
contended priors the extra happened to be most of the time, so a sentence
reading it was right by accident; at the measured rates it's 13 s of 98.
`estimate.recoded_seconds` gives the whole paced time. Anything that says
"seconds" or "minutes" reads a whole-job estimate.

### Insane on recoded media is estimated 2–3× high

`precomp+zpaqfranz` is billed at Silesia's 0.091 MB/s; on packJPG/packMP3
output the pipeline ran at 0.26 and 0.19 MB/s (one quiet run each), so quiet
runs finish under the low end. Strict xfails in `tests/test_quiet_rates.py`.
And Insane bought nothing over Extreme on the design JPEGs.

### Phase-true constants can make a whole job look worse

Lepton's re-fit matches its pack and D9 phases exactly, and photo folders
now come out 15–19% under as a whole: 6–10 s per job sits outside the
phases the model knows. The fix is a per-job cost, not a fudged rate.

### Solid archives beat the per-file estimate on near-duplicates

Two React Native AABs: 0.67 each per file, 0.344 together, under the range's
low end. The estimator is per file (known gap); an under-estimate is the
safe direction.

### Still true

- **The venv's `python.exe` is a launcher**; untyped ctypes
  `SetPriorityClass` silently fails; write test files with the Edit/Write
  tool and `unix2dos` them (the repo's files are CRLF).
- **Measure the incumbent that fills the slot**, **two corpora**, **never pin
  a contended timing**, **render the GUI**, **CI's runner is not the
  target**, **check a test asserts the outcome, not the mechanism** (B19's
  edited bar test had stopped being able to fail; the review caught it).

---

## 3. Next: B21, the stored formats nobody has measured

Spec: `docs/ROADMAP.md`, B21. **Measure the baseline first**
(memory: three of four proposed tools lost to the route already there), two
corpora, per file then end to end, every file restored and SHA-256 compared.
In this order:

1. **GIF through Precomp.** Precomp's `-t` lists `F = GIF`; GIFs are stored
   today (122 in Downloads, 33 MB; 93 in Downloads-1, 7.6 MB). Measure
   `precomp → 7z` per file against storing, as B19 did for JPEG and B20 for
   zips (`C:\excmp-bench\b20\zip_perfile.py` is the pattern).
2. **PNG by content.** Precomp gets PNGs by suffix (`_PRECOMP_MEDIA`); 43
   files named `.jpg` on the owner's drives are PNGs and are stored at 0%.
   B3 measured 38% on PNG. Route by the first bytes, as the store route does
   for JPEG (`FileInfo.is_jpeg`).
3. **MKV (16 files, 2.07 GB in Downloads-1), WebM, M4A (26, 356 MB)**: the
   B18/B19 probe rule's measurement (`C:\excmp-bench\b19\setup_mov.py` and
   B18's `b18_media.py` are the pattern). ffprobe (installed, unused) only if
   the zstd probe turns out blind there.

Then, as B22 if B21 is done: **Insane's rate on recoded media** (three quiet
runs each on JPEG and MP3 output, which flips the xfails) and **a fixed
per-job cost** in the time model.

Downloads aren't needed for any of it. Ask once per batch if they become so.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates come out under the range: the AABs); no fixed per-job cost (photo folders 15–19% under, 64 KB jobs, two 6 MB container runs 3–4× slow for no visible reason); Insane on recoded media 2–3× high; calibration: the recode extras sit on a fixed 1.41 MB/s base and `summarize` reads default rates where the table reads calibrated ones (latent until a Precomp rate is learned) |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job |
| **B5's 0.55** | a mean plus margin, not a worst file; re-check file by file under B18's rule |
| **Precomp memory** | grows with pixels, not file size (5000² CMYK: 220 MiB; a design job's Precomp reached 791 MB working set on the quiet night) |
| **I11 leftovers** | zpaqfranz reports 100% at stage start (Insane's bar freezes); a store-only job's bar jumped (check whether B19's lepton pack band fixed it) |
| **Media** | HEIC/WebP: no lossless recompressor in the toolchain |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **B6** | only with an owner-provided Oodle sample; it also settles `-intense` |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Time priors are quiet medians; contention goes in the range's high
  side** (2026-10-17). The low end is the chain's.
- **Lepton's constants are phase-true** even though whole photo jobs come
  out under; the gap is a missing per-job cost.
- **The container rate stays 0.46 MB/s**: the big containers confirmed it,
  the small samples are noise.
- **"Seconds"/"minutes" in a suggestion reads the whole job's estimate.**
- **Lepton keeps every JPEG it accepts; Precomp gets only what lepton
  refuses** (B19).
- **Calibration learns rates, not the factor** (B19).
- **Containers are piped by structure, not name** (B20); the suffix list
  stays for what the probe can't see (`.gz`).
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
- **Before deleting anything, inventory it completely** (owner's global rule,
  2026-10-17): hidden files, `git status --ignored`, junctions unlinked first.
