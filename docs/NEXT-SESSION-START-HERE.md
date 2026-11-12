# 🚦 START HERE — handoff (written 2026-11-12)

> **B21 is merged** (`9ac2d4e`): GIFs go through Precomp on Extreme and
> Insane, PNG and GIF are recognised by their first bytes, and PNG/GIF have
> time rates of their own. Tests: **1,741 passed, 1 skipped, 4 xfailed**
> locally (12 min 46 s), corpus guard clean; CI green on the branch.
>
> **Next: B21b** (§3). Item 3 of B21, MKV/WebM/M4A under B18's probe rule,
> is written and measured on its own branch, and **the owner held it back
> on 2026-11-12** until the disk preflight stops refusing video folders.
>
> **The owner runs other sessions and Docker Desktop on this machine, and
> Docker and WSL must stay running.** Never stop them yourself. One heavy
> process at a time, below-normal priority, rows logged as they land, the
> full suite last. **Claude Code's low-memory reaper stopped two of B21's
> runs**; when it fires, report it and ask before restarting. **Drive C: had
> 6.4-8.7 GB free** on 2026-11-12 (888 of 894 GB used): enough for the
> suite, but it is what makes B21b's preflight finding bite.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- The full suite with the corpus guard: `C:\excmp-bench\b17\suite.py` from
  a checkout with its own `.venv`; on a worktree,
  `C:\excmp-bench\b19\suite_wt.py <tree>` (it needs `tools\bin` junctioned).
  pytest rotates its own temp (`%TEMP%\pytest-of-<you>`, three runs kept);
  freeze the tree while it runs.
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU
  share against everything else's. Run it beside any timing you mean to pin.
  **"bash" in it is usually another Claude session's `remember` plugin
  hooks** (`post-tool-hook.sh`, up to ~60 s of CPU each): walk
  `ParentProcessId` before blaming anything, and make no tool calls of your
  own while a timing runs.
- **Worktree `..\ExtremeCompressor-b21`** is checked out on
  `b21b-media-probe` (`01296b1`, local only, based on B21's pre-merge
  `a9e030e`: merge `main` into it first). Its `tools\bin` is a junction to
  the main checkout's: **unlink it before removing the worktree**.

---

## 1. What shipped (2026-10-19 – 11-12)

| item | result | record |
|---|---|---|
| **GIF through Precomp** | stored → piped on chains with Precomp. Extreme **25.78%** (64 GIFs, 30.0 MB) and **6.98%** (24, 6.0 MB) against −0.04/−0.08% stored; Insane 11.29%. Every file restored | `docs/benchmarks/2026-10-19-b21-stored-formats.md` §1 |
| **PNG/GIF by content** | `FileInfo.image_format` from the full signature; planner and temp budget read it. **249 JPEGs named `.png`** now reach lepton: 26.57% → **28.12%**, ~5× faster; **8 PNGs named `.jpg`** −0.10% → **6.78%** | §2 |
| **PNG/GIF time** | they had no term since B3 (billed at 1.41 MB/s). Recode kinds now: **PNG 0.21 / 0.76 MB/s, GIF 0.34 / 2.40** (compress / self-test, byte-weighted over three rounds per corpus); all 12 rows of the pinned set inside the range | §4 |
| **Review fixes** | a stored PNG/GIF says Extreme shrinks it; Normal no longer calls a GIF/PNG folder "already compressed, ~0%"; the ≥8 GiB card no longer promises Normal "most of the win"; a piped GIF's `high` is 1.26 (two noisy GIFs came out 1.176 and 1.254) | test file "review fixes" |
| **MKV/WebM/M4A measured** | probe-flagged against not, 7-Zip, every file restored: MKV 3.68 / 2.23%, M4A 7.37 / 1.79%, WebM 6.97 / 0.57% — **rule on `b21b-media-probe`, not merged** | §3 |

Tests added: `tests/test_b21_stored_formats.py` (33: 32 pass, 1 strict xfail).

---

## 2. Findings worth not rediscovering

### The names lied in both directions

B19 recorded 43 PNGs named `.jpg`; a re-scan of the same drives (and of
B19's own listing) finds **10**. The bigger set was the other way round:
**268 JPEGs named `.png`**, which the suffix sent to packJPG. Route and
price by content; scan both directions before quoting either.

### When two corpora disagree, weight by bytes

GIF ran 0.28–0.33 MB/s on one corpus and 0.61–0.92 on the other. The median
of six (0.47) fell between them and under every run of the bigger corpus;
total bytes over total seconds (0.34) is the rate that sums over a mixed
folder. A reviewer recomputing from the raw rows caught it.

### Precomp's cost follows pixels, not bytes

A 1.4 KB PNG became a 704 KB `.pcf`. Small, large-canvas images run ~1.4×
the per-byte estimate on a quiet machine; the slow side holds it.

### Insane on pixel-expanding media is estimated low

Insane on 6 MB of GIFs ran **564.7 s against a 333 s high**, no paging.
That's the opposite direction from packJPG/packMP3 output (2–3× high), and
not explained by expansion (that corpus's `.pcf` was 1.14×). Strict xfail
`test_insane_on_gifs_holds_the_one_measured_run`.

### Piping more media raises the disk floor

The preflight's floor is `piped × 2 + total + out`. Piping 1.67 GB of MKV
takes the owner's video folder from 3.85 to 6.97 GiB, so with 4–7 GB free
a job that used to store is refused outright. MP4/MOV since B18 too. This
is why B21b waits.

### Still true

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
  `&&` chain (B21 lost a push to it).

---

## 3. Next: B21b, MKV/WebM/M4A with a disk fallback

Spec: `docs/ROADMAP.md`, B21b; data in the B21 record §3. The rule is
done (`01296b1`: `.mkv/.webm/.m4a` in `_PROBE_DECIDES`, tests, two older
tests moved to AVI/WMV/AAC). Before it merges:

1. **Store instead of refuse.** In the engine's compress preflight
   (`engine._check_compress_space` / `compress_space_needs`), when the plan
   doesn't fit but the same files with the probe-decided media stored
   would, store them and say so in the result, rather than refuse a job
   for 2–4%. TDD: the reviewer's repro is the owner's 16 MKVs as
   `FileInfo`s against a free-space figure between the two floors. It
   protects MP4/MOV too. Lossless either way; keep the SHA-256 gate as is.
2. **The recommendation.** A folder that is mostly probe-piped video gets
   Extreme ("lots of compressible data") while the table flags Extreme as
   no better than Normal (`recommend_profile` reads
   `floor_pipeline_fraction`; `recommend_with_estimates` keeps an
   `upper_bound` row). True of MP4 since B18.
3. **Optional:** keep pass-through video out of Extreme's calibration (one
   run learned 3.1 MB/s against the 1.41 prior).

Then: e2e on `C:\excmp-bench\b21\{mkv,webm,m4a}` (hard links;
`run_media_e2e.cmd`), the full suite, review, push, CI, merge.

Then **B22**: Insane on recoded media (JPEG, MP3, GIF, PNG; three quiet
runs each) and a fixed per-job cost.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates come out under the range); no fixed per-job cost (store-only GIF jobs 17–20 s against 0.1–0.6 s; photo folders 15–19% under); Insane on recoded media (above); a piped file under 3 MiB is one probe sample, so `low` = `expected` (M4A came in 12.7 KB under); the store-only overhead estimate misses by a few bytes both ways (16 B low on 25 M4As) |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job |
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

- **PNG and GIF are routed and priced by content** (`image_format`, B21);
  a hand-built `FileInfo` (`None`) is taken at its name.
- **GIF goes to Precomp on Extreme/Insane**, stored on Fast/Normal. Its
  `high` is 1.26; its `expected` stays the probe's reading.
- **Recode rates are byte-weighted when corpora disagree** (B21).
- **MKV/WebM/M4A join the probe rule** (measured, decided) **once the disk
  fallback lands** (owner, 2026-11-12). ffprobe isn't needed.
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
  decides, as for MP4, MOV and Ogg.
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
