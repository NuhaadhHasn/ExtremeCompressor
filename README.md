# ExtremeCompressor

FitGirl-repack-style extreme compression for your own files: games, documents,
and media — with honest handling of what can and cannot shrink.

## How it works

Every input file is **analyzed** (magic bytes + entropy), **routed** to the right
treatment, run through a **stage pipeline** of proven native tools, and packaged
into a `.excmp` archive whose manifest records the exact chain + SHA-256 of every
file, so extraction replays it in reverse and **verifies the restore is
byte-identical**.

| Profile | Chain | Best for |
|---|---|---|
| `fast` | zstd-19 (long mode) | quick backups |
| `normal` | 7-Zip LZMA2 max | general use |
| `extreme` | precomp → srep → 7-Zip | game data (zlib paks, duplicated assets) |
| `insane` | extreme + stronger final codec (WIP) | maximum ratio |

Media files (video/audio/images) are **stored losslessly by default** — they are
already compressed by their codecs, and no lossless tool can shrink them; the
app tells you so instead of wasting hours. An opt-in re-encode mode (AV1/Opus)
is planned for when you *want* them smaller.

First benchmark on the dev machine (17 MB mixed corpus, 2-core i7-3540M):
fast 31.0% saved / normal 31.2% / **extreme 72.4%** — see `docs/benchmarks/`.

## Usage (engine CLI)

```
.venv\Scripts\python.exe -m excmp analyze  <path>
.venv\Scripts\python.exe -m excmp compress <inputs...> -o out.excmp -p extreme
.venv\Scripts\python.exe -m excmp extract  out.excmp -o restored\
```

## Requirements

- Python 3.12+, `pip install zstandard pytest`
- [7-Zip](https://www.7-zip.org/) (LGPL) — `normal`/`extreme` final stage
- Optional for `extreme`: Precomp (Apache-2.0) and SREP (freeware) — detected if
  installed, never bundled in this repo
- Tests: `.venv\Scripts\python.exe -m pytest tests -v`

## Project docs

- Research: `docs/research/` (why video can't shrink losslessly, tool landscape)
- Approved design: `docs/superpowers/specs/2026-07-14-extreme-compressor-design.md`
- Roadmap: engine core ✅ → PySide6 GUI → zpaqfranz backend → video shrink mode → packaging
