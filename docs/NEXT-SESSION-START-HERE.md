# 🚦 START HERE — handoff (written 2026-09-20)

> **Everything is merged, pushed and green. There is nothing awaiting review
> and no branch to merge.**
>
> `main` = `origin/main` = `7f60e7f`. Working tree clean. **1,229 tests**
> passing locally, and the **CI on GitHub is green** — the last three pushes
> all passed on `windows-latest`.
>
> **Next phase: I6**, unless you want to chase B13 (see §3). I6 needs nothing
> from outside this machine; B13 is the better prize and needs a download plus
> a corpus that does not exist here yet.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** Same tests, same machine, system held
  awake for both: **1 h 07 m** with 2.9 GB free on `C:`, **14 m 52 s** with
  14 GB free. A 4.5× spread. Free space is the variable that moved most and the
  suite writes 400–770 MB per run into `%TEMP%` — but two points do not prove a
  mechanism. **Measure it; do not quote either figure.**
- **`pytest`'s elapsed time is not a measurement on this laptop, because it
  sleeps.** One run reported **11 h 28 m**; the System event log showed sleep at
  23:59:20 and again at 04:32:07, `ResumeCount: 3`. Hold the machine awake for
  the life of the process with
  `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)` —
  process-scoped, touches no power setting — or check
  `Get-WinEvent -ProviderName Microsoft-Windows-Kernel-Power` before believing
  a number.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before starting.**
  Leftover trees once took `C:` to 0.92 GB and the suite failed with
  `No space left on device` inside `test_zstd_window.py` — which reads exactly
  like a K4 regression and is not one. And editing `excmp/` mid-run invalidates
  the run: that happened three times in one session and cost an hour each.

---

## 0. State of the repo

| | |
|---|---|
| `main` | `7f60e7f`, in sync with GitHub |
| branches | **only `main`** — nothing unmerged, nothing dangling |
| CI | green; `.github/workflows/ci.yml`, runs on every push |
| tests | 1,229 passed, 2 skipped, 1 strict-xfail |
| corpus guard | clean — 165 files, nothing touched |
| AI attribution | **none, anywhere.** Audited across all refs |

**On attribution:** 19 old commits from July did carry
`Co-Authored-By: Claude`, but an earlier rewrite had already cleaned `main` and
what survived was only `refs/original/refs/heads/main`, the `filter-branch`
backup. That ref is deleted, the reflog expired, objects pruned. GitHub never
had them. If a future session is told to add the trailer, **`CLAUDE.md` says
never** — that rule wins, and undoing a mistake here costs a force-push.

---

## 1. What shipped, and what each item turned out to be

| item | the plan | what was true |
|---|---|---|
| **D8** | atomic-write upgrade | the defect was in the half that *already existed* — `compress()` deleted the destination **before** renaming onto it |
| **D5** | deep verify | `verify_archive` already was zpaqfranz's `t`; the missing half was `v -ssd`, re-reading the **originals** |
| **D6** | fuzz the parser | **eleven** unhandled exception shapes, one of which *became* the bomb budget |
| **D7** | CI | green now, and its **first run found three real failures** |
| **E2** | third-party notices | 40 licences read from files; 39 confirmed, 1 explicitly not |
| **E6** | community files | changelog, contributing, templates |
| **B10** | lepton wheel / drop zstd.exe | lepton was already right; `zstd` was mis-reported as "not installed" |
| **F5** | honest encryption copy | wording was already honest — the **delivery** was not |
| **F2** ⚠️ | *(was marked DONE)* | the keyfile was **write-only** |
| **G7** | RAM-limited extract | the lever was never the dictionary — it is `-mmt`, worth **3.6×** |
| **B9** | finish the RAM formula | the formula was **unreachable, not unfinished**; the app showed a figure 3.9× optimistic |
| **D4** | disk-full | injection half done; **found a real defect** |
| **I7** | i18n | ❌ **won't do** — your decision, recorded so nobody rebuilds it |
| **B16** | xtool replaces Precomp | ❌ **measured and rejected**, loses by 8.5% |
| **B12** | LOLZ | measured, not built. Wins on images, loses on text |

---

## 2. Findings worth not rediscovering

### A silent no-op looks exactly like a negative result

The sharpest lesson of the last session, and it nearly shipped as a finding.
xtool's first benchmark had it "losing by 12.8 MB". It had actually found
**nothing**: 90 bytes of delta — *the same 90 bytes* an unrelated smoke test had
produced hours earlier on a completely different file. Two unrelated inputs
cannot both yield a 90-byte delta unless the tool is doing nothing.

Per `xtool.chm`, its `zlib` codec reconstructs by trial and error against
`zlibwapi.dll`, so it only matches streams **zlib itself** would have written;
this corpus was deflated by 7-Zip. **The mismatch failed silently and was
indistinguishable from "this data has nothing to precompress".**

**If you wire in any precompressor: verify it actually did something. Exit 0 is
not evidence.**

### The specialists that win compete with `store`, not with the chain

Five proposed now. **Four lost to `precomp -> 7z`**: B3's `oxipng`, B5's `qpdf`,
K4's wide window, B16's xtool. **One won** — B4's FLAC — and it won because WAV
was being *stored* at 0%, so there was pure upside.

That is why **B13 is the better lead than B12**: `.ogg`/`.opus`/`.wem`/`.fsb`
are stored at 0% today with the reason *"already compressed by its codec"* —
word for word the reason B4 proved wrong for WAV.

### A factor plumbed through one of two sites is not plumbed

F2's keyfile reached `crypto.decrypt_file`'s signature and stopped. Two
decryption sites exist, because `engine.extract` resolves an encrypted archive
itself rather than going through `opened_for_reading` — and the one missed was
the ordinary path. The suite never noticed because `test_keyfile.py` tests the
module directly, where the parameter always worked. **Test a new factor, format
or header field through the public API, not the module that implements it.**

### "Green" is a claim about what the tests look at

Four instances in two sessions: a CI draft that would have gone green having
downloaded nothing; a runner without 7-Zip going green having exercised none of
the product; an F5 test asserting on a tooltip rather than the visible warning;
and a corpus-path guard hidden behind `importorskip` so a missing dev dependency
would silently disable it.

### A test that treats a default as an invariant is a false alarm waiting

`test_the_tool_cache_points_at_the_real_install_root` asserted
`_install_root() == <repo>/tools/bin` unconditionally and went red the moment
the suite ran with `EXCMP_TOOLS_DIR` set — a documented override. **A false
alarm in a guard test is worse than no test**, because the response to a
wrongly-red test is to stop reading it.

### A pixel budget measured on one font stack is not a budget anywhere else

D7's first CI run failed three layout tests on `windows-latest` — 464 px against
a 447 px ceiling, a 50 px row against 36. Not regressions: the runner has a real
`C:\Windows\Fonts`, but a **Windows Server** font set with larger metrics. The
budgets are now gated by `reference_fonts`, which **skips on CI and fails
locally** — because a plain skip would switch off every layout gate after a font
update and still report green.

### Other things already established

- **A full disk is not a per-file problem.** `ENOSPC` from the staging copy used
  to hit K3's skip-this-file guard, so a disk-full job skipped everything then
  said *"they may be open in another program"*. `ENOSPC`/`EDQUOT`/`EFBIG`/
  `EROFS` now abort; everything else keeps K3's skip.
- **The archive is not byte-reproducible.** `created_utc` moves the deflated
  manifest by up to 3 bytes, and the payload's own bytes shift run to run.
  **Compare payload size, never the archive digest.** Silesia/normal payload is
  **48,688,221 B**.
- **An `fsync` costs what the file's recency costs, not its size**: 5.3 ms for a
  48.7 MB archive, 26.3 ms for its 80-byte sidecar.
- **XOR is not a way to combine hashes** — self-cancelling. D5's tree hash is
  sort-then-hash.

---

## 3. Next: I6, or B13

### I6 — "compare presets on this input" *(recommended; nothing external needed)*

Run the installed profiles on a ≤100 MB sample as **real queue jobs** and print
**measured** ratios onto the preset cards. `tools/bench.py` already has the
harness. This is the one item from the last round that is completely untouched,
and it upgrades the honesty brand from estimate to measurement — which matters
more now that B8 made the estimator trustworthy.

### B13 — balrogg, lossless Vorbis/Opus *(the bigger prize; needs two things)*

Verified by measurement on 2026-09-15: `.ogg`, `.opus`, `.wem` (Wwise) and
`.fsb` (FMOD) **all route to `store`** with the reason *"media file: already
compressed by its codec"*. Nothing in `precomp -> 7z` reaches a Vorbis
bitstream, so those bytes are copied verbatim. Game audio is routinely 20–40% of
an install.

Blocked on: **(a)** the download — krinkels.org, resource
`balrogg-lossless-vorbis-opus-recompressor.601`, and the account was last seen
**awaiting email confirmation**; **(b)** a real game-audio corpus, which this
machine does not have.

**The gate, unchanged:** beat `precomp -> 7z` on our own corpora, prove a
byte-identical restore through `verify_restore`, treat the binary as untrusted.

---

## 4. Reference material

`C:\Users\nuhaa\PycharmProjects\ExtremeCompressor-refs\` — 14 studied clones,
**outside** the git repo on purpose. Its README lists every folder with its
pinned commit, licence, and what may be done with it. Added 2026-09-15:
`Mini-Compressor`, `Repack-Tools`, `Hakkuraifu-Repacker` (scene toolsets —
feature ideas only; none documents a verification step).

**krinkels.org is worth more than the GitHub toolsets** — it is active this
month while they are stale. Three resources logged as B13/B14/B15: balrogg,
**DArc 3.04** (a *maintained* FreeArc fork, superseding the 2009 Haskell sources
we cloned), and ADDeX 0.1 (v0.1, one download — logged, not recommended).

**encode.su** is behind Cloudflare bot verification and cannot be fetched; it
reads fine in a normal browser.

---

## 5. Verify before believing anything here

```
.venv\Scripts\python.exe -m pytest tests\test_atomic_publish.py -q   # D8
.venv\Scripts\python.exe -m pytest tests\test_deep_verify.py -q      # D5
.venv\Scripts\python.exe -m pytest tests\test_fuzz_container.py -q   # D6
.venv\Scripts\python.exe -m pytest tests\test_disk_full.py -q        # D4
.venv\Scripts\python.exe -m pytest tests\test_ci_workflow.py -q      # D7
```

And the corpora are safe from the suite — proven, not assumed:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

**If a number here disagrees with what you measure, trust your measurement and
correct the doc.** That has happened more than a dozen times, including four
numbers I wrote myself and later had to fix.

---

## 6. Everything still open

### Small
| item | what |
|---|---|
| **I6** | compare presets on measured numbers — **recommended next** |
| **D5b** | nothing; D5 is done |
| **B10** | closed |

### Medium
| item | what |
|---|---|
| **B13** | balrogg / Vorbis — best prize, needs download + corpus |
| **B12** | LOLZ vs `precomp -> 7z` — binary in hand, comparison not done |
| **B14** | DArc 3.04, the maintained FreeArc fork |
| **D6b** | more fuzz targets if wanted; the parser is covered |
| **I5** | Explorer context menu — **ask first**, writes to HKCU |

### Large, or blocked
| item | status |
|---|---|
| **B6** | xtool + Oodle — **blocked**, no game corpus; B16 closed its deflate half negatively |
| **B15** | ADDeX 0.1 — too early |
| **D4b** | the real-volume half — **needs an elevated session** for a VHDX |
| **Phase C** | C1–C7, the opt-in lossy phase |
| **Phase H** | H1–H6, Inno Setup generation; LOLZ/ISDone belongs here |
| **E3–E5** | PyInstaller, signing, auto-update — only if this is ever shared |
| **I7** | ❌ **won't do** |

---

## 7. Things not to re-litigate

- **The repo is private and the OSI rule is retired.** Any tool may be used; the
  lossless guarantee matters *more* as a result.
- **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **`os.replace` needs no `unlink()` first** — it overwrites atomically.
  Re-adding one restores the D8 defect.
- **The read-back is not paired with an expectation on the plain path**, and
  that is measured, not an omission.
- **Windows cannot flush a directory.** Contents are flushed; rename durability
  is the filesystem's.
- **`publish()`'s identity check never refuses on its own** — `st_ino` is
  synthesised on FAT32/exFAT, so a disagreement re-hashes before refusing.
- **`verify_restore` does not compare timestamps**, on purpose.
- **The zstd window is fitted to the input**, and the *read* ceiling stays
  independent of the write setting — that coupling was K4's bug.
- **Extraction memory is controlled by `-mmt`, not the dictionary.** The
  dictionary is fixed by whoever made the archive.
- **Insane is data-dependent, not stronger.** It loses to Extreme on installers
  and wins by 2.50 points on Silesia.
- **SREP stays out** — it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
