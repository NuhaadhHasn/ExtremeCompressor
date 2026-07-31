# 🗺️ ExtremeCompressor — Remaining Work, Step by Step

> Status date: **2026-08-01**. Engine core DONE, Phase A (GUI) DONE,
> **Phase D0 (security hotfix) DONE and merged**, and **Phase J part 1 (J1-J4, J8)
> done** — the app now shows estimated size and time for all four profiles before
> anything is compressed, scored against two real corpora. **289 tests**.
> **Next up: J5-J7 (remember last choice, long-job confirm, self-calibration),
> then B11 + D9 — two integrity findings from the J8 run that outrank new
> features: SREP failed a restore intermittently, and `compress()` can publish an
> archive it cannot restore. Then G1-G2, then D1-D3 + D7.**
>
> This is the complete, ordered plan for everything left. Companion deep-dives:
> [06 best-compression-per-filetype](research/06-best-compression-per-filetype.md) ·
> [07 UI v1 blueprint](research/07-ui-ux-design.md) ·
> [08 archiver product features](research/08-archiver-product-features.md) ·
> [09 FitGirl installer + honest comparison](research/09-fitgirl-installer-and-comparison.md) ·
> [10 security & integrity](research/10-security-and-integrity.md) ·
> [11 UI v2 plan](research/11-ui-v2-plan.md) ·
> [12 lightweight & performance](research/12-lightweight-and-performance.md)
>
> **Source-code study series (2026-07-31, read [21 synthesis](research/21-source-study-synthesis.md) first):**
> [13 xtool](research/13-source-study-xtool.md) ·
> [14 NanaZip](research/14-source-study-nanazip.md) ·
> [15 Precomp](research/15-source-study-precomp.md) ·
> [16 Inno Setup](research/16-source-study-innosetup.md) ·
> [17 PeaZip](research/17-source-study-peazip.md) ·
> [18 FreeArc + par2](research/18-source-study-freearc-par2.md) ·
> [19 7-Zip](research/19-source-study-7zip.md) ·
> [20 lrzip + zpaqfranz](research/20-source-study-lrzip-zpaqfranz.md) ·
> **[22 feature-parity master](research/22-feature-parity-master.md)** (the
> all-in-one map: every studied feature → our own implementation → phase)

---

## Phase D0 — Security hotfix ✅ DONE (2026-07-31, D0.1-D0.5)

Research on 2026-07-31 audited our own code and found an **exploitable
path-traversal bug**. An archiver that can write outside its output folder has no
business gaining features. Full analysis: [research/10](research/10-security-and-integrity.md).

**Shipped:** `excmp/safepath.py` (reject-never-mangle validator, the union of the
7-Zip/NanaZip/PeaZip rule sets plus bidi overrides), wired into `extract_stored()`,
`read_container()`, `verify_restore()` **and** `write_container()` — so we also
cannot create an archive we would refuse to read. Extraction is bounded by the
manifest's own ledger (exact per-entry size on the real stream, 8 MiB
`manifest.json` cap, free-disk preflight, per-stage backstop). `SECURITY.md` added.
**223 tests pass** (was 91): `tests/test_safepath.py`,
`tests/test_malicious_archive.py`, `tests/test_tar_safety.py`.

**Real-data acceptance run** (not just fixtures) —
[benchmarks/2026-08-01](benchmarks/2026-08-01-real-programs-folder.md): 721 MB of
real installers and archives, both profiles, **6/6 byte-identical** under an
independent SHA-256 check. Confirms the two things unit tests cannot: legitimate
awkward filenames (spaces, parens, `=`) are *not* rejected, and the exact-size
stream cap handles 250 MB single entries. Also yields throughput calibration
(~11.6 MB/s normal, ~4.3 MB/s extreme compress on the 2-core target).

Two things the implementation corrected against the plan below, both verified live:

1. **The absolute-path escape needs no `..` at all.** `Path("out") / "C:/evil"`
   returns `C:\evil` — Python's `/` discards the left operand when the right side is
   absolute. The traversal case got the attention, but this was the quieter half.
2. **tarfile's `data` filter *strips* a leading `/`** rather than raising, and only
   raises `AbsolutePathError` if the name is still absolute afterwards (on Windows,
   a drive letter). So the D0.4 test pins *containment* for `/x` and a raise for
   `C:/x`; expecting a raise for both would have encoded a misreading.

Reject-not-mangle turned out to be forced by our own contract, not merely
preferable: ledger keys are the authoritative filenames, so a rewritten name could
never satisfy `verify_restore()` — mangling would convert a clear "hostile archive"
into a puzzling hash mismatch.

- [x] D0.1. **Fix zip-slip in `extract_stored()`** (`excmp/manifest.py` ~107-122):
      it builds `out_dir / rel` from the raw zip entry name and writes with no
      sanitization, so a crafted `.excmp` with `stored/..\..\Startup\evil.bat`
      (or a drive path, or an NTFS ADS name `x.txt:payload`) escapes the
      destination. The manual `zf.open()` + write loop bypasses
      `ZipFile.extract()`'s sanitizer. Write ONE shared sanitizer, also applied to
      `read_container()`'s `manifest.payload_name` and `verify_restore()`'s ledger
      keys: reject absolute paths, drive letters, `..`, `:`, reserved device names
      (CON/NUL/COM1), trailing dots/spaces — then belt-and-braces
      `target.resolve().is_relative_to(out_dir.resolve())` before any write
- [x] D0.2. **Malicious-archive test suite**: hand-craft hostile `.excmp` files
      and assert refusal. The **full test matrix is now source-pinned** by the
      union of three archivers' sanitizers ([14 §6](research/14-source-study-nanazip.md),
      [17 §5](research/17-source-study-peazip.md), [19 §7](research/19-source-study-7zip.md)):
      `..` / `..\`, absolute, drive letter (`C:\`, `C:rel`), UNC (`\\srv\share`),
      `\\?\C:\`, ADS `x:stream` and `x:Zone.Identifier:$DATA`, reserved device
      names **including `NUL.txt` / `COM1 .log`**, trailing dot/space, control
      chars, empty parts (`a//b`), symlink→abs, symlink→`../..`, symlink chains,
      hardlink outside root, 32 KB+ Zone buffer — **plus RLO `U+202E`, which
      7-Zip itself does NOT sanitize in normal path components**, so D0 can
      honestly claim to exceed 7-Zip. Reject (don't mangle) on link escapes,
      mirroring 7-Zip's `IsSafePath`
- [x] D0.3. **Ledger-bounded extraction** (decompression-bomb defense): our
      manifest already declares every file's exact size and count — bound
      extraction to `sum(ledger sizes) + slack` and `len(ledger)` files, enforced
      on the real streams (headers can be forged); cap `manifest.json` at ~8 MiB
      before `json.loads`; free-disk preflight; per-stage bounds (Precomp
      legitimately inflates 2-5×, so bound each stage, not just the end)
- [x] D0.4. **Pin `filter="data"` with a regression test**: `tarstage.py` already
      passes it (PEP 706 — good), so add a hostile-tar test that fails if anyone
      ever removes the argument
- [x] D0.5. `SECURITY.md` + short threat model (pulled forward from E6): malicious
      archive, tampered tools, tampered archive, lost password. An archiver parses
      untrusted input — researchers need a disclosure channel before v1
- [ ] D0.6. **DEFERRED to its own session** (doc 21 §4 suggests it become a
      standalone D-item; it is Windows ctypes work on subprocess spawning, not
      part of the archive-parsing fix). **(new, from [14 §3](research/14-source-study-nanazip.md))** Process
      mitigations, S-effort: apply `PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY`
      (prohibit dynamic code + block non-system DLLs) and
      `CHILD_PROCESS_POLICY` + a kill-on-close Job object to every tool
      subprocess (7z.exe/precomp/xtool need neither children nor JIT); apply
      only the **safe subset** to our own Python process (image-load policy,
      strict handles, `SetDefaultDllDirectories`) — NOT ProhibitDynamicCode,
      which breaks ctypes/PySide6. NanaZip proves the split (`FM.cpp` vs
      `MainAr.cpp`)

---

## Phase A — Desktop GUI (PySide6) ✅ DONE (2026-07-30)

The single-window flow (full blueprint in research/07):
**drop files → smart suggestion → preset cards → visible queue → results screen**.
Run it with `python -m gui`. Screenshots in `docs/images/`, regenerated by
`tools/shots.py`.

- [x] A1. `pip install PySide6`; app skeleton (`gui/` package, `python -m gui`), dark QSS
      token theme (hand-rolled — PySide6-Fluent-Widgets is GPLv3, conflicts with our MIT)
- [x] A2. Drop zone + file picker; dragEnter highlight; multi-file/folder drop adds
      everything (HandBrake's most-complained bug — we fix it day one)
- [x] A3. Analysis summary card: run engine analyzer in a worker thread, show per-type
      breakdown + smart suggestion
- [x] A4. Preset cards (Fast / Normal / Extreme / Insane) + "Advanced" expander
      (threads, temp dir, output path); Media-Shrink toggle greyed until Phase C
- [x] A5. `QueueManager(QObject)`: one job at a time, jobs run engine calls in
      `QThreadPool`; signals `jobProgress(id, stage, pct, eta)`, `jobDone(id, result)`;
      pause = finish-current-stage-then-hold; cancel wired to `StageContext.cancel`
- [x] A6. Queue table always visible in main window (name, profile, size→size, %,
      ETA, state) with per-job log expander
- [x] A7. Results screen: headline "You saved X MB (Y%)", per-type before/after bars,
      one-line "why didn't X shrink" explainers straight from `store_reason()`
- [x] A8. Windows integration: taskbar progress (ITaskbarList3 via `comtypes`),
      completion toast (`Windows-Toasts`) with "Open folder", system tray option —
      all optional, no-op if unavailable
- [x] A9. Extract tab: pick `.excmp` → destination → verified restore with progress
- [x] A10. Day-one hygiene: every string in `self.tr()`, `setAccessibleName` on
      icon-only buttons, full keyboard tab order, no color-only meaning
- [x] A11. GUI smoke tests (pytest-qt): queue lifecycle, cancel, pause, progress
      signal flow, drop handling — 52 new tests, 90 total
- [x] A12. Screenshot set for README: dark-theme hero of the RESULTS screen, plus a
      7.7 s / 1.6 MB GIF of drop→suggest→compress→result. Scripted in `tools/shots.py`
      so both regenerate every release

**Three additive engine changes landed with it** (all backwards-compatible):
`StageContext.pause` checked at stage boundaries, `StageContext.log_cb` for
per-job tool output, and a `.tmp` cleanup so a cancelled job leaves nothing
beside the user's output. `planner._store_reason` became public `store_reason`.

**Left open:** an NVDA screen-reader pass, and verification at 125%/150%
display scaling — both need a human at the machine.

## Phase B — Stronger + specialist compression

> **Cross-cutting wrapper rules from the source study** (apply to every stage
> that shells a tool — [21 §1.2](research/21-source-study-synthesis.md)):
> (1) pass **`-bsp1`** to 7z.exe or it prints **zero** progress when piped, and
> split its progress on `\r` for `(\d+)%`; (2) **xtool** (`WriteConsole`) and
> **Precomp** emit no parseable progress when piped — poll output-file size
> instead; (3) **never trust a tool's exit code as proof of a good restore** —
> Precomp `exit(0)`s even on fatal restore failure, and xtool/Precomp don't
> round-trip-verify every path. **Our own post-restore SHA-256 comparison is
> the acceptance gate for every stage** (fold into the stage base class).

- [ ] B1. **zpaqfranz stage** (actively maintained, FOSS, MIT): `a -m4 -longpath`
      default for Insane (`-m5` behind an "overnight" warning — note both use
      64 MiB blocks, `-m5` is ~2-3× the CPU for CM depth, so **`-m4` is the
      realistic Insane ceiling on 2 cores**, `-m5` a small-precious-data niche);
      add `-test` for a one-shot post-add decompress-check. Keep archives
      **vanilla-zpaq-7.15-readable** (plain `a` only; no `backup` multipart /
      ZETA / W-chunk). This stage is ALSO our long-range-dedup answer: its CDC
      dedup matches identical fragments at unlimited distance (<500 MB RAM for
      200 GB of data) — which is why **lrzip is rejected** (GPL + hard-POSIX,
      no Windows path) and `zstd --long=31` / 7z big-dict stay the ≤2 GB
      default. [20](research/20-source-study-lrzip-zpaqfranz.md); completes
      Insane; add to bench
- [ ] B2. **JPEG specialist**: `lepton_jpeg_rust` (Microsoft, Apache-2.0) — ~22%
      lossless, bit-exact restore; route `Category.IMAGE/jpeg` through it
- [ ] B3. **PNG specialist**: `oxipng -o max` default, ECT `-9` under Extreme
- [ ] B4. **WAV specialist**: FLAC 1.5 `-8 -j N`; TAK/OptimFROG as detected-only
      opt-ins (closed freeware — never bundled)
- [ ] B5. **PDF/Office**: qpdf `--object-streams=generate --recompress-flate`;
      docx/xlsx members unpacked into the solid stage (they're just ZIPs)
- [ ] B6. **xtool stage** (game paks: zlib/lz4/zstd/**Oodle** via the game's own
      oo2core DLL): detected-only, MIT but archived upstream — always verified
      roundtrip; extend router with pak/Oodle magic detection. **Source study
      ([13](research/13-source-study-xtool.md)) adds hard requirements:**
      (a) **restore = recompress**, so the oo2core DLL is part of the archive
      contract — pin `{oodle_dll_name, sha256, source_relpath}` in the manifest,
      re-resolve from the game folder at restore, refuse clearly on mismatch
      (Oodle has **no** patch fallback); (b) exact CLIs —
      `precomp -mkraken+mermaid+selkie+leviathan+hydra -c64mb -t2 -d0
      "-oodle<GAMEDIR>\oo2core_9_win64.dll" -bd<TOOLS> <in> <out.xtp>` and
      `decode -t2 "-oodle…" -bd<TOOLS> <out.xtp> <restoredir>`; (c) pass **`-t2`**
      explicitly (default `50p` = 1 thread on 2 cores); (d) run with **cwd = a
      scratch dir** (temp files land in CWD) and **blacklist `-s`** (skips
      verification); (e) container bytes are non-deterministic — hash the
      *restored* payload, never the `.xtp`; (f) fast lane = ship curated `.xtl`
      game-fingerprint DBs in the plugins dir (recognize file by CRC ladder →
      known stream layout, zero scanning). Never ship srep (not OSI; plain
      `-dd` dedup is fine without it)
- [ ] B7. Executables: force 7z BCJ2 explicitly with **`-mf=BCJ2`** (the cheapest
      correct trigger — [19 §4](research/19-source-study-7zip.md): 7z only
      auto-selects BCJ2 at mx≥8 *and* only with the MT mixer, else it falls back
      to plain BCJ; ARM64/RISCV get their own filters, never BCJ2). **Flag the
      "5-10% on x86" figure as benchmark-derived** — there is no source-level
      percentage. **Never UPX** (AV flags, hurts archive ratio)
- [ ] B8. Re-benchmark everything on Silesia + a real game folder; update README table
      — this is also what replaces every *(est.)* in the doc 09 comparison table
- [ ] B9. **RAM caps + thread defaults** (verified formulas, [research/12](research/12-lightweight-and-performance.md);
      **corrected by [19 §3](research/19-source-study-7zip.md)**):
      change default `threads` from 4 to **2** — but the reason is that at mx9 each
      LZMA2 **block** (not "chunk") uses 2 threads (match-finder + coder), so
      total = 2 × block-threads; more just splits the stream and costs RAM.
      ⚠️ **mx9 default dict is 256 MiB on 64-bit since 7-Zip 24.09**, not 64 MB —
      any "mx9 = 64 MB" note in doc 12 is two generations stale, and on 4 GB
      machines mx9 MT LZMA2 can exceed RAM (≈13× dict per block thread). Use the
      **exact estimator formula** `CompressDialog.cpp:2942-3016`
      (`size1 = hs*4 + dict*4 + dict*4 + buffers`, decode = dict + 2 MiB), not a
      flat multiplier. `7z -md=192m` (~2.0 GB compress, 192 MB to extract), never
      past 512m; always pass **`-mqs`** for exe/media trees (solid type-sort is
      OFF by default — [19 §5](research/19-source-study-7zip.md)); keep zstd
      `window_log=27` — `--long=31` costs the *decompressor* too. (srep line
      dropped: not OSI; long-range dedup now comes from B1 zpaqfranz.)
- [ ] B10. **JPEG correction to B2**: use the `lepton-jpeg-python` **wheel** (0.5.8,
      win_amd64, Apache-2.0, in-process, bit-exact) — Microsoft ships no exe, so the
      wheel is the only zero-build Windows path. And **drop zstd.exe** from any tool
      manifest: the `zstandard` wheel already embeds libzstd in-process
- [ ] B11. 🔴 **Remove SREP from the Extreme/Insane chains** — the source study
      already decided this ([20 §4](research/20-source-study-lrzip-zpaqfranz.md),
      [21 §5](research/21-source-study-synthesis.md): not OSI-clean, so it can never
      ship, and B1's zpaqfranz CDC dedup replaces it) but `planner._CHAINS` still
      lists it, so every Extreme run on this machine uses it.
      **Now urgent rather than tidy:** on 2026-08-01 `srep64.exe` failed a restore
      with "checksum of decompressed data is not the same as checksum of original
      data" on **1 of 3 runs over byte-identical input** — intermittent, which is
      worse than deterministic. Details in
      [benchmarks/2026-08-01-estimator-backtest.md](benchmarks/2026-08-01-estimator-backtest.md).
      Dropping the stage removes the fault and the licence problem together; the
      chain becomes `precomp -> sevenzip`, whose estimator constants are already in
      `excmp/estimate.py`. Do B1 first if the dedup is wanted back.

## Phase C — Media Shrink mode (opt-in, quality-targeted)

- [ ] C1. Tool downloader first (see D6) → fetch FFmpeg GPL build (gyan.dev, ~90 MB,
      SHA-pinned) **after asking the user in-app**
- [ ] C2. `ffprobe` stage: codec/bitrate/resolution probe; skip rules (already
      AV1/HEVC at low bits-per-pixel → "nothing to gain")
- [ ] C3. AV1 encode stage: SVT-AV1 preset 8-10 on this class of CPU, CRF slider
      mapped to three cards: *Visually lossless (CRF 24) / Balanced (28) / Small (32)*;
      audio → Opus 128k; subtitles/chapters preserved (mkv out)
- [ ] C4. Honest UX: ETA warning before starting ("~9 hours on this machine — run
      overnight?"), output tagged so we never re-encode our own output
- [ ] C5. Later: ab-av1-style CRF search targeting VMAF 95 (needs beefier machine)

## Phase D — QA hardening (data integrity IS the product)

- [ ] D1. **Property-based roundtrip tests** (Hypothesis): custom composite strategy
      generating file trees — unicode/emoji names, 0-byte files, nested dirs, binary/
      text/already-compressed content; property: compress→extract→byte-identical
- [ ] D2. **Edge-case matrix** as parametrized pytest: >260-char paths (with/without
      long-path registry opt-in), reserved names (CON, NUL), locked files, read-only
      attrs, case-only name collisions, >4 GB file (slow-marked), symlink policy
- [ ] D3. **Crash-consistency**: kill the subprocess at EVERY pipeline stage; assert
      input untouched (bytes + mtime), no partial output at final path, temp cleaned
- [ ] D4. **Disk-full simulation** on a small VHDX/subst volume; graceful failure
- [ ] D5. **Deep-verify command** (`excmp verify archive.excmp`): full decompress +
      hash-compare every file. Model source-pinned by
      [20 §6](research/20-source-study-lrzip-zpaqfranz.md): zpaqfranz's split of
      `t` (decompress to RAM + re-hash every fragment, no source needed) and
      `v -ssd` (re-read source from disk vs stored hash) together equal
      "extract-and-compare" without temp space — run both. Add an
      **order-independent global tree hash** (zpaqfranz `sum` model: combine
      per-file SHA-256 order-free) for one-value whole-output equality against
      the ledger. Avoid zpaqfranz `p -paranoid -to` in automation (interactive
      captcha when the target dir is non-empty)
- [ ] D6. **Fuzzing**: HypoFuzz over the `.excmp` parser on Windows (Atheris is
      Linux-only); optional Linux CI job running Atheris
- [ ] D7. **CI**: GitHub Actions `windows-latest` (7-Zip preinstalled!) — matrix
      Python 3.11–3.13, `setup-python` pip cache, SHA-keyed tool cache; badge in README
- [ ] D8. Atomic-write upgrade: temp + `fsync` + read-back hash + `os.replace`
- [ ] D9. 🔴 **`compress()` can publish an archive it cannot restore** — found
      2026-08-01 during the Phase J out-of-sample run, details in
      [benchmarks/2026-08-01-estimator-backtest.md](benchmarks/2026-08-01-estimator-backtest.md).
      `engine._self_test` tests only the **last** stage's container layer (`7z t`)
      before the atomic publish, so a broken stage *underneath* it goes unnoticed.
      Observed for real: an Extreme archive was written and reported as a success,
      and `srep64.exe` then failed its own decompression checksum during extract.
      The extract-time gate worked — the failure was loud, not silent — but the
      user had already been told the archive was good.
      **Fix:** replay the *whole* chain in the self-test before publishing, at least
      for multi-stage chains, and compare against the ledger. That is the only thing
      consistent with "post-restore SHA-256 comparison is the acceptance gate for
      every stage". Cost is real (it doubles compress time for Extreme), so it may
      need to be a profile-level or opt-in "verify deeply" setting — but the current
      behaviour contradicts the stated guarantee, so the default must change or the
      guarantee must be reworded. Pair with D5's deep-verify command.

## Phase E — Release engineering

- [ ] E1. **SHA-pinned tool downloader** — THE lightweight strategy: core app small,
      specialists fetched when a profile first needs them (whole fleet minus FFmpeg
      is only **~15 MB**). Manifest entry = `{name, version, url, sha256, size,
      exe_relpath, license}`; download to
      `%LOCALAPPDATA%\ExtremeCompressor\tools\<name>\<version>\` via temp file →
      verify sha256 **and size** → atomic `os.replace`; hard-fail and delete on
      mismatch; **never add the download dir to PATH**; re-hash before first use each
      run. (The old "solves SREP legally by download-to-user" rationale is retired —
      SREP was dropped from all plans after the source study, doc 20 §4 / doc 21 §5.)
      **New in 2026:** GitHub's release API exposes a per-asset `digest` (sha256) —
      verified present for 7-Zip 26.02, zpaqfranz 64.8, oxipng 10.1.1, par2 1.4.0 —
      so `tools/make_manifest.py` can seed hashes from the API for a human to pin.
      Add a **minimum-version security floor** per tool (7-Zip ≥ 24.09 for
      CVE-2025-0411), not just a pinned hash. Note 7-Zip binaries are **unsigned** by
      policy, so the pinned hash IS the trust anchor — cross-check against winget
      manifests when bumping. Verified tool versions/licenses: [research/12](research/12-lightweight-and-performance.md)
- [ ] E2. `THIRD-PARTY-NOTICES.md`: 7-Zip 26.02 (LGPL+unRAR), zstd (BSD), Precomp
      (Apache-2.0), zpaqfranz (MIT), lepton-jpeg-python (Apache-2.0), oxipng (MIT),
      FLAC (BSD/GPL CLI), xtool (MIT,
      archived), par2cmdline-turbo (GPL, subprocess only), squarify (Apache-2.0),
      Inno Setup (permissive), `cryptography` (Apache-2.0/BSD), `argon2-cffi` (MIT)
- [ ] E3. PyInstaller **--onedir** (NOT --onefile: self-extraction triggers AV/
      SmartScreen **and** re-extracts the whole bundle to temp on every launch)
      wrapped in an Inno Setup installer. **Commit a tuned `.spec`**: measured
      122 MB → **71 MB on disk / 28 MB zipped** by excluding
      QtQml/QtQuick/QtNetwork/QtPdf/QtOpenGL/QtOpenGLWidgets/QtSvg/QtDBus and
      deleting `opengl32sw.dll` (19.7 MB!), `qdirect2d.dll`, `translations/`. Also
      switch `requirements.txt` from `PySide6` to **`PySide6-Essentials`** (dev env
      642 MB → ~210 MB). Floor for a PySide6 Widgets app is ~55-65 MB on disk
- [ ] E4. **Code signing**: apply to SignPath Foundation (free OV signing for OSS;
      requires 100%-OSI repo — another reason xtool stays external and unrar.dll
      is never bundled). Unsigned exes need thousands of downloads for SmartScreen
      reputation; don't ship unsigned. (EV's instant-reputation advantage was removed
      by Microsoft in 2024 — OV is fine.) Also: publish `SHA256SUMS` + GitHub artifact
      attestations (2 lines of YAML ⇒ SLSA Build L2), pin Actions by commit SHA, pip
      `--require-hashes`; submit AV false positives to Microsoft Security Intelligence
      on release day; **never UPX** (verified to *increase* detections)
- [ ] E5. Auto-update v1: poll GitHub Releases API → download signed installer →
      verify SHA-256 → run; consider `tufup` (TUF) later
- [ ] E6. Community files: CONTRIBUTING.md, SECURITY.md (parser vulns matter for an
      archiver), issue templates asking for tool-manifest versions + log file,
      CHANGELOG.md (Keep-a-Changelog + SemVer)

## Phase F — "Protect": encryption + recovery records

The user-visible security features, built on the D0-hardened base. Design and
rationale: [research/10](research/10-security-and-integrity.md).

- [ ] F1. **Optional password on `.excmp`** — build the inner zip as today, then wrap
      the WHOLE container: header (magic, version, 16-byte random salt, Argon2id
      params, chunk size — header as AAD) + **chunked AES-256-GCM** (4 MiB chunks,
      age-style STREAM nonces = 11-byte counter + final-chunk flag, which defeats
      truncation/reorder AND dodges GCM's ~64 GiB single-message cap). KDF:
      **Argon2id** (`argon2-cffi`, RFC 9106 second recommendation: m=64 MiB, t=3,
      p=4). Cipher: `cryptography` AESGCM (AES-NI present even on the i7-3540M).
      HKDF-derived check value in the header so "wrong password" and "corrupted
      file" are different, honest errors.
      **Why not `7z -p`:** now **source-proven** ([19 §1](research/19-source-study-7zip.md),
      `7zAes.cpp:232-238`): the salt lines are literally commented out ⇒ empty salt
      (identical passwords ⇒ identical keys, precomputable — reinforced by a global
      key cache), AES-256-**CBC** with CRC32-only integrity (no AEAD, ciphertext
      malleable), SHA-256 iterated 2^19 over UTF-16LE (GPU-friendly) — *and* it
      would only cover the 7z payload stage, leaving `manifest.json` (every
      filename + hash) and `stored/` files in plaintext. Even `-mhe=on` leaks
      archive size, header size, KDF params, and volume layout ([19 §2](research/19-source-study-7zip.md)).
      Our design encrypts everything = full `-mhe=on` equivalent **plus**
      authentication 7z doesn't have. Keep `7z -p -mhe=on` only as a labelled
      "7z-compatible (weaker)" export mode
- [ ] F2. **Keyfile two-factor** (PeaZip's idea, done right —
      [17 §1](research/17-source-study-peazip.md)): PeaZip merely prepends
      `base64(SHA256(keyfile))` to the passphrase (separable, rides in plaintext
      through the backend arg). Ours must keep Argon2id in the loop:
      `key = HKDF-Extract(salt=SHA-256(keyfile), ikm=Argon2id(password,
      random_salt))` — HKDF alone would make password brute-force cheap. Stream-
      hash the keyfile with a size cap (PeaZip uses 100 MiB); support
      keyfile-only mode; no in-header password verifier (PeaZip's old 16-bit
      `PW_Ver` is a 2^16 oracle — verify via the first chunk's GCM tag instead)
- [ ] F3. **Recovery records** — the one feature WinRAR has that no OSS archiver does.
      `par2cmdline-turbo` (GPL) via the **PyPI package that ships prebuilt
      Windows binaries**, driven by subprocess like every other stage (GPL stays
      contained in a separate process — app remains MIT; never link `libpar2`).
      **Confirmed the right choice by [18 §5](research/18-source-study-freearc-par2.md)**:
      PAR2 already IS the modern FEC design FreeArc's author redesigned toward
      (GF(2^16) Reed-Solomon, self-describing MD5-checked packets, metadata
      redundancy for free), strictly stronger than FreeArc's XOR `-rr` (2 bad
      sectors in one residue class = unrecoverable). Exact CLIs:
      `par2 create -r10 -n1 -m512 -B <dir> <archive>.excmp.par2 <archive>.excmp`;
      verify `par2 verify …`; repair `par2 repair -p …`. **Caveats:** ≤32768
      source blocks and ≤31 recovery files, so for big archives set `-s`
      explicitly (≈ size/2000, multiple of 4) rather than letting block count cap
      granularity; `-n1` = one tidy `.vol` sidecar; exit codes 0/1 distinguish
      ok/repairable. UX default dose (FreeArc's tiering): ~4% tiny / 2% medium /
      1% large — halvable with RS for equal protection. Sidecars for v1;
      in-container embedding is a v2 refinement
- [ ] F4. **Mark-of-the-Web propagation**: copy a downloaded `.excmp`'s
      `Zone.Identifier` ADS onto extracted files via **direct ADS file I/O**
      (`open(path + ":Zone.Identifier")`, ~40 lines — [14 §5](research/14-source-study-nanazip.md)),
      **never via PowerShell** (PeaZip shipped a PowerShell-injection CVE doing
      exactly this — [17 §5](research/17-source-study-peazip.md)). Cap the read
      at 32 KB; skip directories; ignore write failures on FAT/exFAT; and **skip
      any archive-embedded `Zone.Identifier` / `:$DATA` entry** so a malicious
      archive can't overwrite the propagated zone — this is 7-Zip's own
      CVE-2025-0411 fix ([14 §5](research/14-source-study-nanazip.md),
      [19 §8](research/19-source-study-7zip.md)). Default = mark all files
      (7z.exe's CLI default is OFF — `-snz` needed — so we must do this
      ourselves to be safe-by-default on downloads)
- [ ] F5. Honest UI copy throughout: "protects confidentiality; lost password = lost
      data, no backdoor"

## Phase G — "Real archiver": the features that stop us being one-way

Full audit and legal routing: [research/08](research/08-archiver-product-features.md).
Almost all of it is a thin wrapper over the `7z.exe` we already shell out to.

- [ ] G1. **Open/extract foreign archives** (zip/7z/rar/tar/iso/cab/msi/wim/vhd…) —
      magic-byte detect non-`.excmp` input, run `7z x` through the existing
      `SevenZipStage`. **RAR read comes free** and stays legal because we exec a
      user-installed binary, never link or bundle (never ship unrar.dll — it would
      break the MIT-clean requirement for SignPath signing in E4). *This is the
      single feature that turns a compressor into an archiver.* Effort S
- [ ] G2. **Archive browser / `excmp list`** — parse `7z l -slt` for foreign archives;
      for `.excmp` the manifest read is FREE and shows size + SHA-256 + route +
      *reason* per file. **`-slt` parser grammar now fully pinned**
      ([17 §4](research/17-source-study-peazip.md), [19 §6](research/19-source-study-7zip.md)):
      records are blank-line-separated `key = value` blocks after the
      `----------` line; **accept empty RHS** (`CRC =`); `--` opens archive
      blocks, `----` separates nested layers; field vocabulary = 7z's
      `kPropIdToName[]`; flag `Encrypted=+` / `Method` containing `AES`. **Always
      pass a dummy `-p` on list/test** so an encrypted archive errors instead of
      hanging on the interactive prompt (PeaZip's essential trick). Stream-parse
      with a row cap + "partial/flat" fallback (PeaZip caps at 0.5 M rows /
      64-192 MB stdout — huge archives are slow). Selective extract: `stored/`
      entries are instant zip reads; payload members get an honest "this archive
      is solid — one file replays the whole chain" warning first. Engine: additive
      `list_archive()` + `extract_selected()`
- [ ] G3. **Split volumes** (`.excmp.001`…) — pure-Python chunking with per-part
      SHA-256; extraction accepts part 001 and auto-joins. Simpler and format-safer
      than `7z -v` because `.excmp` isn't a bare `.7z`
- [ ] G4. **Standard-format export** — a "plain .7z/.zip (compatible)" checkbox that
      runs only the 7z stage and skips the container. Kills the lock-in objection;
      nearly free given the existing stage
- [ ] G5. **"Convert & shrink"** (zip/rar/7z/iso → `.excmp`) — extract to temp →
      analyze → pipeline → report *why* it did or didn't help. Parity feature
      elsewhere; a **signature feature** with our analyzer attached
- [ ] G6. **Transport-integrity sidecar** — emit a `.sha256` for the container itself
      (and per split volume) + `excmp verify --transport`. This is the maintained
      equivalent of the one verification habit repack users already have
      (`fitgirl-bins.md5` + QuickSFV)
- [ ] G7. **RAM-limited extraction mode** — mirror FitGirl's "limit to 2 GB" option:
      cap dict/window/threads and spill to temp when RAM is short, because archives
      get extracted on weaker machines than they were created on
- [ ] G8. Hash tool (`excmp hash`, stdlib hashlib) — cheap credibility, fits the brand

**Explicitly skipped, decision recorded:** file manager (dilutes the drop→analyze→queue
identity), password manager (liability), secure delete (ineffective on SSDs — would
contradict our honesty brand), RAR *creation* (legally impossible), update-in-place
(wrong for a solid container — "repack to update").

## Phase H — Installer-style output (the FitGirl-shaped feature)

"Share a self-installing archive." Design: [research/09](research/09-fitgirl-installer-and-comparison.md).

- [ ] H1. **THE design rule, now source-confirmed AND made precise**
      ([16 §2](research/16-source-study-innosetup.md)): a byte-identical stub is
      achievable with stock Inno, but **only** as *one frozen universal script →
      compile once in CI → sign once → cache the canonical `setup.exe` → ship
      identical bytes forever*. Inno's exe **always embeds the full script state**
      (AppName, `[Files]`, compiled `[Code]`), and **recompiles are NOT
      guaranteed to hash identically** (resource-section rewrite is
      OS-build-dependent; LZMA2 file chunks auto-thread by machine) — so do NOT
      rely on per-archive recompiles. ALL per-archive variability lives in
      `{src}` sidecars read at runtime via `[Code]` (`AppName={code:…}` needs
      `DisableStartupPrompt=yes`; all `[Files]` marked `external`). Never append
      per-archive bytes to the signed exe (SetupLdr tolerates trailing junk but
      Authenticode does not). SmartScreen reputation is per-file-hash — a
      uniquely-generated unsigned installer is flagged **forever**. This is
      exactly why FitGirl ships `setup.exe + fg-*.bin`
- [ ] H1b. **(new)** Payload integrity via Inno's **ISSig** system
      ([16 §10](research/16-source-study-innosetup.md)): `[ISSigKeys]` embeds only
      a **public key** (constant across archives ⇒ H1-safe), and the `issigverify`
      file flag verifies `.issig` sidecars at install time — cryptographic
      tamper-proofing with **zero per-archive bytes in the exe**. Our packer emits
      the `.issig` sidecars
- [ ] H2. Inno Setup wrapper: generate `.iss` from a template, compile with `ISCC.exe`
      (mirror studied **7.1-dev**; **7.0.x** is the current stable line — pick the
      x64 stub for HE-ASLR + big dictionaries). License is permissive and
      OSI-clean in substance: it explicitly permits using ISCC, redistributing
      generated installers commercially, and redistributing the (untouched)
      compiler in our tool-downloader — **attribution optional**
      ([16 §1](research/16-source-study-innosetup.md)). Do NOT binary-patch the
      stub (ISCC ECDSA-verifies its own stubs and will refuse — brand via
      compile-time directives only)
- [ ] H3. Progress handoff ([16 §4](research/16-source-study-innosetup.md)):
      simplest path is `Exec(ewNoWait)` launch of our extractor + a `[Code]`
      polling loop that reads a progress file (`LoadStringFromFile`) and drives
      `WizardForm.ProgressGauge` / `CreateOutputProgressPage.SetProgress`
      (`SetProgress` pumps the message loop, so the UI stays live). The ISDone-
      style `external 'f@files:dll'` DLL route stays as an upgrade path — and
      `{src}\helper.dll` imports work via `ExpandConst`, so our DLL can sit next
      to the exe, not embedded
- [ ] H4. **Preflight checks learned from ISDone's error taxonomy** (the four causes
      that generate every "unarc.dll error -1" forum thread): non-Latin characters in
      the path, insufficient free disk (Precomp inflation), missing optional volume
      (proceed and report, don't hard-fail like they do), antivirus warning
- [ ] H5. **Chain constraint**: installer output only for redistributable profiles
      (7-Zip LGPL, zstd BSD, Precomp Apache-2.0). SREP/lolz chains excluded (SREP is
      dropped from all plans entirely — doc 20 §4; zpaqfranz + zstd --long replace it)
- [ ] H6. Optional-component payload volumes (languages/videos as named optional
      volumes recorded in the manifest) — the legit half of their selective-download
      trick. Effort L, post-v1

## Phase I — UI v2

Full plan with effort estimates: [research/11](research/11-ui-v2-plan.md).

- [ ] I1. **Settings page + `QSettings` persistence** — the app currently persists
      **nothing** (no QSettings anywhere in the repo): theme resets to dark every
      launch, advanced options reset. Ship theme (+ follow-system via Qt 6.5
      `QStyleHints.colorScheme()` — the free way to feel modern without GPLv3
      Fluent-Widgets), language, default output/temp dirs, **tool-path overrides**
      (unblocks every user whose tools aren't in `C:\Program Files`), remembered preset
- [ ] I2. **Archive browser tab** (pairs with G2) — also a trust feature: it makes the
      SHA-256 ledger visible
- [ ] I3. Queue upgrades: Up/Down reorder + "Run next" + **persisted History tab**
      with "Compress again" (today `clear_finished()` deletes history forever)
- [ ] I4. First-run onboarding card: what was found, what each missing tool unlocks,
      links to downloads. Upgrades to one-click when E1 lands — don't block on it
- [ ] I5. Explorer context menu, Win10 path: HKCU registry verbs (no admin) + argv
      intake in `gui/app.py`. Win11 top-level cascade needs signed sparse MSIX →
      defer to post-E4. **NanaZip is the reference** ([14 §2](research/14-source-study-nanazip.md)):
      the complete IExplorerCommand/IEnumExplorerCommand pattern + the exact
      AppxManifest (desktop4/desktop5/desktop10 `FileExplorerContextMenus` verbs
      + `com:SurrogateServer` class + `runFullTrust`, with the `0000` verb-Id
      prefix trick). Use the **thin-launcher** shape: the shell DLL only
      enumerates commands and spawns our GUI exe with CLI args — never extract
      in-process (Explorer STA isolation). Define the CLI contract now
      (S-effort); the C++ COM DLL comes with the MSIX later. UX heuristics worth
      copying: extension-exclusion list before showing Extract, smart-extract
      subfolder only when the archive root isn't a single folder, multi-part-
      aware folder naming
- [ ] I6. **"Compare presets on this input"** — run installed profiles on a ≤100 MB
      sample as real queue jobs, print **measured** ratios onto the preset cards.
      Upgrades our honesty brand from estimate to measurement; `tools/bench.py`
      already has the harness
- [ ] I7. i18n pipeline: `pyside6-lupdate`/`lrelease` workflow + first `.ts` + Language
      combo ("takes effect after restart"). Every string is already in `self.tr()` and
      the loader already exists — this is the cheapest remaining step. Unlocks
      Dhivehi/Sinhala/Tamil
- [ ] I8. Input treemap "What's inside?" via `squarify` (Apache-2.0, pure Python) +
      labeled legend (never color-only). Zero engine changes; great README material
- [ ] I9. Fix the one design-rule violation: `closeEvent`'s modal `QMessageBox` →
      inline confirm banner
- [ ] I10. Nice-to-have: command palette (Ctrl+K) + **settings search from a single
      action registry** — PeaZip's F12 picker and Options search field are both
      fed by one caption→action dispatcher ([17 §6](research/17-source-study-peazip.md)),
      so build `ActionSpec{id, title, callback, context}` once and feed both a
      `QSortFilterProxy` palette and the settings search. Drag-out extract
      (`stored/` entries only), jump list (raw COM `ICustomDestinationList`; Qt 6
      removed `QWinJumpList`)

## Phase J — Smart Advisor: recommend + preview + estimates 🟡 J1-J4 + J8 DONE (2026-08-01)

The user's ask: *"add a recommend option so the user can just pick the
recommended one, and a preview before compression with estimated time and
estimated size."* Scope agreed 2026-08-01: **estimates + the extra smart
features** (J1-J8), ~2 sessions.

**Start by reading what already exists** — this is an extension, not a new build:
`gui/suggest.py` already has `recommend_profile()` (returns profile + the reason
string shown on the card), `summarize()`, `headline()`, `gain_note()`,
`store_explanations()` and `strongest_profile()`, all Qt-free and unit-tested in
`tests/test_gui_suggest.py`. **Do not rewrite them.** The genuinely missing
pieces are *estimated output size*, *estimated time*, and surfacing all profiles
side by side.

**Why this matters, measured not guessed**
([benchmarks/2026-08-01](benchmarks/2026-08-01-real-programs-folder.md)): on a real
721 MB installer corpus, Extreme cost **2.7× the time of Normal (166s vs 62s) for
0.17 extra percentage points**. Today nothing tells the user that until after they
have waited. That single fact is the feature's whole justification — so the
comparison view must make a bad trade *visible before it is paid for*.

**Shipped 2026-08-01 (J1-J4, J8; J5-J7 remain):** `excmp/estimate.py` (Qt-free,
injectable `Rates`), `analyzer.sample_stats()` measuring compressibility in the
read pass that already samples for entropy, `gui/suggest.profile_comparison()` +
`recommend_with_estimates()`, `gui/widgets/compare_table.py`, a compression-side
free-disk preflight, and `tools/estimate_report.py`. **289 tests pass** (was 223).
Full scoring: [benchmarks/2026-08-01-estimator-backtest.md](benchmarks/2026-08-01-estimator-backtest.md).

Nine things the implementation corrected against the plan below — the first four
change how the feature works, and none of them were guessable from the desk:

1. **The handoff's Extreme rate was wrong.** It divided Extreme's *time* by
   Normal's *bytes*. With Precomp installed, Extreme's override moves the `.zip`
   and `.msi` into the pipeline, so it pipes **431.7 MB, not 148.3 MB**. Corrected,
   Extreme's throughput is **2.642 MB/s — the same as Normal's 2.616**. Extreme was
   never slower per byte here; its extra 104 s is entirely 283 MB of extra routing.
2. **Estimate from the *worst* sample, not the mean.** The analyzer already reads
   head/middle/tail; an installer is a compressible stub in front of an
   incompressible payload, so the mean over-promises. Predicting from the mean
   needed a 1.28x fudge that disagreed between profiles; predicting from the worst
   sample needs 0.947, stable. Out-of-sample size error then came in at **+0.07%
   and −0.60%** on the zstd and 7-Zip chains.
3. **Sampling cannot predict Precomp, and this is a limitation, not a bug.** Two
   installers with near-identical probe readings (entropy 7.78 / 7.52, worst ratio
   1.00 / 0.96): Precomp found nothing in one and a further ~33 points in the
   other. So for Precomp chains `expected` is a **conservative ceiling** that
   assumes Precomp fails (`SizeEstimate.upper_bound`; the UI prints "≤ 142.6 MB"
   and "8% or better"), and `low` reaches to 0.30 so the range still contains the
   case where it works. Before that fix, a measured 95.7 MB fell *outside* the
   predicted range.
4. **A conditional flag must not demote the recommendation.** The estimate-aware
   override originally overruled the routing heuristic outright. Measured, that was
   right on the 721 MB corpus and badly wrong on a 163 MB one, where it demoted
   Extreme, which then delivered **41.4% against Normal's 7.3%** — a 34-point cost
   to save two minutes. Now: overrule only on an *unconditional* flag; otherwise
   keep the recommendation and put the condition on the row ("if Precomp cannot
   open these streams…"). J3 asked for a bad trade to be *visible* before it is
   paid for, not silently avoided on evidence labelled unknown.
5. **Rates are keyed on the resolved chain, not the profile name** — so an Extreme
   that degrades to zstd for want of Precomp predicts what it will actually run
   instead of promising the absent tool's ratio.
6. **The Precomp chain has two throughput regimes** (2.642 MB/s no-op, 0.842 MB/s
   working — 3.1x), selected by the same unknown as #3. No single rate fits both
   inside J8's ±40%, so that gate is **±80% for Precomp chains**, documented rather
   than quietly widened. Range containment is asserted unconditionally.
7. **ZstdStage's level 19 is not the handicap it looked like.** A 16 MB corpus
   suggested Fast was 2x slower than Normal; measuring 139 MB put zstd at 3.63 MB/s
   against 7-Zip's 4.03 — within 11%. The earlier inference was a small-sample
   artifact.
8. **No cache was added, against J1's instruction, because nothing needed one.**
   The ratio is folded into `FileInfo`, and the GUI already re-plans from cached
   `_infos` without re-reading. An LRU in `estimate.py` would have been dead code.
9. **The ≤1 s cost budget is missed — by pre-existing code.** 300 files took
   4.95 s; the new zstd probe is 0.07 s of that (1.4%) and Shannon entropy's
   `Counter.update` is 1.57 s (~53 ms/MiB). `bytes.count()`x256 measured **3x
   slower**, so there is no cheap stdlib fix; a real one needs numpy or a C
   extension (a dependency decision, deliberately not taken mid-phase).

⚠️ **Two integrity findings that are not Phase J's to fix — see D9 and B11 below.**

- [x] J1. **Sample-based size estimator** (`excmp/estimate.py`, engine-side, Qt-free).
      Do not use a static ratio table — **measure**. The analyzer already reads up
      to 3×1 MiB per file for entropy (`analyzer.sample_entropy`); compress those
      same samples in-process with `zstandard` at a low level to get a *measured*
      ratio per file, then scale to the target profile. This is the same
      poor-man's-detector idea as FreeArc's `-ma` content probe
      ([21 §3.5](research/21-source-study-synthesis.md)), reused for prediction.
      Rules: stored-route files contribute their size at **exactly 1.0** (they are
      copied verbatim — that part of the estimate is not a guess); return a
      **range** (low/expected/high), never a single false-precision number; cache
      per `(path, size, mtime)` so re-analysis is instant. Cost budget: ≤1 s for a
      few hundred files.
- [x] J2. **Time estimator** — must be a **two-rate model**, because a single
      MB/s figure is actively misleading: 81% of the real corpus was *stored*
      (disk-bound) and only 141 MiB was *piped* (CPU-bound). Blending them gave
      "11.6 MB/s" which would mispredict badly on any other mix.
      `time ≈ stored_bytes / io_rate + piped_bytes / codec_rate[profile] × core_scale`.
      Measured 2-core starting points, piped-only: **normal ≈ 2.5 MiB/s, extreme
      ≈ 0.9 MiB/s**; `io_rate` ≈ 100 MB/s and is capped by the *source* disk (the
      benchmark corpus lived on an external HDD). Note the rate is content-
      dependent — the 2026-07-18 synthetic run hit ~6.5 MB/s on compressible data
      vs 2.5 here — so **ranges are mandatory** and J7 exists to fix it properly.
      Round honestly ("~1 min", "~3 min", "2-4 hours"), never "163 s".
- [x] J3. **Profile comparison table** (the headline UI). All four profiles as rows:
      estimated size, estimated time, % saved, recommended row highlighted with the
      existing `recommend_profile()` reason. Plus a **"not worth it" flag**: when a
      slower profile costs ≥2× the time of a cheaper one for <1 percentage point
      more saving, say so on the row. Reuses `AnalysisSummary`; needs a `Plan` per
      profile (cheap — `planner.plan()` is pure and already runs per profile for
      `reference_plan`).
- [x] J4. **Free-disk preflight for compression.** D0 shipped this for *extraction*
      (`engine._check_free_space`) — generalize it. Compression needs
      `output_estimate + peak temp`, and temp is the dangerous one: Precomp
      inflates 2-5× mid-pipeline ([research/10](research/10-security-and-integrity.md) C-3).
      Warn before starting, with the number. **Shipped with two thresholds, which
      the plan did not anticipate:** extraction can hard-fail on an exact figure
      because the manifest declares every size, but compression cannot — the output
      is an estimate and Precomp's inflation is data-dependent. So there is an
      impossible *floor* that refuses and a pessimistic *peak* that only warns. A
      preflight that refuses jobs which would have succeeded gets switched off, and
      then it protects nobody. Needs are also **grouped by volume** (`st_dev`),
      since temp and output are usually the same disk and then compete for the same
      bytes — the extraction check looks at one directory only.
- [ ] J5. **Remember the last choice per content type** — QSettings map
      `dominant category -> profile`, so a user who always picks Fast for video
      folders stops re-picking. **Depends on I1** (the app persists *nothing*
      today, no QSettings anywhere); either do I1 first or ship the QSettings
      bootstrap here and let I1 build on it.
- [ ] J6. **Long-job confirmation** — past a threshold (~45 min estimated), an
      inline confirm: "this is about 3 hours on this machine — run overnight?".
      Generalizes the C4 media-specific warning. Inline banner, **not** a modal
      (I9 is fixing the one existing modal violation — do not add a second).
- [ ] J7. **Self-calibrating rates** (what makes the estimates actually good).
      After every completed job, record real `piped_bytes / elapsed` **per resolved
      chain** (not per profile — a degraded Extreme and a Fast run the same stages
      and should share calibration) into QSettings and blend into future estimates
      (exponential moving average, keep the shipped defaults as the cold-start
      prior). `Rates` is already an injected argument, so this needs no model
      change. Estimates then converge on *this* machine's true speed instead of a
      benchmark laptop's — the two corpora measured on 2026-08-01 disagreed by
      **2.5× on 7-Zip's throughput alone**, purely because one lived on an external
      HDD. **Also learn `codec_factor`,** which is what would eventually fix the
      Precomp blind spot in J1 note 3 — the only real fix, since no cheap probe can.
- [x] J8. **Acceptance test — the estimator must be scored, not trusted.**
      Backtest J1/J2 against both recorded benchmark runs
      (`docs/benchmarks/2026-07-18-*`, `2026-08-01-*`): predicted size within
      ±10% and predicted time within ±40% of measured, as a real pytest. An
      estimator nobody scored is a guess with a progress bar. Also property-test
      that the store-route portion of the size estimate is *exact*.
      **Shipped, with three corrections to the plan.** (a) The **2026-07-18 run
      cannot be backtested at all**: its corpus was `%TEMP%\excmp-sample` and the
      doc records no file list, so nothing is reproducible from it. It survives
      only as evidence of the rate spread. Its lesson is now enforced —
      `2026-08-01-estimator-backtest.md` records exact file names *and* byte sizes,
      and the test voids itself if a size no longer matches. (b) A backtest against
      2026-08-01 is **in-sample** (the factors were fitted on it), so it is a
      regression guard, not validation; the genuine out-of-sample evidence is a
      second 163 MB corpus predicted before it was compressed. (c) The ±40% time
      gate is met for zstd/7-Zip chains and is **unachievable for Precomp chains**
      (two regimes, 3.1× apart) — gated at ±80% with the reason written down.
      Range containment is asserted for every chain, because a range that excludes
      the truth is worse than no range.

**Explicitly out of scope for J** (already covered elsewhere): I6 "compare presets
by actually running them on a ≤100 MB sample" is the *measurement* upgrade to J3's
*estimate* — keep them separate and ship J3 first.

## Recommended extras (post-v1 ideas)

- Folder size treemap (WinDirStat-style) on the analysis screen
- "Compare profiles on a sample" button — runs `tools/bench.py` on 100 MB of the
  input and shows the real trade-off before committing hours
- Solid-archive chunking for resumable multi-hundred-GB jobs + `.excmp` split volumes
- zstd `--train` dictionaries for many-small-similar-file corpora
- Self-extracting `.exe` output option
- Linux/macOS support (engine is already portable; stages need path candidates)

## Suggested order & effort (2-core laptop reality)

| Order | Phase | Rough effort | Why here |
|---|---|---|---|
| ~~1~~ | ~~A (GUI)~~ | ✅ done | made every later feature visible and testable |
| ~~2~~ | ~~D0 (security hotfix)~~ | ✅ done | an exploitable reader bug outranked every feature |
| ~~3a~~ | ~~J1-J4 + J8 (estimator + comparison table + preflight + backtest)~~ | ✅ done | estimates are live and scored against two real corpora |
| **3b** | **J5-J7 (per-type memory, long-job confirm, self-calibration)** | **1 session** | **finishes Phase J; J7 is what turns a cold-start prior into estimates that fit this machine** |
| **4** | **B11 + D9 (drop SREP; make the self-test replay the chain)** | **1 session** | **two integrity findings from the J8 run. An archiver that can publish an unrestorable archive outranks features — same principle that put D0 first** |
| 5 | G1-G2 (open/browse foreign archives) | 1 session | S-sized, and the single biggest identity gain: stops being one-way |
| 6 | D1-D3, D7 (QA core + CI) | 1-2 sessions | locks in the integrity guarantee before adding stages |
| 7 | B1-B3 + B9-B10 (zpaqfranz, JPEG/PNG, RAM caps) | 1-2 sessions | completes Insane; B9 is one-line arg changes with real payoff |
| 8 | E1-E2 (downloader + notices) | 1 session | unblocks every remaining specialist (par2, xtool, FFmpeg) |
| 9 | I1-I2 (settings/persistence + archive browser) | 1-2 sessions | the app forgetting everything is the loudest daily annoyance |
| 10 | F1-F3 (encryption + recovery records) | 2-3 sessions | table-stakes "secure"; F3 is the WinRAR feature nobody OSS has |
| 11 | B6 (xtool + Oodle) | 1-2 sessions | the real FitGirl gap on modern games — needs E1 first |
| 12 | C (video shrink) | 2-3 sessions | biggest user-visible win on media, but hours of CPU per job |
| 13 | G3-G8, I3-I8, E3-E4 | as needed | parity + polish + release |
| 14 | H (installer output) | 2-3 sessions | flagship differentiator, but needs E4 signing to be usable |

Two ordering principles behind this: **security before features** (D0 first — we
found a real bug), and **cheap identity wins early** (G1-G2 are S-sized and change
what the app *is*). Phase H sits last on purpose: an unsigned generated installer is
SmartScreen-flagged forever, so it depends on E4.

---

## Answering the two questions that drove this research round

**"Is ours more powerful and more highly compressible than the FitGirl method?"**
Honest, evidence-based answer ([research/09](research/09-fitgirl-installer-and-comparison.md)):
- **Old zlib-era games**: we're already in their league (72.4% measured on our
  synthetic corpus vs their 60-75% class).
- **Modern Oodle/zstd AAA games**: we lose badly today — ~5-15% vs their 50-70% —
  because Precomp can't open Oodle streams. B6 (xtool + the game's own oo2core DLL)
  closes most of it; the remainder is the lolz codec (~5-10%, no legal path) and
  per-game hand tuning (structurally unavailable to an automatic tool).
- **Everything that isn't a game**: we're simply better — they don't route by type.
- **Trust and safety**: we win everywhere. SHA-256 per-file ledger + chain replay vs
  CRC32 + an optional MD5 batch file; a maintained legal stack vs 2014-era abandoned
  DLLs (ISDone/unarc); inputs never modified and bounded RAM vs "set a 16 GB pagefile
  and disable your antivirus."

So: **not uniformly more compressible — more *powerful* in scope and far more
trustworthy.** They optimize one number (download size of one hand-tuned game); we
optimize a contract (anything in → smallest honest size → verified bit-exact restore).

**"Can we include the Inno Setup / installer things they use?"** Yes — Phase H, with
one hard design rule (H1): the generated `setup.exe` must be byte-identical for every
user and signed once, because SmartScreen reputation is per-file-hash. That is
precisely why FitGirl ships `setup.exe + fg-*.bin` rather than one big exe.
