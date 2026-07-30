# Third-Party Notices

ExtremeCompressor orchestrates external tools as **separate processes**. None of
them are linked into, or distributed inside, this repository. Each keeps its own
license. "Bundled" below means: may be shipped alongside future binary releases;
"Detected" means: used only if already installed on the user's machine;
"Downloaded" means: fetched to the user's machine by the SHA-pinned tool
downloader (planned), never redistributed by us.

| Tool | Version (checked 2026-07-18) | License | Distribution |
|---|---|---|---|
| 7-Zip (`7z.exe`) | 26.02 | LGPL-2.1 + unRAR restriction | Detected now; bundled later with license text |
| Zstandard (python `zstandard`) | 1.5.x | BSD-3 | pip dependency |
| Precomp | 0.4.8 (dormant upstream) | Apache-2.0 | Detected now; downloadable later |
| SREP | 3.93a beta | Freeware; **commercial license required for redistribution** | Detected / user-side download ONLY — never bundled |
| zpaqfranz | 64.x | FOSS (GPL/MIT heritage) | Planned: downloaded |
| lepton_jpeg_rust | current | Apache-2.0 | Planned: downloaded |
| oxipng | 10.x | MIT | Planned: downloaded |
| ECT | current | Apache-2.0 | Planned: downloaded |
| FLAC | 1.5.0 | BSD (libFLAC) / GPL (flac CLI) | Planned: downloaded |
| qpdf | current | Apache-2.0 | Planned: downloaded |
| FFmpeg (GPL build) | 7.x/8.x | GPL-2.0+ | Planned: downloaded with license text + source offer |
| SVT-AV1 / SVT-AV1-Essential | 4.x | BSD-3-Clause-Clear | Planned: downloaded |
| xtool | 0.7.9 GitHub (archived) / 0.9.5 Patreon | MIT (GitHub) | Detected only; never bundled (depends on game-local proprietary Oodle DLLs, which are never redistributed) |
| TAK / OptimFROG / pingo | — | Closed freeware, redistribution restricted | Detected only; never bundled |

Oodle (`oo2core_*.dll`) is proprietary RAD/Epic software. ExtremeCompressor never
ships it; game-data recompression via xtool uses the DLL already present in the
user's own game installation.

## Python packages

Unlike the tools above these are **linked into the application process**, so
their licenses apply to how we distribute it.

| Package | License | Used for | Notes |
|---|---|---|---|
| [zstandard](https://pypi.org/project/zstandard/) | BSD-3-Clause | the Fast profile | bundles libzstd |
| [PySide6](https://pypi.org/project/PySide6/) | LGPL-3.0 (Qt: LGPL-3.0) | the desktop GUI | Used **unmodified** and **dynamically linked**, which is what LGPL-3.0 requires. Binary releases must ship the LGPL text and keep the Qt libraries replaceable — that rules out PyInstaller `--onefile`, which the roadmap already avoids for SmartScreen reasons. |
| [comtypes](https://pypi.org/project/comtypes/) | MIT | taskbar progress via `ITaskbarList3` | optional at runtime |
| [Windows-Toasts](https://pypi.org/project/windows-toasts/) | Apache-2.0 | completion notifications | optional at runtime |
| [pytest](https://pypi.org/project/pytest/) · [pytest-qt](https://pypi.org/project/pytest-qt/) | MIT | test suite | development only |
| [Pillow](https://pypi.org/project/Pillow/) | MIT-CMU | assembling `docs/images/demo.gif` | development only |

PySide6-Fluent-Widgets was evaluated for the GUI and **rejected**: it is
GPL-3.0, which would force this MIT codebase to relicense. The theme in
`gui/theme.py` is hand-rolled instead.
