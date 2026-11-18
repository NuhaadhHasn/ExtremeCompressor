# 🚦 START HERE — handoff (written 2026-11-18, after B25; B22-B24 before it)

> **B22-B25 are merged** (`ba84077`, `524881c`, `65e6d9c`, `d9a8965`). Tests:
> **1,861 passed, 1 skipped, 1 xfailed** locally, corpus guard clean over 154
> files (`Programs` + the corpus copy below); CI green on every branch.
>
> **B25 (2026-11-18, owner-approved):** Precomp v0.4.7 is **pinned** in
> `excmp/toolfetch.py` (zip sha256 + size, the four files of `windows/` as the
> directory digest). Fetched with the project's own `fetch_tool`; it lives in
> `tools\bin\precomp\0.4.7\` (gitignored; **a fresh checkout or CI has none and
> falls back to Program Files**: run `toolfetch.fetch_tool(TOOL_MANIFEST
> ["precomp"])` once). `find_tools` asks for the verified pinned copy **first**
> now, so the pin is what runs. **SREP is still unpinned** (it stays out of the
> engine anyway).
>
> **Test corpus copy (temporary, the owner asked for it):**
> `C:\excmp-bench\corpora\My Graphical Projects`, 123 files, 666,560,229 B,
> hash-identical to the original in `C:\DevCache\_trash\2026-11-16-graphical-
> projects-done`. `tests/test_audit_regressions.py` and `tools/corpus_guard.py`
> read it. **When the owner says the work is done, remove it**: inventory, move
> it to `C:\DevCache\_trash\<date>\`, log it in `CLEANUP-LOG.md`, and delete the
> two fallback paths (each is commented with the date). Do not remove it before.
>
> **There is no queued phase and no owner agenda.** §3 lists what can be
> picked, with a recommendation. **Read §2 first**: most of the B22-B24 cost
> was the machine, not the code.
>
> **The machine is shared and tight on memory.** Claude Code's low-memory
> reaper stopped background work **six times** at 4-7 GB free, beside three
> Claude sessions and Firefox (not Docker: no Docker process was running). The
> notice says to restart only when asked; **ask, then restart** (the owner
> said yes each time). Rows and suite parts survive a reap: the Insane batch
> skips finished rows (`C:\excmp-bench\b22\run_insane.cmd`,
> `run_insane_r3big.cmd`) and `suite_parts.py` skips parts with a `PART-n-OK`
> marker. **Launch background work through a `.cmd` file**, not
> `cmd //c 'start ...'` from the shell: that fails with "Access is denied".
> **Drive C: had ~118 GB free** on 2026-11-17.
>
> **The owner is cleaning up the machine** (log: `C:\DevCache\CLEANUP-LOG.md`;
> read it before touching disk space, installed software or caches). This
> session moved 673,626,040 B + 228,265,325 B of dead bench staging to
> `C:\DevCache\_trash\2026-11-17-excmp-b22-staging\` (the log has the first
> entry). **`C:\excmp-bench\b19` and `b21` are read by the tests: keep.**
> `C:\Program Files\precomp` is now only the fallback (the pinned copy is in
> `tools\bin`, byte-identical); do not delete it from a fresh clone's reach.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **The full suite on a shared machine: `C:\excmp-bench\b21\suite_parts.py
  <tree> [--fresh]`**, launched from a `.cmd` file (`C:\excmp-bench\b22\
  run_suite.cmd` is the template). It takes the corpus snapshot, runs the test
  files in three round-robin parts, then compares. 13-22 min at below-normal
  beside other sessions (it is 3x slower when the others are busy).
  **Run every test file the change could touch, not a guessed subset before
  the suite**: B22's four failures were exact-number assertions in three files a
  targeted run skipped.
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU share
  against everything else's. It is reaped like everything else. "bash" in it is
  usually another session's hooks; **`find` in it was a runaway search for 16
  hours** (§2).
- **Worktree `..\ExtremeCompressor-b21`** is kept, detached at `main`. For the
  next item: `git switch -c <branch>` in it. Its `tools\bin` is a junction to
  the main checkout's: **unlink it before removing the worktree**.

---

## 1. What shipped (2026-11-16 – 11-17)

| item | result | record |
|---|---|---|
| **B22 Insane per kind** | JPEG lepton refuses **0.277 / 0.312 MB/s** (compress / self-test), MP3 **0.171 / 0.221**, GIF **0.121 / 0.148** (B24), PNG **0.029 / 0.034**. The old chain rate (0.091 / 0.107) was 3.1x slow on JPEG, 2x on MP3, 1.5x on GIF and **2.5x fast on PNG**. 24 valid rows, every file restored | `docs/benchmarks/2026-11-16-b22-insane-recoded.md` |
| **B22 setup cost** | a job costs **about 1 s, 2 s at Insane** (3 runs per cell, four profiles). Flat in the range, zero for an empty job; calibration does not learn it | §6 of the record |
| **B24 GIF refit** | `gif-dl` ran 454.0 s on a quiet machine; its earlier "quiet" row (595.7 s) was 31% slow. The two GIF corpora agree on the rate to 0.5% | §9 |
| **B23 headers** | the Compress page's column headers sat left of their values (older than B22): the fixed-width toggle shared the header strip. It takes the first header cell now ("How measured"; the sentence is its tooltip) | `tests/test_gui_compare.py` |
| **B23 calibration** | skips jobs mostly made of recoded plus probe-piped media (`AnalysisSummary.probe_piped_bytes`): one MKV job had taught Extreme 3.1 MB/s against 1.41 | `tests/test_b23_calibration.py` |
| **B23 Insane's bar** | zpaqfranz prints one `100%` scan line (nothing written), then nothing for the whole compress; the bar sat at the top of the chain's band. Fixed three ways: the scan line is not progress; a silent stage creeps by elapsed time against the estimate (90% cap, not while paused, locked against the engine's reports); **a stage the engine skips reports its end** | `tests/test_b23_silent_stage.py` |
| **B23 small** | the Details treemap is hidden for one block (or a dominant one); `test_edge_cases.py`'s `SyntaxWarning` is gone | `tests/test_treemap.py` |
| **B25 Precomp pin** | v0.4.7 pinned; GitHub publishes no digest and winget has no manifest, so the second party is the 2019 Program Files install, whose `precomp.exe` equals the asset's (`aabca1ee...515d`). Discovery prefers the verified copy; one `find_tools` call costs ~31 ms more | `tests/test_b25_precomp_pin.py` |
| **B25 corpus** | the test and the guard read the bench copy of `My Graphical Projects` (the audit test no longer skips) | commit `5efdacc` |
| **Reviews** | two on B22 (estimator consistency, evidence) and one with a shell on B23; each found real bugs (calibration folding the setup second, the unweighted JPEG rate, Precomp-skip leaving the creep off, the creep running while paused); B24 was a constant refit and had no separate reviewer | the records |

Tests added: **55** (`test_b22_insane_recoded.py`), **28** (`test_b23_*`, the
header and treemap tests); four exact-number assertions moved by the setup term.

---

## 2. Findings worth not rediscovering

### The measurements, and how far to trust them

- **Contention is the story.** Rows ran 1.4-4.3x their quiet time. **A row at 6%
  CPU contention and 4.2 GB free was 31% slow** (`gif-dl` r2 595.7 s against
  r3 454.0 s): the protocol's two numbers do not catch cache, thermal state or
  another session's I/O. **The fastest of three rows is a floor, not a quiet
  machine; a corpus with one row is a guess.**
- **The JPEG rate is the firmest**: CMYK 8 MB and design 135 MB, 18x apart,
  agree within 1% (compress) and 1.5% (self-test).
- **PNG's split is one corpus's.** `png-dl1`'s extract (491.8 s) was as long as
  its whole compress + D9 (484.5 s): compress minus extract is unusable there,
  so the total (0.0156 MB/s) is measured and the 54:46 split is `png-dl`'s. One
  contended PNG row (`png-dl1` r2, 2,096 s) sits **8 s** inside the high (2,104).
- **MP3 may be 3% low**: `mp3-misc`'s fastest row (836.2 s, others 17%) gives a
  total of 0.0995 MB/s against the 0.0965 in use. Left alone.

### Machine behaviours that cost hours

- **A `find / -iname *hms*.sql` ran 16 hours at ~24% of the CPU**, another
  session's, parent gone. The owner agreed to stop it; `Stop-Process` returned
  before the process was gone for a few seconds, so check twice.
- **The machine slept 15.6 h through a row** (Kernel-Power 42 at 19:18, 107 at
  10:56): `time.monotonic` counted it, **57,207 s** for a 925 s job. The
  harness asks Windows not to sleep; a lid close or manual sleep ignores it.
  Check an absurd row against the event log.
- **A killed row's staging dir survives** (up to 336 MB: `s0.tar`, `s1.pcf`, a
  copy of the input). Regenerable; the owner wants them in the trash folder.
- **`My Graphical Projects` is gone** from `...\0No Need To Check\` (moved to
  `C:\DevCache\_trash\2026-11-16-graphical-projects-done`, not by this
  session). The guard still prints "skipped, not present" for the original
  path; that is expected now that the bench copy (top of this file) is watched
  too. **The one remaining skip** is the opt-in 57k-file corpus walk.

### Estimator and GUI facts

- **A rate-relative extra goes negative**: the first B22 version made the signed
  recode extras relative to the calibrated chain rate; a test through
  `queue_manager._time_split` showed the bar at -11.5 s after a text job taught
  Insane 0.16 MB/s. The extras are measured against **fixed constants**
  (`_INSANE_BASE_RATE`), and `time_split` takes the own-rated bytes out of the
  chain's term.
- **zpaqfranz prints one `%` line while compressing**, the scan line, at 0.1 s,
  `100.00% ... =>(0.00 B)`; the stage ignores it (`_NOTHING_WRITTEN`). Measured
  on the real tool: 14 MB at -m58 took 82.5 s and emitted 24 lines.
- **A skipped stage never reported its end**: Precomp finding nothing sent
  `('precomp', 0.0)` and then the next stage's events. The engine now reports
  `100.0` on `StageSkip`.
- **The handoff's "10-50 s per job" and "stored GIF folders 17-20 s" did not
  reproduce** (1.0 s here). Whatever made B21's runs slow was not the job.
- **The suggestion text reads Extreme as "strongest"**, so Insane's new figures
  reach the comparison table and the bar, not the recommendation sentence.
- **The B20 containers are unmeasured at Insane** and keep the chain's rate and
  the old extra; their share of the calibration subtraction follows it.
- **Python on this machine**: `open()` defaults to cp1252, so pass
  `encoding="utf-8"` (and `python -X utf8`) for any file with emoji, such as the
  roadmap; `printf` eats backslashes (it garbled a log entry; rewritten): build
  Windows paths with `chr(92)` or an Edit; a heredoc halves `\\`.

### Still true

- **Insane on pass-through media is not measured.**
- **When two corpora disagree, weight by bytes**; **route and price by
  content**, not name; **Precomp's cost follows pixels, not bytes**.
- **Contended priors are wrong by a factor**; pin the fastest rows and let the
  range's high side carry contention.
- **`recoded_seconds`, not `RecodeCost`, answers "how long do these files
  take".**
- **The venv's `python.exe` is a launcher**; untyped ctypes
  `SetPriorityClass` silently fails; write files with Edit/Write and
  `unix2dos` them (the repo is CRLF).
- **Measure the incumbent that fills the slot**, **two corpora**, **render
  the GUI** (it found B23's header defect; the suite never did), **CI's runner
  is not the target**, **check a test asserts the outcome** (six B22 tests
  passed under the old model), and **a `grep -c` that finds nothing exits 1**.

---

## 3. What can be picked next (no queued phase)

The roadmap has nothing left that is both unblocked and in the code's lane.
Recommended order, each one branch and one merge:

1. ~~The Precomp pin~~ **done (B25).** Left over from it: a missing pinned
   copy falls back to Program Files **silently** (a log line would help), and
   `main.py`, the superseded Tkinter prototype, still hardcodes the old path
   (leave it).
2. **The B20 containers at Insane** (AAB, NuGet, APPX, AAR, ODT, EPUB): the one
   recoded kind Insane still prices at the chain rate plus an old extra. Three
   corpora already exist (`C:\excmp-bench\b20`); about 2-3 hours on a quiet
   machine, with the reaper off or a restart after each stop.
3. **The estimator's per-file limits** (§4: near-duplicates, a piped file under
   3 MiB as one probe sample); small and testable.
4. **Anything the owner asks for**: the elevated-session and release lanes
   (D4b, E3-E5), the Explorer menu (I5, **ask first**, HKCU).

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates come out under the range); a piped file under 3 MiB is one probe sample, so `low` = `expected` (M4A came in 12.7 KB under); the store-only overhead estimate misses by a few bytes both ways; **the 80 KB tiny job at Insane is ~1.4x high** (the chain's byte term and the setup cost both count) |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job; `probe_piped_bytes` overstates what was piped when `_plan_that_fits` turns probe piping off (it only skips learning) |
| **Insane's bar** | the creep assumes the plan's chain ran: if a tool is missing or degrades the chain, it creeps a zpaqfranz band that never runs |
| **B5's 0.55** | a mean plus margin, not a worst file; re-check file by file under B18's rule |
| **Precomp memory** | grows with pixels, not file size (5000² CMYK: 220 MiB; a design job's Precomp reached 791 MB) |
| **I11 leftovers** | a store-only job's bar jumped |
| **Media** | HEIC/WebP: no lossless recompressor; AVI/WMV/FLV/AAC unmeasured |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **B6** | only with an owner-provided Oodle sample; it also settles `-intense` |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **Tools** | SREP unpinned (not used by the engine); the pinned Precomp exists only where it was fetched (per checkout) |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Precomp is pinned and preferred over Program Files** (B25); a pinned tool
  that fails its directory digest is not used, and discovery falls through.
- **Insane prices JPEG (lepton-refused), MP3, GIF and PNG at their own
  rates** (B22, B24); the B20 containers keep the chain's.
- **A job has a setup cost: 1 s, 2 s at Insane**; flat in the range, zero for
  no files, not learned by calibration.
- **The extras are signed and measured against fixed constants**, never the
  calibrated chain rate.
- **The fastest row of three is the floor** the Insane rates are fitted to.
- **Calibration skips jobs mostly of recoded plus probe-piped media** (B23).
- **A stage that prints nothing moves the bar by time against the estimate**,
  capped at 90% of its band; **the engine reports a skipped stage's end** (B23).
- **The toggle sits in the first header cell** ("How measured") so the header
  spans the rows' width (B23); the Details treemap hides for one block.
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
