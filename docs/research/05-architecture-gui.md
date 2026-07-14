# Architecture, language & GUI strategy

## The key insight

Every heavy operation is done by battle-tested **native CLI tools** (7z, zstd, FFmpeg,
precomp, xtool, zpaqfranz). The app itself is an **orchestrator**: analyze → plan → run
subprocesses → parse progress → verify. Orchestrators don't need a fast language — they need
good process management and a good GUI. StaxRip (VB.NET driving x265/ffmpeg) and PeaZip
(driving 7z/zpaq CLIs) prove this model at scale.

## Language options

| Option | Pros | Cons |
|---|---|---|
| **Python + PySide6 (Qt)** — recommended | User already has Python code & venv; Qt = professional GUI (queue tables, dark theme, system tray); rich subprocess/asyncio; fastest iteration | Distribution needs PyInstaller (~40–80 MB); startup a bit slower |
| C# .NET 8 + WPF/Avalonia | Single-exe publish, best Windows citizen | Full rewrite in a new language; slower iteration for a solo dev learning as they go |
| Rust + Tauri | Tiny, fast | Steepest learning curve; overkill for an orchestrator |
| Keep Tkinter | Zero new deps | Too weak for queue/progress-heavy UX; looks dated |

## Process orchestration requirements (Windows)

- `subprocess` with `CREATE_NO_WINDOW`, killable process groups for **cancel**.
- Progress parsing: FFmpeg `-progress pipe:1`; 7z `-bsp1` percent stream; zstd/zpaqfranz
  stderr parsing; fallback: output-file-size polling.
- **Temp space management**: precomp stage can inflate data 2–5× before final stage shrinks
  it — check free disk before running; stream stages where possible; clean up on failure.
- Long-path support (`\\?\` prefix), Unicode filenames, low-priority class option so the
  laptop stays usable during hours-long jobs.
- **Resume/journal**: per-job state file; a killed job can restart at the last completed stage.
- Verify after compress: SHA-256 of inputs recorded, test-extract (or `7z t`) before
  declaring success; for video, duration/stream checks.

## GUI shape (v1)

- Main window: drop zone + job queue table (name, type, profile, size→size, ratio, ETA, state).
- Per-job profile picker: Fast / Normal / Extreme / Insane + "Media mode" toggle (lossy
  video/audio re-encode with quality slider: Visually Lossless / Balanced / Small).
- Settings: tool paths, temp dir, CPU threads/priority, output naming.
- Log panel per job; notification on completion.

## Toolchain shipping

- v1: detect installed tools; offer guided download of missing ones (ffmpeg gyan.dev build,
  zstd, zpaqfranz) into an app-managed `tools/` dir with hash pinning.
- Licenses permit redistribution for: 7-Zip (LGPL), zstd (BSD), FFmpeg GPL builds (must ship
  license text + source offer), zpaqfranz, Precomp (Apache 2.0). Do **not** bundle: SREP,
  lolz, Oodle DLLs.
- Unsigned exe → SmartScreen warnings; fine for personal use, revisit signing if published.

## Archive format

`<name>.excmp` = ZIP container holding `manifest.json` (schema-versioned: stage chain, tool
versions, per-file routing, hashes) + payload blobs produced by the final codec stage.
Extraction replays stages in reverse. Also support plain outputs (.7z/.zst/.mkv) when the
pipeline is single-stage so users aren't locked in.
