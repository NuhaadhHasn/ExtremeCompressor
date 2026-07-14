# ExtremeCompressor — Design Proposal (DRAFT, awaiting approval)

> Status: **proposed**, not yet approved. No implementation until the user signs off.
> Research basis: `docs/research/01..05`.

## Goal

A Windows GUI app that compresses *anything* as hard as practical, FitGirl-repack style:
games and general files via a lossless multi-stage pipeline; videos/audio via opt-in
quality-targeted lossy re-encoding (the only way they shrink). For the user's own files.

## Approach chosen (pending approval)

**Approach A — Python orchestrator, evolved from the existing prototype.**
Python 3.12 + PySide6 GUI; all heavy lifting by native CLI tools. Alternatives considered:
C#/.NET rewrite (better distribution, but full rewrite), thin preset scripts (fast, no
product). See `research/05-architecture-gui.md`.

## Components

1. **Analyzer** — walks input; per file: magic-byte type detection, `ffprobe` for media,
   entropy sample (first/random 1 MB) to predict compressibility.
2. **Planner/Router** — maps analysis → per-file pipeline plan:
   - media + Media-mode ON → `reencode(av1/opus, quality target)`
   - media + Media-mode OFF → `store`
   - game-ish/general data → `precompress → dedup → final codec` per chosen profile
   - detected already-compressed non-expandable → `store` (with report line explaining why)
3. **Pipeline engine** — async stage runner: subprocess management, progress parsing,
   cancel, pause/resume via job journal, temp-space guard, post-verify (hash + test-extract).
4. **Packager** — `.excmp` manifest container (multi-stage) or plain `.7z`/`.zst`/`.mkv`
   (single-stage). Extraction = reverse replay.
5. **GUI (PySide6)** — drop zone, queue table, profiles (Fast/Normal/Extreme/Insane),
   Media-mode quality slider, ETA, logs, settings, completion notifications.
6. **Tool manager** — locates/downloads pinned CLI tools (7z, zstd, ffmpeg, precomp,
   zpaqfranz; later xtool), hash-verified.

## Profiles

| Profile | Lossless pipeline | Media mode (opt-in) |
|---|---|---|
| Fast | zstd -19 --long=31 | remux + Opus audio only |
| Normal | 7z LZMA2 -mx=9 | AV1 preset 10, CRF 32 |
| Extreme | precomp → srep/zstd-long → 7z -md=192m | AV1 preset 8, CRF 28 |
| Insane | precomp/xtool → dedup → zpaqfranz -m5 | AV1 preset 6 + CRF search to VMAF 95 |

## Phases

- **Phase 0 — Benchmark harness (validation before building)**: script that runs pipeline
  variants on 3 sample corpora (game folder, video set, mixed docs), produces a
  ratio/time table on the actual machine. Kills guesswork; calibrates profiles.
- **Phase 1 — Core engine as CLI** (`excmp` package): analyzer, router, stages (7z, zstd,
  precomp, srep, ffmpeg), manifest, extract, verify; unit + roundtrip tests.
- **Phase 2 — GUI**: PySide6 queue app over the engine.
- **Phase 3 — Advanced**: xtool + zpaqfranz backends, CRF auto-search (ab-av1), resume,
  self-extracting archives.
- **Phase 4 — Packaging**: PyInstaller build, tool downloader, docs.

## Error handling principles

- Never delete/overwrite input; output to temp then atomic move.
- Every stage failure → job marked failed with captured stderr; temp cleaned; inputs intact.
- Verify-before-success is mandatory (test-extract / stream checks).

## Testing

- Roundtrip property: compress→extract→byte-identical (lossless paths).
- Golden probes: known files must route to expected pipelines.
- Media path: duration/track-count invariants; VMAF spot check ≥ target.

## Open questions for the user

1. Language/GUI: confirm Python + PySide6 (vs C# rewrite)?
2. Media mode: accept lossy re-encode as the video path? Default quality target?
3. v1 scope order: general archiver + video first, game pipeline after — or game-first?
4. Personal tool or public release (affects bundling/licensing/signing)?
