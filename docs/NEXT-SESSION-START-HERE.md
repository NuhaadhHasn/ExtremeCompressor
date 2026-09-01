# 🚦 START HERE — handoff (written 2026-09-01)

> **G2 is done and sitting on branch `phase-g2-foreign-listing`, unmerged,
> awaiting your review.** Foreign archives list, encrypted ones ask for a
> password instead of freezing the app, and single members come out of either
> kind of archive.
>
> **Start here: J5-J7** — per-type memory, long-job confirm, self-calibration.
> Section 3 has the detail.

**552 tests: 551 pass + 1 strict-xfail.** Baseline last session was 469.

```
.venv\Scripts\python.exe -m pytest -q
```

```
git merge --no-ff phase-g2-foreign-listing
```

---

## 1. What is on `main` (plus the unmerged branch)

| area | what it does now |
|---|---|
| **Compress** | drop → analysed → four profiles side by side with size, saving, time **and peak RAM** for your actual files |
| **Activity** | queue, per-job logs, results; a status strip carries queue state onto every tab |
| **Extract** | ours (ledger-verified) **or** zip/7z/rar/tar/iso/cab/msi/wim (honestly unverified); **"What's inside" now works on both** |
| **Settings** | threads, temp folder, `.sha256` sidecar, open-after-extract, notifications, tray, theme — all persisted |
| **CLI** | `analyze` `compress` `extract` `list` `verify` `hash` · `--level` `--dict` `--params=` `--sha256` `--only` `--password` |

New on the branch: `excmp/slt.py` (the `7z l -slt` grammar, subprocess-free),
`engine.list_any()` / `extract_selected()` / `selection_cost()`,
`Banner.ask_secret()`, and a `ListingWorker` so a 7-second MSI listing does not
freeze the window.

## 2. Decisions that are settled — do not re-litigate

1. **research/23 §2.4's ≤300px page budget is unreachable, and §3.3 wins.**
   Fully compacted the page floors at **415px**; the ≤300 assertion stays a
   `strict=True` xfail. **Do not "fix" it by shrinking controls below 32px.**
   Arithmetic: `benchmarks/2026-08-07-ui-wave2b.md`.
2. **Row height encodes uncertainty.** Fast/Normal are 34px; Extreme/Insane are
   51px because theirs is a *range*.
3. **`.sha256` is opt-in and remembered.**
4. **Advanced is per-job; Settings is remembered.**
5. **Verification means a real restore of every byte against the ledger** —
   never a container self-test.
6. **`list_archive()` stays `.excmp`-only; `list_any()` is the foreign twin.**
   Not style. `ExtractTab._suggest_destination()` calls `list_archive()`
   synchronously on every dropped file, so widening it in place puts a
   `7z.exe` launch on the GUI thread for every drop. A test guards this.
7. **A CRC-32 is never written to a `sha256` field.** Foreign entries carry
   `crc` and leave `sha256` empty; `ArchiveListing.ledger_backed` says which
   kind you are holding. Same rule as `ExtractResult.ledger_backed`.
8. **`--password` takes no value.** It prompts. A password in argv is in the
   process table and the shell history.

## 3. The next job: J5-J7

`docs/ROADMAP.md` Phase J. J1-J4 and J8 shipped 2026-08-01; these three finish
it.

- **J5 — remember the last choice per content type.** QSettings map
  `dominant category -> profile`. **The I1 dependency the roadmap warns about
  is gone** — wave 3c shipped QSettings persistence, so `gui/settings_tab.py`
  and its store already exist. Extend them; do not bootstrap a second one.
- **J6 — long-job confirmation** past ~45 min estimated. **Use
  `Banner.show_message` with two verb-labelled actions** — the pattern is now
  worked twice over, most recently by G2's solid-archive warning in
  `MainWindow._start_selected_extract`, which prices the wait in bytes before
  charging it. Copy that shape. **Not a modal.**
- **J7 — self-calibrating rates.** Record real `piped_bytes / elapsed` **per
  resolved chain** after each job, EMA it into `Rates`, keep the shipped
  defaults as the cold-start prior. `Rates` is already an injected argument,
  so no model change is needed. This is the one that turns a benchmark
  laptop's numbers into this machine's.

After that, the roadmap's own order: D1-D3/D7 (QA core + CI), B1-B3/B9-B10.

## 4. Run the QA sweep before calling any UI work done

```
.venv\Scripts\python.exe tools\qa_sweep.py --out .qa
```

**19 surfaces × 2 themes** (G2 added three: the foreign listing, a ticked
selection, and the password prompt). It exists because **every visual defect
this project has shipped got past a fully green suite**. G2 alone produced six
more, all with the tests passing:

| defect | how it read on screen |
|---|---|
| `packed = 0 B` on solid members | 7-Zip printed *nothing* there; "0 B" claims the file costs no space |
| "Reading the archive's contents…" left up | a finished table under a status line still saying it was working |
| "Extract selected" never appeared | the async listing populated after the button's `setVisible` had run |
| the caption restated the status line | the same warning twice, five rows apart |
| password field with no placeholder | an unlabelled box |
| `·` in a new CLI line | rendered `?` in the console code page |

**Tests pin behaviour; rendering pins appearance. UI work needs both.**

## 5. Findings worth not rediscovering

The wave-1-to-3 list still stands (`QT_QPA_FONTDIR` is load-bearing; a number
can be true and still be wrong; `verified == 0` needed a companion flag; a
route-level summary is not a per-file fact; a rounded percentage can lie; QSS
`height` does not constrain a `QProgressBar`; a cell that cannot wrap must
elide; accessible strings need their own assertions; tinted SVGs need `$text`;
"fill the host" and "size to your hint" contradict; grep is the wrong tool for
"no modals left"; word-wrapping QLabels poison QScrollArea sizing; argparse
eats values starting with `-`). G2 adds seven:

1. **`subprocess.communicate()` hides a hang.** It closes stdin, handing the
   child an EOF a real parent never sends. Reproducing the encrypted-archive
   freeze needs stdin *held open*. The first measurement said "no hang" and
   was wrong.
2. **A timeout cannot be enforced from inside the read loop.** A tool blocked
   on a prompt prints nothing, so `for line in stdout` never returns to be
   checked. `run_capture` uses a watchdog `threading.Timer` that kills the
   process; the read then gets EOF.
3. **`.msi` is not one format.** 7-Zip reports `cab` or `compound` depending on
   internal structure, and `compound` is ~20× slower to list (7.14 s vs
   0.27 s). That is why listing is on a worker.
4. **7-Zip's `-i!` patterns are globs with no literal mode.** A member named
   `a*.txt` would over-match. `safepath.safe_relpath` already refuses `*` and
   `?`, so validating requested names *before* they become filters closes it
   by construction rather than by escaping.
5. **`isVisible()` is False for every child of a window that was never shown.**
   Useless for "is the prompt up?" in tests and on a background window — ask
   the state, not the pixels. `Banner.has_secret_field()` returns
   `self._on_secret is not None` for this reason.
6. **A worker must not reach back through `self.job`.** `_EngineWorker`
   deliberately stores `job.id` only, so the worker never shares a mutable
   object with the thread that owns it. The first full-suite run of this phase
   failed on exactly that, and only there — the engine-level tests all call
   the function directly and never exercise the Job handoff. **Test through
   the queue, not only the engine.**
7. **Naming a guarantee in a disclaimer is not claiming it.** Two of this
   phase's tests first asserted "the string SHA-256 never appears", which
   flagged the honest sentence explaining what a foreign archive *lacks*.
   Assert on the shape of a claim — a heading, a 64-hex value — not on the
   word.

## 6. Standing rules

- **No AI attribution in commits** — audit before committing.
- Docs → `main`; code → its own branch, left unmerged for review. One phase
  per session.
- **100 % OSI-clean.** `assets/icons/` vendors Fluent UI System Icons (MIT)
  with the upstream `LICENSE` beside them. Never bundle SREP / lolz / oo2core /
  unrar.dll / Segoe Fluent Icons (EULA).
- Target hardware: 2-core i7-3540M, 16 GB, **1366×768 primary display**.
- Lossless is a hard guarantee; post-restore SHA-256 is the acceptance gate.

## 7. Real test data

Corpus A (721 MB, 6 files, external HDD) has compressed to **700,884,250
bytes** on three separate occasions across four sessions, with 6/6 independent
SHA-256 matches each time. That number is the regression canary for the whole
engine.

The `Programs` folder keeps drifting: **39 top-level entries on 2026-09-01**,
42 on 2026-08-07, 81 in an older note. **Re-count before quoting it.**
Nineteen of the 39 are archives 7-Zip can open, and **four of those have
encrypted headers** — they are the real-world regression corpus for the hang
guard, and they cost nothing to run (~0.4 s each).

Timings on that drive are cache-noisy — identical extracts have measured 50.3 s
and 8.2 s. Never quote throughput from a single run.

## 8. Both warts are closed (2026-09-01)

1. **The status bar no longer advertises `srep`.** It reads `srep (legacy)`,
   and Settings spells out what that means: *only used to open archives made
   before it was dropped; never used to compress*. Discovery deliberately
   **stays** — `SrepStage.available()` goes through `find_tools()`, and there
   is a test that builds a genuine pre-B11 archive and restores it. Hiding a
   tool that can still run would leave someone debugging a legacy archive
   unable to see it was found. `excmp/tools.py:LEGACY_ONLY` carries the label
   and a test asserts no chain in `_CHAINS` can reach anything in it.
2. **7-Zip is now 26.02**, above the 24.09 floor. Verified: the `-slt` parser,
   the `solid` flag, encryption detection and *both* error strings in
   `slt._SIGNATURES` are byte-identical between 24.07 and 26.02, so the
   upgrade cost nothing. `excmp/tools.py` now has `parse_tool_version()` and
   `below_floor()` (E1 groundwork), surfaced in all **three** inventory
   surfaces — status strip, Settings, and the About card.

**The one thing to watch:** `slt._SIGNATURES` is a table of *English* 7-Zip
error strings, and `classify_failure()` returns `""` for anything it does not
recognise — by design, because guessing "corrupt" from an unrecognised string
would tell somebody their archive was broken on the strength of wording that
changed between releases. The consequence is that if a future 7-Zip reworded
"Cannot open encrypted archive" the password prompt would **silently stop
appearing**, and every test would still pass. `test_failures_are_told_apart`
pins the strings; re-run it after any 7-Zip upgrade. (`the system cannot find
the file` in that same table is a Windows CRT message and tracks the OS
locale, not the 7-Zip version — it is already wrong on a non-English Windows.)
