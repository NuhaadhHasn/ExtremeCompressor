# 19 — Source study: 7-Zip 26.02 (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference and a CONFIRMED/REFUTED/NUANCED verdict where a prior doc made a
> claim. We drive `7z.exe` as a subprocess and never link its LGPL code, so
> this is ground-truth for parsing/tuning, not for reuse. Studied commit:
> `f9d78aff31a5f2521ae7ddbdc97c4a8855808959` ("26.02", 2026-06-25) from
> https://github.com/ip7z/7zip. Paths relative to the mirror root.

## Version studied

**7-Zip 26.02** (released 2026-06-25). `DOC/readme.txt:1`, `C/7zVersion.h:1-4`
(`MY_VER_MAJOR 26`, `MY_VER_MINOR 2`). This is the exact version our other
docs cite — apples-to-apples.

## Answers

### 1. AES key derivation for `-p` — (a) CONFIRMED, (b) CONFIRMED, (c) CONFIRMED

**(a) Salt is empty on the CREATE path.** `CPP/7zip/Crypto/7zAes.cpp:232-238`
— `CEncoder::CEncoder()` sets only `_key.NumCyclesPower = 19`; the salt line
is *commented out*: `// _key.SaltSize = 4; g_RandomGenerator.Generate(...)`.
`SaltSize` stays 0 from `CKeyInfo()` → `ClearProps()` (`7zAes.h:32-39`). The
whole `ResetSalt()` method is commented out (`7zAes.cpp:191-198`). So every
archive 7z.exe creates uses **salt = empty**; the only per-archive
randomness is the **16-byte random IV** (`ResetInitVector()`,
`7zAes.cpp:200-207`). Props byte: `props[0] = NumCyclesPower | (salt?0x80:0)
| (iv?0x40:0)` → `0x53` for created archives (`7zAes.cpp:209-230`).

**(b) KDF = SHA-256 iterated 2^19.** `CKeyInfo::CalcKey()`
(`7zAes.cpp:39-114`). Semantically: `Key = SHA256( concat_{i=0}^{2^19-1}
(salt ‖ password ‖ uint64_le(i)) )` — **one running hash**, not chained
rehashing; `numRounds = 1 << NumCyclesPower = 524,288`. Password bytes are
**UTF-16LE, no BOM/terminator** (`CPP/7zip/Archive/7z/7zEncode.cpp:228-236`).
Special case `NumCyclesPower == 0x3F` = no hashing (`7zAes.cpp:41-50`). The
decoder rejects `NumCyclesPower > 24` (`7zAes.cpp:27, 278-279`).

**(c) AES-256-CBC, no MAC.** `CEncoder` instantiates `new
CAesCbcEncoder(kKeySize)` with `kKeySize = 32` (`7zAes.cpp:237`,
`7zAes.h:16`). No HMAC/AEAD anywhere in the 7zAES path. Integrity is only
**CRC32 of decompressed plaintext, checked per file at extraction**
(`7zExtract.cpp:94-95, 128-130`). Consequences: no authenticated
encryption, key equality across archives with same password (empty salt +
global key cache `g_GlobalKeyCache`, `7zAes.cpp:155`), CBC malleability.
**This fully supports building excmp's own encryption layer** (AES-GCM or
XChaCha20-Poly1305 + Argon2id + random salt) around a plaintext 7z stream.

### 2. `-mhe=on` header encryption — what's hidden vs what leaks

Write path `7zOut.cpp:883-963` (`WriteDatabase`): with a header method +
password, the **entire header** (names, sizes, timestamps, attributes,
per-file CRCs, folder/coder layout) is serialized, compressed+encrypted as
a normal 7z folder (`EncodeStream`, `7zOut.cpp:561-586`), and the tail gets
only `kEncodedHeader` + **plaintext** PackInfo/UnpackInfo. Option plumbing
`7zHandlerOut.cpp:739-764`: for a *new* archive the default is **off** with
plain `-p` (names/sizes/times leak); `-mhe=on` is preserved on update if the
source had it. Header compressor is LZMA BT2 fb=273 level 5 dict 1 MB.

**Still leaks with `-mhe=on`:** (1) plaintext 32-byte StartHeader →
NextHeaderOffset/Size/CRC → exact **archive size and encrypted-header
size**; (2) the plaintext outer `kEncodedHeader`: **coder IDs (LZMA +
7zAES)**, the AES coder props (**NumCyclesPower, salt, IV**), the
**unpacked size of the real header** (≈ file-count estimate), pack sizes;
(3) externally: **volume count and sizes** (`.001…`), archive mtime, total
payload size. Hidden: names, per-file sizes/CRCs, file count, internal
structure.

### 3. LZMA2 threading & memory (B9 claims) — NUANCED (mostly confirmed)

- **"2 threads" is per LZMA encoder instance (per block), not per chunk.**
  `C/LzmaEnc.c:103-109`: `numThreads = (btMode && algo) ? 2 : 1` — at mx9
  (bt4 + algo=1) each LZMA encoder spawns a match-finder thread + a coder
  thread. `C/Lzma2Enc.c:262`: `totalThreads = 2 × numBlockThreads`. So
  B9's "2 threads per block" = CONFIRMED; "per chunk" wording = wrong
  (chunks are sequential inside a block).
- **Block splitting vs `-mmt` and solid:** `Lzma2EncProps_Normalize`
  (`C/Lzma2Enc.c:241-345`): default LZMA2-internal block size = `dict*4`,
  clamped [1 MiB, 256 MiB]; `BLOCK_SIZE_SOLID` forces 1 block thread; with
  known input size, block-thread count reduced to
  ceil(fileSize/blockSize). In the 7z **handler**, `-mmt=N` → blockThreads
  = N/2 at mx9; the **7z solid block default for LZMA2 = chunk×64**
  (`7zHandlerOut.cpp:201-226`, "at least 64 chunks per solid block"), and
  a memory-limit loop lowers block threads (`246-268`).
- **~10.5× dict compress RAM: CONFIRMED for solid/single-block.** GUI
  estimator `CompressDialog.cpp:2942-3014`: `size1 = hs*4 + dict*4 +
  dict*4(level≥5) + 2MB (+2MB+4MB when 2 threads)`; with `hs*4 ≈ dict` →
  ≈ 9×dict; plus window buffer `(dict+64K[+1MB])*1.5` → **≈ 10.5×dict +
  ~8 MiB per block thread**. Multi-block: `numBlockThreads × (size1 +
  chunkSize) + numPackChunks × chunkSize`, chunk = `dict*4` capped 256 MiB
  → ≈ 13×dict per block thread. **Use the exact formula, not the
  multiplier.**
- **Decompress RAM ≈ dict: CONFIRMED.** `decompressMemory = dict +
  (2 << 20)` (`CompressDialog.cpp:3016`).
- ⚠️ **Bonus (24.09+, still true in 26.02): default mx9 dict =
  256 MiB on 64-bit** (64 MiB on 32-bit) — `C/LzmaEnc.c:76-81`. **If our
  docs still say "mx9 = 64 MB dict", that is two generations stale.**

### 4. BCJ2 vs BCJ auto-selection — CONFIRMED, with exact gates

- **Content sniffing, not just extension:** `CAnalysis` reads the file head
  and runs `Parse_EXE/ELF/MACH/WAV` (`7zUpdate.cpp:415-422`). `Parse_EXE`
  (`75-212`) checks MZ+PE and maps machine → filter. Analysis level
  default 5 (`2122-2141`): ≥5 parse exe by extension list `g_Exe_Exts`
  {dll,exe,ocx,sfx,sys}+{so,dylib}; ≥7 extension-less files; ≥9 all files
  (changed by `-ma`, not `-mx`).
- **BCJ2 gate:** `useBcj2 = bcj2_IsAllowed && Is86Filter(...)` (`1317-1319`);
  `Is86Filter = (m == k_BCJ || m == k_BCJ2)` — x86/x64 only;
  `bcj2_IsAllowed = MaxFilter && MultiThreadMixer` (`2330-2337`); **MaxFilter
  = (level >= 8)** (`7zHandlerOut.cpp:781`). So **mx8/mx9 → BCJ2; mx5-7 →
  BCJ**; ARM64/RISCV get their own filter + lc/lp/pb re-tuning.
- **BCJ2 chain** (`AddBcj2Methods`, `1253-1291`): coder0 = BCJ2 (4 output
  streams MAIN/CALL/JUMP/RC); MAIN → main LZMA2 chain; CALL and JUMP each
  get a dedicated **LZMA d=1MiB fb=128 lc=0 lp=2 1-thread**; RC stored raw.
- **CLI to force:** simplest **`-mf=BCJ2`**
  (`Archive/Common/HandlerOut.cpp:219-227`; aux coders auto-completed
  `7zUpdate.cpp:1299-1304`). Force plain BCJ: `-mf=BCJ` or mx≤7.
- ⚠️ **Gain class: the source/docs carry NO percentage claims.** The only
  signal is Igor gating BCJ2 behind level ≥ 8 + MT mixer. **Treat any
  "5-10% on x86 binaries" figure in our docs as external/benchmark-derived,
  not source-backed.**

### 5. Solid-block file ordering — comparator quoted

`CompareUpdateItems` (`7zUpdate.cpp:850-935`), applied at `2706-2717`.
⚠️ **`sortByType` requires `-mqs` — `_useTypeSorting` defaults to `false`**
(`7zHandlerOut.cpp:872`). Default order is therefore **by full path name
only** (line 931). With `-mqs`:

```
RINOZ_COMP(ExtensionIndex …)     // rank in g_Exts table
RINOZ(CompareFileNames(ext …))   // ext string
RINOZ(CompareFileNames(basename))
… then MTime (defined-first), then Size,
RINOK(CompareFileNames(full path))   // fallthrough for both modes
```

`ExtensionIndex = GetExtIndex(lowercased ASCII ext)` over the hardcoded
ranked list `g_Exts` (`722-753`) — precompressed formats first (7z xz …
zip … media …), sources/text mid, **exe/dll/obj/lib/pdb last**. Replicating
in excmp's solid stage = copy `g_Exts` + `(extRank, ext, basename, mtime,
size, path)` key. ⚠️ Many blog posts claim 7z always sorts by extension;
**source says only with `-mqs`** — always pass `-mqs` (or pre-sort
ourselves) for exe/media-heavy trees.

### 6. `l -slt` output grammar and fields (for G2 parser)

Structure (`CPP/7zip/UI/Console/List.cpp`):

- Archive block: `Listing archive: X` then `--`, then `Path = …`, `Type =
  …`, optional `ERRORS:/WARNINGS:/ERROR =/WARNING =`, `Physical Size = …`,
  then handler archive props (7z: `Headers Size`, `Method`, `Solid`,
  `Blocks`). Nested archive layers separated by `----`.
- Items section starts with **`----------`** (`1264-1265`); each item =
  `Name = value` lines (`" = "` separator, `436-459`); **one blank line
  after each item** (`729`); **a VT_EMPTY property still prints `Name = `
  with empty RHS** (`572-578`) — parser MUST accept empty values.
- Fields are **handler-driven**. For 7z the item fields
  (`Archive/7z/7zProperties.cpp:95-145`): `Path, Size, Packed Size,
  Modified, Created, Accessed, Attributes, CRC, Anti, Position, Encrypted,
  Method, Block`.
- **Canonical name table** `kPropIdToName[]` (`List.cpp:29-136`) — the
  complete vocabulary any handler can emit by PROPID (0-105): Path, Name,
  Extension, Folder, Size, Packed Size, Attributes, Created, Accessed,
  Modified, Solid, Commented, Encrypted, Split Before/After, Dictionary
  Size, CRC, Type, Anti, Method, Host OS, File System, User, Group, Block,
  Comment, Position, Path Prefix, Folders, Files, Version, Volume,
  Multivolume, Offset, Links, Blocks, Volumes, Time Type, 64-bit,
  Big-endian, CPU, Physical Size, Headers Size, Checksum, Characteristics,
  Virtual Address, ID, Short Name, Creator Application, Sector Size, Mode,
  Symbolic Link, Error, Total Size, Free Space, Cluster Size, Label, Local
  Name, Provider, NT Security, Alternate Stream, Aux, Deleted, Tree, SHA-1,
  SHA-256, Error Type, Errors, Warnings, Warning, Streams, Alternate
  Streams(+Size), Virtual Size, Unpack Size, Total Physical Size, Volume
  Index, SubType, Short Comment, Code Page, Is not archive type, …, Tail
  Size, Embedded Stub Size, Link, Hard Link, iNode, Stream ID, Read-only,
  Out Name, Copy Link, ArcFileName, IsHash, Metadata Changed, User/Group
  ID, Device Major/Minor. Unknown PROPIDs print the handler BSTR name or
  numeric id (`420-434`).
- Tech-mode formatting: timestamps to 100 ns; `Attributes` full string;
  booleans as `+`/`-`; raw props hex-lowercase, `data:<N>` if > 64 bytes.

### 7. Windows extraction path-safety checklist (D0 sanitizer matrix)

Sanitizer core `CPP/7zip/UI/Common/ExtractingFilePath.cpp`:

1. **`.` and `..` parts → emptied then dropped** (`Correct_PathPart`,
   `162-174`; empty parts deleted in `Correct_FsPath`, `246-271`).
2. **Bad chars → `_`**: `: * ? < > | "` and all `< 0x20`, plus `/` inside a
   name (`ReplaceIncorrectChars`, `23-51`); embedded backslash → WSL
   replacement char.
3. **Trailing dots/spaces → `_`** on Windows, iterating from the end
   (`53-88`).
4. **Reserved device names**: `CON PRN AUX NUL` and `COM<digit>
   LPT<digit>`, including with extensions → prefixed `_` (`119-158`).
5. **Alt-stream names**: `: \ /` and RLO (U+202E) → `_`, `:$DATA` suffix
   preserved (`Correct_AltStream_Name`, `96-113`).
6. **Absolute paths/drive letters**: only honored in `kAbsPaths` mode
   (`-spf`); default mode prefixes everything with the output dir
   (`ArchiveExtractCallback.cpp:1343-1347`).
7. **Link-target validation**: `IsSafePath` = not absolute, never escapes
   above root (`LowLevel >= 0`), non-empty
   (`ArchiveExtractCallback.cpp:643-700`), applied at `2207`; 25.01
   hardened further (CVE-2025-55188).
8. **Long/`\\?\` paths**: `GetSuperPathBase` refuses when the path still
   contains `.`/`..` folders (`AreThereDotsFolders`, `Windows/
   FileName.cpp:577, 641`) — dot-folders never reach the FS via
   super-path.
9. Empty final component → `_`.

Test-matrix inputs implied: `..\..\x`, `C:\abs`, `C:rel`, `\\server\share`,
`\\?\C:\x`, `a:b` (ADS), `a::$DATA`, `CON`, `COM7.txt`, `NUL .txt`,
`name.`/`name ` (trailing), control chars, RLO, `/` and `\` inside names,
empty parts (`a//b`), symlink target `../../evil`, absolute symlink target.

### 8. Mark-of-the-Web propagation — CONFIRMED implementation map

- Stream name + R/W helpers: `ArchiveExtractCallback.cpp:160-191`
  (`":Zone.Identifier"`, `ReadZoneFile_Of_BaseFile`,
  `WriteZoneFile_To_BaseFile`).
- Source: the **archive file's own** `Zone.Identifier` ADS is read once
  before extraction (`Extract.cpp:447-450`).
- Propagation: written to **every extracted regular file** (not
  alt-streams), *before* timestamps, failure (FAT) silently ignored
  (`1961-1977`).
- Anti-spoof: an archive-embedded alt-stream item named `Zone.Identifier`
  is skipped when propagation is active (`1686-1695`).
- Switch: `-snz` (`ArchiveCommandLine.cpp:354`); bare `-snz` → kAll,
  `-snz0` none, `-snz1` all, `-snz2` Office-only. ⚠️ **CLI default = kNone**
  (`Extract.h:52`) — **7z.exe does NOT propagate MotW unless asked**; the
  GUI File Manager uses a registry option. Nested-archive fix landed 24.09
  (CVE-2025-0411). **excmp must pass `-snz` explicitly (or write
  Zone.Identifier itself) to be safe-by-default on downloads.**

### 9. Other findings worth having

- **Exit codes** (`ExitCode.h:8-23`): `0` success, `1` warning(s), `2`
  fatal error, `7` command-line error, `8` out of memory, `255` user break.
  Codes 3-6, 9 exist only as commented history — never emitted.
- **Progress parsing (critical):** when stdout is not a terminal, **percent
  output is disabled entirely by default** (`ArchiveCommandLine.cpp:
  1083-1086`). A wrapper must pass `-bsp1` (percents→stdout) or `-bsp2`
  (→stderr). Format (`PercentPrinter.cpp:59-87`): right-padded 4 chars,
  `NN%`, or `NNM` (MiB counter) when total unknown; lines rewritten with
  `\r` on Windows — parser should split on `\r` and regex `(\d+)%`.
- **Multivolume naming:** `-v` output is `<final-name>.<ext>.NNN` — first
  volume literally `arcPath + ".001"` (`Update.cpp:1206-1210`); 1-based,
  zero-padded to ≥3 digits (`MultiOutStream.cpp:183-191`).
- **ISO is read-only** (no `Iso*Out*` handler); **WIM has store-class write
  support**. G1 must not plan on `7z a -tiso`.
- **Solid defaults**: LZMA2 solid block = chunk×64 capped 16 GiB; other
  methods `dict << 7` within [16 MiB, 4 GiB].

## ADOPT list (ranked)

1. **Pass `-bsp1` to every 7z.exe invocation; parse `\r`-separated
   `(\d+)%` tokens** — otherwise no progress at all when piped. Treat `NNM`
   as bytes-mode fallback. **Effort S.**
2. **G2 `-slt` parser grammar**: records = blank-line-separated `key =
   value` blocks after the `----------` line; accept empty values (`CRC
   =`); `--` opens archive blocks, `----` separates nested layers;
   whitelist keys from `kPropIdToName` + 7z's 13 item fields. **Effort S.**
3. **Own encryption layer** (already decided — now source-proven): wrap 7z
   payloads in AES-GCM/XChaCha20-Poly1305 with Argon2id + random salt.
   Keep `-p`+`-mhe=on` only as a "7z-compatible" mode and document its
   leaks (archive size, header size, KDF params). **Effort M.**
4. **D0 sanitizer matrix**: implement the 9-point checklist in answer 7 as
   a pure-Python `sanitize_parts()` + property tests with the exact inputs
   listed; refuse (not mangle) on `IsSafePath`-style link escapes.
   **Effort M.**
5. **Solid ordering replication**: copy `g_Exts` ranking + `(extRank, ext,
   basename, mtime, size, path)` sort key; note 7z's own default is plain
   path-sort — **always pass `-mqs` (or pre-sort ourselves)** for
   exe/media-heavy trees. **Effort S.**
6. **MotW**: after extraction, write `Zone.Identifier` ADS (ZoneId=3 or
   copy from the source archive) to extracted files ourselves, or pass
   `-snz` — CLI default propagates nothing. **Effort S.**
7. **RAM planner**: implement the exact `CompressDialog.cpp:2901-3017`
   formula (per-block `size1 + chunk` model, decode = dict + 2 MiB) for
   weak-hardware presets instead of a flat 10.5× multiplier. **Effort S-M.**
8. **BCJ2 forcing**: use `-mf=BCJ2` for x86 exe-heavy jobs at mx<8 (cheapest
   correct trigger); optionally pre-sniff MZ/PE machine words in Python.
   **Effort S.**
9. **Exit-code mapping** {0,1,2,7,8,255} into typed excmp errors, treating
   1 as partial-success. **Effort S.**

## Gotchas

- **Percent output silently vanishes under subprocess pipes** unless
  `-bsp1/2` — the single most common wrapper bug.
- `-p` **without** `-mhe=on` leaves all file names/sizes/times in cleartext;
  and even `-mhe=on` leaks KDF params, header size, archive size, volume
  layout.
- `-slt` emits `Key = ` lines with **empty values**; field sets differ per
  archive type — never hardcode 7z's field order for zip/tar listings.
- "Type sort" is **off by default** (`_useTypeSorting = false`) — the
  common "7z always sorts by extension" claim is wrong; only with `-mqs`.
- mx9 default dictionary changed in 24.09 to **256 MiB on 64-bit** — memory
  planning docs citing 64 MiB are two generations stale; on 4 GB machines
  mx9 MT LZMA2 can exceed RAM (≈13×dict per block thread).
- BCJ2 auto-selection additionally requires the **multithreaded mixer** —
  single-threaded builds/paths fall back to BCJ even at mx9.
- Decoder caps `NumCyclesPower` at 24 — don't generate archives with higher
  values expecting 7z compatibility.
- The mirror is **26.02 (2026-06-25)**, newer than most public docs; verify
  against `DOC/src-history.txt` before citing behavior as "current" for
  users on 24.x.
- No source-level percentage for BCJ/BCJ2 gains — keep our gain figures
  flagged as benchmark-derived.
