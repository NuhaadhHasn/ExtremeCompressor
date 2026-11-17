# 🚦 START HERE — handoff (written 2026-11-17)

> **B22 is merged** (`ba84077`): Insane prices **JPEG, MP3, GIF and PNG at their own
> measured rates**, and every job carries a **setup cost** (1 s; 2 s at
> Insane). Tests: **1,826 passed, 2 skipped, 1 xfailed** locally, corpus
> guard clean (it covers `Programs` only now, see §2); CI green on the branch.
>
> **Next: B23** (§3): calibration and the open list. **There is no owner
> agenda.** One defect found by rendering is waiting for the owner's pick (§3).
>
> **The machine is shared and tight on memory.** Claude Code's low-memory
> reaper stopped background work **five times** this session at 4-7 GB free,
> beside three Claude sessions and Firefox (not Docker: no Docker process was
> running). The notice says to restart only when asked; **ask, then restart**
> (the owner said yes each time). Rows and suite parts survive a reap: the
> Insane batch skips finished rows (`C:\excmp-bench\b22\run_insane.cmd`), and
> `suite_parts.py` skips parts with a `PART-n-OK` marker.
> **Launch background work through a `.cmd` file**, not `cmd //c 'start ...'`
> from the shell: the latter fails with "Access is denied".
> **Drive C: had 118 GB free** on 2026-11-17.
>
> **The owner is cleaning up the machine** (log: `C:\DevCache\CLEANUP-LOG.md`;
> read it before touching disk space, installed software or caches). This
> session moved 673,626,040 B of dead bench staging to
> `C:\DevCache\_trash\2026-11-17-excmp-b22-staging\` (the log has the entry).
> **`C:\excmp-bench\b19` and `b21` are read by the tests: keep.**
> `C:\Program Files\precomp` and `srep` are still the app's only copies.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **The full suite on a shared machine: `C:\excmp-bench\b21\suite_parts.py
  <tree> [--fresh]`**, launched from a `.cmd` file (`C:\excmp-bench\b22\
  run_suite.cmd` is the template). It takes the corpus snapshot, runs the test
  files in three round-robin parts, then compares. B22's run: 5:42 + 3:30 +
  6:44 (about 16 min at below-normal beside other sessions).
  **Run every test file the change could touch, not a guessed subset before
  the suite**: B22's four failures were exact-number assertions in
  `test_b13_gui.py`, `test_b19_media.py` and `test_i11_verify_progress.py`
  that a targeted run skipped.
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU share
  against everything else's. It is reaped like everything else; its log
  stopped at 12:51 on 2026-11-17. "bash" in it is usually another session's
  hooks; **`find` in it was a runaway search for 16 hours** (see §2).
- **Worktree `..\ExtremeCompressor-b21`** is kept (detached at `main` once the
  branch is deleted). For the next item: `git switch -c <branch>` in it. Its
  `tools\bin` is a junction to the main checkout's: **unlink it before
  removing the worktree**.

---

## 1. What shipped (2026-11-16 – 11-17)

| item | result | record |
|---|---|---|
| **Insane per kind** | JPEG lepton refuses **0.277 / 0.312 MB/s** (compress / self-test), MP3 **0.171 / 0.221**, GIF **0.084 / 0.141**, PNG **0.029 / 0.034**. The old chain rate (0.091 / 0.107) was 3.1x slow on JPEG, 2x on MP3, 1.2x on GIF and **2.5x fast on PNG** (its high end sat under the measured time). Quiet rows land within 14% of expected on seven corpora and 32% on the 6 MB GIF corpus, inside the range on all eight; every contended row is inside the high side | `docs/benchmarks/2026-11-16-b22-insane-recoded.md` |
| **Setup cost** | a job costs **about 1 s, 2 s at Insane** (3 runs per cell: 2 KB file, twenty 4 KB, the 6 MB GIF folder stored; four profiles). Flat in the range (x0.3 low, x3.0 high), zero for an empty job. Calibration no longer learns it | §6 of the record |
| **GIF xfail** | its premise (one 564.7 s run) did not reproduce: three runs gave **87.7, 107.0, 180.1 s**. It is a pass on the reproduced rows | §4 |
| **Two JPEG/MP3 strict xfails** | flipped; markers removed | `tests/test_quiet_rates.py` |
| **Review (two lenses + my skeptic pass)** | calibration folded the new second into the learned rate (fixed, test first); the JPEG rates had not been byte-weighted (0.279 -> 0.277); "23 rows" was 21; the tiny-job "quiet" claim was unlogged past the first run; Insane's fixed second was 3.0 and fitted none of the six tiny runs (now 2.0 with a 3x margin); six tests passed under the old model and were tightened | the record |

Tests added: **55** in `tests/test_b22_insane_recoded.py`; four exact-number
assertions moved by the setup term (`test_b13_gui.py`, `test_b19_media.py`,
`test_i11_verify_progress.py` x2, `test_estimate.py`).

---

## 2. Findings worth not rediscovering

### Where the rates come from, and how far to trust them

- **Contention is the story.** Rows ran 1.4-4.3x their quiet time. In 21 valid
  rows the quiet row of a corpus is its least-contended one (others about
  15% or less, 4+ GB free). **Three of the eight corpora have one quiet row
  only** (design, MP3 misc, `gif-dl`: round 3 was skipped after three reaps);
  `mp3-misc`'s ran beside another session's `find`/`du` for four minutes, so
  the MP3 rate (0.171 against music's 0.208) may be low.
- **The JPEG rate is the firmest**: CMYK 8 MB and design 135 MB, 18x apart,
  agree within 1% (compress) and 1.5% (self-test).
- **PNG's split is one corpus's.** `png-dl1`'s extract (491.8 s) was as long as
  its whole compress + D9 (484.5 s): compress minus extract is unusable
  there, so the total (0.0156 MB/s) is measured and the 54:46 split is
  `png-dl`'s. One contended PNG row (`png-dl1` r2, 2,096 s) sits **8 s** inside
  the high (2,104): it holds by luck.
- **GIF's byte-weighted rate sits 30% from the 6 MB corpus** (the corpora
  disagree 1.5x), so its test margin is 1.35.

### Machine behaviours that cost hours

- **A `find / -iname *hms*.sql` ran 16 hours at ~24% of the CPU**, another
  session's, parent gone. The owner agreed to stop it; the `Stop-Process`
  returned before the process was gone ("still running: True" for a few
  seconds), so check twice.
- **The machine slept 15.6 h through a row** (Kernel-Power 42 at 19:18, 107
  at 10:56). `time.monotonic` counted it: **57,207 s** for a 925 s job. The
  harness asks Windows not to sleep; a lid close or manual sleep ignores it.
  Check a row against the event log when it is absurd.
- **A row's staging dir survives a reap** (up to 336 MB each: `s0.tar`,
  `s1.pcf`, a copy of the input). They are regenerable.
- **The harness that "failed" was a quoting bug**: `cmd //c 'start "" /b ...
  > log'` from bash gives "Access is denied". A `.cmd` file works.

### Estimator facts

- **A rate-relative extra goes negative**: the first version made the signed
  recode extras relative to the calibrated chain rate; a test through
  `queue_manager._time_split` showed the bar at -11.5 s compress after a text
  job taught Insane 0.16 MB/s. The extras are measured against **fixed
  constants** (`_INSANE_BASE_RATE`), and `time_split` takes the own-rated bytes
  out of the chain's term.
- **The handoff's "10-50 s per job" and "stored GIF folders 17-20 s" did not
  reproduce** (1.0 s here). Whatever made B21's runs slow was not the job.
- **The suggestion text reads Extreme as "strongest"**, so Insane's new figures
  reach the comparison table and the bar, not the recommendation sentence.
- **The B20 containers are unmeasured at Insane** and keep the chain's rate and
  the old extra; their share of the calibration subtraction follows it.

### The corpus guard

**`My Graphical Projects` is gone** from `...\0No Need To Check\` (moved to
`C:\DevCache\_trash\2026-11-16-graphical-projects-done`, not by this
session); the guard says "skipped, not present" and covers 31 files in
`Programs`. `tests/test_audit_regressions.py` reads one JPEG from it and now
**skips** (the second skip in the count). A folder `HND` also appeared and
vanished in the same place; not ours.

### Still true

- **Insane on pass-through media is not measured.** On packJPG/packMP3 output
  it is now priced from the rows above.
- **When two corpora disagree, weight by bytes**; **route and price by
  content**, not name; **Precomp's cost follows pixels, not bytes**.
- **Contended priors are wrong by a factor**; pin quiet rows and let the
  range's high side carry contention.
- **`recoded_seconds`, not `RecodeCost`, answers "how long do these files
  take".**
- **The venv's `python.exe` is a launcher**; untyped ctypes
  `SetPriorityClass` silently fails; write files with Edit/Write and
  `unix2dos` them (the repo is CRLF). **Python `open()` defaults to cp1252 on
  this machine**: pass `encoding="utf-8"` (and `python -X utf8`) for any file
  with emoji, such as the roadmap. **`printf` eats backslashes** (it garbled a
  log entry; rewritten): build Windows paths with `chr(92)` or an Edit.
- **Measure the incumbent that fills the slot**, **two corpora**, **render
  the GUI**, **CI's runner is not the target**, **check a test asserts the
  outcome** (six B22 tests passed under the old model), and **a `grep -c`
  that finds nothing exits 1** and stops an `&&` chain.

---

## 3. Next: B23, calibration and the open list

Spec: `docs/ROADMAP.md`, B23. **No owner agenda.** Start with the question
below, then:

1. **The owner's pick (ask first): the Compress page's column headers do not
   sit over their values.** Rendering the populated page (`tools/qa_sweep.py`,
   `compress-populated`, both themes) shows "Estimated size", "Saved",
   "Estimated time" and "Peak RAM" 75-165 px left of the values under them
   (the values of one column sit under the next column's header). **It is
   identical on `main`, so it is older than B22**, and it may be an
   offscreen-render artefact of the 1180 px window; check at a real width
   first. Options: fix it as the first B23 item, fix it on its own branch
   first, or leave it.
2. **Calibration**: one MKV run taught Extreme **3.1 MB/s** against the 1.41
   prior (pass-through video is not the chain). `queue_manager._calibrate`
   skips a job whose recoded bytes are a quarter of the piped bytes; extend it
   to probe-piped media that Precomp has no recoder for. Test first.
3. **Round 3 of the three large Insane corpora** (design, MP3 misc, `gif-dl`)
   and a quieter MP3 row, if the owner wants the three-run medians. Needs a
   quiet machine and the reaper off; about 2.5 hours.
4. The small open items in §4 (single-block treemap, the `SyntaxWarning`,
   Insane's bar freezing).

Then the full suite (`suite_parts.py`), review, push, CI, merge.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates come out under the range); a piped file under 3 MiB is one probe sample, so `low` = `expected` (M4A came in 12.7 KB under); the store-only overhead estimate misses by a few bytes both ways (16 B low on 25 M4As); **the 80 KB tiny job at Insane is ~1.4x high** (the chain's byte term and the setup cost both count) |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job; **pass-through video teaches Extreme a chain rate** (B23) |
| **B5's 0.55** | a mean plus margin, not a worst file; re-check file by file under B18's rule |
| **Precomp memory** | grows with pixels, not file size (5000² CMYK: 220 MiB; a design job's Precomp reached 791 MB) |
| **GUI** | with one category, the Details treemap is a single huge block; **column headers vs values on the populated Compress page** (§3) |
| **Tests** | `tests/test_edge_cases.py:1` raises a `SyntaxWarning` (unescaped `\.` in its docstring) |
| **I11 leftovers** | zpaqfranz reports 100% at stage start (Insane's bar freezes); a store-only job's bar jumped |
| **Media** | HEIC/WebP: no lossless recompressor; AVI/WMV/FLV/AAC unmeasured |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **B6** | only with an owner-provided Oodle sample; it also settles `-intense` |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **Tools** | Precomp (files dated 2019) and SREP (legacy restore only) are found only under `C:\Program Files\`, unpinned and unhashed, unlike zpaqfranz/flac/balrogg/qpdf in `tools\bin`; consider pinning Precomp through `toolfetch` (ask the owner first: it is a download) |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Insane prices JPEG (lepton-refused), MP3, GIF and PNG at their own
  rates** (B22); the B20 containers keep the chain's.
- **A job has a setup cost: 1 s, 2 s at Insane**; flat in the range, zero for
  no files, not learned by calibration.
- **The extras are signed and measured against fixed constants**, never the
  calibrated chain rate.
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
- **Recode rates are byte-weighted when corpora disagree** (B21, B22).
- **Time priors are quiet figures; contention goes in the range's high
  side** (2026-10-17). The low end is the chain's.
- **Lepton's constants are phase-true.**
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
  **Moves go to `C:\DevCache\_trash\<date>\`; the owner empties it.**
