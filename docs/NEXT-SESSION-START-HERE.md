# 🚦 START HERE — handoff (written 2026-11-21, after B27/B28, I5, I5b and E3)

> **Five branches merged on 2026-11-21** (merge commits `6f36989` B27, `cfa2a83` B28, `f50f45d`
> I5, `b7cd5da` I5b, `87d756e` E3 and `d859aea`, a fix to I5's tests). Tests: **2,213 passed, 1 skipped, 1 xfailed** locally in three parts, corpus guard
> clean; CI green on every branch (and on `main` after the push). Earlier: B26 `8f59953`,
> B22-B25 `ba84077`, `524881c`, `65e6d9c`, `d9a8965`.
>
> **The owner's 2026-11-20/21 agenda is done**: the Explorer right-click menu (I5, with a Settings
> tab switch, I5b), a frozen build and a per-user installer (E3, **unsigned**), and the work
> around B26 (B27 measured B5's types, B28 priced archives inside archives). The owner said to
> stop at 07:00 on 2026-11-21, so the work stopped there.
>
> **There is no queued phase and no owner agenda.** §3 lists what can be picked, with a
> recommendation: **a second `.docx` corpus first**. **Read §2 first**: the machine cost more
> than the code again (a 6.9 h sleep corrupted a row that a fit then rested on).
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
  when the bench is done** (it runs forever; B27 stopped its own on 2026-11-21).
- **Worktree `..\ExtremeCompressor-b21`** is kept, detached at `main`, clean (its `dist\` and
  `build\` from the E3 builds were removed). For the next item: `git switch -c <branch>` in it. Its
  `tools\bin` is a junction to the main checkout's: **unlink it before removing the worktree**. A
  frozen build needs a `.venv` there too (a junction to the main checkout's works; unlink it the same
  way). Main checkout's code is what `b21_app.py` times: **do not edit it while a batch runs**; work in
  the worktree.
- **The timing batch is over and nothing of mine is running**: `C:\excmp-bench\b27\` has the corpora
  (`corpora\`, copies of the owner's files), the rows (`out\b13-app-*.jsonl`), `driver2.py` (the
  reordered batch with a cutoff), `b27_report.py` (the tables of the record) and `mk_handoff.py`-style
  scratch scripts. The contention logger was stopped. `aab2` was started and stopped (no row).

---

## 1. What shipped (2026-11-20 – 11-21)

| item | result | record |
|---|---|---|
| **I5 Explorer menu** | `excmp shell install/uninstall/status` writes per-user HKCU verbs (Compress on files and folders; Extract here / Verify archive on `.excmp`); Explorer starts **one process per selected file**, so a named mutex picks the window and the rest hand their file over a validated pipe (`QLocalServer`, message ids dedupe retries). Two reviews, every finding reproduced: a foreign `.excmp` default was overwritten, uninstall removed keys others had added, Extract here overwrote a user's edit (now a fresh `name (2)` folder) | `tests/test_i5_shell_menu.py`, `test_i5_gui_intake.py`; README; ROADMAP I5 |
| **I5b Settings switch** | Add / Remove / Repair on the Settings tab, state line inline (no modal dialog); a review made a half-installed menu say so and gave the button an accessible name that says what it does | `tests/test_i5b_settings_menu.py` |
| **E3 frozen build + installer** | `packaging/`: PyInstaller `--onedir` (window `ExtremeCompressor.exe` and console `excmp.exe` in one folder, never onefile, never UPX), Inno Setup per user. **110 MB folder, 33.8 MB installer first**; a real silent install registered the *window* for the verb and the uninstaller left no file and no key. `PySide6-Essentials` is enough (proved from the wheel's file list). A review found **PAR2 missing from the frozen build** (fixed) | `packaging/README.md`; ROADMAP E3 |
| **B27** | B5's six types timed at Insane, 12 rows on 10 corpora, 0 mismatches: **no change**, the chain stays (docx is the one miss, one corpus). Plus the pin-fallback warning (`find_tools` logs when a hash-pinned tool is replaced by an unverified one) | `docs/benchmarks/2026-11-21-b27-b5-types.md` |
| **B28 nested archives** | `zip_nested_bytes`; `_NESTED_FACTOR = 3.0` from two corpora; a zip's members are clamped to the file (a 226-byte `.war` was priced at 26,465 s) | `tests/test_b28_nested_archives.py` (25) |

---

## 2. Findings worth not rediscovering

### This session (2026-11-20/21)

- **Check `slept_s` before trusting a row, and never fit on one.** The harness now times with
  `QueryUnbiasedInterruptTime` and prints `slept_s`; the times stay right through a sleep, but a
  slept row still ran under odd conditions: `war-r1` read 512 s with `slept_s` 24,669, its extract
  277 s against 96 s on round 2, and **round 2 read 300 s**. B28's factor was first fitted to the
  512 (5.3) and a reviewer noticed the test accepted any factor from 2 to 7.9; **two corpora gave
  3.0**. A fit whose test can't fail is a fit nobody checked.
- **The timing batch order matters when time is short.** A 12-row queue was ~6 h; it was
  reordered (`C:\excmp-bench\b27\driver2.py`) so the rows that decide something ran first, and
  nothing starts after a cutoff. The quiet CPU for the suite and a rebuild is part of the plan.
- **B5's types, measured over expected (one row each):** chain xlsx 0.89, pptx 1.64, zip 0.89, jar
  1.48, **docx 2.84 (past its high)**, apk 0.51 (below its low); container model xlsx 0.29, pptx
  1.41, zip 0.83, jar 2.14, docx 0.97, apk 0.58. Neither wins; docx is one corpus.
- **`.zip`, `.jar` and `.apk` are not reached by B28's nested rule** (`_recode_kind` returns
  nothing for the B5 suffixes), so the nested factor is dormant for them until they are lifted.
- **A silent uninstall with the window open returned 0, deleted the uninstall entry and left every file
  behind** (found by the smoke test's own cleanup, not by a test): Inno's `AppMutex` (the window holds
  `gui.singleinstance.RUNNING_MUTEX`) makes the uninstaller refuse instead. **Always read what a
  "success" left on disk.**
- **A pytest process died on exit (139 / 0xC0000005) with every test passing**: I5's `main()` tests left
  the window and server alive until interpreter exit, after the QApplication, which crashes on the
  offscreen platform (production exits clean on the real one, three runs). `suite_parts.py` prints each
  part's return code: read it, a green dot line is not a pass.
- **The Explorer verbs are HKCU, and tests must never touch it**: every test writes under a
  throwaway registry root; `packaging/smoke_test.py` writes the real keys, so it now refuses to run
  over an existing menu and always uninstalls.
- **`par2` is a namespace package** (`__file__` is None): `Path(par2.__file__)` raises in a frozen
  build. `recovery._exe` looks in `sys._MEIPASS` and `par2.__path__`.
- **Qt traps:** a stray `QCoreApplication.quit()` leaves nested event loops dead until the next
  `exec()` (a fixture drains it); an in-process `QLocalServer` and client in one process never
  deliver, so the intake tests use real subprocesses; `Popen.wait` blocks the event loop; the venv's
  `python.exe` is a launcher, so kill a process tree with `taskkill /F /T`.
- **Windows traps:** PowerShell `-Path` treats `*` as a wildcard (use `reg.exe` or `-LiteralPath`);
  git-bash rewrites `/D...` switches (set `MSYS_NO_PATHCONV=1` for `reg` and `ISCC`); **a literal
  NUL byte in a `.py` makes git call it binary** (write `bytes(n)`); `sed -i` converts CRLF to LF
  (still); Claude Code's low-memory reaper kills background shell loops, **a detached
  `Start-Process` python survived all night**; the classifier blocks a force-push, so branch
  surgery means a new branch and a normal push.
- **The frozen build:** `requirements.txt` is `PySide6-Essentials`; the roadmap's exclude list
  wrongly names QtSvg (icons) and QtNetwork (I5's pipe), a test reads the real imports; the
  excluded modules' DLLs still ship unless dropped (`DROP_FILES`).

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
  although the probe now fills their counts: timed in B27, no model beat it (see above).

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

1. **A second `.docx` corpus** at Insane, one round (~80 min for 80 MB: B27's docx took
   4,632 s). Docx is the one B5 type outside its chain range on the unsafe side (2.84x); the
   container model matched it (0.97x). **The probe explains it**: the docx corpus is 71.7 MB PNG in
   80 MB (one file, `office-docx-020`, is 46% of it), the mechanism B26 already priced; xlsx (PNG 6.1 MB
   in a 7.2 MB corpus, container 3.4x over) and pptx (24 of 40 MB JPEG) are why a suffix rule is wrong.
   Consider pricing a B5 type by its counts when they show a large PNG/JPEG share, not by suffix. If the
   second corpus agrees, lift `.docx` from
   `_PRECOMP_EXPANDABLE` in `_recode_kind` (which also arms B28's nested rule for it), and read
   `.pptx` again (1.64x chain, 1.41x container). The corpora are in `C:\excmp-bench\b27\corpora`.
2. **A third nested corpus** (a `.war`/`.ear`/`.whl`/`.vsix` with a high nested share): the
   factor 3.0 rests on a real `.war` and a synthetic zip. The 1%-nested jar corpus ran 2.2x
   over the container model, so part of the gap may be a general "class-file archives cost more".
3. **Windows 11's top-level menu** needs a signed sparse MSIX, so it waits for E4 (code signing).
   Not done and not possible without a certificate: **E4 signing, E5 auto-update, an `.ico`**.
4. **A second JPEG-in-zip corpus and a second PNG-heavy container** (B26's rates each rest on one).
5. **The estimator's per-file limits** (§4).
6. **Anything the owner asks for.** A rebuilt installer is `packaging\build.cmd` then
   `python packaging\smoke_test.py` (it writes the real Explorer keys and refuses if they exist).

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
| **D6b, I10** | fuzz targets; settings search / drag-out / jump list |
| **Tools** | SREP unpinned (not used by the engine); the pinned Precomp exists only where it was fetched (per checkout) |
| **B15, D4b, C, H, E4-E5** | too early / elevated session / lossy phase / installer phase / signing and auto-update |
| **I5 pipe squatting** | an automated review of the push noted that the intake pipe/mutex names are per user but guessable (`ExtremeCompressor-intake-v1-<user>`): on a **multi-user machine** another local user could create the pipe first and receive the file *paths* a second launch forwards (paths only, nothing is executed from them; the pipe is `UserAccessOption`, the strict wire validation stands). Not exploitable on the single-user target; fixes if it ever matters: put the user SID in the name, treat a failed `listen()` as fatal, and check the server's owner with `GetNamedPipeServerProcessId` before forwarding |
| **E3 leftovers** | the installer is unsigned (SmartScreen warns); the external tools are not bundled (the downloader fetches them beside the app); `PrivilegesRequired=lowest` means per-user only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **A zip container at Insane is priced by its central-directory counts**
  (B26): deflated members' uncompressed size at 0.385 / 0.360 MB/s, PNG members at
  B22's PNG rate, JPEG members at its JPEG rate, the rest at the chain's; **all
  counts 0 keeps the old pricing**; Extreme is untouched; **B5's types keep the
  chain rate** (timed in B27: no model beat it).
- **A header may not claim more than deflate can make** (1032:1), **and a zip's members may not
  occupy more than the zip** (B28); a stored member counts its own bytes.
- **A nested archive member costs `_NESTED_FACTOR = 3.0` plain deflated bytes** (B28, two
  corpora); it reaches `.war .ear .aar .nupkg .whl .vsix` and zips under other names.
- **The Explorer menu is per user (HKCU), a thin launcher, one window via a named mutex**; Extract
  here never overwrites (a collision gets a fresh `name (2)` folder).
- **The frozen build is `--onedir`, never onefile, never UPX; the installer is per-user and
  unsigned.**
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
