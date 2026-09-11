# 🚦 START HERE — handoff (written 2026-09-09)

> **Eight roadmap items closed, and two of them were defects in features the
> roadmap already marked DONE.**
>
> The one worth reading first: **F2's keyfile was write-only.**
> `engine.compress` accepted `keyfile=` and no read path passed one, so the
> engine could write an archive that no code path in the engine — including
> `excmp verify` — could open. Reproduced, fixed, and pinned by the property
> nobody had stated: *whatever factors an archive was created with, the same
> factors must open it, through the same public API a caller uses.*
>
> **Next phase: your choice of three**, and section 4 has the one decision
> that has to be made before D7 can be called done at all.

**1,201 tests on the merged tree** (+142 this session), 2 skipped and 1 strict-xfail, verified green on 2026-09-10.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured:

- **The runtime is not a stable number, and disk headroom is the leading
  suspect.** Three measurements of the same 1,174 tests on this machine, all
  with the system held awake:

  | date | free on `C:` | wall clock |
  |---|---:|---:|
  | 2026-09-09 | 2.9 GB | 1 h 07 m |
  | 2026-09-10 | 14 GB | **14 m 52 s** |

  A 4.5x spread. The cause is **not confirmed** - free space is the variable
  that changed most, and this suite writes 400-770 MB per run into `%TEMP%`,
  but two points do not establish a mechanism. Do not quote either figure as
  "the" runtime; measure it, and clear `%TEMP%\pytest-of-<you>` first either
  way.

  `pytest -q` also buffers everything when stdout is not a terminal, so a run
  looks hung the whole time. Check it is alive with
  `Get-Process python | Select Name,Id,CPU`, not by waiting for output.
- **`pytest`'s elapsed time is not a measurement on this laptop, because it
  sleeps.** One run reported **11 h 28 m**; the System event log showed the
  machine entering sleep at 23:59:20 and again at 04:32:07, `ResumeCount: 3`.
  That figure is an hour of work plus hours of a sleeping machine. Before
  timing anything overnight, hold the system awake for the duration of the
  process - `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` is
  scoped to the calling process and touches no power setting - or check
  `Get-WinEvent -ProviderName Microsoft-Windows-Kernel-Power` afterwards
  before believing the number.
- **Clear `%TEMP%\pytest-of-<you>` first.** Each run leaves 400–770 MB and
  pytest keeps the last three; an aborted run leaves its tree on top. Four
  leftovers took `C:` to 0.92 GB free and the suite failed with
  `No space left on device` inside `test_zstd_window.py` — which reads exactly
  like a K4 regression and is not one.
- **Freeze the code before you start it.** This session started the suite
  three times and invalidated two of them by editing `excmp/` mid-run. A run
  against a tree that no longer exists proves nothing, and each restart cost
  another hour. Do the self-audit *before* the run.

---

## 0. Branches, and the merge — verified, not assumed

Two code branches, both left for review. **They are siblings off `main`, not a
stack** — the second was written before D8 was merged anywhere, so both modify
`engine.py`, `crypto.py`, `volumes.py` and `cli.py`.

```
git merge --no-ff phase-d8-atomic-publish
git merge --no-ff phase-d5-d6-d7-hardening
```

**The merged result was built and tested, rather than trusted to `git`.** In a
throwaway worktree: both merges apply with **zero conflicts**, and the merged
tree passes **1,201 tests** (2 skipped, 1 xfailed) with the tool root pointed
at the real `tools/bin`, so FLAC and zpaqfranz ran too. A real encrypted job on
the merged code — compress with password *and* keyfile, `verify --deep
--source`, extract — came back `ok=True`, source re-read clean, every file
byte-identical.

That check was worth doing and would have been easy to skip. `git merge-tree`
reporting no conflicts says nothing about whether the two halves *work*
together, and the merged run is what found the last two defects in this
session.

Docs went straight to `main` per the working agreement: the roadmap ticks, the
benchmark, `THIRD-PARTY-NOTICES.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, the
`SECURITY.md` update, the issue templates, and this file.

> Note the asymmetry that follows from that split: `main`'s docs now describe
> features whose code is on the branches. That is the established pattern here
> (the ROADMAP header names the unmerged branches), but it does mean **the
> suite on bare `main` is the pre-D5 suite** — 1,059 tests, not 1,201.

---

## 1. What shipped

| item | what it was | what it turned out to be |
|---|---|---|
| **D8** | atomic-write upgrade | the defect was in the half that already existed — `compress()` deleted the destination *before* renaming onto it |
| **D5** | deep verify | `verify_archive` already was zpaqfranz's `t`; the missing half was `v -ssd`, re-reading the **originals** |
| **D6** | fuzz the parser | **eleven** unhandled exception shapes on the first pass, one of which *became* the bomb budget |
| **D7** | CI | written, and **unproven until pushed**; two "green means nothing" holes found in my own draft |
| **E2** | third-party notices | 40 licences read from files; 39 confirmed, 1 (zpaqfranz) explicitly not |
| **E6** | community files | changelog + contributing + templates; the roadmap asked for a "log file" that does not exist |
| **B10** | lepton wheel / drop zstd.exe | lepton was already right; `zstd` was still being reported "not installed" |
| **F5** | honest encryption copy | the wording was already honest — the **delivery** was not |
| **F2** ⚠️ | *(was marked DONE)* | the keyfile was **write-only**. See below |

Full detail with numbers: `docs/ROADMAP.md` (each item's own entry) and
[benchmarks/2026-09-09-d8](benchmarks/2026-09-09-d8-atomic-publish.md).

---

## 2. The five findings worth not rediscovering

### A factor plumbed through one of two sites is not plumbed

F2's keyfile reached `crypto.decrypt_file`'s signature and stopped. Threading
it required **two** decryption sites, because `engine.extract` resolves an
encrypted archive itself rather than going through `opened_for_reading` — and
the one that was missed was the one on the ordinary path.

**Why the suite never noticed:** `tests/test_keyfile.py` tests
`encrypt_file`/`decrypt_file` directly, where the parameter always worked. And
the D9 publish gate — the thing that would otherwise catch an unopenable
archive — verifies the *plaintext* container **before** encryption, by design.
Nothing on either side of that seam ever tried to decrypt what was published.
**If you add a factor, a format or a header field, test it through the public
API, not through the module that implements it.**

### The last three defects were in the fixes, not the features

Worth its own heading because it is the shape of the whole session's tail.
After D5/D6/D7 were done and the branch suite was green at 1,171:

1. `verify --password` **hung forever** from a pipe (getpass reads the console
   on Windows). Fixed.
2. That fix broke **five** tests: under pytest `sys.stdin` is a
   `DontReadFromInput` whose read raises, so "not a terminal" was being
   treated as "has a password on it". The correct rule is *if the read cannot
   happen, ask* - which is also right for a GUI-spawned subprocess with no
   console. Fixed.
3. My own **CI test** then failed, because it asserted
   `_install_root() == <repo>/tools/bin` unconditionally and the merged-tree
   run set `EXCMP_TOOLS_DIR` - a documented override. A test that treats a
   default as an invariant goes red for someone using a feature as intended,
   and a false alarm in the one test guarding CI's cache path is worse than no
   test, because the response to a wrongly-red test is to stop reading it.
   Fixed.

None of the three was reachable from the suite that had just gone green. Each
was found by running the thing one step further out: pipe it, merge it, set the
documented environment variable.

### Three defects came from *running the command*, not from tests

After the engine fix and a green suite, a real CLI run found that `excmp
verify` had **no `--password` flag at all** — so no encrypted archive could
ever be verified from the command line — and that the right password with the
wrong keyfile printed `error: wrong password`, which is false and sends
someone hunting for a password they already have. Neither was reachable from
the test suite as written.

**And the third only appeared when the fixed flag was itself used from a
script.** `echo pw | excmp verify --deep --password --keyfile k a.excmp` **hung
indefinitely** and was killed after ten minutes. `getpass.getpass` is
`getpass.win_getpass` on Windows: it reads with `msvcrt.getwch()`, from the
*console*, and falls back to stdin only when `sys.stdin is not sys.__stdin__`,
which piping does not change. So the flag added to make encrypted archives
verifiable was usable only by a human at a terminal — and the callers who most
need it are a scheduled sweep, a CI job and a batch script over a folder of
archives.

The lesson is narrower and more useful than "test the CLI": **a fix is not
finished until it is used the way the thing it unblocks will be used.** Adding
`--password` to `verify` was verified by running `verify --password`
interactively, which is the one context in which the remaining bug is
invisible.

### "Green" is a claim about what the tests look at

Three separate instances this session:

1. **My own CI draft** would have gone green having downloaded nothing
   (`ensure_tool` returns None rather than raising) and, on a runner without
   7-Zip, green having exercised none of the product (every chain test is
   behind `skipif`).
2. **F5's existing test** built `password.toolTip() + " " + protect_note.text()`
   from a panel where nothing had been typed, so it asserted on the tooltip
   alone — the visible warning could have been deleted and it would still have
   passed.
3. **My own D7 test file** put the corpus-path guard behind
   `importorskip("yaml")`, so a missing dev dependency would have silently
   disabled the one test protecting CI from an ungated absolute path.

### A number that cannot be read is not a number to guess at

`declared_total` was `sum(int(meta.get("size", 0)) for meta in ledger.values())`
and its result *is* the payload budget and D0.3's decompression-bomb budget.
`{"size": 10**400}` sailed through and became one. The fix **refuses the
archive** rather than clamping: a ledger whose sizes cannot be read is a ledger
whose bounds cannot be trusted, and a guessed bound defeats the guard it was
meant to enforce.

The ledger is now validated **once, at the parse boundary** — the same
principle that makes `safepath` the only place an archive-supplied *name* is
judged. Four places downstream had each been trusting its shape.

### XOR is not a way to combine hashes

D5's tree hash is sort-then-hash. XOR is order-free without needing a sort and
is unusable here: it is self-cancelling, so a tree holding the same content at
two paths hashes identically to a tree holding **neither** copy — and this
program deduplicates identical files as a *feature*, so that is the ordinary
case, not a contrived one.

---

## 3. What is measured, so nobody re-measures it

| thing | number |
|---|---|
| D8 overhead, Silesia/normal | **0.234%** of the job; **0.0046%** with `--sidecar` |
| `fsync` of a 48.7 MB archive vs its 80-byte sidecar | **5.3 ms** vs **26.3 ms** — cost tracks *recency*, not size |
| volumes sidecar after D8 | **13.9× cheaper** (218.2 → 15.7 ms) |
| deep verify vs shallow | **4.13 s vs 4.27 s** over three runs each — no measurable cost |
| fuzz soak | **35,000 examples / 7 properties / 136 s**, no violation |
| a clean full suite pass | **14 m 52 s** with 14 GB free; **1 h 07 m** with 2.9 GB free - unstable, see section above |
| Silesia/normal payload | **48,688,221 B** — compare *this*, never the archive digest |

---

## 4. Next: three candidates, and one decision

### The decision, and it is D7's

**D7 is written and cannot be finished from this machine.** A workflow that has
never run is not evidence, and this project does not record unreproduced
behaviour — so it is ticked amber, not green. Finishing it means **pushing the
branch and reading the run**, which is an outward-facing action on a private
repo that also spends Actions minutes.

So: **push `phase-d5-d6-d7-hardening` to see CI run, or leave D7 amber?**
Everything checkable locally is checked (17 tests parse the YAML and assert it
against facts measured here); what a push would answer is whether Actions
accepts the schema, whether 7-Zip is really on the runner image, and how long
a job actually takes there.

### Then, in order of value

**B9 — finish the RAM estimator formula.** `-md=192m` and `-mqs` are settled;
only the formula is left, and it is the kind of item this project is good at:
run 7-Zip at several dictionary sizes, measure peak working set, fit. Bounded
and measurable.

**I6 — "compare presets on this input".** Run the installed profiles on a
≤100 MB sample as real queue jobs and print *measured* ratios onto the preset
cards. `tools/bench.py` already has the harness, and B8 made the estimator
trustworthy enough for this to be honest rather than embarrassing.

**I7 — ❌ WON'T DO. Decided by the owner 2026-09-10. Do not build it and do
not re-open it.** The loader at `gui/app.py:18` is real and 344 strings are
already in `self.tr()`, but there is not one `.ts`, `.qm` or `translations/`
directory in the tree — so the feature was never "nearly done", it was "no
language a user can pick". The loader and the `tr()` calls stay where they
are: both are shipped, harmless and no-ops without `.qm` files, and deleting
working code to express a decision is its own risk.

### What 2026-09-11 closed, and the one correction it forced

**G7 and B9 were the same finding.** `lzma2_decompress_ram` was already
source-pinned and already correct - 66 MiB predicted, **71 MiB measured** - but
`build_extract_cmd` never passed `-mmt`, so a real decode used **255 MiB** and
the figure the app showed was **3.9x optimistic**. G7's "cap dict/window" was
impossible (the archive fixes both); the decoder thread count was the whole
lever, worth **3.6x**. `excmp extract --low-memory` now exists, and on two
cores it measured *faster* as well - which is deliberately **not** why it is
opt-in.

**Compression under-booked too, and my first fix was wrong.** A flat +32 MiB
baseline fitted the three large measurements and then predicted 64.7 MiB for a
job that measures 15.8 - re-creating the "6.0 GB for a 371 KB job" failure.
The margin is proportional now. **An existing test broke on the flat version
and was right to break.**

**⚠️ And I had to correct a roadmap entry I wrote the same day.** I recorded
that LOLZ was an installer component, not a codec, after searching four repack
toolsets and finding it only in a credits line. The owner produced the binary:
`lolz v22c4b`, adaptive rANS, round-trips byte-identically, and beats
`7z -mx9` by **+11.93% on a medical image, +2.89% on float data, +2.22% on a
binary executable** while **losing 2.93% on English prose**. Absence of
evidence in four repos was not evidence of absence, and the entry stated the
stronger claim. It is a per-category specialist like B4's FLAC - and it is
**measured, not built**: the gate before any code is a comparison against
`precomp → 7z`, because 7-Zip alone is not what this app ships and three of
four proposed specialists have already lost to that chain.

### Two items whose premises need re-examining before you start

**G7 (RAM-limited extraction) may not mean what the roadmap thinks.** At
extract time the memory is set by *the archive*: 7-Zip's dictionary is fixed by
whatever created it, and the zstd window comes out of the frame header (which
is exactly what K4's read ceiling is about). So "cap dict/window" is not
available to the extractor. What *is* available: cap threads, and refuse or
warn when an archive's declared requirements exceed a limit. That is still
worth having — but write the item down again before building it.

**D4 (disk-full simulation) needs elevation.** A size-limited volume means a
VHDX, and `diskpart`/`New-VHD` want administrator; `subst` does not limit size,
so it cannot stand in. Either run that session elevated or find another way.
D8 did give it a specific target though: `publish()`'s short-write refusal has
a unit test and has never met a real `ENOSPC`. And note the suite itself
produced a genuine `ENOSPC` this session, by accident, which is worth
remembering as a cheap source of one.

---

## 5. Verify before you believe anything here

```
.venv\Scripts\python.exe -m pytest tests\test_atomic_publish.py -q      # D8, 18
.venv\Scripts\python.exe -m pytest tests\test_deep_verify.py -q         # D5, 18
.venv\Scripts\python.exe -m pytest tests\test_fuzz_container.py -q      # D6, 48
.venv\Scripts\python.exe -m pytest tests\test_ci_workflow.py -q         # D7, 17
.venv\Scripts\python.exe -m pytest tests\test_keyfile_roundtrip.py -q   # F2, 13
.venv\Scripts\python.exe -m pytest tests\test_f5_honest_copy.py -q      # F5, 12
.venv\Scripts\python.exe -m pytest tests\test_inprocess_tools.py -q     # B10, 7
.venv\Scripts\python.exe tools\fuzz_container.py --examples 5000        # a real soak
```

And the corpora are not at risk from the suite — verified again this session,
clean:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

If a number here disagrees with what you measure, **trust your measurement and
correct the doc.**

---

## 6. Session mechanics

**Corpora kept on disk — do not re-download or rebuild:**

| path | what | why keep |
|---|---|---|
| `C:\excmp-bench\silesia` | 202 MB, 12 files, **211,938,580 B** | the anchor. Payload size for normal is **48,688,221 B** — compare *that*, not the archive digest |
| `...\Downloads-1\Songs` | 610 `.flac`, 110 `.wav` (5.07 GiB) | B4's material; the 610 FLACs are still an unexamined question |
| `Downloads-1\PalluVaapaHDD\0No Need To Check\Programs` | 721 MB, 42 installers | the estimator backtest pins exact sizes |

**Disk space is a real constraint.** `C:` sits around 13 GB free and the
Silesia job does not fit there with its temp — put `StageContext(temp_dir=...)`
on `D:` (12 GB free) and only the archive on `C:`. That also means job *times*
are not comparable to B8's.

**Plan mode is NOT needed for the normal `/next` flow.** Turn it on for
**B6** (its DLL-bootstrap flaw is an architecture decision touching the
lossless guarantee) and **Phase H** (large, and H5 conflicts with B6). Skip it
for B9, I6, G7.

**Rename the session as soon as you know the phase.** That instruction now
lives in `.claude/commands/next.md` where the command itself will load it,
because it kept being forgotten.

**Re-judge B6's size.** The "3-4 sessions" figure was made when context could
not hold its five sub-items at once. Read the audit note, then size it.

---

## 7. Everything still open

**Nothing left is a known defect.** D8 closed the last one found by
inspection; F2's was found by an audit and closed the same day.

### Medium

| item | what | note |
|---|---|---|
| **D7** | CI | ⏳ amber until a run exists — section 4 |
| ~~**B9**~~ | ~~RAM estimator formula~~ | ✅ **done 2026-09-11** - it was unreachable, not unfinished |
| **I6** | "compare presets on this input" | `tools/bench.py` has the harness |
| ~~**I7**~~ | ~~i18n pipeline~~ | ❌ **won't do** — owner's decision 2026-09-10 |
| ~~**G7**~~ | ~~RAM-limited extraction~~ | ✅ **done 2026-09-11** - `--low-memory`, 3.6x less peak RAM |
| **D4** | disk-full simulation | 🟡 **injection half written**; the real-volume half needs elevation |
| **B12** | LOLZ as a per-category codec | ⚠️ **measured, not built.** +11.93% on images, −2.93% on text. Gate: compare against `precomp → 7z`, not 7-Zip alone |

### Large, or blocked

| item | what | status |
|---|---|---|
| **B6** | xtool + Oodle | **blocked on test material.** No Oodle game folder here; archives would only restore on the machine that made them |
| **Phase C** | C1-C7: FFmpeg fetch, ffprobe, AV1 encode, honest ETA, `oxipng`, `qpdf` | the opt-in lossy phase; C6/C7 measured and waiting. **Note E2's finding**: a GPL FFmpeg build needs its licence text *and* a source offer placed beside it |
| **Phase H** | H1-H6: Inno Setup installer | large, and H5 conflicts with B6 |
| **E3-E5** | PyInstaller build, signing, auto-update | **only if this is ever shared.** E2 now lists exactly which licences a redistributable build engages — start there |
| **D0.6** | Windows process mitigations for subprocesses | deferred to its own session by design |
| **I5** | Explorer context menu | **ask first** — writes to HKCU |

---

## 8. Things not to re-litigate

- **The repo is private and the OSI rule is retired** (2026-09-01). Any tool
  may be used; the lossless guarantee matters *more* as a result.
- **Never weaken verification to fit a tool in.**
- **`os.replace` needs no `unlink()` first.** It overwrites atomically on
  Windows and POSIX. Adding one back restores D8's defect.
- **The publish read-back is not paired with an expectation on the plain
  path**, and that is measured, not an omission — nothing runs between the
  write and the rename.
- **`publish()`'s `(st_dev, st_ino, st_size)` check never refuses on its own.**
  `st_ino` is a real file index on NTFS and synthesised on FAT32/exFAT, which
  is what a USB stick arrives formatted as. A disagreement re-hashes; only
  differing *content* refuses.
- **Windows cannot flush a directory.** Contents are flushed; rename metadata
  durability is the filesystem's.
- **The ledger is validated at the parse boundary, not at each reader.** If you
  add a ledger field, validate it in `manifest.validate_ledger`.
- **D5's tree hash is sort-then-hash and must never become XOR.** See §2.
- **`zstd` stays in the tool table with an `IN_PROCESS` qualifier**, not
  deleted — it is also a *stage* id, and a row that explains why it has no
  binary beats a name with no entry anywhere.
- **HypoFuzz is not installed and D6 did not need it.** The parser surface is
  pure byte-in. Install it only if the parser grows deep branchy paths.
- **An `.excmp` is not byte-reproducible.** `created_utc` moves the deflated
  manifest by up to 3 bytes and 7-Zip's payload is length-deterministic but
  not byte-deterministic.
- **`verify_restore` does not compare timestamps**, on purpose.
- **The zstd window is fitted to the input**, and the *read* ceiling stays
  independent of the write setting — that coupling was K4's bug.
- **zpaqfranz's licence is not established on this machine** and E2 says so
  rather than guessing. Settle it before any public release.
- **Four top-level tabs is the ceiling.**
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
