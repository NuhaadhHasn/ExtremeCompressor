# 🚦 START HERE — handoff (written 2026-09-04)

> **Start with K1.** A folder of the user's real data cannot be archived at
> all, and the failure lands *after* the whole job has run. Section 3.
>
> Everything is merged to `main` except **`phase-i3-i8-i10`**, which is pushed
> and waiting for review.

**921 tests: 920 pass + 1 strict-xfail.**

```
.venv\Scripts\python.exe -m pytest -q
```

---

## 0. The working rule for this project

**Confirm, do not hypothesise.** Every claim in this document was reproduced on
this machine before it was written down; where a number appears, it was
measured, not estimated. The session that produced these findings started from
an agent survey and then re-ran every material claim by hand — four "critical"
items survived that and several did not.

This is not a style preference. Three of the four defects below had been
shipped for weeks behind a green test suite, and two of them were *found* by
things that verify rather than assert: a property test, and rendering the GUI
and looking at it.

### Your data is not at risk from the suite — verified, not assumed

Two tests read from the real corpora. Both are read-only, and rather than
trust that, `tools/corpus_guard.py` proves it:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

It records every file's size and mtime under `Programs` and
`My Graphical Projects` (165 files), then diffs after a full run. Any write,
delete or create shows up. **Run it after any change that touches the tests.**

---

## 1. What is on `main`

Everything below shipped and is merged. Since the last handoff: B1, G9, the
QA phase (D1/D2/D3), B7/B9, G3, G4, F1, F2, F3, F4, G5, J5–J7, and two rounds
of audit fixes.

The app now does: verified byte-identical restore · per-file routing with
reasons · duplicate-file dedup · split volumes · PAR2 recovery records ·
AES-256-GCM + Argon2id encryption with keyfiles · Mark-of-the-Web propagation ·
foreign-archive listing and extraction · convert-and-shrink · plain `.7z`/`.zip`
export · self-calibrating time estimates · persisted history · treemap · Ctrl+K.

**Unmerged:** `phase-i3-i8-i10` (I3 + I8 + I10, and the 7-Zip floor raise).

```
git checkout main && git merge --no-ff phase-i3-i8-i10
```

---

## 2. What this session found, and how

**25 bugs fixed across the session, 13 of them already shipped.** The ones
worth remembering because of *how* they were caught:

| Found by | Bug |
|---|---|
| Hypothesis | The restore comparison could **pass a lost file** — 6 test files |
| Rendering the GUI | A failed job displayed **"3.7 GB → 0 B"** |
| Rendering the GUI | The extension label said `.excmp` while writing `.zip` |
| Adversarial audit | Encrypted archives were **unopenable by every reader** |
| Adversarial audit | `compress_standard` archived **only its first input** |
| A 19-minute test | A tampered header could ask Argon2 for **4 TiB of RAM** |

The pattern: a green suite proves nothing about the things tests do not look
at. Two of these were in the tests themselves.

---

## 3. The next job: K1, the manifest cap

**A real folder cannot be archived.** `MAX_MANIFEST_BYTES = 8 << 20`
(`excmp/manifest.py:27`), measured against the live tree:

| folder | files | manifest | outcome |
|---|---:|---:|---|
| `5React, ReactNative` | **57,020** | **~29 MiB** | ⛔ **refused** |
| `7Python` | 12,701 | 5.4 MiB | ok |

`node_modules` is exactly the shape that does this. **1 of 21 tutorial folders
is affected today.**

The worst part is *when* it fails: `_verify_before_publish` → `verify_archive`
→ `_read_manifest`, which is where the cap lives. The whole job runs, then the
archive is refused. A pre-flight check belongs at the front.

Three avoidable things inflate the manifest, all in `engine.compress`:

- `routes[].files` (engine.py:672) **duplicates every relative path** already
  in the ledger
- `store_reasons` (engine.py:671) stores a **whole English sentence per file**
- `write_container` uses `ZIP_STORED` (manifest.py:215), so the JSON costs its
  full uncompressed size on disk

Needs `SCHEMA_VERSION = 2`. Keep `Manifest.from_json`'s `cls(**data)` shape so
old archives still load, and add a test that builds a genuine v1 archive and
restores it — the B11 precedent.

**Then K2, K3, K4** — all specified with their measurements in `ROADMAP.md`
under "2026-09-04 — four confirmed defects". K4 (zstd window) is the free one:
**half the size and 2.1× faster**, but read the warning — raising only the
compress side produces archives older builds cannot read.

---

## 4. Verify before you believe anything here

Every one of these reproduces in under a minute:

```
# K1 - the manifest cap, against the real tree
.venv\Scripts\python.exe -c "from excmp.manifest import MAX_MANIFEST_BYTES; print(MAX_MANIFEST_BYTES)"

# K2 - timestamps: set an mtime, round-trip, look at the date
# K3 - lock a file with CreateFileW(dwShareMode=0), then compress the folder
# K4 - 300 MiB with a duplicate half 150 MiB away, wl=27 vs wl=31
```

The exact scripts used are in the session transcript; the *results* are in
`ROADMAP.md`. If a number here disagrees with what you measure, **trust your
measurement and correct the doc.**

---

## 5. Still open, in the order they are worth doing

1. **K1–K4** — confirmed defects, above
2. **B6** (Oodle/AAA games) — the biggest ratio gap, ~3-4 sessions.
   **Blocked on test material**: there is no game with Oodle data on this
   machine, and research/24 §2 proved there is no open-source Oodle encoder,
   so the `oo2core` DLL is unavoidable and permanent
3. **I6** (compare presets on a real sample), **I7** (translations — the
   loader exists, a `.ts` file does not; **do not invent Dhivehi**, set up the
   pipeline and let the user translate)
4. **I5** (Explorer context menu) — **ask first**, it writes to HKCU
5. **B12** (LOLZ), **C** (video shrink, needs ~90 MB FFmpeg), **D4–D8**,
   **E1–E5** (only if this is ever shared)

### From the tool survey, still unevaluated

`preflate-rs` (Microsoft, Apache-2.0) as a Precomp alternative · `eXdupe 4.0`
for unlimited-distance dedup · **Precomp MP3 support, which is already
installed and switched off** by `_MEDIA` routing · par2cmdline's >2000-file
bug · incremental/versioned archives.

---

## 6. Things not to re-litigate

- **The repo is private and the OSI rule is retired** (2026-09-01). Any tool
  may be used. The lossless guarantee is *more* important as a result, not
  less — several newly-permitted tools are known-unreliable.
- **Never weaken verification to fit a tool in.** The D9 gate caught a broken
  archive on the first codec added after the rules relaxed.
- **zpaqfranz is not tree-capable here**, deliberately — it stores absolute
  paths and `add` has no relative-path switch.
- **SREP stays out.** Permitted now, but zpaqfranz buys the same points and
  SREP failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.** A fifth costs the tab bar its reason
  to exist.
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done. It has caught defects no test could.
