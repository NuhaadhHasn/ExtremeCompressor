# 🗜️ ExtremeCompressor

> **FitGirl-repack-style extreme compression for your own files — games, documents, media — with honest handling of what can and cannot shrink.**

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)
![Tests](https://img.shields.io/badge/tests-38%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

Most archivers run one algorithm over everything. ExtremeCompressor works like a
game repacker instead: it **analyzes every file**, **routes** it to the pipeline
that actually works for that data, chains **specialist tools** (precompression →
long-range dedup → strong codec), and **verifies** the restore is byte-identical
before ever claiming success.

---

## ✨ Features

- **Smart routing** — magic-byte type detection + Shannon-entropy sampling
  decides per file: pipeline it, or store it and *tell you why* (no more hours
  wasted "compressing" a video for 0%).
- **Repack-class pipeline** — `tar → Precomp (-intense) → SREP → 7-Zip LZMA2`:
  expands weak zlib layers hidden inside game paks, dedupes repeated assets,
  then compresses hard. **72% saved** on game-style data in first benchmarks.
- **4 profiles** — `fast` (zstd-19 long mode) · `normal` (7z max) · `extreme`
  (full chain) · `insane` (stronger final codec, WIP). Profiles degrade
  gracefully when a tool isn't installed.
- **Lossless media guarantee** — video/audio/images are stored bit-exact by
  default; quality is never touched. (Opt-in AV1/Opus "Shrink" mode is on the
  roadmap for when you *want* them smaller.)
- **Trust built in** — `.excmp` archives carry a manifest (exact stage chain,
  tool versions, SHA-256 of every file). Extraction replays the chain in
  reverse and fails loudly on any mismatch. Inputs are never modified; outputs
  are written atomically.
- **Progress, cancel, clean errors** — every stage streams progress; Ctrl-C
  safe; failures surface the tool's real output, not a stack trace.

---

## 🧬 How it works

```
 input files/folders
        │
        ▼
 ┌─────────────┐   magic bytes + entropy   ┌──────────────────────────────┐
 │  Analyzer    │ ─────────────────────────▶│  Router                      │
 └─────────────┘                            │  media / high-entropy → store │
                                            │  everything else → pipeline   │
                                            └──────────────┬───────────────┘
                                                           ▼
                    ┌──────────────────────────────────────────────────────┐
                    │  Stage chain (profile-dependent)                     │
                    │  tar → precomp → srep → 7z   (extreme)               │
                    └──────────────────────────┬───────────────────────────┘
                                               ▼
                        ┌───────────────────────────────────────┐
                        │  .excmp container                     │
                        │  manifest.json (chain + SHA-256 ledger)│
                        │  payload blob + stored/ files          │
                        └───────────────────────────────────────┘
```

| Component | Role |
|---|---|
| `excmp/analyzer.py` | File type detection (magic bytes, zlib-stream sniffing) + entropy sampling |
| `excmp/planner.py` | Profile → per-file route decisions with human-readable reasons |
| `excmp/stages/` | One module per tool: 7-Zip, zstd, tar, Precomp, SREP |
| `excmp/engine.py` | Runs the chain, packages, self-tests, atomic publish |
| `excmp/manifest.py` | `.excmp` container: schema-versioned manifest + payload |
| `excmp/verify.py` | SHA-256 ledger, restore verification |
| `excmp/cli.py` | `analyze` / `compress` / `extract` commands |

---

## 📊 First benchmark (2-core i7-3540M laptop, 17 MB mixed corpus)

| Profile | Compressed | Saved | Compress | Extract + verify |
|---|---|---|---|---|
| fast | 11.3 MB | 31.0% | 5.1s | 0.3s |
| normal | 11.2 MB | 31.2% | 2.5s | 0.5s |
| **extreme** | **4.5 MB** | **72.4%** | 8.5s | 1.6s |

The extreme win comes from Precomp opening zlib-wrapped "game pak" data and
SREP deduplicating shared assets **before** the final codec — order matters
more than strength. Full methodology in [`docs/benchmarks/`](docs/benchmarks/).

---

## 📁 Project structure

```
.
├── excmp/                  # engine package (GUI-independent)
│   ├── analyzer.py         # type detection + entropy
│   ├── planner.py          # profiles + routing
│   ├── engine.py           # orchestration, verify, atomic outputs
│   ├── manifest.py         # .excmp container
│   ├── verify.py           # SHA-256 ledgers
│   ├── cli.py              # command-line interface
│   └── stages/             # sevenzip, zstd, tar, precomp, srep
├── tests/                  # 38 pytest tests incl. real-tool roundtrips
├── tools/bench.py          # profile benchmark harness
├── docs/
│   ├── research/           # compression landscape research (6 docs)
│   ├── superpowers/specs/  # approved design document
│   ├── superpowers/plans/  # implementation plans
│   └── benchmarks/         # measured results
└── main.py                 # legacy Tkinter prototype (superseded)
```

---

## 🚀 Getting started

### 1. Clone and set up

```bash
git clone https://github.com/NuhaadhHasn/ExtremeCompressor.git
cd ExtremeCompressor
python -m venv .venv
.venv\Scripts\activate
pip install zstandard pytest
```

### 2. Install the tools

| Tool | Needed for | Get it |
|---|---|---|
| [7-Zip](https://www.7-zip.org/) | `normal` / `extreme` | installer puts `7z.exe` in `C:\Program Files\7-Zip` |
| [Precomp](https://github.com/schnaader/precomp-cpp) | `extreme` (optional) | detected at `C:\Program Files\precomp\` |
| SREP | `extreme` (optional) | detected at `C:\Program Files\srep\` |

Missing tools are fine — profiles degrade automatically and tell you what was skipped.

### 3. Use it

```bash
# what would happen? (categories, entropy, routing plan)
python -m excmp analyze "D:\MyGame"

# compress with the full repack chain
python -m excmp compress "D:\MyGame" -o game.excmp -p extreme

# restore — verified byte-identical, or it fails loudly
python -m excmp extract game.excmp -o "D:\restored"
```

Example output:

```
done: 16.3 MB -> 4.5 MB (72.4% saved) in 8.5s
note: 1 file(s) stored losslessly - media file: already compressed by its
      codec; stored losslessly so quality is untouched
```

### 4. Run the tests

```bash
python -m pytest tests -v
```

---

## 🖥️ GUI

The PySide6 desktop app (drop zone → smart suggestions → job queue → results
screen) is **Phase 2, in progress** — screenshots will land here when it does.
The legacy Tkinter prototype in `main.py` still runs but is superseded by the
engine CLI above.

---

## 🗺️ Roadmap

- [x] Research: repack tech, video encoding, archiver landscape (`docs/research/`)
- [x] Engine core: analyzer, router, stages, verified `.excmp` roundtrip, CLI
- [x] Extreme chain with real Precomp + SREP, first benchmarks
- [ ] PySide6 GUI (queue, profiles, progress, results)
- [ ] zpaqfranz backend → completes the `insane` profile
- [ ] Opt-in video/audio Shrink mode (FFmpeg + SVT-AV1, quality-targeted)
- [ ] Per-file-type specialists (PNG/JPEG/WAV recompression)
- [ ] PyInstaller packaging + SHA-pinned tool downloader

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the detailed step-by-step plan.

---

## ⚠️ Honest limitations

- **Already-compressed data (video, MP3, RAR…) cannot shrink losslessly** — no
  tool on earth does this; ExtremeCompressor stores it and says so. Re-encoding
  (lossy, quality-targeted) is the only way and will be strictly opt-in.
- `extreme` trades time and temp disk space (Precomp can inflate data 2-5×
  mid-pipeline) for ratio — that's the repack deal.
- SREP is closed freeware: used if installed, never bundled or redistributed.

---

## 🤝 Contributing

Issues and PRs welcome. Run the tests, keep the "inputs are never modified"
and "verify before success" guarantees intact.

## 📄 License

MIT for this codebase — see [LICENSE](LICENSE). External tools keep their own
licenses (7-Zip LGPL, Zstandard BSD, Precomp Apache-2.0, SREP freeware).
