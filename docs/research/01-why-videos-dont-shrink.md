# Why the current pipeline can't shrink videos

The prototype (`main.py`) chains **Precomp → SREP → FreeArc**. This pipeline is correct
for *game data* but mathematically cannot shrink video, and here is why.

## The root cause: entropy

- MP4/MKV/AVI files contain streams encoded with lossy codecs (H.264, H.265, VP9, AV1).
- A lossy codec's final stage is an **entropy coder** (CABAC in H.264/H.265). Its output is
  statistically close to random noise — there is almost no redundancy left.
- Lossless compressors (LZMA, Zstandard, PAQ, FreeArc, anything) work by finding redundancy.
  No redundancy → no reduction. Typical result on video: **0–2%**, sometimes the output is
  slightly *larger* (container overhead).

## Why each stage fails on video

| Stage | What it does | Why it fails on video |
|---|---|---|
| Precomp | Finds zlib/deflate/jpeg streams inside files and *decompresses* them so a stronger codec can recompress them | Video streams are not deflate — nothing to expand |
| SREP | Long-range deduplication (finds repeated blocks MBs/GBs apart) | Encoded video almost never repeats byte-identical blocks |
| FreeArc -max | LZMA-class compression | High-entropy input is incompressible |

## What actually shrinks video

**Lossy re-encoding with a newer codec.** This is what the "lossy repack" option in
FitGirl-style repacks means, and what HandBrake/Av1an do:

- H.264 → **AV1** at the same *perceived* quality typically gives **30–60% size reduction**.
- H.264 → HEVC (x265) gives roughly 25–50%.
- Audio: AC3/PCM → **Opus** gives large gains at transparent quality.
- This is *lossy*: output is not bit-identical to the input; you re-decide the quality target.

There is no known lossless method to significantly shrink already-encoded video. Any tool
claiming otherwise is either re-encoding (lossy) or lying.

## Consequence for ExtremeCompressor's design

The app needs a **router**: detect file type first, then send each file down the right pipeline:

- Video/audio → FFmpeg re-encode pipeline (opt-in, quality-targeted) — see `03-video-reencoding.md`
- Game data / general files → precompress + dedup + strong codec — see `02-game-repack-pipeline.md`
- Already-compressed files (zip archives can be recompressed via Precomp; but .rar/.7z/random
  data) → store or light zstd pass, don't waste hours for 0%
