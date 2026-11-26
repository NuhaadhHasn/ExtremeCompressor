# Third-Party Notices

**Every licence below was read from a file on this machine on 2026-09-09**, and
the path is given so it can be re-checked. Nothing here is quoted from memory,
from a project's website, or from the previous version of this file — the
previous version was written 2026-07-18, before the tool downloader existed,
and had drifted: it described fetched tools as "planned", omitted six runtime
dependencies that had since been added, and stated three licences less
precisely than the files on disk do.

Where a licence could **not** be established from a file here, it says so
rather than guessing. Since 0.1.2 every tool the installer carries has its licence text
in `licenses/tools/<tool>/` (copied from the pinned package or from the upstream repository
file named below), and none of them is in that category.

## How these tools are used, and why it matters

| Relationship | What it means | Distribution obligation |
|---|---|---|
| **Bundled** | A hash-pinned, unmodified binary the installer carries and the app runs as a separate program (never linked). Since 0.1.2: 7-Zip (7za), Precomp, zpaqfranz, FLAC, balrogg | We redistribute it: its licence text is installed beside the program (`licenses\tools\`), and the source is named below |
| **Subprocess** | We execute a separate binary. No linking, no bundling. | Runs on the user's machine under its own licence; we redistribute nothing |
| **Wheel (in-process)** | A pip dependency loaded into our process | Its licence applies to how the application is distributed |
| **Downloaded** | Fetched to the user's machine by the SHA-256-pinned downloader (`excmp/toolfetch.py`), verified before install | Never redistributed by us; the user's own copy |
| **Detected** | Used only if already installed | We neither ship nor fetch it |

The repo is **public again since 2026-11-25** and the installer distributes the tools marked *bundled*, so the
obligations that trigger on distribution are engaged. The rule is the project's OSI rule: nothing is bundled whose
licence is not an open-source one, which is why SREP, Oodle, xtool and `unrar` stay out (and why the bundled 7-Zip is
the "Extra" `7za.exe`, which holds no RAR code). Knowing which of these is GPL is the difference between a
shippable build and a legal problem; the GPL ones (FLAC's `flac.exe`, balrogg, par2) are run as separate programs and
never linked, and their source is named in each section.

---

## Native tools

### 7-Zip — **bundled** (7za.exe 26.06), and a full 7-Zip is used when the machine has one

**Bundled:** `7za.exe` from the official "7-Zip Extra" package `7z2606-extra.7z` (GitHub release 26.06 of
`ip7z/7zip`, 1,758,340 bytes, sha256 `396c180f…e5f104` = GitHub's own digest, confirmed on the downloaded bytes
2026-11-26; `x64/7za.exe` inside it is 1,328,640 bytes, sha256 `dd3757f3…84ffa`). It runs standalone and reads and
writes 7z, zip, tar, gzip, bzip2, xz, zstd and cab; its `7za.exe i` format list has **no RAR**. Licence read from the
`License.txt` inside that package (`licenses/tools/7zip/License.txt`, 5,188 bytes): the **GNU LGPL** for most of the
code, **BSD-3-Clause** (LZFSE, ZSTD decode) and **BSD-2-Clause** (XXH64). **That file has no "unRAR licence
restriction" section, because this build holds no unRAR code** (the full installer's `License.txt` is 6,031 bytes and
does have it): that is why the Extra build is the one that ships. Source: https://github.com/ip7z/7zip/releases/tag/26.06.

**Used from the machine when present:** a full 7-Zip (`C:\Program Files\7-Zip`, version 26.02 read from its banner
here) is preferred over the bundled one while it meets the 26.02 security floor, because it also opens RAR and ISO.
It is **detected, not shipped**: its `7z.dll` carries the LGPL + unRAR-restricted RAR engine, and this project never
ships `unrar.dll` or the full 7-Zip.

### Precomp — **bundled** (0.4.7), invoked as `precomp.exe`

The zip `precomp.zip` of release v0.4.7 (2,300,841 bytes, sha256 `fcd30831…de0b`), whose `windows\` folder
(`precomp.exe`, `precomp32.exe`, `precomf.exe`, `precomf32.exe`) is what ships. Licence read from the `readme.txt` in that
zip (`licenses/tools/precomp/readme.txt`, "Legal stuff", lines 229-252) and the upstream `LICENSE`
(`licenses/tools/precomp/LICENSE-Apache-2.0.txt`): **Apache-2.0**, "Copyright 2006-2016 Christian Schneider". (An
earlier comment in `excmp/toolfetch.py` named a restrictive licence for it; that was wrong, and is corrected.)
The upstream repository also reports Apache-2.0.

The same section names the code embedded in the binary: **packJPG v2.5k and packMP3 v1.0g (Matthias Stirner;
upstream repositories `packjpg/packJPG` and `packjpg/packMP3`, both reported as LGPL-3.0)**, **bZip2 1.0.6** (Julian
Seward, BSD-style), **zLib 1.2.8** (Gailly and Adler, zlib licence) and **GifLib 4.1.4** (Eric S. Raymond, X11-style).
All are open-source licences. The LGPL parts are statically part of `precomp.exe`; the LGPL text is
`licenses/LGPL-3.0.txt`, and the sources are https://github.com/schnaader/precomp-cpp/tree/v0.4.7 (Precomp, with the
others vendored or linked as its readme lists) and the two packJPG/packMP3 repositories above. You may replace the
installed `precomp.exe` with your own build; the app will then not run it from that folder, because every file there is pinned by SHA-256.

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

### zpaqfranz — **bundled** (64.8, "v64.8j"), invoked as `zpaqfranz.exe`

Release 64.8 (2026-06-29) of `fcorbelli/zpaqfranz`, asset `zpaqfranz.exe`: 4,288,000 bytes, sha256
`8c832075…fa533`. GitHub's digest for that asset and the file used for every measurement in this repository since
2026-09-02 are byte-identical. It reports `zpaqfranz v64.8j-JIT,SFTP,RES-L,HW BLK3,SHA1/2,4,SFX64 55.1 (2026-06-29)`.
(The previous version of this section said its licence could not be established: the file had arrived with no
licence beside it. It is now read from upstream.)

Licence: **MIT**, "Copyright (c) 2021-2026 Franco Corbelli" (upstream `LICENSE`, also the header of `zpaqfranz.cpp`;
`licenses/tools/zpaqfranz/LICENSE.txt`). Upstream's `COPYING` (`licenses/tools/zpaqfranz/COPYING.txt`, 12,045 bytes)
is its own list of the other authors' code inside it, and it ships too: ZPAQ 7.15 and its parts (public domain,
Matt Mahoney), libtomcrypt AES and Salsa20 (public domain), libdivsufsort (MIT), Stephan Brumme's CRC32, MD5 and SHA-3
(zlib licence), xxHash and LZ4 (BSD-2-Clause), zstd (BSD-3-Clause), BLAKE3 (CC0 or Apache-2.0), HighwayHash and
Mbed TLS (Apache-2.0), wyhash (Unlicense), LZAV (MIT), a Twofish implementation described there as
"almost-unrestricted", and, for optional mounting features, libfuse (LGPL) and WinFsp (GPLv3 with the FLOSS
exception). Every entry upstream lists is an open-source or public-domain grant; **which of them are compiled into
this particular Windows binary has not been checked here**, and this program never uses mounting. Source:
https://github.com/fcorbelli/zpaqfranz/releases/tag/64.8.

### FLAC — **bundled** (1.5.0), invoked as `flac.exe`

Read from `tools/bin/flac/1.5.0/flac-1.5.0-win/` — all four `COPYING` files
plus `AUTHORS` are present. The split, which matters:

- **`libFLAC` / `libFLAC++`** → Xiph.Org BSD-like, i.e. **BSD-3-Clause**
  (`COPYING.Xiph`: retain notice / reproduce notice in binary form / no
  endorsement using the Xiph.Org name; no patent clause)
- **`flac.exe` / `metaflac.exe`** → **GPL**. `COPYING.GPL` is verbatim "GNU
  GENERAL PUBLIC LICENSE Version 2, June 1991", with no "or later" wording in
  the COPYING file itself.
- documentation → GNU FDL

We invoke `flac.exe`, so **the GPL half is the one that applies to our usage**. It is
run as a separate program and never linked, and the installer ships it with its
licence texts (`licenses/tools/flac/COPYING.GPL`, `COPYING.LGPL`, `COPYING.Xiph`, `AUTHORS`)
and the pinned `Win64` folder only. Source: https://github.com/xiph/flac/releases/tag/1.5.0.
You may replace the installed copy with your own build; the hash pin then rejects the
changed file and the app does not run it from that folder.

### balrogg — **bundled** (1.4), invoked as `balrogg-x86_64.exe`

Release 1.4 of `iczelia/balrogg` (the Ogg Vorbis / Opus specialist, B13): one bare executable, 247,315 bytes, sha256
`b3a52670…97db2` (GitHub's asset digest, confirmed on the bytes). Licence: **GPL-3.0** (the repository's `COPYING`,
byte-identical to `licenses/GPL-3.0.txt`; also at `licenses/tools/balrogg/COPYING.txt`). Run as a separate program,
never linked. Source: https://github.com/iczelia/balrogg/releases/tag/1.4. (Its own banner prints "balrogg 1.3"; the
hash is what identifies the file.)

### qpdf 12.4.1 — **downloadable** (hash-pinned), never invoked, **not bundled** (87 MB)

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
relicense — is not the whole story now that the installer distributes the app.
The decision stands: the hand-rolled theme in
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

### The other programs in the installer (since 0.1.2)

7-Zip's `7za.exe` (LGPL), Precomp (Apache-2.0 with LGPL, BSD-style and zlib parts), zpaqfranz (MIT with the credits in its
`COPYING`), FLAC's `flac.exe` (GPL-2.0, with BSD-3-Clause libFLAC) and balrogg (GPL-3.0) live under
`_internal\tools\bin\<tool>\<version>\` and their licence texts under `licenses\tools\<tool>\`, installed beside the
program. Each is a separate program run by this application, not part of it. Their sources are linked in the sections above;
you may replace any of them with your own build, and the application will then refuse the changed file (every file is pinned
by SHA-256) rather than run it.
