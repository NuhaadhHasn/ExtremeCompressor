# 06 — Best possible compression per file type (verified July 2026)

> How ExtremeCompressor becomes "the best compressor for everything": not one
> magic algorithm, but the *best specialist per data type*, routed automatically,
> with default / extreme / lossy-opt-in tiers. All tool statuses verified by
> live research 2026-07-18.

## The master routing table

| Data type | Default (bundled/OSS) | Extreme option | Lossy opt-in (never default) | Typical lossless gain |
|---|---|---|---|---|
| **JPEG** | `lepton_jpeg_rust` (Microsoft, Apache-2.0, active) — bit-exact restore | same | `cjpegli` (~35% better than libjpeg) / AVIF | **~20-22%** |
| **PNG** | `oxipng -o max` (MIT, Rust, multithreaded) | `ECT -9` (Apache-2.0, best ratio, slow) | WebP/AVIF convert | 5-30% |
| **WAV/AIFF** | `flac -8 -j N` (FLAC 1.5, multithreaded, 2025) | TAK 2.3.3 / OptimFROG (closed freeware — detect-only) | Opus 1.6 @ 96-128k | **40-60%** |
| **MP3/AAC/OGG** | store (already entropy-coded) | precomp/xtool packMP3 path (~15-20% on MP3) | Opus re-encode | 0% (store) / 15-20% (packMP3) |
| **Video** | store losslessly | — (physics) | SVT-AV1 quality-targeted (30-60% at equal perceived quality) | ~0% |
| **PDF** | `qpdf --object-streams=generate --recompress-flate` (Apache-2.0) | + precomp deflate expansion into solid LZMA | Ghostscript `/ebook` (breaks signatures) | 5-25% |
| **docx/xlsx/pptx/epub/jar** | unpack ZIP members into the solid stage | same (solid LZMA across members) | — | 5-15% |
| **Executables (x86/x64)** | 7z **BCJ2** filter + LZMA2 | same, bigger dict | ⚠️ never UPX (AV false-positive magnet, *hurts* archive ratio) | +5-15% over plain LZMA |
| **Game paks (zlib)** | Precomp `-intense` → SREP → 7z *(working today)* | **xtool** depth mode | per-game "lossy repack" (texture/audio downscale) | 30-70% |
| **Game paks (Oodle/zstd/lz4)** | store (v1) | **xtool** + game's own `oo2core*.dll` (never redistribute the DLL) | same | up to 60% (engine-dependent) |
| **Text/code/logs** | 7z LZMA2 solid / zstd --long | zpaqfranz `-m5` | — | 70-95% |
| **Random/encrypted/.rar/.7z** | store + honest explanation | — | — | ~0% |
| **Everything else** | 7z `-mx9` | **zpaqfranz `-m4`** (sweet spot) / `-m5` (overnight) | — | varies |

## Key verified facts behind the table

### Images
- Dropbox **Lepton is deprecated/archived**, but Microsoft's **lepton_jpeg_rust**
  port is active (crates.io, ships `lepton_jpeg_util.exe`): same ~22% lossless
  JPEG gain, bit-exact restore — perfect for our manifest-verified container.
  Alternative: JPEG XL transcode `cjxl -j 1` (BSD-3, active) — also ~20-22% and
  byte-exact restorable via `djxl`.
- **pingo** is fast and near-best but its freeware license forbids repackaging —
  risky for a public GitHub app; oxipng (MIT) + ECT (Apache-2.0) cover us.
- brunsli is frozen (absorbed into JPEG XL); packJPG survives only inside
  Precomp/xtool.

### Audio
- All lossless audio codecs land within ~4-7% of each other; **FLAC 1.5** (Feb
  2025) finally multithreads encode (`-j N`) and is the compatibility/licensing
  winner. TAK ≈ Monkey's-High ratio at 1/7th the decode CPU — ideal opt-in for
  the 2-core dev machine. WavPack 5.9 (Jan 2026) for DSD/32-bit-float edge cases.

### Game data (the FitGirl tier)
- **xtool** (Razor12911): MIT on GitHub but archived Oct 2023 at v0.7.9; newer
  builds (v0.9.5, Mar 2026) exist via the author's Patreon. Codecs: zlib/reflate/
  preflate, lz4/lz4hc/lzo, zstd, **Oodle Kraken/Mermaid/Selkie/Leviathan/Hydra**,
  png/flac/packjpg/brunsli/jojpeg. It loads the game's own `oo2core_*.dll` —
  Oodle is RAD/Epic proprietary and must never ship with our app.
- Documented result class: a UE `.pak` recompressed to **40.5% of original**;
  FitGirl-class repacks land 60-80% total reduction.
- lolz/ztool: private-scene tools, no maintained public repo — unavailable to us.
- Since xtool is unmaintained, every xtool route MUST use our verified-roundtrip
  gate (which we already enforce engine-wide).

### The fallback codec race (mixed ~1 GB data class)
- **zpaqfranz** is the only actively maintained max-ratio archiver (v64.x through
  2026, FOSS, single exe): `-m4` = sweet spot, `-m5` = max (hours). Its
  "paranoid-level verify" is also our QA role model.
- kanzi (Apache-2.0, active) and bsc (Apache-2.0) are strong mid-ratio/multicore
  options worth benchmarking later; PAQ8px/cmix remain benchmark toys (days/GB).
- 7-Zip current is **26.02** (June 2026); BCJ2 section default now 240 MiB
  (better for big EXEs).

## How this lands in the code (router v2 design)

1. `analyzer.py` gains sub-type detail: `jpeg`, `png`, `wav`, `pdf`, `zip-office`,
   `pak-zlib`, `pak-oodle` (magic sniffing inside pak headers), `exe-x86`.
2. `planner.py` maps sub-type → specialist stage when the tool is present,
   else falls through to today's generic chains. Every specialist is a normal
   `Stage` (compress/extract/available) — the framework already supports this.
3. Specialist outputs live inside the `.excmp` payload with their stage recorded
   in the manifest, so extraction reverses them exactly like precomp/srep today.
4. Multi-option UX: each profile picks a tier per type (the table above), and the
   Advanced expander lets users override per-type choices.

## Sources (highlights)

- github.com/microsoft/lepton_jpeg_rust · github.com/shssoichiro/oxipng ·
  github.com/fhanau/Efficient-Compression-Tool · libjxl releases
- xiph.org/flac (1.5.0) · thbeck.de/Tak · wavpack.com (5.9)
- qpdf.readthedocs.io · github.com/amadvance/advancecomp
- github.com/Razor12911/xtool (+ encode.su thread 4000) · fcorbelli/zpaqfranz
- 7-zip.org/history.txt (26.02) · UPX false-positive mega-thread (github.com/upx/upx)
