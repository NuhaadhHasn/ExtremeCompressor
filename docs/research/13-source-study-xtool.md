# 13 — Source study: xtool 0.7.9 (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference into the studied commit. **No code was copied** — xtool is MIT but
> Delphi; reuse is conceptual. Studied commit:
> `9a1d5fafcfd93be25967e6e20734ee05fed07b72` ("0.7.9 hotfix 1", 2023-09-18)
> from https://github.com/Razor12911/xtool — the final archived release, i.e.
> exactly the binary our Phase B6 stage will drive.

## Architecture

xtool is a **stream-level precompressor**: it scans arbitrary input for
embedded compressed streams (zlib/lz4/zstd/oodle/lzo/gdeflate/...),
decompresses each candidate, **verifies it can recreate the original bytes
exactly by recompressing**, and emits a container of decompressed streams +
metadata. "Decode" is the inverse: it **re-compresses every stream with the
recorded codec/level/params** to reproduce the input bit-exactly. This is the
critical mental model: *decoding requires the same compression libraries as
encoding, because restore = recompress.*

Core dataflow (`precompressor/PrecompMain.pas`):

- `Encode` (`:3231`) builds a fixed codec table — insertion order defines
  codec IDs 0-13: INI=0, INIEx=1, Search=2, DLL=3, EXE=4, Crypto=5, ZLib=6,
  LZ4=7, LZO=8, ZSTD=9, Oodle=10, Media=11, DStorage=12, Dummy=13
  (`:3239-3252`).
- Input is read in chunks (`-c`, default 16 MB, min 4 MB clamp at `:233`)
  into per-thread slots (`TDataStore1`, `common/Utils.pas:377`). Each thread
  runs `Scan1` (every codec's scanner over its chunk), then `Scan2` (re-check
  "future" streams that crossed chunk/thread boundaries, `:1169-1293`), then
  `Process` (verification, `:1295-1517`), then `EncData` serializes (`:1942`).
- Every codec implements the 7-function record `TPrecompressor`
  (`precompressor/PrecompUtils.pas:229-239`):
  `Init/Free/Parse/Scan1/Scan2/Process/Restore`, communicating via a 128-slot
  function table `_PrecompFuncs` (`PrecompUtils.pas:121-204`) — the same ABI
  exposed to DLL plugins.

## Answers

### 1. Project layout

- `xtool.dpr` — the console EXE; dispatches commands `precomp, generate,
  find, erase, replace, extract, patch, archive, execute, decode`
  (`xtool.dpr:104-114`). `patch`/`archive` are still listed (`:128,133`) but
  their handlers were removed in 0.7.9 (`changes.txt:19-20`).
- `xtoolui.dpr` — builds `xtoolui.dll`, an FMX GUI **library** (exports
  `XTLUI1/XTLUI2`, `xtoolui.dpr:51-58`). If `xtoolui.dll` sits next to
  `xtool.exe` and it's launched with 0 args, the EXE enters GUI mode and
  re-invokes *itself* as a subprocess with generated CLI args
  (`xtool.dpr:429-471`); it can iterate a folder of DLLs injecting
  `-lz4<path>`/`-zstd<path>`/`-oodle<path>` per run ("library checker",
  `xtool.dpr:452-459`, `changes.txt:87`).
- `cls_xtool.dpr` — builds a **CLS plugin DLL** (FreeArc Compression Library
  System, used by ISDone-based installers); exports `ClsMain`
  (`cls_xtool.dpr:72-132`).
- `dbgenerator/` — the `generate` command implementation (`DbgMain.pas`),
  producing `.xtl` stream databases (see answer 2).
- `precompressor/` — the heart: `PrecompMain` (pipeline), `PrecompUtils`
  (ABI/structs/patching), per-codec units
  (`PrecompZLib/LZ4/LZO/ZSTD/Oodle/Media/DStorage/Crypto`), plugin hosts
  (`PrecompINI` = signature-config plugins, `PrecompINIEx` =
  list/counter-config plugins, `PrecompSearch` = `.xtl` DB plugins,
  `PrecompDLL` = native DLL plugins, `PrecompEXE` = external-executable
  plugins).
- `imports/` — late-bound DLL wrappers for codec libraries (OodleDLL,
  ZLibDLL, ZSTDDLL, LZ4DLL, LZODLL, ReflateDLL, PreflateDLL, FLACDLL,
  PackJPG/Brunsli/JoJpeg, FLZMA2DLL). All optional — features degrade if a
  DLL is absent.
- `io/` — auxiliary commands (`IOFind/IOErase/IOReplace/IODecode/IOExecute`),
  each writing containers with own magics `XTOOL_IODEC=$314C5458`,
  `XTOOL_EXEC=$324C5458` (`io/IOUtils.pas:11-12`).
- `common/` — `Utils.pas` (4,596 lines: streams, TProcessStream subprocess
  piping, TDataStore chunking, zstd-based EncodePatch/DecodePatch, arg
  parser), `Threading.pas` (TTask), `LibImport.pas` (LoadLibrary +
  in-memory MemoryModule loading), `DStorage.pas`, `CLS.pas`.
- `sources/` — `lz4.pas`, a Delphi port of lz4 exposing
  `LZ4_decompress_generic(..., endOnOutputSize)` used by the universal
  raw-lz4 scanner.
- `contrib/` — third-party Delphi libs (FastMM4-AVX, mORMot
  SynCommons/SynCrypto, XXHASH4Delphi, ZSTD4Delphi, MemoryModule,
  ParseExpression). **Mixed licenses** (FastMM4 GPL/LGPL dual, mORMot
  tri-license) — only xtool's own units are plain MIT.

### 2. The stream database

Two distinct mechanisms:

**a) In-memory encode DB** (always on since 0.7.0, `changes.txt:82`). Entry =
`TDatabase` (`PrecompUtils.pas:253-259`): `packed record Size: Integer;
Codec: Byte; Option: Integer; Checksum: XXH128_hash_t; Status: TStreamStatus
end` — Status ∈ {None, Invalid, Predicted, Database} (`:37`). Bucketed into
65,536 lists by the first 16 bits of the xxh3_128 checksum
(`PrecompMain.pas:1696-1700`, `CheckDB :1001`, `AddDB :1025`). On every
stream, `Process` consults it: a hit with `Status=Invalid` skips the stream
instantly; a hit with a valid Option replays the known level without
searching (`:1367-1380`); every miss result is added back with `Predicted` or
`Invalid` (`:1439-1450`). This is memoization keyed on `(size, xxh3_128)` so
identical streams are never re-brute-forced. (A file save/load path exists —
`DBFile` at `:1796-1820, :2341-2363` — but `TEncodeOptions.DBaseFile` is
never set by `Parse`, so on-disk export is dead code in 0.7.9.)

**b) On-disk `.xtl` plugin databases** consumed by `PrecompSearch` and
produced by `dbgenerator`. File format (`PrecompSearch.pas:265-323` reader,
`DbgMain.pas:324-337` writer): `Int32 magic XTOOL_DB=$31445458` ("XTD1",
`DbgUtils.pas:20`) then repeated records: `SearchInt1` (first 4 bytes of the
source file), `SearchInt2` (Int32 at offset 65532), `Hash` (CRC32 of first
64 KB), `Int32 HashCount + HashCount×{Size:Int32, Hash:Cardinal}` (CRC32 per
4 MB block of the whole file, `HashSize=4*1024*1024` `DbgMain.pas:31`),
method string (len-prefixed), `Int32 EntryCount + EntryCount×TEntryStruct{
Position: Int64; OldSize, NewSize, DepthSize: Int32}` (`DbgUtils.pas:25-28`).
Runtime detection (`PrecompSearch.pas:167-235`): 2-byte bucket → compare
SearchInt1/SearchInt2 → CRC32 of 64 KB → verify full 4 MB CRC chain via
`ReadFuture` → if the *file fingerprint* matches, add **all** recorded stream
entries at `Pos+Entry.Position` with the recorded codec string. So a `.xtl`
is "recognize this exact game file, then apply this known stream layout" —
zero scanning cost.

**How `generate` differs from inline detection:** `xtool generate [-m -c -t]
extracted_streams original_data database_output` (`DbgMain.pas:57-68`) does
**no codec work at all**. Input1 is a folder of previously extracted raw
streams (e.g. from `precomp -x<dir>`, saved as `<hexpos>_<codec>.raw`,
`PrecompMain.pas:673-681`); it fingerprints each (first-256-byte CRC + full
CRC, `MinSize1=256` `:29`) and byte-locates them inside the original files by
rolling 2-byte+CRC candidate matching (`:269-303`). The output records
positions only; codec/params come from the `-m` method string stored
alongside. Dropped into the plugins dir, the `.xtl` filename becomes a codec
name selectable via `-m<name>`.

### 3. Stream detection

Per-codec scanners in `Scan1`, run over every chunk (no global magic
registry):

- **zlib/deflate** (`PrecompZLib.pas:417-598`): brute-force with cheap
  prefilters — skip runs of identical bytes (`:466-476`); detect a zlib
  header behind the deflate data (`CMF/FLG` check `(In-2)^ and $F = 8`,
  FCHECK mod 31, `:477-489`, giving a predicted level from FLEVEL
  `:545-556`); otherwise try any byte whose low 3 bits look like a deflate
  block start (`and 7 in [$4,$5]`, `:492`). Confirm by `inflate` of 16 scan
  bytes (`Z_SCANBYTES=16`, `:26`) then stream to end with `Z_BLOCK`; accept
  if `Z_STREAM_END` and ≥128 input bytes (`Z_MINSIZE=128`). w15 raw enforced
  by default (`ZWinBits=7`, `changes.txt:96`).
- **zstd** (`PrecompZSTD.pas:163`): frame magic `$FD2FB528`, then decompress
  to learn sizes.
- **lz4f** (`PrecompLZ4.pas:256`): frame magic `$184D2204` via
  `LZ4F_decompress_safe`.
- **raw lz4/lz4hc** (`PrecompLZ4.pas:219-253`): heuristic — first token byte
  in `$F0..$F4`, then `LZ4_decompress_generic(..., endOnOutputSize)` to find
  a plausible end, re-verify with `LZ4_decompress_safe`, accept if output
  > 256 bytes and expansion occurred.
- **Oodle** (`PrecompOodle.pas:52-209` `GetOodleSI`): parses real Oodle block
  headers — first byte `$8C` (compressed) / `$CC` (stored), second byte
  `$06`=Kraken, `$0A`=Mermaid/Selkie, `$0C`=Leviathan (`$86/$8A/$8C` = same
  with per-quantum CRC), big-endian 24-bit quantum lengths cross-checked
  between the header and the first 256 KB block (`BlkSize=262144`), chaining
  across blocks. Decompressed size is *unknown*, so `CustomLZ_Decompress`
  (`:240-285`) trial-decompresses with a shrinking/probing capacity search,
  using a fill-byte sentinel (`LocalLZ_Decompress` fills the tail with
  `aIdent` and measures how much was overwritten, `:218-238`) to discover the
  true raw length. LZNA/old-format branches are commented out.
- **gdeflate** (`PrecompDStorage.pas:236`): 2-byte signature `GDefSig` +
  `GetGDefSI` structural check, decompressed via the DirectStorage codec COM
  interface (`:283-308`).
- **Config plugins** (`PrecompINI.pas:218-352`): `BinarySearch` for the
  declared `Signature` bytes, read declared header fields around it, evaluate
  size expressions and `Condition#` with an expression parser.
- **WAV/JPG** (`PrecompMedia.pas`), **PNG** (`PrecompZLib.pas:45-148`: PNG
  sig `$A1A0A0D474E5089`, IDAT merge with per-chunk CRC verification).

**Depth semantics:** `-d#` stores `Depth = #+1`, clamped 1..10
(`PrecompMain.pas:296-298`). After a stream is successfully precompressed at
depth N, its decompressed output is loaded into a `TDataStore2` slot and the
whole codec pipeline is recursively re-run on it at depth N+1 (`Process`,
`:1464-1512`) — this is how e.g. zlib-inside-oodle gets caught. `/` in a
method string declares an explicit depth chain (`GetDepthCodec`,
`PrecompUtils.pas:665-682`), e.g. a plugin codec `kraken:l5/zlib`.

### 4. Oodle integration (`imports/OodleDLL.pas`)

- Binding: plain `LoadLibrary`/`GetProcAddress` via `TLibImport`
  (`common/LibImport.pas:106-186`; can also load DLLs embedded as PE
  resources through MemoryModule). Exports resolved by name, with a fallback
  loop over stdcall-decorated names `_OodleLZ_Compress@N` for N=0..98 step 2
  (`OodleDLL.pas:119-125,132-139` — handles 32-bit decorated builds).
- Functions used: `Oodle_CheckVersion`, `OodleLZ_Compress` (two signatures:
  pre-2.6.0 without scratch memory, 2.6.0+ with `scratchMem/scratchSize`,
  selected by `OldCompress := LongRec(C).Hi < $2E06` from CheckVersion,
  `:126-140`), `OodleLZ_Decompress` (full 14-arg signature, called with
  `fuzzSafe=0, checkCRC=0`, `:56-62`), `OodleLZ_CompressOptions_GetDefault`
  (arg-less variant on ≥2.E.08, `:129-130`),
  `OodleLZ_GetCompressedBufferSizeNeeded` (1-arg vs 2-arg),
  `OodleLZ_GetCompressScratchMemBound`.
- Compressor enum mapping (`PrecompOodle.pas:351-369` `GetOodleCodec`):
  LZNA=7, Kraken=8, Mermaid=9, Selkie=11, Hydra=12, Leviathan=13; levels 1..9
  are `compressSelect`.
- Options replayed bit-packed in the stream `Option`: level (bits 3-6),
  `sendQuantumCRCs` (bit 7), `spaceSpeedTradeoffBytes` (bits 8-18, default
  `O_TRADEOFF=256`), `dictionarySize` KB (bits 19-31) (`OodleParse
  :434-464`, applied in `Process :603-607` and `Restore :678-688`).
- DLL location: default `PluginsPath + 'oo2core_9_win64.dll'`; overridden by
  a **global** argument `-oodle<full-path>` scanned from the raw command line
  in `initialization` (`OodleDLL.pas:229-247`). Fallback probe:
  `oo2core_3..9_win64.dll` then `oo2ext_3..9_win64.dll` in the plugins dir
  (`:100-114`). `PluginsPath` defaults to the exe dir, overridable with
  `-bd<path>` (`InitCode.pas:14,88-103`). So "use the game's own DLL" = pass
  `-oodle<gamedir>\oo2core_X_win64.dll`.
- Version handling: only the *presence/signature* differences above; there is
  **no** enforcement that decode uses the same DLL version — see Gotchas.

### 5. Precompress vs restore — the lossless mechanism

- **Encode-side verification is bit-exact recompression.** `Process` calls
  the codec's `Process()`: Oodle recompresses the decompressed data at each
  candidate level and requires `Res1 = OldSize` **and**
  `CompareMem(OldInput, Buffer, OldSize)` (`PrecompOodle.pas:611-618`); zstd
  the same (`PrecompZSTD.pas:345-347`); zlib does incremental 512-byte-block
  `CompareMem` during deflate so mismatches bail early
  (`PrecompZLib.pas:694-713`, `Z_BLKSIZE=512`).
- **Fallback chain for deflate:** if no zlib level reproduces the bytes, the
  stream is *re-processed* as reflate then preflate
  (`PrecompZLib.pas:722-733`); those store an extra "hif"/diff blob via the
  EXTENDED_STREAM mechanism and reflate optionally CRC-verifies its own
  roundtrip when the stream had a zlib header (`:783-826`).
- **Binary diff/patch fallback:** for zstd, lz4 and EXE plugins (NOT
  oodle/lzo — removed in 0.6.5 because "crc mismatch often generates large
  diff files", `changes.txt:113`), if recompression is close but not exact,
  xtool builds a patch with **zstd long-distance matching +
  `ZSTD_CCtx_refPrefix`** (dictionary = the wrong recompressed output, data =
  the original compressed bytes): `PrecompEncodePatchEx`
  (`PrecompUtils.pas:1039-1105`; windowLog = `log2(NewSize)+1`, LDM on, level
  `DIFF_CLEVEL` default 1). Acceptance: `PrecompAcceptPatch` (`:1522-1530`)
  — patch ≤ `DIFF_TOLERANCE` (default **0.05** = 5% of max(old,new), `:391`;
  configurable `-df#`, absolute byte value if >1). The patch is stored as
  EXTENDED_STREAM ext-data; on restore, `PrecompDecodePatchEx` re-applies it
  over the freshly recompressed bytes (`PrecompZSTD.pas:478-486`,
  `PrecompEXE.pas:624-632`). This replaced xdelta3 in 0.7.9
  (`changes.txt:27`).
- **Failure handling:** a stream that fails verification is simply **left as
  raw bytes** in the container (deleted from the stream list,
  `PrecompMain.pas:2158-2169`) and recorded `Invalid` in the DB — lossless by
  construction. On decode, if a codec's `Restore` fails (e.g. wrong DLL),
  xtool **raises** `'Error in the method %s'` and decode aborts with exit
  code 1 (`PrecompMain.pas:2716-2718`, `PrecompUtils.pas:15`,
  `xtool.dpr:631-638`) — it fails loudly, never silently corrupts.
- **`-s` (NOVERIFY)** skips all verification and marks every candidate
  successful except crypto streams (`Codec in [5]` exemption,
  `PrecompMain.pas:1385-1386`) — this genuinely breaks the guarantee; never
  use it.

### 6. Exact CLI surface

Quoted from `PrecompMain.PrintHelp :155-191` and parse code:

```
xtool precomp [parameters] input output
  -m#   codecs ("+"-separated; ":" params, "," also accepted; "/" = depth chain)
  -c#   scanning range/chunk [16mb]  (min 4mb; kb/mb/gb suffixes, expressions OK)
  -t#   working threads [50p]       ("p"/"%" = percent of cores)
  -d#   scan depth [0]
  -dd   stream deduplication        (-dd# additionally pipes through srep -m#)
  -l#   fast-lzma2 level 0-10, 'x'=max; sub-params d#=dict o#=overlap  [0=off]
  -lm   low memory mode (single scan slot)
  -s    skip stream verification    (DANGEROUS)
  -sp#  srep parameters, ":"-separated (each token gets "-" prefixed)
  -v    verbose (forces -t1)
  -df#  patch tolerance [5p]; sub-param l# = patch zstd level 1-22 [1]
  -x#   extract detected streams to directory
  -dm#  dedup memory limit [75p]
  -db#  decode block size [512mb]
  -p#   prefetch cache [0mb]        (x64 only)
  -r#   recompress streams with another codec   (-r alone = REPROCESSED mode)
  -a#   assign/reassign failed streams to another codec
  -T#   thread priority 0..6 [3]
  -o    optimise decoding (search lower level that also matches)
  -f    full scan
  -bd#  base directory for plugins/libraries
  -lz4#, -zstd#, -oodle#   custom library path (global args, also pre-parse)
  --debug
xtool decode input [decode_data] output      (DecodePrintHelp, xtool.dpr:141-151)
  -t# threads [50p]; -dm# dedup mem [75p]; -sp# srep params; -p# cache; -T#; -e#
xtool generate [-m# -c# -t#] extracted_streams original_data database_output
xtool find|erase|replace [-c# -t#] ... ; xtool extract|execute ...
```

Method examples from code paths: `-mzlib:l68:w15`, `-mkraken:l4:c1:t256:b0`,
`-mzstd:l19`, `-mlz4f:l9:b4`, `-mreflate:l6`, `-m<inifile-name>` (config
plugin), `-m<xtlname>` (DB plugin). Codec params are parsed per codec: zlib
`l`(11-99)/`w`; oodle `l`(1-9)/`c`(CRC)/`t`(tradeoff)/`b`(dict KB)/`s`(max
size)/`w`(workmem)/`n`; zstd `l/f/w/b`; lz4 `a/b/s`, lz4f `l/b/d`. Input may
be a file, directory, URL (`://`) or `-` stdin; output a file, existing
directory, `-` stdout, or empty (null sink) (`xtool.dpr:153-175`).

### 7. Plugin systems

- **CLS** (`cls_xtool.dpr`, `common/CLS.pas`): exports `ClsMain(operation,
  callback, instance)`. `CLS_COMPRESS`: fetches the parameter string via
  `CLS_GET_PARAMSTR` (≤256 chars), splits on `:`, prefixes each token with
  `-`, feeds `PrecompMain.Parse/Encode` with the callback-backed `TCLSStream`
  as both input and output (`cls_xtool.dpr:86-105`). `CLS_DECOMPRESS`: reads
  the magic, decodes with `-t100p` (`:106-126`). Returns `CLS_OK=0 /
  CLS_ERROR_GENERAL=-1 / CLS_ERROR_NOT_IMPLEMENTED=-2` (`CLS.pas:44-46`). So
  an ISDone `arc.ini` method string like `xtool:mzlib+kraken:c64mb:t2` maps
  1:1 onto the CLI.
- **INI signature plugins** (`PrecompINI.pas:407-560`): any `*.ini` in the
  plugins dir with sections `[Stream1..N]` and keys `Name` (comma-separated
  aliases — "multiple games same config", `changes.txt:9`), `Codec` (target
  codec+params, `/`-chain for depth), `BigEndian`,
  `Structure=Signature(4),CSize(4),DSize(4),Stream,...` (named fields with
  sizes; `Stream` marks the data start; `Footer` supported),
  `Signature=0x...`, `StreamOffset/CompressedSize/DecompressedSize/DepthSize`
  (arithmetic **expressions over the named fields**, evaluated by
  `TExpressionParser`), `Condition1..N` (must evaluate non-zero). The ini
  filename becomes the codec name.
- **INIEx advanced plugins** (`PrecompINIEx.pas:534-707`): `[StreamList1..N]`
  variant with `StreamPosition` (absolute positions instead of signature
  scan) and `Counter#Start/End/Step` loops — for TOC-driven archives where
  stream offsets are computed, not scanned.
- **DLL plugins** (`PrecompDLL.pas:56-110`): native DLLs exporting
  `PrecompInit/Free/Codec/Scan1/Scan2/Process/Restore` with the
  `_PrecompFuncs` table passed in — full-power scanners in any language.
- **EXE plugins** (`PrecompEXE.pas:663-758`): `<plugins>\xtool.ini` sections
  `[codecname]` (comma-list) with `Encode=`/`Decode=` command templates.
  Placeholders: `<stdin>/<stdout>` (pipe modes), `<filein>/<fileout>`
  (temp-file mode, default names `data.in`/`data.out` `:15-16`), `<library>`
  (persistent stdio server process speaking a
  `[insize][outsize][data] → [outsize][data]` framing, `:127-165`),
  `[insize] [outsize] [fileres] [ressize] [codec]` substitutions. Each thread
  gets its own randomized work dir `<codec>_<hex>` under CWD (`:468-471`),
  deleted on exit (`:770-774`). EXE plugin results get the same
  recompress-verify plus zstd-patch fallback (`:567-582`).

### 8. Threading and memory model

- Thread default `50p` = 50% of cores (`PrecompMain.pas:235-238`) →
  **1 thread on a 2-core machine** unless overridden. `-lm` shares a single
  scan slot among threads (`:1737-1744`).
- Encode RAM ≈ `Threads × ChunkSize` (input slots) + per-thread output
  streams `MemOutput1/2/3` (grow to hold decompressed data — deflate output
  is *bigger* than input) + per-thread `WorkStream` scratch (Oodle path
  allocates `GetCompressedBufferSizeNeeded + 64MB` `O_WORKMEM`,
  `PrecompOodle.pas:29`) + dedup tables. Guard rails: `XTOOL_FREEMEM =
  $40000000` (1 GB) always left free (`PrecompMain.pas:26`),
  `XTOOL_MEMLIMIT` unbounded on x64 (`:21-25`).
- Decode groups streams into blocks capped by `DecodeMemBlock` (default
  **512 MB**, `-db#`, `:138`); decode RAM ≈ block size + max(OldSize,NewSize)
  + dedup pool (`-dm#`, default 75% of total RAM, spilling to a `-vm.tmp`
  file stream via `TPrecompVMStream`, `PrecompUtils.pas:285-304`).
- Per-thread codec state: zlib keeps a 9×9×7 lattice of reusable z_streams
  per thread (`PrecompZLib.pas:36`); every codec keeps a per-thread
  **MTF-ordered candidate-level list** (`TSOList`, e.g. levels 1-9 for oodle
  `PrecompOodle.pas:417-422`, 11..99 + seeds {99,18,58,68,98} for zlib
  `PrecompZLib.pas:306-329`) so the level that worked last time is tried
  first.
- **For our 2-core/16 GB target:** `-t2 -c64mb -db256mb`, no `-p` cache, no
  fast-lzma2 (`-l0`), plain `-dd` only if RAM headroom is confirmed; expect
  <1.5 GB working set for the oodle-only method. `-lm` if the input contains
  huge deflate streams.

### 9. Phase B6 deliverable — wrapper command lines

**(a) Precompress a game folder/file with the game's own oo2core DLL**
(xtool x64 ≥0.7.9 in `<tools>`, plugins dir = same):

```
xtool.exe precomp -mkraken+mermaid+selkie+leviathan+hydra -c64mb -t2 -d0
          "-oodle<GAMEDIR>\oo2core_9_win64.dll" -bd<TOOLSDIR>
          <INPUT(file|folder)> <OUTPUT.xtp>
```

Add `+zlib+zstd+lz4+lz4f` per game profile; add `-dd` for dedup (temp file
cost); `-mhydra` alone covers Kraken/Mermaid/Selkie recompression choices.
Note `-oodle` takes the **full path** appended directly to the flag (one arg,
quote the whole thing).

**(b) Restore:**

```
xtool.exe decode -t2 "-oodle<GAMEDIR>\oo2core_9_win64.dll" -bd<TOOLSDIR> <OUTPUT.xtp> <RESTOREDIR|file>
```

Decode reads depth/method/resources from the container header (`DecInit`,
`PrecompMain.pas:2757-2772`); `-m` not needed. The output directory must
already exist to be treated as a directory (`xtool.dpr:169-170`).

- **Exit codes:** 0 = success; 1 = any exception, including restore failure
  (`xtool.dpr:631-638`). Nothing else. **Verify restored bytes against our
  own SHA-256 manifest regardless.**
- **Progress:** interactive stats ("`Streams: P / C`", "`Time: hh:mm:ss (CPU
  ...)`", "`Size: A >> B >> C`") are rewritten every 500 ms via
  `WriteConsole(GetStdHandle(STD_ERROR_HANDLE))` with cursor repositioning
  (`EncodeStats`, `PrecompMain.pas:3105-3185`; `WriteLine`,
  `Utils.pas:682-688`). **`WriteConsole` fails silently on redirected handles
  — when our wrapper pipes stderr there is NO progress output at all.** `-v`
  gives line-based logs (`[depth] Actual <codec> stream found at <hexpos>
  (in >> out)`, `Processed ... successfully/has failed`) but forces `-t1`
  (`:401-402`) and still goes through `WriteConsole`. Practical wrapper
  design: run xtool with `CREATE_NO_WINDOW`, don't parse progress, poll
  output-file size for a progress proxy, wait for exit code.
- **Temp files (all under CWD — always launch with cwd = scratch dir):**
  `xtool_<hex8>-storage.tmp` (chunk spill, `PrecompMain.pas:1785-1788`),
  `xtool-dd.tmp` (dedup staging when output is a real file, `:2046-2051`),
  `xtool-vm.tmp` (decode dedup spill, `PrecompUtils.pas:287`),
  `<codec>_<hex>` dirs (EXE plugins). srep integration additionally shells
  `srep[64].exe -m#[f] ... - -` from the plugins dir (`:2037-2044,
  :2472-2489`) — srep is not OSI-licensed, do not ship it.
- **Determinism caveats:** (1) container bytes are **not reproducible
  run-to-run** — per-thread MTF level lists and thread/chunk scheduling
  change which level is recorded first (harmless for restore, fatal for
  dedup-by-container-hash; hash the *restored* data, not the `.xtp`);
  (2) restore recompresses with the recorded level, so **decode requires an
  oo2core DLL whose encoder output is byte-identical to the one used at
  encode** — same DLL version, ideally same file. Record the DLL's SHA-256 +
  filename in our manifest.json and re-resolve it from the game dir at
  restore; (3) `-c` (chunk) changes stream detection at boundaries → also
  non-reproducible across different `-c`; pin chunk size per profile.

### 10. Otherwise-missed valuables

- **`Option` bit-packing** — every codec packs its full replay parameters
  into one Int32 (e.g. oodle: codec 3b | level 4b | CRC 1b | tradeoff 11b |
  dictKB 13b) stored per stream; restore is a pure function of
  (codec, Option, decompressed bytes).
- **Internal dedup** (`-dd`): duplicate streams keyed `(OldSize, xxh3_128)`
  (`TDuplicate1`, `PrecompUtils.pas:263-268`; `FindOrAddDD`
  `PrecompMain.pas:1098-1133`) are stored once; the container records
  `DUPLICATED_STREAM` headers whose `Option` is the source index, and decode
  keeps a ref-counted replay pool (`TDataManager`, `Utils.pas:430-454`) sized
  by a precomputed `DecMem3` written into the container (`:2438`). Reported
  to cut both size and decode time (`changes.txt:8`).
- **Reprocess/reassign** (`-r`/`-a`, 0.7.9): `-r<codec>` re-compresses
  already-detected streams with a *different* codec in place, writing
  `[origsize|newsize]` trailer markers into the data (`Reproc`,
  `PrecompMain.pas:1308-1353`) that scanners later recognize via the
  `REPROCESSED` flag (`PrecompOodle.pas:519-526`); `-a` retries failed
  streams under another codec.
- **`-o` OPTIMISE_DEC**: after a level matches, search *downward* for the
  lowest level that still reproduces bytes → faster decode for free
  (`PrecompOodle.pas:622-641`).
- **Resource system**: config/DB plugins can attach binary resources (e.g.
  per-game dictionaries) embedded into the container itself (`Resources`,
  `PrecompMain.pas:1884-1894`), so decode is self-contained.
- **Known limitations from changes.txt**: 2 GB memory issues fixed only at
  0.2.9; x86 build discontinued 0.3.20 (`:226`); library injection removed
  0.7.9 ("buggy", `:18`); patch/archive commands removed 0.7.9 (`:19-20`);
  fast-lzma2 MT decompression removed for memory reasons (`:80`).

## ADOPT list (ranked)

1. **Verify-by-recompress with byte-compare, else store raw** — the entire
   lossless guarantee in one rule; a stream only enters the transformed set
   if `recompress(decompress(s)) == s`, otherwise it ships untouched.
   *Python:* our B6 stage runs xtool which already does this; for our own
   future stages (Precomp/zstd), enforce the same invariant in the pipeline
   contract. **Effort S.**
2. **Ship the DLL identity in the manifest** — xtool's
   restore-by-recompression makes the oo2core DLL part of the data contract.
   *Python:* store `{oodle_dll_name, sha256, source_relpath}` in
   `manifest.json`; at restore, locate/verify before invoking decode; refuse
   with a clear error otherwise. **Effort S.**
3. **zstd `refPrefix`+LDM patching with a 5% acceptance gate**
   (`PrecompUtils.pas:1039-1105,1522-1530`) — near-miss recompressions
   salvaged by a tiny diff instead of storing raw. *Python:* `zstandard`
   `ZstdCompressionParameters(window_log=..., enable_ldm=True)` + compress
   with dict prefix, or CLI `zstd --patch-from`; accept if
   `len(patch) <= 0.05*max(old,new)`. Useful for our Precomp/deflate stage
   too. **Effort S-M.**
4. **(size, xxh3_128) memo DB with negative caching** (`CheckDB/AddDB`) —
   never brute-force the same stream twice, *including remembering failures*.
   *Python:* dict keyed `(size, xxh128)` → `{codec, params, status}`; persist
   per-archive or per-game profile. **Effort S.**
5. **MTF candidate-parameter lists** (`TSOList`) — try the last-successful
   level first; on game data one level usually dominates, collapsing the
   9-level search to ~1 attempt. *Python:* `list.insert(0, hit)` per worker
   per codec. **Effort S.**
6. **Game fingerprint databases (dbgenerator model)** — precomputed
   `.xtl`-style "recognize file by CRC ladder → known stream table"
   eliminates scanning entirely for known games; two-phase workflow
   (`precomp -x` extract → `generate`) is fully automatable in CI. *Python
   for B6:* just ship/curate `.xtl` files in xtool's plugins dir per game
   profile; long-term reimplement the 4 MB-CRC ladder for our own router.
   **Effort M.**
7. **Declarative INI signature plugins** — game-format support without code:
   signature + field layout + size expressions + conditions
   (`PrecompINI.pas`). *Python:* YAML profile + `struct` + `simpleeval` for
   our router's game-specific containers. **Effort M.**
8. **Stream dedup before compression** (`TDuplicate1`/`TDataManager`) — game
   archives repeat identical compressed blocks across localization/platform
   variants; dedup on decompressed-stream hash costs one dict. *Python:*
   manifest-level `dup_of` entries; replay pool with refcounts at restore.
   **Effort M.**
9. **Dual-signature DLL binding with decorated-name fallback**
   (`OodleDLL.pas:119-190`) — if we ever bind oo2core directly via ctypes:
   resolve `OodleLZ_Decompress` else `_OodleLZ_Decompress@56`; gate
   signatures on `Oodle_CheckVersion` high word (`< $2E06` = old Compress
   ABI). **Effort S.**
10. **Fill-byte sentinel size discovery** (`LocalLZ_Decompress`,
    `PrecompOodle.pas:218-238`) — determine unknown decompressed size by
    pre-filling the tail with a sentinel and measuring overwrite, two passes
    with different sentinels to kill false positives. Needed only if we write
    our own Oodle scanner. **Effort M.**

## Gotchas

- **Restore = recompress.** Decoding an xtool container needs the same codec
  DLLs with byte-identical encoders. Oodle/LZO have **no patch fallback**
  (removed 0.6.5, `changes.txt:113`); a version drift makes decode raise
  `'Error in the method ...'` and exit 1. It fails loudly (good), but our
  manifest must pin the DLL (see ADOPT #2).
- **Container bytes are nondeterministic** across runs/thread-counts/
  chunk-sizes (MTF state + scheduling). Never dedupe or verify by hashing the
  `.xtp`; hash restored payloads.
- **`-s` kills the guarantee** (all non-crypto streams accepted unverified,
  `PrecompMain.pas:1385`). Blacklist it in our wrapper.
- **No parseable progress when stderr is piped** — `WriteConsole` no-ops on
  redirected handles (`Utils.pas:682-688`); `-v` forces single-thread. Exit
  code is the only reliable signal (0/1).
- **Temps land in CWD** (`*-storage.tmp`, `*-dd.tmp`, `*-vm.tmp`, exe-plugin
  dirs); crashes can leave them. Run in a scratch cwd and sweep it.
- **Int32 limits everywhere**: single stream OldSize/NewSize < 2 GB; `-c`
  clamped ≥4 MB, ≤2 GB-1; streams larger than the chunk are missed by inline
  scanning (only `generate`/IO functions handle bigger, `changes.txt:154`).
- **`-t 50p` default = 1 thread on our 2-core target**; pass `-t2`
  explicitly. `-dd#` silently degrades to plain `-dd` if `srep.exe` isn't in
  the plugins dir (`PrecompMain.pas:261-267`) — and srep is not OSI, so we
  must not ship it; plain `-dd` is fine.
- **`archive`/`patch` commands are ghosts** (listed in help, handlers removed
  0.7.9).
- **contrib/ licensing is mixed** (FastMM4 GPL/LGPL, mORMot tri-license).
  xtool's own units are MIT; we take concepts only, so we're clean either way
  — but do not vendor contrib code.
- **The oodle scanner trial-decompresses aggressively** ($8C/$CC byte
  prefilter is weak); on incompressible data expect slow scans. Restrict `-m`
  to codecs the game profile actually needs, keep the DB plugin path (`.xtl`)
  as the fast lane.
- **`GetOodleUS` rejects streams that don't expand** (`Result > CSize`,
  `PrecompOodle.pas:319`) and <64-byte streams — tiny/incompressible Oodle
  blocks stay raw by design; don't chase 100% stream coverage in benchmarks.
