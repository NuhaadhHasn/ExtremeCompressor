# 🚦 START HERE — handoff for the next session (written 2026-08-01)

> Previous session: **Phase D0 (security hotfix) — implemented, tested, merged.**
> Next session: **Phase J — Smart Advisor** (recommend + preview + estimated
> size/time). Read this file, then `docs/ROADMAP.md` → Phase J.

---

## 1. State of the repo

`main` is clean and everything is committed and merged. Three commits landed:

| commit | what |
|---|---|
| `15275e0` | docs: the source-code study (13-22), security/UI/perf research (08-12), roadmap rewrite |
| `a262ec2` | fix(security): the D0 path validator + ledger-bounded extraction |
| `d4889b6` | docs(bench): the 721 MB real-data acceptance run |

**223 tests pass** (`.venv\Scripts\python.exe -m pytest -q`), up from 91.

Worktrees: two redundant ones were removed. Remaining are `main`,
`extremecompressor-phase-d0-security-28fc68` (D0's branch, already merged — safe
to delete) and `extremecompressor-research-plan-5f5cdb`.

⚠️ **One gotcha for future worktree cleanups:** the old
`claude/pyside6-gui-phase-a-f8af25` branch has a history *disjoint* from `main` —
no merge base, because Phase A was replayed onto main with fresh SHAs. So
`git log main..<branch>` shows every commit as "missing" and proves nothing.
**Compare trees instead:** `git diff --stat main <branch>` (empty = safe).

## 2. What Phase D0 actually shipped

New `excmp/safepath.py` — one validator for every path an archive supplies, used
by `extract_stored()`, `read_container()`, `verify_restore()` **and**
`write_container()` (so we cannot create an archive we would refuse to read).

The bug was real and was demonstrated before fixing: a crafted `.excmp` wrote
both a traversal entry **and** an absolute-path entry outside the destination,
while the destination itself stayed empty.

Three findings worth not rediscovering:

1. **There were two escape primitives, not one.** `Path("out") / "C:/evil"`
   returns `C:\evil` — Python's `/` discards the left operand when the right side
   is absolute. A drive letter escapes with no `..` anywhere in the name.
2. **Reject-not-mangle was forced, not just preferred.** 7-Zip/NanaZip/PeaZip all
   *rewrite* hostile names. We cannot: the ledger keys are the authoritative
   filenames, so a rewritten name could never satisfy `verify_restore()` —
   mangling would turn a clear "hostile archive" into a puzzling hash mismatch.
3. **`tarfile`'s `data` filter strips a leading `/`** rather than raising, and only
   raises `AbsolutePathError` if the name is still absolute afterwards (on Windows
   that means a drive letter). The test pins *containment* for `/x` and a raise for
   `C:/x`.

**Still open from D0:** `D0.6` (Windows process mitigations on tool subprocesses)
was deliberately deferred to its own session — it is ctypes work on subprocess
spawning, unrelated to archive parsing.

## 3. Phase J — the actual next job

**Full spec: `docs/ROADMAP.md` → "Phase J — Smart Advisor" (J1-J8).** Scope was
agreed as *estimates + the extra smart features*, ~2 sessions.

**Read `gui/suggest.py` before writing anything.** A large part of what was asked
for already exists and is unit-tested in `tests/test_gui_suggest.py`:
`recommend_profile()` (profile + the reason string), `summarize()`, `headline()`,
`gain_note()`, `store_explanations()`, `strongest_profile()`. All Qt-free.
**Do not rewrite them — extend them.**

Genuinely missing: **estimated output size**, **estimated time**, and showing all
four profiles side by side.

### The one number that justifies the whole phase

From the real 721 MB corpus
([`docs/benchmarks/2026-08-01-real-programs-folder.md`](benchmarks/2026-08-01-real-programs-folder.md)):

| profile | time | saved |
|---|---|---|
| normal | 62.4 s | 2.80% |
| extreme | 166.3 s | 2.97% |

**Extreme cost 2.7× the time for 0.17 extra percentage points**, and nothing in
the app warns about that until after the wait. Making that visible *before* it is
paid for is the point of J3.

### Two design decisions already made — don't re-litigate

- **Estimate by measuring, not by table lookup.** The analyzer already reads
  3×1 MiB per file for entropy; compress those same samples in-process with
  `zstandard` to get a real per-file ratio, then scale to the profile. Store-route
  files contribute at **exactly 1.0** (verbatim copies — that part is not a guess).
  Always return a **range**, never false precision.
- **Time needs a two-rate model.** A single MB/s figure is actively misleading:
  81% of the real corpus was *stored* (disk-bound) and only 141 MiB was *piped*
  (CPU-bound), so the blended "11.6 MB/s" would mispredict on any other mix. Use
  `stored/io_rate + piped/codec_rate[profile]`. Measured 2-core piped-only
  starting points: **normal ≈ 2.5 MiB/s, extreme ≈ 0.9 MiB/s**; `io_rate` ≈
  100 MB/s, capped by the *source* disk.

Rates are content-dependent (the 2026-07-18 synthetic run hit ~6.5 MB/s on
compressible data vs 2.5 here) — which is why **J7 self-calibration** exists:
record real throughput per completed job and blend it in, so estimates converge on
this machine's true speed. And **J8 scores the estimator** against both recorded
benchmark runs as a pytest — an estimator nobody backtested is a guess with a
progress bar.

### Dependency to decide early

**J5** (remember last choice per content type) needs `QSettings`, and the app
currently persists **nothing** — that is roadmap **I1**. Either do I1 first, or
ship the QSettings bootstrap inside J5 and let I1 build on it. Pick one at the
start of the session rather than half way through.

## 4. Suggested first prompt for the next session

> Continue ExtremeCompressor. Read `docs/NEXT-SESSION-START-HERE.md`, then the
> Phase J section of `docs/ROADMAP.md`, then `gui/suggest.py` and
> `excmp/analyzer.py`.
>
> Implement **Phase J (Smart Advisor)** using TDD — J1 sample-based size
> estimator and J2 two-rate time estimator first, in a new Qt-free
> `excmp/estimate.py`, with J8's backtest against both files in
> `docs/benchmarks/` written as the failing test *first*. Then J3 the profile
> comparison table with the "not worth it" flag, then J4 the compression-side
> free-disk preflight.
>
> Extend `gui/suggest.py` — do not rewrite `recommend_profile()`. Decide the
> J5/I1 QSettings question up front. Run the full suite (223 existing tests) and
> commit. Docs-only changes go straight to `main`; keep the code on a branch for
> me to review.
>
> Leave J5-J7 for the following session if the context fills up — one phase per
> session, little by little.

## 5. Standing rules (do not relearn these)

- **No AI attribution in commit messages** — no `Co-Authored-By`, no "Generated
  with Claude Code". These are public portfolio repos. Audit before committing.
- **Docs-only commits go straight to `main`; code goes on a branch** left
  unmerged for review. Pending files often sit in the **main** checkout even when
  the session runs from a worktree — check `git status` there too.
- **The repo stays 100% OSI-clean** (required for free SignPath signing). Never
  bundle SREP, lolz, oo2core/Oodle DLLs, unrar.dll, or xtool Patreon builds.
- **Target hardware is weak on purpose**: 2-core i7-3540M, 16 GB. Default threads
  is 2, not 4.
- **Lossless is a hard guarantee; lossy is always opt-in.**
- **Post-restore SHA-256 comparison is the acceptance gate for every stage** —
  tool exit codes cannot be trusted (Precomp `exit(0)`s on fatal restore failure).

## 6. Real test data on this machine

Useful for real-run QA (both confirmed present, on a slow external drive — avoid
recursive `du`, it times out):

```
C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programs
    37 top-level files, 5.76 GB - installers (.exe/.msi) + archives (.rar/.zip).
    81% already-compressed bytes: the worst-case ratio corpus, and a good
    false-positive check for safepath (filenames with spaces, parens, '=').
C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programming Tutorials, Guides, Course, and Files
    deep tree, course material - untested so far, likely more compressible.
```

`docs/benchmarks/2026-08-01-real-programs-folder.md` records the exact 6-file
subset used, so the run is repeatable.
