# 🚦 START HERE — handoff (written 2026-11-13)

> **B21b is merged** (`d78ec62`): MKV, WebM and M4A join B18's probe
> rule, and a job whose piped media don't fit the disk now **stores them
> instead of refusing**. Tests: **1,769 passed, 1 skipped, 4 xfailed**
> locally, corpus guard clean; CI green on the branch.
>
> **Next: B22** (§3): Insane's rate on recoded media (JPEG, MP3, GIF, PNG)
> and a fixed per-job cost in the time model.
>
> **The owner runs other sessions and Docker Desktop on this machine, and
> Docker and WSL must stay running.** Never stop them yourself. One heavy
> process at a time, below-normal priority, rows logged as they land, the
> full suite last. **Claude Code's low-memory reaper killed B21b's first
> suite 23 s in** (3.2 GB free); when it fires, report it and ask before
> restarting; the three-part run below passed.
> **Drive C: had 58.9 GB free** on 2026-11-13 (8.33 GB of old bench output
> went to the Recycle Bin on 2026-11-12; list in
> `C:\excmp-bench\cleanup-2026-11-12.tsv`).
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **The full suite on a shared machine: `C:\excmp-bench\b21\suite_parts.py
  <tree> [--fresh]`.** It takes the corpus snapshot, runs the test files in
  three round-robin parts (one pytest each), then compares. A part that
  passes leaves `suite-parts\PART-n-OK`, so after a reap a rerun without
  `--fresh` runs only the parts left. B21b's run: **37 min 48 s** (8:13,
  19:49, 9:23) at below-normal beside WSL and two other Claude sessions; quiet,
  the whole suite was ~13 min. Start it below normal from creation:
  `cmd /c 'start "" /b /belownormal /wait <venv python> C:\excmp-bench\b21\suite_parts.py <tree> --fresh > <log> 2>&1'`.
  `b17\suite.py` (own `.venv`) and `b19\suite_wt.py` (worktree) still work
  in one piece.
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU
  share against everything else's. Run it beside any timing you mean to pin.
  **"bash" in it is usually another Claude session's `remember` plugin
  hooks** (`post-tool-hook.sh`, up to ~60 s of CPU each): walk
  `ParentProcessId` before blaming anything, and make no tool calls of your
  own while a timing runs.
- **Worktree `..\ExtremeCompressor-b21`** is kept, detached at `main`
  (its branch is merged and deleted). For B22: `git switch -c <branch>` in
  it. Its `tools\bin` is a junction to the main checkout's: **unlink it
  before removing the worktree**.

---

## 1. What shipped (2026-11-12 – 11-13)

| item | result | record |
|---|---|---|
| **MKV/WebM/M4A under the probe rule** | `.mkv/.webm/.m4a` in `planner._PROBE_DECIDES`: probe-flagged against not, 7-Zip, every file restored, MKV 3.68 / 2.23%, M4A 7.37 / 1.79%, WebM 6.97 / 0.57% | `docs/benchmarks/2026-10-19-b21-stored-formats.md` §3 |
| **Store instead of refuse** | `engine._plan_that_fits`: when the plan doesn't fit the disk, the same files with the probe-flagged media stored (`plan(probe_media=False)`) are tried; if that fits, the job runs and its first warning says how many files and MiB were stored and how much more space would recompress them. Protects MP4/MOV too (since B18). Each stored file's reason in the manifest says it was the disk | §5 |
| **No Extreme for a video folder** | `AnalysisSummary.floor_probe_bytes` (bytes piped only by the probe) don't count toward Extreme; a mostly-video folder gets Normal, "Extreme adds only time on video". An MP3 folder still gets Extreme (packMP3) | §5 |
| **Gain note** | a mostly-video folder says "a few percent, no more" | §5 |
| **Chip bug (older than B21)** | the intake chip showed the previous drop's total or "0 B" when the recommendation didn't move; it refreshes on every analysis now | §5 |
| **Review fixes** | the free-space gap was quoted 2× low (the floor counts piped bytes twice); per-file reason missing; a double refusal named the lean plan's floor (now the chosen plan's own); a mixed folder's note; MP3 without Precomp counted as recodable; "only time" shown beside PNG | test file |

Tests added: **28** — `tests/test_b21b_media_fallback.py` (19),
`tests/test_b21_stored_formats.py` (7, the container cases),
`tests/test_gui_compact.py` (2, the chip). Two older tests moved from
MKV/WebM/M4A to AVI/WMV/AAC (`test_b18_media_probe.py`,
`test_b13_ogg_probe.py`).

---

## 2. Findings worth not rediscovering

### The disk floor counts piped bytes twice

The preflight's floor is `piped × 2 + total + out` (staging plus the tar).
Piping the owner's 1.67 GB of MKV took the folder's floor from 3.85 to
6.97 GiB. So "free X more" is about twice the files' size, never their size:
the first draft quoted it 2× low.

### A widget fed by the summary must refresh on every analysis

The intake chip read the summary but was refreshed only when the
recommendation moved the selected profile. A second drop with the same
recommendation kept the first drop's total. Rendering it found this, not
the suite.

### Split the suite when RAM is short

At 3.2 GB free the one-piece suite was reaped 23 s in; the next run, in
three parts, passed.
Part 2 took 19:49 alone: the runtime on this machine depends on what else
is running, not on the tests.

### Still true

- **Insane on pixel-expanding media is estimated low** (GIF 564.7 s against
  a 333 s high), **on packJPG/packMP3 output 2–3× high**. Both pinned by
  strict xfails.
- **When two corpora disagree, weight by bytes**; **route and price by
  content**, not name; **Precomp's cost follows pixels, not bytes**.
- **Contended priors are wrong by a factor**; pin quiet medians and let the
  range's high side carry contention.
- **`recoded_seconds`, not `RecodeCost`, answers "how long do these files
  take".**
- **The venv's `python.exe` is a launcher**; untyped ctypes
  `SetPriorityClass` silently fails; write files with Edit/Write and
  `unix2dos` them (the repo is CRLF).
- **Measure the incumbent that fills the slot**, **two corpora**, **render
  the GUI**, **CI's runner is not the target**, **check a test asserts the
  outcome**, and **a `grep -c` that finds nothing exits 1** and stops an
  `&&` chain.

---

## 3. Next: B22, Insane on recoded media and a per-job cost

Spec: `docs/ROADMAP.md`, B22.

1. **Insane's rate on recoded media.** Insane (`-m58`) on Precomp/lepton
   output is priced from the generic chain rate:
   - **packJPG/packMP3 output: 2–3× high** (two strict xfails,
     `tests/test_quiet_rates.py`);
   - **GIF: 564.7 s against a 333 s high** (strict xfail
     `test_insane_on_gifs_holds_the_one_measured_run`,
     `tests/test_b21_stored_formats.py`);
   - **PNG: unmeasured** (~50× Precomp expansion).

   Three quiet runs per kind, `contention.ps1` beside each, byte-weighted
   when corpora disagree. Corpora already on disk (hard links or copies,
   read-only use): JPEG `C:\excmp-bench\b19\jpg-design`, `jpg-phone`,
   `jpg-web`; MP3 `C:\excmp-bench\b18\mp3-music`, `mp3-misc`; GIF
   `C:\excmp-bench\b21\gif-dl`, `gif-dl1`; PNG `C:\excmp-bench\b21\png-dl`,
   `png-dl1`. Timing harness to copy: `b21\run_timing3.cmd` +
   `contention_by_row.py`. Each strict xfail should flip to a pass; remove
   its marker in the same commit.
2. **A fixed per-job cost.** Store-only and small jobs carry 10–50 s the
   model doesn't have (B21: stored GIF folders 17–20 s against 0.1–0.6 s;
   photo folders 15–19% under). Measure a near-empty job per profile
   (three runs) and add it as a constant term; check it doesn't push the
   big-folder rows out of their ranges.

Then the full suite (`suite_parts.py`), review, push, CI, merge.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates come out under the range); a piped file under 3 MiB is one probe sample, so `low` = `expected` (M4A came in 12.7 KB under); the store-only overhead estimate misses by a few bytes both ways (16 B low on 25 M4As) |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job; **pass-through video teaches Extreme a chain rate** (one MKV run learned 3.1 MB/s against the 1.41 prior) |
| **B5's 0.55** | a mean plus margin, not a worst file; re-check file by file under B18's rule |
| **Precomp memory** | grows with pixels, not file size (5000² CMYK: 220 MiB; a design job's Precomp reached 791 MB) |
| **GUI** | with one category, the Details treemap is a single huge block (seen rendering B21; not fixed) |
| **Tests** | `tests/test_edge_cases.py:1` raises a `SyntaxWarning` (unescaped `\.` in its docstring) |
| **I11 leftovers** | zpaqfranz reports 100% at stage start (Insane's bar freezes); a store-only job's bar jumped |
| **Media** | HEIC/WebP: no lossless recompressor; AVI/WMV/FLV/AAC unmeasured |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **B6** | only with an owner-provided Oodle sample; it also settles `-intense` |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **MKV/WebM/M4A are under the probe rule** with MP4, MOV and Ogg (B21b).
  ffprobe isn't needed.
- **When the plan doesn't fit the disk, probe-flagged media are stored, not
  the job refused** (B21b). Lossless either way; the job says what it
  stored. If even that doesn't fit, the refusal is the chosen plan's own.
- **A mostly-video folder is recommended Normal**; probe-only bytes don't
  count toward Extreme. MP3 on a Precomp chain is recoded and does count.
- **PNG and GIF are routed and priced by content** (`image_format`, B21);
  a hand-built `FileInfo` (`None`) is taken at its name.
- **GIF goes to Precomp on Extreme/Insane**, stored on Fast/Normal. Its
  `high` is 1.26; its `expected` stays the probe's reading.
- **Recode rates are byte-weighted when corpora disagree** (B21).
- **Time priors are quiet medians; contention goes in the range's high
  side** (2026-10-17). The low end is the chain's.
- **Lepton's constants are phase-true**; the gap is a missing per-job cost.
- **The container rate stays 0.46 MB/s.**
- **"Seconds"/"minutes" in a suggestion reads the whole job's estimate.**
- **Lepton keeps every JPEG it accepts; Precomp gets only what lepton
  refuses** (B19), by content.
- **Calibration learns rates, not the factor** (B19).
- **Containers are piped by structure, not name** (B20).
- **Precomp keeps `-intense`** (B18); B6's game data is the only thing that
  reopens it.
- **Every MP3 goes to Precomp on Extreme/Insane**; on Fast/Normal the probe
  decides, as for MP4, MOV, MKV, WebM, M4A and Ogg.
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
