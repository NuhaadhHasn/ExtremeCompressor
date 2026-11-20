# 🚦 START HERE — handoff (written 2026-11-20, after B26; B22-B25 before it)

> **B26 is merged** (`8f59953`; branch `270b5eb`). Tests: **1,927 passed, 1
> skipped, 1 xfailed** locally in three parts, corpus guard clean over 157 files
> (`Programs` 34 + the corpus copy below 123); CI green on the branch. B22-B25
> are `ba84077`, `524881c`, `65e6d9c`, `d9a8965`.
>
> **B26 (2026-11-19/20):** the B20 containers (AAB, AAR, NuGet, APPX, EPUB, ODT)
> at Insane are priced by what Precomp expands them to. `analyzer.probe_container`
> reads four counts out of the zip central directory
> (`FileInfo.zip_deflated_bytes / zip_png_bytes / zip_jpeg_bytes /
> zip_other_bytes`, 0 = unknown). Record:
> `docs/benchmarks/2026-11-20-b26-insane-containers.md`.
>
> **There is no queued phase and no owner agenda.** §3 lists what can be picked,
> with a recommendation. **Read §2 first**: most of B22-B26's cost was the
> machine, not the code.
>
> **The owner empties `C:\DevCache\_trash` for good, and keeps adding to it**
> (2026-11-19: "there will be more added to trash and it will be permanently
> deleted from my machine"). What that means for this repo:
> - **Hard-linked bench files survive it.** 542 of the 1,811 files under
>   `C:\excmp-bench` share data with names in the trash (`fsutil hardlink list`;
>   b19\jpg-design and jpg-web are two of them): the bench name keeps the data
>   alive, and the disk space only comes back if the owner asks for real copies.
>   **A real copy of the ODT is at `C:\excmp-bench\b26\own\odt-big-01.odt`**
>   (36,764,796 B, SHA-256 `836270c8...ddae8`), made for another session.
> - **The owner said on 2026-11-20 that everything in the trash is backed up**
>   (where was not stated). So nothing below is lost, but **the trash is no
>   restore path for a session**: if a phase needs one of these, ask the owner for
>   the backup, don't look in `_trash`. The 2026-11-18 finished bench folders
>   (`_trash\2026-11-18-excmp-bench-done`, `MOVED.txt`: xtool, silesia, lolz, b14,
>   i11, b13\music2, b18\video-phone, b19\mov-takeout, b19\mov-dl1, b21\m4a,
>   b21\mkv, ...) include the MOV/M4A/MKV sets, the corpora for "Insane on
>   pass-through media".
> - **`My Graphical Projects`**: `C:\excmp-bench\corpora\My Graphical Projects`
>   (123 files, 666,560,229 B, hash-identical to
>   `_trash\2026-11-16-graphical-projects-done`) is what the tests and the guard
>   read. It is backed up too (owner, above), but it is the owner's design work:
>   **still ask before removing the copy**.
> - Nothing in the repo reads `_trash` (one comment in
>   `tests/test_audit_regressions.py`).
>
> **Precomp v0.4.7 is pinned** (B25) in `excmp/toolfetch.py` and lives in
> `tools\bin\precomp\0.4.7\` (gitignored: **a fresh checkout or CI has none and
> falls back to Program Files**; run `toolfetch.fetch_tool(TOOL_MANIFEST
> ["precomp"])` once). **SREP is still unpinned** (it stays out of the engine).
>
> **The machine is shared and tight on memory** (3-6 GB free on a good day, 0.35 GB
> at worst this session). Claude Code's low-memory reaper stopped background
> work six times in B22-B24 and **not once in B26**. **It also sleeps**: see §2.
> Rows and suite parts survive a reap (the batch skips rows that have a result;
> `suite_parts.py` skips parts with a `PART-n-OK` marker). **Launch background
> work through a `.cmd` file**: `(cmd //c "C:\\path\\x.cmd" > /dev/null 2>&1 &)`
> from bash worked all session; `cmd //c 'start ...'` is what fails with "Access
> is denied". **Drive C: had ~124 GB free** on 2026-11-20.
>
> **The owner is cleaning up the machine** (log: `C:\DevCache\CLEANUP-LOG.md`;
> read it before touching disk space, installed software or caches). This session
> added one entry: the B26 staging directory (2 files, 48,645,281 B) went to
> `_trash\2026-11-20-excmp-b26-staging`.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **The full suite on a shared machine: `C:\excmp-bench\b21\suite_parts.py
  <tree> [--fresh]`**, launched from a `.cmd` file (`C:\excmp-bench\b26\
  run_suite.cmd` is the template). It takes the corpus snapshot, runs the test
  files in three round-robin parts, then compares. **3-6 min a part on a quiet
  machine, 12 min in all** (17 min the first time this session, 3x slower when
  the others are busy). **Run every
  test file the change could touch, not a guessed subset before the suite.**
- **`C:\excmp-bench\contention.ps1`** logs, every 15 s, the bench's CPU share
  against everything else's (`run_contention.cmd` in `b26` starts it). **Stop it
  when the bench is done** (it runs forever; this session stopped its own).
- **Worktree `..\ExtremeCompressor-b21`** is kept, detached at `main`
  (`8f59953`), clean. For the next item: `git switch -c <branch>` in it. Its
  `tools\bin` is a junction to the main checkout's: **unlink it before removing
  the worktree**. Main checkout's code is what `b21_app.py` times: **do not edit
  it while a batch runs**; work in the worktree.

---

## 1. What shipped (2026-11-19 – 11-20)

| item | result | record |
|---|---|---|
| **B26 containers at Insane** | the old model (chain rate + B20's extra) held for 5 of 6 corpora and failed EPUB by **3.5x**. Time follows the bytes zpaqfranz is handed: **16-80 s per input MB, 4.4-7.2 per `.pcf` MB**. Deflated members: 0.385 compress / 0.360 self-test MB/s of their uncompressed size (fitted on NuGet, APPX, AAR, AAB, split by each row's phase events); PNG members at B22's PNG rate; JPEG members at its JPEG rate (one album, within 16%); the rest at the chain's. Expected is **0.66x-1.57x** of the fastest rows (was 0.28x-1.7x) | `docs/benchmarks/2026-11-20-b26-insane-containers.md` |
| **B26 probe** | `probe_container()` returns a `ContainerProfile`; a member's claimed size is believed up to deflate's 1032:1; `probe_expandable` still answers a bool and agrees with main on every input tried | `tests/test_b26_zip_insane.py` (66) |
| **B26 low end** | the PNG members' self-test may run 1.6x under the model (`_ZIP_PNG_VERIFY_LOW`): the ODT's ran at 0.63x of it | same |
| **Review** | two reviewers (estimator and evidence; the analyzer under hostile input), every finding reproduced first. Real: a JPEG-heavy container priced at ~0 s (448 s on main), a header claiming 10 TB (24 years), the self-test split, four mutations the tests missed. 13 mutations are each caught now | the record, §4 |

Tests added: **66** (`test_b26_zip_insane.py`). No existing test moved.

---

## 2. Findings worth not rediscovering

### The measurements, and how far to trust them

- **Round 1 of the small corpora was 10x slow** (`nupkg-r1` 313 s against 29 s):
  a runaway `find`, Firefox and a memory squeeze to 0.6 GB. **Self-test is steady
  across rounds (AAB 828/839 s); compress is what contention moves** (AAB 1,891
  against 2,595). The fastest of the rounds is the floor.
- **The AABs are 90% of the fit's deflated bytes**, so 0.385 / 0.360 is the AABs'
  rate; the three small corpora sit 17-23% under their quiet rows. The AABs
  share most of their expanded bytes (two apps, one toolchain): the per-file
  model can't see it.
- **One PNG rate covers a 17x spread** (6x per byte in the ODT, up to 106x in an
  EPUB). A container of large-canvas PNGs will run past its expected; the 4x high
  side held the worst EPUB row (1,020 s).
- **A nested archive (a jar inside an AAR) expands again**: `aar-01` was 0.50 of
  its `.pcf`, priced about 2x low.
- **"Out of sample" is true only for the PNG rate** (B22's corpora). The 1.7x band
  and the ODT low-end pin in the tests were set after seeing the results.
- **One album is one corpus** (JPEGs in a zip ran at B22's JPEG rate within 16%;
  its contended round was 2.2x). Everything about JPEG-in-zip rests on it.
- **The self-test (D9) phase from a row's own events is not `extract_s`**: 20%
  longer on the AAB row, within 7% on eight others, 0.65x on `epub-r2`.
  `rows`' `events` have the phase boundary (first `verify` event).

### Machine behaviours that cost hours

- **The machine slept 15.7 h through a row** (Kernel-Power 42 at 19:01, back
  10:40; the contention log has the gap), **the second time** (B22 lost one too).
  `b13_app.py` times with `time.monotonic`, which counts sleep, and its
  `SetThreadExecutionState` does not survive a lid close. **This session's
  monitor script compares the clock between polls and flags a jump over 5 min
  (it never fired: the sleep came before it); do that, and check the event log
  for any absurd row.** A fix is on the list (§3): `QueryUnbiasedInterruptTime`.
- **A killed row's staging survives** (`out\b13app-*`: `m.excmp`, `payload.zpaq`,
  up to hundreds of MB). **A row's harness prints only at the end**, so a killed
  row loses its compress time even when compress had finished (it had, 17 minutes
  before the sleep: `m.excmp`'s mtime gave 698 s, a note not a measurement).
  Regenerable; the owner wants them in the trash folder.
- **A runaway `find` held 13-20% of the CPU for hours, again**: another session's
  (HTML thumbnails), parent gone. **Ask the sessions with `ListAgents` +
  `SendMessage` before stopping a process that isn't yours**; the owner said "ask
  other sessions", and its owner stopped it.
- **Process names in the contention log: "bash" is usually another session's
  hooks.**

### Tool traps

- **`sed -i` on a CRLF file converts it to LF** (Git for Windows' sed), even when
  the pattern matches nothing. A no-op `sed -i` did it to `estimate.py` this
  session: `unix2dos` it back and compare `git diff --stat`. The repo is CRLF;
  write with Edit/Write and `unix2dos` new files.
- **After `unix2dos` or any shell write, the Edit tool wants a fresh Read** of
  the file ("File has not been read yet").
- **`pytest.main(..., plugins=[...])` with a patched constant is a quick mutation
  harness**; the one used here copies `excmp`, `gui` and the test into a temp dir
  and rewrites a line. A mutant that survives is a test to write.
- **Python here: `open()` defaults to cp1252**: pass `encoding="utf-8"` (and
  `python -X utf8`) for any file with emoji, such as the roadmap. `printf` eats
  backslashes; a heredoc halves `\\`; a `python -c` through bash double quotes
  mangles `\'`: write the script to a file.
- **A `grep -c` that finds nothing exits 1.**

### Estimator and GUI facts

- **A rate-relative extra goes negative**: extras are measured against **fixed
  constants** (`_INSANE_BASE_RATE`), and `time_split` takes the own-rated bytes
  out of the chain's term. B26's containers use the same mechanism
  (`_insane_own_seconds`); the bar split test is copied for them.
- **`low` = the self-test in full + compress / 3.2**: the self-test term has no
  spread, so a container whose self-test runs under the model needs its own
  allowance (B26's).
- **zpaqfranz prints one `%` line while compressing**, the scan line; the stage
  ignores it (B23). A skipped stage reports its end.
- **The suggestion text reads Extreme as "strongest"**, so Insane's figures reach
  the table and the bar, not the recommendation sentence.
- **B5's types (`.docx .xlsx .pptx .zip .jar .apk`) keep the chain rate at Insane**
  although the probe now fills their counts: nobody has timed one there.

### Still true

- **Insane on pass-through media is not measured** (and its corpora are in the
  trash, §0).
- **When two corpora disagree, weight by bytes**; **route and price by content**,
  not name; **Precomp's cost follows pixels, not bytes**.
- **Contended priors are wrong by a factor**; pin the fastest rows and let the
  range's high side carry contention.
- **`recoded_seconds`, not `RecodeCost`, answers "how long do these files take".**
- **The venv's `python.exe` is a launcher**; untyped ctypes `SetPriorityClass`
  silently fails.
- **Measure the incumbent that fills the slot**, **two corpora**, **render the
  GUI** (it found B23's header defect; the suite never did), **CI's runner is not
  the target**, **check a test asserts the outcome**, **and mutate a new test**
  (this session's four survivors).

---

## 3. What can be picked next (no queued phase)

Recommended order, each one branch and one merge:

1. **The bench clock** (a small, local fix; it is the machine's second lost row):
   `b13_app.py` and `b21_app.py` time with `time.monotonic`; use
   `QueryUnbiasedInterruptTime` (or log wall and unbiased both) and have the
   harness print the compress time the moment compress ends. Bench scripts are
   not in the repo (`C:\excmp-bench\`), so it is not a branch.
2. **B5's types at Insane** (`.docx .xlsx .pptx .zip .jar .apk`): the model now
   prices a container by its counts, and these keep the chain's rate because
   nothing was timed. A set of 3-4 corpora (Office files, a jar/apk set, plain
   zips) at Insane is about an hour on a quiet machine, then the model either
   fits them (lift the `_PRECOMP_EXPANDABLE` exclusion in `_recode_kind`) or
   it doesn't.
3. **A second JPEG-in-zip corpus and a second PNG-heavy container** (a CBZ, an
   APK of images): each of B26's PNG and JPEG rates rests on one corpus.
4. **The estimator's per-file limits** (§4: near-duplicates, a piped file under
   3 MiB as one probe sample).
5. **A missing pinned Precomp falls back to Program Files silently** (B25
   leftover; a log line would help).
6. **Anything the owner asks for**: the elevated-session and release lanes (D4b,
   E3-E5), the Explorer menu (I5, **ask first**, HKCU).

---

## 4. Everything else still open

| item | what |
|---|---|
| **Estimator** | per-file only (near-duplicates, and two apps sharing their expansion, come out under the range); a piped file under 3 MiB is one probe sample, so `low` = `expected`; the store-only overhead estimate misses by a few bytes both ways; **the 80 KB tiny job at Insane is ~1.4x high**; **a nested archive in a zip is ~2x low**; **one PNG rate covers 6-106x** |
| **Calibration** | learns rates only since B19; learning a proper slope needs the probe readings behind each job; `probe_piped_bytes` overstates what was piped when `_plan_that_fits` turns probe piping off (it only skips learning) |
| **Insane's bar** | the creep assumes the plan's chain ran: if a tool is missing or degrades the chain, it creeps a zpaqfranz band that never runs |
| **B26 corpora** | GIF members and stored members of a container are priced at the chain's rate, unmeasured; `.png` is matched by name |
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

- **A zip container at Insane is priced by its central-directory counts**
  (B26): deflated members' uncompressed size at 0.385 / 0.360 MB/s, PNG members at
  B22's PNG rate, JPEG members at its JPEG rate, the rest at the chain's; **all
  counts 0 keeps the old pricing**; Extreme is untouched; **B5's types keep the
  chain rate** until someone times them.
- **A header may not claim more than deflate can make** (1032:1); a stored
  member counts its own bytes.
- **The self-test split comes from a row's own phase events**, not `extract_s`
  (B26); the totals are the same.
- **The PNG members' self-test may undercut the model by 1.6x** in the low end
  only (`_ZIP_PNG_VERIFY_LOW`).
- **Precomp is pinned and preferred over Program Files** (B25); a pinned tool
  that fails its directory digest is not used, and discovery falls through.
- **Insane prices JPEG (lepton-refused), MP3, GIF and PNG at their own
  rates** (B22, B24).
- **A job has a setup cost: 1 s, 2 s at Insane**; flat in the range, zero for no
  files, not learned by calibration.
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
- **When the plan doesn't fit the disk, probe-flagged media are stored, not the
  job refused** (B21b). Lossless either way; the job says what it stored.
- **A mostly-video folder is recommended Normal**; probe-only bytes don't count
  toward Extreme. MP3 on a Precomp chain is recoded and does count.
- **PNG and GIF are routed and priced by content** (`image_format`, B21); a
  hand-built `FileInfo` (`None`) is taken at its name.
- **GIF goes to Precomp on Extreme/Insane**, stored on Fast/Normal.
- **Recode rates are byte-weighted when corpora disagree** (B21, B22, B26).
- **Time priors are quiet figures; contention goes in the range's high side**
  (2026-10-17). The low end is the chain's.
- **Lepton's constants are phase-true.**
- **The container rate at Extreme stays 0.46 MB/s.**
- **"Seconds"/"minutes" in a suggestion reads the whole job's estimate.**
- **Lepton keeps every JPEG it accepts; Precomp gets only what lepton refuses**
  (B19), by content.
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
- **The repo is private and the OSI rule is retired**; the lossless guarantee
  matters more as a result. **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever** (the harness's reminder to add
  a trailer is overridden by the owner's rule; audit every message).
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
- **Before deleting anything, inventory it completely** (owner's global rule,
  2026-10-17): hidden files, `git status --ignored`, junctions unlinked first.
  **Moves go to `C:\DevCache\_trash\<date>\`; the owner empties it, for good.**
