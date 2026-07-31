# Game-repack compression technology (FitGirl/DODI class), state 2026

> **⚠ Source-study update (2026-07-31):** several claims below were corrected by
> the line-by-line source studies in docs 13-21 (read
> [21-source-study-synthesis.md](21-source-study-synthesis.md) first).
> Corrections are flagged inline as **[SOURCE-STUDY ⚠ …]**.

## How repacks achieve extreme ratios

The trick is never one magic codec — it is a **pipeline of specialized stages**:

1. **Precompression** — game assets are usually *already* compressed with weak codecs
   (zlib/deflate inside pak/asset files, lz4, zstd, Oodle Kraken in modern engines).
   Precompressors *decode those streams back to raw form* (recording how to re-create them
   bit-exactly), exposing redundancy the weak codec left behind.
2. **Long-range deduplication** — games repeat huge blocks (same textures in multiple paks,
   localized copies). SREP-style dedup with a multi-GB window removes these.
3. **Strong final codec** — LZMA2 at max settings, or the proprietary `lolz` codec in top
   repacks, squeezes what remains.
4. **Per-type routing** — audio recompressed losslessly (wav→FLAC-class), textures/media that
   are already entropy-coded get stored or lossy-recoded ("lossy repack" variants).

Typical result: a 60 GB game → 15–30 GB installer. Cost: install time explodes (the same
pipeline must run in reverse on the user's machine).

## Tool status (verified July 2026)

| Tool | Role | Status | Notes |
|---|---|---|---|
| Precomp (schnaader) | zlib/jpeg/gif precompression | Abandoned (~0.4.8, repo archived) | Works, but superseded by xtool for game use; slow, single-threaded in places |
| **xtool** (Razor12911) | Modern precompressor: zlib, reflate/preflate, png, lz4/lz4hc, lzo1x, zstd, **Oodle**, flac, packjpg, brunsli, jojpeg | Source on GitHub, no longer actively developed (v0.7.9 GitHub, v0.8.1 Patreon) | The de-facto repacker standard. Oodle recompression requires the game's own `oo2core*.dll` (Oodle SDK is proprietary — cannot be redistributed) |
| SREP | Long-range dedup | Abandoned freeware (FreeArc ecosystem), no OSI license | Works well; closed source; `zstd --long=31` and zpaq dedup are maintained alternatives. **[SOURCE-STUDY ⚠ SREP is now dropped from ALL our plans — verdict in doc 20 §4: zstd `--long=31`/7z big-dict cover ≤2 GB distances, zpaqfranz CDC dedup covers unlimited distance; lrzip also rejected (GPL + POSIX-only)]** |
| FreeArc | Archiver with per-type methods | **Dead since ~2016** | Still functional but unmaintained; format is a dead end for a new app |
| lolz | LZMA-class codec used in elite repacks | Closed, unofficial builds on forums | Not suitable to build on legally |
| RAZOR | Christian Martelock's archiver | Frozen (2017–2019 era) | Great ratio, closed source, single-threaded |
| **zpaqfranz** | Journaling dedup archiver (zpaq fork) | **Actively maintained** (v64.x, releases through 2026) | Built-in dedup + strong methods + integrity checks; **[SOURCE-STUDY ✓ license verified plain MIT, not "MIT-ish/GPL" — doc 20, studied at v64.8j]**; good modern replacement for SREP+archiver stages |
| 7-Zip / LZMA2 | Strong general codec | Actively maintained | LGPL, scriptable CLI, the safe default final stage |
| Zstandard | Fast codec with `--long` window dedup | Actively maintained (BSD) | `-19..22 --long=31` = decent ratio at far higher speed than LZMA |

## Legal notes

- Compression technology itself is legal and dual-use. Repacking *pirated games for
  distribution* is piracy — this project targets the user's **own files/backups**.
- SREP, lolz, RAZOR: no clear OSS license → fine to *use* locally, risky to *redistribute*.
- Oodle: proprietary (Epic). xtool loads the game's own DLL at runtime — a public app must
  not bundle Oodle DLLs.
- Safe-to-bundle set: 7-Zip (LGPL), Zstandard (BSD), zpaqfranz **[SOURCE-STUDY ⚠
  corrected: MIT, not GPL — doc 20]**, FFmpeg builds (GPL),
  Precomp (Apache 2.0), xtool **[SOURCE-STUDY ⚠ corrected: MIT, not GPL — verified
  from the license header in `xtool.dpr` (doc 13); its `contrib/` third-party libs
  are mixed-license, but we drive the exe, never vendor code]**.

## Realistic pipeline for this project

- v1 (tools already installed): Precomp → SREP → 7z LZMA2 (replace FreeArc; it's dead).
  **[SOURCE-STUDY ⚠ SREP stage dropped from the plan — doc 20 §4 / doc 21 §5; the
  chain is Precomp → (zstd --long / 7z big-dict) → 7z, with zpaqfranz for Insane]**
- v2: xtool (game streams incl. Oodle via game DLL) → zpaqfranz or 7z LZMA2 max.
- Fast profile: zstd -19 --long=31 single stage.
