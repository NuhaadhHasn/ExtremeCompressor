# Third-Party Notices

**Every licence below was read from a file on this machine on 2026-09-09**, and
the path is given so it can be re-checked. Nothing here is quoted from memory,
from a project's website, or from the previous version of this file — the
previous version was written 2026-07-18, before the tool downloader existed,
and had drifted: it described fetched tools as "planned", omitted six runtime
dependencies that had since been added, and stated three licences less
precisely than the files on disk do.

Where a licence could **not** be established from a file here, it says so
rather than guessing. There is exactly one of those, and it is named.

## How these tools are used, and why it matters

| Relationship | What it means | Distribution obligation |
|---|---|---|
| **Subprocess** | We execute a separate binary. No linking, no bundling. | Runs on the user's machine under its own licence; we redistribute nothing |
| **Wheel (in-process)** | A pip dependency loaded into our process | Its licence applies to how the application is distributed |
| **Downloaded** | Fetched to the user's machine by the SHA-256-pinned downloader (`excmp/toolfetch.py`), verified before install | Never redistributed by us; the user's own copy |
| **Detected** | Used only if already installed | We neither ship nor fetch it |

The repo went **private on 2026-09-01** and there is no distribution, so the
obligations that trigger *on distribution* are not currently engaged. This file
exists anyway, because the moment that changes it has to be right — and because
knowing which of these is GPL is the difference between a shippable build and a
legal problem.

---

## Native tools

### 7-Zip — **detected**, invoked as `7z.exe`

Read from `C:\Program Files\7-Zip\License.txt` (6,031 bytes, mtime 2026-02-11);
version reported by the binary as **7-Zip 26.02 (x64)**.

Not a single licence but a per-component mix, all inside `7z.dll`:

- **LGPL-2.1-or-later** as the main licence for most of the code
- **LGPL + the unRAR restriction** for the RAR decompression engine. The unRAR
  sources may not be used to re-create the proprietary RAR *compression*
  algorithm, and derived use must state that the code may not be used to
  develop a RAR/WinRAR-compatible archiver. This is why this project **never
  ships `unrar.dll`** and reads RAR only through a user-installed 7-Zip.
- **BSD-3-Clause** for LZFSE decompression (Apple Inc) and ZSTD decompression
  (Facebook reference code)
- **BSD-2-Clause** for the XXH64 code

### Precomp — **detected**, invoked as `precomp.exe`

Read from `C:\Program Files\precomp\readme.txt` (the Apache statement is at
line 238, the copyright at 240). **Apache-2.0**, "Copyright 2006-2016 Christian
Schneider".

The same "Legal stuff" section names bundled third-party code under separate
terms, and **none of those licence texts are present on this machine**:
packJPG v2.5k and packMP3 v1.0g (Matthias Stirner), bZip2 1.0.6 (Julian
Seward), zLib 1.2.8 (Gailly/Adler), GifLib 4.1.4 (Eric S. Raymond). packJPG in
particular is *not* Apache-licensed upstream. **If this binary is ever
redistributed, those five need their own review first** — Precomp's own
Apache-2.0 does not cover them.

### SREP / SuperREP — **detected, legacy-only**

Read from `C:\Program Files\srep\src\srep.cpp` lines 1-2 (the same header
appears in `decompress.cpp`, `io.cpp`, `compress.cpp`, `compress_cdc.cpp`,
`compress_inmem.cpp`, `hash_table.cpp` and `hashes.cpp`):

> Copyright (C) 2009-2014 Bulat Ziganshin. All rights reserved.
> Mail … if you have any questions or want to buy a commercial license for the
> source code.

**"All rights reserved", with a commercial licence available on request.** Not
open source. **Never bundled, never fetched** — and no longer used for new
archives at all (B11 removed it from every chain after it failed its own
decompression checksum on 1 of 3 runs). It is still *detected* so that archives
made before that removal can still be extracted, which is why it appears in
the app's tool list marked "legacy".

Its `src` tree also vendors public-domain subcomponents with their own separate
grants — `Common/LZMA2/C/Types.h`, `ThreadsWin32.c/.h`, `ThreadsUnix.h`
(7-Zip heritage), `Encryption/ciphers/aes/aes.c`, and
`Encryption/hashes/siphash`. Those are additional grants, not an exception to
Ziganshin's terms.

### zpaqfranz — **downloaded/placed, licence NOT established here** ⚠️

`tools/bin/zpaqfranz.exe`, 4,288,000 bytes, mtime 2026-09-02, reporting
`zpaqfranz v64.8j-JIT,SFTP,RES-L,HW BLK3,SHA1/2,4,SFX64 55.1 (2026-06-29)`.

**There is no licence file beside it.** `tools/bin/` contains exactly
`flac/`, `qpdf/` and this bare executable. Two independent passes looked for a
`COPYING`, `LICENSE` or readme sibling and found none, so the previous version
of this file — which said "FOSS (GPL/MIT heritage)" — was asserting something
no file here supports.

This is the one gap in this document. It is *used* (Insane profile) and it is
not currently redistributed, so nothing is broken; but before this project is
ever shared, its licence has to be established from upstream and its text
placed beside the binary. Recorded rather than guessed, deliberately.

### FLAC — **downloaded** (hash-pinned), invoked as `flac.exe`

Read from `tools/bin/flac/1.5.0/flac-1.5.0-win/` — all four `COPYING` files
plus `AUTHORS` are present. The split, which matters:

- **`libFLAC` / `libFLAC++`** → Xiph.Org BSD-like, i.e. **BSD-3-Clause**
  (`COPYING.Xiph`: retain notice / reproduce notice in binary form / no
  endorsement using the Xiph.Org name; no patent clause)
- **`flac.exe` / `metaflac.exe`** → **GPL**. `COPYING.GPL` is verbatim "GNU
  GENERAL PUBLIC LICENSE Version 2, June 1991", with no "or later" wording in
  the COPYING file itself.
- documentation → GNU FDL

We invoke `flac.exe`, so **the GPL half is the one that applies to our usage**.
As a subprocess on the user's machine that is fine; bundling it in a
redistributable build would not be.

### qpdf 12.4.1 — **downloaded** (hash-pinned), currently never invoked

Read from
`tools/bin/qpdf/12.4.1/qpdf-12.4.1-msvc64/share/doc/qpdf/manual-html/_sources/license.rst.txt`:

> qpdf is licensed under the Apache License, Version 2.0

**With an at-your-option fallback**, which the previous version of this file
missed. Every shipped header in `include/qpdf/` carries, after the Apache
block (e.g. `Buffer.hh` lines 16-18):

> Versions of qpdf prior to version 7 were released under the terms of version
> 2.0 of the Artistic License. At your option, you may continue to consider
> qpdf to be licensed under those terms.

So: **Apache-2.0, or Artistic-2.0 at the licensee's option.**

It is pinned but **not used by the lossless engine** — B5 measured
`--recompress-flate` rewriting the file, so 0 of 10 real PDFs came back
byte-identical, and the existing `precomp → 7z` route saved 49.5% where qpdf
saved 7.14%. It is kept for Phase C.

### FFmpeg / FFprobe — **not present**

`find_tools()` lists them because they are Phase C tools, and both resolve to
nothing on this machine. **No FFmpeg binary and no FFmpeg licence text exists
here**, so this file records no licence for them. When Phase C fetches a GPL
build, that build's licence text and the corresponding source offer have to be
placed beside it and this section rewritten from the files.

### Oodle, xtool, TAK, OptimFROG, pingo — **not present, never bundled**

`oo2core_*.dll` is proprietary RAD/Epic software. This project never ships it;
if game-data recompression is ever built (B6), it would use the DLL already
inside the user's own game installation. Nothing about it is redistributed.

---

## Python packages — linked into the application process

Every row read from that package's own `dist-info` in
`.venv\Lib\site-packages\`. `License-Expression` is quoted verbatim where the
package provides one.

### Runtime (declared in `requirements.txt`)

| Package | Licence (verbatim) | Notes |
|---|---|---|
| `zstandard` | `BSD-3-Clause` | bundles libzstd; **this is the whole Fast profile** — there is no `zstd.exe` |
| `PySide6-Essentials` (what `requirements.txt` installs since E3; the `PySide6` meta-package adds Addons) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | plus a commercial option. Used **unmodified and dynamically linked**, which is what the LGPL branch requires. A binary release must ship the LGPL text and keep the Qt libraries replaceable — which rules out PyInstaller `--onefile`, as the roadmap already does for SmartScreen reasons |
| `PySide6-Essentials`, `PySide6-Addons`, `shiboken6` | same triple disjunction | pulled in by PySide6 |
| `comtypes` | `MIT` | taskbar progress; optional at runtime |
| `windows-toasts` | (bundled `LICENSE`; Apache-2.0) | completion toasts; optional at runtime |
| `winrt-runtime` and the `winrt-Windows.*` packages | `MIT` | pulled in by windows-toasts |
| `lepton-jpeg-python` | `Apache-2.0` | in-process, bit-exact JPEG recompression. Microsoft ships no exe, so the wheel is the only zero-build Windows path |
| `cryptography` | `Apache-2.0 OR BSD-3-Clause` | licensee's choice. AES-256-GCM for F1 |
| `argon2-cffi`, `argon2-cffi-bindings` | `MIT` | Argon2id KDF |
| `cffi` | `MIT-0` | with a carve-out: subdirectories may state otherwise |
| `pycparser` | `BSD-3-Clause` | pulled in by cffi |
| `par2cmdline-turbo` | **`GPL-2.0-or-later`** | ⚠️ **the one GPL runtime dependency.** The wheel ships `par2.exe`, which we drive **as a subprocess only** — we never link it. A redistributable build that bundles this wheel is distributing a GPL binary, and that has to be handled deliberately rather than by accident |
| `squarify` | `Apache License 2.0` | pure-Python treemap layout |
| `typing_extensions` | `PSF-2.0` | transitive |

### Development only (`requirements-dev.txt`)

| Package | Licence (verbatim) | Notes |
|---|---|---|
| `pytest` | `MIT` | |
| `pytest-qt` | `MIT` | |
| `hypothesis` | `MPL-2.0` | with a carve-out: some vendored files are dual-licensed under their upstream terms. Dev-only, never shipped |
| `sortedcontainers` | `Apache 2.0` | pulled in by hypothesis |
| `Pillow` | `MIT-CMU` | assembles the README GIF. Its own code is MIT-CMU; bundled native libraries have their own terms |
| `PyYAML` | `MIT` | lets a test parse the CI workflow instead of trusting it |

### Installed here but neither declared nor used

- **`pyoxipng` 9.1.1** (`MIT`, "Copyright (c) 2022 Nick Frasser") — a leftover
  from B3's evaluation, which oxipng **lost**: it managed 31.8% where the route
  already present did better. It is imported nowhere in `excmp/`, `gui/` or
  `tools/`, and appears in no requirements file. Safe to uninstall; recorded
  here so nobody mistakes its presence for a dependency.

---

## A note on a rejected dependency

**PySide6-Fluent-Widgets** was evaluated for the GUI and rejected because it is
GPL-3.0. The original reason — that it would force this MIT codebase to
relicense — is no longer the operative one, since the repo is private and not
distributed. The decision stands anyway: the hand-rolled theme in
`gui/theme.py` works, and taking on a GPL-3.0 UI dependency would have to be
re-argued from scratch before any public release rather than inherited.

## Re-checking this file

The commands used to build it, in order: read `excmp/tools.py` for the
discovery list and `excmp/toolfetch.py` for the pinned downloads; list each
install root and read every `LICENSE` / `COPYING` / `readme` found there; and
for Python packages read `License-Expression` (or the licence classifier) from
each `dist-info/METADATA` plus the bundled licence file. Anything that cannot
be read from a file belongs in the ⚠️ category above, not in a table.

## Where a binary release carries these texts

The installer puts `LICENSE`, this file and the full licence texts (`licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`, fetched from gnu.org on 2026-11-25) next to the program, which is what PySide6's LGPL branch asks of a dynamically linked, replaceable Qt (the one-folder build keeps the Qt DLLs as separate files).

### The one GPL program in the installer: `par2.exe`

The installer includes **par2cmdline-turbo 1.4.0** (`par2.exe`, GPL-2.0-or-later) for the recovery-data feature. It is run as a
separate program and never linked into this app. Its licence text is `licenses/GPL-2.0-par2cmdline-turbo.txt` (installed beside the
program). Its source code is available at https://github.com/animetosho/par2cmdline-turbo (the Windows build comes from the
`par2cmdline-turbo` 1.4.0 Python wheel on PyPI, whose packaging is at https://github.com/brenthuisman/par2cmdline-turbo.py).
You may replace that file with your own build of the same program.
