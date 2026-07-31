# 22 — Feature-parity master: every studied feature → our own implementation

> **The "all-in-one powerful tool" map.** One row per capability found in the
> studied tools (7-Zip, PeaZip, NanaZip, FreeArc, WinRAR, Precomp, xtool,
> zpaqfranz, lrzip, Inno Setup / the FitGirl stack). For each: how they do it,
> how **we** do it — *our own way, in Python, often faster or structurally
> better, never their code* — and which roadmap phase ships it.
>
> Standing rule (user-confirmed 2026-07-31): **use the GPL/LGPL tools, never
> copy their code — take the idea and achieve the same function differently.**
> Sources: feature audit (doc 08) + source studies (docs 13-21). Phases refer
> to `docs/ROADMAP.md`.

Legend: ✅ = shipped · 🔜 = planned, phase noted · ⛔ = deliberately skipped
(reason recorded).

## 1. Core archiver features

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Extract 40+ foreign formats (zip/7z/rar/tar/iso/cab/msi/wim/vhd…) | 7-Zip handlers (C++) | Magic-byte detect → drive `7z.exe x` (subprocess; RAR read comes free, zero license obligations) | 🔜 G1 |
| Browse/list before extract | 7z GUI / PeaZip list | Parse `7z l -slt` with the pinned grammar (doc 19 §6) + dummy `-p` hang-guard (doc 17 §4); for `.excmp` the manifest read is FREE and richer: size + SHA-256 + route + *why* per file | 🔜 G2 + I2 |
| Integrity test | `7z t`, zpaqfranz `t`/`v` | `excmp verify`: full chain replay + per-file SHA-256; deep-verify models zpaqfranz's `t` + `v -ssd` split (doc 20 §6) — ours checks *both* archive rot and source drift | 🔜 D5 (basic ✅) |
| Split volumes | `7z -v100m`, .pea chunks | Pure-Python chunking with **per-part SHA-256** (PeaZip's per-volume tag idea, doc 17 §2) + auto-join on extract | 🔜 G3 |
| Standard-format export (.7z/.zip) | native | "Compatible output" checkbox → run only the 7z stage, skip the container | 🔜 G4 |
| Archive conversion | PeaZip convert | "Convert & shrink" as a **mode of Add** (PeaZip's cheap pattern, doc 17 §6) + our analyzer's honesty report on *why* it helped or not | 🔜 G5 |
| Hash tool | `7z h`, NanaZip RHash, zpaqfranz `sum` | `excmp hash` (stdlib) + zpaqfranz-style order-independent global tree hash for one-value equality (doc 20 §10) | 🔜 G8 |
| Update-in-place / file manager / password manager / secure delete / RAR creation | various | ⛔ all five — recorded reasons in doc 08 + ROADMAP (identity, liability, SSD honesty, legality) | — |

## 2. Compression power (the FitGirl-class pipeline, legal edition)

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Per-filetype method dispatch | FreeArc `arc.groups` + `arc.ini` (GPL Haskell) | Our router already does this in Python; adopt the **grammar** (ext→group, group×level→chain, `#` expansion) as a TOML data table (doc 18 §1) | ✅ core; 🔜 refinement |
| Content sniffing overrides extension | FreeArc `-ma` (5×64 KB probes, entropy+LZ vote) | `zlib.compress(probe)` ratio first, mmdet-style voting later (doc 18 §10) — stops "renamed .zip inside .dat" | 🔜 B-series |
| Deflate precompression | Precomp 0.4.8 + preflate | Drive `precomp -cn` with private CWD; **never trust its exit code — our post-restore SHA-256 gate is the acceptance test** (doc 15 §3/§9) | ✅ stage; 🔜 hardening |
| Oodle/zstd/lz4 game streams | xtool (MIT Delphi) + game's own oo2core DLL | Drive `xtool.exe` with exact CLIs from doc 13 §9; pin the DLL's SHA-256 in the manifest (restore = recompress); `.xtl` game-fingerprint DBs as the fast lane | 🔜 B6 |
| Long-range dedup (SREP's job) | srep (closed), lrzip rzip (GPL, POSIX-only) | Two-tier, all-legal: `zstd --long` / 7z big-dict for ≤2 GB distances + **zpaqfranz CDC dedup for unlimited distance** (verdict, doc 20 §4) | ✅ zstd; 🔜 B1 |
| Solid-block file ordering | FreeArc "gerpn" sort, 7z `-mqs` | Pre-sort ourselves with the `(group, ext, similarity-bucket, size, name)` key incl. FreeArc's near-duplicate clustering trick (doc 18 §2, doc 19 §5) — and always pass `-mqs` | 🔜 B-series (S) |
| x86 branch filter | 7z BCJ/BCJ2 auto (only mx≥8+MT) | Force `-mf=BCJ2` explicitly per router decision (doc 19 §4) | 🔜 B7 |
| Maximum-ratio CM mode | zpaq/zpaqfranz -m4/-m5, PAQ | zpaqfranz `-m4 -t2` Insane profile (2-core realistic ceiling, doc 20 §8), 7.15-compatible archives only | 🔜 B1 |
| Specialists (JPEG/PNG/WAV/PDF) | packJPG/brunsli in precomp; PeaZip backends | lepton-jpeg wheel (in-process), oxipng, FLAC 1.5 `-j`, qpdf — each behind the SHA-256 restore gate | 🔜 B2-B5 |
| Per-game hand tuning | FitGirl (hours of human craft) | ⛔ structurally unavailable to an automatic tool — honesty recorded in doc 09 | — |
| lolz codec | closed, no license | ⛔ zero legal path (doc 09) | — |

## 3. Trust & integrity (where we beat everyone)

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Per-file integrity | CRC32 (7z/RAR/FitGirl) | **SHA-256 ledger per file + full chain replay** — already stronger than every studied tool | ✅ |
| Recovery records | WinRAR RR (closed), FreeArc XOR `-rr` (weak, self-admitted) | par2cmdline-turbo sidecars — real Reed-Solomon, source-confirmed as the strongest legal option (doc 18 §5/§9); exact CLIs pinned | 🔜 F3 |
| Extraction safety | 7z/NanaZip/PeaZip sanitizers (each with CVE history) | Union of all three checklists **plus RLO U+202E which 7-Zip misses** — canonicalize-compare-reject with redundant layers (docs 19 §7, 14 §6, 17 §5) | 🔜 D0 ⚠ first |
| Decompression-bomb defense | mostly none | Ledger-bounded extraction (manifest declares exact sizes — bound is nearly free) | 🔜 D0.3 |
| Mark-of-the-Web | 7z 24.09+ (CLI default OFF) | Direct ADS I/O, default ON, skip archive-embedded Zone entries; never PowerShell (docs 14 §5, 17 §5, 19 §8) | 🔜 F4 |
| Crash safety | zpaqfranz append-only transactions | Atomic temp+rename today; adopt append-only transaction framing + tail-trim on open later (doc 20 §10) | ✅/🔜 D8 |
| Tool-fleet trust | PeaZip `checkchash` binary self-verify | SHA-pinned tool downloader (E1) + re-hash before first use + resolved tool+version recorded in each archive (FreeArc alias-pinning idea, doc 18 §10) | 🔜 E1 |
| Subprocess hardening | NanaZip CET/CFG/child-policies | Child mitigation policies + kill-on-close Job on every tool we spawn (doc 14 §3) — 7z.exe needs neither JIT nor children | 🔜 D0.6 |

## 4. Security features

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Encryption | 7z `-p`: empty salt, CBC, no MAC (source-proven, doc 19 §1); PeaZip EAX cascades | Argon2id + chunked AES-256-GCM over the WHOLE container, header as AAD, STREAM nonces — authenticated, memory-hard, no filename leaks (doc 10 design) | 🔜 F1 |
| Keyfile two-factor | PeaZip: base64(SHA256(keyfile)) prefixed to passphrase (separable) | `HKDF-Extract(salt=SHA-256(keyfile), ikm=Argon2id(pw))` — real cryptographic binding, keyfile-only mode, no in-header verifier oracle (doc 17 §1) | 🔜 F2 |
| Hidden filenames | 7z `-mhe=on` (still leaks sizes/KDF params) | Everything inside the encrypted envelope incl. manifest — plus we document what *any* format still leaks (honesty) | 🔜 F1 |
| Password strength meter | PeaZip's entropy scorer | Reimplement the scoring rules (or zxcvbn) — 20 lines (doc 17 §3) | 🔜 F-series |

## 5. Installer-style output (the FitGirl-shaped feature)

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Setup.exe that extracts the archive | Inno + ISDone.dll + unarc.dll (2014 DLLs) | Inno + our own extractor via `Exec(ewNoWait)` + progress-file polling — no abandoned DLLs (doc 16 §4) | 🔜 H3 |
| SmartScreen survival | FitGirl: one signed stub + fg-*.bin | Source-confirmed pattern: frozen script → compile once → sign once → cache canonical exe; all variability in `{src}` sidecars (doc 16 §2) | 🔜 H1 |
| Payload tamper-proofing | their CRC32 + optional MD5 .bat | Inno ISSig (public key in exe, `.issig` sidecars — zero per-archive bytes in the stub) + our SHA-256 ledger (doc 16 §10) | 🔜 H1b |
| Preflight checks | ISDone error taxonomy (the "-1 error" forums) | Free-disk (with Precomp inflation math), non-Latin paths, missing-volume proceed-and-report, AV warning (doc 09 + Inno primitives doc 16 §7) | 🔜 H4 |
| Optional components / selective download | FitGirl selective .bin's | Named optional volumes in the manifest + Inno `CreateDownloadPage` with ISSig verify (doc 16 §10) | 🔜 H6 |

## 6. UI/UX & Windows integration

| Capability | Theirs | Ours — our own way | Phase |
|---|---|---|---|
| Command palette + settings search | PeaZip F12 picker (11.2) | One `ActionSpec` registry feeding both Ctrl+K palette and settings search (doc 17 §6) | 🔜 I10 |
| Settings persistence | everyone | `QSettings` + tool-path overrides (doc 11) | 🔜 I1 |
| Explorer context menu | NanaZip IExplorerCommand (the reference implementation) | Win10 HKCU verbs now; Win11 cascade via sparse MSIX post-signing, thin-launcher pattern + their manifest XML as template (doc 14 §2) | 🔜 I5 |
| Smart extract heuristics | NanaZip | Subfolder only when archive root isn't a single folder; multipart-aware naming; "open folder after" (doc 14 ADOPT 8) | 🔜 I5/G1 |
| Dark mode / modern feel | NanaZip Mica/XAML | Qt 6.5 `QStyleHints.colorScheme()` + DWM dark-titlebar attributes (doc 14 ADOPT 9) — no GPL widget libs | ✅ dark; 🔜 polish |
| Presets as data | PeaZip preset text files | TOML profiles shipped as data files, user-swappable (doc 17 §6) | 🔜 I-series |
| Progress reporting from tools | (they're native) | The pinned wrapper rules: 7z `-bsp1` + `\r`-split `%`; xtool/precomp = poll output size; exit codes mapped, never trusted for restores (doc 21 §1.2) | 🔜 B-series |
| "What's inside?" treemap | (nobody has it) | `squarify` treemap on the analysis screen — **a feature none of the studied tools offer** | 🔜 I8 |
| Honesty explainers ("why didn't X shrink") | (nobody has it) | Already shipped via `store_reason()` — our signature differentiator | ✅ |

## The punchline

Feature-for-feature, everything worth having from every studied tool is either
**already ours**, **planned with a pinned design**, or **deliberately skipped
with the reason recorded**. Nothing on this map requires copying a single line
of GPL/LGPL code — the closed gaps (lolz, per-game hand-tuning) are closed to
*everyone* without a license from their authors, and our trust column
(SHA-256 ledger, chain replay, honest reporting) is ahead of every tool
studied, including the closed ones.
