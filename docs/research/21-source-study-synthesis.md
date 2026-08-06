# 21 — Source-study synthesis: what the eight readings change

> Part of the 2026-07-31 source-code study series. This is the **read-me-first**
> for docs 13-20: the cross-cutting decisions, the corrections to earlier docs,
> and the concrete roadmap deltas. Where a claim came from a specific study it
> is cited as (doc N). Every underlying fact carries a file:line reference in
> its own study doc.

## 0. What this round was

The user asked for a genuine line-by-line source study — "download all the
source codes, pull and extract all the information you can, and include the
best parts in our application." We shallow-cloned eleven repos and had a
dedicated agent deep-read each of the eight that matter, at pinned commits:

| Study | Repo | Commit | License | Verdict |
|---|---|---|---|---|
| doc 13 | xtool 0.7.9 | `9a1d5fa` | MIT (Delphi) | **Use as B6 binary stage** |
| doc 14 | NanaZip | `4f5d447` | MIT (C++) | Conceptual: shell menu, MOTW, mitigations |
| doc 15 | Precomp 0.4.8 | `a11b077` | Apache-2.0 | Already a stage; tune + verify |
| doc 16 | Inno Setup 7.1-dev | `899f6ed` | permissive | **Enables Phase H (with one rule)** |
| doc 17 | PeaZip | `380ad91` | LGPLv3 | Conceptual: crypto, `-slt`, palette |
| doc 18 | FreeArc + par2turbo | `298ae5f`/`d56aeb4`/`033424e` | GPL / GPLv2+ | Concepts + confirm par2 choice |
| doc 19 | 7-Zip 26.02 | `f9d78af` | LGPL | Ground-truth for parsing/tuning |
| doc 20 | lrzip + zpaqfranz | `24bffa1`/`cc34e22` | GPLv2 / MIT | Long-range verdict; B1/D5 CLIs |

The license posture from the prior session holds and is now source-verified:
**we copy no non-MIT code.** 7-Zip/FreeArc/PeaZip/lrzip contributed *facts and
designs only*; xtool/zpaqfranz/Precomp are driven as subprocess binaries;
Inno Setup is invoked, not linked. The repo stays MIT-clean for SignPath (E4).

## 1. The five findings that change the plan

### 1.1 xtool restore = recompress ⇒ the Oodle DLL is part of the archive contract (doc 13)

xtool doesn't store transformed Oodle streams — on `decode` it **re-compresses**
each stream with the recorded codec/level, so a correct restore needs an
`oo2core` DLL whose encoder is byte-identical to the one used at encode. Oodle
has **no patch fallback** (removed in 0.6.5). **Roadmap delta (B6):** our
manifest must pin `{oodle_dll_name, sha256, source_relpath}`, re-resolve the DLL
from the game folder at restore, and refuse with a clear error on mismatch.
This is a real addition to B6's scope, not a nicety.

### 1.2 Three tools go silent (or lie) when piped — our wrappers must adapt (docs 13, 15, 19)

- **7z.exe** prints **no percent output at all** when stdout isn't a terminal
  unless we pass **`-bsp1`** (doc 19). This is the single most common 7z-wrapper
  bug and affects every stage that shells 7z.
- **xtool** uses `WriteConsole`, which **no-ops on redirected handles** — there
  is no parseable progress when piped; exit code (0/1) is the only signal
  (doc 13).
- **Precomp** exits **`exit(0)` even on fatal restore failure** (10 code sites)
  and doesn't round-trip-verify JPEG/MP3/default-deflate at compress time
  (doc 15).

**Roadmap delta (cross-cutting, feeds B6/B7 + D5):** the tool-runner contract
must (a) pass `-bsp1` to 7z and split progress on `\r`, (b) treat xtool/precomp
progress as unparseable and poll output-file size instead, and (c) **never
trust a tool's exit code as proof of a good restore** — our own post-restore
SHA-256 comparison is the acceptance gate for every stage. This retroactively
justifies the whole per-file ledger design.

### 1.3 A universal byte-identical installer stub is achievable — but only one way (doc 16)

Inno's compiled `setup.exe` **always embeds the full script state** (AppName,
`[Files]`, compiled `[Code]`), and recompiles are **not** guaranteed to hash
identically (resource-section rewrite is OS-build-dependent; LZMA2 file chunks
auto-thread by machine). So H1's "byte-identical stub" is real **only** via:
*one frozen universal script → compile once in CI → sign once → cache the
canonical `setup.exe` → ship identical bytes forever*, with all per-archive
variability in `{src}` sidecars read at runtime by `[Code]`. Bonus: Inno's
**ISSig** system embeds only a *public key* (constant across archives) and
verifies `.issig` sidecars — giving tamper-proof payloads **with zero
per-archive bytes in the exe**, which is the missing piece that lets H1 and
integrity coexist. **Roadmap delta (H1/H2):** rewrite H1 as the frozen-stub
pattern and add ISSig as the payload-integrity mechanism.

### 1.4 The long-range-dedup question is settled: no lrzip, lean on zpaqfranz (doc 20)

lrzip's rzip is the best byte-granular long-range matcher studied, but it is
GPL **and** hard-POSIX (mmap/mremap/pthreads, zero `_WIN32` path) — a
Cygwin-only GPL binary fails both our license posture and Windows-first bar.
Verdict: keep **`zstd --long=31` / 7z big-dict** for ≤2 GB distances (which,
after our router groups by type + 7z `-mqs` reorders, covers most repack
folders), and get **unlimited-distance dedup for free** from the **zpaqfranz**
Insane stage already planned in B1 (content-defined chunking, <500 MB RAM for
200 GB of data). A Python CDC pre-stage (fastcdc) stays deferred behind
telemetry. **Roadmap delta:** close the "do we need an SREP replacement" thread
— B1 already answers it; drop any lrzip consideration.

### 1.5 Our encryption decision is now source-proven, not recalled (doc 19)

7-Zip 26.02 source confirms all three claims F1 rests on: (a) **salt is empty**
on the create path (the salt lines are literally commented out), (b) KDF is
**SHA-256 iterated 2^19** over UTF-16LE password, (c) cipher is
**AES-256-CBC with CRC32-only integrity — no MAC/AEAD**. Even `-mhe=on` leaks
archive size, header size, KDF params, and volume layout. **Roadmap delta
(F1):** no design change — but the justification in doc 10 / roadmap F1 can now
cite `7zAes.cpp:232-238` etc. as source, and we keep `-p`/`-mhe=on` only as a
labelled "7z-compatible (weaker)" mode.

## 2. Corrections to earlier docs (facts that were stale)

- **mx9 default dictionary is 256 MiB on 64-bit since 7-Zip 24.09** (doc 19),
  not 64 MiB. Any RAM-planning text (B9, doc 12) citing "mx9 = 64 MB dict" is
  two generations stale. On 4 GB machines, mx9 multithreaded LZMA2 can exceed
  RAM (~13× dict per block thread). **Action:** correct B9 and doc 12; the RAM
  planner should use the exact `CompressDialog.cpp:2942-3016` formula, not a
  flat 10.5× multiplier.
- **"2 threads per chunk" wording in B9 is wrong** (doc 19): it's 2 threads per
  LZMA *encoder instance* (= per block); chunks are sequential inside a block.
  The default-threads-→2 decision still stands and is reinforced.
- **7z does NOT sort solid blocks by extension by default** (doc 19):
  `_useTypeSorting` is off unless `-mqs` is passed. Our docs (and many blogs)
  imply automatic extension sorting. **Action:** always pass `-mqs` (or pre-sort
  ourselves using the `g_Exts` ranking) for exe/media-heavy trees.
- **BCJ/BCJ2 gain has no source-level percentage** (doc 19): 7-Zip only gates
  BCJ2 behind level ≥ 8 + MT mixer. **Action:** flag the "5-10% on x86" figure
  in B7/doc 06 as benchmark-derived, not source-backed.
- **Current Precomp is 0.4.8 with preflate** (doc 15), not the old zlib
  level-brute-forcing model — the `zLibMTF` level tables are vestigial. Any
  tuning notes that reference level brute-forcing are obsolete.
- **7z MOTW default is OFF for the CLI** (`-snz` needed; doc 19). F4's premise
  (propagate MOTW ourselves) is correct and, per doc 14, ~40 lines of direct
  ADS I/O — do NOT shell PowerShell for it (PeaZip shipped a PowerShell-injection
  CVE doing exactly that, doc 17).

## 3. New cross-cutting patterns worth adopting (small, high-leverage)

These recur across studies and are cheap enough to fold into existing phases
rather than new ones:

1. **Post-restore hash verification as the universal acceptance gate** (docs 13,
   15) — a stage's output is accepted only if `restore(output) == input` by
   SHA-256. Precomp/xtool exit codes can't be trusted; this is the contract that
   makes an unverified/lossy stage impossible to ship by accident. Fold into the
   stage base class (touches B1/B2/B6/B7, verified by D5).
2. **Redundant, canonicalize-compare-reject path sanitizer** (docs 14, 17, 19) —
   all three ship the same Windows hostile-name checklist, and PeaZip *still*
   shipped a traversal CVE in 2026, so redundancy is the lesson. The D0 test
   matrix is now fully specified by the union of docs 14 §6, 17 §5, 19 §7
   (`..`, absolute, drive, UNC, `\\?\`, ADS `:`/`:$DATA`, reserved device names
   incl. `NUL.txt`, trailing dot/space, control chars, **RLO U+202E — which
   7-Zip itself doesn't sanitize in normal names**, empty parts, symlink→abs,
   symlink→`../..`, symlink chains). D0 can honestly claim to *exceed* 7-Zip.
3. **`7z l -slt` parser grammar, fully pinned** (docs 17, 19) — records are
   blank-line-separated `key = value` blocks after the `----------` line; accept
   empty RHS (`CRC =`); `--`/`----` open archive/nested layers; field vocabulary
   = `kPropIdToName[]`; flag `Encrypted=+` / `Method~AES`; always pass a dummy
   `-p` on list/test so encrypted archives error instead of hanging. This makes
   G2 a spec, not a guess.
4. **Solid-order sort key** (docs 18, 19, 20) — all three independently sort
   `(ext-rank, ext, basename, [similarity bucket], mtime, size, path)` before
   solid compression; FreeArc adds a same-name/same-size clustering pass that
   pulls near-identical files adjacent. Cheap `sorted(key=…)` win for our solid
   stage.
5. **Content sniffing overrides extension routing** (doc 18) — FreeArc's `-ma`
   probes 5×64 KB and votes text/compressed/binary, overriding the extension
   map; prevents the "renamed .zip inside .dat" ratio disaster. Start with a
   `zlib.compress(probe)` ratio as a poor-man's detector in the router.
6. **Process mitigations on the child, not on ourselves** (doc 14) — apply
   `PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY` (prohibit dynamic code, block
   non-system DLLs) + `CHILD_PROCESS_POLICY` + a kill-on-close Job object to the
   7z.exe/tool child; apply only the *safe* subset to our own Python process
   (image-load policy, strict handles) because ProhibitDynamicCode breaks
   ctypes/PySide6. New optional hardening item (fits E-series or a new D-item).
7. **Store fully-resolved tool+version identifiers in the manifest** (doc 18) —
   FreeArc's alias-pinning trick; a future tool swap can't silently break
   decompression. We already pin tool hashes (E1); also record the resolved
   name/version per archive.
8. **"Untrustworthy timestamp" re-hash exceptions** (doc 20) — Excel mutates
   metadata without changing size/mtime, so zpaqfranz force-re-hashes xls/ppt.
   Adopt the exception class in any future incremental logic.

## 4. Concrete roadmap deltas (summary for the ROADMAP edit)

- **D0** — replace the ad-hoc sanitizer note with the union test matrix from
  §3.2; add RLO U+202E (beats 7-Zip); cite docs 14/17/19.
- **New D-item** — child-process mitigations + safe self-process subset
  (doc 14 §3). Optional, S-effort. *(Label settled as **D0.6** in the roadmap
  and in doc 22 §3 — not D9, which 2026-08-02 assigned to the pre-publish
  verify gate. This line originally proposed "D9"; corrected 2026-08-05 after
  a graph pass surfaced the collision.)*
- **B1** — annotate with the exact zpaqfranz CLIs (`a … -m4 -longpath -test`;
  verify `t` + `v -ssd`); note `-m4` is the realistic Insane ceiling on 2 cores,
  `-m5` is a niche; keep archives 7.15-compatible (plain `a`, no `backup`
  multipart). Fold in the long-range verdict (§1.4).
- **B6** — add the DLL-pinning requirement (§1.1); add the exact precomp/xtool
  command lines and the "unparseable progress / untrusted exit code" wrapper
  rules (§1.2); add xtool's `.xtl` game-fingerprint DB as the fast lane.
- **B7** — force `-mf=BCJ2` at mx<8; flag BCJ gain as benchmark-derived.
- **B9 / doc 12** — correct the 256 MiB mx9 dict and the "2 threads/chunk"
  wording; switch to the exact RAM formula (§2).
- **Cross-cutting (stage base)** — `-bsp1` for 7z, poll-file progress for
  xtool/precomp, post-restore hash gate for every stage (§1.2, §3.1).
- **D5** — deep-verify = zpaqfranz `t` + `v -ssd` model; order-independent
  global tree hash from the `sum` command (doc 20 §10).
- **F1** — no design change; cite 7-Zip source for the "why not `-p`" argument
  (§1.5).
- **F3** — confirmed par2cmdline-turbo; add the exact create/verify/repair
  invocations and the ≤32768-block / block-size-scaling caveat (doc 18 §9).
- **F4** — MOTW via direct ADS I/O, never PowerShell (§2, doc 17 warning).
- **G2** — adopt the pinned `-slt` grammar + hang-guard (§3.3).
- **H1** — rewrite as the frozen-stub-compile-once-sign-once pattern (§1.3).
- **H2** — Inno version is **7.1-dev** in the mirror (7.0.x is the stable line);
  license permits redistributing generated installers and the compiler
  (attribution optional). Add ISSig sidecars for payload integrity.
- **G5 / new** — PeaZip's "conversion as a mode of Add" pattern; NanaZip's
  smart-extract folder heuristic.
- **I10** — command-palette + settings-search from a single action registry
  (PeaZip F12, doc 17 §6).

## 5. What we deliberately did NOT take

- **No FreeArc/PeaZip/lrzip code** (GPL/LGPL) — designs and parameter tables
  only, reimplemented cleanroom from the study docs.
- **No srep** (not OSI; xtool degrades gracefully without it).
- **No lrzip on Windows** (POSIX-bound; §1.4).
- **No dict/delta/Tornado ports** (doc 18) — modern zstd/lzma recapture the
  gains; revisit delta only for known-stride data via 7z `-mf=Delta:N`.
- **No Precomp `-brute` on weak hardware** (doc 15) — O(bytes × inflate);
  research-only flag.
- **No binary-patching the Inno stub** (doc 16) — ISCC ECDSA-verifies its own
  stubs and will refuse; branding via compile-time directives only.
- **No `p -paranoid -to` in the pipeline** (doc 20) — interactive captcha when
  the target dir is non-empty.

## 6. Provenance

All eleven repos were cloned to the session scratchpad and read at the pinned
commits in the table in §0. Nothing was committed from the clones; they are
throwaway. This series (docs 13-21) plus the earlier docs 08-12 are the
complete research record for the "study the source, take the best parts"
request. The next implementation session should read this doc first, then the
specific study doc for whatever phase it is starting.
