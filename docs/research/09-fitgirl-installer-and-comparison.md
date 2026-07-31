# 09 — FitGirl deep-dive: the installer side, RAZOR/lolz status, and the honest head-to-head (verified 2026-07-31)

> Complements doc 02 (which covered the compression pipeline). This doc covers what
> we had NOT researched: how a repack actually *installs*, the 2026 status of RAZOR /
> lolz / xtool, what really makes repacks small, and — the question that matters —
> **are we more powerful than the FitGirl method?** Answer: honest comparison below.
>
> **⚠ Source-study update (2026-07-31):** this doc's web-verified claims about
> xtool, Inno Setup, and the CLS/ISDone plumbing have since been verified (and in
> places sharpened) from the **actual source code** — see docs 13 (xtool — incl.
> the exact B6 command lines and the oo2core-DLL-pinning requirement), 16 (Inno
> Setup — the byte-identical-stub verdict) and 18 §6 (unarc/CLS, the exact ABI
> ISDone drives). Corrections flagged inline as **[SOURCE-STUDY …]**.

## 1. How a FitGirl repack installs

**Inno Setup status (2026).** Current stable **7.0.2 (2026-07-13)**. License is still
the classic permissive one — generated installers may be redistributed for any
purpose (retain notices). Since 6.5.0 JR Software *requests* (not requires) a paid
license from commercial users (>$5k/yr revenue) — irrelevant for a free MIT project;
worth a THIRD-PARTY-NOTICES line. Inno 7 relevant additions: 64-bit installers with
LZMA2 dictionaries up to 3.8 GB, long-path support; since 6.5: native `[Files]`
archive extraction (zip, multi-volume, password) + download support + ISSig signature
verification.

**The glue stack** (FitGirl's own FAQ: "mostly FreeArc for compression and Inno Setup
as an installer"):
- **ISDone.dll** (v0.6 final, **2014**, by ProFrager — same author as lolz): Inno
  extension DLL called from `[Code]`; exports `ISArcExtract`, `ISSrepExtract`,
  `ISPrecompExtract`, xdelta handlers; unifies everything onto one progress bar.
- **unarc.dll** — FreeArc's decompression library (source of the infamous
  "unarc.dll returned an error code: -1" genre).
- **CLS-\*.dll plugins** — FreeArc's compression-library plugin API: `cls-srep.dll`,
  `cls-precomp.dll`, `cls-lolz.dll` dropped beside unarc.
- **run.exe** — FitGirl's parallel pipeline orchestrator (multi-core decompression).
- **xdelta** patching — near-duplicate files (localizations) stored as base + diff.

The whole stack is 2012–2014-era Delphi tied to dead FreeArc, maintained only by
forum patches. Every FitGirl install depends on abandoned closed binaries — this is
exactly the "pipeline described only by an installer script" problem our `.excmp`
manifest solves declaratively.

**Verification during install — weaker than ours on every layer:** optional user-run
MD5 batch file (QuickSFV) before install + CRC32-per-block inside FreeArc archives.
No per-file cryptographic ledger, no restore verification. Failures surface as
ISDone/unarc error codes; top documented causes: incomplete download, missing
optional .bin, **non-Latin characters in path/username**, antivirus interference.
(Those causes become explicit preflight checks in our installer-output design, §4.)

**Selective download.** Payload = external `fg-*.bin` archives (core + optional
language/video packs). Users skip optional .bins in the torrent client; installer
checkboxes map to archives. Missing optional + ticked component = the classic
ISArcExtract error (we can do better: proceed and report).

**Why installs take 30–120+ min.** The pipeline runs *in reverse* on the user's
machine: precompression reversal is *re-compression* (slow direction); SREP
reconstruction needs a big RAM window (their "limit to 2 GB RAM" option spills to
disk); plus LZMA/lolz decode + AV scanning ("can slow a fast installer for HOURS" —
her words). Documented spread: ~6 min on 16 threads vs ~24 min on 4 threads for one
lossless repack. On our 2-core i7-3540M class, AAA repacks are multi-hour — the same
honest expectation applies to any ExtremeCompressor installer output running the
extreme chain in reverse.

## 2. RAZOR status (2026): dead end, nothing adoptable

Christian Martelock's archiver: frozen since **v1.03.7 (2018-03-22)**; closed source;
distributed as a "DEMO/TEST version, non-commercial use only" — no OSI license, no
source, ever. Own `.rz` format; ROLZ-flavored LZ + pzlib precompression + SREP-style
dedup; dicts to 1023 MB. Effectively ≤2 threads by design; very slow compression
(~0.4 MB/s vs 1.65 MB/s for 7z in a krinkels test) with fast, low-RAM decompression.
Ratio ≈ 1.5–2 points better than 7z-max (41.96% vs 43.52% on the krinkels corpus).
**Verdict: legally unusable (non-commercial demo terms), technically frozen; zpaqfranz
+ big-dict LZMA2 covers the same class with maintenance and a license.**

## 3. lolz and xtool status (2026)

- **lolz (ProFrager)**: still a ghost — closed source, no license, no official
  distribution; binaries circulate only inside repack toolkits. ~5–10% better than
  LZMA with faster decode — which is why elite repacks use it, and why we accept a
  permanent ~5–10% final-codec deficit (partially recovered by zpaqfranz on
  dedup-heavy data). Permanently off the table.
- **xtool (Razor12911)**: GitHub repo MIT but **archived 2023-10** at v0.7.9;
  development continues on Patreon (**v0.9.5, 2026-03-21**, no stated license —
  treat Patreon builds as unpinnable binaries, never bundle). Capabilities:
  zlib/deflate universal scanner, lz4/lzo/zstd, **Oodle via the game's own
  `oo2core*.dll`**, fast-lzma2, flac/brunsli/jojpeg, depth mode, stream dedup, a
  **precompression database** (export/import of found stream offsets — the
  "per-game plugin" mechanism), and zstd-based patching. Roadmap B6's plan
  (detected-only, verified roundtrip, Oodle only via the game's own DLL) matches
  the verified facts.

## 4. What actually makes FitGirl repacks small (impact order)

1. **Precompression of engine-compressed assets** (the big one) — xtool/precomp
   decode weak zlib/Oodle/lz4 streams back to raw. Reference: a UE pak recompressed
   to 40.5% of original.
2. **Long-range dedup (SREP)** across the decoded data.
3. **Dedup across localizations + selective download** — xdelta diffs + optional
   .bins. The *download* shrinks even when the data wouldn't.
4. **Strong final codec** — lolz (≈5–10% over LZMA2) or big-dict LZMA.
5. **Per-game manual tuning** — hand-crafted method strings, game-specific xtool
   stream databases, hours of human iteration per title. Craft, not code — the least
   transferable part, structurally unavailable to a general automatic tool.
6. **Lossy variants where marked** — re-encoded video/audio, dropped hi-res packs.

Result class: AAA titles 30–70% smaller downloads, at the cost of multi-GB RAM,
30–120 min installs, and zero cryptographic verification.

## 5. The honest head-to-head

Verified anchors: our 72.4% saved on the synthetic zlib-game corpus; xtool UE pak →
40.5%; lolz ≈5–10% over LZMA; RAZOR ≈3–5% relative over 7z; FitGirl headline 30–70%.
Everything marked *est.* is extrapolation — running the real benchmark is B8.

| Scenario (same game folder) | FitGirl-class stack | Our current chain (precomp→srep→7z) | Our planned chain (+xtool, +zpaqfranz) |
|---|---|---|---|
| Older zlib-era game (UE3, most indies) | 60–75% saved (est.) | **50–70% (est., 72% measured on synthetic)** — genuinely close | 55–72% (est.) |
| Modern Oodle/zstd AAA game | 50–70% (est.) | **5–15% (est.)** — precomp can't open Oodle | 40–65% (est.) — gap narrows to lolz delta + tuning |
| Mixed personal data (docs/code/photos) | not their use case | comparable or better (routing + specialists) | better (zpaqfranz dedup + specialists) |
| Media (video/mp3) | store, or lossy variants | store losslessly + honest explanation | same; opt-in Shrink mode (Phase C) |

**Where we genuinely lose:** Oodle recompression until B6 lands (the single biggest
gap on post-2018 games — tens of percent); the lolz final codec (~5–10%, permanent,
no legal path); per-game manual tuning (structurally unavailable); lossy variants
(refused by policy — lossless-first).

**Where we genuinely win:** verification (SHA-256 per-file ledger + chain replay vs
CRC32 + optional MD5 .bat — their failure mode is a forum thread, ours is a loud
specific error); a maintained legal stack (their core DLLs are 2014-era abandonware);
generality (any file type, honest about incompressible data); safety (inputs never
modified, atomic outputs, bounded RAM vs "set a 16 GB pagefile and disable your
antivirus"); restore guarantee (an archival format contract, not a one-shot install).

**Bottom line:** on old zlib games we are already in their league; on modern AAA we
lose badly until xtool/B6 ships, then get close; on everything that isn't a game we
are simply better; and on trust/safety we win everywhere. FitGirl optimizes one
number (download size of one game, hand-tuned). We optimize the contract
"anything in → smallest honest size → bit-exact restore, verified."

## 6. Installer-style output ("share a self-installing archive") — design

**Recommended architecture: Inno Setup wrapper.** At output time, generate an `.iss`
from a template and compile with `ISCC.exe`:
- `[Files]`: our CLI extractor stub + the `.excmp` payload as **external sidecar
  .bin files** (FitGirl's own layout, for the SmartScreen reason below) + the
  redistributable tools the chain needs.
- `[Run]`/`[Code]`: run the extractor, poll progress lines into the Inno progress page.
- Preflight checks learned from ISDone's error taxonomy: path-charset (non-Latin),
  free-disk (precomp inflation), AV warning.
- Chain constraint: **installer output only for redistributable-chain profiles**
  (7-Zip LGPL, zstd BSD, Precomp Apache-2.0). SREP/lolz chains are excluded.
  **[SOURCE-STUDY ⚠ the "installer downloads SREP with user consent" fallback is
  retired — SREP was dropped from all plans (doc 20 §4 / doc 21 §5); zpaqfranz +
  zstd `--long` replace it, both redistributable]**

**The SmartScreen design rule (must be decided before building):** reputation is
per-file-hash; every user-generated unsigned setup.exe would be flagged forever.
Fix: the setup.exe binary must be **byte-identical for all users** — one prebuilt
stub, signed once via SignPath (E4); all per-archive variability lives in sidecar
.bin files + a manifest the stub reads. One hash accrues reputation. This is exactly
why FitGirl ships `setup.exe + fg-*.bin`. (EV's instant-reputation advantage was
removed by Microsoft in 2024 — OV is fine.)

**Overhead:** Inno stub ~1–2 MB; PyInstaller-based extractor realistically 15–40 MB —
acceptable for GB-class archives. A tiny native extract-only stub (C/Rust) is a
someday-refinement. 7z SFX (`-sfx`) remains a cheap alternative for single-stage
profiles only (no verification UI, console-grade UX).

**Legality: clean.** Inno permits redistribution of generated installers; our stub is
our MIT code; never embed SREP/lolz in anything we distribute.

## Sources (highlights)

- jrsoftware.org (license.txt, is7-whatsnew, DiskSpanning docs) · innosetup-announce
- krinkels.org (ISDone v0.6, RAZOR thread) · encode.su threads 2829/4000
- github.com/Razor12911/xtool (+releases, changes.txt, xtool-plugins) · Patreon v0.9.5 post
- fitgirlrepacks.org/faq + repacks-troubleshooting · innoextract (constexpr.org)
- learn.microsoft.com SmartScreen reputation model · digicert EV-reputation notes
- wiki.haskell.org FreeArc CLS API · github.com/CarldricGaming/Mini-Compressor
