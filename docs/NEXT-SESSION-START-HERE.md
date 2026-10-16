# 🚦 START HERE — handoff (written 2026-10-16)

> **B18 is merged into `main`** (2026-10-16, `6adf005`): local suite 1,548
> passed, 2 skipped, 1 xfailed, corpus guard clean, CI green. B14 is on
> `main` (docs only). **`b13-followups`** (1 test-only commit, CI-green) was
> being merged next; **if it still exists on GitHub, do §3.2 first.**
>
> **Next session is an owner agenda**, in this order (§3 has each spec):
> 0. **Name the session** (`/rename`; the title tool isn't in this client).
> 1. ~~Merge `b18-settings`~~ ✅ done.
> 2. **Merge `b13-followups`** if it's still open.
> 3. **Quiet-machine re-measures** (B13's Ogg restore rate, packMP3's rates),
>    only when the owner says the machine is quiet.
> 4. **B6**, only with an owner-provided Oodle sample.
>
> **The owner runs other sessions and Docker Desktop on this machine, and
> Docker and WSL must stay running** (owner, 2026-10-16). `vmmem` alone holds
> ~6.5 GB; 2–4 GB is usually free. Claude Code reaps background shells when
> memory runs critically low (it killed a benchmark and the full suite on
> 2026-10-15/16). So: one heavy process at a time, below-normal priority
> (checked with `Get-Process`), rows logged as they land, and **the full
> suite last**, when the owner says memory allows.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **Use `C:\excmp-bench\b17\suite.py`** (corpus guard around the suite), run
  from the repo root, below-normal from creation:
  `cmd /c 'start "" /b /belownormal /wait .venv\Scripts\python.exe C:\excmp-bench\b17\suite.py > out.txt 2>&1'`.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `docs/` mid-run is fine; nothing else is.

---

## 1. What shipped (2026-10-15 → 10-16)

| item | what | record |
|---|---|---|
| **B14** ❌ | DArc 3.0.4 (maintained FreeArc, Rust) **measured, not integrated**: +1.37% to +27.80% against Insane on all three corpora, beats Extreme only on deflate data (−1.00%). B12a closes with it | [2026-10-15-b14](benchmarks/2026-10-15-b14-darc.md) |
| **B18** ✅ | (a) zstd keeps `-1` (identical bytes; timings too noisy), now honours an explicit thread count, capped. (b) **`-intense` kept on**: off saved 0.08–0.85% but lost whole raw-zlib streams (−16.8% synthetic); the local suite caught it. (c) **MP3/MP4 probe rule**. (c′) **every MP3 to Precomp on Extreme/Insane** (packMP3): 18.02%/15.87%/18.97% end to end | [2026-10-15-b18](benchmarks/2026-10-15-b18-settings.md) |
| B13 follow-up | the toolfetch discovery test finally runs (it always skipped); checks balrogg, flac, qpdf | branch `b13-followups` |

---

## 2. Findings worth not rediscovering

### Precomp recodes MP3, and the probe can't see it

Precomp v0.4.7 lists `3 = MP3` among its stream types: packMP3, built in.
Every one of 21 real MP3s lost 10.0–25.9% through `precomp -cn → 7z`,
including the ones the zstd probe called incompressible. It costs
cross-file matches (two near-identical MP3s become unrelated streams), and
its time estimate is still optimistic (§3.3). **Before calling any media
"already compressed", ask what Precomp's `-t` list says it can open** —
`J = JPG` is on it too, unmeasured against lepton.

### Filter a corpus by the exact suffix the rule ships for

B18's "57 MP4s" were 51 MP4 + 6 MOV, because the probe search matched
`.mov` too. The reviewer caught it; the MP4-only figures moved from
8.99%/1.12% to 9.20%/1.61%.

### On a Precomp chain, `expected` is a ceiling

The GUI shows it as "≤ X". An average there (0.835 for MP3) put "≤ 64.0 MB"
over a 64.4 MB archive. Any per-type ratio on a Precomp chain must use the
worst case measured, not the mean (`_MP3_PRECOMP_RATIO` uses 0.90).

### Two measurement traps

- **The venv's `python.exe` is a launcher.** `Popen(...)._handle` on a Python
  child reads the launcher's memory (4 MB for a 171 MiB job). Measure a
  Python child from inside it. Native tools are fine.
- **Untyped ctypes `SetPriorityClass(GetCurrentProcess(), …)` silently
  fails** (`ERROR_INVALID_HANDLE`). Use `creationflags=` or
  `start /belownormal`, and check with `Get-Process`.

### Write test files with the Edit tool

A Python-in-heredoc rewrite turned `\x00` into real NUL bytes and `\b` into
a backspace, and a mangled path made the real-file tests skip silently (5
skipped, which is how it was noticed). Watch the skip count.

### Still true

- **Measure the incumbent that fills the slot**, **two corpora**, **never
  pin a contended timing**, **a silent no-op looks like a negative result**,
  **render the GUI** (the shrink-hint change was rendered in both themes
  with Details open: `C:\excmp-bench\b18\render_hint.py`), **the archive is
  not byte-reproducible**, **CI's runner is not the target**.

---

## 3. The agenda, in order

### 1. Merge `b18-settings`

Reviewed by two lenses and a skeptic (every finding reproduced or measured,
then fixed), the GUI change rendered in both themes, CI green on `e9e9e93`.
What's left is the local gate: `suite.py` (corpus guard around the suite,
below-normal, see the top). Every test must pass. Expected count: 1,504
passed on `main` before, plus about 50 new B18 tests (some skip without the
bench samples in `C:\excmp-bench\b18\samples`). If it passes: `git merge
--no-ff b18-settings` on `main`, push, delete the branch locally and on
GitHub. Then update CLAUDE.md: the test count, and the threads paragraph
(zstd's `-1` **has** now been measured against 2: identical bytes, +184 MiB,
timings too noisy; an explicit count is honoured, capped at `-1`).

### 2. Merge `b13-followups`

One test-only commit: `test_an_e1_installed_tool_is_found_by_normal_discovery`
now restores the real install root for itself. It was mutation-checked here
(fails with discovery broken, passes against `tools\bin`), and CI is green.
Same gate and merge. Then `git worktree remove ..\ExtremeCompressor-b13fu`
and `..\ExtremeCompressor-main` (created for this docs commit).

### 3. Quiet-machine re-measures (only with the owner's say-so that it's quiet)

- **B13's Ogg restore rate**: `C:\excmp-bench\b13\b13_app.py C:\excmp-bench\b13\music <out> quiet normal`,
  normal priority, nothing else heavy running. Compare D9 and extract
  seconds with `_PACK_DECODE_RATE` (1.5 MB/s); re-pin only from a median of
  three.
- **packMP3's rates** (new, B18): Extreme on the music MP3s was predicted
  13–82 s and took 180 s; the self-test assumes 6.5 MB/s restore for the
  Precomp chain while packMP3 restored at 0.07–1.46 MB/s per file
  (contended). `C:\excmp-bench\b18\mp3_perfile.py` and `b18_app.py
  <corpus> <out> <label> extreme` measure it. The estimator needs an MP3
  term in the time model the way `pack_cost` has one for Ogg.

### 4. B6 — only with an owner-provided Oodle sample

Unchanged. It also settles **`-intense`**: B18 measured it costing
0.08–0.85% on installers and deflate archives, and kept it on because
without it raw zlib streams (game paks) aren't found at all. Measure both on
real game data; a per-data-type switch may be the answer.

---

## 4. Everything else still open

| item | what |
|---|---|
| **Media not yet measured** | MOV (65 files in Downloads, a corpus is there), MKV, WebM, M4A: still stored. Precomp `J = JPG` vs lepton (B2) never compared |
| **Estimator** | per-file only: near-duplicate files made one corpus come out *under* its range (MP3 misc, Normal). Any piped duplicates do this |
| **I11 leftovers** | zpaqfranz reports 100% at stage start (Insane's bar freezes); a store-only job's bar jumps; old calibration self-corrects in ~9 jobs |
| **B13** | the owner's *Celeste* FMOD download never arrived |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Precomp keeps `-intense`** (B18): off is 0.08–0.85% smaller on
  installers and deflate archives but finds nothing in raw zlib streams.
  B6's game data is the only thing that reopens it.
- **Every MP3 goes to Precomp on Extreme/Insane**; on Fast/Normal the probe
  decides, as for MP4 and Ogg. MOV/MKV/WebM/M4A stay stored until measured.
- **zstd keeps `threads=-1`** by default; an explicit count is honoured and
  capped at it.
- **DArc is not integrated.** It reopens only if a release writes `cm` or
  `pmm` (ppmonstr).
- **Insane runs `-m58`, and balrogg `-9` on Insane.** balrogg effort: Fast
  `-1`, Normal `-4`, Extreme `-5`, Insane `-9`.
- **Default threads is one per physical core** for 7-Zip and zpaqfranz.
- **Code is merged after suite + review + CI green on its branch**, and the
  branch is deleted. The owner doesn't want to review diffs.
- **LOLZ is not integrated. SREP stays out.**
- **With balrogg installed, Ogg stays on the store route and is repacked.**
- **The repo is private and the OSI rule is retired**; the lossless guarantee
  matters more as a result. **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**

---

## Suite history, 2026-10-16

- 02:43, `e9e9e93`: **1 failed**, 1,548 passed, 2 skipped, 1 xfailed (corpus
  guard clean). `test_extreme_manifest_records_chain` expects Precomp in the
  chain for raw zlib data; with `-intense` off Precomp found nothing there.
  A real regression, not a stale test: fixed in `3821a99` by keeping
  `-intense` on (record §3).
- 03:40 and later, `3821a99`: two reruns reaped for low memory; the third
  passed, 07:52: **1,548 passed, 2 skipped, 1 xfailed** (25 min 2 s), corpus
  guard clean. Merged as `6adf005`.
