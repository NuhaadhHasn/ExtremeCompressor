# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versioning
intent is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**0.1.0 was the first release (2026-11-25); 0.1.1 followed on 2026-11-26, 0.1.2 on 2026-11-27.** Until 1.0 the archive format may still change between versions: an
app always reads the archives it wrote, but an older app may not read a newer archive. Everything built before the
first release is listed under 0.1.0, in the order it was done.

Each entry names its roadmap item (`docs/ROADMAP.md`) and the date the work
was measured, so a line here can always be traced to the benchmark that backs
it.

## [Unreleased]

### Added

- **Drag files out of the Restore tab's list (2026-11-27).** Select rows and drag them into an Explorer folder: the app unpacks
  just those files to a staging folder, checks them against the archive's fingerprints (our own archives; a zip made by somebody
  else has only its own error check), and Explorer copies them. Copy only. It happens while the mouse button is held, so it is
  capped by bytes (128 MB) and by estimated time (8 s, priced by the archive's own stage chain); past that, or for folders, split
  archives, archives that are neither ours nor a zip, and ambiguous names, the line under the list says why and points to
  Restore selected. Files come from the archive the rows were read from, not whatever the Archive field says now. Staging folders
  are kept for a while (Explorer may still be copying), removed when the app closes, and stale ones swept at start-up, never
  through a junction. An independent review found 8 defects, all fixed; verified with a real mouse drag onto a second window:
  the dropped copy was byte-identical.
- **A search box on the Settings page.** Shows only the rows that mention what you type.
- **A clean-machine check of a released installer** (`.github/workflows/clean-machine.yml`, run by hand): on a throwaway Windows
  runner it removes the Visual C++ runtime from System32, shows a bare Precomp then fails to start, and shows the installed app
  still round-trips Insane byte-identical. Run on 0.1.2: it passed.

### Fixed

- The tick boxes in the Restore list were nearly invisible on the dark theme; they are styled like every other check box.
- **"Restore selected" from a zip could hand back the wrong file** when the zip held names that differ only by capital letters
  (`A.txt` and `a.txt`) or the same name twice: 7-Zip picks members case-insensitively, and the last one won. Such a pick is now
  refused with a plain message. (Found by the review of drag-out; the bug was in the existing selective restore.)
- The shared temp-folder cleanup (`rmtree_force`) no longer walks into a junction or symlink: it used to clear the read-only bit
  on files in whatever folder a junction inside the tree pointed at.
- The user guide said the Restore tab's button was "Extract N selected" (it is "Restore N selected") and showed a stray tab
  character in the temporary-folder path.

## [0.1.2] - 2026-11-27

### Added

- **The installer carries the external tools (2026-11-26).** 7-Zip (the "Extra" `7za.exe` 26.06, no RAR code), Precomp 0.4.7,
  zpaqfranz 64.8, FLAC 1.5.0 and balrogg 1.4 now ship inside the installer, each checked against its SHA-256 pin, with its
  licence text under `licenses\tools`. An installed app has what a source checkout has and never downloads a tool: before
  this the installed app had no zpaqfranz, so Insane could not run, and no Precomp, so Extreme could not either. A full
  7-Zip on the machine is still preferred when it is new enough, because it also opens RAR and ISO. Settings marks the
  copies that came with the app (so does the new `excmp tools` command). A RAR or ISO opened with only the bundled
  7-Zip now gets a plain "needs the full 7-Zip" message instead of "the file appears damaged". The frozen app hands its
  Visual C++ runtime folders to the tools it starts, because Precomp needs them and a machine without the redistributable
  would otherwise not start it from `excmp.exe`. `packaging/stage_tools.py` builds the folder; `THIRD-PARTY-NOTICES.md` was rewritten from
  the files (Precomp is Apache-2.0, not "non-commercial"; zpaqfranz is MIT).

### Fixed

- **The in-app update could fail (found on the first real 0.1.0 to 0.1.1 test).** The window started the silent installer
  and only then closed, so the installer's one-shot "is the app running?" check saw it and exited 1 with the old version
  left in place. The window now lets go of its running marker before it launches the installer, and the installer waits up
  to 20 seconds for a closing window instead of checking once. An interactive Setup or uninstall still refuses at once with
  a message.

## [0.1.1] - 2026-11-26

### Added

- **Extreme finds repeats further back than 7-Zip's dictionary (B31, 2026-11-25).** A dedup stage
  in front of 7-Zip (`excmp/stages/dedup.py`) keeps one copy of each repeated chunk of the stream
  Precomp produces. Two versions of one 155 MB design file: 222.1 MB -> 112.0 MB. The owner's design
  folder (666 MB): 370.5 MB -> 258.4 MB. Two versions of a folder of jars and zips: 104.5 MB ->
  54.2 MB. The stage is skipped, leaving no record, when the stream fits the dictionary (256 MiB
  by default) or holds under 2% of such repeats; then the archive is byte-identical to before, at a
  cost of about a second per 30 MB of stream for the scan. Every chunk is checked against its hash
  on restore, and the SHA-256 ledger gate is unchanged.
  **Compatibility:** archives without the stage are written and read exactly as before (manifest
  schema 2). An archive that records a `dedup` stage is written as schema 3 and needs this version
  or later: 0.1.0 refuses it at once as "written by a newer version".
  ([record](docs/benchmarks/2026-11-25-dedup-stage.md))

## [0.1.0] - 2026-11-25

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

- **An update checker (E5, 2026-11-25).** Looks at this project's latest GitHub release (a Settings row, a daily check you can
  turn off, a banner) and installs a newer version only if its checksum file carries the owner's Ed25519 signature. The release
  procedure and the signing tool are in `packaging/RELEASING.md` and `tools/release_sign.py`.
- **The installer ships the licence texts (2026-11-25):** LICENSE, THIRD-PARTY-NOTICES.md and the LGPL-3.0 and GPL-3.0 texts.
- **An application icon (E6, 2026-11-25).** a 512 px master (`assets/app-icon-512.png`: a file squeezed from both sides, with a lightning
  bolt) and the `assets/app.ico` built from it (`packaging/make_icon.py`), on the window, both programs, the installer and the Explorer menu.
- **The Fast profile is faster (2026-11-25).** It ran zstd level 19, the slowest useful setting, so it was no faster than Normal. It now runs level 12:
  measured end to end (compress plus the restore check) 1.5-1.8x faster on Office files, installers and source code, for 0.2-2.8 points of
  saving. The codec alone is 15-60x faster at level 12 than 19, but most of a job's time is per-file work, which is the next thing to fix.
- **A JPEG inside a container is priced 1.45x slower than a JPEG file (B30, 2026-11-24).** A second album ran 1.77x
  and six JPEG EPUBs 1.53x over the old rate; one factor fitted on the three pure-JPEG corpora. Plain `.jpg` files are
  unchanged. Three more corpora were measured and changed nothing (nested archives 1.10x, a second `.pptx`, a second PNG-heavy
  container 0.67x).
- **A PNG-dominant `.docx` is priced by its counts at Insane (B29, 2026-11-23).** A second `.docx` corpus
  (55 files, 43.8 MB, 73% PNG) ran 1,794 s against a chain-rate estimate of 892 s; the first had been 2.84x
  too short. The container model was 0.97x and 0.78x of the two. Lifted when PNG is at least half the file and
  only at Insane; `.xlsx .pptx .zip .jar .apk` and a docx with little PNG keep the chain rate.
- **Archives inside archives are priced (B28, 2026-11-21).** A `.war` of `.jar` files ran past its
  high at Insane (300 s measured against 100 s expected): Precomp expands the inner streams too.
  The central-directory probe counts nested members apart and the estimator charges each 3.0
  plain deflated bytes (fitted on a `.war` and a synthetic nested zip, both inside their ranges).
  A crafted directory claiming more compressed bytes than the file has is clamped. `.zip`, `.jar`
  and `.apk` keep the chain's rate: B27 measured them and found no better model
  ([record](docs/benchmarks/2026-11-21-b27-b5-types.md)).
- **The frozen build carries PAR2 (E3 review, 2026-11-21).** `excmp.exe compress --recovery` and
  `repair` failed in the first frozen build; the spec now bundles `par2.exe` and the lookup finds
  it. The installer is per-user only, and **an uninstall with the window open no longer
  half-removes the program** (it used to return 0, delete the uninstall entry and leave every file):
  the window holds a mutex the installer watches, so the uninstaller refuses. The unused Qt DLLs
  are dropped: 110 MB to 92 MB, installer 27.7 MB.

- **A pinned tool replaced by an unverified one was silent (B27, 2026-11-20).** B25 made
  discovery prefer the hash-pinned Precomp and fall back to the Program Files install for
  a checkout that has not fetched it; nothing said so. `find_tools` now logs one warning
  per tool and process, naming the unverified path it is using and how to fetch the pinned
  copy (a pinned copy that is found, a pinned tool that is absent, and an unpinned tool
  are not warnings).
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
