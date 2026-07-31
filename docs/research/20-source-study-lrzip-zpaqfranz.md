# 20 — Source study: lrzip + zpaqfranz (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference. Two questions answered from source: (a) what is our best *legal,
> Windows-viable* long-range dedup pre-stage, and (b) the journaling/verify
> machinery for zpaqfranz (Phase B1 Insane profile + D5 deep-verify).
> Commits studied: **lrzip `24bffa12061337f328ae0a13f480a0f2c475fe86`**
> (2026-07-13, GPLv2, github.com/ckolivas/lrzip), **zpaqfranz
> `cc34e224d816e50234d5b7cf30e579ec1e89f0eb`** (2026-06-29, v64.8j, MIT,
> github.com/fcorbelli/zpaqfranz — a single 127,439-line `zpaqfranz.cpp`).
>
> ⚠️ **License boundary:** lrzip is GPLv2 — ideas/parameters only.
> zpaqfranz is MIT but we drive the exe (conceptual reuse).

## Architecture

- **lrzip** — two-phase: an **rzip pre-pass** (`rzip.c`) finds long-range
  exact matches inside a giant mmap'd "chunk" and rewrites input as a token
  stream (stream 0 = match/literal control tokens, stream 1 = literal
  bytes), then backend-compresses the streams with lzma/zstd/bzip3/zpaq in
  threads (`stream.c`). Decompression (`runzip.c`) replays tokens against
  already-written output (seek-back copy). Everything hangs off POSIX mmap.
- **zpaqfranz** — fork of zpaq 7.15 journaling archiver. Add path: scan →
  sort → content-defined chunking into fragments (order-1-prediction
  rolling hash) → SHA-1 per fragment → dedup lookup against all fragments
  ever stored → new fragments packed into ~64 MiB blocks, each compressed by
  a ZPAQL method chosen per detected data type (LZ77 / BWT / CM) → appended
  as an immutable, dated `jDC` transaction. Franz additions: per-file CRC-32
  + a second hash (XXHASH64 default) in a length-prefixed attr extension,
  plus a large verify-command suite.

## Answers

### 1. lrzip rzip pre-pass design

- *Rolling hash*: not Karp-Rabin — a **Zobrist/XOR tag** over a fixed
  `MINIMUM_MATCH=31`-byte window (`rzip.c:69`). `hash_index[256]` random
  32-bit tags (`rzip.c:1099-1105`); full tag = XOR of table entries for 31
  bytes (`rzip.c:547-595`); rolled by XOR-out byte `p-1`, XOR-in byte
  `p+30` (`rzip.c:521-529`).
- *Sparse sampling, fixed memory*: tags inserted only when low bits match a
  mask (`(t & tag_mask)==tag_mask`, `rzip.c:1041-1047`). When the table
  passes 2/3 full (`rzip.c:971`), `clean_one_from_hash` widens the required
  mask and evicts (`rzip.c:493-519`) — **table size is fixed regardless of
  window size**: `levels[]` maps level → 1..64 MB of slots + chain length
  (`rzip.c:88-103`); entries 8 B, or 16 B ("wide") when chunk > 4 GiB
  (`rzip.c:405-433, 949-950`). Level 9: 2^23 slots × 16 B = 128 MB max.
- *Match search*: linear-probed lookup with capped probes/chain
  (`find_best_match`, `rzip.c:772-814`); candidate extended forward
  word-at-a-time and **backwards** past the tag position (`match_len_linear`,
  `rzip.c:602-651`); min useful match 31 B, matches ≥ `GREAT_MATCH=1024`
  emitted immediately (`rzip.c:1055-1064`).
- *How far back*: offsets are chunk-relative, so match range = chunk size.
  Default chunk = min(file, **2/3 of RAM**) (`rzip.c:1387-1398`); `-U` sets
  chunk = whole file → effectively unlimited distance via a **sliding
  mmap**: one big low map (≤ ramsize/3) + a page-sized high map remapped on
  every far access (`rzip.c:108-145`) — the code's own comment: "much
  slower than mmap but makes it possible to have unlimited sized compression
  windows" (`rzip.c:140-145`).
- *Encoding*: stream-0 tokens — literal `{0x00, len:2B}` + bytes to stream
  1; match `{0x01, len:2B, offset:chunk_bytes LE}` where `chunk_bytes` =
  minimal byte width for the chunk. Tokens cap at 64 KiB.
- *Memory scaling*: constant in file size — hash table (≤128 MB) + low
  mmap (RAM/3) + backend. Decompression needs no table at all.
- *Why it kills on repack-style input*: byte-granular exact matches ≥31 B at
  whole-file distances, run **before** the backend, so duplicate game
  assets hundreds of MB apart collapse to ~10-byte tokens. Their benchmark:
  6 kernel trees (2.37 GB): 7z 14.5% vs lrzip 4.4% vs `lrzip -U` **3.1%**
  (`doc/README.benchmarks:45-70`).

### 2. Windows viability: NO

lrzip is hard-POSIX: `mmap/munmap/mremap` at the design core (with a
`fake_mremap` for non-Linux, `rzip.c:1107-1129`), `sys/statvfs.h`,
`sysconf(_SC_PHYS_PAGES)` for RAM detection (`lrzip.c:99,127`), mandatory
pthreads (`configure.ac:118-119`). The **only** Windows-ish ifdef in the
tree is an `ffsll` shim for MinGW/Cygwin (`lrzip_private.h:157-159`); there
is no `_WIN32` path anywhere. The one historical claim is "Now builds on
Cygwin" (`WHATS-NEW:220`). **Do not plan to ship lrzip on Windows** — a
Cygwin-shipped GPL binary in an MIT, Windows-first tool fails both our
license posture and our maintenance bar.

### 3. Parameter guidance

`-w N` = window in **N×100 MB** (`CHUNK_MULTIPLE`, `rzip.c:66`; man
`lrz.1.pod:307-312`). Default window = 2/3 RAM; mmap = RAM/3. `-U` costs:
README says unlimited mode can be "drastically" slower when window ≫ RAM,
but *faster AND smaller* when the file is only modestly bigger than RAM (the
6-kernel case — rzip removed so much data the backend had less to do). Level
(`-L`) scales the hash table/chain (`levels[]`, default 7). Docs' claim vs
plain lzma: identical-ratio-but-faster on single trees, several-times-better
on far-apart redundancy.

### 4. VERDICT — (b) + (c); do not build (a); defer (d)

**Keep `zstd --long=31` / 7z big-dict as the default long-range strategy,
and get "unlimited-distance" dedup from the zpaqfranz Insane stage already
planned in B1.**

- **(a) lrzip stage: rejected on shipping grounds, not on merit.** The
  algorithm is the best byte-granular long-range matcher of the four, but
  it is GPL (ideas only) and structurally unportable to native Windows
  (answer 2). A Cygwin-shipped GPL binary fails our license + maintenance
  bar.
- **(b) covers ≤2 GB distances well.** `zstd --long=31` = 2 GiB window; 7z
  on 16 GB can run ~1.5 GiB dictionaries with `qs` sorting. For inputs
  whose duplicate assets sit within ~2 GB of each other (most repack folders
  after our router groups by type + 7z `qs` reorders by extension), (b)
  already captures what rzip would. What (b) *cannot* do is match across
  >2 GB gaps in 100 GB+ jobs.
- **(c) zpaqfranz closes exactly that gap at zero extra engineering.** Its
  CDC dedup (answer 5) matches identical 4 KB–500 KB fragments at
  **unlimited distance** — dedup index ≈ `#fragments × 28 B` + a 4×-slot
  hash table, i.e. ~3.2 M fragments ≈ <500 MB RAM for 200 GB of data at the
  default 64 KB average fragment — comfortably inside 16 GB, single pass, no
  mmap games. Since B1 ships it for Insane anyway, the "Insane" answer to
  SREP is already in the plan. Granularity caveat: CDC at 4 KB min fragment
  misses sub-4 KB and near-duplicates that rzip's 31-byte matcher catches —
  accept this; the backend's own window mops up short-range redundancy.
- **(d) Python CDC pre-stage: defer.** Feasible (fastcdc-style, MIT deps
  exist) and would give container-native dedup for non-Insane profiles, but
  on 2 cores pure/py-accelerated chunking + SHA-256 will bottleneck
  (zpaqfranz needed hand-unrolled ×4 byte loops just to keep the boundary
  scan fast, `zpaqfranz.cpp:123405-123477`), and it duplicates what (c)
  gives Insane for free. Revisit only if telemetry shows big cross-file
  duplication in Normal-profile jobs.

### 5. zpaqfranz journaling/dedup model (`Jidac::add`, ~`:122540+`)

- *CDC*: order-1-prediction rolling hash — `o1[256]` predicts next byte from
  previous; on hit `h=(h+c+1)*314159265`, on miss `h=(h+c+1)*271828182`
  (`:95808-95829`; unrolled fast path `:123073`, `:123405-123477`).
  Boundary when `h < 2^(22-fragment)` and `sz ≥ MIN_FRAGMENT` (`:95834`).
  Sizes: `-fragment N` default 6 → avg 2^N KiB = **64 KiB**,
  `MIN_FRAGMENT = 64<<N` = 4 KiB, `MAX_FRAGMENT ≈ 508 KiB`. Boundaries
  prefer compressible cut points, not plain Rabin.
- *Fragment IDs*: **SHA-1 (20 B) is the dedup key** (`HT.sha1[20]`,
  `:44777-44781`); CRC-32 per fragment added for verify. Lookup via
  `HTIndex` open-addressed map (`:71736-71796`); found → file references old
  ID (dedup **across all versions**); miss → fragment appended to current
  block. XXHASH64 is *not* the fragment ID — it's the default whole-file
  second hash.
- *Blocks & methods*: default `-mN` expands to `N6` for N≥2 → block ≈
  **64 MiB** (`:122566-122584`). Per block, data is typed
  (text/exe/redundancy) and `compressBlock` picks the ZPAQL config
  (`:20313-20439`): **-m4** = store / LZ77 / LZ77+CM / BWT+ICM / mid-range
  CM (ICM + 4-ISSE chain + MATCH + optional word model + MIX); **-m5** = big
  CM (word ISSE chains + auto-detected periodic models + mixer). `doe8` =
  E8E9 x86 transform when exe detected.

### 6. Verify machinery & exact CLI for B1/D5

- `t` (test): archive-only. Structural invariants (`Jidac::test`,
  `:80534-80600`) then **multithreaded full decompression to RAM** with
  per-fragment SHA-1 re-check, no disk writes (`:80601-80706`). With file
  args → `testverify()` (SHA-1-chunked compare vs named files).
- `v` (verify): **re-reads source files from the filesystem**, recomputes
  the stored franz hash per file, compares (`Jidac::verify`,
  `:88913-89000`; `-ssd` = multithread). Archive⟷disk, but trusts the
  archive's stored hashes (does not decompress).
- `p` (paranoid): re-extracts everything **in RAM with the independent
  unzpaq206 reference decompressor** (help `:65507-65529`); `p -verify` also
  hashes against the filesystem. Not multipart-capable, high RAM.
- `t -paranoid -to dir`: physically extract, check, delete — ⚠️
  **interactive captcha prompt if `-to` is non-empty** (`getcaptcha`,
  `:80568`) — avoid in automation unless dir is empty.
- **Recommended invocations** — B1 add: `zpaqfranz a archive.zpaq <files>
  -m4 -longpath` (defaults store CRC-32+XXHASH64/file; add `-test` for a
  post-add decompress-check in one command). Routine integrity (no source):
  `zpaqfranz t archive.zpaq`. D5 deep-verify vs source dir: `zpaqfranz v
  archive.zpaq -ssd` (disk re-read) **plus** `zpaqfranz t archive.zpaq`
  (decompressed-bytes check) — together they equal "extract-and-compare"
  without temp space; nuclear option `zpaqfranz p archive.zpaq -verify`
  (single-part only, high RAM).

### 7. Windows specifics (lessons for D2 matrix)

- Long paths: `\\?\` prepended by `preparelongpath/makelongpath` but **only
  when `-longpath` is passed** (`:29785-29852`); without it, add measures
  the longest filename to warn. **Lesson: make long-path handling
  default-on in excmp, not a flag.**
- ADS: detected via `:$DATA` (`isads`, `:28607-28613`); **skipped by
  default**, stored only with `-forcewindows`/`-715`; enumeration via
  dynamically-loaded `FindFirstStreamW`.
- Symlinks/reparse: directory reparse points (junctions) — comment:
  "REPARSE_POINTS are a nightmare. For now: just skip" (`:71264-71270`);
  file symlinks stored as regular files unless `-nosymlink`. **Lesson: D2
  should decide junction/symlink policy up front; "skip + warn" is the
  shipped-in-production answer.**
- Also: `-vss` shadow copy for locked files; UTF-8/ANSI collision and
  case-collision counters at scan time.

### 8. RAM/threads at -m4/-m5

Threads default = all cores (`:69414-69415`), `-tN` to cap. Component memory
from libzpaq's estimator (`:14259-14264`): CM=4·2^sizebits,
ICM/ISSE=64·2^sizebits, MATCH=4·2^sizebits+buf. At default 64 MiB blocks:
**-m4** mid-CM ≈ 6-8 components ≈ **0.4-0.55 GB/thread** + ~128 MB block
buffers; **-m5** ≈ 10-12 components ≈ **0.7-0.9 GB/thread**. On 2-core/
16 GB: 2 threads × ~1 GB ≈ 2 GB peak — **both -m4 and -m5 fit easily**; the
binding constraint is CPU (CM ~1-3 MB/s/core). `p` (paranoid) is the only
RAM hazard (whole version in RAM). Sane Insane ceiling on target: `-m4 -t2`;
`-m5` only for small precious sets.

### 9. franz-blocks & vanilla-zpaq compatibility

Franz metadata (hashes, CRC, dates, POSIX/symlink info) lives **inside the
length-prefixed attr field** of the index i-block (`FRANZOFFSETV1/2/3`,
`:1884-1886`; `writefranzattr` `:72400-72410`). Data blocks are standard
`jDC` journaling blocks with standard ZPAQL methods, so **vanilla zpaq 7.15
and unzpaq206 can list/extract zpaqfranz archives** (README `:278-290`; the
`p` command literally proves decodability with the reference decompressor).
Safe rules for B1: plain `a ... -m4` (+`-longpath`) keeps archives
7.15-readable; `-715` forces byte-identical 7.15 behavior if needed. Avoid:
`backup` multipart index files, `-backupzeta`, `-chunk`ed W-extract — those
add zpaqfranz-only sidecars.

### 10. Other genuinely valuable finds

- *File ordering before solid blocks*: files sorted by extension/size then
  path before chunking (`:122637`, comparators `:63704-63723`, custom
  `-orderby`) — same trick as our router + 7z `qs`; validates our design.
- *`sum` command as excmp-hash model*: multithreaded (`-ssd`),
  memory-mapped (`-mm`) hashing with a **cumulative order-independent
  "GLOBAL SHA256"** for whole-tree equality (`:66157-66171`) — exactly the
  shape our ledger comparator wants.
- *XLS forced re-add*: Excel mutates metadata **without changing size or
  mtime**, so zpaqfranz force-re-hashes xls/ppt on every add
  (`:122662-122675`) — adopt this "untrustworthy timestamp" exception class
  in our incremental logic.
- *Append-only transaction model*: each update is one appended dated
  transaction; incomplete tails auto-trimmed — model for our container's
  crash-safety story.
- *`backup`/`testbackup`*: multipart chunks + per-part MD5/XXH3 index for
  WORM/cloud — the pattern for multi-hundred-GB excmp jobs.
- *CRC-32-from-fragments vs CRC-32-from-file cross-check* during add
  (`:72390-72398`) — a cheap dedup-error tripwire; mirror it in D5.

## ADOPT list (ranked)

1. **zpaqfranz as the Insane long-range dedup + archive stage (B1)** —
   unlimited-distance CDC dedup, journaling, fits 16 GB at -m4/-m5, MIT,
   7.15-compatible. Drive the exe: `a arch.zpaq <in> -m4 -longpath
   [-test]`, verify `t` + `v -ssd`, deep `p -verify`; parse its numbered
   `NNNNN:` message codes for progress. **Effort S.**
2. **D5 deep-verify = `t` (decompressed-bytes SHA-1) + `v -ssd` (disk
   re-read vs stored hash)** — covers archive rot AND source drift without
   temp extraction. **Effort S.**
3. **Order-independent global tree hash (from `sum`)** — single-value
   equality for whole outputs, perfect for repack A/B validation against
   our SHA-256 ledger. **Effort S.**
4. **"Untrustworthy timestamp" re-hash exceptions (XLS lesson)** — an
   extension blacklist forcing full hash regardless of size+mtime match.
   **Effort S.**
5. **Append-only container transactions + tail-trim recovery** — crash-safe
   .excmp updates, rsync-append friendliness. **Effort M.**
6. **rzip's *ideas* (GPL-safe, parameters only) for a future Python CDC
   pre-stage (option d, deferred)** — sparse tag sampling with adaptive
   culling (fixed-RAM index), min-match/great-match thresholds,
   chunk-relative variable-width offsets; fastcdc(MIT) chunker at 4 KiB
   min / 64 KiB avg + SHA-256 dedup store. **Effort L**, telemetry-gated.
7. **Long-path default-on + junction/ADS policy matrix (D2)** — always
   `\\?\` internally, skip junctions with a warning, ADS opt-in.
   **Effort S.**

## Gotchas

- **lrzip GPL boundary**: parameters/architecture only; no code or
  stream-format re-implementation from source.
- **lrzip matches never cross chunk boundaries** — without `-U`,
  "long-range" is capped at 2/3 RAM (≈10 GB on target); `-U` on files ≫ RAM
  page-thrashes.
- **This lrzip is a moving fork**: 2026 tree has AEAD, chunk prefilters, a
  NOT-backward-compatible format — online benchmarks refer to older
  formats.
- **zpaqfranz `t -paranoid -to` can block on an interactive captcha** when
  the target folder is non-empty (`:80568`) — never use in the pipeline;
  use `t` + `v`.
- **`p`/`P` paranoid commands hold a whole version in RAM** and refuse
  multipart — gate behind an archive-size check on the 16 GB target.
- **Don't assume `-m5` ≫ `-m4`**: both use 64 MiB blocks; -m5's gain is CM
  depth, at ~2-3× the CPU. On 2 cores, -m4 is the realistic Insane default.
- **Dedup is exact-fragment only**: zpaqfranz won't catch near-duplicates
  or sub-4 KiB repeats — `zstd --long`/7z big-dict remain complementary.
- **SHA-1 is the fragment key** (collision-theoretic risk inherited from
  zpaq); CRC-32 per fragment + GURU cross-check mitigate — keep
  `-paranoid`-style CRC checking on for Insane adds.
- **Vanilla-zpaq compat holds only for plain `a`** — multipart `backup`,
  ZETA, W-chunk extraction are zpaqfranz-only.
