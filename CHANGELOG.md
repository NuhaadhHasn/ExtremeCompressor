# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versioning
intent is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Nothing has been released yet.** `excmp.__version__` is `0.1.0` and there is
no git tag, so everything below sits under *Unreleased* — inventing version
numbers for work that never shipped as a version would be inventing history.
The first tag should be cut when the archive format is one the project is
willing to keep reading, because that is the compatibility promise that
matters for an archiver.

Each entry names its roadmap item (`docs/ROADMAP.md`) and the date the work
was measured, so a line here can always be traced to the benchmark that backs
it.

## [Unreleased]

### Added

- **A frozen build and a per-user installer (E3, 2026-11-21).** `packaging/` holds a
  PyInstaller `--onedir` spec (the window and a console `excmp.exe`), an Inno Setup script
  (no administrator, an optional Explorer-menu task, a clean uninstall), `build.cmd` and
  `smoke_test.py`. First build: 110 MB folder, 33.8 MB installer. A real silent install
  registers the window (not the console tool) for the menu, and the uninstaller leaves no
  file and no registry key. **Unsigned**: Windows SmartScreen will warn until E4.

- **Explorer right-click menu, Windows 10 path (I5, 2026-11-20).** `excmp shell
  install | uninstall | status` writes per-user registry verbs (no administrator):
  *Compress with ExtremeCompressor* on files and folders, *Extract here* and *Verify
  archive* on `.excmp`, which also opens with the app. Each verb is a thin launcher
  (`<program> <action> "%1"`); nothing is loaded into Explorer. Explorer starts one
  process per selected file (measured: 3 files, 3 processes, in both multi-select
  models), so a named mutex makes the first process the window and the others forward
  their paths over a per-user pipe whose messages are validated strictly. Uninstall
  removes only what install wrote, and a foreign `.excmp` association of any registry
  type is never taken over. **Extract here** never overwrites: a name collision means a
  fresh `name (2)` folder. Two reviews found and fixed, among others, that the obvious
  "whoever can listen is the window" design is wrong on Windows (a second process can
  listen on a name already in use) and that a verb skipped the checks the buttons make
  (`tests/test_i5_shell_menu.py`, `tests/test_i5_gui_intake.py`).
- **A failed restore no longer leaves the folder it created.** `engine.extract` takes
  an empty destination it made back out on failure (a password-protected or unreadable
  archive used to leave an empty `junk/` beside it).
- **Verified byte-identical restore as the acceptance gate.** `compress()`
  fully restores the archive in a temp directory and hash-compares every file
  against the ledger *before* the archive is published; a chain that cannot
  round-trip produces no file at all, not a warning (D9, 2026-08-02).
- **Per-file routing with reasons.** Every file is analyzed and sent to the
  pipeline that suits its data, and the reason is reported rather than implied
  (engine core; J1).
- **Four profiles** — Fast (`zstd`), Normal (`7-Zip`), Extreme
  (`precomp → 7-Zip`), Insane (`precomp → zpaqfranz`) (B1, B11).
- **Duplicate-file dedup in the store route.** On a 49%-duplicate corpus this
  moved Extreme from 5.22% to 51.08% saved — the win was never in the
  compressor (G9, 2026-09-02).
- **JPEG recompression** via the `lepton-jpeg-python` wheel, in-process and
  bit-exact (B2, 2026-09-02).
- **WAV packed with FLAC** — 43.15% on real files, 4/4 byte-identical, where
  WAV had previously been stored at 0% and mislabelled "already compressed by
  its codec" (B4, 2026-09-07).
- **BCJ2 branch filtering** for executables, measured rather than assumed
  (B7, 2026-09-02).
- **AES-256-GCM encryption** of the whole finished container — Argon2id
  (m=64 MiB, t=3, p=4), 4 MiB chunks with age-style STREAM nonces, the header
  as AAD for every chunk (F1, 2026-09-03).
- **Keyfiles as a real second factor**, folded into the key with HKDF
  (F2, 2026-09-03).
- **PAR2 recovery records** that actually repair (F3, 2026-09-03).
- **Mark-of-the-Web propagation** on restore, so a file downloaded from the
  internet keeps saying so (F4, 2026-09-03).
- **Foreign-archive listing and extraction** — zip/7z/rar/tar/iso/cab/msi and
  the rest, through the 7-Zip already being shelled out to (G2, 2026-09-01).
- **Split volumes** with a per-part `sha256sum`-layout sidecar, so a failed
  transfer says *which* part to fetch again (G3, 2026-09-02).
- **Plain `.7z` / `.zip` export** for anybody who wants no container at all —
  still extracted and hash-compared before it is published (G4, 2026-09-02).
- **Convert-and-shrink**: repack any archive 7-Zip can open (G5, 2026-09-03).
- **`excmp verify`**, **`excmp list`**, **`excmp hash`**, and a `.sha256`
  transport sidecar (G6, G8).
- **Self-calibrating time and size estimates.** Every finished job feeds its
  measured throughput back into the model, keyed on the resolved chain rather
  than the profile (J1, J2, J7, 2026-09-03).
- **Free-disk preflight** for compression, including the temp space the
  verification restore needs (J4).
- **Persisted job history**, queue reordering, a treemap of where the bytes
  went, and a Ctrl+K command palette (I3, I8, I10, 2026-09-03).
- **Hash-pinned tool downloads.** Every fetched binary is verified against a
  SHA-256 pinned in source, over HTTPS with a redirect policy — and its own
  first fetch found that policy refusing GitHub (E1, 2026-09-07).
- **Timestamps and empty directories are preserved** through a round-trip
  (K2, 2026-09-07).
- **`excmp/atomic.py`**: every output is flushed to the device, read back off
  the filesystem, and only then renamed into place. The read-back's digest is
  reported as `CompressResult.sha256` (D8, 2026-09-09).
- **CI on `windows-latest`** — the suite on every push, a Python 3.12/3.13
  matrix plus an informational 3.11 leg on a schedule, and a separate job that
  fetches the pinned tools so the real chains are exercised. The gate job
  *requires* 7-Zip rather than hoping the runner image has it, because
  every chain test skips without it and the suite would otherwise be green
  having tested none of the product (D7, 2026-09-09). **Not yet proven** — a
  workflow that has never run is not evidence.
- **`excmp verify --deep`** — reports one order-independent SHA-256 for the
  whole restored tree, so "is this the same archive?" is a single value you
  can write down and check next year. It also refuses an archive that returns
  files its ledger does not account for, which the per-file check could not
  see (D5, 2026-09-09).
- **`excmp verify --source DIR`** — re-reads the **originals** and compares
  them against the archive. This is the one check here that can find bit-rot
  in your own files: the archive is the only reference copy of what they used
  to be. Measured on real data — one flipped bit in a 120,313-byte file
  caught as "same size, different content", with a deletion and a new file
  reported separately and neither treated as corruption (D5, 2026-09-09).
- **`--keyfile` on `compress`, `extract`, `list`, `convert` and `verify`**, and
  `--password` on `verify`, which had none. Before this, a keyfile-protected
  archive could be *created* through the API and opened by nothing — see
  Fixed (F2/F5, 2026-09-09).
- **A fuzz harness for the container parser** — `tools/fuzz_container.py`,
  35,000 examples across 7 properties in 136 s (D6, 2026-09-09).
- **CONTRIBUTING.md, CHANGELOG.md and issue templates** (E6, 2026-09-09).

### Changed

- **SREP removed from the Extreme and Insane chains** (B11, 2026-08-02). It
  failed its own decompression checksum on 1 of 3 runs over byte-identical
  input. Old archives that used it still extract, pinned by a test that builds
  a genuine pre-B11 archive and restores it.
- **The zstd window is fitted to the input rather than pinned at 31**, for
  identical output and 769 MiB less peak memory. The *read* ceiling is a
  separate constant and stays independent of the write setting — that coupling
  was the actual bug (K4, 2026-09-07).
- **The size estimator's range was recentred.** It had been excluding the truth
  on 3 of 4 profiles, by 14–19 points, because a constant fitted on one corpus
  had been mistaken for a property of the codec. Now 4/4 in range, erring
  conservative by 2.6–3.5 points (B8, 2026-09-08).
- **Extreme vs Normal on PDFs and Office files** — the estimator had shown a
  4-point gap where the truth was 40 (B5, 2026-09-07).
- **The sidecar no longer re-reads the archive.** The publish read-back
  already measured that digest (D8, 2026-09-09).
- **Splitting no longer reads the archive twice.** `split_file` records each
  part's SHA-256 from the bytes it writes, making the volumes sidecar 13.9×
  cheaper (D8, 2026-09-09).
- **The consequence of losing a password is now where people actually are.**
  It used to live in a tooltip that needed a mouse, and the visible note was
  *replaced* by "the two entries do not match yet" for the whole time somebody
  was typing the confirmation — the exact moment they were deciding. It now
  stands from the first keystroke, is announced to assistive technology, and
  the CLI prints it before prompting (on stderr, so `--json` stays parseable)
  (F5, 2026-09-09).
- **The Settings tab no longer says "zstd — not installed"** for the codec
  that runs the whole Fast profile in-process. It reads "built in, no
  executable needed" instead (B10, 2026-09-09).
- **`THIRD-PARTY-NOTICES.md` rewritten from the files on disk.** 40 licences,
  each with the path it was read from; 39 confirmed and one — zpaqfranz —
  explicitly *not*, because there is no licence file beside that binary. The
  previous version had drifted since 2026-07-18 and stated three licences less
  precisely than the files do (E2, 2026-09-09).

### Fixed

- **A 57,020-file folder could not be archived at all.** The manifest went to
  schema v2 with a 64 MiB cap measured against its own serialised size; the
  same tree now archives, 55,477 files, 71.39% saved, byte-identical
  (K1, 2026-09-04).
- **Stored files came back dated today, and empty folders vanished**
  (K2, 2026-09-07).
- **One locked file destroyed the whole job.** Unreadable files are now
  skipped at analysis, guarded again at hash and copy, and reported by name —
  a file the user believes is backed up and is not is the worst outcome this
  program can produce (K3, 2026-09-07).
- **zstd could not see past 128 MiB, and could not read wider than it writes**
  (K4, 2026-09-07).
- **Every job touching a `.git` directory leaked a temp directory**
  (K5, 2026-09-07).
- **The destination was deleted before the rename.** A failure at the publish
  — the one moment a whole job's work is on the line — left the user with
  neither yesterday's archive nor today's (D8, 2026-09-09).
- **`compress a.txt b.txt c.txt --format 7z` archived only the first file** and
  reported the original size of all three, i.e. a 99% saving (G4).
- **The `.sha256` sidecars were written with CRLF**, so `sha256sum -c` read the
  trailing CR as part of the filename and every line failed — in a file whose
  entire purpose is that one command (2026-09-02).
- **The volumes sidecar overwrote the whole-archive sidecar**, so a user who
  asked for a checksum of the archive silently got a checksum of its parts
  (2026-09-03).
- **Split archives silently lost the ledger guarantee.** `big.excmp.001` is not
  a zip, so it fell through to the foreign-archive branch, which joined the set
  generically, wrote `manifest.json` into the destination and reported success
  with `verified=0` (2026-09-03).
- **A keyfile-protected archive could be created and opened by nothing.**
  `engine.compress` accepted `keyfile=`; no read path passed one, and
  `engine.extract` would not even take the argument. So the engine wrote
  archives it could not read, `excmp verify` could not check them, and the
  error message told users to "supply the same file as well as the password"
  through a CLI in which the word *keyfile* appeared zero times. Every read
  entry point now takes it — and there were **two** decryption sites, not
  one, which is how a factor came to be half-plumbed (F2, 2026-09-09).
- **A wrong keyfile reported "wrong password".** The password was correct. That
  message sends someone hunting for a password they already have, and the
  conclusion after "mine is right and it still says wrong" is "the archive is
  broken" — which is how archives get deleted (F5, 2026-09-09).
- **`excmp verify` had no `--password`**, so no encrypted archive could be
  verified from the command line at all (2026-09-09).
- **`--password` then hung forever under any automation** (2026-09-10). On
  Windows `getpass.getpass` reads the console with `msvcrt.getwch()` rather
  than stdin, so `echo pw | excmp verify --password ...` blocked indefinitely.
  The flag was usable only by a human at a terminal, which defeated the point
  of adding it: a scheduled integrity sweep, a CI job and a batch script are
  exactly the callers that want to prove an encrypted archive still restores.
  A password is now read from stdin when stdin is not a terminal. `--password`
  still takes no argument - a piped password is in neither the process table
  nor shell history, which is what argv would have broken.
- **Eleven unhandled exception shapes in the container parser**, found by
  fuzzing it for the first time. A crafted ledger raised `AttributeError`,
  `TypeError` or `ValueError` out of the parse layer instead of the
  `ContainerError` every caller catches — and `{"size": 10**400}` sailed
  through to *become* the decompression-bomb budget. The ledger is now
  validated once, at the parse boundary (D6, 2026-09-09).
- **`parse_size("1e400m")` raised `OverflowError`** rather than a clean
  refusal, along with three other size strings (D6, 2026-09-09).

### Security

- **Zip-slip in `extract_stored()`** — a hostile archive could write outside
  the destination (D0.1, 2026-07-31).
- **Ledger-bounded extraction**, so a decompression bomb cannot expand past
  what the ledger declares (D0.3).
- **`filter="data"` pinned on tar extraction**, with a regression test
  (D0.4).
- **A hand-crafted malicious-archive suite** — absolute paths, `..`
  traversal, reserved device names, symlink members (D0.2).
- **`SECURITY.md` and a threat model**, because parser bugs are the realistic
  attack surface for an archiver (D0.5).
- **Argon2 parameters from an untrusted header are bounded.** They are needed
  to derive the key that would authenticate the header, so "the header is AAD"
  does not protect this step; one flipped bit in `m_kib` asked Argon2 for
  16 GiB and hung for 19 minutes (F1).
- **A ledger is validated before any bound is derived from it.** The payload
  budget and the decompression-bomb budget are both computed from
  archive-supplied numbers, and a ledger those cannot be read from is now
  refused rather than producing a budget that does not bound (D6,
  2026-09-09).
- **`7z -p` was deliberately not used.** Its salt lines are commented out, so
  identical passwords produce identical keys, and it would have left
  `manifest.json` and the whole stored tree in plaintext (F1).

### Known limitations

- **`verify_restore` does not compare timestamps**, on purpose: every archive
  written before K2 lacks them, and failing those archives' verification would
  be worse than a wrong date.
- **An `.excmp` is not byte-reproducible.** `manifest.json` carries
  `created_utc`, which moves the deflated member by up to 3 bytes, and 7-Zip's
  payload is length-deterministic but not byte-deterministic. Compare payload
  size across runs, never the archive digest (D8, 2026-09-09).
- **zpaqfranz's licence is not established on this machine.** There is no
  licence file beside `tools/bin/zpaqfranz.exe`. It is used (Insane profile)
  and nothing is redistributed, so nothing is broken — but it has to be
  settled from upstream before this project is ever shared. Recorded rather
  than guessed.
- **Precomp bundles five third-party components whose licence texts are not
  present here** (packJPG, packMP3, bZip2, zLib, GifLib). Precomp's own
  Apache-2.0 does not cover them, so redistributing that binary needs its own
  review first.
- **`research/23` §2.4's 300px page budget is unreachable** and is a
  deliberate strict-xfail: §2.4 and §3.3 contradict each other and §3.3's 32px
  touch floor wins.
