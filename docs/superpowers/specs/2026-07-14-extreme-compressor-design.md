# ExtremeCompressor — Approved Design

> Status: **APPROVED 2026-07-14** (user delegated final choices: "you choose best and do the things").
> Supersedes `docs/2026-07-13-extreme-compressor-design-DRAFT.md`. Research basis: `docs/research/01..05`.

## Goal

A Windows-first GUI app that compresses anything as hard as practical — games and general
files via a lossless multi-stage pipeline (FitGirl-repack style); video/audio archived
losslessly by default (bit-identical on extract), with a clearly-labeled opt-in "Shrink
videos" mode that re-encodes to AV1/Opus for real size reduction. Built for the user's own
files; repo must stay publishable on GitHub (no unredistributable binaries committed).

## Decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Stack | Python 3.12+, PySide6 GUI, native CLI backends | All heavy compression runs in C/C++ tools; Python only orchestrates. Existing code is Python; fastest iteration for a solo dev |
| Video default | Lossless container archive — never touches quality; reports honest ~0% gain | User requirement: "video should not lose quality, like a rar file" |
| Video opt-in | "Shrink videos" mode: SVT-AV1 re-encode with quality slider (visually lossless / balanced / small), Opus audio | Only physically possible way to make video smaller |
| Build order | 1) general archiver core, 2) game-specialist stages, 3) video shrink mode | Archiver core subsumes everything; game/video are routers+stages on top |
| Distribution posture | Bundle/download only OSS tools (7-Zip LGPL, zstd BSD, FFmpeg GPL build, zpaqfranz, Precomp Apache-2.0). SREP/xtool/Oodle: auto-detect if user-installed, never committed | Future GitHub publication |

## Architecture

```
GUI (PySide6)  ──── job queue, profiles, progress, logs, settings
   │
Engine (pure-Python package `excmp`, GUI-independent, also usable as CLI)
   ├── analyzer/    magic-byte + ffprobe type detection, entropy sampling
   ├── planner/     per-file pipeline plan from profile + analysis (the ROUTER)
   ├── stages/      one module per tool: sevenzip, zstd, precomp, srep, ffmpeg…
   │                 each stage: run(args) → subprocess w/ progress callback, cancel token
   ├── package/     .excmp manifest container (schema-versioned JSON) + plain outputs
   ├── verify/      SHA-256 ledger, test-extract, media stream checks
   └── jobs/        journal (resume), temp-space guard, priority/threads config
```

- Analyzer → Planner produce a declarative `PipelinePlan`; the engine executes it; the
  manifest records exactly what ran (tools, versions, order, hashes) so extraction replays
  it in reverse deterministically.
- Router defaults: media files → `store` (lossless) unless Shrink mode; high-entropy
  already-compressed → `store` with explanation; everything else → profile pipeline.
- Profiles: Fast (zstd -19 --long), Normal (7z LZMA2 -mx=9), Extreme (precomp → srep/zstd-long → 7z big-dict), Insane (… → zpaqfranz -m5). Profiles degrade gracefully when a
  tool is missing (Extreme without precomp = Normal + warning).

## Error handling (principles)

- Inputs are never modified/deleted; outputs written to temp, atomically moved on success.
- Any stage failure → job failed with captured stderr, temp cleaned, partial outputs removed.
- Success requires verification: test-extract (`7z t`/roundtrip) or media stream checks.
- Disk-space preflight: precomp can inflate 2–5×; check before running.

## Testing

- pytest; roundtrip property tests (compress→extract→byte-identical) on synthetic corpora;
  router golden tests (file X routes to plan Y); manifest schema round-trip; stage progress
  parsers fed recorded CLI output fixtures.

## Phases

0. Benchmark harness (`tools/bench.py`) on real samples — calibrates profiles on this machine.
1. Engine package + CLI (`python -m excmp compress/extract/analyze`) with tests.
2. PySide6 GUI: drop zone, queue table, profile picker, progress/ETA, logs, settings, extract.
3. Game-specialist: xtool/srep detection-based stages, zpaqfranz backend, resume.
4. Video shrink mode: ffmpeg/SVT-AV1 + Opus, skip rules, quality slider, (later ab-av1 CRF search).
5. Packaging: PyInstaller exe, tool downloader with hash pinning, README, license texts.
