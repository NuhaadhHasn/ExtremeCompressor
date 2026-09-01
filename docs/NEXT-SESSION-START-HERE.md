# 🚦 START HERE — handoff (written 2026-08-07)

> **UI v3 is complete and merged to `main`.** research/23 is fully
> implemented; nothing is waiting for review and the tree is clean.
>
> **Start here: G2 — foreign-archive listing.** Then J5-J7. Section 3 has the
> detail.

**469 tests: 468 pass + 1 strict-xfail.** Baseline five sessions ago was 324.

```
.venv\Scripts\python.exe -m pytest -q
```

---

## 1. What is on `main`

| area | what it does now |
|---|---|
| **Compress** | drop → analysed → four profiles side by side with size, saving, time **and peak RAM** for your actual files |
| **Activity** | queue, per-job logs, results; a status strip carries queue state onto every tab |
| **Extract** | ours (ledger-verified) **or** zip/7z/rar/tar/iso/cab/msi/wim (honestly unverified); "What's inside" lists the ledger without extracting |
| **Settings** | threads, temp folder, `.sha256` sidecar, open-after-extract, notifications, tray, theme — all persisted |
| **CLI** | `analyze` `compress` `extract` `list` `verify` `hash` · `--level` `--dict` `--params=` `--sha256` |

Per-wave measurements are in `docs/benchmarks/2026-08-0*`. The Compress page
went **869 → 415px**, and the empty page fits a 150 %-scaled 1366×768 display
for the first time in the project's history.

## 2. Decisions that are settled — do not re-litigate

1. **research/23 §2.4's ≤300px page budget is unreachable, and §3.3 wins.**
   Four profile rows at the Windows 32px touch floor are 128px on their own;
   §2.4 allowed 172px for the entire chooser. Fully compacted, the page floors
   at **415px**. The ≤300 assertion stays in `test_gui_fit.py` as a
   `strict=True` xfail. **Do not "fix" it by shrinking controls below 32px.**
   Arithmetic: `benchmarks/2026-08-07-ui-wave2b.md`.
2. **Row height encodes uncertainty.** Fast/Normal are 34px (one number);
   Extreme/Insane are 51px because theirs is a *range* — Precomp's gain is
   unknowable until it runs. Inlining it needs ~210px in a 178px column.
3. **`.sha256` is opt-in and remembered.** Default-on is the QuickSFV
   convention, but a second file beside every archive is an output nobody
   asked for, and *"inputs are never modified; outputs are written to .tmp and
   atomically renamed"* has been the promise since the first commit.
4. **Advanced is per-job; Settings is remembered.** Where both exist, Advanced
   wins for that job and does not rewrite the preference.
5. **Verification means a real restore of every byte against the ledger** —
   never a container self-test. `7z t` checks only the last stage's framing,
   which is exactly how `srep64.exe` once passed an archive it had corrupted.
   `_verify_before_publish` calls the public `verify_archive`, and a test
   fails if the two ever drift.

## 3. The next job: G2 — foreign-archive listing

"What's inside" works on our archives and **deliberately refuses** on everyone
else's, because an empty list would read as "this archive is empty". G2 is
what makes it work:

- The pinned **`7z l -slt`** grammar, plus the **dummy `-p` hang guard**
  (doc 17 §4) — without it 7-Zip blocks forever waiting for a password on an
  encrypted archive, and the GUI simply looks hung.
- **Password-on-demand** on W2-9's `Banner`: File Roller's timing, and
  distinguish *encrypted* from *corrupt* via stderr. Never log the password
  (PeaZip's redaction rule) — `excmp/ram.py`'s `parse_extra_args` already
  refuses `-p` for that reason, and its error message is a worked example.
- Where it plugs in: `engine.list_archive()` raises `ContainerError` for
  anything that is not an `.excmp` — that is the seam.
  `ExtractTab.contents_toggle` is already disabled with an explanatory
  tooltip, so the UI half is enabling it and widening `ArchiveListing.kind`.

After that: **J5-J7** (per-type memory, long-job confirm, self-calibration —
J7 turns a cold-start prior into estimates fitted to this machine, and it now
has real settings to calibrate against). Then the roadmap's own order:
D1-D3/D7 (QA core + CI), B1-B3/B9-B10.

## 4. Run the QA sweep before calling any UI work done

```
.venv\Scripts\python.exe tools\qa_sweep.py --out .qa
```

**16 surfaces × 2 themes**, offscreen with real fonts — including the ones no
test and no README screenshot ever renders: the banner, the Extract tab with
both archive kinds, the expanded pending list, a failed-job results panel,
Settings, the first-run notice, and everything-disclosed-at-once.

It exists because **every visual defect these waves produced got past a fully
green suite**, and every one was caught by looking at a PNG:

| defect | how it read on screen |
|---|---|
| progress bars filled their cell | a 55px slab of flat colour, not a bar |
| tinted glyphs used `$muted` | three near-invisible ghosts beside one green flame |
| chooser cells hard-clipped | "zpaqfranz missing - runs as E:" — looks like a bug |
| `fmt_percent` rounded 99.6 → 100 | **"100% or better"** — an archive of zero bytes |
| foreign extract reused our wording | **"0 SHA-256 hashes verified — byte-identical to the originals"** |
| the Extract card's standing blurb | promised a ledger directly above "this one has none" |
| Settings' threads control | "auto (4 cores)" beside a line calling this a two-core laptop |
| the new Peak RAM column | **6.0 GB quoted for a 371 KB job** |

**Tests pin behaviour; rendering pins appearance. UI work needs both.**

## 5. Findings worth not rediscovering

1. **`QT_QPA_FONTDIR` in `tests/conftest.py` is load-bearing.** Qt's offscreen
   plugin ships no font database; without it every GUI test measures tofu
   boxes of the wrong width and every height gate is fiction. Wave 1's gates
   were all measured against tofu. **Never remove that line.**
2. **A number can be true and still be wrong.** The RAM column's 6.0 GB was
   the correct output of the correct formula — for a dictionary LZMA2 would
   never have allocated on that input. Any figure derived from a *setting*
   must be recomputed against the *data*.
3. **`verified == 0` needed a companion flag.** "Nothing to check against" and
   "checked, found zero good" are different facts. Wherever a count of zero
   could mean two things, carry the reason beside it.
4. **A route-level summary is not a per-file fact.** `planner.store_reason`
   said so in its own docstring for months; the listing was simply the first
   surface to render the joined string per file and make it obviously wrong.
5. **A rounded percentage can become a lie.** `fmt_percent(0.996)` is "100%".
   Anywhere a percentage meets a superlative, check the rounding.
6. **QSS `height` does not constrain a laid-out `QProgressBar`** — only
   `setFixedHeight`/`setFixedSize` does.
7. **A cell that cannot wrap must elide, not clip.** `_ElidingLabel` in
   `compare_table.py`; the full text stays in the tooltip and the spoken name.
8. **Accessible strings need their own assertions.** The missing-tool caveat
   silently stopped being spoken the moment estimates arrived.
9. **Tinted SVGs need `$text`, not `$muted`** — a muted glyph on `$surface` is
   very nearly invisible in dark mode.
10. **"Fill the host" and "size to your hint" are contradictory**, which is why
    the Activity page is deliberately not a `QScrollArea`.
11. **Grep is the wrong tool for "no modals left"** — the comments explaining
    why the modals went name `QMessageBox`. The test tokenises instead.
12. **Word-wrapping QLabels poison QScrollArea sizing**, and the chooser's
    `window.presets` / `window.compare_table` alias must not be "cleaned up".
13. **argparse eats values starting with `-`.** `--params` must be spelled
    `--params="-mqs"`; the help text says so.

## 6. Standing rules

- **No AI attribution in commits** — audit before committing.
- Docs → `main`; code → its own branch, left unmerged for review unless told
  otherwise. One phase per session.
- **100 % OSI-clean.** `assets/icons/` vendors Fluent UI System Icons (MIT)
  with the upstream `LICENSE` beside them, and it must stay there. Never
  bundle SREP / lolz / oo2core / unrar.dll / Segoe Fluent Icons (EULA).
- Target hardware: 2-core i7-3540M, 16 GB, **1366×768 primary display**.
- Lossless is a hard guarantee; post-restore SHA-256 is the acceptance gate.

## 7. Real test data

Corpus A (721 MB, 6 files, external HDD) has compressed to
**700,884,250 bytes** on three separate occasions across four sessions —
2026-08-02, wave 2a and wave 3a — with 6/6 independent SHA-256 matches each
time. That number is the regression canary for the whole engine.

The `Programs` folder itself has drifted from older notes: it is now **6.4 GB
across 42 files**, and the analyzer puts **41.9 %** of those bytes in the
store-as-is bucket under the default profile. Re-measure before quoting it.

Timings on that drive are cache-noisy — identical extracts have measured
50.3 s and 8.2 s. Never quote throughput from a single run.

## 8. One wart still standing

**The status bar advertises `srep`.** B11 removed it from every chain; the
stage module survives only so pre-B11 archives still extract, and `find_tools`
still probes for it. Nothing bundles it, so the OSI rule is intact — but the
app names a tool it will never run. Settings' tool inventory is where the
honest version of that line now lives.
