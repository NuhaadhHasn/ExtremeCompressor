# 08 — Archiver product features: what to adopt from 7-Zip / PeaZip / NanaZip / FreeArc (verified 2026-07-31)

> Question answered: which *product features* (not codecs — see docs 04/06 for those)
> from the big open-source archivers should ExtremeCompressor adopt, what is the
> cheapest **legal** route for each in Python on Windows, and what should we
> deliberately skip to stay lightweight?
>
> Key legal reality up front: **we cannot copy code from any of them.** PeaZip is
> LGPLv3 Free Pascal, FreeArc is GPL and dead, 7-Zip is LGPL C++ — all incompatible
> with (or useless to) our MIT Python codebase. What we *can* do is (a) shell out to
> `7z.exe` as we already do, and (b) imitate features — ideas are not copyrightable.

## 7-Zip (mainline) — v26.02, 2026-06-25

License: LGPL + unRAR restriction on the RAR decoder + BSD-3 parts. Actively maintained.

Recent history that matters to us (from history.txt):
- 25.00 (2025-07): >64-thread compression, bzip2 +15-40% speed, symlink CVE fixes
  (CVE-2025-11001/11002); 25.01 added stricter symlink security.
- 26.01 (2026-04): new `-spo` extraction path switch. 26.02 (2026-06): security fixes
  (NTFS handler heap overflow).
- **zstd**: mainline 7-Zip *reads* zstd (since 24.01/24.05) but **still cannot create**
  zstd archives in 2026 — only the mcmilk 7-Zip-zstd fork (v1.5.7-R2, active) and
  NanaZip can. **We already write zstd via the `zstandard` wheel — we are ahead of
  mainline 7-Zip here.**

Product features reachable from the `7z.exe` CLI we already invoke:
- **~40 read formats**: 7z, ZIP, TAR, RAR/RAR5 (incl. WinRAR 7 big dictionaries), ISO,
  CAB, MSI, WIM, VHD/VHDX/VMDK, DMG, NTFS/FAT/EXT images, SquashFS, RPM, DEB, NSIS,
  standalone .zst… Write: 7z, ZIP, TAR, XZ, BZIP2, GZIP, WIM.
- Listing without extraction: `7z l -slt` (machine-parseable key=value blocks).
- Integrity test `7z t`; hash tool `7z h -scrc{SHA256|CRC64|BLAKE2sp|XXH64|*}`.
- AES-256 for .7z/.zip (`-p`, `-mem=AES256`), header encryption `-mhe=on`.
- Split volumes `-v100m`; SFX (`-sfx`, 7z-format only); update-in-place (`u`, `rn`);
  stdin/stdout streaming.
- Has **no** recovery record, no cross-file dedup beyond solid blocks, no password
  manager, no secure delete.

## PeaZip — v11.2.0 (2026), LGPLv3, Free Pascal

Actively maintained. Architecturally it is *us in Pascal*: a front-end orchestrating
7z/p7zip, zpaq, brotli/zstd and other CLI backends.

Features: 200+ read formats; archive conversion (extract+repack); split volumes; SFX;
AES/Twofish/Serpent; **keyfile two-factor** (password + keyfile); encrypted password
manager; secure delete; checksum tools; full file manager; batch operations; **export
any GUI task as a reusable command line**; context-menu integration. New in 11.2: an
**F12 "function picker"** — a command palette for an archiver (see doc 11).

## NanaZip — v6.5 stable / 7.0 preview (July 2026)

Own code MIT (legally readable!), but embeds 7-Zip code (LGPL+unRAR) — never vendor
its `SevenZip` tree. Feature-wise it is 7-Zip-ZS + Windows-11 packaging: signed MSIX
via Microsoft Store/winget, modern cascade context menu (IExplorerCommand), Mica/dark
mode, RHash hash suite (BLAKE3, SHA-3…), hardened binaries (CFG, CET). Its lesson for
us is **distribution** (Phase E), not engine features.

## FreeArc (historical, GPL, dead ~2016) — the ideas that survive it

It pioneered our whole concept: per-filetype method dispatch (`arc.groups`/`arc.ini`),
external-compressor plugin sections, and:
- **Recovery record (`-rr`)** — damage-repair data appended to the archive. The one
  trust feature nothing in our stack has; WinRAR-class. Modern replacement: par2
  (doc 10).
- Smart solid update (only changed solid blocks recompressed) — v2+ idea at best.
- Its XOR-based recovery record was self-documented as weaker than RAR's → use real
  Reed-Solomon (par2), not XOR (see doc 10).

## Closed references (what the market values)

- **WinRAR 7.23 (~$29)**: recovery records + recovery *volumes* + repair command are
  its moat; everything else we can match.
- **Bandizip 7 ($35 Pro)**: paywalls password manager, password recovery, archive
  repair — i.e. the market prices "repair + password tooling" at $35.

## Legal findings

**RAR**: *creating* RAR is legally impossible forever (proprietary; unRAR license
forbids re-creating the compressor; Fedora classifies unRAR as non-free). *Reading*
RAR: best route is the one we already have — shell out to installed `7z.exe`
(its unRAR-derived decoder is 7-Zip's problem, not ours; executing a user-installed
binary imposes zero obligations on MIT code). Never bundle unrar.dll — it would break
the MIT-clean requirement for SignPath signing (E4). Alternatives if ever needed:
libarchive/bsdtar (BSD, ships in Windows 10+, RAR5 gaps), `rarfile` PyPI (ISC,
listing-only parser).

**License compatibility summary**: `cryptography` (Apache-2.0/BSD), `zstandard` (BSD),
`squarify` (Apache-2.0), `rarfile` (ISC), `libarchive-c` (CC0) — all MIT-compatible
pip deps. par2cmdline-turbo (GPL) — subprocess only, downloaded not bundled (same
posture as SREP). py7zr (LGPL-2.1) — allowed but redundant while 7z.exe is required.

## The minimal set that makes us "a real archiver" (decision)

All but one item is a thin wrapper over the `7z.exe` we already shell out to
(`excmp/stages/sevenzip.py` already implements compress/extract/test):

1. **Open/extract other people's archives** (zip/7z/rar/tar/iso/cab/msi…) — magic-byte
   detect non-.excmp input → `7z x`. The single feature that turns a one-way
   compressor into an archiver. Effort S.
2. **Browse/list before extracting** — parse `7z l -slt`; for .excmp the manifest read
   is free. Effort S-M.
3. **Test/deep-verify** — already planned (D5).
4. **Encryption with hidden filenames** — container-level AES-256-GCM, *not* 7z `-p`
   (full analysis in doc 10). Effort M.
5. **Split volumes** (.excmp.001…) — pure-Python chunking + per-part hashes. Effort S-M.
6. **Standard-format export** (.7z/.zip output checkbox) — kills the lock-in
   objection. Effort S.
7. **Archive conversion** ("Convert & shrink": zip/rar → .excmp with an honesty
   report *why* it did or didn't help) — parity feature elsewhere, a **signature
   feature** with our analyzer. Effort M.

**Deliberately skipped** (with reasons, so this decision stays made):
- File manager (dilutes the drop→analyze→queue identity; doubles GUI surface)
- Password manager (scope creep, security liability; `keyring` if ever)
- Secure delete (ineffective on SSDs — shipping it would contradict the honesty brand)
- RAR creation (legally impossible)
- Update-in-place (wrong for a solid multi-stage container; "repack to update")

## Sources (highlights)

- 7-zip.org/history.txt · github.com/mcmilk/7-Zip-zstd · github.com/M2Team/NanaZip
  (License.md) · peazip.github.io · fedoraproject.org/wiki/Licensing:Unrar
- freearc.sourceforge.net · win-rar.com/whatsnew · bandisoft.com edition comparison
- rarfile.readthedocs.io · libarchive.org · learn.microsoft.com/windows/tar
