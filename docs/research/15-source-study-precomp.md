# 15 — Source study: Precomp 0.4.8 (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference (all refs are `precomp.cpp` unless stated). Studied commit:
> `a11b077425fb6f6c22fc39c3265a2c1af7333665` ("Update LICENSE", 2025-06-26)
> from https://github.com/schnaader/precomp-cpp.

## Version & status

- **Version:** Precomp **v0.4.8 DEVELOPMENT** (`precomp.cpp:20-26`:
  `V_MAJOR 0 / V_MINOR 4 / V_MINOR2 8`, `V_STATE "DEVELOPMENT"`,
  `V_MSG "USE AT YOUR OWN RISK!"`). Copyright banner says 2006-2021 (`:639`).
- The code is unchanged since ~2021 (readme stops at 2016,
  `changes_before_git.txt` at 2013, dead travis-ci badges). Project is
  effectively **stalled/dormant**: the only 2025 activity is a LICENSE
  touch-up.
- **Successor tech referenced in-repo:** none as a project, but README.md:82
  credits **preflate v0.3.5 (Dirk Steinke)** — the deflate-reconstruction
  engine that *replaced* precomp's old zlib level brute-forcing in 0.4.8 —
  and brunsli (Google) for JPEG.
- **License:** top-level `LICENSE` = Apache-2.0; but the runtime banner still
  prints "Free for non-commercial use" (`:639`) — a leftover contradiction.

## Answers

### 1. Main scan loop & signatures (`compress_file`, 3676-4548)

Byte-by-byte scan: `for (input_file_pos = 0; input_file_pos < fin_length;
input_file_pos++)` (3701) over a 64 KB sliding window `in_buf`
(`IN_BUF_SIZE` 65536, refilled when < 4 KB lookahead remains, 3707-3719;
`CHECKBUF_SIZE` 4096 per-position lookahead). At each offset it tests, in
fixed order (each gated by `use_*` flags / `-t` switch):

- **ZIP**: `'P','K',3,4` local file header, method byte must be 8=deflate
  (3731-3771)
- **gzip**: `1F 8B`, CM==8, reserved FLG bits zero; walks
  FEXTRA/FNAME/FCOMMENT/FHCRC to find header length (3773-3851)
- **PDF**: literal `/FlateDecode` then `stream` + EOL, then zlib header check
  `((b0<<8+b1)%31)==0`, CM==8, FDICT unset (3853-3997); optional
  `/Width`/`/Height`/`/BitsPerComponent` parse for BMP-wrapping (`-pdfbmp`)
- **PNG**: literal `IDAT`, walks chained IDATs collecting lengths/CRCs
  (3999-4108); single-IDAT vs `try_decompression_png_multi` for multi-IDAT
  (concatenated into `tempfile0` first, 4077-4094)
- **GIF**: `GIF8[79]a` (4110-4133)
- **JPG**: `FF D8 FF` + valid marker; full marker walk validating
  DQT/DHT/SOF0/SOF2 up to SOS, then scans entropy data to EOI `FF D9`
  (4135-4212)
- **MP3**: `FF` + `(b&0xE0)==0xE0` framesync; parses frame chain, requires
  ≥5 consecutive consistent frames, MPEG-1 Layer III only (packMP3
  restriction), CRC-validates side info (4214-4353, `is_valid_mp3_frame`
  7010)
- **SWF**: `CWS` + zlib header at offset 8 (4355-4381)
- **MIME Base64**: case-insensitive `content-transfer-encoding: base64` +
  double CRLF (4383-4426)
- **bZip2**: `BZh` + level digit '1'-'9' (4428-4444)
- **`-intense`** (4447-4493): additionally treats *any* 2 bytes passing the
  raw zlib header test (`%31==0`, CM==8, FDICT unset — incl. classic
  `78 01/9C/DA`) as a candidate, pre-qualified by a trial `inflate()` of up
  to 2048 input bytes (`check_inf_result`, 2712-2789; streams ending with
  < 32 output bytes rejected as false positives, 2783).
- **`-brute`** (4495-4529): headerless raw deflate — trial-inflates with
  windowbits −15 at **every byte offset**. Cost controls: byte-histogram
  prefilter over first 256 bytes rejects over-redundant data (2721-2735),
  BTYPE 00/11 skipped (2714-2719), min 1024 output bytes (2784). Help text
  itself says "VERY slow" (1221). Both accept `-intenseN`/`-bruteN`
  recursion-depth caps (696, 729; checked at 2524, 2531). Failed candidate
  offsets are remembered in `intense_ignore_offsets`/`brute_ignore_offsets`
  sets so they're never retried (3510-3511, 3574-3575).

### 2. Deflate parameter recovery — preflate, not level brute-force

`try_recompression_deflate` (3162-3222) calls **`preflate_decode(uos,
result.recon_data, ...)`** (3178) which decompresses the stream AND emits
`recon_data`: a per-stream correction/diff blob produced by preflate's open
zlib-encoder model (`contrib/preflate/preflate_complevel_estimator.*`
estimates level/windowbits/memlevel, then arithmetic-codes every place the
real stream diverges from the model's prediction). Restoration is
`preflate_reencode(recon_data, uncompressed) → original bytes` (3238). The
old approach survives only as vestigial scaffolding:
`recompress_deflate_result.zlib_perfect/zlib_comp_level/zlib_mem_level/
zlib_window_bits` (3064-3074) are `memset` to 0 (3170) and **never set
true** on the compress side; the read side still decodes the "perfect"
format (8153-8158) for compatibility. The 81-slot `zLibMTF` level cache
(precomp.h:100-130) and `show_used_levels` (3590) are dead weight in 0.4.8.

**Penalty bytes** (kept for bzip2/GIF): when re-compression is *almost*
identical, each mismatching byte costs 5 bytes of patch data — 4-byte
big-endian position + 1 replacement byte (`compare_files_penalty`,
5826-5912; also `compare_file_mem_penalty` 2972-3018). The running score
`same_byte_count_penalty` (+1 per match, −5 per mismatch) tracks the best
cut-off point; cap `MAX_PENALTY_BYTES` 16384 (264). At restore, the
recompressed output is written, then patched in place by seeking to
`old_fout_pos + pb_pos` and overwriting one byte each (bzip2: 5120-5136;
GIF: 4817-4834). Semantics: penalty bytes are **forward patches applied over
the freshly recompressed stream** — "recompress with same level, then fix
these N bytes".

### 3. Verification model — NOT uniform, and this matters

- **deflate/preflate paths (PDF/ZIP/GZIP/PNG/SWF/RAW/BRUTE):** acceptance =
  `preflate_decode` returning `accepted` (3178). Bit-exact round-trip
  re-encode + compare happens **only when `-pfverify` is set**
  (`preflate_verify`, default `false`, 218; verify block 3185-3219 — on
  mismatch `result.accepted = false` and the offending stream is dumped to
  `preflate_error_%04d.raw` in CWD). Without the flag, correctness rests on
  preflate's by-construction guarantee (recon data is generated *against the
  actual bytes*), not on an explicit compare.
- **bzip2:** genuinely verified in-place during compression: decompress →
  recompress at detected level → byte-compare vs original with penalty
  tolerance (`file_recompress_bzip2` 2901 → `def_compare_bzip2`; acceptance
  gates 7123, plus `partial_ratio < 3.0f` rule 5338-5339).
- **GIF:** verified: LZW-decode → re-encode → `compare_files_penalty`
  against original (6449-6458); rejected if `best_identical_bytes <
  gif_length`.
- **Base64:** verified: decode → re-encode → `compare_files` (7446-7450).
- **JPG/MP3:** **NOT round-trip verified at compress time.** Acceptance =
  brunsli/packJPG/packMP3 encoder returning success (6776-6800, 6945-6965);
  losslessness is delegated to those codecs' internal guarantees.
- **On failure:** the stream is left raw — `compressed_data_found` stays
  false, position/`cb` are rolled back (e.g. 3764-3767, 4348-4351), and the
  byte joins the current "uncompressed data" run (3533-4539). A candidate
  that fails is copied through untouched. Plus the restore-side hard-stop:
  every restore path checks reconstruction success and aborts the run on
  failure (`if (!ok) { printf("Error recompressing data!"); exit(0); }` —
  4658-4661 ZIP, 4693-4696 PNG, 5211-5214 brute, etc.).

### 4. Recursion (`-d`)

Default `max_recursion_depth = 10` (147); `-d[depth]` (711, 1213). After a
deflate/bzip2/base64 stream is accepted, the *decompressed* payload is
itself scanned: `recursion_write_file_and_compress` (8003) →
`recursion_compress` (7884-8002) saves ~50 globals on a hand-rolled byte
stack (`recursion_push` 7745-7807), writes the decompressed data to
`tempfile1`, and re-enters `compress_file` on it with OTF compression forced
off (7950: "we don't want compressed compressed streams"). If anything was
found, the recursed PCF replaces the plain decompressed data and bit 128 is
set in the stream's flag byte (8197-8203); depth cap reached ⇒ stream
stored non-recursively (7895-7898). Cost: each level re-runs the full
signature scan over the decompressed data and allocates a fresh 64 MB
`decomp_io_buf` (3681) + temp files; `-intenseN`/`-bruteN` exist precisely
to stop those modes from multiplying in recursion (help 1241-1245).

### 5. JPEG & MP3 libraries (contrib/)

- `contrib/packjpg` — **packJPG v2.5k**, Matthias Stirner; license header in
  `packjpg.cpp:10-22`: **LGPL v3** "and special permissions". Invoked
  in-process via `pjglib_convert_stream2mem` / `pjglib_convert_file2file`
  (6678-6700).
- `contrib/packmp3` — **packMP3 v1.0g**, same author/licensing family;
  `pmplib_convert_stream2mem/file2file` (6869-6883).
- `contrib/brunsli` + `contrib/brotli` — Google, **MIT**
  (`contrib/brunsli/LICENSE`). Brunsli is the *preferred* JPEG codec
  (`use_brunsli = true` default, 306): `brunsli::ReadJpeg`/
  `BrunsliEncodeJpeg` (6603-6615); `-brotli` optionally compresses JPEG
  metadata (307).
- **Fallback chain (JPEG):** brunsli → on failure (incl. missing Huffman
  table → retry after injecting a Motion-JPEG DHT, 6618-6665) → packJPG
  (`use_packjpg_fallback` default on, 6677-6682) → packJPG's own MJPEG-DHT
  retry (6705-6759) → give up ⇒ stream stored raw. Streams >
  `JPG_MAX_MEMORY_SIZE` = **512 MB** (`contrib/packjpg/precomp_jpg.h:4`) go
  through temp files and skip brunsli entirely (6683).
- **MP3:** packMP3 only, MPEG-1 Layer III only; on "synching failure" it
  truncates trailing garbage and retries once (6886-6911); characteristic
  failures set suppression sums so the same stream isn't retried at next
  offsets (6912-6932). `MP3_MAX_MEMORY_SIZE` = 512 MB.
- Others: bzip2 1.0.6 (BSD-like), giflib 4.1.4 (MIT-style), zlib 1.2.11,
  liblzma/XZ 5.2.3 (public domain), preflate 0.3.5 (**Apache-2.0**).
  ⚠️ For our OSI-clean rule: all OSI, but packJPG/packMP3 are **LGPL-3.0**
  — calling a stock `precomp.exe` as a subprocess keeps MIT excmp clean;
  static-linking a fork would add LGPL obligations.

### 6. Resource profile

- **Single-threaded scan.** The whole detect/decode/verify pipeline is
  sequential; the only multithreading is the `-cl` xz-MT *output*
  compression (`init_encoder_mt`, 8304; threads =
  `std::thread::hardware_concurrency()` fallback 2, 8319-8324). With `-cn`
  precomp is one core, full stop.
- **Memory:** fixed 64 MB `decomp_io_buf` per compress level
  (`MAX_IO_BUFFER_SIZE` 116-117, allocated at 3681 and again per recursion
  level); deflate streams whose decompressed size ≥ 64 MB spill mid-write to
  `tempfile1` (`UncompressedOutStream::write`, 3137-3151). JPEG/MP3 buffer
  up to 512 MB **in RAM** each (6590, 6862). preflate works in meta-blocks
  of `-pfmeta` KiB (default **2 MB**, 217, 883-889) which bounds its working
  set. LZMA cap only matters for `-cl`. Realistic worst case with `-cn`:
  ~64 MB + codec + up to 512 MB JPEG buffer.
- **Temp files:** created **in the current working directory**, names
  `~temp0000000NN.dat` (129-136, `init_temp_files` 7665-7724 probes for free
  names — inherently racy between processes). There is **no temp-dir CLI
  flag** — control it by setting the subprocess CWD. Spill behavior: deflate
  candidates < 64 MB never touch disk; bzip2 decompresses **every
  candidate** to `tempfile1` (5299-5309); GIF uses tempfile1+2 (6428-6448);
  base64 tempfile1+2 (7303-7444); multi-IDAT PNG copies IDAT payload to
  tempfile0 (4077-4087); recursion adds `tempfile1_` per level. Ctrl-C
  cleanup walks `tempfilelist` (8499-8512).
- **Why 2-5× inflation with `-cn`:** every accepted deflate/bzip2 stream is
  replaced in the PCF by its **fully decompressed bytes** plus recon/penalty
  metadata (`fout_fput_uncompressed` 8188 →
  `write_decompressed_data_io_buf` 2932); deflate payloads typically expand
  2-5×, unmatched bytes are copied 1:1 (3030-3043), so -cn output = input +
  Σ(stream expansion).
- **Flags our stage should expose:** `-cn` (output compression off),
  `-t±pzgnfjsmb3` (type toggles), `-d N` (recursion), `-intense[N]` /
  `-brute[N]`, `-s N` (min identical size, default 4; 280), `-i pos`
  (ignore offset), `-pfmeta KiB` / `-pfverify`, `-o` (output), `-e` (keep
  extension), `-v` (verbose). `-lm/-lt/-lf/-llc/-llp/-lpb` are irrelevant
  under `-cn`.

### 7. .pcf format essentials

Global header (`write_header` 5359-5389 / `read_header` 5436-5468): magic
`"PCF"` + 3 bytes version (`0,4,8` — restore **hard-rejects any other
version**, 5447-5452) + 1 byte OTF method (0=none/`-cn`, 1=bzip2,
2=lzma2-MT; enum precomp.h:139) + original filename (no path),
NUL-terminated. Everything after is the block stream (OTF-compressed unless
method 0). Blocks (`decompress_file` 4574-5243): flag byte `0x00` ⇒
uncompressed run: vlint length + raw bytes (4582-4592; length 0 = EOF
sentinel for bzip2-OTF). Otherwise flag byte (bit0 always 1; bit1 =
recon-data present (deflate) / penalty bytes (bzip2, GIF); bits2-5
type-specific; bit7 = recursion payload) + type byte: `D_PDF 0, D_ZIP 1,
D_GZIP 2, D_PNG 3, D_MULTIPNG 4, D_GIF 5, D_JPG 6, D_SWF 7, D_BASE64 8,
D_BZIP2 9, D_MP3 10, D_BRUTE 254, D_RAW 255` (325-339). Deflate-family
entry: vlint hdr_length + original header bytes, vlint recon_size +
preflate recon blob, vlint compressed_size, vlint uncompressed_size, then
payload (recursed PCF with vlint length if bit7, else decompressed bytes) —
writers 8133-8208. vlint is a 7-bit VLQ with bias (`fout_fput_vlint`
8118-8132 / `fin_fget_vlint` 8265-8274). Sanity-checking a claimed pcf =
first 7 bytes: `50 43 46 00 04 08 <00|01|02>`.

### 8. Why Oodle/LZ4/zstd can't be added the way deflate is (B6 justification)

Precomp's entire stream-entry design stores *only* `(decompressed bytes,
recon_data)` and assumes an **open encoder can deterministically regenerate
the original compressed bytes**: `fout_fput_recon_data` (8169-8177)
persists nothing but the preflate diff + sizes, and restore is
`preflate_reencode(recon_data, uncompressed) == original` (3235-3240) with
hard `exit` on mismatch. That assumption holds for deflate because (a) the
format is fully specified and **self-terminating** (BFINAL/BTYPE bits —
exploited by `check_inf_result` 2712 to detect streams from 2 bytes of
context, or none in brute mode), (b) ~all real-world streams come from
**one canonical open encoder (zlib)** whose choice-space (level 1-9 ×
memlevel 1-9 × windowbits) is small enough for preflate to model and
arithmetic-code the residual divergence cheaply, and (c) the decompressor is
freely linkable.

For **Oodle** every leg fails: decode requires the proprietary `oo2core`
DLL (nothing linkable exists); there is no open re-implementation of the
Kraken/Mermaid/Leviathan *encoders*, so no analogue of `preflate_decode` can
produce recon data — divergence between an approximating encoder and RAD's
would approach the size of the stream itself; encoder output varies by
Oodle **version and encode-effort settings**, so bit-exact re-creation needs
the exact shipped compressor; and raw Oodle blocks embedded in game archives
carry no self-terminating in-band signature comparable to a zlib header,
defeating the byte-scan detection model. The same structural argument
applies (more weakly) to raw LZ4/zstd blocks: decoders are open, but encoder
output is not canonical across versions/levels — which is exactly why
xtool's approach (call the game's own oo2core to re-encode) is the only
viable route, and why it can never be OSI-clean inside precomp.

Bonus in-repo evidence of how invasive even *one* new codec is: bzip2 — an
open, canonical encoder — still needed its own penalty-bytes compare
machinery (5315-5356) because level alone doesn't guarantee bit-exactness.

### 9. Exit codes & error taxonomy

`main` (499-541): **0** = success; **2** `RETURN_NOTHING_DECOMPRESSED` when
`compress_file()` found nothing (515-517 — *not an error*; the .pcf is
still valid). `error()` (7536-7597) exits with its code: **3** disk full
(also deletes the output file, 7560-7565), **4** temp file disappeared,
**5** ignore-pos too big, **6** ident-size too big, **7** recursion depth
too big, **8/9** option set twice, **10** space after `-o`, **11/12**
multiple output/input files, **13** Ctrl-C, **14/15** intense/brute limit
too big, **16/17/18** LZMA options set twice (defines 39-55). Generic
**`exit(1)`** for: bad switches, unreadable/unwritable files, wrong PCF
version (5443, 5451), JPG/MP3 restore failure (4905, 5183), MJPEG
corruption (4946).

**CRITICAL:** most deflate/GIF/bzip2 restore failures print
`"Error recompressing data!"` then **`exit(0)`** (4642, 4660, 4676, 4695,
4731, 4802, 4993, 5117, 5213, 5227) — and unsupported stream type also
`exit(0)` (5233), as does user declining the overwrite prompt (1263).
**Exit code 0 does not prove a successful restore.** Our stage must verify
by output-hash comparison, never by return code alone.

### 10. Other genuinely useful findings

- `-cn` is unequivocally right for excmp: the OTF lzma2/bzip2 stage (default
  `-cl`) is pure double-work when a solid stage follows; `-cn` also skips
  lzma memory pressure entirely. (README:14 explicitly endorses the
  `-cn`-then-stronger-compressor pipeline.)
- **MP3 parsing cache** (4227-4294): remembers the second frame of a parsed
  chain so overlapping candidates at successive offsets resume instead of
  re-parsing — turns O(n²) frame walking into O(n). Same pattern: MP3
  failure-suppression sums (6912-6932) and intense/brute negative-result
  offset sets (3510-3511). Worth replicating in any Python pre-scanner.
- **Brute-mode histogram prefilter** (2721-2735) — a 256-byte frequency test
  that rejects low-entropy windows before spending an `inflate()` — is the
  reason brute is merely very slow instead of unusable.
- False-positive guards worth copying: min decompressed size 32 (intense) /
  1024 (brute) (2782-2785), `min_ident_size` default 4, bzip2
  `partial_ratio < 3.0` rule (5329-5339).
- **Interactive overwrite prompt** `"Overwrite (y/n)?"` (1258-1271) has no
  `-y` override and blocks on `getche()` — automation must guarantee the
  output path doesn't exist.
- `tryOpen` silently **retries opens for 15 s** before `exit(1)` (7599-7620)
  — explains mysterious stalls under AV scanners on Windows.
- All progress/status goes to **stdout** with backspace-character animation
  (8448-8497) — capture but don't parse; rely on file outputs.

## ADOPT list (ranked)

1. **Post-restore hash verification as our acceptance gate** — precomp's
   exit codes lie (`exit(0)` on restore failure) and JPG/MP3/default-deflate
   paths aren't round-trip-verified at compress time. *How:* after
   `precomp <in>` and before trusting the .pcf, run `precomp -r -o<tmp>
   <pcf>` + hash compare vs original; keep the original on any mismatch.
   **Effort S.** (This *is* our lossless guarantee; precomp only guarantees
   it per-stream, and only conditionally.)
2. **Run each precomp job with `cwd=` a private scratch dir** — temp files
   (`~temp*.dat`, `preflate_error_*.raw`) land in CWD, name probing is racy
   across processes, and there's no temp-dir flag. **Effort S.**
3. **Expose exactly `-cn -d<N> -t±… -intense<N>/-brute<N> -s<N>
   -pfmeta<KiB> [-pfverify]`** as our stage's tuning surface; hardcode
   `-cn`; default `-d2`, `-intense0` optional profile, never `-brute` on
   weak hardware. **Effort S.**
4. **Cheap Python signature pre-scan before spawning precomp** — mirror the
   scan-loop signatures (PK\x03\x04, 1F 8B 08, /FlateDecode, IDAT, GIF8,
   FF D8 FF, BZh1-9, CWS, MP3 sync, CTE:base64) over each input; skip
   precomp entirely for files with zero hits. Saves a process spawn + full
   byte-scan per cold file. **Effort M.**
5. **Disk/RAM budgeting formula** — plan for pcf ≤ ~5× input on disk,
   +64 MB RSS base, +512 MB if JPEGs/MP3s present (or pass `-t-j3` under a
   low-RAM profile). Surface `RETURN_NOTHING_DECOMPRESSED (2)` as
   "pass-through, don't keep pcf". **Effort S.**
6. **PCF sniffing** — validate `50 43 46 00 04 08` + method byte ∈ {0,1,2}
   before ever feeding a file to `-r`; pin exact version 0.4.8 (restore
   refuses other versions anyway). **Effort S.**
7. **Negative-result caching across runs** (inspired by ignore-offset sets /
   MP3 suppression): remember per-file "precomp found nothing" (keyed by
   content hash) to skip re-scanning on repeated archive builds.
   **Effort M.**
8. **`-i<pos>` escape hatch** — if a specific stream ever crashes/hangs
   precomp, our stage can retry with that offset ignored; wire it into the
   retry policy rather than blacklisting whole files. **Effort M.**

## Gotchas

- **`exit(0)` on fatal restore errors** (10 sites, e.g. 4642, 5233) — never
  trust return code 0 from `-r`.
- **Overwrite prompt deadlock**: existing output file ⇒ interactive
  `getche()` wait; always emit to fresh paths.
- **`tryOpen` 15-second silent retry loop** (7607) — Windows AV/indexer
  contention shows up as stalls, not errors.
- **Version-locked format**: pcf from 0.4.8 restores only with 0.4.8
  (5447-5452); pin the binary, store its hash next to the archives.
- **`-pfverify` failure side effect**: dumps `preflate_error_NNNN.raw` into
  CWD (3204-3217) — another reason for private CWDs.
- **License texture**: binary banner says "free for non-commercial use"
  (639) while LICENSE is Apache-2.0; packJPG/packMP3 are LGPL-3.0.
  Subprocess use keeps excmp MIT-clean; do not vendor/static-link the
  codecs.
- **Vestigial code misleads**: zlib level tables, `zLibMTF`, `-zl`,
  `min_ident_size_intense_brute_mode` all predate preflate — don't tune
  against them; deflate behavior is 100% preflate in 0.4.8.
- Scan is O(bytes) even with all types disabled except one; `-brute` is
  O(bytes × inflate-attempt) — a research-only flag on the weak-hardware
  target.
