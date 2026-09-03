# 🗺️ ExtremeCompressor — Remaining Work, Step by Step

> Status date: **2026-09-01**. **552 tests** (551 pass + 1 strict-xfail).
> Everything below is **merged to `main`**; nothing is awaiting review.
>
> **Done:** engine core · Phase A (GUI) · Phase D0 (security hotfix) ·
> Phase J part 1 (estimates before compressing, scored on two real corpora) ·
> B11 + D9 (SREP-free chains; nothing publishes without a fully verified
> restore) · **all of UI v3** — [research/23](research/23-ui-v3-redesign.md)
> §7's four waves and the whole of its §5 engine-exposure inventory:
> screen fit and the merged chooser (w1), the Activity tab and the height
> compaction (w2), and verify/list/hash, foreign archives, the `.sha256`
> sidecar, Settings with persistence, and the level/dictionary knobs with a
> peak-RAM column (w3).
>
> The one open exception: research/23 §2.4's ≤300px page budget is
> **unreachable** and stays a `strict=True` xfail — §2.4 and §3.3 contradict
> each other, and §3.3's 32px touch floor wins. See
> [benchmarks/2026-08-07-ui-wave2b](benchmarks/2026-08-07-ui-wave2b.md).
>
> **G2 is done** (2026-09-01, branch `phase-g2-foreign-listing`, awaiting
> review): foreign archives list, encrypted ones ask for a password instead of
> hanging, and single members can be pulled out of either kind.
> **Next up: J5-J7** (per-type memory, long-job confirm, self-calibration).
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

## ⚖️ 2026-09-01 — the repo went private, and the licence constraint is gone

The repo is now **PRIVATE**. The 100%-OSI rule existed to keep free SignPath
code signing available for a public release; there is no public release, so
there is no distribution, so the obligations that trigger on distribution do
not apply. **SREP, LOLZ, Oodle/`oo2core`, `unarc.dll` and xtool Patreon builds
are all permitted now.**

### What this unblocks

| Item | Was blocked by | Now |
|---|---|---|
| **B6** (xtool + Oodle) | needed E1 for a pinned hash | **unblocked** — and the `oo2core` DLL may simply be vendored, which dissolves the restore-time bootstrap problem doc 24 §2 showed is otherwise permanent |
| **LOLZ as final codec** | not OSI, never even listed | **new item B12** below |
| **SREP** | "not OSI" (which doc 24 §5 showed was shaky anyway) | permitted — **but still not recommended**, see below |
| **`unarc.dll` / ISDone** (H3) | GPL, in-process = linking | permitted; still only matters when Phase H starts |

### What it does NOT change — and what gets *more* important

**The lossless guarantee, and the SHA-256 gate that enforces it.** Several
newly-permitted tools are known-unreliable. SREP failed its own decompression
checksum on **1 of 3 runs over byte-identical input**. The licence rule was
never what protected us from that — `_verify_before_publish` was. With flakier
tools now in scope, that gate is the whole safety story. **Never weaken
verification to accommodate a new tool.**

### What becomes optional

**Phase E4 (SignPath code signing) no longer applies**, and E3/E5 (installer,
auto-update) matter only if this is ever shared. Deprioritise the whole of
Phase E except **E1's tool downloader**, which is still useful for *fetching*
tools onto the machine.

### Standing recommendation on SREP

Permitted ≠ advisable. It buys ~3.5 points; **zpaqfranz (B1) does the same job**
— long-range CDC dedup at unlimited distance — is actively maintained, MIT, and
has never failed a restore here. **Do B1 first.** Only reach for SREP if B1
measurably underperforms on a real corpus, and if it goes in, it goes in behind
the verification gate like everything else.

### Revised order, best-app-first

1. **B1** (zpaqfranz) — dedup back, no risk, completes Insane
2. **B6** (xtool + Oodle) — the AAA gap; now vendorable, so the DLL problem is solvable
3. **B12** (LOLZ) — final-codec upgrade
4. **B8** — re-benchmark and replace every `(est.)` with a measurement
5. J5-J7, then D1-D3/D7 (QA + CI)

If the repo is ever made public again, **this entire section reverts** and the
OSI rule comes back before anything ships.

- [ ] B12. **LOLZ as an optional final codec** (new 2026-09-01, unblocked by the
      licence change). ~5-10% over LZMA2 on game data per scene reports —
      **unverified by us**, so B8 must measure it before any UI copy quotes a
      number. Closed-source, so: treat exactly like every other untrusted
      stage — pinned binary, `-t2`, no trust in its exit code, and the
      post-restore SHA-256 comparison is what decides whether the archive
      publishes. Route it as an Insane-tier alternative to the 7-Zip stage,
      never as a default, and degrade gracefully when the binary is absent.

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

- [x] B1. ✅ **DONE 2026-09-02** (branch `phase-b1-zpaqfranz`, measured in
      [benchmarks/2026-09-02-b1-zpaqfranz.md](benchmarks/2026-09-02-b1-zpaqfranz.md)).
      Insane is real: `precomp → zpaqfranz`, 5/5 byte-identical on two corpora
      under an independent SHA-256 check, and the profile no longer prints
      "zpaqfranz backend not integrated yet" while quietly running the Extreme
      chain. `-m4 -longpath`, plain `a` (vanilla-zpaq-7.15-readable), never
      `t -paranoid -to` (captcha hazard).
      **Three things the implementation corrected against this plan:**
      (1) **It did not buy the 3.5 points.** Insane measured **40.77%** against
      Extreme's **41.75%** on corpus B — *worse* by 0.97 points, at 2.3× the
      compress time and 4.8× the extract time. After Precomp the stream is five
      *distinct* installers, so CDC has nothing to find and LZMA2 simply wins
      the CM contest. (2) **The 3.5 points came back anyway, without it.** Same
      corpus, unchanged Extreme chain: 37.91% in August, **41.75%** now. Leading
      hypothesis is the 7-Zip 24.07 → 26.02 upgrade; **unconfirmed**, because
      24.07 is no longer installed to A/B against. (3) **zpaqfranz cannot be
      tree-capable here.** It stores the *absolute* path it is handed
      (`C:` → `C_`) and `add` has no relative-path switch, so a tar must
      precede it and it only ever gets one file; `extract` relocates that file
      back to its real name. Found by the D9 gate refusing to publish, not by
      any test — Precomp exits 0 while producing nothing when the path passes
      `MAX_PATH`. Original item:
      **zpaqfranz stage** (actively maintained, FOSS, MIT): `a -m4 -longpath`
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
- [x] B2. ✅ **DONE 2026-09-02** — JPEG specialist via the
      `lepton-jpeg-python` 0.5.8 wheel (as B10 corrected: in-process, no exe).
      Measured on **37 real JPEGs** from this machine
      ([benchmarks/2026-09-02-b2](benchmarks/2026-09-02-b2-lepton-jpeg.md)):
      **33.42% saved on the 23 files lepton accepted** — better than the ~22%
      predicted — and **37/37 byte-identical** end-to-end.
      **The finding that shaped it: lepton refused 14 of 37 files** — 13
      CMYK/4-channel (print work, an ordinary genre) and one wider than
      16384 px. And the refused files were the *big* ones, 135 MB of 151 MB,
      so the folder-level saving was **3.47%** despite 23 files packing.
      Read it as: **~33% on RGB photo folders, ~0% on CMYK print work, and no
      error either way.** Before B2 this folder compressed by approximately
      nothing, since JPEGs are high-entropy and were all stored verbatim.
      Design: `excmp/jpeg.py`'s `pack()` compresses **and immediately
      decompresses**, returning `None` unless the bytes match the original
      exactly. That doubles the work per JPEG and buys the ability to *fall
      back* rather than *fail* — a file lepton would mishandle is caught while
      storing it raw is still free, instead of at restore time when D9 would
      refuse the whole archive. Reuses the `stored/` machinery G9 extended
      (a `codec: "lepton"` ledger entry), so no new route was needed.
- [x] B3. ✅ **DONE 2026-09-02 — but NOT as specified.** The plan said
      "`oxipng -o max` default"; measured, that would have broken the product.
      ([benchmarks/2026-09-02-b3](benchmarks/2026-09-02-b3-png.md).)
      **oxipng does not preserve bytes**: on 10 real PNGs it saved 31.79% and
      produced **0 byte-identical files**. It re-encodes the image to a smaller
      form that renders the same — pixel-lossless, not byte-lossless — so it
      cannot satisfy a SHA-256 ledger. **oxipng moves to Phase C** with the
      AV1 re-encoder: opt-in, labelled, changes your file.
      **The lossless route is better anyway.** PNG is deflate all the way down,
      so Precomp expands and reconstructs it exactly: **38.41% saved, 15/15
      byte-identical**, against oxipng's 31.79% and zero. All it needed was for
      PNGs to stop being routed to `store` — `_DEFLATE_MEDIA = {".png"}` is the
      one exception to "media stays stored", because a PNG's entropy is deflate
      output rather than real randomness. JPEG deliberately stays out: its
      entropy *is* real and it has B2/lepton on the stored route.
      **Uncovered a bigger bug.** PNG inflates ~50x through Precomp (3.5 MB tar
      → 177 MB .pcf), and extraction runs the chain backwards, so the
      decompression-bomb guard's flat 8x-over-ledger allowance refused the
      restore. No multiplier can fix that — loose enough for PNG is no defence,
      tight enough to defend rejects PNG. So `StageRecord.input_bytes` now
      records what each stage actually consumed, and extraction is bounded by
      that measured figure + 25% instead of a ratio. **This makes the bomb
      defence stronger**, and old archives (`input_bytes: 0`) fall back to the
      multiplier, with a test that strips the field and restores one.
      Also: `precomp_inflation()` is now per-type and byte-weighted, because a
      flat 5x under-reserved temp for PNG by an order of magnitude.
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
      🔒 **RESEARCH 2026-09-01 ([24](research/24-fitgirl-razor12911-toolchain.md)
      §2): there is no open-source Oodle *encoder*, and there will not be one.**
      `powzix/ooz` is the reverse-engineered Oodle implementation everyone
      cites, and its own README reads `-z --compress compress (requires
      oo2core_7_win64.dll)` — it **decodes** in open code and **encodes by
      calling the proprietary DLL**. Since our model is restore = recompress,
      the DLL is unavoidable and permanent. This converts the audit note below
      from "prudent design" into "forced": B6 must be built around shipping or
      re-sourcing the exact `oo2core` version, because no OSI-only path to
      Oodle recompression exists. Also confirmed: xtool is **MIT, © 2016-2022,
      archived 28 Oct 2023** — our routing was correct, but nothing upstream
      will ever be fixed, so pin the version and verify every roundtrip.

      ⚠️ **AUDITED 2026-09-01 — B6 as written would still leave the AAA gap
      open, and the reason is load-bearing.** B6(a) says "re-resolve the
      oo2core DLL from the game folder at restore". **In the archival case
      the game folder no longer exists** — and architecturally it cannot,
      because `planner._CHAINS` is one linear whole-payload chain and a stage
      is one path in, one path out, so the DLL is *inside the very blob xtool
      decode has to produce*. Left as written, an xtool archive only restores
      on the machine that made it, which breaks the lossless guarantee far
      more seriously than the ratio gap B6 exists to close. **Fix before
      implementing:** force the oo2core DLL(s) into the `stored/` bucket, copy
      them in as a container resource when the user's selection did not
      include them, materialize to the scratch cwd before decode, and make the
      manifest field a **list** — one game can ship several oo2core/oo2ext
      versions and different paks can come from different ones.
      **Five sub-items the plan is missing:** (i) where the xtool stage sits
      in the chain and how it arbitrates with Precomp (both handle zlib);
      (ii) a version pin for the xtool binary, not just the DLL; (iii)
      `excmp/ram.py` is LZMA2-only, so the shipped peak-RAM column will
      silently under-report — xtool decode's `-dm` default is 75% of RAM,
      which is the number that hurts on a 2-core/16 GB target; (iv)
      `excmp/analyzer.py` has zero Oodle/pak awareness and
      `gui/suggest.py`'s prose already promises "70%" on paks, so J8's
      estimator backtest **regresses before it improves**; (v) a free-disk
      preflight for precompression inflation, plus a decision on what an
      xtool stage does to D9's chain-replay cost. **Also:** the self-test
      cannot exercise the real failure mode (a *different* DLL at restore),
      so it will look green while the actual risk is untested — the manifest
      pin is the only defence. **Phase H conflict:** nothing currently stops
      an installer being generated from an xtool+Oodle archive, which would
      embed a proprietary DLL in a redistributable `setup.exe` and break the
      100%-OSI requirement E4/SignPath depends on. **Effort is 3-4 sessions,
      not 1-2**, and B6(f) (`.xtl` curation) should be split out as post-v1:
      doc 09 §4 classifies it as the least transferable lever and it requires
      owning and running each title. **The "needs E1 first" dependency is
      soft** — `tools.py` already degrades gracefully and `_resolve_chain`
      already warns, the same detected-only pattern B4 uses. What E1 really
      buys is a pinned hash, which restore-side correctness wants anyway.

- [x] B7. ✅ **DONE 2026-09-02** — BCJ2, measured rather than assumed
      (`tests/test_sevenzip_switches.py` carries the table).
      Across three corpora on 7-Zip 26.02 at mx9: forcing `-mf=BCJ2` is worth
      **−1.296%** on 23.5 MB of real DLLs/EXEs, **+0.000%** on 163 MB of
      installers, and **+0.043%** (i.e. slightly worse) on 3.2 MB of source.
      So it is applied **conditionally** — `_wants_bcj2()` turns it on when
      ≥25% of the *piped bytes* are `Category.EXECUTABLE`, weighed by bytes
      rather than file count, because one 50 MB DLL beside a hundred small
      text files is an executable job.
      **The plan's "5-10% on x86" figure is not supported**: measured here it
      is **1.3%**. The item already flagged it as benchmark-derived with no
      source-level basis; this is our own number replacing it. Forcing the
      filter also proved necessary — at mx9 with the MT mixer 7-Zip is
      documented to auto-select BCJ2 and plainly had not. **Never UPX** still
      stands.
- [ ] B8. Re-benchmark everything on Silesia + a real game folder; update README table
      — this is also what replaces every *(est.)* in the doc 09 comparison table
- [~] B9. 🟡 **PARTLY DONE 2026-09-02** — `-mqs` is now always passed (measured never harmful, worth 0.13% on source trees; 7-Zip leaves it off by default). **`-md=192m` was measured and deliberately NOT adopted: zero bytes of difference on all three corpora, up to 27% more time.** It stays a user knob, not a default. Default threads is already 2. The remaining part is the exact RAM estimator formula. Original item: **RAM caps + thread defaults** (verified formulas, [research/12](research/12-lightweight-and-performance.md);
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
- [x] B11. ✅ **DONE 2026-08-02** (branch `phase-b11-d9-integrity`, measured in
      [benchmarks/2026-08-02-b11-d9-acceptance.md](benchmarks/2026-08-02-b11-d9-acceptance.md)).
      Chains are now `precomp → sevenzip`; old srep archives still extract
      (pinned by a test that builds a genuine pre-B11 archive and restores it).
      The measured price: −3.5 points on the dedup-friendly corpus, +31 s
      compress on the 721 MB corpus — SREP's dedup used to shrink 7-Zip's input.
      B1 (zpaqfranz) is how the points come back. Original item:
      **Remove SREP from the Extreme/Insane chains** — the source study
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
- [ ] C6. **(moved from B3, 2026-09-02)** `oxipng` / ECT as an **opt-in**
      PNG re-encoder. Measured 31.79% on real PNGs but **0 of 10 files came
      back byte-identical** — it rewrites the image to a smaller encoding.
      That is pixel-lossless, not byte-lossless, so it belongs here with the
      AV1 re-encoder and not in a lossless phase. Note the lossless
      `precomp → 7z` route already beats it (38.41%), so this is only worth
      building for the case where Precomp is unavailable.

## Phase D — QA hardening (data integrity IS the product)

- [x] D1. ✅ **DONE 2026-09-02** — property-based roundtrip tests
      (`tests/test_property_roundtrip.py`, Hypothesis, MPL-2.0, dev-only).
      States the product's whole claim as one executable property:
      `extract(compress(T)) == T` for every generated tree. Trees mix names
      drawn from the characters that actually break archivers (unicode,
      spaces, dots, `=`, `#`, `&`), contents from the three regimes a codec
      treats differently (compressible / random / empty), and per-file depth
      0-3 so one example can hold a top-level file and a four-deep one.
      Two more properties alongside it: **the input is never modified** (bytes
      *and* mtime) and **the ledger accounts for every file** — an entry
      missing from the ledger is a file nobody would notice failing to return.
      Suite runs 30 examples; a one-off deeper hunt of **120 generated trees
      found no counterexample**.
- [x] D2. ✅ **DONE 2026-09-02** — the awkward-but-legitimate file matrix
      (`tests/test_edge_cases.py`, 25 cases, all real engine round-trips).
      The complement to D0: `test_safepath.py` pins what we **refuse**, this
      pins what we must **accept**, because rejecting a legitimate awkward
      name is its own kind of data loss. Covers spaces, parens, `=`, `%`,
      `&`, `#`, brackets, apostrophes, Cyrillic, Japanese, **Dhivehi**, emoji,
      200-character names, leading dashes; zero-byte files, trees of nothing
      but empty files, 20-deep nesting, 200 small files, >260-character paths,
      read-only attributes, and names that merely *contain* a reserved word
      (`CONTENTS.txt`, `console.log`, `NULLABLE.md`) — the false-positive half
      of D0's validator. Plus an explicit input-is-never-modified check on
      bytes and mtime. **All 25 passed first time**; no bugs found, but the
      class was previously untested.
- [x] D3. ✅ **DONE 2026-09-02** — crash consistency
      (`tests/test_crash_consistency.py`, 8 cases). Cancels a job from inside
      `progress_cb` so the interrupt lands *during* a stage rather than at a
      boundary, then asserts the three things that must hold either way: the
      input is untouched (bytes and mtime), nothing partial sits at the output
      path, and temp is clean — the last one matters because Precomp
      legitimately inflates 2-5x mid-pipeline. Also pins D9 as a
      crash-consistency property: an assertion inside the progress callback
      fires if a `.excmp` ever appears at the final path *before* verification
      finishes. Plus: a cancelled run must not poison the next run sharing the
      same temp dir.
      **One thing the implementation corrected:** the first version asserted
      `pytest.raises` and failed on the Fast profile — not a bug, the corpus
      simply finished before the cancel landed. Whether a cancel wins is a
      race, so the tests now assert the invariant that holds *either way*: if
      the job finished it must have published a genuinely restorable archive,
      and if it stopped it must have published nothing.
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
- [x] D9. ✅ **DONE 2026-08-02** (branch `phase-b11-d9-integrity`).
      `_verify_before_publish` fully restores the archive in temp and runs the
      real `extract()` + `verify_restore()` before the atomic rename — no hash
      match, no file. It went in as the **default, not an option**: the tagline
      promises a verified byte-identical restore, so the default had to make it
      true. Measured cost 6–48% of total job time depending on chain and mix
      ([benchmarks/2026-08-02](benchmarks/2026-08-02-b11-d9-acceptance.md));
      the estimator gained a per-chain verify term so promised waits include
      it, and the J4 preflight budgets the restore in temp — store-only jobs
      included. A corrupting stage now blocks publication outright
      (`tests/test_publish_gate.py`). Original item:
      **`compress()` can publish an archive it cannot restore** — found
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
      SREP was dropped from all plans after the source study, doc 20 §4 / doc 21 §5. **Rationale corrected 2026-09-01** ([24](research/24-fitgirl-razor12911-toolchain.md) §5): the licence is *unclear*, not provably non-OSI — SREP-adjacent source sits in GPL-2.0 repos, though the shipped `srep64.exe` is an unlicensed freeware binary. **The disqualifying reason is integrity:** it failed its own decompression checksum on 1 of 3 runs over byte-identical input. Lead with that, not the licence.)
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

- [x] F1. ✅ **DONE 2026-09-03** — `excmp/crypto.py`, `compress --password`,
      and `extract` decrypts transparently. Argon2id (m=64 MiB, t=3, p=4) →
      AES-256-GCM in 4 MiB chunks with age-style STREAM nonces (11-byte
      counter + final-chunk flag), the header as AAD for every chunk, and an
      HKDF check value so "wrong password" and "damaged file" are different
      sentences. The **whole container** is wrapped, so `manifest.json` — every
      filename and every hash — and the `stored/` tree are encrypted too;
      `7z -p` could only ever have covered the payload stage.
      Verified end-to-end: archive encrypted on disk, plaintext marker absent
      from the bytes, wrong password refused with the right error, correct
      password restores byte-identically.
      **A denial-of-service found in our own code while testing.** The KDF
      parameters live in the header and are therefore attacker-controlled, and
      "the header is AAD" does *not* protect them — they are needed to derive
      the key that would check the tag. `test_header_tampering_is_detected`
      flipped one bit that landed in the top byte of `m_kib`, 8 KiB became
      16 GiB, and the single test took **19 minutes**. A crafted header can ask
      for 4 TiB. Bounds are now enforced before Argon2 is called
      (8 KiB-1 GiB memory, ≤20 passes, ≤16 lanes) with three tests pinning it;
      the suite went from 19 minutes to **1.8 seconds**.
      Prompting asks **twice** when setting a password, because there is no
      backdoor and a typo is unrecoverable. The password is never accepted on
      argv — it would sit in the process table and the shell history.
- [x] F2. ✅ **DONE 2026-09-03** — a keyfile as a real second factor.
      `key = HKDF(ikm=Argon2id(password, salt), salt=SHA-256(keyfile))`. The
      ordering is the point: HKDF is fast by design, so folding the keyfile in
      *instead of* Argon2id would leave an attacker who steals the keyfile
      facing only a cheap password guess — the flaw in PeaZip's
      prepend-the-hash approach. Argon2id runs first and stays memory-hard;
      HKDF only mixes. Two tests pin that: one times the KDF directly, one
      asserts the Argon2 output is HKDF's *ikm* and not its salt.
      Format bumped to **v2** with a flags byte; v1 archives still read. The
      flag exists so a missing keyfile raises `KeyfileRequired` rather than
      "wrong password" — otherwise a user with the correct password hunts for
      one that is already right and concludes the archive is broken. The mirror
      case (a keyfile supplied where none was used) is refused too.
      Keyfile-only works; an empty keyfile is refused rather than silently
      reducing two factors to one; the keyfile is stream-hashed with a 100 MiB
      cap, because somebody will eventually point this at a 40 GB video.
- [x] F3. ✅ **DONE 2026-09-03** — `excmp/recovery.py`,
      `compress --recovery [PCT]`, and a new `excmp repair` verb. PAR2 via the
      `par2cmdline-turbo` wheel, which ships a real Windows binary; driven as a
      subprocess so its GPL stays out of our in-process code.
      **The whole point, proven end-to-end through the CLI**: 200 KB zeroed out
      of a 5.5 MB archive → `excmp repair` → **byte-identical to the original**
      → `excmp verify` passes 32/32. And the honest failure too: 300 KB of
      damage against a 5% record is correctly reported as *"damaged beyond what
      its recovery records can rebuild"* rather than attempted and fudged.
      Default dose is FreeArc's tiering (5% ≤50 MB, 3% ≤1 GB, 1% above), which
      is about what the percentage *costs*: 4% of 10 MB is nothing, 4% of 50 GB
      is 2 GB. Exit codes measured rather than assumed — 0 ok, 1 repairable,
      2 beyond repair, 3 no records.
      **One performance bug worth recording.** `_block_size` originally sized
      to par2's 32768-block *ceiling*, which for a 400 KB archive means 16-byte
      blocks and ~25,000 of them: block count drives the Reed-Solomon work
      almost linearly, and the recovery tests took **284 seconds**. Sizing for
      ~2000 blocks with a 4 KiB floor took that to **7 seconds** — a 40×
      speedup, and the same win applies to real archives.
- [x] F4. ✅ **DONE 2026-09-03** — `excmp/motw.py`, wired into `extract()`.
      The archive's `Zone.Identifier` is copied onto every file extracted from
      it, so an executable that arrived from the internet does not land looking
      like one the user wrote themselves. **Default on**, where 7-Zip's CLI
      needs `-snz`: a downloaded archive is the ordinary case, and the safe
      behaviour should not be the one you have to know a switch for.
      Direct ADS file I/O, never a shell — PeaZip shipped a
      PowerShell-injection CVE doing this exact job by shelling out, and the
      filename here is attacker-controlled. A test **parses the module** and
      fails if it imports `subprocess`/`os` or calls anything that spawns a
      process. (A first version grepped for the word and flagged the docstring
      explaining why it is absent.)
      Propagation always overwrites, which is the CVE-2025-0411 case: an
      archive that smuggles its own `Zone.Identifier` must not downgrade the
      file to "local". Read capped at 32 KB, directories skipped, and a write
      failure is ignored — FAT32 has no streams and a USB stick is not an
      error condition.
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
- [x] G2. ✅ **DONE 2026-09-01** (branch `phase-g2-foreign-listing`, measured in
      [benchmarks/2026-09-01-g2-foreign-listing.md](benchmarks/2026-09-01-g2-foreign-listing.md)).
      `excmp/slt.py` parses the pinned grammar, `engine.list_any()` is the
      foreign-capable twin of `list_archive()`, and `extract_selected()` pulls
      single members out of either kind. **38,496 entries listed across 19 real
      archives in 21.3 s.** 552 tests pass (was 469).
      **Five things the implementation corrected against the plan:**
      1. **The dummy `-p` was fixing a bug that had already shipped, not
         hardening a new path.** `_extract_foreign()` passed no `-p` at all, so
         an encrypted archive dropped on the Extract tab froze the running app
         on a prompt with nowhere to appear. Measured: **still running after
         8.0 s** without the guard, **exit 2 in 0.22 s** with it. Four of the
         nineteen archives in the real corpus have encrypted headers, so this
         was reachable by dropping a file the user already owns.
      2. **`communicate()` hides the hang.** The first measurement showed no
         block, because `subprocess.communicate()` closes stdin and hands
         7-Zip an EOF a real parent never sends. Reproducing it needs stdin
         held open. A timeout alone is not enough either — the deadline can
         only be enforced from a watchdog thread, since a tool blocked on a
         prompt never returns from the read loop to be checked.
      3. **`list_archive()` had to stay `.excmp`-only.** Widening it in place
         looked obvious and would have put a `7z.exe` launch on the GUI thread
         for every dropped file, because `ExtractTab._suggest_destination()`
         calls it synchronously on every drop. The `extract`/`extract_any`
         split already existed for a different reason and turned out to solve
         this one too.
      4. **`.msi` is not one format, and the difference is 20x.** 7-Zip reports
         `cab` for some and `compound` for others; a 371 MB `compound` MSI took
         **7.14 s** to list against 0.27 s for a 20 MB `cab` one. Seven seconds
         on the GUI thread is a freeze, which is what makes the worker thread
         load-bearing rather than tidy.
      5. **A packed size of 0 is a lie.** 7-Zip leaves `Packed Size` *empty*
         for every member of a solid block after the first, so `int` could only
         say "0 bytes" about files that had no individual figure. Carried as
         `int | None` — the same "a number that could mean two things needs a
         companion" lesson as `ledger_backed`. Caught by looking at the output,
         not by a test.
      **Deliberately not done:** an in-app archive *browser* tab (that is I2);
      this is the listing surfaced on the Extract tab where the archive is
      already chosen. Original item:
      **Archive browser / `excmp list`** — parse `7z l -slt` for foreign archives;
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
- [x] G3. ✅ **DONE 2026-09-02** — split volumes (`excmp/volumes.py`,
      `compress --split 100m`, and `extract` auto-joins when handed a `.001`).
      Pure-Python chunking as planned: parts are `<archive>.001`, `.002`, …,
      zero-padded so a lexical sort *is* the join order, capped at 999 because
      `.1000` would sort before `.101` and silently reorder the archive. The
      container is untouched — join first, then the ordinary reader runs — so
      a split archive is not a second format to reason about, and the split
      happens only **after** the D9 gate has published, because splitting an
      unverified archive just produces several unverified files.
      Per-part SHA-256 goes in a `.sha256` sidecar in `sha256sum` layout. It is
      a convenience, not a correctness requirement: joining works without it,
      and it exists so a failed transfer can name *which* part to re-fetch.
      Verified end-to-end: 22.5 MB of executables split into 2 volumes, whole
      archive deleted, rejoined from the parts alone — **32/32 byte-identical**.
      **Two bugs found while building it.** (1) `part_paths` originally stopped
      at the first gap, so a missing middle volume looked identical to a set
      that simply ended there and we would have joined a truncated archive; it
      now scans to the highest number present and names the hole. (2) **The G6
      sidecar had never been checkable with `sha256sum -c`** — `write_text`
      emits CRLF on Windows, so the trailing `
` became part of the filename
      and every line failed with "No such file or directory". A feature whose
      entire purpose was that one command, shipped broken. Both sidecars now
      pass `newline="
"`, with a test asserting no CRLF.
- [x] G4. ✅ **DONE 2026-09-02** — `compress --format 7z|zip` writes a plain
      archive with no container (`engine.compress_standard`). Verified for real:
      a `.zip` opened by Python's own `zipfile` (15 entries, `testzip()` clean)
      and a `.7z` that `7z t` accepts, 75.22% on executables.
      **It reuses `SevenZipStage`** rather than reimplementing anything, so the
      output path staying last, the password redaction and the progress parsing
      all come free; only the container type differs. That needed a real
      `archive_type` parameter — appending `-tzip` to `extra_args` beside the
      baked-in `-t7z` makes 7-Zip exit 7 with "Multiple instances for switch",
      and `-mqs`/`-mf` are 7z-format concepts that make it refuse a zip outright
      with "The parameter is incorrect", so both are now gated on the type.
      **The honesty is the feature.** A standard archive has no ledger, so
      nothing can re-verify it later — but it is still extracted and hashed
      against the originals *before* publication, exactly like the `.excmp`
      path, and nothing is written if that fails. `StandardResult.has_ledger`
      and `.note` exist so the caller says which half of the guarantee it has
      rather than implying both.
- [x] G5. ✅ **DONE 2026-09-03** — `excmp/convert.py` and `excmp convert`.
      Extracts any archive 7-Zip can open, analyses the *contents*, runs the
      pipeline, and reports. Measured on a real 8.9 MB zip of executables:
      **8.5 MB → 5.5 MB, 35.2% smaller**, source untouched.
      The signature part is the verdict. Recompressing archives is not new; our
      planner already knows *why* each file was stored, so a conversion that
      gained nothing says so in a sentence instead of leaving two numbers to
      compare. Reasons collapse by cause ("31 files: already compressed")
      rather than listing every file.
      **The source archive is never touched** — not moved, not deleted, not on
      success. The staging copy is the size of the whole archive and is removed
      in a `finally`, because leaving it would cost the user that space twice.
      **One thing measuring corrected:** a 940-byte zip converts *larger*,
      because the per-file SHA-256 ledger is fixed overhead. The tool correctly
      says "no smaller, keep the original" — the first version of that test
      asserted an improvement and was wrong about small archives, not about the
      feature.
- [ ] G6. **Transport-integrity sidecar** — emit a `.sha256` for the container itself
      (and per split volume) + `excmp verify --transport`. This is the maintained
      equivalent of the one verification habit repack users already have
      (`fitgirl-bins.md5` + QuickSFV)
- [ ] G7. **RAM-limited extraction mode** — mirror FitGirl's "limit to 2 GB" option:
      cap dict/window/threads and spill to temp when RAM is short, because archives
      get extracted on weaker machines than they were created on
- [ ] G8. Hash tool (`excmp hash`, stdlib hashlib) — cheap credibility, fits the brand
- [x] **G9. ✅ DONE 2026-09-02** — deduplicate stored files against the ledger.
      Measured in [benchmarks/2026-09-02](benchmarks/2026-09-02-b1-zpaqfranz.md):
      on the 49%-duplicate corpus, Extreme went **5.22% → 51.08% saved
      (+45.86 points)** and Insane **5.21% → 51.06%**, 5/5 byte-identical, and
      marginally *faster* because writing one copy of a 23.8 MB file beats
      writing two. For scale, B1 moved that same corpus by −0.02 points.
      **The duplicate-file win was never in the compressor** — it was in the
      store route, which copies identical high-entropy files verbatim where no
      deduplicator can see them.
      Implementation: `write_container` groups stored entries by the SHA-256
      the ledger already carries, writes the first, and gives the rest a
      `same_as` pointer; `extract_stored` gains a second pass that reads the
      source **from the zip** (not from disk, so selective extract still
      works) and writes every duplicate out in full. `verify_restore` needed
      **no change at all** — it re-hashes the restored file on disk, which is
      exactly what makes this safe.
      Four hostile cases are refused and tested: a `same_as` cycle, a chain of
      more than one hop, a pointer outside the ledger, and a pointer whose
      ledger hash or size disagrees with the target's. Chains are refused
      rather than bounded, which is what makes a cycle impossible instead of
      merely survivable. A file with an empty `sha256` is never deduplicated:
      "we do not know" is not a statement about equality.

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
free-disk preflight, and `tools/estimate_report.py`. **290 tests pass** (was 223).
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
10. **Headless rendering is not GUI QA.** The table passed 9 pytest-qt tests and
   was only ever rendered on Qt's offscreen platform, which draws every glyph as a
   tofu box unless `QT_QPA_FONTDIR` is set — something `tools/shots.py` has always
   done and which went unread. Rendered with real fonts, four copy and layout
   defects were obvious in seconds and **none was reachable by a unit test**: the
   same warning printed three times in one panel, the recommendation reason printed
   twice (the preset cards already print it), the planner's log sentence leaking
   into the UI verbatim (`"insane: zpaqfranz backend not integrated yet - using
   extreme chain"`), and a collapsed range restating the value above it. Fixed in
   `5675c90`; `docs/images/` regenerated and the shot window raised to 1010 px so
   the panel is in frame. **Run `python tools/shots.py` and look at the output
   before calling any GUI change done** — it is the cheapest QA in this repo.

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
- [x] J5. ✅ **DONE 2026-09-03** — `gui/prefs.py`. The profile chosen for each
      dominant content type is remembered in QSettings and offered on the next
      folder of the same shape. **It suggests; it never overrides** — a
      remembered choice that silently outranked the analyser would make the
      recommendation unpredictable, which is worse than an occasional extra
      click. Once the user picks for themselves, `_profile_touched` stops the
      re-suggestion for that drop, and `select()` defaults to `emit=False` so
      offering a profile is not mistaken for choosing one. A hand-edited
      QSettings value is discarded rather than trusted: it costs the
      preference, never the app. The I1 dependency was already satisfied —
      QSettings landed with wave 3c.
- [x] J6. ✅ **DONE 2026-09-03** — `suggest.long_job_warning()`, shown on the
      existing inline banner. Past 45 minutes the estimate is stated in words
      somebody can act on: *"about 3 hours on this machine - worth starting
      before you step away, or leaving to run overnight."*
      The comparison table already made the *relative* cost visible, which was
      J3's job; this makes the absolute one visible, because "about 3 hours"
      means something to a person that "0.842 MB/s" does not. Phrased in
      minutes below 90, hours above.
      `ComparisonRow` gained `time_seconds` so the decision is made on the
      number rather than by re-parsing the formatted string - a formatting bug
      waiting to happen otherwise. **Inline, never a modal**: a test parses
      `mainwindow.py` and fails on any `QMessageBox` call, so the I9 rule
      cannot be broken again by accident.
- [x] J7. ✅ **DONE 2026-09-03** — `excmp/calibrate.py`. Every finished job
      records its real `piped_bytes / elapsed` **per resolved chain**, and
      future estimates blend that with the shipped defaults as the cold-start
      prior (EMA, alpha 0.25). Qt-free, so the CLI and the GUI feed one JSON
      store and `excmp/` keeps its independence from Qt.
      **Measured convergence** on a machine 2.5x slower than the shipped
      constant: a 500 MB job is predicted at 2.6 min cold, 3.0 after one job,
      5.9 after ten, and **6.4 after twenty-five against a true 6.4** —
      without ever lurching, which is the property the EMA exists for.
      Also learns `codec_factor`, which is the only real fix for the J1 note-3
      blind spot: no cheap probe can predict what Precomp will find, so
      watching what it actually achieved is the only thing that can.
      Three guards, each about not making the estimate *worse*: samples under
      8 MiB are ignored (they measure process startup, not throughput), a rate
      more than 100x from the prior is dropped as a clock artefact or a cached
      read, and a corrupt or unwritable store costs the learned rates and
      nothing else.
      **One thing the implementation corrected:** the first version replaced
      the rate outright on the first sample. That is not what "cold-start
      prior" means - it throws away everything the defaults encode on the
      strength of one job. It now blends from sample one.
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
| ~~UI-1~~ | ~~UI v3 wave 1 (screen fit, merged chooser, action bar, registry, WCAG, fit gate)~~ | ✅ done, merged | all 13 items of research/23 §7; the 1366×768 gate pins the fix |
| ~~UI-2a~~ | ~~UI v3 wave 2a (Activity tab + status strip, compact results, queue density, scan progress, Banner/I9)~~ | ✅ done, merged | W2-1/3/7/8/9. Populated Compress page 869→748px, last `QMessageBox` gone, scan silence 4.7s→0.3s on the real HDD tree. Also fixed the tests' missing `QT_QPA_FONTDIR` — every prior height gate had been measuring tofu |
| ~~UI-2b~~ | ~~UI v3 wave 2b (compaction, token sweep, Fluent SVG icons, dark title bar, pending-items list)~~ | ✅ done, merged | W2-4/5/6/10 + intake chip, analysis-card collapse, chooser diet. Populated page 748→415px; the empty page fits 150% for the first time. ≤300px is unreachable without dropping a profile row, the analysis card, or the 32px touch floor — recorded as a strict xfail, not silently dropped |
| ~~4~~ | ~~B11 + D9 (drop SREP; make the self-test replay the chain)~~ | ✅ done | the chain is SREP-free and nothing publishes without a verified restore — four clean Extreme round-trips on real corpora |
| ~~UI-3a~~ | ~~UI v3 wave 3a (verify verb + button, `excmp hash`)~~ | ✅ done, merged | The D9 gate became public: same code path, three callers. Catches a single flipped byte in a 721 MB archive and names the file |
| ~~UI-3b~~ | ~~UI v3 wave 3b (G1 foreign archives, I2-lite listing)~~ | ✅ done, merged | Opens zip/7z/rar/iso/…, and shows the ledger — size, SHA-256, route and *why stored* — without extracting. `ledger_backed` keeps the verified restore distinguishable from the best-effort one |
| ~~UI-3c~~ | ~~UI v3 wave 3c (`.sha256` sidecar, Settings + persistence, autosubfolder, first-run notice)~~ | ✅ done, merged | Sidecar is **opt-in and remembered** (decided 2026-08-07). The app persists preferences for the first time — it kept only window geometry before. Settings also hosts the tool inventory the status strip elides |
| ~~UI-4~~ | ~~Level/dict knobs + RAM column + Parameters line~~ | ✅ done | `excmp/ram.py` implements 7-Zip's own peak-RAM formula (doc 19 §3), clamped to the input the way `reduceSize` does. B9's cap drives the dictionary menu; the Parameters line is an allowlist |
| ~~G2~~ | ~~Foreign archive listing (`7z l -slt`) + password-on-demand + selective extract~~ | ✅ done | 38,496 entries across 19 real archives in 21.3 s. Also fixed a shipped hang: `_extract_foreign` passed no `-p`, so an encrypted archive froze the running app — four of the nineteen real archives would have triggered it |
| **3b** | **J5-J7 (per-type memory, long-job confirm, self-calibration)** | **1 session** | **finishes Phase J** |
| 6 | D1-D3, D7 (QA core + CI) | 1-2 sessions | locks in the integrity guarantee before adding stages |
| 7 | B1-B3 + B9-B10 (zpaqfranz, JPEG/PNG, RAM caps) | 1-2 sessions | completes Insane; B9 is one-line arg changes with real payoff |
| 8 | E1-E2 (downloader + notices) | 1 session | unblocks every remaining specialist (par2, xtool, FFmpeg) |
| **9** | **B6 (xtool + Oodle) + B8 (re-benchmark)** | **3-4 sessions** | **the real FitGirl gap on modern AAA games — the single biggest competitive deficit.** Moved up from 11 on 2026-09-01: the "needs E1 first" dependency is soft (tools degrade gracefully already), and nothing justifies shipping encryption and settings polish ahead of the one thing we measurably lose at. **Read the audit note on B6 before starting — the DLL-bootstrap design flaw must be fixed first or the archives only restore on the machine that made them.** B8 is paired because nothing currently validates the 5-15% vs 50-70% claim; both figures are `(est.)` in doc 09 |
| 10 | I1-I2 (settings/persistence + archive browser) | 1-2 sessions | I1 already shipped in wave 3c; this is the browser tab |
| 11 | F1-F3 (encryption + recovery records) | 2-3 sessions | table-stakes "secure"; F3 is the WinRAR feature nobody OSS has |
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
