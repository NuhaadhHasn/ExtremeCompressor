# ExtremeCompressor Engine Core (`excmp`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tested, GUI-independent Python package `excmp` + CLI that analyzes files, routes them to the right compression pipeline, produces `.excmp`/`.7z` archives, and extracts them back byte-identical.

**Architecture:** Pure-Python orchestrator package. Native tools (7z.exe, precomp, srep) do the heavy compression via subprocess; the `zstandard` pip package covers the Fast profile with no external binary. A JSON manifest inside a ZIP container (`.excmp`) records the exact stage chain + hashes so extraction replays it in reverse and verifies integrity.

**Tech Stack:** Python 3.11+ (project venv `venvPython`), `zstandard`, `pytest`; external: 7-Zip (`C:\Program Files\7-Zip\7z.exe`), optional Precomp/SREP (already installed on dev machine).

## Global Constraints

- Windows-first; all subprocess calls must pass `creationflags=subprocess.CREATE_NO_WINDOW` when frozen/GUI, and never use `shell=True`.
- Inputs are NEVER modified or deleted. Outputs go to a temp path then atomic `os.replace` on success.
- Every compress job must verify before reporting success (hash ledger + test-extract).
- Media/high-entropy files default to lossless `store` routing — quality is never touched by default.
- No unredistributable binaries committed to the repo (SREP/Precomp are *detected*, not bundled).
- Package layout: `excmp/` at repo root; tests in `tests/`; run tests with `venvPython\Scripts\python.exe -m pytest tests -v`.

---

### Task 1: Package scaffold + tool discovery

**Files:**
- Create: `excmp/__init__.py`, `excmp/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `ToolInfo(name, path, version)` dataclass; `find_tools() -> dict[str, ToolInfo|None]` with keys `"7z"`, `"precomp"`, `"srep"`, `"zpaqfranz"`, `"ffmpeg"`, `"ffprobe"`, `"zstd"`; `require(tools, name) -> ToolInfo` raising `ToolMissingError`.

- [ ] **Step 1: failing test** — `tests/test_tools.py`:

```python
from excmp.tools import find_tools, ToolInfo

def test_find_tools_returns_all_keys():
    tools = find_tools()
    assert set(tools) >= {"7z", "precomp", "srep", "zpaqfranz", "ffmpeg", "ffprobe", "zstd"}

def test_7z_found_on_dev_machine():
    tools = find_tools()
    assert tools["7z"] is not None and tools["7z"].path.lower().endswith("7z.exe")
```

- [ ] **Step 2: run, expect FAIL** (`ModuleNotFoundError: excmp`)
- [ ] **Step 3: implement** — `excmp/tools.py`: dataclass `ToolInfo`; `CANDIDATES` dict mapping tool name → list of well-known absolute paths (7z: `C:\Program Files\7-Zip\7z.exe`; precomp: `C:\Program Files\precomp\windows\precomp.exe`; srep: `C:\Program Files\srep\srep64.exe`; zpaqfranz/zstd/ffmpeg: PATH via `shutil.which` + `tools/bin/` app dir). `find_tools()` checks candidates + `shutil.which`, returns dict. `ToolMissingError(Exception)`, `require()`.
- [ ] **Step 4: run, expect PASS**
- [ ] **Step 5: commit** `feat: excmp package scaffold and tool discovery`

### Task 2: Analyzer (type detection + entropy)

**Files:**
- Create: `excmp/analyzer.py`
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Produces: `Category` StrEnum: `VIDEO, AUDIO, IMAGE, COMPRESSED_ARCHIVE, EXECUTABLE, TEXT, BINARY`; `FileInfo(path, size, category, entropy_bps)`; `analyze_file(path) -> FileInfo`; `analyze_tree(root) -> list[FileInfo]`; `sample_entropy(path, sample=1_048_576) -> float` (Shannon bits/byte over up to 3 samples: head/middle/tail).

- [ ] **Step 1: failing test** (build tiny fixtures in `tmp_path`):

```python
from excmp.analyzer import analyze_file, sample_entropy, Category
import os, random

def test_detects_text(tmp_path):
    p = tmp_path / "a.txt"; p.write_text("hello world " * 1000)
    assert analyze_file(p).category == Category.TEXT

def test_detects_mp4_magic(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
    assert analyze_file(p).category == Category.VIDEO

def test_detects_zip_magic(tmp_path):
    p = tmp_path / "x.zip"; p.write_bytes(b"PK\x03\x04" + b"\x00" * 50)
    assert analyze_file(p).category == Category.COMPRESSED_ARCHIVE

def test_entropy_random_high_text_low(tmp_path):
    r = tmp_path / "r.bin"; r.write_bytes(random.randbytes(200_000))
    t = tmp_path / "t.txt"; t.write_text("abc" * 100_000)
    assert sample_entropy(r) > 7.5 and sample_entropy(t) < 3.0
```

- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** — magic-byte table (ftyp/matroska/RIFF-AVI → VIDEO; ID3/fLaC/OggS/RIFF-WAVE → AUDIO; JPEG/PNG/GIF/WEBP → IMAGE; PK/7z/Rar/gzip/zstd/xz → COMPRESSED_ARCHIVE; MZ → EXECUTABLE) with extension fallback; Shannon entropy via `collections.Counter` on ≤3 × 1 MiB samples.
- [ ] **Step 4: run, expect PASS**  — **Step 5: commit** `feat: file analyzer with magic-byte detection and entropy sampling`

### Task 3: Manifest + `.excmp` container

**Files:**
- Create: `excmp/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Produces: `StageRecord(stage, tool_name, tool_version, params)`; `Manifest(schema=1, created_utc, profile, stages: list[StageRecord], inputs: dict[relpath, {size, sha256}], payload_name)`; `write_container(archive_path, manifest, payload_path)` (ZIP_STORED zip holding `manifest.json` + payload blob); `read_container(archive_path) -> (Manifest, extracted_payload_tmp_path)`; `Manifest.to_json/from_json`.

- [ ] **Step 1: failing test** — round-trip a manifest + dummy payload through a container in `tmp_path`; assert equality of parsed fields and payload bytes.

```python
from excmp.manifest import Manifest, StageRecord, write_container, read_container

def test_container_roundtrip(tmp_path):
    payload = tmp_path / "p.bin"; payload.write_bytes(b"DATA" * 1000)
    m = Manifest.new(profile="normal",
                     stages=[StageRecord("sevenzip", "7z", "24.08", {"mx": 9})],
                     inputs={"a.txt": {"size": 4, "sha256": "aa"}},
                     payload_name="p.bin")
    arc = tmp_path / "out.excmp"
    write_container(arc, m, payload)
    m2, payload2 = read_container(arc)
    assert m2.profile == "normal" and m2.stages[0].stage == "sevenzip"
    assert payload2.read_bytes() == payload.read_bytes()
```

- [ ] **Steps 2–4: fail → implement (dataclasses + json + zipfile ZIP_STORED) → pass**
- [ ] **Step 5: commit** `feat: .excmp manifest container`

### Task 4: Stage framework + 7-Zip stage

**Files:**
- Create: `excmp/stages/__init__.py`, `excmp/stages/base.py`, `excmp/stages/sevenzip.py`
- Test: `tests/test_sevenzip.py`

**Interfaces:**
- Produces: `StageContext(temp_dir, threads, progress_cb: Callable[[str, float], None], cancel: threading.Event)`; `Stage` ABC with `.id`, `.compress(src: Path, dst: Path, ctx) -> Path`, `.extract(src: Path, dst: Path, ctx) -> Path`, `.available() -> bool`; `SevenZipStage(level=9, dict_size="192m"|None)` — compress a *directory or file list* into `dst.7z` with `a -t7z -mx{level} -bsp1 -y`, extract with `x -y -o<dst>`, `test(archive)` with `t`. Progress parsed from `-bsp1` percent lines. `run_tool(cmd, ctx, parse_line)` helper in `base.py` handles Popen, line pump, cancel (kill), stderr capture, `StageError`.

- [ ] **Step 1: failing test** — compress a small tree with real 7z, extract, compare bytes; assert progress callback fired with values in [0,100]:

```python
import pytest
from excmp.tools import find_tools
from excmp.stages.base import StageContext
from excmp.stages.sevenzip import SevenZipStage

pytestmark = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")

def test_sevenzip_roundtrip(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "a.txt").write_text("hello" * 5000)
    (src / "sub").mkdir(); (src / "sub" / "b.bin").write_bytes(bytes(range(256)) * 100)
    seen = []
    ctx = StageContext(temp_dir=tmp_path / "tmp", progress_cb=lambda s, p: seen.append(p))
    arc = SevenZipStage().compress(src, tmp_path / "out.7z", ctx)
    out = tmp_path / "ext"
    SevenZipStage().extract(arc, out, ctx)
    assert (out / "a.txt").read_text() == "hello" * 5000
    assert (out / "sub" / "b.bin").read_bytes() == bytes(range(256)) * 100
```

- [ ] **Steps 2–4: fail → implement → pass**  — **Step 5: commit** `feat: stage framework and 7-Zip stage`

### Task 5: Zstd stage (tar + python-zstandard, no external binary)

**Files:**
- Create: `excmp/stages/zstdstage.py`
- Modify: `venvPython` — `pip install zstandard pytest`
- Test: `tests/test_zstd.py`

**Interfaces:**
- Produces: `ZstdStage(level=19, long_log=27)` — `compress(src_dir, dst)` = `tarfile` stream piped through `zstandard.ZstdCompressor(level, ZstdCompressionParameters with window_log/long mode, threads=-1)` → `dst.tar.zst`; `extract` reverses. Progress = bytes-read / total-bytes.

- [ ] **Step 1: failing test** — same roundtrip pattern as Task 4 with `ZstdStage()`; plus `test_ratio_on_text` asserting compressed size < 10% of a 1 MB repetitive text tree.
- [ ] **Steps 2–4: fail → implement → pass**  — **Step 5: commit** `feat: zstd tar stage via python-zstandard`

### Task 6: Planner / router

**Files:**
- Create: `excmp/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `FileInfo/Category` (Task 2), `find_tools` (Task 1).
- Produces: `Profile` StrEnum `FAST|NORMAL|EXTREME|INSANE`; `Route` dataclass `(files: list[Path], action: "store"|"pipeline", stages: list[str], reason: str)`; `plan(infos: list[FileInfo], profile: Profile, tools, shrink_media=False) -> Plan` where `Plan.routes` groups: media & COMPRESSED_ARCHIVE & entropy>7.9 → `store` route with human-readable `reason`; everything else → pipeline route (`FAST → ["zstd"]`, `NORMAL → ["sevenzip"]`, `EXTREME → ["precomp","srep","sevenzip"]` degrading to available tools with `Plan.warnings` entries; `INSANE` same as EXTREME until zpaqfranz stage exists, with warning).

- [ ] **Step 1: failing test** — golden routing:

```python
def test_video_routes_to_store(...):   # VIDEO FileInfo → action == "store", "quality" in reason
def test_text_routes_to_pipeline_normal(...):  # TEXT → stages == ["sevenzip"]
def test_extreme_degrades_without_precomp(...):  # tools dict with precomp=None → stages ["sevenzip"], warning mentions precomp
```

- [ ] **Steps 2–4: fail → implement → pass**  — **Step 5: commit** `feat: profile router with lossless media default and graceful degradation`

### Task 7: Verify + engine compress/extract

**Files:**
- Create: `excmp/verify.py`, `excmp/engine.py`
- Test: `tests/test_engine_roundtrip.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `verify.hash_tree(root) -> dict[relpath, sha256]`; `engine.compress(inputs: list[Path], out_path: Path, profile: Profile, ctx) -> CompressResult(archive, orig_bytes, final_bytes, ratio, routes, warnings)`; `engine.extract(archive: Path, out_dir: Path, ctx) -> ExtractResult`. Behavior: stage chain runs left-to-right on a staging copy under `ctx.temp_dir`; store-routed files are zipped (ZIP_STORED) into `stored.zip` payload section; manifest records hashes of ALL inputs; extract replays chain right-to-left then **verifies every output hash against the manifest ledger** and fails loudly on mismatch; output written `.tmp` then `os.replace`.

- [ ] **Step 1: failing test** — end-to-end: build mixed tree (text + fake mp4 + random bin), `compress(..., Profile.NORMAL)`, assert archive exists & result.ratio < 1; `extract`, assert **every** file byte-identical; corrupt one payload byte in a copy → extract raises `VerifyError`.
- [ ] **Steps 2–4: fail → implement → pass**  — **Step 5: commit** `feat: engine with verified roundtrip and atomic outputs`

### Task 8: CLI

**Files:**
- Create: `excmp/cli.py`, `excmp/__main__.py`
- Test: `tests/test_cli.py` (subprocess smoke: `python -m excmp compress`/`extract`/`analyze` on tmp tree)

**Interfaces:**
- Produces: `python -m excmp analyze <path>` (table: file, category, entropy, planned route); `compress <inputs...> -o out.excmp -p fast|normal|extreme|insane`; `extract <archive> -o dir`; exit code 0/1; `--json` flag for machine output (GUI will reuse engine directly, CLI is for testing/benchmarks).

- [ ] **Steps 1–4: fail → implement (argparse, rich-free plain output) → pass**  — **Step 5: commit** `feat: excmp CLI`

### Task 9: Precomp + SREP stages (detection-based, Extreme chain)

**Files:**
- Create: `excmp/stages/precomp.py`, `excmp/stages/srep.py`
- Test: `tests/test_extreme_chain.py` (skipif tools missing)

**Interfaces:**
- Produces: `PrecompStage()` — file-level: `precomp.exe -o<dst> <src>` / restore `-r`; operates on the tar of the staging tree (chain input is always a single file after an initial tar step; `engine` tars staging tree when chain length > 1). `SrepStage()` — `srep64.exe -m3f <src> <dst>` / `-d` to restore. Both `available()` via `find_tools()`.
- Note: chain composition in `engine` becomes: tar → precomp → srep → sevenzip(single file) with manifest stage order recorded; extraction reverses.

- [ ] **Step 1: failing test** — roundtrip a tree containing a zlib-compressed payload (`zlib.compress` of repetitive text written as `.dat`) through the EXTREME chain; assert byte-identical restore AND `extreme_size <= normal_size` on this corpus.
- [ ] **Steps 2–4: fail → implement → pass**  — **Step 5: commit** `feat: precomp and srep stages, extreme chain`

### Task 10: Benchmark harness

**Files:**
- Create: `tools/bench.py`
- Test: manual run (documented in file docstring), not pytest.

**Interfaces:**
- Consumes: `excmp.engine`. Produces: `python tools/bench.py <sample_dir>` → markdown table (profile × {size, ratio, wall time}) written to `docs/benchmarks/<date>-<host>.md`.

- [ ] **Step 1: implement** (no TDD — it's a dev tool that calls tested engine APIs)
- [ ] **Step 2: run on a small real sample, commit results** `feat: benchmark harness + first results`

---

## Follow-up plans (separate documents, in order)
1. **GUI (PySide6)** — queue model, worker thread pool around `engine`, profiles UI, progress/ETA, extract tab.
2. **Video shrink mode** — ffmpeg/SVT-AV1 stage, ffprobe skip rules, quality slider; requires downloading ffmpeg (user permission).
3. **zpaqfranz backend + resume journal** (completes INSANE profile).
4. **Packaging** — PyInstaller, tool downloader with SHA-pinning, README/licenses.
