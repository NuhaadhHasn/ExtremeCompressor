# 17 — Source study: PeaZip (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference. Studied commit: `380ad9108129123532a248e3725d8c3231b1cbae`
> (2026-07-27) from https://github.com/peazip/PeaZip. Source root =
> `peazip-sources/`, all code in `dev/`.
>
> ⚠️ **License boundary:** PeaZip is **LGPLv3 Free Pascal**. Everything in
> this doc is *design, parameters, and observed behavior* — reimplement
> from this description, never translate the Pascal source. This report is
> the derivation record showing we copied concepts, not code.

## Architecture

PeaZip is three cooperating Lazarus/FPC programs, not one:

- **`dev/peach.pas` (80,134 lines)** — the `peazip` GUI/file-manager.
  Contains ALL backend orchestration: per-format `compose_*_cl()` functions
  build a full command-line string, `execute_cl()` (peach.pas:38018) runs
  it via `TProcessUTF8` with `poUsePipes|poNoConsole`, captures
  stdout/stderr into memory-capped `TMemoryStream`s (192 MB / 64 MB
  depending on "prebrowse" level; over-cap kills the child with
  `P.Terminate(255)`, peach.pas:38090-38098). Format→tool dispatch on
  create is a single `case` in `archive_mainsequence`
  (peach.pas:52860-52882). On open, extension→backend is
  `testext`/`testinput` in `dev/list_utils.pas:2309-2473` (e.g.
  `.br`→5001→brotli, `.zst/.zstd/.tzst`→5002→zstd, `.pea`→10001→pea,
  everything else→3 = 7z).
- **`dev/pea.pas` (+ `unit_pea.pas`, `pea_utils.pas`)** — a separate
  `pea.exe` implementing the .pea container (PEA = Pack/Encrypt/
  Authenticate), secure delete, split/join, hashing, MOTW check. PeaZip
  shells out to it like any other backend.
- **`dev/unit_gwrap.pas`** — the job-progress window; decodes exit codes
  (`decode_exitcode`, unit_gwrap.pas:1045).
- Crypto is Wolfgang Ehrhardt's Pascal library, vendored.
- Config, bookmarks, presets, session history are plain text files under
  `res/`; presets are `res/share/presets/0..15.txt` + `alt/*.txt`.

## Answers

### 1. Keyfile two-factor — exact construction

Two different constructions exist:

**(a) For all non-.pea formats (7z, zip, rar, arc — what our F2 compares
against):** `prepend_keyfile` (pea_utils.pas:2363-2399). The keyfile is
SHA-256-hashed by streaming (32 KB blocks; if `kflimit=1` — the default,
peach.pas:23092 — only the first 100 MiB are hashed, loop guard at
pea_utils.pas:2394), then:

```
pw := base64(SHA256(keyfile)) + typed_password        // pea_utils.pas:2397
```

That composite string is passed to the backend as an ordinary password
(`-p...` for 7z, peach.pas:51187-51212). So the "two-factor" is literally a
44-char Base64 digest prefix on the passphrase; the KDF is whatever the
backend applies. Keyfile-only usage is supported (empty password).

**(b) For the .pea format:** raw concatenation into the KDF input. In
`pea_procedure` (pea.pas:1954-1977): keying material = `password bytes ||
22 bytes of archive+stream header material (auth_buf) || raw keyfile bytes
(first 2048 bytes, via use_keyfile, pea_utils.pas:1728-1752)`. That array
is the "password" input to PBKDF2-Whirlpool or scrypt
(`FCA_EAX256_initP`, fcaes256.pas:246-299) with a 96-bit random salt. Note
the clever detail: archive headers are inside the KDF input, so header
tampering breaks key derivation.

**Comparison with our planned `HKDF(password, salt=SHA-256(keyfile))`:**
ours is structurally stronger than (a): HMAC-based extraction gives real
cryptographic binding instead of ASCII concatenation in the passphrase
channel; PeaZip's digest-prefix is separable, rides through process command
lines in plain text, and inherits whatever KDF the backend has. **One
critical caveat for us:** HKDF alone is fast — if it's the entire
derivation, password brute force is cheap. Do: `master = Argon2id(password,
random_salt)` then `key = HKDF-Extract(salt=SHA-256(keyfile), ikm=master)`.
Keep PeaZip's good ideas: stream-hash the keyfile with a size cap
(100 MiB), and support keyfile-only mode.

### 2. The .pea format

- **Archive header, 10 bytes** (`pea_archive_hdr`, pea_utils.pas:611-639):
  magic `$EA`, format version (1), revision (6), volume-control-algo byte,
  ECC byte (always `$00`, reserved), OS byte, datetime byte, charset byte
  (`$01` ANSI only), CPU/endianness byte, byte 9 = KDF iteration multiplier
  `niter`.
- **Stream header, 10 bytes** (641-667): trigger `00 00 'P' 'O' 'D' 00` +
  compression byte + ECC byte + stream-control byte + object-control byte.
- **Crypto subheader, 16 bytes per cipher** (`pea_eax256_subhdrP`,
  900-940): 2 zero bytes + 96-bit salt + 2-byte password-verifier field
  (zeroed in modern modes — "verification at the end", 933-935). Salt =
  512-bit entropy pool reduced through SHA-1 to 160 bits, first 96 used
  (920-924).
- **Integrity — three independent levels** (stream / per-object /
  per-volume), each selectable from the same registry
  (`decode_control_algo` pea_utils.pas:1302-1462; object 1464-1488; volume
  1490-1514): NOALGO, ADLER32, CRC32, CRC64, MD5, RIPEMD160, SHA1, SHA256,
  SHA512, SHA3_256, SHA3_512, WHIRLPOOL, BLAKE2S, BLAKE2B.
- **Authenticated encryption (stream level):** AES / Twofish / Serpent,
  256-bit, **EAX mode** (128-bit tag) singly, or triple-cascaded
  (`TRIATS` = AES→Twofish→Serpent etc.). KDFs: PBKDF2-Whirlpool
  `(niter*100000)+25000` iterations, or scrypt N=64K-1M/r=8/p=1-8, or
  hybrid (fcaes256.pas:254-283; format history pea.pas:151-162, 207-220).
  Cascade keys made independent via different hash primitives, salts, and
  per-cipher password tweaks; the three EAX tags are SHA3-384-hashed into
  one final tag; 1-128 random bytes inserted after the verifier to mask
  exact size (pea.pas:1990-2008). Since 1.32: constant-time tag comparison
  (pea.pas:247).
- **Volume splitting:** chunks `name.000001.pea`… (`update_pea_filename`,
  pea_utils.pas:2183-2197); each volume ends with its own volume-control
  tag (`ch_size:=ch_size-volume_authsize`, pea.pas:813-814); interactive
  re-prompt for missing volumes (`check_chunk`, pea.pas:664).
- **Compression:** only `PCOMPRESS0..3` = store / deflate-3 / deflate-6 /
  deflate-9, block-based with a 4-byte buffer-size field per block
  (pea.pas:2010-2020).

**What .excmp should borrow:** (1) the three-level integrity concept —
whole-stream AEAD + per-object hash + per-volume hash: per-object hashes
let you salvage/verify individual files from a damaged archive, per-volume
tags identify which split part is corrupt before any decryption; (2)
binding header bytes into the KDF/AAD (we get this free with AES-GCM AAD —
feed the container header as AAD); (3) explicit version+revision bytes and
one-byte algorithm registries; (4) size-masking padding as an optional
privacy feature; (5) "verifier at end" (no fast password oracle) —
PeaZip's older 16-bit `PW_Ver` in-header is exactly what NOT to do. Skip:
EAX (GCM is the modern equivalent), triple-cascade (complexity, weak
hardware), SHA-1 salt reduction, ANSI-only names.

### 3. Password strength meter — the actual algorithm

`evaluate_password` (pea_utils.pas:2273-2346), score in "entropy bits":

- +1 per character (length)
- quality bonus, once each, max +20: +2 lowercase present, +2 uppercase,
  +2 space ("multiple words"), +6 digit, +8 non-alphanumeric (excluding
  space); +1 base
- +3 per **unique** character (dedup loop at 2331-2343)
- cap: `score = min(score, 7 × length)` (2345)
- No dictionary check (documented, 2278-2279).

`ratepw` (2348-2361): `<24` weak, `<48` fair, `<72` good, `≥72` strong.
~20 lines in Python; consider zxcvbn instead, but this is a fine
dependency-free fallback.

### 4. Backend abstraction

- **Mapping:** no table — a `case archive_type` dispatch to per-tool
  `compose_*_cl` functions (peach.pas:52860-52882). RAR5 archives are
  sniffed (`testifrar5`) and rerouted to unrar even when 7z could handle
  them (51106-51109).
- **7z command construction** (compose_un7z_cl, 51092-51454) worth copying:
  overwrite policy map `-aos/-aou/-aot/-aoa` (51177-51183); `-spf2/-spf`
  behind an "Absolute paths" advanced setting defaulting to relative
  (51356-51361); `-scc{UTF-8,WIN,DOS}` console-charset pinning
  (51213-51217); `-bb1 -bse1 -bsp2` progress/log switches (51378); `-slt`
  only for detailed list; **dummy password `-pdefault` on list/test jobs so
  an encrypted archive errors instead of hanging on interactive prompt**
  (51233-51246 — essential trick for any 7z wrapper); `-i!name` include
  filters; `*`-prefix workaround for deleting absolute-path entries
  (51428).
- **`7z l -slt` parsing** (`list_slt`, peach.pas:36012-36211): find header
  end dynamically (`find_7z_titles` 35480 — scan for the separator, don't
  hardcode line counts); split fields on `' = '` (35510-35514); blank line
  = new record; handle `Path`, `Folder`, `Type=directory`, `Attributes`
  containing `D`, `Size`, `Packed Size`, `Modified/Created/Accessed`,
  `CRC`, `SHA-1`/`Checksum`, `Method` (flag encrypted if it contains
  `AES`), `Encrypted = +` (36109-36125); dedup duplicate directory records
  (36140-36150); UI yield every 16 K lines (36159); 0.5 M-row cap.
- **Exit-code table** (`decode_exitcode`, unit_gwrap.pas:1045-1058, strings
  895-900) — the 7-Zip table, reused generically: `0` success; `1`
  "Warning, non fatal error(s); i.e. some files missing or locked"; `2`
  "Fatal error occurred"; `7` "Error, got incorrect command line"; `8`
  "Error, not enough memory for requested operation"; `127` "Cannot
  execute requested operation"; `255` "Task halted by the user"; a
  `stopped` flag overrides all with "stopped by user". pea.exe's own codes:
  `0/1/-1/-2/-3/-4` (pea.pas:169-178).
- Every command string passes `validatecl` (list_utils.pas:2197-2260):
  rejects chars 0-31, `|`, 7+ consecutive spaces — **after first excising
  the password fields** so password content isn't policed/logged. (We use
  `subprocess` arg lists, which makes this machinery unnecessary — but the
  "redact passwords before validating/logging" rule carries over.)

### 5. Extraction safety

- **.pea zip-slip fix (May 2026, reported by Harshit Gupta; pea.pas:245):**
  at extract time (pea.pas:3698-3707) each stored name must satisfy
  `fn = ExpandFileName(fn)` — else abort; belt-and-braces explicit
  rejection of `../`, `..\`, and mixed separators anywhere; then
  re-canonicalize anyway. Three redundant layers — adopt the same
  "canonicalize, compare, reject" shape for D0:
  `resolved = (dest / name).resolve(); reject unless
  resolved.is_relative_to(dest.resolve())`.
- **For 7z-extracted formats** PeaZip delegates traversal defense to 7z
  itself (relative paths by default; `-spf` absolute mode is opt-in). It
  validates archive **member names before using them as filters**
  (`checkfiledirname` at 51421/51437/51447) and user-supplied names via
  `checkfilename` (list_utils.pas:2157-2187): rejects `''`, `.`, `..`,
  chars 0-31, `\/:*?<>|"`, 7+ spaces, and Windows reserved device names
  (`winreserved`, list_utils.pas:1726).
- **Own-temp protection:** `control_outpath` (peach.pas:49433)
  refuses/redirects extraction into PeaZip's own temp work dir.
- **Temp hygiene:** previews extract into per-job hidden dirs under user
  temp — `outdir + STR_STMP + hex(random(16 000 000))` with `faHidden`
  (peach.pas:51134-51168); preview uses `-aos` (never overwrite, 51344);
  drag-drop temp cleaned by `cleandragtmp` (79515); success verified by
  extracted size > 0 (38153-38156).
- **Windows-specific:** MOTW detection via PowerShell
  `-Stream Zone.Identifier` (pea.pas:7033, 7062) — the PowerShell argument
  sanitization there was itself a fixed vuln (pea.pas:246): **never
  interpolate archive-derived strings into PowerShell** (we do MOTW via
  direct ADS file I/O instead — see doc 14). On Windows they replace `:`
  with `_` in preview paths (51166, 51343) — kills ADS tricks.

### 6. UX patterns worth stealing

- **Command palette:** F12 → `runfunctions` (peach.pas:64067-64081) → a
  type-or-pick dropdown of every app function → `do_pmfun(caption)`
  dispatcher (61706-61767). Separately, the Options screen has a
  **settings search field** (`EditOptSearch`, ~63900-64050) that jumps to
  the right options page+scroll offset. Both map onto our I10 palette: one
  action registry, palette + settings-search fed from it.
- **Archive conversion** (`archive_convert`, peach.pas:58782-58816): not a
  wizard — it flips checkboxes on the normal Add screen, then the pipeline
  extracts each input archive to temp and recompresses to the target;
  `CheckBoxConvertPW` asks passwords up front. Conversion as a mode of Add
  = far less code.
- **Extract-and-open (double-click in browser):** mode `'extandrun'` →
  single-file extraction to the hidden temp dir → open with associated app
  (peach.pas:45730-45732); "specialopen" types (exe/bat/html needing
  siblings) extract the whole directory instead (51163-51169).
- **Presets/profiles:** `res/share/presets/{0..15}.txt` + `alt/` —
  human-readable text files (display name, general options, per-backend
  sections). Users swap presets by copying files. For us: TOML profiles as
  data files, ship "alt" presets as data, not code.
- **Session history:** browsing steps recorded and surfaced as "recent"
  menu entries (peach.pas:7601+, 11931-11936); "save layout" persists
  open-tabs/layout.
- **List-once, filter-locally:** the whole `-slt` output is parsed into one
  in-memory table; navigation inside the archive never re-invokes 7z
  (design comment peach.pas:363-410) with graduated "prebrowse" memory
  tiers (384-392). The right architecture for G1/G2 on weak hardware.

### 7. Other genuinely valuable bits

- **Keyfile/password generator with user-fed entropy** (unitkf.pas):
  2048-bit keyfiles (170-196) from a pool = persistent seed file + system
  fingerprint + mouse/keyboard/file-picking entropy, with an on-screen
  entropy progress bar (mouse move = 3 bits, keypress = 2, file pick = 2 +
  len + min(512, size); 207, 262, 294). In Python: just use `secrets`
  (entropy bar is theater then); keep size spinner + alnum toggle +
  "password from file hash" button (230-246).
- **Backend binary self-verification:** `checkchash` compares SHA-256 of
  every bundled tool against compiled-in constants; user-visible "verify
  binaries" function (peach.pas:17546-17605). Cheap supply-chain tripwire —
  adopt (hashes in a signed manifest).
- **Zstd/Brotli presets they chose** (peach.pas:32520-32545): Brotli levels
  exposed `0,1,2,3,6,9,11`, default **3**; `--large_window=27` opt-in
  (52301). Zstd levels exposed `1,2,3,5,7,11,15,19,22`, default **3**;
  command `zstd -T0 -q -{lvl}`, `--ultra -22` for 22, `--long=31` when
  "maximize" checked; decompress always `--long=31` (52394-52461). Curated
  level ladders beat exposing 1-22 raw.
- **Secure delete / free-space wipe** tiers (pea.pas:5350+) — low priority
  for us (and dishonest on SSDs; already on our skip list).
- **stdin password pipe** (`pipepw` written to child stdin,
  peach.pas:38070-38079) — keeps passwords off command lines for
  console-mode tools.

## ADOPT list (ranked)

1. **7z hang-guard + exit-code table + `-slt` parser details** — always
   pass a dummy `-p` on list/test so encrypted archives error instead of
   hanging; map exit codes {0,1,2,7,8,255} to typed exceptions; parse
   `-slt` by `' = '` split + blank-line records + dynamic header detection;
   flag `Encrypted=+`/`Method~AES`. **Effort S.**
2. **D0 sanitizer = canonicalize-compare-reject, 3 redundant layers** —
   PeaZip shipped a traversal CVE in 2026 even with checks; redundancy is
   the lesson. `Path.resolve()` + `is_relative_to(dest)` + explicit
   `..`/drive/UNC/ADS(`:`)/reserved-name rejection. **Effort S.**
3. **F1/F2 key derivation done right (their weaknesses as spec)** —
   `HKDF-Extract(salt=SHA-256(keyfile, capped stream-hash),
   ikm=Argon2id(pw, random_salt))`, keyfile-only mode, header bytes as GCM
   AAD, no in-header password verifier, constant-time compares.
   **Effort M.**
4. **Per-object + per-volume integrity in .excmp** — salvage and fast
   fault-localization on split archives. Per-file hash in the index (we
   already have SHA-256), per-volume tag in each part trailer. **Effort M.**
5. **Command palette + settings search from one action registry (I10)** —
   dict of `ActionSpec{id, title, callback, context}` + filter-proxy
   palette. **Effort M.**
6. **Curated Zstd/Brotli level ladders + flags** — zstd
   `[1,2,3,5,7,11,15,19,22]` default 3, `-T0`, `--ultra` only at 22,
   `--long=31` symmetric; brotli `[0,1,2,3,6,9,11]` default 3. **Effort S.**
7. **Conversion as a mode of Add.** **Effort M.**
8. **Preview/extract-and-open temp discipline** — per-job random hidden
   subdir, never-overwrite, size>0 success check, cleanup registry, refuse
   outputs into own temp. **Effort S.**
9. **Backend binary hash manifest + "verify binaries" UI.** **Effort S.**
10. **Password meter** — reimplement the scoring rules above (or zxcvbn);
    thresholds 24/48/72. **Effort S.**
11. **Session/layout save + browse history menu.** **Effort S-M.**

## Gotchas

- **License boundary:** LGPLv3 — concepts only, no line-by-line
  translation. The Ehrhardt crypto library is separately licensed but we
  need none of it (`cryptography` + `argon2-cffi` cover it).
- **Don't imitate:** 16-bit in-header password verifier (a 2^16 oracle —
  they zeroed it themselves in newer modes); SHA-1 salt reduction;
  ANSI-only filenames in .pea; passwords living unwiped in GUI memory;
  string-concatenated command lines; parsing localized 7z output (pin
  `-sccUTF-8`, parse only stable `-slt` key names).
- **Their two 2026 CVE-class fixes are our checklist:** path traversal
  despite existing checks (pea.pas:245) and PowerShell injection from
  archive-derived strings (pea.pas:246) — never feed member names to any
  shell.
- **7z quirks encoded in their workarounds** (will bite us too): deleting
  absolute-path members needs `*name` filters (peach.pas:51428);
  `.tar.zst` double extensions and multipart (`.001`, `.z01`, `.r00`) need
  explicit companion-file collection (`getmultiname`, peach.pas:58826);
  wrong-password on list/test surfaces as exit 2 + "Open ERROR", not a
  distinct code.
- **Scale limits are deliberate:** tiered 64/192 MB stdout caps and the
  0.5 M-row list cap exist because `-slt` on huge archives is slow and
  memory-hungry — G1/G2 should stream-parse with a row cap and a
  "flat/partial" fallback rather than assume unbounded parsing.
