# 🚦 START HERE — handoff for the next session (written 2026-07-31)

> **Read this file first, then `docs/ROADMAP.md`.** This session was
> research-and-planning only — **no production code was written or intended.**
> Everything below is decided, verified, and ready to implement.

---

## 1. State of the repo right now ⚠️ READ THIS

The project folder was renamed this session from
`ExtremeCompressor (Application running and successfully got the output but the didnt complress video file size)`
to **`ExtremeCompressor`** (to stop hitting Windows path-length limits). That rename
broke both git worktree registrations; **they have been repaired** — `git worktree
list` is clean and no longer shows `prunable`.

All new documentation now lives in the **main checkout on `main`**, and is
**uncommitted** (the session was asked not to commit). A **second research
round on 2026-07-31** (the source-code study) added docs 13-21:

```
 M docs/ROADMAP.md
?? docs/NEXT-SESSION-START-HERE.md      <- this file
?? docs/research/08-archiver-product-features.md
?? docs/research/09-fitgirl-installer-and-comparison.md
?? docs/research/10-security-and-integrity.md
?? docs/research/11-ui-v2-plan.md
?? docs/research/12-lightweight-and-performance.md
?? docs/research/13-source-study-xtool.md            <- source-study round
?? docs/research/14-source-study-nanazip.md
?? docs/research/15-source-study-precomp.md
?? docs/research/16-source-study-innosetup.md
?? docs/research/17-source-study-peazip.md
?? docs/research/18-source-study-freearc-par2.md
?? docs/research/19-source-study-7zip.md
?? docs/research/20-source-study-lrzip-zpaqfranz.md
?? docs/research/21-source-study-synthesis.md        <- read this one first
?? docs/research/22-feature-parity-master.md         <- the all-in-one feature map
```

**First actions for the next session:**

1. **Commit these docs** (branch first if you follow the "don't commit to main"
   convention). Remember: **no `Co-Authored-By` and no "Generated with Claude Code"
   in the commit message** — the user's standing rule for all portfolio repos.
2. The two worktrees (`compression-tool-research-0b8a5d`, `pyside6-gui-phase-a-f8af25`)
   are now redundant — identical copies of the earlier docs also exist in the
   research worktree. Safe to `git worktree remove` both once the docs are committed.
   (Note: the source-study docs 13-21 were written from a **third** worktree,
   `extremecompressor-research-plan-5f5cdb`, straight into the main checkout.)
3. Read, in order: `docs/research/21-source-study-synthesis.md` (the read-me-first
   for the whole source study) → `docs/ROADMAP.md` →
   `docs/research/10-security-and-integrity.md` (the real bug to fix) → the
   specific source-study doc (13-20) for whatever phase you're starting.

---

## 1b. The source-study round (2026-07-31, second research session)

The user asked for a genuine line-by-line source study: *"download all the
source codes, pull and extract all the information you can, and include the
best parts in our application."* Eleven repos were shallow-cloned to a
scratchpad (throwaway, nothing committed from them) and eight were deep-read at
pinned commits by dedicated study agents. Output = **docs 13-21** above.

**Read `docs/research/21-source-study-synthesis.md` first** — it is the
read-me-first that lists the five findings that change the plan, the six stale
facts it corrected, and every roadmap delta (all of which are now folded into
`docs/ROADMAP.md`). The headline changes:

- **B6 (xtool):** restore = recompress, so the game's `oo2core` DLL is part of
  the archive contract — pin its SHA-256 in the manifest.
- **Cross-cutting wrapper rules:** 7z needs `-bsp1` or it prints no progress
  piped; xtool/Precomp progress is unparseable piped; **Precomp `exit(0)`s even
  on fatal restore failure** — so our post-restore SHA-256 compare is the
  acceptance gate for every stage.
- **H1 (installer):** a byte-identical stub is real only as
  frozen-script→compile-once→sign-once→cache; recompiles don't hash identically.
  Inno's ISSig gives payload integrity with zero per-archive bytes in the exe.
- **Long-range dedup:** lrzip rejected (GPL + POSIX-only); zpaqfranz (B1) is our
  unlimited-distance answer; `zstd --long`/7z big-dict cover ≤2 GB.
- **Encryption (F1):** the "why not `7z -p`" argument is now source-proven
  (empty salt, AES-CBC + CRC32, 2^19 SHA-256) — no design change.
- **Corrections:** mx9 default dict is 256 MiB (not 64) since 24.09; 7z solid
  type-sort is OFF without `-mqs`; BCJ gains are benchmark-derived, not
  source-backed.

**License posture (source-verified):** we copied **no** non-MIT code. FreeArc/
PeaZip/lrzip/7-Zip gave designs and parameter tables only; xtool/zpaqfranz/
Precomp are subprocess binaries; Inno Setup is invoked, not linked. Repo stays
MIT-clean for SignPath (E4).

**Where the studied source lives:** ALL eleven studied repos (xtool, NanaZip,
zpaqfranz, Precomp, Inno Setup, 7-Zip, PeaZip, FreeArc orig+next, lrzip,
par2turbo) are kept as shallow clones at
**`C:\Users\nuhaa\PycharmProjects\ExtremeCompressor-refs\`** (~229 MB, outside
the git repo on purpose — never vendor anything from it into the MIT tree).
Its `README.md` maps each repo → studied commit → license → what we may
legally do with it (keeping/studying GPL code is unrestricted; the only
restricted act is copying/translating GPL/LGPL source text into the MIT repo).
Every study doc also pins the repo URL + commit, so re-cloning is one
`git clone --depth 1` away.

**Flagging pass (done, same day):** all stale claims in the earlier docs were
flagged inline as `[SOURCE-STUDY …]` with pointers into docs 13-21 — docs 02
(xtool/zpaqfranz license corrections, SREP chain), 04 (BCJ2 %, dedup verdict),
06 (BCJ2, SREP, zpaqfranz), 09 (SREP fallback retired), 10 (encryption claims
source-proven, MOTW implementation, SREP), 11 (srep tool-path), 12 (threads
wording, mx9 256 MiB dict, exact RAM formula, SREP rows historical) — plus the
ROADMAP's remaining SREP mentions (E1/E2/E4/H5, order table).

## 2. What the FIRST session produced (docs 08-12)

**Five new research documents** (all facts live-verified on 2026-07-31, versions and
licenses checked against upstream, not recalled from memory):

| Doc | Contents |
|---|---|
| `docs/research/08-archiver-product-features.md` | Feature audit of 7-Zip 26.02 / PeaZip 11.2 / NanaZip / FreeArc / WinRAR / Bandizip; the legal route for each feature in Python; what RAR support legally requires; the minimal set that makes us "a real archiver"; explicit skip-list with reasons |
| `docs/research/09-fitgirl-installer-and-comparison.md` | The FitGirl **installer** stack (Inno Setup, ISDone.dll, unarc.dll, CLS plugins, xdelta, run.exe); why installs take 30-120 min; RAZOR / lolz / xtool 2026 status; what actually makes repacks small; **the honest head-to-head table**; installer-output design + the SmartScreen rule |
| `docs/research/10-security-and-integrity.md` | ⚠️ **A confirmed vulnerability in our own reader**; why 7z `-p` is the wrong encryption route (with evidence); the Argon2id + chunked AES-256-GCM design; par2 recovery records; safe-extraction hardening; supply chain; AV/SmartScreen posture |
| `docs/research/11-ui-v2-plan.md` | Current GUI state read from code (incl. "persists nothing" and one modal-dialog rule violation); competitive scan; prioritized Tier 1/2/3 UI v2 plan with effort estimates |
| `docs/research/12-lightweight-and-performance.md` | **Measured** package sizes (122 MB → 71 MB / 28 MB zip), RAM formulas per tool, per-profile RAM/thread budgets for 2C/4T-16GB, startup timings, verified tool fleet table (~15 MB total), FreeArc concepts worth copying |

**`docs/ROADMAP.md` rewritten** with four new phases and corrections to existing ones:

- **Phase D0 — security hotfix (DO FIRST)**
- **Phase F — "Protect"**: encryption + recovery records
- **Phase G — "Real archiver"**: open/browse foreign archives, split volumes, export, convert
- **Phase H — Installer-style output** (the FitGirl-shaped feature)
- **Phase I — UI v2**
- New items **B9/B10** (RAM caps + JPEG-via-wheel correction), and E1/E2/E3/E4
  rewritten with measured numbers and 2026-verified facts
- A **12-step suggested order** and a section answering the FitGirl question directly

---

## 3. 🚨 The one thing that must happen first: Phase D0

Research read our own code and found an **exploitable path-traversal bug**:

`extract_stored()` in `excmp/manifest.py` (~lines 107-122) builds
`target = out_dir / rel` from the **raw zip entry name** and writes it with no
sanitization. A malicious `.excmp` containing an entry like
`stored/..\..\..\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\evil.bat`
— or an absolute path, a drive letter, or an NTFS alternate-data-stream name like
`stored/x.txt:payload` — **writes outside the destination directory**. The manual
`zf.open()` + write loop bypasses `ZipFile.extract()`'s built-in sanitizer.

Weaker adjacent issues: `read_container()` trusts `manifest.payload_name`;
`verify_restore()` in `excmp/verify.py` joins untrusted ledger keys (read-only, lower
risk). There are also **no decompression-bomb bounds** anywhere.

Good news: `excmp/stages/tarstage.py` already uses `extractall(dst, filter="data")`,
which is correct — it just needs a regression test so nobody removes it.

**Fix = D0.1-D0.5 in the roadmap.** One shared path sanitizer + malicious-archive
tests + ledger-bounded extraction. The manifest already declares every file's exact
size and hash, so the bomb defense is nearly free. This is ~1 session.

---

## 4. Direct answers to the questions asked this session

**Q: "Is ours more powerful and more highly compressible than the FitGirl method?"**

Not uniformly more compressible — but broader in scope and far more trustworthy:

- **Old zlib-era games**: already in their league (we measured 72.4% saved on the
  synthetic repack-style corpus; their class is 60-75%).
- **Modern Oodle/zstd AAA games**: **we lose badly today** — roughly 5-15% vs their
  50-70% — because Precomp cannot open Oodle streams. Phase B6 (xtool driving the
  game's *own* `oo2core*.dll`) closes most of the gap. What stays permanently out of
  reach: the **lolz** codec (~5-10%, closed, no license, zero legal path) and
  **per-game manual tuning** (hours of human craft per title — structurally
  unavailable to an automatic tool).
- **Anything that isn't a game**: we're simply better — they don't route by file type.
- **Trust/safety**: we win everywhere. Per-file SHA-256 ledger + full chain replay vs
  their CRC32 + an optional user-run MD5 batch file; a maintained legal stack vs
  2014-era abandoned DLLs; inputs never modified and bounded RAM vs "set a 16 GB
  pagefile and disable your antivirus."

They optimize **one number** (download size of one hand-tuned game). We optimize a
**contract** (anything in → smallest honest size → verified bit-exact restore).
Full table with every estimate flagged: `docs/research/09`.

**Q: "Did you compare the open-source tools' source code, and FitGirl's tools?"**

Partly, and deliberately so — here is the precise scope, because it matters legally:

- **Our own source: yes, read directly.** `excmp/manifest.py`, `verify.py`,
  `stages/*.py`, `gui/*` — that's how the vulnerability, the missing `QSettings`, the
  `threads=4` default, and the module-level `comtypes` import were all found.
- **Their source: studied at the level of documented behavior, CLI surface, licenses,
  changelogs, and format/algorithm documentation — not copied, and not line-by-line
  ported.** That was the right call rather than a limitation:
  - **PeaZip** is LGPLv3 **Free Pascal** — cannot be reused in an MIT Python codebase.
  - **FreeArc** is **GPL and dead since ~2016** — same problem, plus it's a dead end.
  - **7-Zip** is LGPL **C++** — and we don't need its source: we already drive
    `7z.exe` as a subprocess, which is what gives us ~40 read formats (including RAR)
    with **zero license obligations**.
  - **NanaZip's own code is MIT** (legally readable, and named as the reference for
    the Win11 context-menu implementation), but it's C++ — reuse is conceptual.
  - **FitGirl's tools**: **lolz** and **RAZOR** have *no public source at all* and no
    license (lolz binaries only circulate inside scene toolkits; RAZOR is a
    "non-commercial DEMO"). **ISDone.dll/unarc.dll** are 2014 Delphi with mixed
    licensing. **xtool** *is* MIT on GitHub (archived 2023, v0.7.9) — that one we can
    legitimately use as a binary stage, which is exactly Phase B6.
  - What we extracted instead: **architecture and ideas** — FreeArc's `arc.ini`
    per-type dispatch and its recovery record, PeaZip's keyfile-2FA and command
    palette, the ISDone error taxonomy (which became our installer preflight checks),
    and the FitGirl `setup.exe + fg-*.bin` layout (which became the SmartScreen rule).
    **Ideas aren't copyrightable; code is.** Keeping the repo 100% MIT-clean is also a
    hard prerequisite for free SignPath code signing (E4).
  - If you want a genuine line-by-line source study next session, the two candidates
    worth it are **xtool** (MIT, Delphi — to understand its stream-database format)
    and **NanaZip** (MIT, C++ — for the `IExplorerCommand` context-menu pattern).
    Everything else is either license-blocked or better consumed as a CLI.

**UPDATE (source-study round, same day):** that line-by-line study was then
actually done — and broadened to **eight** repos, not two. See docs 13-21 and
§1b above. Bottom line: xtool's stream-database format and restore-by-recompress
model, NanaZip's exact IExplorerCommand + AppxManifest recipe, PeaZip's `-slt`
parser and keyfile construction, 7-Zip's encryption internals and path
sanitizer, FreeArc's dispatch grammar and the PAR2 confirmation, Precomp's
preflate/verify model, Inno's byte-identical-stub mechanics, and the
lrzip-vs-zpaqfranz long-range verdict are all now documented with file:line
citations. **No non-MIT code was copied** — designs and parameters only.

---

## 5. Decisions already made — do not re-litigate

| Decision | Why |
|---|---|
| **Never bundle**: SREP, lolz, oo2core/Oodle DLLs, unrar.dll, xtool Patreon builds | No license / proprietary / breaks the MIT-clean requirement for SignPath signing |
| **Encryption: our own layer, not `7z -p`** | 7z has an empty salt by default, no AEAD (CRC32 only), a GPU-friendly KDF, and would leave `manifest.json` + `stored/` files in plaintext |
| **par2cmdline-turbo for recovery records** (GPL, subprocess only, downloaded) | Real Reed-Solomon; FreeArc's XOR `-rr` was self-documented as weaker than RAR's |
| **Stay on PySide6 Widgets; no QML, no Fluent-Widgets** | Fluent-Widgets is GPLv3+commercial — incompatible with MIT. Use Qt 6.5 `QStyleHints.colorScheme()` for the modern feel, free |
| **`--onedir`, never `--onefile`; never UPX; no SFX in v1** | Self-extraction and packing are AV heuristics magnets, and onefile re-extracts to temp on every launch |
| **Generated installers must use a byte-identical signed stub + sidecar payload** | SmartScreen reputation is per-file-hash — a uniquely-generated unsigned exe is flagged forever |
| **RAR: extract only, forever** | Creating RAR is legally impossible; the unRAR license forbids re-creating the compressor |
| **Skip**: file manager, password manager, secure delete, update-in-place | Scope creep or (for secure delete on SSDs) actively dishonest |
| **Default threads → 2, not 4** | Verified: 7-Zip x9 uses 2 threads per chunk; more just splits the stream and costs RAM on a 2-core CPU |
| **Lossless-first stays non-negotiable; lossy always opt-in** | The product's identity |
| **No lrzip, ever** (source-study round) | GPL *and* hard-POSIX (mmap/mremap, zero Windows path); fails both license posture and Windows-first bar. zpaqfranz (B1) is the unlimited-distance dedup answer instead |
| **Post-restore SHA-256 compare is the acceptance gate for every stage** | Precomp `exit(0)`s on fatal restore failure; xtool/Precomp don't verify every path — tool exit codes cannot be trusted (doc 15, doc 13) |
| **B6 manifest must pin the oo2core DLL hash** | xtool restore = recompress; wrong DLL version = broken restore, and Oodle has no patch fallback (doc 13) |
| **par2cmdline-turbo confirmed for recovery records (F3)** | Source-checked against FreeArc's own ECC redesign — PAR2 already is that design; nothing OSS/Windows/MIT-clean beats it (doc 18) |
| **MOTW propagation via direct ADS I/O, never PowerShell** | PeaZip shipped a PowerShell-injection CVE doing exactly this (doc 17); direct `open(path+":Zone.Identifier")` is ~40 lines (doc 14) |

---

## 6. Suggested first prompt for the next session

Copy-paste this:

> Continue ExtremeCompressor. Read `docs/NEXT-SESSION-START-HERE.md` first, then
> `docs/research/21-source-study-synthesis.md`, `docs/ROADMAP.md`, and
> `docs/research/10-security-and-integrity.md`.
>
> Step 1: commit ALL pending docs changes shown by `git status` — the new research
> docs (`docs/research/08-22`), the source-study-flagged older docs
> (`docs/research/02/04/06/11/12`), the updated `docs/ROADMAP.md`, and this handoff
> doc — **no AI attribution in the commit message**.
> Then remove the two now-redundant worktrees.
>
> Step 2: implement **Phase D0** (the security hotfix) using TDD — write the failing
> malicious-archive tests first, using the **source-pinned test matrix in D0.2**
> (`..`, absolute, drive letters, UNC, `\\?\`, NTFS ADS `name:stream` and
> `:$DATA`, reserved device names incl. `NUL.txt`, trailing dot/space, control
> chars, RLO `U+202E`, symlink escapes). Then the shared path sanitizer used by
> `extract_stored()`, `read_container()` and `verify_restore()`, then
> ledger-bounded extraction plus the hostile-tar regression test that pins
> `filter="data"`. Run the full suite (90 existing tests + the new ones) and commit.
>
> (User's preferred pace: **one phase per session, little by little.** Stop after
> Step 2 — Phase G1-G2 is deliberately deferred to its own future session, using
> the pinned `-slt` parser grammar in G2 with a dummy `-p` + `-bsp1`.)

### Later sessions, in roadmap order

- **G1-G2** — open/browse foreign archives (the "stop being one-way" milestone)
- **D1-D3, D7** — property-based roundtrips, edge-case matrix, crash-consistency, CI
- **B1-B3, B9-B10** — zpaqfranz, JPEG/PNG specialists, RAM caps, threads→2
- **E1-E2** — the SHA-pinned tool downloader (unblocks everything else) + notices
- **I1-I2** — settings/persistence + archive browser UI
- **F1-F3** — encryption (Argon2id + chunked AES-256-GCM) + par2 recovery records
- **B6** — xtool + Oodle: the real FitGirl gap on modern games
- **C** — opt-in video/audio Shrink mode
- **H** — installer-style output (needs E4 signing first)
