# 2026-08-07 — UI v3 wave 3c: the sidecar, and an app that remembers

Machine: i7-3540M, 16 GB, Windows 10 19045. Wave 3 complete.

---

## 1. G6 — the `.sha256` sidecar

**Decision taken this session: opt-in, remembered.** Not default-on.

The case for default-on was real — it is the QuickSFV / `fitgirl-bins.md5`
convention, and verification is the brand. The case against won: a second file
appearing beside every archive is an output nobody asked for, and *"inputs are
never modified; outputs are written to `.tmp` and atomically renamed"* has been
the engine's standing promise since its first commit. A surprise file is a
small violation of the same principle.

So: one checkbox in Settings, `--sha256` on the CLI, and the choice persists.

Three details that are not incidental:

- **Hashed after the atomic rename**, so it describes the file that shipped
  rather than the `.tmp` twin that existed a moment earlier.
- **Names the archive by file name, not full path.** `sha256sum -c` resolves
  relative to the working directory; an absolute path breaks the moment the
  pair is moved, which is the only situation a transport sidecar exists for.
- **A failed compress writes none.** A sidecar for an archive that does not
  exist is worse than no sidecar.

```
$ excmp compress ... -o MyGame.excmp --sha256
wrote MyGame.excmp.sha256 - check it anywhere with `sha256sum -c MyGame.excmp.sha256`
```

## 2. I1 — Settings, and the first persisted preferences

Before this wave the app persisted **exactly one thing**: window geometry.
Threads, temp folder, theme, notifications — all reset on every launch. The
roadmap has called that "the loudest daily annoyance" for four phases.

A fourth tab, on CommunityToolkit `SettingsCard` geometry: title, a
description saying what the setting *does* rather than restating its label,
and the control on the right. Persisted: threads, temp folder, sidecar,
open-after-extract, notifications, tray, **and theme**.

It is also where the **full tool inventory** lives — which is what makes the
status strip's eliding (W2-1) honest rather than lossy. That wart has been
carried in the handoff since wave 2a; it is closed.

### A duplication this surfaced

Adding Settings gave the app *two* "notify when a job finishes" checkboxes —
the new persisted one, and an older one in Advanced that was the one actually
read. Notifications and tray are app preferences, not per-job overrides, so
they left Advanced entirely. The rule now: **Advanced is per-job (threads,
temp, where this archive goes); Settings is remembered.**

Where both exist, Advanced wins for that job and does not rewrite the
preference.

## 3. The Ark autosubfolder heuristic

Extract used to always propose `archive.with_suffix('')`. Ark's rule is
better, and our manifest can answer it exactly rather than guessing from a
listing:

| archive | proposed destination |
|---|---|
| everything under one top-level folder | **beside the archive** — another folder would produce `bundle/src/…` |
| several things at the top level | **a folder named after the archive** — otherwise they spray |
| foreign (no manifest) | a folder of its own — the safe branch |

A destination the user typed is never overwritten.

## 4. I4 — the first-run notice

On W2-9's `Banner`, shown once and remembered:

> Your originals are never modified — archives are written to a temporary file
> and only renamed into place once a full restore has verified every SHA-256.
> Anything that cannot shrink is stored byte-for-byte, and the app tells you
> why.

A promise, not a tip, which is why it earns one showing rather than a
dismissible-forever nag.

## 5. What the QA sweep caught this time

Settings shipped with **"auto (4 cores)"** in the threads control, sitting
directly beside a description that called this "a two-core laptop".
`os.cpu_count()` reports *logical* processors and the target i7-3540M reports
4 for its 2 physical cores. Both halves were on screen at once. Now reads
"auto (4 available)", and the description no longer hard-codes a core count.

Third wave running where the sweep found something the suite could not.
It is 16 surfaces × 2 themes now.

## 6. Suite

`.venv\Scripts\python.exe -m pytest -q` → **431 passed, 1 xfailed**
(415 + 1 after wave 3b). New: `tests/test_sidecar_and_settings.py` (12),
`tests/test_wave3c_polish.py` (5).

One wave-2a test changed rather than broke: it asserted exactly three tabs.
research/23 §2.3's wireframe always had four — `Compress | Extract | Activity
| Settings` — and four is exactly WinUI's ceiling for top navigation, which is
why the tab bar was chosen over a nav rail in the first place.

## 7. Wave 3, complete

| item | wave |
|---|---|
| Verify button + `excmp verify` + `excmp hash` | 3a |
| G1 foreign archives, I2-lite listing, `excmp list` | 3b |
| G6 sidecar, I1 Settings + persistence, autosubfolder, I4 notice | 3c |

**Not done, deliberately deferred:** level/dictionary knobs + the RAM column +
the free-text Parameters line. That one needs real plumbing — `_stage_factory`
hard-codes stage defaults and `StageRecord.params` is always `{}` — so it is
engine work wearing a UI hat, and it is the natural first item of a wave 4
alongside G2 (foreign listing via `7z l -slt`).
