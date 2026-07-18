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
