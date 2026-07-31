# 18 — Source study: FreeArc (orig + Next docs) and par2cmdline-turbo

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference. Commits studied: **freearc-orig
> `298ae5fece821c4a187f782df034bbd9e029688f`** (2009-10-11 SVN-era mirror,
> github.com/svn2github/freearc), **freearc-next
> `d56aeb4e6231a73f3715d5d9adbe8ce5a26cb055`** (2023-12-25,
> github.com/Bulat-Ziganshin/FA — the author's design-doc repo), **par2turbo
> `033424e74bdb27a053a088e8e58fb380d8ed1498`** (2026-06-11,
> github.com/animetosho/par2cmdline-turbo).
>
> ⚠️ **License boundary:** FreeArc code (incl. cls.h, CELS.h, unarc) is
> GPL; par2cmdline-turbo is GPLv2+. Parameter tables, formats, algorithms,
> and grammar semantics extracted only — no code, no header copying.
> Cleanroom re-expression from this report is the intended path.

## Architecture

- **freearc-orig** — Haskell orchestrator (Arc.hs, Cmdline.hs, Options.hs,
  ArcCreate/ArcExtract, ArhiveFileList.hs sorting/grouping,
  ArhiveStructure.hs format, ArcRecover.hs RR) over a C++ codec layer
  (`Compression/` — REP, Dict, Delta, Tornado, LZMA+BCJ/BCJ2, PPMD, GRZip,
  MM/TTA, LZP, External). Everything is driven by a text "method string"
  language (`rep:96m+exe+lzma:...`) resolved through a substitution table.
  `Unarc/` is a standalone minimal C++ extractor (also built as unarc.dll
  for installers); `Compression/_CLS/cls.h` + `Compression/CLS/C_CLS.cpp`
  is the external-codec plugin ABI.
- **freearc-next** — the author's (Bulat Ziganshin) design-doc repo: .arc
  format spec (FreeArc-archive-format.md), a redesigned format
  (New-archive-format.md, How-to-improve-the-archive-format.md), an ECC
  redesign (Recovery-record.md), FA 0.11/0.20 release notes (dedup, zstd,
  Lua), and **CELS** — the successor of CLS.
- **par2turbo** — par2cmdline 0.8.x with computation kernels (GF16, MD5,
  CRC32, matrix inversion) swapped for ParPar's SIMD backend
  (`parpar/gf16`, `parpar/hasher`), OpenMP replaced by C++11 threads.
  CLI/semantics identical to par2cmdline. MSVC solution in-tree; upstream
  publishes prebuilt win-x64/arm64 binaries.

## Answers

### 1. arc.ini dispatch / method tables

Canonical embedded defaults: `Compression.hs:352-463`
(`builtinMethodSubsts`); resolution machinery `decode_method`/`subst`/
`split_to_methods` at `Compression.hs:300-349` (line 340: a bare `m1/m2`
pair auto-expands to `[("","exe+"++b),("$obj",b),("$text",t)]`). `#` is a
digit wildcard expanded 1..9 (`Compression.hs:347`). Key lines: `-m# =
#rep+exe+#xb / $obj=#b / $text=#t` (359), `#b = #rep+#bx` (375), rep ladder
(376-383), `#xb = delta+#binary` (395), binary ladder = tor:3 / tor:96m /
lzma:96m:fast:mc8 / lzma:96m:normal:mc16 / lzma:16m..255m:max (398-406),
text ladder (363-371), `$wav`/`$bmp`/`$compressed` groups (434-462).
Resulting table:

| -m | default (binary) | $obj | $text | $wav | $bmp | $compressed |
|---|---|---|---|---|---|---|
| 0 | storing | — | — | — | — | — |
| 1 | tor:3 (`$exe=exe+tor:3`) | tor:3 | tor:3 | tta:m1 | mm:d1+tor:3:t0 | — |
| 2 | rep:96m+exe+tor:96m:h64m | rep:96m+tor:96m:h64m | grzip:m4:8m:32:h15 | tta:m1 | mm:d1+tor:3:t0 | rep:96m+tor:3 |
| 3 | rep:96m+exe+delta+lzma:96m:fast:mc8 | rep:96m+delta+lzma:96m:fast:mc8 | dict:p:64m:85%+lzp:64m:24:h20:92%+grzip:m3:8m:l | tta | mm+grzip:m4:l:a | rep:96m+tor:3 |
| 4 | rep:96m+exe+delta+lzma:96m:normal:mc16 | rep:96m+delta+lzma:96m:normal:mc16 | dict:p:64m:80%+lzp:64m:65:d1m:s16:h20:90%+ppmd:8:96m | tta | mm+grzip:m1:l2048:a | rep:96m+tor:c3 |
| 5 | rep:128m+exe+delta+lzma:16m:max | rep:128m+delta+lzma:16m:max | dict:p:64m:80%+lzp:80m:105:d1m:s32:h22:92%+ppmd:12:192m | tta | mm+grzip:m1:l2048:a | — |
| 6 | rep:256m+exe+delta+lzma:32m:max | … | same as 6-text | tta | same | — |
| 7 | rep:512m+exe+delta+lzma:64m:max | … | same | tta | same | — |
| 8 | rep:1024m+exe+delta+lzma:128m:max | … | same | tta | same | — |
| 9/x | rep:2040m+exe+delta+lzma:255m:max | … | same | tta | same | — |

Fast-decompression family `-m#x` (360, 386-395); external-PPMonstr family
`#p` (414-422); `#q` = rep+delta+pmm (424-432). Extensions→groups live in
**arc.groups** (`Installer/ini/arc.groups:19-409` — ordered sections
`$text`(19), `$binary`(162), `$default`(164), `$exe`(171), `$iso`(188),
`$obj`(231), `$bmp`(237), `$wav`(247), `$mod`(264), `$precomp`(278),
`$jpg/$jpgsolid`(368-371), `$compressed`(372)); loaded via
`aDEFAULT_GROUPS_FILE = "arc.groups"` (`Options.hs:392`,
`Cmdline.hs:400-432`). The shipped `Installer/ini/arc.ini` (11-333) is a
*community-tuned* override layering external compressors (ccm, nanozip,
durilca, rar…) over the same grammar — grammar evidence only, don't copy
its tool set.

### 2. Solid-compression file order

Default order is **`"gerpn"`** (`Options.hs:404`, applied at
`Cmdline.hs:637-644`; disabled for -m0/fake/very-fast compressors).
Comparator machinery `ArhiveFileList.hs:36-106`: dirs first (`partition
fiSpecialFile`, 43), then per sort char (`key_func`, 89-99): **g** =
arc.groups group number → **e** = lowercased extension → **r** =
"intelligent reorder" (116-149: files >16 KB with equal (ext,size) or equal
(basename, size within 0.5-2×) get the same bucket number via two hash
tables — clusters near-identical files for REP even across directories;
then stable sort on `(bucket, size, basename, directory)`, 148) → **p** =
packed directory path → **n** = basename. Also available: `s` size, `t`
time, and an `i` "intellectual" mode (72-85) grouping by 3-char basename
prefix with singletons pulled out by size.

### 3. rep / srep

`rep` = in-archive long-range LZ77 preprocessor,
`Compression/REP/rep.cpp:1-27` (header comment): finds only large matches
(default MinLen **512**) at huge distances, outputs (len,offset), memory
overhead only **1/4 of buffer** — vs RZIP/LZP it uses a sliding window
advancing 1/16 buffer, "almost ideal" hash, direct hashing without chains,
tag bits inside hash entries, and indexes only 1/√L of L=MinLen/2 blocks.
Defaults `C_REP.cpp:14-23`: BlockSize (=dictionary=max match distance)
64 MB, MinCompression 100%, MinMatchLen 512, HashSizeLog auto, Barrier
INT_MAX, SmallestLen 512, Amplifier 1; grammar
`rep:BlockSize:MinCompression%:MinMatchLen:dBarrier:sSmallestLen:
hHashSizeLog:aAmplifier` (`C_REP.cpp:49-61,93-130`). **Decompression
memory = BlockSize** (`C_REP.h:44`) — why -m9's rep:2040m needs 2 GB to
*unpack*. **srep** is a separate standalone tool (not in either repo);
lineage documented at `freearc-next/0.11/Release-notes.md:29`: SREP
introduced **Future-LZ** (matches stored as "future references" so the
decompressor keeps only data needed for later matches — guaranteed speed,
unpredictable memory), and FA'Next's `-dup` full-archive dedup
(Release-notes.md:18-35) is the successor idea: content-defined chunking +
VMAC/SHA-256 dedup, presented explicitly as "alternative to the REP
filter" (~4% bigger archive, decompress RAM 735→179 MB in his test).
Modern OSS equivalent of the rep idea: zstd `--long` long-distance
matching.

### 4. Preprocessors

- **dict** (`Compression/Dict/dict.cpp:1-60`; params `C_Dict.cpp:9,86-87`):
  word frequency table over the block (hash of 4-byte fragments, 2-byte
  counters), words seen ≥5 times get 1-2 byte codes ranked by count×len;
  rewrites text with codes + escapes; skipped if projected ratio below
  threshold (`dict:p:64m:80%` = preserve-mode, apply only if ≤80%). Gain:
  ~5-15% on text before LZ77/PPMd. **Verdict: skip in v1** — modern
  zstd/lzma recapture most of it.
- **exe** (= BCJ x86 E8/E9): FreeArc simply reuses 7-Zip's Bra86 filter —
  `Compression/LZMA2/C_BCJ.cpp:5` includes `C/Bra86.c` (`x86_Convert`),
  registered as method `"exe"` (`C_BCJ.cpp:50-60`); `bcj2` alias `exe2`
  also present (arc.ini:325). Converts relative CALL/JMP targets to
  absolute so identical call sites compress. Gain: 5-10% on x86 binaries,
  nearly free. **OSS: trivially** — 7z/xz expose BCJ; Python can pre-filter
  via `lzma.FORMAT_RAW` filter chains. Adopt.
- **delta** (`Compression/Delta/Delta.cpp:1-24`): detects **tables of
  fixed-width binary records** (6+ repeats of same byte at same stride →
  fast monotonic check → slow exact-boundary check), then subtracts
  successive column values and reorders columns; ~20 MB/s claimed. Gain:
  big (2-4×) on struct arrays, zero elsewhere. Closest OSS is 7-Zip's
  simple `Delta:N` filter (fixed distance, no detection). **Verdict:
  medium value, post-v1; or route known-stride data to 7z `-mf=Delta:N`.**

### 5. Recovery records

- **Original -rr** (`ArcRecover.hs:42-63` scheme comment; writer 73-181):
  archive cut into sectors (auto size: "4% → 512 B, 2% → 1 KB, 1% → 2 KB…",
  119-123); RR = N recovery sectors + CRC32 of every archive sector;
  archive sector *i* is XORed into recovery sector `i mod N` (149-162).
  Two RECOVERY_BLOCKs written: sectors, then CRCs+geometry (175-181);
  footer written *again after* the RR so the footer itself is recoverable.
  Repair (284-415): CRC scan finds bad sectors; a bad sector is
  recoverable **only if it is the sole bad sector mapping to its recovery
  sector** (310-314). Default dose: 4%/2%/1% by archive size (79-81).
  **Failure modes** (why weaker than RAR): pure XOR parity ⇒ 2 bad sectors
  in the same residue class = both unrecoverable; burst damage spanning ≥N
  sectors kills recovery; and the author's own verdict —
  `freearc-next/Recovery-record.md:16-22`: metadata is not self-recovering;
  "*2 deliberate shots*" (first byte of directory record + first byte of
  RR) kill an archive with RR of any size, because every record is gated
  by a single CRC.
- **FA'Next redesign** (`Recovery-record.md:1-67`): sector-level FEC with
  real ECC — recover from any N survivors (Reed-Solomon-like, N≤~64K with
  interleaved "cohorts", §1); RR at archive end (§2); every metadata record
  **self-describing**, metadata ECC at ~10× redundancy (§3-4); optional
  per-sector geometry/ID/checksum (§6); directory records get their own
  high-redundancy ECC (§8).
- **vs PAR2 / par2cmdline-turbo:** PAR2 already *is* the §1-§5 design:
  GF(2^16) Reed-Solomon over ≤32768 source blocks, every packet
  self-describing + MD5-checked + duplicated across .par2 volumes
  (metadata redundancy for free), external sidecars. The only redesign
  feature PAR2 lacks is interleaving parity *inside* the host archive —
  irrelevant for a sidecar design. **Confirmed: par2cmdline-turbo is the
  right F3 choice.** Alternatives checked: ParPar (creation-only, no
  repair — used *as* turbo's backend), zfec/wirehair (libraries, no
  file-format/verify ecosystem), RAR RR (proprietary).

### 6. unarc + CLS (the repack-installer plumbing)

Minimal extractor: `Unarc/unarc.cpp` (105 lines; real logic header-only:
`ArcStructure.h`, `ArcCommand.h`, `ArcProcess.h`), with installer GUI
variant (29-89) and a DLL build `unarcdll.cpp` exporting exactly one
symbol — `unarc.def: FreeArcExtract`, signature `unarcdll.h:3-6`:

```c
typedef int __stdcall cbtype(char *what, Number int1, Number int2, char *str);
extern "C" int __cdecl FreeArcExtract(cbtype *callback, ...);  /* varargs = CLI-style strings */
```

**This is the entry point ISDone.dll drives.** The codec plugin ABI is
**CLS** — `Compression/_CLS/cls.h`: single export
`extern "C" int __cdecl ClsMain(int operation, CLS_CALLBACK callback,
void* instance)` (22-25); callback `int __cdecl CLS_CALLBACK(void*
instance, int op, void* ptr, int n)` (15). Operations:
CLS_INIT/DONE/FLUSH/COMPRESS/DECOMPRESS/PREPARE_METHOD (28-33); callback
ops: CLS_FULL_READ 4096 / CLS_PARTIAL_READ 5120 / CLS_FULL_WRITE 6144 /
CLS_PARTIAL_WRITE 7168 (+i for stream i), CLS_GET/SET_PARAMSTR,
CLS_MEMORY, CLS_BLOCK etc. (36-53). Host side: FreeArc scans its exe dir
for `cls-*.dll`, loads any exporting `ClsMain`, method name = filename
minus `cls-` (`Compression/CLS/C_CLS.cpp:87-116`) — exactly the hook
xtool's `cls_xtool` implements (see doc 13 §7). FA 0.11 added
`cls64-foo.dll` lookup. Successor **CELS**
(`freearc-next/CELS/README.md:40-56`): everything collapses to one
function `Cels(method, service, inbuf, insize, outbuf, outsize, ud, cb)`
with 64-bit sizes.

### 7. Archive format — what .excmp should borrow

Original (.arc), `freearc-next/FreeArc-archive-format.md` +
`ArhiveStructure.hs`: block types `DESCR/HEADER/DATA/DIR/FOOTER/RECOVERY`
(315-320); signature `"ArC\1"` (36). **Every control block is followed by
a LOCAL DESCRIPTOR**: `(signature, blType, blCompressor, origSize,
compSize, dataCRC) + CRC-of-descriptor` (52-63; doc 13-23). Archive open =
scan last 4096 bytes (`aSCAN_MAX`, 42) for the footer descriptor; FOOTER
lists all control blocks (relative positions), lock flag, RR settings,
**archive comment** (doc:47-63). Broken-archive path:
`findBlocksInBrokenArchive`/`scanArchiveSearchingDescriptors` (95-155)
walks the file backwards in 8 MB windows finding descriptors by signature.
RR is written after the footer, then a second footer follows the RR
(doc:68). DIR block = solid-block list + dirname list + SoA file list
(doc:26-44); varints 1-9 bytes.

FA'Next redesign worth stealing from (`How-to-improve….md:35-63`,
`New-archive-format.md:10-47`): chain-link control blocks backwards via
descriptors, reversed-byte-order descriptor with **dynamic signature =
checksum of next 8 bytes** (rolling-hash findable, checksums recursively
authenticate each other), inline tiny blocks into descriptors (18-byte
minimum archive), bit-flag optional fields, custom fields as (ID,len,data)
with mandatory-bit semantics, separate extension field for filenames
(-10% directory size).

**For .excmp borrow:** (a) trailing self-CRC'd descriptor after every
metadata block + signature scan-back = truncation recovery; (b)
self-describing footer with comment + tool-versions; (c) SoA file table
with dir-number indirection; (d) custom-field TLVs with "mandatory" flag
for forward compat.

### 8. Tornado profiles (design gradient)

`Compression/Tornado/Tornado.cpp:38-52` `std_Tornado_method[]`, modes
**0-11**: 0 = storing; 1 = bytecoder + 16 KB hash + 1 MB buffer, greedy —
LZ4-class; 2 = bitcoder, 64 KB/2 MB; 3 = **hufcoder + table-detection on**
(128 KB hash, 4 MB); 4 = 2 MB hash + caching MF level 1, 8 MB; 5 =
**arithmetic coder + lazy parsing** (16 MB buf) — the default (55); 6 =
row 8, 32 MB hash, 64 MB buf; 7 = row 32, 128 MB hash, caching MF 5,
256 MB buf + auxhash; 8 = row 128, 512 MB hash, 1 GB buffer; 9 = row 256,
2 GB hash; 10-11 = deeper caching MF + bigger auxhash. The ladder is:
entropy-coder class → hash size/associativity → buffer(=window) → parser
(greedy→lazy) → match-finder caching depth → auxiliary hash. (zstd covers
this whole gradient today.)

### 9. par2cmdline-turbo CLI (F3)

`src/commandline.cpp:92-145` usage. Commands `par2 c|v|r <par2file>
[files]` (100-105). Create: `-b<n>` block-count (**default 2000**, 127),
`-s<n>` block-size (multiple of 4; don't combine with -b, 364-386),
`-r<n>` redundancy % (**default 5%**, 129) or `-r<g|m|k><n>` target size
(130), `-c<n>` recovery-block-count (131), `-u` uniform / `-l` limit /
`-n<n>` number of recovery files (max 31, geometric 2^n-1 sizing,
640-653), `-R` recurse, `@filelist`. Global: `-m<n>` MB memory (**default
= half physical RAM**, 112/1015), `-t<n>` threads (default = hw
concurrency), `-T<n>` parallel file hashing, `-B<path>` basepath,
`-a<file>` archive name. Verify/repair: `-p` purge, `-O` rename-only,
`-N` data-skipping, `-S<n>` skip leaway. Hard limits: ≤**32768 source
blocks** (173-176), ≤31 recovery files. "Turbo" = ParPar GF16/MD5/CRC32
SIMD kernels + stitched hashing + accelerated matrix inversion + C++11
threads (README.md:1-24); same file format, drop-in.

**Recommended F3 invocation** (sidecar next to archive):

```
par2 create -r10 -n1 -m512 -B <dir> <archive>.excmp.par2 <archive>.excmp
par2 verify -B <dir> <archive>.excmp.par2
par2 repair -p -B <dir> <archive>.excmp.par2
```

Notes: pick `-s` explicitly for huge archives (≈ archive_size/2000 rounded
to a multiple of 4) rather than letting block count silently cap
granularity; `-n1` keeps a single `.vol` file for tidy sidecars; exit codes
0/1 distinguish ok/repairable.

### 10. Extras worth knowing

- **-ma content autodetect**: `ArhiveFileList.hs:484-627 (splitFileTypes)`
  — files first grouped by arc.groups ext; then up to 5×64 KB probes per
  file/group (`aCHUNKS/aCHUNK_SIZE`, 479-481) run through C
  `detect_datatype()` (`Compression/MM/mmdet.cpp:777` — order-0 entropy +
  LZ match density + repdist counting + charset concentration →
  "text"/"compressed"/default) and `detect_mm/detect_mm_header`
  (760-769, entropy-per-channel WAV/BMP detection); 92%-agreement vote
  picks the type (557-565), disagreeing groups split recursively
  (538-542). Detected type *overrides* the extension mapping — exactly the
  router-vs-sniffing architecture excmp wants, and cheap (probes, not full
  reads).
- **Encryption**: `Encryption.hs:29-60` — per-algorithm random salt+IV,
  PBKDF-style `deriveKey` + 2-byte checkcode, serialized *into the method
  string* (`aes:k…:i…`); ciphers AES/Blowfish/Serpent/Twofish, chainable
  (`aes+serpent`). FA'Next plans aes-256/ctr default.
- **Method-string versioning trick**: arc.ini `[Compression methods]`
  alias section (205-333) pins `ccm = ccm130` etc. — archives store the
  *resolved* name so future tool swaps can't silently break decompression.
  Adopt: store fully-resolved tool+version identifiers in .excmp metadata.
- **External compressor recipe format**: `[External compressor:...]`
  sections (arc.ini:335-894) — `packcmd/unpackcmd` templates with
  `$$arcdatafile$$`/`$$arcpackedfile$$` placeholders + declared
  `cmem/dmem` memory budgets: a ready-made schema for excmp's tool-adapter
  config.
- **FA 0.11 dedup** (0.11/Release-notes.md:18-35): CDC chunking +
  per-buffer independent compression, group-aware; a good post-v1 roadmap
  item that replaces rep's decompression-RAM problem.

## ADOPT list (ranked)

1. **PAR2 sidecar via par2cmdline-turbo subprocess** — proven RS FEC,
   self-describing packets, Windows binaries. `subprocess.run(["par2",
   "create", f"-r{pct}", "-n1", ...])`; compute `-s` from archive size
   (≤32768 blocks). **Effort S.** (Confirmed best choice.)
2. **Two-level dispatch table: extension→group (arc.groups) + group×level→
   chain (builtinMethodSubsts grammar)** — the whole router in ~100 lines
   of data, user-overridable via one TOML file; `#`-digit expansion and
   `$group=` overrides are worth cloning as *syntax* (cleanroom from this
   description). **Effort S-M.**
3. **Solid-order sort `(group, ext, similarity-bucket, dir, name)`** — the
   "gerpn" pipeline incl. the reorder hash trick (same ext+size / same
   name+~size ⇒ adjacent). Directly improves 7z/zstd solid ratios with
   zero new tooling. `sorted(files, key=...)` + two dicts. **Effort S.**
4. **Trailing self-CRC'd block descriptors + scan-back open** — makes
   truncated/damaged .excmp listable and PAR2-independent for metadata;
   add FA'Next refinements (descriptor checksum covering block checksum,
   double footer around embedded recovery data). **Effort M.**
5. **Content sniffing to override extension routing** (mmdet-style) —
   5 probes × 64 KB, order-0 entropy + LZ-match density vote. Prevents the
   "renamed .zip inside .dat" ratio disaster. Start with
   `zlib.compress(probe)` ratio as a poor-man's detector. **Effort M.**
6. **BCJ x86 filter for `$exe` group** — free 5-10%: route exe/dll through
   7z with BCJ(2)+LZMA2, or `lzma.FORMAT_RAW` filter chain
   `[{"id": lzma.FILTER_X86}, {…LZMA2}]`. **Effort S.**
7. **rep-equivalent long-range stage via `zstd --long=31`** — captures
   most of rep's dedup win with a maintained OSS tool; document
   decompression RAM = window size, mirroring rep's BlockSize lesson.
   **Effort S.** (Writing our own rep in Python: skip.)
8. **CLS/CELS-style adapter ABI knowledge** — don't implement the ABI, but
   model excmp's tool-adapter interface on its callback shape
   (read/write callbacks, PREPARE_METHOD/paramstr negotiation, declared
   cmem/dmem budgets); keeps the door open to consuming xtool CLS plugins
   later. **Effort S (design only).**
9. **Resolved-alias version pinning + external-tool recipe schema** in
   excmp config. **Effort S.**
10. **Skip:** dict (marginal vs modern entropy stages), delta table
    detector (revisit post-v1), Tornado itself (zstd covers the gradient),
    XOR RR (obsoleted by PAR2).

## Gotchas

- **GPL containment**: freearc code is GPL — parameter tables, formats,
  algorithms, grammar semantics only; no code, no comment translation, no
  header copying into the MIT repo.
- **par2cmdline-turbo is GPLv2+**: invoke strictly as a separate
  subprocess binary, never link/embed (libpar2.vcxproj exists — don't use
  it). If the excmp installer *redistributes* par2.exe, GPL §3 applies
  (ship license + source offer/link); safest is download-on-first-use via
  our SHA-pinned tool downloader (E1).
- The studied `arc.ini` is a scene-modified variant referencing
  non-redistributable/closed tools (ccm, nanozip, durilca, rar, uharc…) —
  grammar reference only; authoritative defaults are
  `Compression.hs:352-463`.
- freearc-orig snapshot is 2009 SVN-era; late-0.67 behaviors (e.g.
  `lzma:max` dictionary auto-scaling, 4x4 threading) may differ — don't
  cite these numbers as "final FreeArc 0.67" without checking a later
  tree.
- PAR2 limits to respect in F3 UX: ≤32768 source blocks (block size must
  grow with archive size), ≤31 recovery files, redundancy default 5%.
  FreeArc's size-tiered dose is a nice UX default to copy: 4% for tiny,
  2% medium, 1% large — with RS these can be halved for equal protection.
- FreeArc's rep lesson for excmp docs: **decompression RAM = long-range
  window** — surface this in the GUI before letting weak-hardware users
  pick 2 GB windows.
