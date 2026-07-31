# 12 — "Powerful but lightweight": footprint, RAM budgets, and the on-demand tool strategy (verified 2026-07-31)

> **⚠ Source-study update (2026-07-31, same day, later):** the 7-Zip threading
> and RAM claims below were re-verified against the **actual 26.02 source**
> (doc 19 §3) and two were corrected; SREP was **dropped from all plans**
> (doc 20 §4 / doc 21 §5) so the srep rows/formulas below are historical.
> Corrections flagged inline as **[SOURCE-STUDY …]**.

> The user's constraint was "high performance, better if lightweight but without
> losing any features." This doc resolves that tension with **measured** numbers from
> the actual dev machine (i7-3540M 2C/4T, 16 GB, Win10 19045, Python 3.12.2,
> PySide6 6.11.1, PyInstaller 6.21.0). Figures marked **[measured]** were produced
> live during this research on this hardware — not estimates.

## The formula that falls out of the data

**28 MB core download + ≤15 MB of hash-pinned specialists fetched on demand + hard
RAM caps derived from verified formulas.** Nothing on this hardware class needs more
than ~2 GB steady-state; the app idles under 100 MB; every "power" feature arrives as
a 0.5–19 MB verified download only when a profile first needs it. **Lightweight and
full-featured are not in conflict — the specialists just must not live in the
installer.**

## 1. Packaged footprint [measured]

| Build | On-disk | Zipped (download) | Notes |
|---|---|---|---|
| Baseline `--onedir --windowed` | **122 MB** | ~45 MB (est.) | PyInstaller pulls Qt6Quick (6.3 MB), Qt6Qml (5.1), Qt6Pdf (4.4), Qt6OpenGL, Qt6Network + a **duplicate OpenSSL** (`libcrypto-3.dll` 5.0 MB *and* `libcrypto-3-x64.dll` 4.9 MB), `opengl32sw.dll` 19.7 MB, `qdirect2d.dll` |
| Tuned (excludes + prune) | **71 MB** | **28 MB zip** | `--exclude-module PySide6.QtQml/QtQuick/QtNetwork/QtPdf/QtOpenGL/QtOpenGLWidgets/QtSvg/QtDBus`, then delete `opengl32sw.dll`, `qdirect2d.dll`, `translations/` |

The tuned exe **was launched and verified alive** (offscreen) after pruning.
Irreducible core: Qt6Core 10.0 + Qt6Gui 9.1 + Qt6Widgets 6.3 + python312.dll 6.7 +
three PySide6 `.pyd`s (~11.5 MB). **A PySide6 Widgets app will not go below roughly
55–65 MB on disk / ~25 MB download — that is the floor.**

**Dev environment** [measured from wheel RECORDs]: full `pip install PySide6` = **642
MB** (Essentials ≈204 MB + Addons ≈437 MB; `Qt6WebEngineCore.dll` alone is 195 MB).
The GUI imports only QtCore/QtGui/QtWidgets → **switch `requirements.txt` to
`PySide6-Essentials`** (~69 MB compressed wheel). PyInstaller already skips WebEngine
since nothing imports it, so this mainly fixes dev installs, CI time, and
accidental-import risk.

**RAM** [measured]: packaged app idles at **68 MB working set / 38 MB private**
(offscreen; expect ~90–120 MB rendering on screen). Normal for Qt Widgets — heavier
than 7-Zip's Win32 GUI (~5–10 MB), far below Electron-class apps.

**User expectations (verified installer sizes)**: 7-Zip 26.02 x64 = **1.66 MB**;
NanaZip 6.5 MSIX ≈ **11.3–11.7 MB**; PeaZip 11.x ≈ **10.8 MB**. A 28 MB zip / 71 MB
installed is defensible for Python+Qt — **but the core must stay that size.**

## 2. The tool fleet: everything verified, ~15 MB total

| Tool | Latest (verified) | License | Win binary | Size | SHA-256 discipline at source |
|---|---|---|---|---|---|
| 7-Zip console | **26.02** (2026-06-25), `7z2602-extra.7z` (github.com/ip7z/7zip) | LGPL-2.1 + unRAR | yes | 1.76 MB | **GitHub API `digest` field present** |
| zstd | **1.5.7** (2025-02-19) | BSD-3/GPL-2.0 | yes | 1.75 MB | `.sha256` for source tarballs only — pin our own |
| Precomp | **0.4.7 (2019!)**; repo NOT archived (last push 2025-06-26) but no release in 7 years — treat as frozen | Apache-2.0 | yes | 2.3 MB | none — pin our own |
| zpaqfranz | **64.8** (2026-06-29), repo pushed 2026-07-30 — **very active** | MIT | yes, single exe | 4.29 MB | **best in class**: GitHub digest + author-signed (.p7m) SHA-256 files |
| par2cmdline-turbo | **1.4.0** (2026) | GPL-2.0 | yes | 0.66 MB | GitHub digest present |
| oxipng | **10.1.1** (2026-04-22) | MIT | yes | 0.49 MB | GitHub digest present |
| lepton_jpeg_rust | 0.5.3 repo, **no exe assets** | Apache-2.0 | **no exe** → use `lepton-jpeg-python` **0.5.8** wheel (win_amd64, py3.8–3.14) | wheel | PyPI hashes |
| FLAC | **1.5.0** (2025-02-11) | libFLAC BSD-3; `flac.exe` GPL-2.0+ | yes | 1.32 MB | no digest on that release — pin our own |
| xtool | **0.7.9** (2023-09), repo **archived**; newer = Patreon-only | MIT (GitHub) | yes | 18.8 MB | none — pin our own; always roundtrip-verified |
| SREP | 3.93a (2014), **no official host** (freearc.org dead) — third-party mirrors only | closed freeware | yes | ~1 MB | **[SOURCE-STUDY ⚠ DROPPED from the fleet entirely — doc 20 §4 / doc 21 §5; zpaqfranz CDC + zstd `--long` replace it]** |

**Key new fact for E1:** GitHub's release API now exposes a per-asset `digest`
(sha256) — verified present for 7-Zip 26.02, zpaqfranz 64.8, oxipng 10.1.1, par2
1.4.0. A small `tools/make_manifest.py` can seed `tools/manifest.json` from the API,
then a human pins it in git.

**Downloader design that held up:** manifest entry = `{name, version, url, sha256,
size, exe_relpath, license}`; download to
`%LOCALAPPDATA%\ExtremeCompressor\tools\<name>\<version>\` via temp file → verify
sha256 + size → atomic `os.replace`; hard-fail and delete on mismatch; **never add
the download dir to PATH**; re-hash the exe before first use each run (cheap — all
are ≤19 MB). This is the Scoop/winget manifest model, and it solves SREP
redistribution legally (download-to-user, never bundle).

**Two corrections to earlier plans:**
- **JPEG should NOT be a download** — use the `lepton-jpeg-python` wheel (Apache-2.0,
  in-process, bit-exact). Microsoft publishes no exe, so the wheel is also the only
  zero-build Windows path.
- **`zstd.exe` should not be in the manifest at all** — the `zstandard` wheel already
  embeds libzstd in-process (`excmp/stages/zstdstage.py`). A CLI adds a download and
  a second code path for zero capability.

## 3. Performance envelope on 2C/4T, 16 GB (verified formulas)

**What parallelizes:**
- **zstd**: `-T#`; CLI default 1–4 by physical cores; `zstandard` `threads=-1`
  (current setting) = logical count (4) — fine.
- **7-Zip LZMA2**: x9 uses 2 threads per **block** — **[SOURCE-STUDY ⚠ corrected
  wording, doc 19 §3: `LzmaEnc.c:103-109` spawns a match-finder thread + a coder
  thread per LZMA encoder *instance* (= per block, `totalThreads = 2 ×
  blockThreads`); chunks are sequential *inside* a block]** — more threads splits
  the stream into blocks (different ratio, more RAM). On 2 physical cores
  **`-mmt2` is the sweet spot** — so the engine's default `threads` should be
  **2, not 4** (conclusion unchanged, now source-proven).
- **zpaqfranz**: `-t` defaults to core count; memory is **per-thread**, so `-t2`
  halves RAM vs `-t4` with near-zero speed loss on 2 cores.
- **SREP `-m3`**: single-threaded (`-tN` only applies to -m1/-m2 [measured from
  srep.exe help]); **Precomp**: effectively single-threaded. These two are the
  wall-clock bottleneck of Extreme — nothing to tune, only to warn about in the ETA.
- **FLAC 1.5** (`-j N`) and **oxipng** are multithreaded — free wins for specialists.

**Verified RAM formulas:**
- **LZMA2 compress** (bt4, dict 64 MB–1 GB): **10.5 × dict** (11.5× for ≤48 MB;
  hc4 = 6.5×). **Decompress ≈ 1 × dict.** So `-md=192m` = ~2.0 GB compress / 192 MB
  extract; `-md=512m` = ~5.4 GB — the practical ceiling here. *Remember the
  extract side: archives made with a 512m dict need 512 MB on the recipient's machine.*
  **[SOURCE-STUDY ✓/⚠ doc 19 §3: multiplier confirmed for the solid/single-block
  case (≈10.5×dict + ~8 MiB per block thread; multi-block ≈13×dict/thread) — use
  the exact estimator formula from `CompressDialog.cpp:2942-3016` in the RAM
  planner, not a flat multiplier. AND: since 24.09, **mx9's DEFAULT dict is
  256 MiB on 64-bit** (not 64 MB) — always pin `-md=` explicitly or "plain -mx9"
  costs ~2.7 GB compress on its own]**
- **zstd `--long=31`** = 2 GiB window, raising memory for **both** sides, and the
  decompressor must be invoked with `--long=31`/`--memory` (default decode limit is
  128 MiB). Engine's `window_log=27` (128 MiB) is the correct default; 28–30 is a safe
  opt-in on 16 GB; **31 is not worth the decode-side friction.**
- **SREP** [measured from srep.exe 3.93a help] **[SOURCE-STUDY ⚠ HISTORICAL —
  SREP dropped from all plans (doc 20 §4 / doc 21 §5); kept for reference only]**:
  compression memory = **7–8% of file size** for `-m3`, **3–4%** for `-m4`, 7–9%
  for `-m5`. Decompression: `-mem75%` of RAM by default, overflow to a VM temp
  file; `-m*o` I/O-LZ modes need only 24 MB.
- **zpaqfranz**: block 64 MiB for methods 2–5; RAM ≈ **8 × block/thread (512 MiB) for
  `-m4`**, **16 × block/thread (1 GiB) for `-m5`**.

**Recommended per-profile budgets** (keep the pipeline ≤ ~6 GB so the OS cache still
works and we never swap):

| Profile | Chain settings | Peak RAM | Threads |
|---|---|---|---|
| Fast | zstd-19, window_log 27 | < 1 GB | 2–4 |
| Normal | 7z `-mx9 -md=64m -mmt2` **[SOURCE-STUDY ⚠ `-md=64m` must now be EXPLICIT — bare `-mx9` defaults to a 256 MiB dict since 24.09 (doc 19 §3), which would be ~2.7 GB, not 0.7]** | ~0.7 GB | 2 |
| Extreme | precomp → zstd `--long=27..30` pre-pass or 7z big-dict → 7z `-md=192m -mmt2 -mqs` **[SOURCE-STUDY ⚠ srep stage replaced — dropped from plans (doc 20 §4); `-mqs` added because 7z does NOT type-sort solid blocks by default (doc 19 §5)]** | ~2 GB steady | 2 |
| Insane | … → zpaqfranz `-m4 -t2` (`-m5 -t2` behind overnight warning) | 1 GiB / 2 GiB | 2 |

Stages run sequentially, so budgets **don't stack** — peak is the worst single stage.
**Temp disk (Precomp's 2–5× inflation) remains the bigger constraint than RAM.**

## 4. Startup time and perceived speed

Warm import costs [measured]: `PySide6.QtWidgets` 0.23 s, full `gui.mainwindow`
0.60 s, `windows_toasts` 0.28 s, `comtypes` 0.13 s, `excmp.analyzer` 0.06 s,
`zstandard` 0.03 s. Cold start (HDD-class, first run after boot) is typically 3–10×.

- **Stay `--onedir`** — `--onefile` self-extracts the whole bundle to temp on *every*
  launch (multi-second cold starts) on top of the AV/SmartScreen reasons in E3.
- **Defer `comtypes`**: `gui/winintegration.py:30` imports `comtypes.client` at module
  level and `gui/app.py:13` pulls it at startup; `windows_toasts` is already correctly
  deferred (line 122). Moving the comtypes import into `TaskbarProgress.__init__`
  shaves ~0.1 s warm / up to ~1 s cold for zero cost.
- The big lever is already built (window first, analyzer on a worker). Keep the rule:
  **nothing heavier than QtCore/QtGui/QtWidgets imports before `show()`**; schedule
  remaining init with `QTimer.singleShot(0, …)` after the first frame.
- Memoize `find_tools()` per session so preset cards render instantly.

## 5. FreeArc concepts worth copying (GPL + dead → ideas only)

1. **Data-driven per-type dispatch** — `arc.groups` maps files to groups (`$text`,
   `$exe`, `$wav`), `arc.ini` maps groups to method chains, e.g. `-m4 = mexe+rep:64mb+delta+lzma:8mb / $text=dict:p+lzp+ppmd:8:96mb / $wav=tta`.
   Our planner does this **in code**; externalizing profile→(category→chain+params)
   into a versioned `profiles.toml` gives FreeArc's extensibility (new tool = manifest
   entry + config line + thin Stage class) without recompiling — and the manifest
   already records the executed chain, so extraction stays deterministic.
   *Do this when B2–B6 land more than ~6 specialists, not before (YAGNI).*
2. **`[External compressor]` sections** — our Stage interface + hash-pinned tool
   manifest is the modern, safer equivalent. Keep the Stage ABI deliberately tiny so
   this stays true.
3. **Recovery records** — the one FreeArc feature nothing in our stack has. Modern
   replacement is par2 (Reed-Solomon, strictly stronger than FreeArc's XOR) — see
   doc 10.
4. **Test-before-and-after-every-operation ethos** — already our core guarantee;
   FreeArc validates that this is what users of "extreme" archivers actually rely on.
5. Its `-mx`/`-max` split ("strongest internal" vs "strongest with external tools")
   maps exactly onto Extreme vs Insane profiles that degrade when tools are missing —
   **current design is already right.**

## Sources (highlights)

- pyinstaller.org/en/stable/usage · doc.qt.io/qtforpython-6/package_details ·
  pypi.org/project/PySide6-Essentials
- 7-zip.opensource.jp/chm/cmdline/switches/method.htm (LZMA memory formulas) ·
  github.com/ip7z/7zip/releases · github.com/facebook/zstd (releases + zstd.1.md)
- github.com/fcorbelli/zpaqfranz/releases · mankier.com/1/zpaq (per-thread memory)
- github.com/animetosho/par2cmdline-turbo · github.com/shssoichiro/oxipng ·
  pypi.org/project/lepton-jpeg-python · github.com/xiph/flac/releases
- freearc.sourceforge.net/FreeArc040-eng.htm (arc.ini, -rr, external compressors)
- Local measurements 2026-07-31: PyInstaller onedir builds of the real GUI
  (122/71 MB, 28 MB zip), RAM working set 68 MB, warm import timings, PySide6 wheel
  RECORD sizes, srep.exe 3.93a built-in help (memory percentages per mode)
