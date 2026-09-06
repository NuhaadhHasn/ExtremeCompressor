# 🚦 START HERE — handoff (written 2026-09-07)

> **Start with K2.** Restore a folder today and every stored file is dated
> today, and empty directories do not come back at all. Section 3.
>
> **Two branches are stacked and awaiting review**: `phase-i3-i8-i10`, then
> `phase-k1-manifest-v2` on top of it. Merge in that order — section 1.

**947 tests: 945 pass + 1 skip + 1 strict-xfail.**

```
.venv\Scripts\python.exe -m pytest -q
```

The skip is the 57,020-file corpus walk, which costs ~20 s of drive metadata
latency and is therefore opt-in:

```
set EXCMP_SLOW_CORPUS=1
.venv\Scripts\python.exe -m pytest tests\test_manifest_v2.py -q -k 57k -s
```

---

## 0. The working rule for this project

**Confirm, do not hypothesise.** Every claim in this document was reproduced on
this machine before it was written down.

K1 is now the clearest demonstration of why, and it demonstrated it **twice**.

*First:* the roadmap's plan for K1 was specific, plausible, and **would not have
worked**. It named three savings that together still left the manifest 1.8× over
the cap. Only serialising the real thing revealed that.

*Second, and more useful:* the K1 implementation was **finished, green, and
wrong in three places**. A 945-test suite passed over all three. What found them
was auditing the diff against the artifact it actually produces, and then
looking at the disk:

| found by | defect |
|---|---|
| Comparing the estimate to a *mutated* ledger | preflight under-read by **24%** on dedup |
| Trying non-ASCII names against it | preflight under-read by **45%** on Dhivehi |
| Asking where a constant came from | deflate factor calibrated on placeholder hashes |
| **Listing the temp directory after a run** | every job touching a `.git` leaks temp (K5) |

Three of those four are the same mistake: **a check that models something other
than the artifact it is protecting.** Carry that into K2, where the temptation
will be to assert on the ledger rather than on the restored file's `st_mtime`.

### Your data is not at risk from the suite — verified, not assumed

Three tests read from the real corpora. All are read-only, and rather than trust
that, `tools/corpus_guard.py` proves it:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

165 files under `Programs` and `My Graphical Projects`, size and mtime. Run
twice on 2026-09-06/07: **clean both times — nothing added, removed or
modified.** Run it after any change that touches the tests.

---

## 1. What is on `main`, and what is waiting

`main` has everything up to and including J5–J7. The app does: verified
byte-identical restore · per-file routing with reasons · duplicate-file dedup ·
split volumes · PAR2 recovery records · AES-256-GCM + Argon2id encryption with
keyfiles · Mark-of-the-Web propagation · foreign-archive listing and extraction
· convert-and-shrink · plain `.7z`/`.zip` export · self-calibrating time
estimates · persisted history · treemap · Ctrl+K.

**Unmerged, stacked, in this order:**

```
git checkout main
git merge --no-ff phase-i3-i8-i10        # I3 + I8 + I10, and the 7-Zip floor
git merge --no-ff phase-k1-manifest-v2   # K1
```

K1 is stacked on `phase-i3-i8-i10` deliberately: `tools/corpus_guard.py` and
`tests/restored.py` exist only on that branch and `CLAUDE.md` mandates running
the guard, and both branches change `gui/queue_manager.py`.

---

## 2. What K1 shipped, proven end to end

Full numbers: [benchmarks/2026-09-04-k1](benchmarks/2026-09-04-k1-manifest-v2.md).

**The folder that could not be archived, archived.** 55,477 files, 338.5 MiB —
the `node_modules` subtree of the corpus that broke:

```
354,988,110 -> 101,576,020 B    71.39% saved      compress 137.5 min
excmp verify : OK, 55,477 restored, 55,477 hashes verified    24.5 min
excmp extract: 55,477 files, 55,477 hashes OK                 18.3 min
independent SHA-256 tree comparison, both trees walked:
    0 missing, 0 extra, 0 differing  ->  BYTE-IDENTICAL
```

**The manifest, v1 vs v2 on that same job** — the v1 document reconstructed from
the v2 one, so the real routing decides who carries a store reason:

| | bytes | | |
|---|---:|---|---|
| v1 | 22,611,183 | 21.56 MiB | ⛔ 2.7× over the old 8 MiB cap |
| v2 | 12,782,745 | 12.19 MiB | ok against 64 MiB |
| v2 deflated in the container | 2,720,064 | 2.59 MiB | |

**22,611,183 is byte-for-byte the number in the pre-K1 build's own error
message.** That is what confirms this is the folder that failed *and* that the
reconstruction is exact rather than approximate.

**What changed:** schema v2 (interned store reasons — 12 possible sentences,
1,232 bytes, of which this archive used 7; `routes[].count` instead of a second
copy of every relative path; compact separators; and the document now written as
real UTF-8), `manifest.json` DEFLATED, `MAX_MANIFEST_BYTES` 8 → 64 MiB against a
*measured* parse cost, the cap enforced on the write side too, and
`engine._check_manifest_size` refusing at the front before the first `mkdtemp`.
v1 archives still load and restore, pinned by a test that rewrites a real
archive's manifest back into genuine v1 shape.

**Also fixed here, all found by audit before the commit** — details in the
ROADMAP's K1 entry:

- the preflight under-read by **24%** on dedup-heavy stored data and by up to
  **45%** on non-ASCII names (either would have re-created K1: accepted at the
  front, refused at the end);
- `_MANIFEST_DEFLATE_FACTOR` was calibrated on placeholder hashes and therefore
  *under*-booked disk — real hashes measure 0.213, not 0.045;
- J7 self-calibration had **never recorded anything** from the GUI, because it
  stat-ed archive-relative paths against the process working directory.

---

## 3. The next job: K2, timestamps and empty directories

**Reproduced 2026-09-04.** Two files given an mtime of 2023-07-31, compressed,
restored:

```
text.txt  (pipeline route)  ->  2023-07-31   ✅ tar carries mtime
rand.bin  (store route)     ->  2026-09-04   ❌ today
emptydir/                   ->  did not come back at all
```

The two routes disagree, and the reason is confirmed by reading the code:
**there is no `mtime`, `utime` or `st_mtime` anywhere in `excmp/`.** Nothing in
the engine ever preserves or restores a timestamp. The pipeline route gets it
for free only because `tarfile` records one; the store route goes through
`write_container`'s `zf.write` (which keeps a zip timestamp no reader applies)
and `extract_stored`'s `target.open("wb")`, which sets nothing.

Empty directories are lost one layer up: `analyzer.analyze_tree` is
`[analyze_file(p) for p in iter_files(root)]`, so a directory with no files in
it never enters the ledger, and there is nothing in the manifest for
`extract_stored` to recreate. Fixing mtimes will not fix this; it needs its own
field.

The bytes *are* identical, so the lossless claim holds literally — but restore a
photo archive and every file is dated today, which breaks sort-by-date and looks
like data loss to anyone who did not read the fine print.

**Where to work:**

- `excmp/manifest.py` — the ledger entry needs an mtime, `extract_stored` needs
  to apply it (**and `_read_lepton_member`'s branch too**, which writes through
  `target.write_bytes` and is easy to miss), and empty directories need
  somewhere to live. Schema v2 just shipped, so **add to v2 rather than minting
  v3**: a defaulted field costs nothing and `Manifest.from_json`'s `cls(**data)`
  fills it in for older archives. Follow how `reasons` was added.
- `excmp/analyzer.py` — `iter_files` is where empty directories are dropped.
- `excmp/verify.py` — decide **deliberately** whether `verify_restore` compares
  mtimes. Today it compares bytes; if it starts comparing timestamps, every
  pre-K2 archive fails verification, so it almost certainly must not.

**Two things K1 learned that apply directly to K2:**

1. **Assert on the restored file, not on the ledger.** Three of the four defects
   in section 0 were checks that modelled something other than the artifact.
   `os.stat` the file that came back.
2. **A new ledger key costs manifest bytes, and there is now a preflight that
   has to know.** `_MANIFEST_ENTRY_BYTES = 120` in `manifest.py` is counted from
   the format, not fitted; an `mtime` field has to be added to it or
   `manifest_size_estimate` starts under-reading again.
   `test_the_size_estimate_survives_what_write_container_adds_afterwards` will
   catch it, but only if you keep its worst case honest.

**Then K5, K3, K4** — all specified with measurements in `ROADMAP.md`.
**K5 is the cheapest**: a shared `rmtree_force` across 11 call sites, found by
this session's end-to-end when a read-only git object stranded a whole scratch
directory because `rmtree(ignore_errors=True)` silently gives up. K4 (zstd
window) is the biggest free win — **half the size and 2.1× faster** — but read
the warning: raising only the compress side produces archives older builds
cannot read.

---

## 4. Verify before you believe anything here

```
# K1's cap
.venv\Scripts\python.exe -c "from excmp.manifest import MAX_MANIFEST_BYTES; print(MAX_MANIFEST_BYTES)"

# K2 - set an mtime, round-trip, look at the date; and grep for yourself:
findstr /S /I "st_mtime utime" excmp\*.py

# K3 - lock a file with CreateFileW(dwShareMode=0), then compress the folder
# K4 - 300 MiB with a duplicate half 150 MiB away, wl=27 vs wl=31
# K5 - chmod a file read-only, shutil.rmtree(d, ignore_errors=True), d.exists()
```

If a number here disagrees with what you measure, **trust your measurement and
correct the doc.** That happened four times this session.

---

## 5. Still open, in the order they are worth doing

1. **K2, K5, K3, K4** — confirmed defects, all with reproductions in `ROADMAP.md`
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
- **`MAX_MANIFEST_BYTES` is 64 MiB and that number is measured** — 2.2× parse
  cost against the real tree. Do not trim it back on principle; if it ever needs
  to move, measure again.
- **`manifest.json` is the one DEFLATED member of the container**, and it is
  written with `ensure_ascii=False`. Both are load-bearing: the payload and the
  `stored/` tree stay STORED because a real codec has already had its turn at
  them, and the UTF-8 is what makes `manifest_size_estimate` truthful about
  non-ASCII names.
- **The preflight is deliberately pessimistic** — 2.08× on an all-stored tree,
  but only 1.09× on the real end-to-end job. Refusing a job that would have
  worked is bad; accepting one that cannot finish is the defect K1 exists to
  fix. Do not "tighten" it without re-reading benchmarks §4b.
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done. It has caught defects no test could.
