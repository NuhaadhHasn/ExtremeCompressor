# 🗺️ ExtremeCompressor — Remaining Work, Step by Step

> Status date: 2026-07-18. Engine core is DONE (38 tests, benchmarked, on GitHub).
> This is the complete, ordered plan for everything left. Companion deep-dives:
> [research/06-best-compression-per-filetype.md](research/06-best-compression-per-filetype.md)
> and [research/07-ui-ux-design.md](research/07-ui-ux-design.md).

---

## Phase A — Desktop GUI (PySide6) ← NEXT

The single-window flow (full blueprint in research/07):
**drop files → smart suggestion → preset cards → visible queue → results screen**.

- [ ] A1. `pip install PySide6`; app skeleton (`gui/` package, `python -m gui`), dark QSS
      token theme (hand-rolled — PySide6-Fluent-Widgets is GPLv3, conflicts with our MIT)
- [ ] A2. Drop zone + file picker; dragEnter highlight; multi-file/folder drop adds
      everything (HandBrake's most-complained bug — we fix it day one)
- [ ] A3. Analysis summary card: run engine analyzer in a worker thread, show per-type
      breakdown + smart suggestion, e.g. *"Mostly video (82%): lossless gain ~0%.
      Enable Shrink mode (slow on this CPU)?"*
- [ ] A4. Preset cards (Fast / Normal / Extreme / Insane) + "Advanced" expander
      (threads, temp dir, output path); Media-Shrink toggle greyed until Phase C
- [ ] A5. `QueueManager(QObject)`: one job at a time, jobs run engine calls in
      `QThreadPool`; signals `jobProgress(id, stage, pct, eta)`, `jobDone(id, result)`;
      pause = finish-current-stage-then-hold; cancel wired to `StageContext.cancel`
- [ ] A6. Queue table always visible in main window (name, profile, size→size, %,
      ETA, state) with per-job log expander
- [ ] A7. Results screen: headline "You saved X MB (Y%)", per-type before/after bars,
      one-line "why didn't X shrink" explainers straight from `Route.reason`
- [ ] A8. Windows integration: taskbar progress (ITaskbarList3 via `comtypes`),
      completion toast (`Windows-Toasts`) with "Open folder" button, system tray option
- [ ] A9. Extract tab: pick `.excmp` → destination → verified restore with progress
- [ ] A10. Day-one hygiene: every string in `self.tr()`, `setAccessibleName` on
      icon-only buttons, full keyboard tab order, no color-only meaning; NVDA pass
- [ ] A11. GUI smoke tests (pytest-qt): queue lifecycle, cancel, progress signal flow
- [ ] A12. Screenshot set for README: dark-theme hero of the RESULTS screen (big
      saved-% number), <10s GIF of drop→suggest→compress→result

## Phase B — Stronger + specialist compression

- [ ] B1. **zpaqfranz stage** (actively maintained, FOSS): `a -m4` default for Insane,
      `-m5` behind an "overnight" warning; completes the Insane profile; add to bench
- [ ] B2. **JPEG specialist**: `lepton_jpeg_rust` (Microsoft, Apache-2.0) — ~22%
      lossless, bit-exact restore; route `Category.IMAGE/jpeg` through it
- [ ] B3. **PNG specialist**: `oxipng -o max` default, ECT `-9` under Extreme
- [ ] B4. **WAV specialist**: FLAC 1.5 `-8 -j N`; TAK/OptimFROG as detected-only
      opt-ins (closed freeware — never bundled)
- [ ] B5. **PDF/Office**: qpdf `--object-streams=generate --recompress-flate`;
      docx/xlsx members unpacked into the solid stage (they're just ZIPs)
- [ ] B6. **xtool stage** (game paks: zlib/lz4/zstd/**Oodle** via the game's own
      oo2core DLL): detected-only, MIT but archived upstream — always verified
      roundtrip; extend router with pak/Oodle magic detection
- [ ] B7. Executables: enable 7z BCJ2 filter args explicitly; **never UPX** (AV flags,
      hurts archive ratio)
- [ ] B8. Re-benchmark everything on Silesia + a real game folder; update README table

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

## Phase D — QA hardening (data integrity IS the product)

- [ ] D1. **Property-based roundtrip tests** (Hypothesis): custom composite strategy
      generating file trees — unicode/emoji names, 0-byte files, nested dirs, binary/
      text/already-compressed content; property: compress→extract→byte-identical
- [ ] D2. **Edge-case matrix** as parametrized pytest: >260-char paths (with/without
      long-path registry opt-in), reserved names (CON, NUL), locked files, read-only
      attrs, case-only name collisions, >4 GB file (slow-marked), symlink policy
- [ ] D3. **Crash-consistency**: kill the subprocess at EVERY pipeline stage; assert
      input untouched (bytes + mtime), no partial output at final path, temp cleaned
- [ ] D4. **Disk-full simulation** on a small VHDX/subst volume; graceful failure
- [ ] D5. **Deep-verify command** (`excmp verify archive.excmp`): full decompress +
      hash-compare every file (restic `check --read-data` / zpaqfranz paranoid model)
- [ ] D6. **Fuzzing**: HypoFuzz over the `.excmp` parser on Windows (Atheris is
      Linux-only); optional Linux CI job running Atheris
- [ ] D7. **CI**: GitHub Actions `windows-latest` (7-Zip preinstalled!) — matrix
      Python 3.11–3.13, `setup-python` pip cache, SHA-keyed tool cache; badge in README
- [ ] D8. Atomic-write upgrade: temp + `fsync` + read-back hash + `os.replace`

## Phase E — Release engineering

- [ ] E1. **SHA-pinned tool downloader**: manifest in repo (`tools/manifest.json`:
      name, version, URL, sha256); download→verify→atomic move; hard-fail on mismatch.
      Solves SREP legally too — SREP requires a commercial license to REDISTRIBUTE,
      so the app downloads it to the user's machine instead of bundling
- [ ] E2. `THIRD-PARTY-NOTICES.md`: 7-Zip 26.02 (LGPL+unRAR), zstd (BSD), Precomp
      (Apache-2.0), zpaqfranz (FOSS), lepton_jpeg_rust (Apache-2.0), oxipng (MIT),
      FLAC (BSD/GPL CLI), SREP (freeware, downloaded not bundled), xtool (MIT, archived)
- [ ] E3. PyInstaller **--onedir** (NOT --onefile: self-extraction triggers AV/
      SmartScreen) wrapped in an Inno Setup installer
- [ ] E4. **Code signing**: apply to SignPath Foundation (free OV signing for OSS;
      requires MIT-clean repo — another reason SREP stays external). Unsigned exes
      now need ~15k downloads for SmartScreen reputation; don't ship unsigned
- [ ] E5. Auto-update v1: poll GitHub Releases API → download signed installer →
      verify SHA-256 → run; consider `tufup` (TUF) later
- [ ] E6. Community files: CONTRIBUTING.md, SECURITY.md (parser vulns matter for an
      archiver), issue templates asking for tool-manifest versions + log file,
      CHANGELOG.md (Keep-a-Changelog + SemVer)

## Recommended extras (post-v1 ideas)

- Folder size treemap (WinDirStat-style) on the analysis screen
- "Compare profiles on a sample" button — runs `tools/bench.py` on 100 MB of the
  input and shows the real trade-off before committing hours
- Solid-archive chunking for resumable multi-hundred-GB jobs + `.excmp` split volumes
- zstd `--train` dictionaries for many-small-similar-file corpora
- Self-extracting `.exe` output option
- Linux/macOS support (engine is already portable; stages need path candidates)

## Suggested order & effort (2-core laptop reality)

| Order | Phase | Rough effort |
|---|---|---|
| 1 | A (GUI) | 3-5 sessions |
| 2 | D1-D3, D7 (QA core + CI) | 1-2 sessions |
| 3 | B1-B3 (zpaqfranz + JPEG/PNG) | 1-2 sessions |
| 4 | E1-E2 (downloader + notices) | 1 session |
| 5 | C (video shrink) | 2-3 sessions |
| 6 | B4-B8, D4-D6, E3-E6 | as needed |

GUI first: it makes every later feature visible and testable, and produces the
README screenshots.
