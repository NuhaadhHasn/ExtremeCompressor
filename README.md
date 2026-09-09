# 🗜️ ExtremeCompressor

> **FitGirl-repack-style extreme compression for your own files — games, documents, media — with honest handling of what can and cannot shrink.**

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)
![Tests](https://img.shields.io/badge/tests-1074%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

Most archivers run one algorithm over everything. ExtremeCompressor works like a
game repacker instead: it **analyzes every file**, **routes** it to the pipeline
that actually works for that data, chains **specialist tools** (precompression →
long-range dedup → strong codec), and **verifies** the restore is byte-identical
before ever claiming success.

<p align="center">
  <img src="docs/images/03-results.png" width="820"
       alt="Results screen: 'You saved 12.3 MB (71%)', a before/after bar, a
            per-type breakdown, and one plain-English line explaining why the
            .mp4 and .rar in the folder could not shrink.">
</p>

> **And it tells you the truth about the files it couldn't shrink.** No other
> compressor does — they just quietly return 0% and let you wonder.

---

## ✨ Features

- **Desktop app** — drop anything (files *and* folders, as many as you like),
  get an honest read on what can shrink before you commit, then pick from four
  profiles shown side by side with their *measured* size, saving and time for
  the files you actually dropped. Jobs run on an Activity tab with live
  progress, per-job tool logs, pause and cancel — and a status strip keeps the
  queue visible from every tab. No modal dialogs anywhere.
- **Smart routing** — magic-byte type detection + Shannon-entropy sampling
  decides per file: pipeline it, or store it and *tell you why* (no more hours
  wasted "compressing" a video for 0%).
- **Repack-class pipeline** — `tar → Precomp (-intense) → 7-Zip LZMA2`:
  expands weak zlib layers hidden inside game paks, then compresses hard.
  **71% saved** on game-style data. (SREP was dropped in B11 after an
  intermittent restore-corruption bug inside `srep64.exe`; correctness beats
  the ~3.5 points it was worth.)
- **4 profiles** — `fast` (zstd-19 long mode) · `normal` (7z max) · `extreme`
  (full chain) · `insane` (stronger final codec, WIP). Profiles degrade
  gracefully when a tool isn't installed.
- **Lossless media guarantee** — video/audio/images are stored bit-exact by
  default; quality is never touched. (Opt-in AV1/Opus "Shrink" mode is on the
  roadmap for when you *want* them smaller.)
- **Trust built in** — `.excmp` archives carry a manifest (exact stage chain,
  tool versions, SHA-256 of every file, and the settings that produced it).
  Extraction replays the chain in reverse and fails loudly on any mismatch.
  Inputs are never modified; outputs are written atomically.
- **Ask it to prove it** — `Verify only` (or `excmp verify`) fully restores an
  archive to a temp folder, checks every hash, and deletes it again. Not a
  container self-test: a real restore, the same one that gates every publish.
  Catches a single flipped byte in a 721 MB archive and names the file.
- **Opens other people's archives** — zip, 7z, rar, tar, iso, cab, msi, wim.
  Those carry no SHA-256 ledger, and the app says so rather than borrowing the
  verified-restore wording.
- **Shows what is inside without extracting** — name, size, SHA-256, route,
  and *why a file was stored*. That last column exists nowhere else, because
  nothing else records the reason.
- **Knobs with their cost attached** — level and dictionary, with the peak RAM
  each would need shown before you start (7-Zip's own formula, clamped to your
  actual data). The dictionary list stops where your machine would.
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
                    │  tar → precomp → 7z          (extreme)               │
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
| `excmp/stages/` | One module per tool: 7-Zip, zstd, tar, Precomp (plus a retained SREP *reader* so pre-B11 archives still extract) |
| `excmp/engine.py` | Runs the chain, packages, self-tests, atomic publish |
| `excmp/manifest.py` | `.excmp` container: schema-versioned manifest + payload |
| `excmp/verify.py` | SHA-256 ledger, restore verification |
| `excmp/ram.py` | 7-Zip's own peak-RAM formula, the dictionary cap, and the Parameters allowlist |
| `excmp/cli.py` | `analyze` / `compress` / `extract` / `list` / `verify` / `hash` |

---

## 📊 First benchmark (2-core i7-3540M laptop, 17 MB mixed corpus)

| Profile | Compressed | Saved | Compress | Extract + verify |
|---|---|---|---|---|
| fast | 11.3 MB | 31.0% | 5.1s | 0.3s |
| normal | 11.2 MB | 31.2% | 2.5s | 0.5s |
| **extreme** | **4.5 MB** | **72.4%** | 8.5s | 1.6s |

> ⚠️ These numbers were measured **with SREP in the chain**, before B11
> removed it. The current SREP-free chain measures **71.3%** on the same
> corpus; on a 721 MB real-installer corpus the difference was ~3.5 points.

The extreme win comes from Precomp opening zlib-wrapped "game pak" data
**before** the final codec — order matters more than strength. Full
methodology in [`docs/benchmarks/`](docs/benchmarks/).

---

## 📁 Project structure

```
.
├── excmp/                  # engine package (knows nothing about the GUI)
│   ├── analyzer.py         # type detection + entropy
│   ├── planner.py          # profiles + routing
│   ├── engine.py           # orchestration, verify, atomic outputs
│   ├── manifest.py         # .excmp container
│   ├── verify.py           # SHA-256 ledgers
│   ├── cli.py              # command-line interface
│   └── stages/             # sevenzip, zstd, tar, precomp (+ srep reader)
├── gui/                    # PySide6 desktop app (python -m gui)
│   ├── theme.py            # design tokens → QSS (dark + light)
│   ├── suggest.py          # analysis summary, honesty copy, preset advice
│   ├── progress.py         # per-stage progress → one job percentage + ETA
│   ├── queue_manager.py    # QueueManager + engine workers on a thread pool
│   ├── winintegration.py   # taskbar progress, toasts, tray (all optional)
│   ├── mainwindow.py       # the single-window flow
│   ├── icons.py            # theme-tinted Fluent SVGs (MIT, vendored)
│   └── widgets/            # dropzone, analysis card, chooser, queue, results, banner
├── tests/                  # 1,077 pytest tests incl. real-tool roundtrips
├── tools/
│   ├── bench.py            # profile benchmark harness
│   ├── shots.py            # regenerates docs/images/ from the real app
│   └── qa_sweep.py         # renders every surface in both themes, for review
├── docs/
│   ├── images/             # README screenshots + demo GIF
│   ├── research/           # landscape + source studies + UI design (23 docs)
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
pip install -r requirements.txt          # engine + GUI
pip install -r requirements-dev.txt      # plus pytest, pytest-qt, Pillow
```

Only `zstandard` is needed if you just want the CLI.

### 2. Install the tools

| Tool | Needed for | Get it |
|---|---|---|
| [7-Zip](https://www.7-zip.org/) | `normal` / `extreme` | installer puts `7z.exe` in `C:\Program Files\7-Zip` |
| [Precomp](https://github.com/schnaader/precomp-cpp) | `extreme` (optional) | detected at `C:\Program Files\precomp\` |
| SREP | **nothing any more** — no chain uses it since B11. Detected only so archives created before 2026-08-02 still extract. | `C:\Program Files\srep\` |

Missing tools are fine — profiles degrade automatically and tell you what was skipped.

### 3. Use it

```bash
python -m gui
```

…or from the command line:

```bash
# what would happen? (categories, entropy, routing plan)
python -m excmp analyze "D:\MyGame"

# compress with the full repack chain
python -m excmp compress "D:\MyGame" -o game.excmp -p extreme

# restore — verified byte-identical, or it fails loudly
python -m excmp extract game.excmp -o "D:\restored"

# is this archive still good? a full restore + ledger check; writes nothing
python -m excmp verify game.excmp

# what is inside, straight from the manifest - no extraction, any size
python -m excmp list game.excmp

# SHA-256 of anything, in sha256sum layout
python -m excmp hash game.excmp
```

`extract` also opens archives made by other tools - zip, 7z, rar, tar, iso,
cab, msi, wim - and says plainly when one carries no ledger to check against.

Knobs, when you want them. The defaults are whatever the profile picks:

```bash
# level, dictionary, and a transport sidecar for whoever you send it to
python -m excmp compress "D:\MyGame" -o game.excmp -p extreme --level 9 --dict 256m --sha256

# extra 7-Zip method switches. Needs an "=" sign, because every value
# starts with a dash. -p/-o/-w/@listfile are refused: they would leak a
# password into the log or move the output away from the verified publish.
python -m excmp compress "D:\MyGame" -o game.excmp --params="-mqs"
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

## 🖥️ The desktop app

```bash
python -m gui
```

<p align="center">
  <img src="docs/images/demo.gif" width="820"
       alt="Animated demo: a folder is added, the analysis card reports its
            composition, Extreme is suggested and selected, the queue runs the
            precomp/7-Zip chain with live progress, and the results screen
            reports 71% saved.">
</p>

One window, no modal dialogs — ever. Three tabs, one per stage of the job:
**Compress** is where you decide, **Activity** is where work in flight lives,
**Extract** is its own thing. A one-line status strip along the bottom carries
the queue onto every tab, so nothing is ever hidden behind the tab you are not
looking at.

| Surface | What it does |
|---|---|
| **Drop zone** | Files *and* folders, any number at once. (HandBrake's two most-reported intake bugs, avoided by design.) Once something is pending it collapses to a one-line receipt — *"3 items · 1.9 GB"* — that expands into a removable list. |
| **Analysis card** | Runs the analyzer on a worker thread, ticking through the files as it reads them, and reports the composition plus the honest gain estimate — *"Nearly all of this (15.4 MB) is worth compressing"* or *"86% of this is already compressed and will be stored bit-exact"*. |
| **Profile chooser** | Fast / Normal / Extreme / Insane in one table, each with its measured size, saving and time **for the files you actually dropped** — as a range where the answer is genuinely a range. The suggested one is pre-selected and says why; a profile whose tools are missing says what will really happen instead of degrading silently. |
| **Queue** (Activity tab) | Name, profile, size→size, live progress, time, state — and a per-job expander showing the tool's own output. Pause finishes the current stage before holding; cancel kills the child process and leaves nothing behind. |
| **Results** (Activity tab) | The big number, a to-scale before/after bar, input bytes by type, and one plain-English sentence per file that couldn't shrink. |
| **Extract tab** | Pick an `.excmp`, pick a destination, get the verified hash count back. |

<p align="center">
  <img src="docs/images/01-drop-analysis.png" width="410"
       alt="The Compress tab: intake receipt, analysis card, and the profile chooser with per-profile estimates.">
  <img src="docs/images/02-queue-running.png" width="410"
       alt="The Activity tab: an Extreme job running with its per-job log expanded.">
</p>

Also: taskbar progress, a completion toast with an "Open folder" button,
optional minimize-to-tray, a light theme, full keyboard tab order, accessible
names on every icon-only control, and no meaning carried by colour alone.

Every screenshot above is regenerated from the real app by
[`tools/shots.py`](tools/shots.py) — it builds a reproducible ~17 MB
repack-style corpus, drives the actual window through the whole flow, and
grabs the frames. The numbers in them are genuine output, not mockups.

The legacy Tkinter prototype in `main.py` still runs but is superseded.

---

## 🗺️ Roadmap

- [x] Research: repack tech, video encoding, archiver landscape (`docs/research/`)
- [x] Engine core: analyzer, router, stages, verified `.excmp` roundtrip, CLI
- [x] Extreme chain with real Precomp + SREP, first benchmarks
- [x] PySide6 GUI (drop zone, suggestions, queue, progress, results, extract)
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
- SREP is closed freeware: never bundled or redistributed, and since B11 not
  used to *create* anything — it is detected only to read older archives.

---

## 🤝 Contributing

Issues and PRs welcome. Run the tests, keep the "inputs are never modified"
and "verify before success" guarantees intact.

## 📄 License

MIT for this codebase — see [LICENSE](LICENSE). External tools keep their own
licenses (7-Zip LGPL, Zstandard BSD, Precomp Apache-2.0, SREP freeware).
