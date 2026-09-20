# 🗺️ ExtremeCompressor — Remaining Work, Step by Step

> Status date: **2026-09-20**. **1,271 tests, 10 skipped, 1 strict-xfail.**
> **Branch `phase-i6-measured-presets` is awaiting review**; everything else is
> merged to `main`.
>
> ⚠️ **Eight of those ten skips are `test_estimate_backtest.py` switching
> itself off**, because one pinned file — `lghub_installer.exe`, 58,146,712 B —
> has been deleted from the live Programs corpus. The estimator's backtest
> against real data is therefore **not running**, and the suite says nothing
> about it beyond a skip. The skip now names the file. Restore it, or re-pin
> `FILES` and re-derive the expected ratios; do not just drop the entry, the
> assertions were fitted to the whole six-file set. The other two skips are the
> opt-in 57k-file corpus walk (`EXCMP_SLOW_CORPUS=1`) and a test that only runs
> when no E1-pinned tool is installed.
>
> **D7 is green.** The workflow has run on `windows-latest` and passed, as have
> the last three pushes. Its *first* run failed three layout tests, and that was
> the point: a workflow that has never run is not evidence, and this one earned
> its keep immediately by proving the pixel budgets were measuring the dev
> machine's fonts rather than the layout.
>
> **Done:** engine core · Phase A (GUI) · Phase D0 (security hotfix) ·
> Phase J part 1 (estimates before compressing, scored on two real corpora) ·
> B11 + D9 (SREP-free chains; nothing publishes without a fully verified
> restore) · **all of UI v3** — [research/23](research/23-ui-v3-redesign.md)
> §7's four waves and the whole of its §5 engine-exposure inventory:
> screen fit and the merged chooser (w1), the Activity tab and the height
> compaction (w2), and verify/list/hash, foreign archives, the `.sha256`
> sidecar, Settings with persistence, and the level/dictionary knobs with a
> peak-RAM column (w3).
>
> The one open exception: research/23 §2.4's ≤300px page budget is
> **unreachable** and stays a `strict=True` xfail — §2.4 and §3.3 contradict
> each other, and §3.3's 32px touch floor wins. See
> [benchmarks/2026-08-07-ui-wave2b](benchmarks/2026-08-07-ui-wave2b.md).
>
> **G2 is done** (2026-09-01, branch `phase-g2-foreign-listing`, awaiting
> review): foreign archives list, encrypted ones ask for a password instead of
> hanging, and single members can be pulled out of either kind.
> **Next up: J5-J7** (per-type memory, long-job confirm, self-calibration).
>
> This is the complete, ordered plan for everything left. Companion deep-dives:
> [06 best-compression-per-filetype](research/06-best-compression-per-filetype.md) ·
> [07 UI v1 blueprint](research/07-ui-ux-design.md) ·
> [08 archiver product features](research/08-archiver-product-features.md) ·
> [09 FitGirl installer + honest comparison](research/09-fitgirl-installer-and-comparison.md) ·
> [10 security & integrity](research/10-security-and-integrity.md) ·
> [11 UI v2 plan](research/11-ui-v2-plan.md) ·
> [12 lightweight & performance](research/12-lightweight-and-performance.md)
>
> **Source-code study series (2026-07-31, read [21 synthesis](research/21-source-study-synthesis.md) first):**
> [13 xtool](research/13-source-study-xtool.md) ·
> [14 NanaZip](research/14-source-study-nanazip.md) ·
> [15 Precomp](research/15-source-study-precomp.md) ·
> [16 Inno Setup](research/16-source-study-innosetup.md) ·
> [17 PeaZip](research/17-source-study-peazip.md) ·
> [18 FreeArc + par2](research/18-source-study-freearc-par2.md) ·
> [19 7-Zip](research/19-source-study-7zip.md) ·
> [20 lrzip + zpaqfranz](research/20-source-study-lrzip-zpaqfranz.md) ·
> **[22 feature-parity master](research/22-feature-parity-master.md)** (the
> all-in-one map: every studied feature → our own implementation → phase)

---

## ⚖️ 2026-09-01 — the repo went private, and the licence constraint is gone

The repo is now **PRIVATE**. The 100%-OSI rule existed to keep free SignPath
code signing available for a public release; there is no public release, so
there is no distribution, so the obligations that trigger on distribution do
not apply. **SREP, LOLZ, Oodle/`oo2core`, `unarc.dll` and xtool Patreon builds
are all permitted now.**

### What this unblocks

| Item | Was blocked by | Now |
|---|---|---|
| **B6** (xtool + Oodle) | needed E1 for a pinned hash | **unblocked** — and the `oo2core` DLL may simply be vendored, which dissolves the restore-time bootstrap problem doc 24 §2 showed is otherwise permanent |
| **LOLZ as final codec** | not OSI, never even listed | **new item B12** below |
| **SREP** | "not OSI" (which doc 24 §5 showed was shaky anyway) | permitted — **but still not recommended**, see below |
| **`unarc.dll` / ISDone** (H3) | GPL, in-process = linking | permitted; still only matters when Phase H starts |

### What it does NOT change — and what gets *more* important

**The lossless guarantee, and the SHA-256 gate that enforces it.** Several
newly-permitted tools are known-unreliable. SREP failed its own decompression
checksum on **1 of 3 runs over byte-identical input**. The licence rule was
never what protected us from that — `_verify_before_publish` was. With flakier
tools now in scope, that gate is the whole safety story. **Never weaken
verification to accommodate a new tool.**

### What becomes optional

**Phase E4 (SignPath code signing) no longer applies**, and E3/E5 (installer,
auto-update) matter only if this is ever shared. Deprioritise the whole of
Phase E except **E1's tool downloader**, which is still useful for *fetching*
tools onto the machine.

### Standing recommendation on SREP

Permitted ≠ advisable. It buys ~3.5 points; **zpaqfranz (B1) does the same job**
— long-range CDC dedup at unlimited distance — is actively maintained, MIT, and
has never failed a restore here. **Do B1 first.** Only reach for SREP if B1
measurably underperforms on a real corpus, and if it goes in, it goes in behind
the verification gate like everything else.

### Revised order, best-app-first

1. **B1** (zpaqfranz) — dedup back, no risk, completes Insane
2. **B6** (xtool + Oodle) — the AAA gap; now vendorable, so the DLL problem is solvable
3. **B12** (LOLZ) — final-codec upgrade
4. **B8** — re-benchmark and replace every `(est.)` with a measurement
5. J5-J7, then D1-D3/D7 (QA + CI)

If the repo is ever made public again, **this entire section reverts** and the
OSI rule comes back before anything ships.

- [x] B16. ❌ **MEASURED AND REJECTED 2026-09-15** — xtool loses to Precomp by
      **8.5%** on our data. Full numbers:
      [benchmarks/2026-09-15-b16](benchmarks/2026-09-15-b16-xtool-vs-precomp.md).
      Silesia zipped with 7-Zip deflate (64,726,889 B), same `7z -mx9 -mmt2`
      final compressor in every row, every route restored and SHA-256 compared:
      `precomp -cn -> 7z` **51,745,050**; xtool's best of four configurations
      (`-mreflate -d1`) **56,149,054**. xtool is 1.95x faster, which is not the
      axis that decides here.
      **The item was written on the author's published benchmark and it did not
      reproduce.** He measured `-mzlib` beating `precomp -brute` by 2,673,415 B
      and 4.7x on GTA V's `x64w.rpf`. Both results can stand: his streams came
      from a game engine's zlib, mine from 7-Zip's encoder, and *which encoder
      wrote the stream* is exactly what separates xtool's `zlib` codec from its
      `reflate` codec. **Do not re-adopt this on his numbers.**
      **A near-miss worth keeping.** The first run had xtool losing by 12.8 MB,
      because `-mzlib` found *nothing* here - 90 bytes of delta, the same 90
      bytes an unrelated smoke test had produced, which is what exposed it as a
      no-op rather than a measurement. Per `xtool.chm`, the zlib codec
      reconstructs by trial and error against `zlibwapi.dll`, so it only matches
      streams zlib itself would have written. **A codec mismatch fails silently
      and looks identical to "nothing to precompress".**
      **Still open, narrowly:** the Oodle/Kraken/LZ4 codecs are untested because
      no game corpus exists on this machine - the gap that also blocks B6.
      Revisit only with real game data, and measure the Oodle path, not deflate,
      which is the case Precomp is already good at.
      Original item text follows.
- [ ] ~~B16-original. **xtool as a drop-in Precomp replacement — the half of B6 that is
      NOT blocked** (new 2026-09-15, from the author's own thread,
      encode.su/threads/4000, read 2026-09-15).
      **B6 was framed as "xtool + Oodle" and shelved because this machine has
      no Oodle game folder and because the DLL-bootstrap flaw would make
      archives restore only where they were made. Both are true of the *Oodle*
      codec. Neither is true of the rest of xtool.**
      Razor12911's published benchmark, GTA V `x64w.rpf`, 937,340,928 B, final
      compression by 7-Zip 21.07 (lzma2 ultra, 64 MB dict, 12 threads, solid)
      in every row:

      | route | time | final bytes |
      |---|---:|---:|
      | 7-Zip alone | - | 818,957,826 |
      | `precomp048 -brute -t+ -cn -d0` | 214.6 s | 589,588,701 |
      | `xtool precomp -c64mb -t1 -mzlib` | 169.4 s | **586,915,286** |
      | `xtool precomp -c64mb -t4 -mzlib` | **45.6 s** | 586,915,318 |

      **2,673,415 bytes better than Precomp and 4.7x faster**, on the `-mzlib`
      path - no Oodle, no game DLL, nothing that cannot run here. Precomp is
      single-threaded and that is our known pipeline bottleneck; xtool is
      multi-threaded across every codec.
      Also natively: `reflate`, `preflate`, `zstd`, `lz4f`, `flac`, `packjpg`,
      `brunsli` - and stdin/stdout, so it can be driven exactly the way we
      drive everything else.
      **Its unrestorable-stream story is the thing to check first.** The author
      states that streams which cannot be restored losslessly are patched with
      **xdelta**. That is a real answer rather than a silent failure, but it
      means the tool has a category of input it cannot invert, so our D9
      post-restore SHA-256 gate matters more here, not less. Confirm the patch
      path round-trips before anything else.
      **The author's own caveats, quoted rather than paraphrased:** stream
      detection is "almost sliding-window like", so capturing large streams
      needs a large chunk size and that costs memory (`-lm` exists for it); and
      `lz4`, `lz4hc`, `lzo1x`, `hydra`, `leviathan`, `jojpeg` are flagged
      experimental "and/or does not work as intended". **The project is no
      longer in development** - the author considers it finished.
      Versions in the wild: **0.6.9** attached to that thread, **0.7.9** on the
      archived GitHub (already cloned to `ExtremeCompressor-refs/xtool`), and
      **0.9.8** on krinkels.org dated 2026-07-30.
      **The gate is unchanged and it is the same one Precomp passed:** measure
      `xtool -mzlib -> 7z` against `precomp -> 7z` on our own corpora, prove a
      byte-identical restore, and treat the binary as untrusted.
- [ ] B13. **balrogg — lossless Vorbis/Opus recompression** (new 2026-09-15,
      found on krinkels.org; v1.1 dated 2026-09-06, author `Mickey1s`,
      "demonically compacting (up to 15%) lossless Vorbis/Opus recompressor").
      **The strongest untested lead in the project, because it targets a bucket
      we currently score 0% on.** Measured 2026-09-15: `.ogg`, `.opus`, `.wem`
      (Wwise) and `.fsb` (FMOD) all route to `store` with the reason *"media
      file: already compressed by its codec"* - word for word the reason B4
      proved wrong for WAV. Nothing in `precomp -> 7z` reaches a Vorbis
      bitstream, so every one of those bytes is copied verbatim today.
      **Why it is structurally different from B12.** LOLZ competes with a route
      that already works; this competes with *storing the file*. B4 is the
      precedent and remains the only specialist to beat the existing chain - and
      it won for exactly this reason: WAV had no codec, so there was pure
      upside. Vorbis *is* compressed, but its entropy layer can be recompressed
      losslessly, which is the same trick Precomp plays on deflate.
      **Scale.** Game audio is routinely 20-40% of an install, and `.wem`/`.fsb`
      are the two containers it arrives in.
      **Gate unchanged:** measure against the existing route first, prove a
      byte-identical restore through `verify_restore`, treat the binary as
      untrusted - pinned hash, no faith in its exit code. Needs a real game
      audio corpus, which this machine does not have (the gap that also blocks
      B6), and the download needs a krinkels.org account.

      ### 🔴 2026-09-20 — both blockers re-checked by searching, both still real

      Full record: [benchmarks/2026-09-20-b13](benchmarks/2026-09-20-b13-vorbis-baseline.md).
      **Nothing here is quoted from the 2026-09-15 note; it was all re-run.**

      - **No balrogg binary anywhere on this machine.** Bounded searches of
        Downloads, Desktop, Documents, PycharmProjects, both AppData trees,
        `C:\` to depth 2, both Program Files trees, `excmp-bench` and all 14
        `-refs` clones. (An unbounded sweep timed out at 480 s, so the claim is
        "not in the plausible places", not "proven absent".) The download is
        still behind a krinkels.org login.
      - **No game-audio corpus, and this time the search was done properly.**
        Zero `.opus`, `.wem`, `.fsb`, `.bnk` anywhere — including the whole
        external `Downloads-1` tree and the F: volume, the omission that made
        B4's original "blocked" verdict wrong. No game is installed at all: no
        Steam, Epic, GOG, Riot or Unity directory exists. The only Vorbis is
        **39 UI sound effects (31 unique, 326,692 B)** inside the odoo18/odoo19
        source trees, 5–30 KB each.

      **The premise is confirmed and there is a defect under it.** Running the
      planner (not reading it): `.ogg`, `.opus`, `.wem`, `.fsb` **and a file
      called `named.dat` that merely starts with `OggS`** all store, under every
      profile — the magic-byte rule at `analyzer.py:52` fires before the
      extension table, so a patch that edited only `_EXT` would be bypassed.
      Precomp on a tar of them prints **`Recompressed streams: 0/0`** and makes
      the file 19 bytes bigger.

      On that corpus, through `engine.compress` itself:

      | what ran | bytes out | saved |
      |---|---:|---:|
      | **Normal / Extreme (what ships)** | 333,317 | **−2.0%** |
      | `7z -mx9 -ms=off` | 256,784 | 21.4% |
      | `7z -mx9` (solid) | 189,826 | 41.9% |

      The archive comes out **6.6 KB larger than the input** while the reason
      line says the data is already compressed by its codec — and the analyzer
      had already measured `sample_ratio` **0.687–0.945** on those same files
      and been overruled. Same shape as B4's WAV case.
      **Nothing was changed on the strength of it.** 326 KB of low-bitrate UI
      blips is not a corpus, most of the solid win is cross-file redundancy
      between two versions of one product, and high-bitrate Vorbis music is
      expected near 0%. The finding is recorded; the fix waits for data.
      **The structural hook, when the data arrives, is `_UNCOMPRESSED_AUDIO`**
      (`planner.py:173`, B4's precedent) — not `_DEFLATE_MEDIA`, which would
      throw the file into a `precomp` that has been measured to find nothing
      in it.
- [ ] B14. **DArc (Distended Arc) 3.04** - a *maintained* FreeArc fork
      (krinkels.org, 2026-09-07, `Mickey1s`). Supersedes the 2009 Haskell
      sources in `ExtremeCompressor-refs/freearc-orig` as the thing to measure
      if FreeArc is revisited. Same gate: it has to beat `precomp -> 7z`, not
      `7z` alone.
- [ ] B15. **ADDeX 0.1** - "Advanced Data Deduplication Engine" (krinkels.org,
      2026-09-07, `Mickey1s`). The SREP-replacement space, where zpaqfranz's CDC
      already sits. **Version 0.1 with one recorded download** - logged so it is
      not rediscovered, not recommended. Revisit if it matures.
- [ ] B12. **An optional final codec — retargeted 2026-09-10 from LOLZ to
      FreeArc, because LOLZ is not what this item assumed it was.**

      ### ✅ 2026-09-20 — measured against the real route. It wins, twice, and the second win is the interesting one

      Full record:
      [benchmarks/2026-09-20-b12](benchmarks/2026-09-20-b12-lolz-vs-precomp-7z.md).
      **Gate (1) is now satisfied.** Every LOLZ row below was decompressed and
      SHA-256 compared; the deflate corpus went all the way home through
      `precomp -r` to the original bytes.

      **Corpus A — deflate** (B16's Silesia zip, `precomp -cn -intense` →
      236,958,376 B):

      | final codec | archive | vs best 7-Zip | compress |
      |---|---:|---:|---:|
      | `7z -mx9 -mmt1` | **51,820,126** | baseline | 162.7 s |
      | **`lolz -d64m`** | **50,233,466** | **−3.06%** | 776.7 s |
      | `lolz -d64m -mt2` | 50,797,463 | −1.97% | 772.3 s |

      **Corpus B — real installers**, 13 files / 55.7 MB chosen out of the live
      `Programs` folder by I6's own `pick_sample`, `precomp` → 62,482,862 B:

      | final codec | archive | vs 7-Zip | compress |
      |---|---:|---:|---:|
      | `7z -mx9 -mmt1` / `-mmt2` | **46,048,116** (identical) | baseline | 28.0 s |
      | **`lolz -d64m`** | **45,933,664** | **−0.249%** | 186.4 s |
      | `lolz -d64m -mt2` | 46,052,632 | **+0.01% — loses** | 157.9 s |

      **The verdict is the gap between those two tables.** 3.06% is a
      deflate-stream result; on the data this app is actually for the win is
      **0.249% — 114,452 bytes — for 6.7× the compression time**. One corpus
      would have shipped "the first specialist to beat `precomp → 7z`"; two
      corpora say "wins, by an amount inside the margin of a dictionary
      choice". It is **not** rejected the way B16's xtool was — smaller-at-any-
      speed is the axis this project has said it optimises — so it qualifies as
      exactly what this item already specified: an **Insane-tier alternative to
      the 7-Zip stage, never a default, degrading when absent**. Whether 0.25%
      buys 6.7× is the owner's call and the numbers now exist to make it.

      **Three things any integration must carry:**
      (a) **`-mt2` costs LOLZ ratio** (1.12% / 0.26%) and turns its win into a
      loss on corpus B — its default `-mt1` is its best setting, so do not hand
      it the project's calibrated two threads;
      (b) `cls-lolz_x64.exe` **segfaults on corrupt input and still leaves a
      0-byte output**, and silently writes a 0-byte output for a missing input.
      A "did the file appear?" check — which is what `stages/precomp.py:57`
      does — passes both. The SHA-256 gate is the only thing that catches it;
      (c) `-mmt` costs 7-Zip essentially nothing (byte-identical on corpus B),
      so the round-1 thread asymmetry explained nothing.

      **Still not established, and gate (2) is only half-closed:** 237 MB has
      now been through it, but there is still **no DXT or game data**, which is
      its headline claim — and **LOLZ has never been measured against
      `zpaqfranz`**, which is the codec it would actually be displacing if it
      lands in Insane. Run that before writing the stage.

      **One correction to a committed number.** B16 ran `precomp -cn`; the app
      runs **`-cn -intense`** (`stages/precomp.py:42`). On the same corpus that
      costs **82,086 bytes** — 51,827,136 rather than B16's 51,745,050. Anything
      comparing against "our route" should use the larger figure or re-run it.

      ### ⚠️ CORRECTION, same day: LOLZ is a real codec and it was measured

      **An earlier version of this entry, written hours before, said LOLZ was
      an installer component and deferred it to Phase H. That was wrong.** The
      reasoning was: four repack toolsets cloned and searched, no `lolz.exe`
      in any of them, and `LOLZ` appearing only in a credits line — `ISDONE,
      LOLZ, UELR, MSC (ProFrager)` at `Mini-Compressor/README.md:122`. All of
      that is still true, and **absence of evidence in four repos was not
      evidence of absence.** The owner produced the binary.

      `lolz v22c4b [Dec 30 2018]`. Adaptive rANS, with dedicated models for
      DXT textures and raw graphics; `-d16..2047` MB dictionary, `-mt1..16`,
      `-mtt0..1`. Compress `lolz_x64.exe {options} <in> <out>` (confirmed from
      its own shipped `arc.ini`), decompress `cls-lolz_x64.exe d <in> <out>`.
      **Round-trips byte-identically** on a 3,000,000 B sample. SHA-256 of the
      distribution recorded in
      [benchmarks/2026-09-11](benchmarks/2026-09-11-ram-and-lolz.md).

      **Measured, same dictionary, against `7z -mx9 -md=64m`:**

      | data | 7-Zip | LOLZ | delta |
      |---|---:|---:|---:|
      | `x-ray` medical image | 4,479,879 | **3,945,563** | **+11.93%** |
      | `sao` float catalogue | 4,413,934 | **4,286,259** | **+2.89%** |
      | `mozilla` binary exe | 4,993,294 | **4,882,426** | **+2.22%** |
      | `osdb` database | 2,851,804 | **2,823,379** | **+1.00%** |
      | `dickens` English text | **871,193** | 896,746 | **−2.93%** |

      So the "~5-10%" is real **on the data it was claimed for**, and LOLZ is
      a *per-category specialist* — like B4's FLAC (43% on WAV, useless
      elsewhere), and exactly what the analyzer's per-file routing exists to
      exploit. It belongs behind a category test, never as a blanket default.

      **What has NOT been established, and gates any code:**
      (1) it has not been measured against **`precomp → 7z`**, which is what
      this app actually ships — 7-Zip alone is not the baseline, and three of
      four proposed specialists have already lost to that chain;
      (2) nothing larger than 12 MB has been through it, and no game/DXT data
      at all — its headline claim is untested for want of a corpus, the same
      gap that blocks B6;
      (3) provenance is a forum download of a 2018 closed-source binary, so it
      gets the untrusted-stage treatment: pinned hash, no trust in its exit
      code, post-restore SHA-256 decides whether the archive publishes.

      **B12a — FreeArc, the candidate that is actually testable.** `Arc.exe`
      (3,647,488 B, sha256 `a2bbdde6…e905`) plus `facompress.dll` /
      `facompress_mt.dll` are in `ExtremeCompressor-refs/Repack-Tools/APEX/`.
      Rules, unchanged from the original item: pinned binary, no trust in its
      exit code, and the post-restore SHA-256 comparison decides whether the
      archive publishes. Route it as an Insane-tier alternative to the 7-Zip
      stage, never a default, degrading when absent.

      **Two things to settle before any code.** (1) **Measure first** — B8's
      rule, and three of four proposed specialists have already lost to the
      `precomp → 7z` route that is already here. Run it on Silesia, whose
      payload size for `normal` is a recorded **48,688,221 B**. (2) **Do not
      pin the binary from `Repack-Tools`** — that bundle has no licence file
      at all while redistributing GPL binaries. FreeArc is GPL and its source
      is Haskell (`ExtremeCompressor-refs/freearc-orig`), so we would drive
      `Arc.exe` as a subprocess like every other tool, fetched from upstream
      with its own licence, never from the bundle.

---

## 🔴 2026-09-04 — four confirmed defects, every one reproduced on this machine

Found by an adversarial tool-landscape survey, then **reproduced by hand
before being believed**. None of these is a hypothesis; each line below is a
measurement taken on this laptop against the real corpora. They are listed
before every remaining feature because three of them affect data the user
already has.

### K1. A real folder cannot be archived at all ✅ **DONE 2026-09-04**

Branch `phase-k1-manifest-v2`, every number in
[benchmarks/2026-09-04-k1](benchmarks/2026-09-04-k1-manifest-v2.md).
`MAX_MANIFEST_BYTES` was `8 << 20` (`excmp/manifest.py:27`); it is now
`64 << 20`, the schema is v2, and the check happens before any work starts.

**Three things the implementation corrected against this plan, all measured:**

**(1) The manifest was far bigger than "~29 MiB".** The authoritative figure is
from a real end-to-end archive of the `node_modules` subtree that broke —
55,477 files — with its v1 document reconstructed from the v2 manifest that job
produced, so the *real* routing decides who carries a store reason:

| the same real job | bytes | | vs the old 8 MiB cap |
|---|---:|---|---|
| **v1 manifest** | 22,611,183 | **21.56 MiB** | ⛔ 2.7× over |
| **v2 manifest** | 12,782,745 | **12.19 MiB** | ok |
| **v2, deflated in the container** | 2,720,064 | 2.59 MiB | — |

**22,611,183 is byte-for-byte the number in the pre-K1 build's own error
message**, which is how we know the reconstruction is faithful and that this is
the folder that failed. Modelling the whole 57,020-file tree with *every* file
stored puts v1 at 40.87 MiB and v2 at 14.77 MiB — a worst case, not what a real
job writes.

**(2) Schema v2 alone does not fix K1 — the cap had to rise.** The reason is
structural: those relative paths average **152 bytes** each, so **8.67 MB of the
document is pure path text** and clears an 8 MiB cap before a single other field
is written. No field-trimming reaches 8 MiB.

So the cap is now measured rather than guessed. Its whole purpose is to stop an
unbounded `json.loads` on attacker bytes being a free memory bomb, and that
costs **1.2–1.7 s and 32.1 MiB resident for 14.8 MiB of JSON** — 2.2× the bytes,
590 B per file. `64 << 20` is therefore ~139 MiB and ~5 s worst case, covers
~250,000 files at these path lengths, and is still a hard bound. The old 8 MiB
was over-tight by an order of magnitude.

**(3) It was never one folder.** `7Python` (12,701 files) sat at **7.11 MiB
against an 8 MiB cap** — one folder-growth from breaking — and the whole
tutorial corpus as a single selection (74,648 files, ~46 MiB) was refused too.

**Shipped:** `SCHEMA_VERSION = 2`; `routes[].files` replaced by a `count`
(the ledger already carried a route per file); store reasons interned into a
`reasons` table indexed from the ledger entry (`planner.store_reason` can emit
at most **12** distinct sentences — one media sentence plus one per two-decimal
entropy value from the 7.9 threshold to 8.00 — so the table is **1,232 bytes**
at any file count, and the real end-to-end archive used 7); compact JSON
separators; `manifest.json` written **DEFLATED**, the one compressed member of
the container. v1 archives still load and restore — `store_reasons` stays on
the dataclass because `from_json` splats `cls(**data)`, and `Manifest.reason_for`
reads v2, then v1, then the route summary. A missing schema check was added
too: an archive from a newer build is now refused instead of quietly misread.
The cap is enforced on the **write** side as well, which is the asymmetry that
caused this: `compress` built an archive its own reader refused and only found
out from inside the publish gate, after every byte had been written.
`engine._check_manifest_size` refuses at the front, before the first `mkdtemp`.

**Proven end to end, on the folder that could not be archived.** 55,477 files,
354,988,110 B, profile `normal`:

```
354,988,110 -> 101,576,020 B   71.39% saved     compress 137.5 min
excmp verify : OK, 55,477 restored, 55,477 hashes verified   24.5 min
excmp extract: 55,477 files, 55,477 hashes OK                18.3 min
independent SHA-256 tree comparison: 0 missing, 0 extra, 0 differing
                                     -> BYTE-IDENTICAL
```

**Two further defects were found while auditing K1 before committing it**, both
fixed here with a failing test first, both variants of the same mistake — *the
preflight was modelling a manifest that is not the one that gets written*:

1. **It under-read by 24% on duplicate-heavy stored data.** `write_container`
   stamps `same_as` (a whole relative path) and `codec` onto the ledger *after*
   the estimate is taken. Under-reading re-creates K1 exactly: accepted at the
   front, refused at the end. Now budgeted at the worst case.
2. **It under-read by up to 45% on non-ASCII names.** `json.dumps` defaults to
   `ensure_ascii=True`, so a Dhivehi path costs 6 bytes per character while the
   estimate charged its 2–3 UTF-8 bytes. Fixed by writing the manifest as real
   UTF-8, which is also *smaller* for those trees. This product has an explicit
   Dhivehi/Japanese/Cyrillic/emoji edge-case matrix (D2), so it was in scope.

And one constant was wrong for a related reason: `_MANIFEST_DEFLATE_FACTOR` had
been calibrated on a manifest full of placeholder hashes (`"0" * 64`), which
deflate to nothing. Real sha256s measure **0.213**, not 0.045 — so 0.10 was
*under*-booking disk in a preflight whose entire job is to over-book it. Now
0.30. The reason table's documented bound was wrong by 4× as well (12 sentences
and 1,232 bytes, not "~52 and ~5.3 KB" — that is the figure for a 7.5 entropy
threshold, and the planner uses 7.9); it is now enumerated and pinned by a test.

**A defect found while doing it, and fixed here:** `gui/queue_manager.py`'s
J7 self-calibration derived its piped byte count by stat-ing `routes[].files`.
Those are archive-*relative* paths, so they resolved against the process
working directory, `piped` was always 0, and **J7 had never recorded anything
from the GUI**. Reproduced: the pre-K1 expression returned `0` where the ledger
said `30,000`. The engine now reports `CompressResult.piped_bytes` from the
ledger, exactly, with no filesystem access.

### K2. Stored files come back dated today ✅ **DONE 2026-09-07**

Branch `phase-k2-k5-defects`. Both halves fixed, proven on real files: the two
MySQL installers restored to **2023-11-14 00:29:20** and **2025-08-10 22:29:56**
— their real download dates, exact to the nanosecond.

**One thing the implementation did differently from the plan, and it matters.**
The plan said to teach the store route to set mtimes. Instead they are applied
in **one pass at the end of `engine.extract`**, from the ledger, for *both*
routes. Two reasons, the second found while building it:

1. The routes disagreed precisely because each half looked reasonable alone.
   One pass over the ledger makes them agree by construction, not by coincidence.
2. It has to run **after** F4's Mark-of-the-Web propagation. Writing a
   `Zone.Identifier` alternate data stream **updates the host file's last-write
   time on NTFS**, so a timestamp applied inside `extract_stored` is silently
   overwritten by the zone marker a few lines later. Pinned by
   `test_the_zone_marker_does_not_clobber_the_restored_date`, which marks the
   archive first so the propagation path actually runs.

`mtime_ns` rides on the `stat()` the analyzer already performs, so there is no
second walk — on a 55,000-file tree over the external drive that would have been
minutes. Empty directories travel in a new defaulted `dirs` field (still v2, no
v3 needed) holding only *wholly* empty ones: a directory with files in it is
already implied by their paths, and a chain is rebuilt from its deepest member
with `mkdir(parents=True)`. `verify_restore` deliberately does **not** compare
timestamps — every pre-K2 archive lacks them, and "your archive is corrupt" is a
far worse outcome than "your file is dated today".

<details><summary>the original entry</summary>

### K2 (original)

Reproduced: two files given an mtime of 2023-07-31, compressed, restored.

```
text.txt  (pipeline route)  ->  2023-07-31   ✅ tar carries mtime
rand.bin  (store route)     ->  2026-09-04   ❌ today
```

The two routes disagree. `write_container` uses `zf.write`, which keeps a
zip timestamp the reader never applies. **Empty directories are lost
entirely** (`emptydir` did not come back). The bytes *are* identical, so the
lossless claim holds literally — but restore a photo archive and every file is
dated today, which breaks sort-by-date and looks like data loss to anyone who
did not read the fine print.

</details>

### K3. One locked file kills the whole job ✅ **DONE 2026-09-07**

Branch `phase-k2-k5-defects`. Six files, one held with `CreateFileW`
`dwShareMode=0`: the five readable ones are now archived, restore and verify,
and the sixth is reported by name.

**The plan was right about the behaviour and wrong about the location.** It
reads as though the fix belongs where the file is copied. It does not —
`analyzer.analyze_file` **opens every file** to sniff its category and sample its
entropy, and that happens during collection, before the plan exists, before the
ledger, before any staging copy. So the skip starts in `analyze_tree_safe()` and
is carried through to `CompressResult.skipped`.

Two later windows are guarded as well, because a file readable at analysis time
can be locked before it is hashed or copied — a real race, not a theoretical
one, since analysing a large tree takes minutes. A file dropped in either window
must leave **the ledger and both route lists**, or D9 refuses to publish an
archive whose ledger promises a file the payload does not contain, turning a
graceful skip into a total failure one stage later.

`describe_unreadable()` exists because the stdlib's text for a share-mode denial
is "Permission denied", which is actively misleading on Windows: the user's
permissions are usually fine and the real cause is another program holding the
file open. Closing Excel fixes it; changing an ACL does not.

<details><summary>the original entry</summary>

### K3 (original)

Reproduced with `CreateFileW(dwShareMode=0)`, the way Outlook and Excel hold a
file open. Six files, one locked:

```
>>> PermissionError: [Errno 13] Permission denied
>>> the five readable files were NOT archived
```

Every other archiver skips it, carries on, and reports it at the end. This
fails the whole job and writes nothing.

</details>

### K4. zstd's window ✅ **DONE 2026-09-07 — and it is not a free win**

Branch `phase-k2-k5-defects`. The roadmap's synthetic measurement **reproduced
to within 4 bytes** (314,580,006 against the predicted 314,580,010; 157,699,989
against 157,699,992). Three of its other claims did not.

| the plan said | measured |
|---|---|
| half the size | ✅ **49.9% smaller** on the synthetic case |
| 2.1x faster | ❌ **1.54x** |
| peak working set *fell* (1,707 -> 1,644 MiB) | ❌ **rose**, 1,002 -> 1,813 MiB |
| raising only compress breaks old readers | ✅ confirmed exactly |

**And the real-data number is 4.40%, not 49.9%.** Two builds of the same
installer (mysql-installer-community 8.0.35.0 + 8.0.43.0, 642.9 MiB, sharing
content ~288 MiB apart) forced through the stage: 668,628,541 -> 639,241,730 B,
**4.40% smaller and no speedup at all**.

**Worse for the "free win" framing: in the actual pipeline those two MSIs are
high-entropy, so the analyzer routes them to `store` and the zstd stage never
sees them.** K4 changes nothing for that job. The win applies only to bytes that
go through the codec — so read 49.9% as "what a window is worth when the
duplicate is exact", 4.40% as "two versions of a real installer", and 0% as
"already-compressed input", which is most of the Programs corpus.

**The window is therefore fitted to the input, not pinned at the maximum.** A
window larger than the data cannot find matches the data does not contain:

| window_log | output | peak |
|---|---:|---:|
| 29 (512 MiB) | 157,699,989 | **1,045 MiB** |
| 30 (1 GiB) | 157,699,989 | 1,289 MiB |
| 31 (2 GiB) | 157,699,989 | 1,814 MiB |

Byte-identical at all three, so `_window_log_for()` rounds the input up to the
next power of two and clamps it to [27, 31] — the full ratio win for **769 MiB
less memory**, and small jobs stay exactly where they were before K4.

**The actual defect, which the plan only hinted at:** `extract` computed
`max_window_size = 1 << self.long_log`, so a build could only ever read archives
as wide as it writes. Confirmed directly — a 27-cap reader given a 31-window
streamed frame fails with *"Frame requires too much memory for decoding"*. The
read ceiling is now a module constant independent of the write setting, and
raising it is genuinely free: measured **14 MiB** peak for a 27-byte frame under
a 2 GiB ceiling, because `max_window_size` is a refusal threshold and not an
allocation. `excmp/ram.py` still models LZMA2 dictionaries only, so none of the
zstd figures reach the GUI's peak-RAM column — a known gap, not fixed here.

<details><summary>the original entry</summary>

### K4 (original)

Measured here, three runs, bit-identical, round-trip verified both ways —
300 MiB whose duplicate half sits 150 MiB away:

| `window_log` | output | time |
|---|---:|---:|
| 27 (today) | 314,580,010 | 114.6 s |
| **31** | **157,699,992** | **53.5 s** |

**Half the size and 2.1× faster**, because there is half as much left to
entropy-code. Peak working set *fell* (1,707 → 1,644 MiB). The Programs corpus
averages ~143 MB per installer, so any runtime shared between two of them is
guaranteed to sit beyond the current 128 MiB window and is invisible today.

⚠️ **Not a one-line change.** `ZstdStage.extract` hardcodes
`max_window_size = 1 << self.long_log`, so raising only the compress default
produces archives that an older build cannot read. Raise the **decompress**
cap first and unconditionally (it is a ceiling; existing 27-window archives
still read), then raise the compress default separately. Then both directions
interoperate.

### K5. Every job that touches a git repo leaks temp forever ✅ **DONE 2026-09-07** (found 2026-09-06)

Not from a test — from *looking at the disk* after the K1 end-to-end run. Two
abandoned scratch directories were sitting in temp, each holding exactly the
same 11 files:

```
excmp-verify-i05n75qg/restore/.../rn_first_app/.git/objects/18/1f3cee...
    attrs = ReadOnly, Archive
```

**Git creates loose objects read-only, and `shutil.rmtree(ignore_errors=True)`
cannot delete a read-only file on Windows — it swallows the error and leaves
it.** Reproduced directly, independent of this codebase:

```python
os.chmod(f, stat.S_IREAD)
shutil.rmtree(d, ignore_errors=True)
d.exists()          # -> True, with objects/18/deadbeef still in it
```

So any compress or extract of a tree containing a `.git` directory — or any
read-only file at all — leaves debris behind on every run, and `ignore_errors`
guarantees nobody is told. **11 call sites**, all with the same flag:
`engine.py` ×7 (589, 706, 757, 834, 1141, 1175, 1211, 1310), `convert.py:117`,
`stages/zpaqfranz.py` ×2.

D3 already asserts "temp is clean" and D2 already round-trips read-only
attributes; neither crosses the two, which is why 945 tests are green over a
defect that fires on ordinary input. **Fix:** one shared `rmtree_force` that
clears the read-only bit and retries (`onexc=` on 3.12, `onerror=` below), used
at all 11 sites — plus the D3 test the existing ones imply, with a read-only
file in the fixture.

</details>

- [x] K1. ✅ Manifest schema v2, a 64 MiB cap measured against its own parse
      cost, a deflated manifest, and a pre-flight that refuses at the front
- [x] K2. ✅ mtimes from the ledger, applied after MOTW; empty dirs in `dirs`
- [x] K3. ✅ Skipped at analysis, guarded at hash and copy, reported by name
- [x] K4. ✅ Read ceiling decoupled and raised; compress window **fitted** to input
- [x] K5. ✅ `rmtree_force` at all 11 call sites, premise pinned by its own test

---

## Phase D0 — Security hotfix ✅ DONE (2026-07-31, D0.1-D0.5)

Research on 2026-07-31 audited our own code and found an **exploitable
path-traversal bug**. An archiver that can write outside its output folder has no
business gaining features. Full analysis: [research/10](research/10-security-and-integrity.md).

**Shipped:** `excmp/safepath.py` (reject-never-mangle validator, the union of the
7-Zip/NanaZip/PeaZip rule sets plus bidi overrides), wired into `extract_stored()`,
`read_container()`, `verify_restore()` **and** `write_container()` — so we also
cannot create an archive we would refuse to read. Extraction is bounded by the
manifest's own ledger (exact per-entry size on the real stream, 8 MiB
`manifest.json` cap, free-disk preflight, per-stage backstop). `SECURITY.md` added.
**223 tests pass** (was 91): `tests/test_safepath.py`,
`tests/test_malicious_archive.py`, `tests/test_tar_safety.py`.

**Real-data acceptance run** (not just fixtures) —
[benchmarks/2026-08-01](benchmarks/2026-08-01-real-programs-folder.md): 721 MB of
real installers and archives, both profiles, **6/6 byte-identical** under an
independent SHA-256 check. Confirms the two things unit tests cannot: legitimate
awkward filenames (spaces, parens, `=`) are *not* rejected, and the exact-size
stream cap handles 250 MB single entries. Also yields throughput calibration
(~11.6 MB/s normal, ~4.3 MB/s extreme compress on the 2-core target).

Two things the implementation corrected against the plan below, both verified live:

1. **The absolute-path escape needs no `..` at all.** `Path("out") / "C:/evil"`
   returns `C:\evil` — Python's `/` discards the left operand when the right side is
   absolute. The traversal case got the attention, but this was the quieter half.
2. **tarfile's `data` filter *strips* a leading `/`** rather than raising, and only
   raises `AbsolutePathError` if the name is still absolute afterwards (on Windows,
   a drive letter). So the D0.4 test pins *containment* for `/x` and a raise for
   `C:/x`; expecting a raise for both would have encoded a misreading.

Reject-not-mangle turned out to be forced by our own contract, not merely
preferable: ledger keys are the authoritative filenames, so a rewritten name could
never satisfy `verify_restore()` — mangling would convert a clear "hostile archive"
into a puzzling hash mismatch.

- [x] D0.1. **Fix zip-slip in `extract_stored()`** (`excmp/manifest.py` ~107-122):
      it builds `out_dir / rel` from the raw zip entry name and writes with no
      sanitization, so a crafted `.excmp` with `stored/..\..\Startup\evil.bat`
      (or a drive path, or an NTFS ADS name `x.txt:payload`) escapes the
      destination. The manual `zf.open()` + write loop bypasses
      `ZipFile.extract()`'s sanitizer. Write ONE shared sanitizer, also applied to
      `read_container()`'s `manifest.payload_name` and `verify_restore()`'s ledger
      keys: reject absolute paths, drive letters, `..`, `:`, reserved device names
      (CON/NUL/COM1), trailing dots/spaces — then belt-and-braces
      `target.resolve().is_relative_to(out_dir.resolve())` before any write
- [x] D0.2. **Malicious-archive test suite**: hand-craft hostile `.excmp` files
      and assert refusal. The **full test matrix is now source-pinned** by the
      union of three archivers' sanitizers ([14 §6](research/14-source-study-nanazip.md),
      [17 §5](research/17-source-study-peazip.md), [19 §7](research/19-source-study-7zip.md)):
      `..` / `..\`, absolute, drive letter (`C:\`, `C:rel`), UNC (`\\srv\share`),
      `\\?\C:\`, ADS `x:stream` and `x:Zone.Identifier:$DATA`, reserved device
      names **including `NUL.txt` / `COM1 .log`**, trailing dot/space, control
      chars, empty parts (`a//b`), symlink→abs, symlink→`../..`, symlink chains,
      hardlink outside root, 32 KB+ Zone buffer — **plus RLO `U+202E`, which
      7-Zip itself does NOT sanitize in normal path components**, so D0 can
      honestly claim to exceed 7-Zip. Reject (don't mangle) on link escapes,
      mirroring 7-Zip's `IsSafePath`
- [x] D0.3. **Ledger-bounded extraction** (decompression-bomb defense): our
      manifest already declares every file's exact size and count — bound
      extraction to `sum(ledger sizes) + slack` and `len(ledger)` files, enforced
      on the real streams (headers can be forged); cap `manifest.json` at ~8 MiB
      before `json.loads`; free-disk preflight; per-stage bounds (Precomp
      legitimately inflates 2-5×, so bound each stage, not just the end)
- [x] D0.4. **Pin `filter="data"` with a regression test**: `tarstage.py` already
      passes it (PEP 706 — good), so add a hostile-tar test that fails if anyone
      ever removes the argument
- [x] D0.5. `SECURITY.md` + short threat model (pulled forward from E6): malicious
      archive, tampered tools, tampered archive, lost password. An archiver parses
      untrusted input — researchers need a disclosure channel before v1
- [ ] D0.6. **DEFERRED to its own session** (doc 21 §4 suggests it become a
      standalone D-item; it is Windows ctypes work on subprocess spawning, not
      part of the archive-parsing fix). **(new, from [14 §3](research/14-source-study-nanazip.md))** Process
      mitigations, S-effort: apply `PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY`
      (prohibit dynamic code + block non-system DLLs) and
      `CHILD_PROCESS_POLICY` + a kill-on-close Job object to every tool
      subprocess (7z.exe/precomp/xtool need neither children nor JIT); apply
      only the **safe subset** to our own Python process (image-load policy,
      strict handles, `SetDefaultDllDirectories`) — NOT ProhibitDynamicCode,
      which breaks ctypes/PySide6. NanaZip proves the split (`FM.cpp` vs
      `MainAr.cpp`)

---

## Phase A — Desktop GUI (PySide6) ✅ DONE (2026-07-30)

The single-window flow (full blueprint in research/07):
**drop files → smart suggestion → preset cards → visible queue → results screen**.
Run it with `python -m gui`. Screenshots in `docs/images/`, regenerated by
`tools/shots.py`.

- [x] A1. `pip install PySide6`; app skeleton (`gui/` package, `python -m gui`), dark QSS
      token theme (hand-rolled — PySide6-Fluent-Widgets is GPLv3, conflicts with our MIT)
- [x] A2. Drop zone + file picker; dragEnter highlight; multi-file/folder drop adds
      everything (HandBrake's most-complained bug — we fix it day one)
- [x] A3. Analysis summary card: run engine analyzer in a worker thread, show per-type
      breakdown + smart suggestion
- [x] A4. Preset cards (Fast / Normal / Extreme / Insane) + "Advanced" expander
      (threads, temp dir, output path); Media-Shrink toggle greyed until Phase C
- [x] A5. `QueueManager(QObject)`: one job at a time, jobs run engine calls in
      `QThreadPool`; signals `jobProgress(id, stage, pct, eta)`, `jobDone(id, result)`;
      pause = finish-current-stage-then-hold; cancel wired to `StageContext.cancel`
- [x] A6. Queue table always visible in main window (name, profile, size→size, %,
      ETA, state) with per-job log expander
- [x] A7. Results screen: headline "You saved X MB (Y%)", per-type before/after bars,
      one-line "why didn't X shrink" explainers straight from `store_reason()`
- [x] A8. Windows integration: taskbar progress (ITaskbarList3 via `comtypes`),
      completion toast (`Windows-Toasts`) with "Open folder", system tray option —
      all optional, no-op if unavailable
- [x] A9. Extract tab: pick `.excmp` → destination → verified restore with progress
- [x] A10. Day-one hygiene: every string in `self.tr()`, `setAccessibleName` on
      icon-only buttons, full keyboard tab order, no color-only meaning
- [x] A11. GUI smoke tests (pytest-qt): queue lifecycle, cancel, pause, progress
      signal flow, drop handling — 52 new tests, 90 total
- [x] A12. Screenshot set for README: dark-theme hero of the RESULTS screen, plus a
      7.7 s / 1.6 MB GIF of drop→suggest→compress→result. Scripted in `tools/shots.py`
      so both regenerate every release

**Three additive engine changes landed with it** (all backwards-compatible):
`StageContext.pause` checked at stage boundaries, `StageContext.log_cb` for
per-job tool output, and a `.tmp` cleanup so a cancelled job leaves nothing
beside the user's output. `planner._store_reason` became public `store_reason`.

**Left open:** an NVDA screen-reader pass, and verification at 125%/150%
display scaling — both need a human at the machine.

## Phase B — Stronger + specialist compression

> **Cross-cutting wrapper rules from the source study** (apply to every stage
> that shells a tool — [21 §1.2](research/21-source-study-synthesis.md)):
> (1) pass **`-bsp1`** to 7z.exe or it prints **zero** progress when piped, and
> split its progress on `\r` for `(\d+)%`; (2) **xtool** (`WriteConsole`) and
> **Precomp** emit no parseable progress when piped — poll output-file size
> instead; (3) **never trust a tool's exit code as proof of a good restore** —
> Precomp `exit(0)`s even on fatal restore failure, and xtool/Precomp don't
> round-trip-verify every path. **Our own post-restore SHA-256 comparison is
> the acceptance gate for every stage** (fold into the stage base class).

- [x] B1. ✅ **DONE 2026-09-02** (branch `phase-b1-zpaqfranz`, measured in
      [benchmarks/2026-09-02-b1-zpaqfranz.md](benchmarks/2026-09-02-b1-zpaqfranz.md)).
      Insane is real: `precomp → zpaqfranz`, 5/5 byte-identical on two corpora
      under an independent SHA-256 check, and the profile no longer prints
      "zpaqfranz backend not integrated yet" while quietly running the Extreme
      chain. `-m4 -longpath`, plain `a` (vanilla-zpaq-7.15-readable), never
      `t -paranoid -to` (captcha hazard).
      **Three things the implementation corrected against this plan:**
      (1) **It did not buy the 3.5 points.** Insane measured **40.77%** against
      Extreme's **41.75%** on corpus B — *worse* by 0.97 points, at 2.3× the
      compress time and 4.8× the extract time. After Precomp the stream is five
      *distinct* installers, so CDC has nothing to find and LZMA2 simply wins
      the CM contest. (2) **The 3.5 points came back anyway, without it.** Same
      corpus, unchanged Extreme chain: 37.91% in August, **41.75%** now. Leading
      hypothesis is the 7-Zip 24.07 → 26.02 upgrade; **unconfirmed**, because
      24.07 is no longer installed to A/B against. (3) **zpaqfranz cannot be
      tree-capable here.** It stores the *absolute* path it is handed
      (`C:` → `C_`) and `add` has no relative-path switch, so a tar must
      precede it and it only ever gets one file; `extract` relocates that file
      back to its real name. Found by the D9 gate refusing to publish, not by
      any test — Precomp exits 0 while producing nothing when the path passes
      `MAX_PATH`. Original item:
      **zpaqfranz stage** (actively maintained, FOSS, MIT): `a -m4 -longpath`
      default for Insane (`-m5` behind an "overnight" warning — note both use
      64 MiB blocks, `-m5` is ~2-3× the CPU for CM depth, so **`-m4` is the
      realistic Insane ceiling on 2 cores**, `-m5` a small-precious-data niche);
      add `-test` for a one-shot post-add decompress-check. Keep archives
      **vanilla-zpaq-7.15-readable** (plain `a` only; no `backup` multipart /
      ZETA / W-chunk). This stage is ALSO our long-range-dedup answer: its CDC
      dedup matches identical fragments at unlimited distance (<500 MB RAM for
      200 GB of data) — which is why **lrzip is rejected** (GPL + hard-POSIX,
      no Windows path) and `zstd --long=31` / 7z big-dict stay the ≤2 GB
      default. [20](research/20-source-study-lrzip-zpaqfranz.md); completes
      Insane; add to bench
- [x] B2. ✅ **DONE 2026-09-02** — JPEG specialist via the
      `lepton-jpeg-python` 0.5.8 wheel (as B10 corrected: in-process, no exe).
      Measured on **37 real JPEGs** from this machine
      ([benchmarks/2026-09-02-b2](benchmarks/2026-09-02-b2-lepton-jpeg.md)):
      **33.42% saved on the 23 files lepton accepted** — better than the ~22%
      predicted — and **37/37 byte-identical** end-to-end.
      **The finding that shaped it: lepton refused 14 of 37 files** — 13
      CMYK/4-channel (print work, an ordinary genre) and one wider than
      16384 px. And the refused files were the *big* ones, 135 MB of 151 MB,
      so the folder-level saving was **3.47%** despite 23 files packing.
      Read it as: **~33% on RGB photo folders, ~0% on CMYK print work, and no
      error either way.** Before B2 this folder compressed by approximately
      nothing, since JPEGs are high-entropy and were all stored verbatim.
      Design: `excmp/jpeg.py`'s `pack()` compresses **and immediately
      decompresses**, returning `None` unless the bytes match the original
      exactly. That doubles the work per JPEG and buys the ability to *fall
      back* rather than *fail* — a file lepton would mishandle is caught while
      storing it raw is still free, instead of at restore time when D9 would
      refuse the whole archive. Reuses the `stored/` machinery G9 extended
      (a `codec: "lepton"` ledger entry), so no new route was needed.
- [x] B3. ✅ **DONE 2026-09-02 — but NOT as specified.** The plan said
      "`oxipng -o max` default"; measured, that would have broken the product.
      ([benchmarks/2026-09-02-b3](benchmarks/2026-09-02-b3-png.md).)
      **oxipng does not preserve bytes**: on 10 real PNGs it saved 31.79% and
      produced **0 byte-identical files**. It re-encodes the image to a smaller
      form that renders the same — pixel-lossless, not byte-lossless — so it
      cannot satisfy a SHA-256 ledger. **oxipng moves to Phase C** with the
      AV1 re-encoder: opt-in, labelled, changes your file.
      **The lossless route is better anyway.** PNG is deflate all the way down,
      so Precomp expands and reconstructs it exactly: **38.41% saved, 15/15
      byte-identical**, against oxipng's 31.79% and zero. All it needed was for
      PNGs to stop being routed to `store` — `_DEFLATE_MEDIA = {".png"}` is the
      one exception to "media stays stored", because a PNG's entropy is deflate
      output rather than real randomness. JPEG deliberately stays out: its
      entropy *is* real and it has B2/lepton on the stored route.
      **Uncovered a bigger bug.** PNG inflates ~50x through Precomp (3.5 MB tar
      → 177 MB .pcf), and extraction runs the chain backwards, so the
      decompression-bomb guard's flat 8x-over-ledger allowance refused the
      restore. No multiplier can fix that — loose enough for PNG is no defence,
      tight enough to defend rejects PNG. So `StageRecord.input_bytes` now
      records what each stage actually consumed, and extraction is bounded by
      that measured figure + 25% instead of a ratio. **This makes the bomb
      defence stronger**, and old archives (`input_bytes: 0`) fall back to the
      multiplier, with a test that strips the field and restores one.
      Also: `precomp_inflation()` is now per-type and byte-weighted, because a
      flat 5x under-reserved temp for PNG by an order of magnitude.
- [x] B4. ✅ **DONE 2026-09-07** — FLAC, and **the first specialist in this
      project that beats the route already present**. Measured in
      [benchmarks/2026-09-07-b4](benchmarks/2026-09-07-b4-wav-flac.md) on 4
      real WAVs (335,536,808 B):

      | method | saved | lossless |
      |---|---:|:--:|
      | store (what shipped) | **0.00%** | n/a |
      | `7z -mx=9 -mf=Delta:4` | 3.07% | yes |
      | `7z -mx=9` default | 9.45% | yes |
      | **`flac -8 --keep-foreign-metadata`** | **43.15%** | **yes, 4/4** |

      **The baseline was 0% and the explanation was false.** `.wav` is
      `Category.AUDIO`, `AUDIO` is in `_MEDIA`, so 5.07 GiB of real audio was
      stored verbatim and told "already compressed by its codec". A WAV has no
      codec. Its entropy is genuinely high (7.70–7.88 bits/byte,
      `sample_ratio_max` 0.991–1.000), so no entropy heuristic could ever have
      caught this — only the *format* says an audio predictor will halve it.
      New `_UNCOMPRESSED_AUDIO` set in `planner`, the audio twin of B3's
      `_DEFLATE_MEDIA`.
      **7-Zip's Delta filter, which exists for this, made it 3× worse.**
      Mastered music is loud, so consecutive samples are far apart and
      differencing raises the entropy it was meant to lower.
      **`--keep-foreign-metadata` is mandatory, and plain `flac -8` would have
      made B4 a Phase C item.** Without it: 43.79% saved and **0 of 4**
      byte-identical. The `data` chunk matched exactly (`0x031899f0` both
      sides) while the file came back **458,114 bytes short** — these WAVs
      carry non-audio RIFF chunks that `flac -d` silently drops. FLAC is
      lossless about *audio*; the ledger is about *files*. The flag costs 0.64
      points of ratio and buys byte-identity.
      **End to end:** 201,976,638 → 116,227,778 B (42.45%), 3/3 verified,
      byte-identical under an independent SHA-256 walk.
      Implementation follows B2's lepton pattern exactly (`excmp/flacaudio.py`):
      pack, **immediately unpack and compare**, return `None` otherwise — so a
      file FLAC would mishandle is caught while storing it raw is free. The
      `codec` key in the container is now a **registry** rather than a
      hardcoded `"lepton"`, which was spelled out in six places across writer
      and reader.
      **The 610 `.flac` files are a separate question**, deliberately untouched:
      they are already FLAC, so the issue is "does anything beat storing it",
      which is where the analyzer already routes them.
      ⚠️ **A process note.** This item was recorded as "BLOCKED on test
      material" by an earlier session that searched the two corpus folders and
      `~/Music` and never checked `Desktop\Downloads-1`. The user corrected it.
      **A negative search result is only as good as the search**, and that one
      was written down with the confidence of a measurement.
- [x] B5. ✅ **DONE 2026-09-07** — and it was not the job this item
      describes. Measured in
      [benchmarks/2026-09-07-b5](benchmarks/2026-09-07-b5-pdf-office.md) on
      **238 real PDF/Office files (433.4 MiB)**.
      **These types were already piped, not stored** (all four are in
      `_PRECOMP_EXPANDABLE`), and the existing lossless route is already
      strong: on 224 files, Normal `7z` saved **10.37%** and Extreme
      `precomp → 7z` saved **50.36%** — Precomp does 4.9x what plain 7-Zip
      does. So a specialist has to beat 50.36% *losslessly* to earn a place,
      which is the B3 lesson repeating.
      **The real defect was in the estimator, and it is fixed.** It predicted
      **13.78%** for Extreme against the measured 50.36% — so
      `compare_profiles` showed Extreme beating Normal by 4 points where the
      truth is 40, steering users past half their compression on two of the
      most ordinary document formats there are. Now **46.32%**: error 36.6
      points → 4.0, still conservative.
      **Why it was invisible:** `zlib_stream` checks for a zlib header at
      offset 0 and **all 224 files fail it** — a `.docx` starts `PK`, a PDF
      scatters Flate streams through its body — while the entropy probe
      honestly reads 0.88-0.91. `estimate.py` had recorded "no cheap signal
      separates them" as permanent; that is true of the *bytes* and false of
      the *container*.
      **Why an extension list would have been wrong:** 37% of the estimator's
      own backtest corpus is a 263 MB **encrypted** `.zip` that measured
      2.97%. Two real corpora, same extension, opposite answers. So
      `analyzer.probe_expandable` reads structure — a zip's central-directory
      member flags, or a bounded `/FlateDecode` scan for PDFs — and both
      corpora now agree.
      **qpdf: measured, and closed rather than deferred.** Fetched with E1 and
      run on 10 real PDFs with `--object-streams=generate --recompress-flate
      --compression-level=9`. Two independent disqualifications, either
      sufficient: **0 of 10 files came back byte-identical**, so no output of
      it can satisfy a SHA-256 ledger; and it saved **7.14%** against the
      existing lossless route's **49.5% on the same ten files** — losing by
      7×, with two files coming out *larger*. Moved to Phase C as **C7**,
      where its value is marginal anyway. There is no configuration of qpdf
      worth adding to a lossless phase. The "unpack docx members into the solid stage"
      half is already achieved by Precomp for Extreme/Insane; doing it
      explicitly would only help profiles without Precomp and would need B2's
      pack-verify-fallback pattern to stay byte-lossless.
- [ ] B6. **xtool stage** (game paks: zlib/lz4/zstd/**Oodle** via the game's own
      oo2core DLL): detected-only, MIT but archived upstream — always verified
      roundtrip; extend router with pak/Oodle magic detection. **Source study
      ([13](research/13-source-study-xtool.md)) adds hard requirements:**
      (a) **restore = recompress**, so the oo2core DLL is part of the archive
      contract — pin `{oodle_dll_name, sha256, source_relpath}` in the manifest,
      re-resolve from the game folder at restore, refuse clearly on mismatch
      (Oodle has **no** patch fallback); (b) exact CLIs —
      `precomp -mkraken+mermaid+selkie+leviathan+hydra -c64mb -t2 -d0
      "-oodle<GAMEDIR>\oo2core_9_win64.dll" -bd<TOOLS> <in> <out.xtp>` and
      `decode -t2 "-oodle…" -bd<TOOLS> <out.xtp> <restoredir>`; (c) pass **`-t2`**
      explicitly (default `50p` = 1 thread on 2 cores); (d) run with **cwd = a
      scratch dir** (temp files land in CWD) and **blacklist `-s`** (skips
      verification); (e) container bytes are non-deterministic — hash the
      *restored* payload, never the `.xtp`; (f) fast lane = ship curated `.xtl`
      game-fingerprint DBs in the plugins dir (recognize file by CRC ladder →
      known stream layout, zero scanning). Never ship srep (not OSI; plain
      `-dd` dedup is fine without it)
      🔒 **RESEARCH 2026-09-01 ([24](research/24-fitgirl-razor12911-toolchain.md)
      §2): there is no open-source Oodle *encoder*, and there will not be one.**
      `powzix/ooz` is the reverse-engineered Oodle implementation everyone
      cites, and its own README reads `-z --compress compress (requires
      oo2core_7_win64.dll)` — it **decodes** in open code and **encodes by
      calling the proprietary DLL**. Since our model is restore = recompress,
      the DLL is unavoidable and permanent. This converts the audit note below
      from "prudent design" into "forced": B6 must be built around shipping or
      re-sourcing the exact `oo2core` version, because no OSI-only path to
      Oodle recompression exists. Also confirmed: xtool is **MIT, © 2016-2022,
      archived 28 Oct 2023** — our routing was correct, but nothing upstream
      will ever be fixed, so pin the version and verify every roundtrip.

      ⚠️ **AUDITED 2026-09-01 — B6 as written would still leave the AAA gap
      open, and the reason is load-bearing.** B6(a) says "re-resolve the
      oo2core DLL from the game folder at restore". **In the archival case
      the game folder no longer exists** — and architecturally it cannot,
      because `planner._CHAINS` is one linear whole-payload chain and a stage
      is one path in, one path out, so the DLL is *inside the very blob xtool
      decode has to produce*. Left as written, an xtool archive only restores
      on the machine that made it, which breaks the lossless guarantee far
      more seriously than the ratio gap B6 exists to close. **Fix before
      implementing:** force the oo2core DLL(s) into the `stored/` bucket, copy
      them in as a container resource when the user's selection did not
      include them, materialize to the scratch cwd before decode, and make the
      manifest field a **list** — one game can ship several oo2core/oo2ext
      versions and different paks can come from different ones.
      **Five sub-items the plan is missing:** (i) where the xtool stage sits
      in the chain and how it arbitrates with Precomp (both handle zlib);
      (ii) a version pin for the xtool binary, not just the DLL; (iii)
      `excmp/ram.py` is LZMA2-only, so the shipped peak-RAM column will
      silently under-report — xtool decode's `-dm` default is 75% of RAM,
      which is the number that hurts on a 2-core/16 GB target; (iv)
      `excmp/analyzer.py` has zero Oodle/pak awareness and
      `gui/suggest.py`'s prose already promises "70%" on paks, so J8's
      estimator backtest **regresses before it improves**; (v) a free-disk
      preflight for precompression inflation, plus a decision on what an
      xtool stage does to D9's chain-replay cost. **Also:** the self-test
      cannot exercise the real failure mode (a *different* DLL at restore),
      so it will look green while the actual risk is untested — the manifest
      pin is the only defence. **Phase H conflict:** nothing currently stops
      an installer being generated from an xtool+Oodle archive, which would
      embed a proprietary DLL in a redistributable `setup.exe` and break the
      100%-OSI requirement E4/SignPath depends on. **Effort is 3-4 sessions,
      not 1-2**, and B6(f) (`.xtl` curation) should be split out as post-v1:
      doc 09 §4 classifies it as the least transferable lever and it requires
      owning and running each title. **The "needs E1 first" dependency is
      soft** — `tools.py` already degrades gracefully and `_resolve_chain`
      already warns, the same detected-only pattern B4 uses. What E1 really
      buys is a pinned hash, which restore-side correctness wants anyway.

- [x] B7. ✅ **DONE 2026-09-02** — BCJ2, measured rather than assumed
      (`tests/test_sevenzip_switches.py` carries the table).
      Across three corpora on 7-Zip 26.02 at mx9: forcing `-mf=BCJ2` is worth
      **−1.296%** on 23.5 MB of real DLLs/EXEs, **+0.000%** on 163 MB of
      installers, and **+0.043%** (i.e. slightly worse) on 3.2 MB of source.
      So it is applied **conditionally** — `_wants_bcj2()` turns it on when
      ≥25% of the *piped bytes* are `Category.EXECUTABLE`, weighed by bytes
      rather than file count, because one 50 MB DLL beside a hundred small
      text files is an executable job.
      **The plan's "5-10% on x86" figure is not supported**: measured here it
      is **1.3%**. The item already flagged it as benchmark-derived with no
      source-level basis; this is our own number replacing it. Forcing the
      filter also proved necessary — at mx9 with the MT mixer 7-Zip is
      documented to auto-select BCJ2 and plainly had not. **Never UPX** still
      stands.
- [x] B8. ✅ **DONE 2026-09-08** — and the benchmark was the easy half. Full
      numbers: [benchmarks/2026-09-08-b8](benchmarks/2026-09-08-b8-rebenchmark.md).
      **Silesia, 211,938,580 B, four profiles, every restore byte-identical:**
      fast `zstd` **75.18%** (2.4m) · normal `7z` **77.03%** (2.5m) · extreme
      `precomp→7z` **78.05%** (8.8m) · **insane `precomp→zpaqfranz` 80.55%**
      (16.7m).
      **Insane is vindicated, conditionally.** B1 measured it *losing* to
      Extreme on installers (40.77% vs 41.75%, 2.3× the time) and concluded the
      CDC dedup had nothing to find. On text it wins by 2.50 points. It is
      **data-dependent**, not weaker — and doc 09's table should never have
      implied a single ordering.
      **The estimator's range excluded the truth on 3 of 4 profiles**, off by
      −14 to −19 points. `_CODEC_FACTOR` was one multiplier per chain, all near
      1.0, fitted on the 721 MB Programs corpus — installers, where the probe
      reads 0.91–0.97 and a real chain *cannot* beat it. Correct for that data,
      then generalised into a property of the codec.
      Fixed by making the factor depend on compressibility,
      `factor(r) = (1 − k) + k·r`, **anchored at the one point that is physics
      rather than fitting**: at probe 1.0 the data is incompressible, so the
      factor must be 1.0. Two independent corpora produced lines passing within
      **1.2%** of that point without being told to — that agreement, not the
      fit, is why the shape is trusted. **1/4 → 4/4 in range**, error now
      +2.6…+3.5 points (conservative), Programs backtest unchanged.
      **A six-shape stress matrix found three more defects, and then killed
      the fixes for two of them — which is the more useful result. 3/6, and
      deliberately so.**
      **C, worth 50 points:** no term for G9 dedup at all, so 20 MiB of random
      data duplicated once was predicted to compress by nothing (random →
      `store` → every ratio 1.0) while the real archive halved. A same-size
      credit closed all 50 points **and broke the exactness guarantee** — five
      10,000,000-byte videos that are *not* duplicates gave `low = 10 MB`
      against a true 50 MB. "Stored bytes are exact, not estimated" is a
      documented property and the load-bearing one; a store-only estimate that
      says "exactly this" and is right beats one that says "between half and
      all of it" for a case that may not occur. **Reverted.**
      **B, worth 7.6 points:** 7-Zip's mx9 dictionary is 256 MiB and found a
      duplicate 120 MiB away. Extending the long-range floor to 7-Zip chains
      fixed it **and set `low` to 10% of piped bytes for every ordinary
      estimate** — destroying a uniform file's exactness, collapsing Normal's
      and Extreme's optimistic ends, and pushing the Compress page to 447px.
      **Reverted**; the floor stays zstd-only, where K4 made long-range
      matching deliberate.
      **D/E, 2,093 bytes on a 125 MB archive:** the obvious fix was tried and
      **measurement contradicted it** — `_ZIP_ENTRY_BYTES` raised to 160, then
      measured at 1,429/1,455 real against 1,460 modelled, i.e. already
      over-booking, and reverted. The harness reports 3,553 bytes where a
      direct measurement gives 1,455, implicating the harness.
      **The same proxy was wrong twice for different reasons**, which is the
      lesson worth keeping: against zstd because it matches *substrings* (equal
      length implies nothing), against G9 because the mechanism is right but
      the cost is not.
      **One shipped side effect:** the Compress page guard moved 420 → 447px.
      Not drift — before B8 `low` and `high` collapsed on that fixture so no
      range line rendered at all; honest ranges mean every profile row now
      carries one. Suppressing the range to save 27px was rejected, since J1
      exists to stop the product presenting a guess as a single number.
      `suggest._span` was compacted instead ("38.1 – 85.9 MB", one unit).
      **What could NOT be measured:** doc 09's two *game* rows stay `(est.)` —
      no Oodle game folder on this machine, the same blocker as B6, and filling
      them from a text corpus would be the exact failure B8 exists to correct.
      Doc 09 also had a stale fact fixed: it described our chain as
      `precomp→srep→7z`, and SREP left every chain in B11.
- [~] B9. 🟡 **PARTLY DONE 2026-09-02** — `-mqs` is now always passed (measured never harmful, worth 0.13% on source trees; 7-Zip leaves it off by default). **`-md=192m` was measured and deliberately NOT adopted: zero bytes of difference on all three corpora, up to 27% more time.** It stays a user knob, not a default. Default threads is already 2. **✅ B9 FINISHED 2026-09-11 — the formula was not unfinished, it was
      *unreachable*.** Numbers:
      [benchmarks/2026-09-11](benchmarks/2026-09-11-ram-and-lolz.md); harness
      `tools/ram_backtest.py`, peak working set via `GetProcessMemoryInfo` on
      the exited child rather than a sampled poll.
      `lzma2_decompress_ram` was already source-pinned to
      `CompressDialog.cpp:3016` and already right - 66 MiB predicted at
      `-md=64m` against **71 MiB measured single-threaded**. But nothing ever
      passed `-mmt`, so a real decode used 255 MiB and **the figure the app
      showed was 3.9x optimistic** on the one path where optimism costs most.
      "Finish the formula" was really "make its precondition true" = G7.
      **Compression under-booked too** (198/176 = 1.12 at `-md=16m`,
      686/680 = 1.01 at 64m) - the dangerous direction, because under-booking
      is what lets a job be accepted and then thrash. **The first fix was
      wrong and a fourth measurement caught it:** a flat +32 MiB baseline
      fitted all three large rows, then predicted 64.7 MiB for a job measuring
      15.8 - re-creating the "6.0 GB for a 371 KB job" failure
      `effective_dict` exists to prevent. The margin is proportional instead;
      every measured row now over-books and a 300 KB job still reports
      37.6 MiB. An existing test broke on the flat version and was right to.
      Original item: **RAM caps + thread defaults** (verified formulas, [research/12](research/12-lightweight-and-performance.md);
      **corrected by [19 §3](research/19-source-study-7zip.md)**):
      change default `threads` from 4 to **2** — but the reason is that at mx9 each
      LZMA2 **block** (not "chunk") uses 2 threads (match-finder + coder), so
      total = 2 × block-threads; more just splits the stream and costs RAM.
      ⚠️ **mx9 default dict is 256 MiB on 64-bit since 7-Zip 24.09**, not 64 MB —
      any "mx9 = 64 MB" note in doc 12 is two generations stale, and on 4 GB
      machines mx9 MT LZMA2 can exceed RAM (≈13× dict per block thread). Use the
      **exact estimator formula** `CompressDialog.cpp:2942-3016`
      (`size1 = hs*4 + dict*4 + dict*4 + buffers`, decode = dict + 2 MiB), not a
      flat multiplier. `7z -md=192m` (~2.0 GB compress, 192 MB to extract), never
      past 512m; always pass **`-mqs`** for exe/media trees (solid type-sort is
      OFF by default — [19 §5](research/19-source-study-7zip.md)); keep zstd
      `window_log=27` — `--long=31` costs the *decompressor* too. (srep line
      dropped: not OSI; long-range dedup now comes from B1 zpaqfranz.)
- [x] B10. ✅ **DONE 2026-09-09** (branch `phase-d5-d6-d7-hardening`).
      Half of it was already true and half was not. Lepton **is** the
      in-process wheel - `excmp/jpeg.py` imports `lepton_jpeg_python` and
      round-trips through `compress_bytes`/`decompress_bytes` with a
      bit-exactness self-check - and it appears in no tool manifest. But
      `zstd` was still a row in `tools.CANDIDATES`, so the Settings tab
      printed **"zstd - not installed"** for the codec that runs the whole
      Fast profile in-process, which reads as a degraded install and invites a
      pointless download.
      **Fixed with a qualifier, not a deletion**, following the `LEGACY_ONLY`
      precedent: `tools.IN_PROCESS` marks it and the row now reads "built in,
      no executable needed (in-process via the zstandard wheel)". Deleting the
      row would have left `zstd` as a *stage* id in the planner, estimator and
      progress model with nothing anywhere explaining why it has no binary,
      and would have broken the tool-table shape `tests/test_tools.py` pins.
      Rendered and looked at in both themes.
      Original item: **JPEG correction to B2**: use the `lepton-jpeg-python` **wheel** (0.5.8,
      win_amd64, Apache-2.0, in-process, bit-exact) — Microsoft ships no exe, so the
      wheel is the only zero-build Windows path. And **drop zstd.exe** from any tool
      manifest: the `zstandard` wheel already embeds libzstd in-process
- [x] B11. ✅ **DONE 2026-08-02** (branch `phase-b11-d9-integrity`, measured in
      [benchmarks/2026-08-02-b11-d9-acceptance.md](benchmarks/2026-08-02-b11-d9-acceptance.md)).
      Chains are now `precomp → sevenzip`; old srep archives still extract
      (pinned by a test that builds a genuine pre-B11 archive and restores it).
      The measured price: −3.5 points on the dedup-friendly corpus, +31 s
      compress on the 721 MB corpus — SREP's dedup used to shrink 7-Zip's input.
      B1 (zpaqfranz) is how the points come back. Original item:
      **Remove SREP from the Extreme/Insane chains** — the source study
      already decided this ([20 §4](research/20-source-study-lrzip-zpaqfranz.md),
      [21 §5](research/21-source-study-synthesis.md): not OSI-clean, so it can never
      ship, and B1's zpaqfranz CDC dedup replaces it) but `planner._CHAINS` still
      lists it, so every Extreme run on this machine uses it.
      **Now urgent rather than tidy:** on 2026-08-01 `srep64.exe` failed a restore
      with "checksum of decompressed data is not the same as checksum of original
      data" on **1 of 3 runs over byte-identical input** — intermittent, which is
      worse than deterministic. Details in
      [benchmarks/2026-08-01-estimator-backtest.md](benchmarks/2026-08-01-estimator-backtest.md).
      Dropping the stage removes the fault and the licence problem together; the
      chain becomes `precomp -> sevenzip`, whose estimator constants are already in
      `excmp/estimate.py`. Do B1 first if the dedup is wanted back.

## Phase C — Media Shrink mode (opt-in, quality-targeted)

- [ ] C1. Tool downloader first (see D6) → fetch FFmpeg GPL build (gyan.dev, ~90 MB,
      SHA-pinned) **after asking the user in-app**
- [ ] C2. `ffprobe` stage: codec/bitrate/resolution probe; skip rules (already
      AV1/HEVC at low bits-per-pixel → "nothing to gain")
- [ ] C3. AV1 encode stage: SVT-AV1 preset 8-10 on this class of CPU, CRF slider
      mapped to three cards: *Visually lossless (CRF 24) / Balanced (28) / Small (32)*;
      audio → Opus 128k; subtitles/chapters preserved (mkv out)
- [ ] C4. Honest UX: ETA warning before starting ("~9 hours on this machine — run
      overnight?"), output tagged so we never re-encode our own output
- [ ] C5. Later: ab-av1-style CRF search targeting VMAF 95 (needs beefier machine)
- [ ] C7. **(moved from B5, 2026-09-07)** `qpdf` as an **opt-in** PDF
      rewriter. Measured 7.14% on 10 real PDFs with **0 of 10 byte-identical**,
      against the lossless `precomp → 7z` route's 49.5% on the same files — so
      it is both non-byte-lossless *and* 7× worse, and two files got larger.
      Pinned in `toolfetch.TOOL_MANIFEST` and fetchable, but only worth
      building for the case where Precomp is unavailable. Numbers:
      [benchmarks/2026-09-07-b5](benchmarks/2026-09-07-b5-pdf-office.md) §8.
- [ ] C6. **(moved from B3, 2026-09-02)** `oxipng` / ECT as an **opt-in**
      PNG re-encoder. Measured 31.79% on real PNGs but **0 of 10 files came
      back byte-identical** — it rewrites the image to a smaller encoding.
      That is pixel-lossless, not byte-lossless, so it belongs here with the
      AV1 re-encoder and not in a lossless phase. Note the lossless
      `precomp → 7z` route already beats it (38.41%), so this is only worth
      building for the case where Precomp is unavailable.

## Phase D — QA hardening (data integrity IS the product)

- [x] D1. ✅ **DONE 2026-09-02** — property-based roundtrip tests
      (`tests/test_property_roundtrip.py`, Hypothesis, MPL-2.0, dev-only).
      States the product's whole claim as one executable property:
      `extract(compress(T)) == T` for every generated tree. Trees mix names
      drawn from the characters that actually break archivers (unicode,
      spaces, dots, `=`, `#`, `&`), contents from the three regimes a codec
      treats differently (compressible / random / empty), and per-file depth
      0-3 so one example can hold a top-level file and a four-deep one.
      Two more properties alongside it: **the input is never modified** (bytes
      *and* mtime) and **the ledger accounts for every file** — an entry
      missing from the ledger is a file nobody would notice failing to return.
      Suite runs 30 examples; a one-off deeper hunt of **120 generated trees
      found no counterexample**.
- [x] D2. ✅ **DONE 2026-09-02** — the awkward-but-legitimate file matrix
      (`tests/test_edge_cases.py`, 25 cases, all real engine round-trips).
      The complement to D0: `test_safepath.py` pins what we **refuse**, this
      pins what we must **accept**, because rejecting a legitimate awkward
      name is its own kind of data loss. Covers spaces, parens, `=`, `%`,
      `&`, `#`, brackets, apostrophes, Cyrillic, Japanese, **Dhivehi**, emoji,
      200-character names, leading dashes; zero-byte files, trees of nothing
      but empty files, 20-deep nesting, 200 small files, >260-character paths,
      read-only attributes, and names that merely *contain* a reserved word
      (`CONTENTS.txt`, `console.log`, `NULLABLE.md`) — the false-positive half
      of D0's validator. Plus an explicit input-is-never-modified check on
      bytes and mtime. **All 25 passed first time**; no bugs found, but the
      class was previously untested.
- [x] D3. ✅ **DONE 2026-09-02** — crash consistency
      (`tests/test_crash_consistency.py`, 8 cases). Cancels a job from inside
      `progress_cb` so the interrupt lands *during* a stage rather than at a
      boundary, then asserts the three things that must hold either way: the
      input is untouched (bytes and mtime), nothing partial sits at the output
      path, and temp is clean — the last one matters because Precomp
      legitimately inflates 2-5x mid-pipeline. Also pins D9 as a
      crash-consistency property: an assertion inside the progress callback
      fires if a `.excmp` ever appears at the final path *before* verification
      finishes. Plus: a cancelled run must not poison the next run sharing the
      same temp dir.
      **One thing the implementation corrected:** the first version asserted
      `pytest.raises` and failed on the Fast profile — not a bug, the corpus
      simply finished before the cancel landed. Whether a cancel wins is a
      race, so the tests now assert the invariant that holds *either way*: if
      the job finished it must have published a genuinely restorable archive,
      and if it stopped it must have published nothing.
- [ ] D4. **Disk-full simulation** on a small VHDX/subst volume; graceful failure
- [x] D5. ✅ **DONE 2026-09-09**, and completed 2026-09-10 (branch
      `phase-d5-d6-d7-hardening`).
      `excmp verify --deep [--source DIR]`, plus `verify.tree_hash()` and
      `verify.verify_source()`.
      **2026-09-10: the feature was unreachable from a script and nothing
      noticed.** `echo pw | excmp verify --deep --password ...` hung
      indefinitely, because `getpass.getpass` on Windows is `win_getpass`,
      which reads the *console* via `msvcrt.getwch()` and falls back to stdin
      only when `sys.stdin is not sys.__stdin__` - which piping does not
      change. So deep verification of an **encrypted** archive worked only
      with a human at a terminal, and the callers that most want it are a
      scheduled sweep, a CI job and a batch script. `_read_secret` now reads
      one line from stdin when stdin is not a tty; `--password` still takes no
      argument, because argv is in the process table and in shell history
      while a pipe is in neither. Measured after the fix: the same command
      returns in **0.8 s**, and its tree SHA-256 matches the API path exactly.
      **The lesson: a fix is not finished until it is used the way the thing
      it unblocks will be used.** Adding `--password` was checked by running it
      interactively - the one context where the remaining bug is invisible.
      **`verify_archive` already was the `t` half** - a full restore with
      every file re-hashed against the ledger - so what was missing was
      zpaqfranz's *other* verb: `v -ssd`, re-reading the **originals** off
      disk and comparing them against what the archive recorded. That answers
      a question nothing else here could - "are my originals still the bytes I
      archived?" - because the archive is the only reference copy of it.
      **Measured on real data** (56 files, 2.5 MB): one flipped bit in a
      120,313-byte file caught as "same size, different content", a deletion
      reported as `missing`, a new file as `new`, exit code 1 for the changed
      one only. Deep mode costs **nothing measurable** - 4.13 s mean against
      4.27 s shallow over three runs each - because the tree hash is built
      from digests `verify_restore` already computed; the source pass costs
      one read of the originals.
      **The tree hash is sort-then-hash, not XOR.** XOR is order-free without
      sorting and unusable here: it is self-cancelling, so a tree holding the
      same content at two paths collapses to the value of a tree holding
      neither - and this program deduplicates identical files as a *feature*.
      It also binds each digest to its path, so two files swapping names is a
      different tree. The line format is `sha256sum`'s, so the value is
      reproducible with `sort file.sha256 | sha256sum`.
      Original item: **Deep-verify command** (`excmp verify archive.excmp`): full decompress +
      hash-compare every file. Model source-pinned by
      [20 §6](research/20-source-study-lrzip-zpaqfranz.md): zpaqfranz's split of
      `t` (decompress to RAM + re-hash every fragment, no source needed) and
      `v -ssd` (re-read source from disk vs stored hash) together equal
      "extract-and-compare" without temp space — run both. Add an
      **order-independent global tree hash** (zpaqfranz `sum` model: combine
      per-file SHA-256 order-free) for one-value whole-output equality against
      the ledger. Avoid zpaqfranz `p -paranoid -to` in automation (interactive
      captcha when the target dir is non-empty)
- [x] D6. ✅ **DONE 2026-09-09** (branch `phase-d5-d6-d7-hardening`).
      `tests/test_fuzz_container.py` (48 tests) and `tools/fuzz_container.py`
      for a long soak. **It found eleven unhandled exception shapes on the
      first pass**, each reproduced before a line was changed, all on the path
      `excmp list` takes for any file a user points at:
      `declared_total({"a": "not a dict"})` gave AttributeError;
      `{"size": "abc"}` ValueError; `{"size": [1,2]}` and `{"size": None}`
      TypeError; `{"size": nan}` ValueError; a list as the ledger
      AttributeError; `from_json("[1,2,3]")` AttributeError;
      `parse_size("1e400m")` OverflowError, plus three more size strings.
      **`declared_total` is not a corner**: its result *is* the payload budget
      and D0.3's decompression-bomb budget, and `{"size": 10**400}` sailed
      through and became one. The fix refuses the archive rather than
      clamping - a ledger whose sizes cannot be read is a ledger whose bounds
      cannot be trusted.
      **The ledger is validated once, at the parse boundary**
      (`manifest.validate_ledger`), on the same principle that makes
      `safepath` the only place an archive-supplied *name* is judged; four
      places downstream had each been trusting its shape. `verify_restore`
      keeps its own guard because it is public and gets ledgers that never
      came from a manifest.
      **HypoFuzz was not used and is not installed**: the interesting surface
      is pure byte-in - a manifest string, a ledger dict, a sidecar text, a
      name - so Hypothesis, a dev dependency since D1, generates at it fast
      enough. Measured soak: **35,000 examples across 7 properties in 136 s**,
      no violation. If the parser ever grows deep branchy paths, install
      HypoFuzz and point it at the same module; nothing needs to change.
      Original item: **Fuzzing**: HypoFuzz over the `.excmp` parser on Windows
      (Atheris is Linux-only); optional Linux CI job running Atheris
- [x] D7. 🟡 **WRITTEN 2026-09-09, UNPROVEN UNTIL PUSHED** (branch
      `phase-d5-d6-d7-hardening`). `.github/workflows/ci.yml` +
      `tests/test_ci_workflow.py` (17 tests) + README badge.
      **Three jobs, sized for a private repo's 2,000 free minutes:** `test`
      (every push, py3.12, no network beyond pip) is the gate; `matrix`
      (schedule + dispatch) adds 3.13 and an explicitly *informational* 3.11
      leg via `continue-on-error`, because the README declares 3.12+ so a 3.11
      failure answers "could the floor drop?" rather than being a regression;
      `pinned-tools` (schedule + dispatch) fetches the E1 binaries behind a
      `tools/bin` cache keyed on `hashFiles('excmp/toolfetch.py')`.
      **Two holes were found in my own first draft, both "green means
      nothing".** `ensure_tool` returns None on failure and never raises -
      right for the app, wrong for CI - so `pinned-tools` would have printed
      `qpdf None`, exited 0, skipped every chain test and reported success;
      the step now checks the return values. And every chain test is behind
      `skipif(find_tools()["7z"] is None)`, so a runner without 7-Zip gives a
      *green* suite that exercised none of the product - the gate job now
      requires 7-Zip, installs it from Chocolatey if the image lacks it, and
      fails loudly otherwise. `pytest -q -rs` everywhere, so silent skips stop
      being silent.
      **The roadmap's "7-Zip preinstalled!" is asserted nowhere** - it could
      not be verified from this machine, so the workflow prints the discovered
      tool table and the first run answers it with evidence.
      **PyYAML became a dev dependency** so the test can *parse* the workflow
      rather than trust it; the corpus-path guard in that file deliberately
      takes no yaml fixture, because a missing pyyaml would otherwise take the
      guard down with it.
      **What is left is a push.** A workflow that has never run is not
      evidence, and this project does not record unreproduced behaviour, so
      this stays amber until a run exists.
      Original item: **CI**: GitHub Actions `windows-latest` (7-Zip
      preinstalled!) - matrix Python 3.11-3.13, `setup-python` pip cache,
      SHA-keyed tool cache; badge in README
- [x] D8. ✅ **DONE 2026-09-09** (branch `phase-d8-atomic-publish`).
      Atomic-write upgrade: temp + `fsync` + read-back hash + `os.replace`,
      as `excmp/atomic.py` — `publish()`, `atomic_write_text/bytes()`,
      `fsync_file()` — behind every output the program writes: both archive
      publishes, both sidecars, the calibration store and the history file.
      18 tests in `tests/test_atomic_publish.py`; numbers in
      [benchmarks/2026-09-09-d8](benchmarks/2026-09-09-d8-atomic-publish.md).
      **The defect it was worth doing for was in the half that already
      existed:** `compress()` did `out_path.unlink()` and *then* `replace()`,
      so a failure at the rename — the one moment a whole job is on the line
      — left the user with neither yesterday's archive nor today's. There
      since the engine's first commit, survived D9 and the K series, because
      every test asserted what the new archive looked like and none asserted
      what happened to the old one.
      **Measured cost, Silesia/normal (48.7 MB archive, 116 s job):** flush
      5.3 ms, read-back 266.5 ms at 182.7 MB/s, **0.234% of the job** — and
      **0.0046% with `--sidecar`**, because the read-back digest is the one
      the sidecar used to re-read the whole archive to compute. The split
      path got *faster*: digests measured while writing each part make the
      volumes sidecar **13.9×** cheaper (218.2 ms → 15.7 ms), ~4.2 s per GB.
      **Four things the implementation corrected:** (1) an expectation on the
      read-back is vacuous on the plain path — nothing runs between the write
      and the rename, so it was two passes to compare a file with itself; it
      is kept only for the password path, where a separate pass reads the
      plaintext out of temp and writes a different file, and `encrypt_file`
      now proves it read exactly the bytes the D9 gate accepted. (2) Windows
      has no directory handle to flush, so rename durability is the
      filesystem's business and the docstring says so. (3) The
      destination-identity check after the rename uses `(st_dev, st_ino,
      st_size)` rather than a second hash — the Windows file ID survives
      `os.replace`, measured. (4) `calibrate` and `gui.history` were leaking
      a `.tmp` on every failed write - **and, found by auditing the finished
      work, both promise never to raise while catching only
      `(OSError, ValueError, TypeError)`, so D8's own `PublishError` (a
      RuntimeError) had quietly given a finished job a new way to be reported
      as failed.** Adding a check to a path adds a failure mode to it; every
      caller catching by type needed re-reading, not just the write site.
      **And an anchor for every future benchmark:** the same job run twice
      gives the same archive *size* but a different payload CRC32, and
      `created_utc` moves the deflated manifest by up to 3 bytes — so B8's
      48,689,445 and today's 48,689,446 are the same compression result.
      **Compare payload size, never the archive digest, across runs.**
- [x] D9. ✅ **DONE 2026-08-02** (branch `phase-b11-d9-integrity`).
      `_verify_before_publish` fully restores the archive in temp and runs the
      real `extract()` + `verify_restore()` before the atomic rename — no hash
      match, no file. It went in as the **default, not an option**: the tagline
      promises a verified byte-identical restore, so the default had to make it
      true. Measured cost 6–48% of total job time depending on chain and mix
      ([benchmarks/2026-08-02](benchmarks/2026-08-02-b11-d9-acceptance.md));
      the estimator gained a per-chain verify term so promised waits include
      it, and the J4 preflight budgets the restore in temp — store-only jobs
      included. A corrupting stage now blocks publication outright
      (`tests/test_publish_gate.py`). Original item:
      **`compress()` can publish an archive it cannot restore** — found
      2026-08-01 during the Phase J out-of-sample run, details in
      [benchmarks/2026-08-01-estimator-backtest.md](benchmarks/2026-08-01-estimator-backtest.md).
      `engine._self_test` tests only the **last** stage's container layer (`7z t`)
      before the atomic publish, so a broken stage *underneath* it goes unnoticed.
      Observed for real: an Extreme archive was written and reported as a success,
      and `srep64.exe` then failed its own decompression checksum during extract.
      The extract-time gate worked — the failure was loud, not silent — but the
      user had already been told the archive was good.
      **Fix:** replay the *whole* chain in the self-test before publishing, at least
      for multi-stage chains, and compare against the ledger. That is the only thing
      consistent with "post-restore SHA-256 comparison is the acceptance gate for
      every stage". Cost is real (it doubles compress time for Extreme), so it may
      need to be a profile-level or opt-in "verify deeply" setting — but the current
      behaviour contradicts the stated guarantee, so the default must change or the
      guarantee must be reworded. Pair with D5's deep-verify command.

## Phase E — Release engineering

- [x] E1. ✅ **DONE 2026-09-07** — `excmp/toolfetch.py`, 20 tests, first real
      fetch (qpdf 12.4.1) verified against GitHub's own asset digest.
      **Installs to `tools/bin/<name>/<version>/`, not `%LOCALAPPDATA%`** as
      this item sketched: that is where `zpaqfranz.exe` already lives, where
      `find_tools` already looks, and it is already in `.gitignore` — so one
      directory holds every tool the app runs and a binary cannot be committed
      by accident. `EXCMP_TOOLS_DIR` overrides it for E3.
      **Found by its own first real download:** a same-host redirect rule
      refused GitHub, which serves every release asset by redirecting to
      `release-assets.githubusercontent.com`. Now a per-origin allowlist with
      both hops required https, and suffix-match bait pinned by tests.
      Enforced and tested: size **and** sha256 on the received bytes, nothing
      written to the install root until verified, `safepath` on every archive
      entry (zip-slip refused 4 ways), re-hash before use so a tampered binary
      is not handed back, a per-tool minimum-version floor, a 512 MiB download
      ceiling, and PATH never touched.
      🔴 **A critical hole was found by auditing E1 after it shipped, and is
      fixed (2026-09-07).** `verify_installed` hashed `exe_relpath` and nothing
      else — on the real qpdf install, **19,456 of 87,686,094 bytes (0.02%)**,
      because `qpdf.exe` is a launcher and the 7.4 MB `qpdf30.dll` beside it
      holds the code. Windows searches the application directory first for a
      non-KnownDLL, so replacing a sibling is code execution in the process
      the engine spawns. **Live rather than theoretical thanks to B4**:
      `flac.exe` is 339 KB next to a 522 KB `libFLAC.dll` and `flacaudio`
      spawns it — reproduced, `verify_installed` returned True with the DLL
      replaced.
      The first repair made it no better and is worth recording: the digest
      was written to `.pinned-sha256` **beside the binary**, so the same write
      that swaps a DLL rewrites the marker. Hashing the whole tree into that
      file fails identically. The anchor now lives in source
      (`ToolSpec.exe_dir_sha256`), covers every file in the executable's own
      directory, compares case-insensitively (Windows resolves DLLs that way),
      and **refuses extra files** — planting `version.dll` modifies nothing
      pinned and Windows would still load it.
      🔍 **The audit was then finished by hand (2026-09-07).** It had reported
      39 findings and run out of session with 6 of 44 agents done, so the rest
      were leads. Checked by running each:
      [benchmarks/2026-09-07-e1-audit](benchmarks/2026-09-07-e1-audit.md).
      **10 of 12 distinct claims reproduced and are fixed**; 2 did not; and 2
      more turned out to be the verification harness being stale rather than
      the code being wrong.
      The worst was a real zip bomb: **a 204,060-byte download installed
      209,715,202 bytes — 1028× — with no refusal**, because
      `MAX_DOWNLOAD_BYTES` bounds the *compressed* side and nothing bounded
      the expansion. The first replacement ceiling was 768 MiB, which sat
      *above* the bomb that had just been measured and caught nothing; it is
      256 MiB, enforced on the real stream. Also fixed: the transfer is now
      cut at the pinned size (41 MB had been written for a 120-byte pin);
      staging moved out of the install root and a failed fetch sweeps itself
      (209 MB of a refused download had been left behind); `ensure_tool` no
      longer leaks `BadZipFile`/`UnsafePathError` through a docstring that
      promises it never raises; `allow_insecure` defaults to **False**;
      `1.5.0-rc9` no longer outranks `1.5.0`; duplicate archive entries are
      refused; the redirect check compares hostnames and validates **every**
      hop, not just the last; both shipped tools carry a version floor; and
      `find_tools` finally knows E1's nested layout, which it had promised to
      search and never did.
      Original item: **SHA-pinned tool downloader** — THE lightweight strategy: core app small,
      specialists fetched when a profile first needs them (whole fleet minus FFmpeg
      is only **~15 MB**). Manifest entry = `{name, version, url, sha256, size,
      exe_relpath, license}`; download to
      `%LOCALAPPDATA%\ExtremeCompressor\tools\<name>\<version>\` via temp file →
      verify sha256 **and size** → atomic `os.replace`; hard-fail and delete on
      mismatch; **never add the download dir to PATH**; re-hash before first use each
      run. (The old "solves SREP legally by download-to-user" rationale is retired —
      SREP was dropped from all plans after the source study, doc 20 §4 / doc 21 §5. **Rationale corrected 2026-09-01** ([24](research/24-fitgirl-razor12911-toolchain.md) §5): the licence is *unclear*, not provably non-OSI — SREP-adjacent source sits in GPL-2.0 repos, though the shipped `srep64.exe` is an unlicensed freeware binary. **The disqualifying reason is integrity:** it failed its own decompression checksum on 1 of 3 runs over byte-identical input. Lead with that, not the licence.)
      **New in 2026:** GitHub's release API exposes a per-asset `digest` (sha256) —
      verified present for 7-Zip 26.02, zpaqfranz 64.8, oxipng 10.1.1, par2 1.4.0 —
      so `tools/make_manifest.py` can seed hashes from the API for a human to pin.
      Add a **minimum-version security floor** per tool (7-Zip ≥ 24.09 for
      CVE-2025-0411), not just a pinned hash. Note 7-Zip binaries are **unsigned** by
      policy, so the pinned hash IS the trust anchor — cross-check against winget
      manifests when bumping. Verified tool versions/licenses: [research/12](research/12-lightweight-and-performance.md)
- [x] E2. ✅ **DONE 2026-09-09** (docs, straight to `main`).
      `THIRD-PARTY-NOTICES.md` rewritten from **files on this machine** - 40
      licence claims, each read from a quoted path, 39 confirmed and **1
      explicitly not**. The old file dated from 2026-07-18, before the
      downloader existed, and had drifted: fetched tools were still
      "planned", six runtime dependencies were absent, three licences were
      stated less precisely than the files say.
      **What re-reading the files corrected:** 7-Zip is not "LGPL-2.1 +
      unRAR" but a per-component mix - LGPL main, LGPL+unRAR for the RAR
      engine, BSD-3 for LZFSE and ZSTD decode, BSD-2 for XXH64
      (`C:\Program Files\7-Zip\License.txt`, 6,031 bytes). qpdf is Apache-2.0
      **with an at-your-option fallback to Artistic-2.0** in every shipped
      header. Precomp is Apache-2.0 *itself* but bundles packJPG, packMP3,
      bZip2, zLib and GifLib whose licence texts are **not present here** - a
      redistribution blocker, recorded as one. FLAC is split, not dual:
      libFLAC BSD-3 (`COPYING.Xiph`), `flac.exe` GPL-2 - and we invoke the
      GPL half. `par2cmdline-turbo` is **GPL-2.0-or-later** and is a *runtime
      pip dependency* whose wheel ships `par2.exe`.
      **The one gap, stated rather than guessed:** `tools/bin/zpaqfranz.exe`
      has **no licence file beside it** - `tools/bin` holds exactly `flac/`,
      `qpdf/` and that bare 4,288,000-byte binary. The old file claimed "FOSS
      (GPL/MIT heritage)", which nothing here supports.
      Also recorded: `pyoxipng` 9.1.1 is installed, imported nowhere and in no
      requirements file - a leftover from B3, which oxipng lost.
      Original item: `THIRD-PARTY-NOTICES.md`: 7-Zip 26.02 (LGPL+unRAR), zstd (BSD), Precomp
      (Apache-2.0), zpaqfranz (MIT), lepton-jpeg-python (Apache-2.0), oxipng (MIT),
      FLAC (BSD/GPL CLI), xtool (MIT,
      archived), par2cmdline-turbo (GPL, subprocess only), squarify (Apache-2.0),
      Inno Setup (permissive), `cryptography` (Apache-2.0/BSD), `argon2-cffi` (MIT)
- [ ] E3. PyInstaller **--onedir** (NOT --onefile: self-extraction triggers AV/
      SmartScreen **and** re-extracts the whole bundle to temp on every launch)
      wrapped in an Inno Setup installer. **Commit a tuned `.spec`**: measured
      122 MB → **71 MB on disk / 28 MB zipped** by excluding
      QtQml/QtQuick/QtNetwork/QtPdf/QtOpenGL/QtOpenGLWidgets/QtSvg/QtDBus and
      deleting `opengl32sw.dll` (19.7 MB!), `qdirect2d.dll`, `translations/`. Also
      switch `requirements.txt` from `PySide6` to **`PySide6-Essentials`** (dev env
      642 MB → ~210 MB). Floor for a PySide6 Widgets app is ~55-65 MB on disk
- [ ] E4. **Code signing**: apply to SignPath Foundation (free OV signing for OSS;
      requires 100%-OSI repo — another reason xtool stays external and unrar.dll
      is never bundled). Unsigned exes need thousands of downloads for SmartScreen
      reputation; don't ship unsigned. (EV's instant-reputation advantage was removed
      by Microsoft in 2024 — OV is fine.) Also: publish `SHA256SUMS` + GitHub artifact
      attestations (2 lines of YAML ⇒ SLSA Build L2), pin Actions by commit SHA, pip
      `--require-hashes`; submit AV false positives to Microsoft Security Intelligence
      on release day; **never UPX** (verified to *increase* detections)
- [ ] E5. Auto-update v1: poll GitHub Releases API → download signed installer →
      verify SHA-256 → run; consider `tufup` (TUF) later
- [x] E6. ✅ **DONE 2026-09-09** (docs, straight to `main`).
      `CHANGELOG.md` (Keep-a-Changelog; everything under `[Unreleased]`,
      because there is no tag and inventing version numbers for work that
      never shipped as a version would be inventing history),
      `CONTRIBUTING.md` (honest that this is a private single-maintainer repo,
      and written as the practical "how to work here": the hour-long suite,
      the `%TEMP%` cleanup, the corpus guard, the render-and-look rule),
      `.github/ISSUE_TEMPLATE/{bug_report,ratio_report,config}.yml`.
      `SECURITY.md` already existed (D0.5) and was updated - it said
      encryption "will use" Argon2id, future tense, for a feature that shipped
      2026-09-03, and never mentioned that **losing a keyfile is as final as
      losing the password**.
      **One thing the templates could not ask for:** the roadmap wanted "the
      log file". There is no log file - the job log is an in-memory 400-line
      tail in a `QPlainTextEdit`. The template asks for that instead, with the
      keystrokes to copy it, and says what to do when it has scrolled past.

## Phase F — "Protect": encryption + recovery records

The user-visible security features, built on the D0-hardened base. Design and
rationale: [research/10](research/10-security-and-integrity.md).

- [x] F1. ✅ **DONE 2026-09-03** — `excmp/crypto.py`, `compress --password`,
      and `extract` decrypts transparently. Argon2id (m=64 MiB, t=3, p=4) →
      AES-256-GCM in 4 MiB chunks with age-style STREAM nonces (11-byte
      counter + final-chunk flag), the header as AAD for every chunk, and an
      HKDF check value so "wrong password" and "damaged file" are different
      sentences. The **whole container** is wrapped, so `manifest.json` — every
      filename and every hash — and the `stored/` tree are encrypted too;
      `7z -p` could only ever have covered the payload stage.
      Verified end-to-end: archive encrypted on disk, plaintext marker absent
      from the bytes, wrong password refused with the right error, correct
      password restores byte-identically.
      **A denial-of-service found in our own code while testing.** The KDF
      parameters live in the header and are therefore attacker-controlled, and
      "the header is AAD" does *not* protect them — they are needed to derive
      the key that would check the tag. `test_header_tampering_is_detected`
      flipped one bit that landed in the top byte of `m_kib`, 8 KiB became
      16 GiB, and the single test took **19 minutes**. A crafted header can ask
      for 4 TiB. Bounds are now enforced before Argon2 is called
      (8 KiB-1 GiB memory, ≤20 passes, ≤16 lanes) with three tests pinning it;
      the suite went from 19 minutes to **1.8 seconds**.
      Prompting asks **twice** when setting a password, because there is no
      backdoor and a typo is unrecoverable. The password is never accepted on
      argv — it would sit in the process table and the shell history.
- [x] F2. ✅ **DONE 2026-09-03** — a keyfile as a real second factor.
      `key = HKDF(ikm=Argon2id(password, salt), salt=SHA-256(keyfile))`. The
      ordering is the point: HKDF is fast by design, so folding the keyfile in
      *instead of* Argon2id would leave an attacker who steals the keyfile
      facing only a cheap password guess — the flaw in PeaZip's
      prepend-the-hash approach. Argon2id runs first and stays memory-hard;
      HKDF only mixes. Two tests pin that: one times the KDF directly, one
      asserts the Argon2 output is HKDF's *ikm* and not its salt.
      Format bumped to **v2** with a flags byte; v1 archives still read. The
      flag exists so a missing keyfile raises `KeyfileRequired` rather than
      "wrong password" — otherwise a user with the correct password hunts for
      one that is already right and concludes the archive is broken. The mirror
      case (a keyfile supplied where none was used) is refused too.
      Keyfile-only works; an empty keyfile is refused rather than silently
      reducing two factors to one; the keyfile is stream-hashed with a 100 MiB
      cap, because somebody will eventually point this at a 40 GB video.

      🔴 **AND IT WAS WRITE-ONLY UNTIL 2026-09-09.** Found by F5's copy
      audit, which noticed that `crypto.py` tells users to "supply the same
      file as well as the password" through surfaces that had no way to do it.
      Reproduced immediately:

      ```
      engine.compress([src], arc, NORMAL, ctx, password="pw", keyfile=kf)
      # -> writes an 855-byte archive, reports success

      engine.extract(arc, out, ctx, password="pw")
      # -> KeyfileRequired: supply the same file as well as the password

      engine.extract(arc, out, ctx, password="pw", keyfile=kf)
      # -> TypeError: extract() got an unexpected keyword argument 'keyfile'
      ```

      **The engine could write an archive no code path in the engine could
      read**, and `excmp verify` - the product's central promise - could not
      open one either. `--keyfile` existed on no CLI subcommand; the word
      appeared **zero** times in `excmp/cli.py` and once in all of `gui/`, in a
      docstring saying there is no keyfile field.

      **Why nothing caught it.** `tests/test_keyfile.py` exercises
      `crypto.encrypt_file`/`decrypt_file` directly, where the parameter always
      worked. And the D9 publish gate - the thing that would otherwise notice
      an unopenable archive - verifies the *plaintext* container **before**
      encryption, by design (F1: "encrypt after the D9 gate and before the
      rename"). Nothing on either side of that seam ever tried to decrypt what
      was published.

      **Fixed** by threading `keyfile` through every read entry point -
      `opened_for_reading`, `extract`, `extract_any`, `extract_selected`,
      `list_any`, `verify_archive` - and there were **two** decryption sites,
      not one: `extract` resolves an encrypted archive itself rather than going
      through `opened_for_reading`. A factor plumbed through one of two sites
      is exactly how this happened. `--keyfile` added to `compress`, `extract`,
      `list`, `convert` and `verify`; `--keyfile` without `--password` on the
      create path is refused, because the CLI only collects passwords
      interactively and would otherwise have written an archive with no
      encryption at all for somebody who asked for two factors.

      **Two more found by running the real CLI rather than the tests:**
      `excmp verify` had **no `--password` flag at all**, so no encrypted
      archive could ever be verified from the command line; and the right
      password with the wrong keyfile printed `error: wrong password`, which is
      false - it sends the user hunting for a password they already have, and
      the next conclusion after "my password is right and it still says wrong
      password" is "the archive is broken", which is how archives get deleted.
      It now names both factors. 13 tests in
      `tests/test_keyfile_roundtrip.py`, and the property none of them had
      stated before: **whatever factors an archive was created with, the same
      factors must open it, through the same public API a caller uses.**
- [x] F3. ✅ **DONE 2026-09-03** — `excmp/recovery.py`,
      `compress --recovery [PCT]`, and a new `excmp repair` verb. PAR2 via the
      `par2cmdline-turbo` wheel, which ships a real Windows binary; driven as a
      subprocess so its GPL stays out of our in-process code.
      **The whole point, proven end-to-end through the CLI**: 200 KB zeroed out
      of a 5.5 MB archive → `excmp repair` → **byte-identical to the original**
      → `excmp verify` passes 32/32. And the honest failure too: 300 KB of
      damage against a 5% record is correctly reported as *"damaged beyond what
      its recovery records can rebuild"* rather than attempted and fudged.
      Default dose is FreeArc's tiering (5% ≤50 MB, 3% ≤1 GB, 1% above), which
      is about what the percentage *costs*: 4% of 10 MB is nothing, 4% of 50 GB
      is 2 GB. Exit codes measured rather than assumed — 0 ok, 1 repairable,
      2 beyond repair, 3 no records.
      **One performance bug worth recording.** `_block_size` originally sized
      to par2's 32768-block *ceiling*, which for a 400 KB archive means 16-byte
      blocks and ~25,000 of them: block count drives the Reed-Solomon work
      almost linearly, and the recovery tests took **284 seconds**. Sizing for
      ~2000 blocks with a 4 KiB floor took that to **7 seconds** — a 40×
      speedup, and the same win applies to real archives.
- [x] F4. ✅ **DONE 2026-09-03** — `excmp/motw.py`, wired into `extract()`.
      The archive's `Zone.Identifier` is copied onto every file extracted from
      it, so an executable that arrived from the internet does not land looking
      like one the user wrote themselves. **Default on**, where 7-Zip's CLI
      needs `-snz`: a downloaded archive is the ordinary case, and the safe
      behaviour should not be the one you have to know a switch for.
      Direct ADS file I/O, never a shell — PeaZip shipped a
      PowerShell-injection CVE doing this exact job by shelling out, and the
      filename here is attacker-controlled. A test **parses the module** and
      fails if it imports `subprocess`/`os` or calls anything that spawns a
      process. (A first version grepped for the word and flagged the docstring
      explaining why it is absent.)
      Propagation always overwrites, which is the CVE-2025-0411 case: an
      archive that smuggles its own `Zone.Identifier` must not downgrade the
      file to "local". Read capped at 32 KB, directories skipped, and a write
      failure is ignored — FAT32 has no streams and a USB stick is not an
      error condition.
- [x] F5. ✅ **DONE 2026-09-09** (branch `phase-d5-d6-d7-hardening`).
      An audit of **all 42 user-visible crypto strings** found the wording
      already honest and the **delivery** not:
      (1) the clearest sentence in the app was a **tooltip**, needing a mouse,
      so a keyboard or screen-reader user could set a password having never
      been shown it; (2) `_show_protect` *replaced* the consequence with "The
      two entries do not match yet." for the whole time somebody was typing
      the confirmation - the exact moment they are deciding - while its own
      docstring said "Say the unrecoverable part while they are still typing
      it"; (3) the placeholder read "leave empty for no password", framing it
      as a costless convenience; (4) the CLI's create prompt said **nothing**,
      and the honest paragraph sat in a docstring printed to nobody.
      Now the consequence stands from the first keystroke with the mismatch
      notice *appended*, it is in `accessibleDescription` for assistive
      technology, the placeholder says "if set, there is no recovery", and the
      CLI prints it to **stderr** before prompting - stderr so `--json` stays
      parseable. 12 tests.
      **The existing test could not have caught any of it**: it built
      `password.toolTip() + " " + protect_note.text()` from a panel where
      nothing had been typed, so `protect_note` was `""` and it asserted on
      the tooltip alone - the visible note could have been deleted entirely
      and it would still have passed.
      Original item: Honest UI copy throughout: "protects confidentiality;
      lost password = lost data, no backdoor"

## Phase G — "Real archiver": the features that stop us being one-way

Full audit and legal routing: [research/08](research/08-archiver-product-features.md).
Almost all of it is a thin wrapper over the `7z.exe` we already shell out to.

- [x] G1. ✅ **DONE** — subsumed by G2 (`engine.list_any` / `_list_foreign` /
      `_extract_foreign`; verified 2026-09-09). **Open/extract foreign archives** (zip/7z/rar/tar/iso/cab/msi/wim/vhd…) —
      magic-byte detect non-`.excmp` input, run `7z x` through the existing
      `SevenZipStage`. **RAR read comes free** and stays legal because we exec a
      user-installed binary, never link or bundle (never ship unrar.dll — it would
      break the MIT-clean requirement for SignPath signing in E4). *This is the
      single feature that turns a compressor into an archiver.* Effort S
- [x] G2. ✅ **DONE 2026-09-01** (branch `phase-g2-foreign-listing`, measured in
      [benchmarks/2026-09-01-g2-foreign-listing.md](benchmarks/2026-09-01-g2-foreign-listing.md)).
      `excmp/slt.py` parses the pinned grammar, `engine.list_any()` is the
      foreign-capable twin of `list_archive()`, and `extract_selected()` pulls
      single members out of either kind. **38,496 entries listed across 19 real
      archives in 21.3 s.** 552 tests pass (was 469).
      **Five things the implementation corrected against the plan:**
      1. **The dummy `-p` was fixing a bug that had already shipped, not
         hardening a new path.** `_extract_foreign()` passed no `-p` at all, so
         an encrypted archive dropped on the Extract tab froze the running app
         on a prompt with nowhere to appear. Measured: **still running after
         8.0 s** without the guard, **exit 2 in 0.22 s** with it. Four of the
         nineteen archives in the real corpus have encrypted headers, so this
         was reachable by dropping a file the user already owns.
      2. **`communicate()` hides the hang.** The first measurement showed no
         block, because `subprocess.communicate()` closes stdin and hands
         7-Zip an EOF a real parent never sends. Reproducing it needs stdin
         held open. A timeout alone is not enough either — the deadline can
         only be enforced from a watchdog thread, since a tool blocked on a
         prompt never returns from the read loop to be checked.
      3. **`list_archive()` had to stay `.excmp`-only.** Widening it in place
         looked obvious and would have put a `7z.exe` launch on the GUI thread
         for every dropped file, because `ExtractTab._suggest_destination()`
         calls it synchronously on every drop. The `extract`/`extract_any`
         split already existed for a different reason and turned out to solve
         this one too.
      4. **`.msi` is not one format, and the difference is 20x.** 7-Zip reports
         `cab` for some and `compound` for others; a 371 MB `compound` MSI took
         **7.14 s** to list against 0.27 s for a 20 MB `cab` one. Seven seconds
         on the GUI thread is a freeze, which is what makes the worker thread
         load-bearing rather than tidy.
      5. **A packed size of 0 is a lie.** 7-Zip leaves `Packed Size` *empty*
         for every member of a solid block after the first, so `int` could only
         say "0 bytes" about files that had no individual figure. Carried as
         `int | None` — the same "a number that could mean two things needs a
         companion" lesson as `ledger_backed`. Caught by looking at the output,
         not by a test.
      **Deliberately not done:** an in-app archive *browser* tab (that is I2);
      this is the listing surfaced on the Extract tab where the archive is
      already chosen. Original item:
      **Archive browser / `excmp list`** — parse `7z l -slt` for foreign archives;
      for `.excmp` the manifest read is FREE and shows size + SHA-256 + route +
      *reason* per file. **`-slt` parser grammar now fully pinned**
      ([17 §4](research/17-source-study-peazip.md), [19 §6](research/19-source-study-7zip.md)):
      records are blank-line-separated `key = value` blocks after the
      `----------` line; **accept empty RHS** (`CRC =`); `--` opens archive
      blocks, `----` separates nested layers; field vocabulary = 7z's
      `kPropIdToName[]`; flag `Encrypted=+` / `Method` containing `AES`. **Always
      pass a dummy `-p` on list/test** so an encrypted archive errors instead of
      hanging on the interactive prompt (PeaZip's essential trick). Stream-parse
      with a row cap + "partial/flat" fallback (PeaZip caps at 0.5 M rows /
      64-192 MB stdout — huge archives are slow). Selective extract: `stored/`
      entries are instant zip reads; payload members get an honest "this archive
      is solid — one file replays the whole chain" warning first. Engine: additive
      `list_archive()` + `extract_selected()`
- [x] G3. ✅ **DONE 2026-09-02** — split volumes (`excmp/volumes.py`,
      `compress --split 100m`, and `extract` auto-joins when handed a `.001`).
      Pure-Python chunking as planned: parts are `<archive>.001`, `.002`, …,
      zero-padded so a lexical sort *is* the join order, capped at 999 because
      `.1000` would sort before `.101` and silently reorder the archive. The
      container is untouched — join first, then the ordinary reader runs — so
      a split archive is not a second format to reason about, and the split
      happens only **after** the D9 gate has published, because splitting an
      unverified archive just produces several unverified files.
      Per-part SHA-256 goes in a `.sha256` sidecar in `sha256sum` layout. It is
      a convenience, not a correctness requirement: joining works without it,
      and it exists so a failed transfer can name *which* part to re-fetch.
      Verified end-to-end: 22.5 MB of executables split into 2 volumes, whole
      archive deleted, rejoined from the parts alone — **32/32 byte-identical**.
      **Two bugs found while building it.** (1) `part_paths` originally stopped
      at the first gap, so a missing middle volume looked identical to a set
      that simply ended there and we would have joined a truncated archive; it
      now scans to the highest number present and names the hole. (2) **The G6
      sidecar had never been checkable with `sha256sum -c`** — `write_text`
      emits CRLF on Windows, so the trailing `
` became part of the filename
      and every line failed with "No such file or directory". A feature whose
      entire purpose was that one command, shipped broken. Both sidecars now
      pass `newline="
"`, with a test asserting no CRLF.
- [x] G4. ✅ **DONE 2026-09-02** — `compress --format 7z|zip` writes a plain
      archive with no container (`engine.compress_standard`). Verified for real:
      a `.zip` opened by Python's own `zipfile` (15 entries, `testzip()` clean)
      and a `.7z` that `7z t` accepts, 75.22% on executables.
      **It reuses `SevenZipStage`** rather than reimplementing anything, so the
      output path staying last, the password redaction and the progress parsing
      all come free; only the container type differs. That needed a real
      `archive_type` parameter — appending `-tzip` to `extra_args` beside the
      baked-in `-t7z` makes 7-Zip exit 7 with "Multiple instances for switch",
      and `-mqs`/`-mf` are 7z-format concepts that make it refuse a zip outright
      with "The parameter is incorrect", so both are now gated on the type.
      **The honesty is the feature.** A standard archive has no ledger, so
      nothing can re-verify it later — but it is still extracted and hashed
      against the originals *before* publication, exactly like the `.excmp`
      path, and nothing is written if that fails. `StandardResult.has_ledger`
      and `.note` exist so the caller says which half of the guarantee it has
      rather than implying both.
- [x] G5. ✅ **DONE 2026-09-03** — `excmp/convert.py` and `excmp convert`.
      Extracts any archive 7-Zip can open, analyses the *contents*, runs the
      pipeline, and reports. Measured on a real 8.9 MB zip of executables:
      **8.5 MB → 5.5 MB, 35.2% smaller**, source untouched.
      The signature part is the verdict. Recompressing archives is not new; our
      planner already knows *why* each file was stored, so a conversion that
      gained nothing says so in a sentence instead of leaving two numbers to
      compare. Reasons collapse by cause ("31 files: already compressed")
      rather than listing every file.
      **The source archive is never touched** — not moved, not deleted, not on
      success. The staging copy is the size of the whole archive and is removed
      in a `finally`, because leaving it would cost the user that space twice.
      **One thing measuring corrected:** a 940-byte zip converts *larger*,
      because the per-file SHA-256 ledger is fixed overhead. The tool correctly
      says "no smaller, keep the original" — the first version of that test
      asserted an improvement and was wrong about small archives, not about the
      feature.
- [x] G6. ✅ **DONE** (shipped with `compress --sha256`; verified 2026-09-09).
      **Transport-integrity sidecar** — emit a `.sha256` for the container itself
      (and per split volume) + `excmp verify --transport`. This is the maintained
      equivalent of the one verification habit repack users already have
      (`fitgirl-bins.md5` + QuickSFV)
- [x] G7. ✅ **DONE 2026-09-11** — `excmp extract --low-memory`, and the
      lever was never the dictionary.
      Numbers: [benchmarks/2026-09-11](benchmarks/2026-09-11-ram-and-lolz.md).
      **Two thirds of this item was not available to an extractor.** The LZMA2
      dictionary is fixed by whoever *created* the archive and the zstd window
      comes out of the frame header (K4's read ceiling) - neither is the
      extractor's to choose. The decoder thread count is, and it is worth more
      than the other two would have been: **255 MiB with no switch, 71 MiB at
      `-mmt=1`, a 3.6x drop**, while `-mmt=2` and `-mmt=4` both measured
      identical to no switch at all. Each LZMA2 decoder thread holds its own
      dictionary buffer, so the flag that looks like a speed knob is the
      memory knob.
      **And it measured *faster* here** - 2.5-2.7 s against 2.9-3.0 s, twice
      each, because two cores lose more to contention than they gain. One
      corpus on one machine, so it stays **opt-in**: generalising a speed
      result from a single sample is the mistake B8 caught in the estimator.
      Implemented on `StageContext.extract_threads` rather than as a stage
      argument, because the chain drives stages through the generic
      `Stage.extract(src, dst, ctx)`. 14 tests, one of which asserts the
      context value actually *reaches* the command line - F2's defect this
      same session was a parameter plumbed into a signature and no call site.
- [x] G8. ✅ **DONE** (shipped in UI v3 w3; the box was never ticked — verified
      2026-09-09, `excmp hash --json` works). Hash tool (`excmp hash`, stdlib hashlib) — cheap credibility, fits the brand
- [x] **G9. ✅ DONE 2026-09-02** — deduplicate stored files against the ledger.
      Measured in [benchmarks/2026-09-02](benchmarks/2026-09-02-b1-zpaqfranz.md):
      on the 49%-duplicate corpus, Extreme went **5.22% → 51.08% saved
      (+45.86 points)** and Insane **5.21% → 51.06%**, 5/5 byte-identical, and
      marginally *faster* because writing one copy of a 23.8 MB file beats
      writing two. For scale, B1 moved that same corpus by −0.02 points.
      **The duplicate-file win was never in the compressor** — it was in the
      store route, which copies identical high-entropy files verbatim where no
      deduplicator can see them.
      Implementation: `write_container` groups stored entries by the SHA-256
      the ledger already carries, writes the first, and gives the rest a
      `same_as` pointer; `extract_stored` gains a second pass that reads the
      source **from the zip** (not from disk, so selective extract still
      works) and writes every duplicate out in full. `verify_restore` needed
      **no change at all** — it re-hashes the restored file on disk, which is
      exactly what makes this safe.
      Four hostile cases are refused and tested: a `same_as` cycle, a chain of
      more than one hop, a pointer outside the ledger, and a pointer whose
      ledger hash or size disagrees with the target's. Chains are refused
      rather than bounded, which is what makes a cycle impossible instead of
      merely survivable. A file with an empty `sha256` is never deduplicated:
      "we do not know" is not a statement about equality.

**Explicitly skipped, decision recorded:** file manager (dilutes the drop→analyze→queue
identity), password manager (liability), secure delete (ineffective on SSDs — would
contradict our honesty brand), RAR *creation* (legally impossible), update-in-place
(wrong for a solid container — "repack to update").

## Phase H — Installer-style output (the FitGirl-shaped feature)

"Share a self-installing archive." Design: [research/09](research/09-fitgirl-installer-and-comparison.md).

- [ ] H1. **THE design rule, now source-confirmed AND made precise**
      ([16 §2](research/16-source-study-innosetup.md)): a byte-identical stub is
      achievable with stock Inno, but **only** as *one frozen universal script →
      compile once in CI → sign once → cache the canonical `setup.exe` → ship
      identical bytes forever*. Inno's exe **always embeds the full script state**
      (AppName, `[Files]`, compiled `[Code]`), and **recompiles are NOT
      guaranteed to hash identically** (resource-section rewrite is
      OS-build-dependent; LZMA2 file chunks auto-thread by machine) — so do NOT
      rely on per-archive recompiles. ALL per-archive variability lives in
      `{src}` sidecars read at runtime via `[Code]` (`AppName={code:…}` needs
      `DisableStartupPrompt=yes`; all `[Files]` marked `external`). Never append
      per-archive bytes to the signed exe (SetupLdr tolerates trailing junk but
      Authenticode does not). SmartScreen reputation is per-file-hash — a
      uniquely-generated unsigned installer is flagged **forever**. This is
      exactly why FitGirl ships `setup.exe + fg-*.bin`
- [ ] H1b. **(new)** Payload integrity via Inno's **ISSig** system
      ([16 §10](research/16-source-study-innosetup.md)): `[ISSigKeys]` embeds only
      a **public key** (constant across archives ⇒ H1-safe), and the `issigverify`
      file flag verifies `.issig` sidecars at install time — cryptographic
      tamper-proofing with **zero per-archive bytes in the exe**. Our packer emits
      the `.issig` sidecars
- [ ] H2. Inno Setup wrapper: generate `.iss` from a template, compile with `ISCC.exe`
      (mirror studied **7.1-dev**; **7.0.x** is the current stable line — pick the
      x64 stub for HE-ASLR + big dictionaries). License is permissive and
      OSI-clean in substance: it explicitly permits using ISCC, redistributing
      generated installers commercially, and redistributing the (untouched)
      compiler in our tool-downloader — **attribution optional**
      ([16 §1](research/16-source-study-innosetup.md)). Do NOT binary-patch the
      stub (ISCC ECDSA-verifies its own stubs and will refuse — brand via
      compile-time directives only)
- [ ] H3. Progress handoff ([16 §4](research/16-source-study-innosetup.md)):
      simplest path is `Exec(ewNoWait)` launch of our extractor + a `[Code]`
      polling loop that reads a progress file (`LoadStringFromFile`) and drives
      `WizardForm.ProgressGauge` / `CreateOutputProgressPage.SetProgress`
      (`SetProgress` pumps the message loop, so the UI stays live). The ISDone-
      style `external 'f@files:dll'` DLL route stays as an upgrade path — and
      `{src}\helper.dll` imports work via `ExpandConst`, so our DLL can sit next
      to the exe, not embedded
- [ ] H4. **Preflight checks learned from ISDone's error taxonomy** (the four causes
      that generate every "unarc.dll error -1" forum thread): non-Latin characters in
      the path, insufficient free disk (Precomp inflation), missing optional volume
      (proceed and report, don't hard-fail like they do), antivirus warning
- [ ] H5. **Chain constraint**: installer output only for redistributable profiles
      (7-Zip LGPL, zstd BSD, Precomp Apache-2.0). SREP/lolz chains excluded (SREP is
      dropped from all plans entirely — doc 20 §4; zpaqfranz + zstd --long replace it)
- [ ] H6. Optional-component payload volumes (languages/videos as named optional
      volumes recorded in the manifest) — the legit half of their selective-download
      trick. Effort L, post-v1

## Phase I — UI v2

Full plan with effort estimates: [research/11](research/11-ui-v2-plan.md).

- [x] I1. ✅ **DONE** (`gui/widgets/settings_tab.py` + `gui/prefs.py`; verified
      2026-09-09). **Settings page + `QSettings` persistence** — the app currently persists
      **nothing** (no QSettings anywhere in the repo): theme resets to dark every
      launch, advanced options reset. Ship theme (+ follow-system via Qt 6.5
      `QStyleHints.colorScheme()` — the free way to feel modern without GPLv3
      Fluent-Widgets), language, default output/temp dirs, **tool-path overrides**
      (unblocks every user whose tools aren't in `C:\Program Files`), remembered preset
- [x] I2. ✅ **DONE DIFFERENTLY, and deliberately** — the listing lives *inside*
      the Extract tab (`extract_tab.py` calls `list_archive` and renders it), not
      in a tab of its own, because "four top-level tabs is the ceiling" is a
      standing decision and the tabs are Compress/Extract/Settings/Activity.
      Verified 2026-09-09. Original item: **Archive browser tab** (pairs with G2) — also a trust feature: it makes the
      SHA-256 ledger visible
- [x] I3. ✅ **DONE 2026-09-03** — persisted history + queue reordering.
      `clear_finished()` used to delete the record forever; finished jobs now
      move to `gui/history.py` (bounded JSON, newest first) and "Compress
      again" re-queues with the *settings*, not only the paths. Failed jobs are
      kept with their reason — a history that drops the failures flatters the
      tool. **No secret is ever written**: `HistoryEntry` has no field for a
      password, which is the only reliable way to be sure. Queue gained
      `order()` / `move_job()` / `run_next()`.
      **One correction the implementation forced:** it began as a fifth tab,
      and the fit test's own docstring stopped that — "four destinations is
      exactly WinUI's ceiling for top navigation, which is why the tab bar was
      chosen over a nav rail". History lives *inside* Activity behind a
      disclosure instead, and the ceiling holds.
- [x] I4. ✅ **ALREADY DONE** (wave 3c, `_maybe_first_run` on the W2-9 Banner) — verified 2026-09-03, not re-implemented. Original item:
- [ ] ~~I4.~~ First-run onboarding card: what was found, what each missing tool unlocks,
      links to downloads. Upgrades to one-click when E1 lands — don't block on it
- [ ] I5. Explorer context menu, Win10 path: HKCU registry verbs (no admin) + argv
      intake in `gui/app.py`. Win11 top-level cascade needs signed sparse MSIX →
      defer to post-E4. **NanaZip is the reference** ([14 §2](research/14-source-study-nanazip.md)):
      the complete IExplorerCommand/IEnumExplorerCommand pattern + the exact
      AppxManifest (desktop4/desktop5/desktop10 `FileExplorerContextMenus` verbs
      + `com:SurrogateServer` class + `runFullTrust`, with the `0000` verb-Id
      prefix trick). Use the **thin-launcher** shape: the shell DLL only
      enumerates commands and spawns our GUI exe with CLI args — never extract
      in-process (Explorer STA isolation). Define the CLI contract now
      (S-effort); the C++ COM DLL comes with the MSIX later. UX heuristics worth
      copying: extension-exclusion list before showing Extract, smart-extract
      subfolder only when the archive root isn't a single folder, multi-part-
      aware folder naming
- [x] I6. ✅ **DONE 2026-09-20**, branch `phase-i6-measured-presets` (awaiting
      review). Full write-up:
      [benchmarks/2026-09-20-i6](benchmarks/2026-09-20-i6-measured-presets.md).
      A **Measure presets** button runs every distinct chain on a ≤100 MB
      sample as real queue jobs and prints the measured saving onto the cards
      as each one lands. New `excmp/sample.py` (Qt-free) and
      `gui/compare_run.py`; `tools/bench.py` gained `--sample` so the CLI and
      the GUI measure the same bytes by the same rule.
      **Three things the implementation had to settle that the item did not.**
      (1) **The sample is the measurement.** Whole files only, every category
      represented, proportional to bytes, spread across the size distribution.
      (2) **Rule 3 cannot always be honoured** — the real Programs corpus keeps
      42.4% of its bytes in `.zip` files each larger than the whole cap, so the
      sample carries 3.9% of them. That is *reported*
      (`Sample.under_represented`) and it bounds the claim: a measured
      comparison **ranks the profiles on identical bytes, it does not forecast
      the job**. A test asserts a measurement never moves the recommendation.
      (3) The first sampler took **2 of 12** Silesia files and dropped a whole
      category; reserving one file per category before the proportional pass
      takes **3 of 12 at 94% of the cap**. Found by running it, not by reading it.
      **Two defects found by rendering**, both invisible to the suite: a row
      showing `about 225.9 KB` beside `61% measured` (two numbers about one job
      that disagreed), and then a column titled "Estimated size" carrying a
      measured one. The size column is now measured *only* when the sample was
      the whole input, and the header goes to "Size" when it is.
- [~] I7. ❌ **WON'T DO — decided 2026-09-10 by the owner. Do not build this,
      and do not re-open it in a later session.**
      Original item: i18n pipeline (`pyside6-lupdate`/`lrelease` + first `.ts` +
      Language combo), on the grounds that it was "the cheapest remaining step".
      **What the check found before the decision:** the *plumbing* is real —
      `gui/app.py:18` `_install_translator` already builds a `QTranslator` and
      reads `QLocale.system().name()`, and **344** strings across `gui/` are
      already wrapped in `self.tr()`. What does **not** exist is a single
      translation: no `.ts`, no `.qm`, no `translations/` directory anywhere in
      the tree. So the feature was not "nearly done", it was "nothing a user
      could pick", and the owner's call was to stop rather than finish it.
      **The existing loader stays.** It is ~10 lines, it is already shipped, it
      is a no-op with no `.qm` files present, and deleting working code to
      express a decision is its own risk. `self.tr()` also stays everywhere it
      already is - removing 344 call sites would be a large diff with no
      benefit. Neither is a foothold for re-opening this.
- [x] I8. ✅ **DONE 2026-09-03** — `gui/widgets/treemap.py` via squarify
      (Apache-2.0). Behind the same disclosure as the breakdown bar, which it
      complements rather than replaces: a bar 2% wide is invisible whatever it
      is labelled. Never colour alone — every block is labelled where it fits,
      the legend returns **selectable text** (category, share, size) rather
      than being painted, and the whole thing is available as one sentence for
      a screen reader. Slivers below 2% collapse into an honest "other".
- [x] I9. ✅ **ALREADY DONE** (wave 2a) — verified 2026-09-03: `grep -c 'QMessageBox('` over `gui/` returns zero constructions, and a test parses the AST to keep it that way. Original item:
- [ ] ~~I9.~~ Fix the one design-rule violation: `closeEvent`'s modal `QMessageBox` →
      inline confirm banner
- [x] I10. 🟡 **PARTLY DONE 2026-09-03** — Ctrl+K palette shipped
      (`gui/widgets/palette.py`), built as a *filter over* `MainWindow.actions`
      rather than a second list, so a new action appears the moment it is
      registered; a test asserts every enabled action is reachable. Subsequence
      matching, so "oa" finds "Open archive". **Still open from this item:**
      settings search fed by the same registry, drag-out extract, and the jump
      list.
- [x] J1. **Sample-based size estimator** (`excmp/estimate.py`, engine-side, Qt-free).
      Do not use a static ratio table — **measure**. The analyzer already reads up
      to 3×1 MiB per file for entropy (`analyzer.sample_entropy`); compress those
      same samples in-process with `zstandard` at a low level to get a *measured*
      ratio per file, then scale to the target profile. This is the same
      poor-man's-detector idea as FreeArc's `-ma` content probe
      ([21 §3.5](research/21-source-study-synthesis.md)), reused for prediction.
      Rules: stored-route files contribute their size at **exactly 1.0** (they are
      copied verbatim — that part of the estimate is not a guess); return a
      **range** (low/expected/high), never a single false-precision number; cache
      per `(path, size, mtime)` so re-analysis is instant. Cost budget: ≤1 s for a
      few hundred files.
- [x] J2. **Time estimator** — must be a **two-rate model**, because a single
      MB/s figure is actively misleading: 81% of the real corpus was *stored*
      (disk-bound) and only 141 MiB was *piped* (CPU-bound). Blending them gave
      "11.6 MB/s" which would mispredict badly on any other mix.
      `time ≈ stored_bytes / io_rate + piped_bytes / codec_rate[profile] × core_scale`.
      Measured 2-core starting points, piped-only: **normal ≈ 2.5 MiB/s, extreme
      ≈ 0.9 MiB/s**; `io_rate` ≈ 100 MB/s and is capped by the *source* disk (the
      benchmark corpus lived on an external HDD). Note the rate is content-
      dependent — the 2026-07-18 synthetic run hit ~6.5 MB/s on compressible data
      vs 2.5 here — so **ranges are mandatory** and J7 exists to fix it properly.
      Round honestly ("~1 min", "~3 min", "2-4 hours"), never "163 s".
- [x] J3. **Profile comparison table** (the headline UI). All four profiles as rows:
      estimated size, estimated time, % saved, recommended row highlighted with the
      existing `recommend_profile()` reason. Plus a **"not worth it" flag**: when a
      slower profile costs ≥2× the time of a cheaper one for <1 percentage point
      more saving, say so on the row. Reuses `AnalysisSummary`; needs a `Plan` per
      profile (cheap — `planner.plan()` is pure and already runs per profile for
      `reference_plan`).
- [x] J4. **Free-disk preflight for compression.** D0 shipped this for *extraction*
      (`engine._check_free_space`) — generalize it. Compression needs
      `output_estimate + peak temp`, and temp is the dangerous one: Precomp
      inflates 2-5× mid-pipeline ([research/10](research/10-security-and-integrity.md) C-3).
      Warn before starting, with the number. **Shipped with two thresholds, which
      the plan did not anticipate:** extraction can hard-fail on an exact figure
      because the manifest declares every size, but compression cannot — the output
      is an estimate and Precomp's inflation is data-dependent. So there is an
      impossible *floor* that refuses and a pessimistic *peak* that only warns. A
      preflight that refuses jobs which would have succeeded gets switched off, and
      then it protects nobody. Needs are also **grouped by volume** (`st_dev`),
      since temp and output are usually the same disk and then compete for the same
      bytes — the extraction check looks at one directory only.
- [x] J5. ✅ **DONE 2026-09-03** — `gui/prefs.py`. The profile chosen for each
      dominant content type is remembered in QSettings and offered on the next
      folder of the same shape. **It suggests; it never overrides** — a
      remembered choice that silently outranked the analyser would make the
      recommendation unpredictable, which is worse than an occasional extra
      click. Once the user picks for themselves, `_profile_touched` stops the
      re-suggestion for that drop, and `select()` defaults to `emit=False` so
      offering a profile is not mistaken for choosing one. A hand-edited
      QSettings value is discarded rather than trusted: it costs the
      preference, never the app. The I1 dependency was already satisfied —
      QSettings landed with wave 3c.
- [x] J6. ✅ **DONE 2026-09-03** — `suggest.long_job_warning()`, shown on the
      existing inline banner. Past 45 minutes the estimate is stated in words
      somebody can act on: *"about 3 hours on this machine - worth starting
      before you step away, or leaving to run overnight."*
      The comparison table already made the *relative* cost visible, which was
      J3's job; this makes the absolute one visible, because "about 3 hours"
      means something to a person that "0.842 MB/s" does not. Phrased in
      minutes below 90, hours above.
      `ComparisonRow` gained `time_seconds` so the decision is made on the
      number rather than by re-parsing the formatted string - a formatting bug
      waiting to happen otherwise. **Inline, never a modal**: a test parses
      `mainwindow.py` and fails on any `QMessageBox` call, so the I9 rule
      cannot be broken again by accident.
- [x] J7. ✅ **DONE 2026-09-03** — `excmp/calibrate.py`. Every finished job
      records its real `piped_bytes / elapsed` **per resolved chain**, and
      future estimates blend that with the shipped defaults as the cold-start
      prior (EMA, alpha 0.25). Qt-free, so the CLI and the GUI feed one JSON
      store and `excmp/` keeps its independence from Qt.
      **Measured convergence** on a machine 2.5x slower than the shipped
      constant: a 500 MB job is predicted at 2.6 min cold, 3.0 after one job,
      5.9 after ten, and **6.4 after twenty-five against a true 6.4** —
      without ever lurching, which is the property the EMA exists for.
      Also learns `codec_factor`, which is the only real fix for the J1 note-3
      blind spot: no cheap probe can predict what Precomp will find, so
      watching what it actually achieved is the only thing that can.
      Three guards, each about not making the estimate *worse*: samples under
      8 MiB are ignored (they measure process startup, not throughput), a rate
      more than 100x from the prior is dropped as a clock artefact or a cached
      read, and a corrupt or unwritable store costs the learned rates and
      nothing else.
      **One thing the implementation corrected:** the first version replaced
      the rate outright on the first sample. That is not what "cold-start
      prior" means - it throws away everything the defaults encode on the
      strength of one job. It now blends from sample one.
- [x] J8. **Acceptance test — the estimator must be scored, not trusted.**
      Backtest J1/J2 against both recorded benchmark runs
      (`docs/benchmarks/2026-07-18-*`, `2026-08-01-*`): predicted size within
      ±10% and predicted time within ±40% of measured, as a real pytest. An
      estimator nobody scored is a guess with a progress bar. Also property-test
      that the store-route portion of the size estimate is *exact*.
      **Shipped, with three corrections to the plan.** (a) The **2026-07-18 run
      cannot be backtested at all**: its corpus was `%TEMP%\excmp-sample` and the
      doc records no file list, so nothing is reproducible from it. It survives
      only as evidence of the rate spread. Its lesson is now enforced —
      `2026-08-01-estimator-backtest.md` records exact file names *and* byte sizes,
      and the test voids itself if a size no longer matches. (b) A backtest against
      2026-08-01 is **in-sample** (the factors were fitted on it), so it is a
      regression guard, not validation; the genuine out-of-sample evidence is a
      second 163 MB corpus predicted before it was compressed. (c) The ±40% time
      gate is met for zstd/7-Zip chains and is **unachievable for Precomp chains**
      (two regimes, 3.1× apart) — gated at ±80% with the reason written down.
      Range containment is asserted for every chain, because a range that excludes
      the truth is worse than no range.

**Explicitly out of scope for J** (already covered elsewhere): I6 "compare presets
by actually running them on a ≤100 MB sample" is the *measurement* upgrade to J3's
*estimate* — keep them separate and ship J3 first.

## Recommended extras (post-v1 ideas)

- Folder size treemap (WinDirStat-style) on the analysis screen
- "Compare profiles on a sample" button — runs `tools/bench.py` on 100 MB of the
  input and shows the real trade-off before committing hours
- Solid-archive chunking for resumable multi-hundred-GB jobs + `.excmp` split volumes
- zstd `--train` dictionaries for many-small-similar-file corpora
- Self-extracting `.exe` output option
- Linux/macOS support (engine is already portable; stages need path candidates)

## Suggested order & effort (2-core laptop reality)

| Order | Phase | Rough effort | Why here |
|---|---|---|---|
| ~~1~~ | ~~A (GUI)~~ | ✅ done | made every later feature visible and testable |
| ~~2~~ | ~~D0 (security hotfix)~~ | ✅ done | an exploitable reader bug outranked every feature |
| ~~3a~~ | ~~J1-J4 + J8 (estimator + comparison table + preflight + backtest)~~ | ✅ done | estimates are live and scored against two real corpora |
| ~~UI-1~~ | ~~UI v3 wave 1 (screen fit, merged chooser, action bar, registry, WCAG, fit gate)~~ | ✅ done, merged | all 13 items of research/23 §7; the 1366×768 gate pins the fix |
| ~~UI-2a~~ | ~~UI v3 wave 2a (Activity tab + status strip, compact results, queue density, scan progress, Banner/I9)~~ | ✅ done, merged | W2-1/3/7/8/9. Populated Compress page 869→748px, last `QMessageBox` gone, scan silence 4.7s→0.3s on the real HDD tree. Also fixed the tests' missing `QT_QPA_FONTDIR` — every prior height gate had been measuring tofu |
| ~~UI-2b~~ | ~~UI v3 wave 2b (compaction, token sweep, Fluent SVG icons, dark title bar, pending-items list)~~ | ✅ done, merged | W2-4/5/6/10 + intake chip, analysis-card collapse, chooser diet. Populated page 748→415px; the empty page fits 150% for the first time. ≤300px is unreachable without dropping a profile row, the analysis card, or the 32px touch floor — recorded as a strict xfail, not silently dropped |
| ~~4~~ | ~~B11 + D9 (drop SREP; make the self-test replay the chain)~~ | ✅ done | the chain is SREP-free and nothing publishes without a verified restore — four clean Extreme round-trips on real corpora |
| ~~UI-3a~~ | ~~UI v3 wave 3a (verify verb + button, `excmp hash`)~~ | ✅ done, merged | The D9 gate became public: same code path, three callers. Catches a single flipped byte in a 721 MB archive and names the file |
| ~~UI-3b~~ | ~~UI v3 wave 3b (G1 foreign archives, I2-lite listing)~~ | ✅ done, merged | Opens zip/7z/rar/iso/…, and shows the ledger — size, SHA-256, route and *why stored* — without extracting. `ledger_backed` keeps the verified restore distinguishable from the best-effort one |
| ~~UI-3c~~ | ~~UI v3 wave 3c (`.sha256` sidecar, Settings + persistence, autosubfolder, first-run notice)~~ | ✅ done, merged | Sidecar is **opt-in and remembered** (decided 2026-08-07). The app persists preferences for the first time — it kept only window geometry before. Settings also hosts the tool inventory the status strip elides |
| ~~UI-4~~ | ~~Level/dict knobs + RAM column + Parameters line~~ | ✅ done | `excmp/ram.py` implements 7-Zip's own peak-RAM formula (doc 19 §3), clamped to the input the way `reduceSize` does. B9's cap drives the dictionary menu; the Parameters line is an allowlist |
| ~~G2~~ | ~~Foreign archive listing (`7z l -slt`) + password-on-demand + selective extract~~ | ✅ done | 38,496 entries across 19 real archives in 21.3 s. Also fixed a shipped hang: `_extract_foreign` passed no `-p`, so an encrypted archive froze the running app — four of the nineteen real archives would have triggered it |
| **3b** | **J5-J7 (per-type memory, long-job confirm, self-calibration)** | **1 session** | **finishes Phase J** |
| 6 | D1-D3, D7 (QA core + CI) | 1-2 sessions | locks in the integrity guarantee before adding stages |
| 7 | B1-B3 + B9-B10 (zpaqfranz, JPEG/PNG, RAM caps) | 1-2 sessions | completes Insane; B9 is one-line arg changes with real payoff |
| 8 | E1-E2 (downloader + notices) | 1 session | unblocks every remaining specialist (par2, xtool, FFmpeg) |
| **9** | **B6 (xtool + Oodle) + B8 (re-benchmark)** | **3-4 sessions** | **the real FitGirl gap on modern AAA games — the single biggest competitive deficit.** Moved up from 11 on 2026-09-01: the "needs E1 first" dependency is soft (tools degrade gracefully already), and nothing justifies shipping encryption and settings polish ahead of the one thing we measurably lose at. **Read the audit note on B6 before starting — the DLL-bootstrap design flaw must be fixed first or the archives only restore on the machine that made them.** B8 is paired because nothing currently validates the 5-15% vs 50-70% claim; both figures are `(est.)` in doc 09 |
| 10 | I1-I2 (settings/persistence + archive browser) | 1-2 sessions | I1 already shipped in wave 3c; this is the browser tab |
| 11 | F1-F3 (encryption + recovery records) | 2-3 sessions | table-stakes "secure"; F3 is the WinRAR feature nobody OSS has |
| 12 | C (video shrink) | 2-3 sessions | biggest user-visible win on media, but hours of CPU per job |
| 13 | G3-G8, I3-I8, E3-E4 | as needed | parity + polish + release |
| 14 | H (installer output) | 2-3 sessions | flagship differentiator, but needs E4 signing to be usable |

Two ordering principles behind this: **security before features** (D0 first — we
found a real bug), and **cheap identity wins early** (G1-G2 are S-sized and change
what the app *is*). Phase H sits last on purpose: an unsigned generated installer is
SmartScreen-flagged forever, so it depends on E4.

---

## Answering the two questions that drove this research round

**"Is ours more powerful and more highly compressible than the FitGirl method?"**
Honest, evidence-based answer ([research/09](research/09-fitgirl-installer-and-comparison.md)):
- **Old zlib-era games**: we're already in their league (72.4% measured on our
  synthetic corpus vs their 60-75% class).
- **Modern Oodle/zstd AAA games**: we lose badly today — ~5-15% vs their 50-70% —
  because Precomp can't open Oodle streams. B6 (xtool + the game's own oo2core DLL)
  closes most of it; the remainder is the lolz codec (~5-10%, no legal path) and
  per-game hand tuning (structurally unavailable to an automatic tool).
- **Everything that isn't a game**: we're simply better — they don't route by type.
- **Trust and safety**: we win everywhere. SHA-256 per-file ledger + chain replay vs
  CRC32 + an optional MD5 batch file; a maintained legal stack vs 2014-era abandoned
  DLLs (ISDone/unarc); inputs never modified and bounded RAM vs "set a 16 GB pagefile
  and disable your antivirus."

So: **not uniformly more compressible — more *powerful* in scope and far more
trustworthy.** They optimize one number (download size of one hand-tuned game); we
optimize a contract (anything in → smallest honest size → verified bit-exact restore).

**"Can we include the Inno Setup / installer things they use?"** Yes — Phase H, with
one hard design rule (H1): the generated `setup.exe` must be byte-identical for every
user and signed once, because SmartScreen reputation is per-file-hash. That is
precisely why FitGirl ships `setup.exe + fg-*.bin` rather than one big exe.
