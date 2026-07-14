# Video & audio re-encoding strategy, state 2026

## Encoder landscape (verified July 2026)

| Encoder | Status | Use case |
|---|---|---|
| **SVT-AV1** | v4.0.0 mainline (Jan 2026), very active | Best quality-per-bit that is practically encodable on CPU |
| SVT-AV1-PSY | Archived Feb 2026 (read-only) | Its psychovisual features flowed into mainline + forks |
| **SVT-AV1-Essential** | Active fork (v4.0.1-Essential), sensible defaults, psy features (`--tx-bias`, `--complex-hvs`, noise-adaptive filtering) | Good default encoder binary for an app like ours |
| x265 (HEVC) | Mature/stable | Slightly faster than AV1 at slow presets, worse ratio; better device compatibility |
| libaom | Reference AV1 | Too slow for batch use |
| vvenc (VVC/H.266) | Improving but slow, poor playback support | Not practical for consumers yet |
| Hardware (NVENC/QSV AV1) | Needs modern GPU | **Unavailable on the dev machine** (HD4000 + NVS 5200M predate NVENC/QSV-HEVC) |

## Quality-targeted automation

- **ab-av1** (actively maintained, v0.7.x, 2026): runs sample encodes, interpolated binary
  search over CRF to hit a target **VMAF** (or XPSNR) score, then full encode. Also drives
  libx265/libx264. This is exactly the "compress as much as possible without visible quality
  loss" UX we want — bundle it or reimplement its sample-search idea.
- Typical outcomes at perceptually-equal quality (VMAF ≈ 95):
  - H.264 source → AV1: **30–60% smaller**
  - Old MPEG2/XviD sources: 70%+ smaller
  - Already-AV1/HEVC at sane bitrates: little to gain → **detect and skip**
- Audio: re-encode AC3/MP3/PCM → **Opus 96–128k** (transparent for most content); keep
  original on "remux-only" profile.

## Machine reality check (dev laptop: i7-3540M, 2C/4T, 16 GB)

- SVT-AV1 preset 6, 1080p ≈ 1–3 fps on this class of CPU → a 2 h movie ≈ 1–2 days. Preset
  10–12 ≈ 5–15 fps → overnight. x265 medium ≈ 3–8 fps.
- Design consequence: video jobs are **queued batch jobs** with pause/resume, not
  interactive operations. Presets must scale with detected core count; warn the user about
  ETA before starting. On stronger machines (8–16 cores) preset 4–6 becomes practical.

## Pipeline design

1. **Probe** with `ffprobe` (JSON output): codec, bitrate, resolution, tracks.
2. **Skip rules**: already AV1/HEVC below a bits-per-pixel threshold → remux/store only.
3. **Encode**: FFmpeg (gyan.dev/BtbN GPL builds bundle libsvtav1 + libx265 + libopus) with
   `-progress pipe:1` for machine-readable progress; or standalone SvtAv1EncApp-Essential.
4. **Quality target mode**: ab-av1 style CRF search (`--min-vmaf 95`) vs simple CRF presets
   (Fast=CRF 32 preset 10 / Balanced=CRF 28 preset 8 / Extreme=CRF 24 preset 6).
5. **Container**: output MKV via FFmpeg/mkvmerge, preserve subtitles/chapters/attachments.
6. **Verify**: duration match, stream count match, optional VMAF spot-check on samples.
7. Mark output with metadata tag so we never re-encode our own output again (generation loss).

## Prior art worth copying (not the code, the UX)

- **HandBrake**: presets + queue.
- **Av1an**: scene-split chunked parallel encoding (only pays off on many-core machines).
- **StaxRip**: a GUI that *orchestrates external CLI encoders* — closest architectural match
  to what we're building.
