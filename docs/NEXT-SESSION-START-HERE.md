# 🚦 START HERE — handoff (written 2026-10-15)

> **Everything is merged into `main` and pushed; CI is green on `main`. No
> branch exists besides `main`.**
>
> **Next session is an owner agenda, carried over from 2026-10-01**, in this
> order (§3 has each spec):
>
> 0. **Name the session.** No download tabs are needed: DArc is already
>    fetched and verified (§3.1).
> 1. **B14**: DArc against the shipped route.
> 2. **B18**: the small unmeasured settings.
> 3. **B13 follow-ups**, small: the restore-rate re-measure on a quiet
>    machine (§3.3).
> 4. **B6**, only if the owner has provided an Oodle sample by then.
>
> Each code item gets its own branch, merged after suite + review + CI green
> (CLAUDE.md, Commits).
>
> **The owner runs another development session on this machine (2026-10-15).**
> Keep CPU use low: no workflows or parallel subagents unless asked, one
> benchmark process at a time, started at **below-normal priority** (see
> §2, "Running beside another session"), and the full suite only when
> nothing else of ours is running.
>
> **Target machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads),
> 15.9 GB. Run `Get-CimInstance Win32_Processor` before quoting a speed.

```
.venv\Scripts\python.exe -m pytest -q
```

- **The runtime is not a stable number** (20 min 28 s to 30 min 38 s on this
  machine on one day). Measure it; don't quote it.
- **Use `C:\excmp-bench\b17\suite.py`**: it holds the machine awake and wraps
  the corpus guard around the run.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run
  invalidates the run. Editing `docs/` does not.

---

## 0. State of the repo

| | |
|---|---|
| `main` | I11 and B13 merged and pushed |
| branches | only `main`, locally and on GitHub |
| tests | **1,504 passed, 2 skipped, 1 xfailed** locally (2026-10-15, 19 min 42 s at below-normal priority, corpus guard clean) |
| CI | green on the B13 branch's final commit before the merge (9 min 29 s; balrogg is not on the runner, so its real-tool tests skip there) |
| pinned tools | `tools/bin/balrogg/1.4/` (new, fetched through `toolfetch`), flac, qpdf, zpaqfranz |
| AI attribution | none, anywhere. Audited before each commit |

---

## 1. What shipped (2026-10-01 → 10-15)

| item | what | record |
|---|---|---|
| **I11** ✅ | The D9 self-test is a visible, timed phase: an announced start, a 1 s heartbeat (silent while paused), its estimated share of the bar, "verifying" / "verifying, past estimate" / "finishing". Also fixed J7 learning the self-test as codec time (Insane estimates carried it twice) | ROADMAP I11 |
| **B13** ✅ | balrogg repacks Ogg audio on the store route: **music 1.112% → 13.181% end to end** (18/18 packed and restored), game music + speech 0.297% → 10.785% | [2026-10-06-b13](benchmarks/2026-10-06-b13-balrogg.md) |

---

## 2. Findings worth not rediscovering

### A store-route codec's safe failure is a silent one

B13's first end-to-end run saved **0.2%** instead of 13%. `pack()` stores
a file raw whenever its round-trip check fails, which is the correct,
lossless answer. A bug that made the check fail therefore looked exactly
like "this file doesn't shrink". The cause was a size watch that killed
balrogg's honest decodes, because balrogg grows its output 1 MiB ahead of
the data. **Always measure a specialist through `engine.compress` and read
the ledger's `codec` counts**, not just the tool on its own. The suite
missed it because the fixtures decode before the first poll.

### Running beside another session

Start benchmarks at below-normal priority so the owner's work isn't
starved. From PowerShell:
`$p = Start-Process cmd.exe -ArgumentList '/c','<script>.cmd' -WindowStyle Hidden -PassThru; $p.PriorityClass='BelowNormal'`
(children inherit it). Put the commands in a `.cmd` file: a `cmd /c` line
with nested quotes failed silently on 2026-10-15. Timings taken this way
are contended and **must not be pinned**.

### Two numbers in the estimator are priors from contended runs

`estimate._PACK_DECODE_RATE` (1.5 MB/s) and the pack encode rates. In the
app, decoding 147 MB of packed Ogg took 349 s in D9 and 506 s in extract
(~0.3–0.4 MB/s), against ~1.5 MB/s per file from the CLI. That's
unexplained, and partly the low priority. **The time estimate for an Ogg
job's restore is optimistic by up to ~3× until a quiet run settles it**
(§3.3).

### The review keeps paying, and so does checking what it couldn't

B13: 37 findings. 27 were skeptic-checked (21 confirmed, 17 distinct;
6 refuted). 10 lost their skeptic to an API outage, and **5 of those 10
reproduced when re-checked by hand**. Never treat an unchecked finding as
refuted.

### Still true

- **Measure the incumbent that fills the slot.** For B14 that's
  `precomp → zpaqfranz -m58` (Insane) and `precomp → 7z` (Extreme).
- **Two corpora, or don't quote the first.** B13's corpus 2 priors were
  refit on corpus 2, so that test is in-sample. Its docstring says so.
- **Never pin a single timing run, and never a contended one.**
- **A silent no-op looks exactly like a negative result.** Exit 0 isn't
  evidence; `verify_restore` is.
- **Render the GUI** (`tools/qa_sweep.py`, both themes) before calling a
  GUI change done. It found the Ogg card saying "stored bit-exact" beside a
  table promising 15%.
- **`~/.excmp/calibration.json` is global state**, isolated in `conftest.py`.
- **The archive is not byte-reproducible.** Compare sizes, never digests.
- **CI's runner is not the target**: tests that depend on cores or RAM pin
  the machine they describe.

---

## 3. The agenda, in order

### 1. B14 — DArc against the shipped route

**Already fetched and verified (2026-10-01):**
`C:\excmp-bench\b14\bin\darc-3.0.4-windows-amd64.zip`, 5,032,728 B,
SHA-256 `112d021f2ffc981bddb4a94f34f56118ae48f8d40b4e18772a27892a4747b83a`
(GitHub's published digest, matched). Unpacked beside it: `darc.exe`
(`33538f89…6b58`) and `unarc.exe` (`3fce9909…a70a`). GPL-3.0, a Rust
rewrite of FreeArc. Its README documents `-m0`…`-m9`, `-m1x`…`-m9x`, `-mx`
and `-max` (which calls external precomp/ecm/ppmonstr), `-mt`, `-md`, `-s`,
`-lc`/`-ld`, and `--print-config` for the method table.

DArc must beat what ships, on both B12 corpora
(`C:\excmp-bench\b12\fresh.pcf` and `programs.pcf`) and Silesia, at
**Extreme** `precomp → 7z` and **Insane** `precomp → zpaqfranz -m58`
(deflate `.pcf`: 42,852,397 B). Every archive is restored with `unarc` and
SHA-256 compared. Try FreeArc's strongest methods. Pin the zip in
`TOOL_MANIFEST` only if it wins.

### 2. B18 — three unmeasured settings

Spec: [ROADMAP.md, B18](ROADMAP.md). (a) zstd `threads=-1` against 2.
(b) `precomp -intense`, with and without, on both corpora. (c) MP3 and
video: does the analyzer's probe predict a real gain? Search read-only for a
corpus first. Change routing only if measured.

### 3. B13 follow-ups (small)

- **Re-measure the restore rate on a quiet machine**: run
  `C:\excmp-bench\b13\b13_app.py C:\excmp-bench\b13\music <out> quiet normal`
  at normal priority with nothing else running. Compare D9 and extract
  seconds with `_PACK_DECODE_RATE`. Re-pin only from a median of three.
- **`tests/test_toolfetch.py::test_an_e1_installed_tool_is_found_by_normal_discovery`
  has always skipped.** The module's autouse fixture points the install root
  at an empty temp dir. Pre-existing, but it's the only check that
  `find_tools` sees a pinned raw tool.
- The owner's *Celeste* FMOD download never arrived. If it does: `.bank`/`.fsb`
  aren't Ogg containers, so balrogg can't read them without an unwrap step.
  Measure before building one.

### 4. B6 — only with an owner-provided Oodle sample

xtool + Oodle. Blocked until a legitimate sample exists (a game the owner
owns, installed here). Never a third-party DLL site.

---

## 4. Everything else still open

| item | what |
|---|---|
| **I11 leftovers** | zpaqfranz reports 100% at stage start, so Insane's compress bar freezes for the whole stage (pre-existing). A store-only job's bar jumps from 0 to its verify start (pre-existing). Calibration files learned before I11 self-correct in ~9 jobs |
| **D6b, I5, I10** | fuzz targets; Explorer menu (**ask first**, HKCU); settings search / drag-out / jump list |
| **B15, D4b, C, H, E3–E5** | too early / elevated session / lossy phase / installer phase / release-only |
| **I7** | ❌ won't do |

---

## 5. Things not to re-litigate

- **Insane runs `-m58`, and balrogg `-9` on Insane.** The owner chose "best
  for compression". `-9` costs ~5× `-5`'s time for +0.03 points; the table
  shows that cost, and the owner decides.
- **balrogg effort:** Fast `-1`, Normal `-4`, Extreme `-5`, Insane `-9`.
- **Default threads is one per physical core**, measured and RAM-capped.
- **Code is merged after suite + review + CI green on its branch**, and the
  branch is deleted. The owner doesn't want to review diffs.
- **LOLZ is not integrated.** It reopens only on game/DXT data, against `-m58`.
- **With balrogg installed, Ogg stays on the store route and is repacked**;
  without it, B13a's probe rule (pipe when the probe says it shrinks) applies.
- **The repo is private and the OSI rule is retired**; the lossless guarantee
  matters more as a result. **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **SREP stays out**: it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
