# 10 — Security, safety & integrity: findings and design (verified 2026-07-31)

> **✓ Source-study update (2026-07-31):** the 7z-encryption claims below are now
> **source-proven** (doc 19 §1-2, `7zAes.cpp` — the salt lines are literally
> commented out), and the D0 sanitizer test matrix is now **source-pinned** by
> the union of 7-Zip/NanaZip/PeaZip sanitizers (docs 19 §7, 14 §6, 17 §5 —
> includes RLO `U+202E`, which 7-Zip itself does NOT sanitize in normal path
> components). Updates flagged inline as **[SOURCE-STUDY …]**.

> The user requirement is "secure, safe, must never damage files." This research
> audited our own code first, then the crypto/integrity landscape. It found one
> **real vulnerability in our reader** (fix before any new feature), rejected the
> obvious encryption route (7z `-p`) with evidence, and settled the designs for
> optional encryption and recovery records.

## 0. Findings in our own code (read during research)

**C-1. CONFIRMED zip-slip path traversal in the .excmp reader — fix first.**
`extract_stored()` in `excmp/manifest.py` (lines ~107–122) builds
`target = out_dir / rel` from the raw zip entry name and writes with no
sanitization. A malicious `.excmp` with an entry like
`stored/..\..\Start Menu\Programs\Startup\evil.bat` (or an absolute/drive path, or
an NTFS ADS name `stored/x.txt:payload`) writes **outside the destination folder**.
The manual `zf.open()` + write loop bypasses `ZipFile.extract()`'s sanitizer.
Adjacent weaker issues: `read_container()` trusts `manifest.payload_name`;
`verify_restore()` joins untrusted ledger keys (read-only, low risk).

Fix pattern — one shared sanitizer applied to every archive-supplied path:
reject absolute paths, drive letters, `..` segments, `:` (ADS), reserved device
names (CON, NUL, COM1…), trailing dots/spaces; then belt-and-braces
`target.resolve().is_relative_to(out_dir.resolve())` before writing. Plus
malicious-archive tests.

**C-2. Tar extraction is already safe — pin it.** `tarstage.py` already uses
`tar.extractall(dst, filter="data")` (PEP 706, active on our 3.12+ floor; default in
3.14). Add a regression test with a hostile tar so the argument can never be
silently removed.

**C-3. No decompression-bomb bounds anywhere.** The outer zip is STORED (low risk),
but the payload chain and `manifest.json` are unbounded. Our unique advantage: **the
manifest's own ledger declares the exact expected size and count of every restored
file** — bound extraction to `sum(ledger sizes) + slack` and `len(ledger)` files,
enforced on the actual streams (headers can be forged). Also cap `manifest.json`
(~8 MiB) before `json.loads`, and check free disk up front (Precomp legitimately
inflates 2–5× mid-pipeline → per-stage bounds, not just the end).

## 1. Encryption: why not 7z `-p`, and the right design

**7z AES-256 verified weaknesses:** key = SHA-256 iterated 2^19 times over the
password **with an empty salt by default** (identical passwords ⇒ identical keys
across archives — precomputation attacks); AES-CBC with **no authenticated
encryption** (integrity is CRC32 of the plaintext — ciphertext is malleable); plain
SHA-256 iteration is GPU-friendly vs memory-hard KDFs.
**[SOURCE-STUDY ✓ all three claims now proven from 7-Zip 26.02 source — doc 19 §1:
`CEncoder` sets only `NumCyclesPower=19` and the salt lines are commented out
(`7zAes.cpp:232-238`); plus a global key cache shares the KDF result, and even
`-mhe=on` still leaks archive size, header size, KDF params and volume layout
(doc 19 §2)]** Architecturally worse for us:
`-p` would cover only the 7z payload stage — `manifest.json` (every filename + hash)
and `stored/` files stay plaintext, and zstd-profile output gets no encryption at
all. **Verdict: delegating passwords to 7z is the wrong design. Rejected.**

**The design (we control the container — use it):** build the inner `.excmp` zip
exactly as today, then wrap the ENTIRE container in one encrypted blob:
- Header: magic + version + KDF-id + 16-byte random salt + Argon2id params + chunk
  size; header fed to every chunk as AAD.
- KDF: **Argon2id** (`argon2-cffi` 25.1, MIT) at RFC 9106 second recommendation
  (m=64 MiB, t=3, p=4) — comfortable on 16 GB machines; "paranoid" preset optional.
- Cipher: **AES-256-GCM** (`cryptography` 49.x, Apache-2.0/BSD), **chunked** (GCM
  caps one message at ~64 GiB): age-style STREAM construction, 4 MiB chunks, nonce =
  11-byte counter + final-chunk flag byte (defeats truncation/reorder/duplication).
  The i7-3540M has AES-NI — hardware-accelerated even on the low-end target.
- HKDF-derived password-check value in the header so "wrong password" vs "corrupted
  file" stay honest, distinct errors.
- Result: full `-mhe=on` equivalent and more — filenames, manifest, stored/ files all
  hidden; every byte authenticated (fails loudly on tamper — matches "verify before
  success"); salt + memory-hard KDF fix 7z's two crypto weaknesses.
- Optional **keyfile two-factor** (PeaZip's idea): HKDF(password, salt=SHA-256(keyfile)).

**Alternatives assessed and rejected as implementation:** pyrage/age — the age v1
spec is exactly this design and stays our template, but pyrage's API is in-memory
bytes only (fatal for multi-GB archives) and the age/rage CLIs only take passphrases
from an interactive TTY (hostile to GUI). Picocrypt — validates the Argon2id+AEAD
direction (audited 2024); it's a Go app, nothing to reuse; its Reed-Solomon role is
better served by par2.

UI copy stays honest: "protects confidentiality; lost password = lost data, no
backdoor."

## 2. Integrity beyond SHA-256: recovery records (the WinRAR gap)

- **par2cmdline-turbo v1.4.0** (2026, GPL-2.0+, actively maintained, SIMD): best
  route is the **`par2cmdline-turbo` PyPI package** (ships prebuilt Windows
  binaries) driven via subprocess exactly like our other stages. GPL contained:
  separate process, never linked; optional extra, never vendored.
- Design: opt-in "Add recovery record (5/10%)" → after atomic publish, `par2 create
  -rN archive.excmp` → sidecar `.par2` volumes; on failed verify, offer `par2 repair`.
  Sidecar-first v1 (proven Usenet model); in-container embedding is a v2 refinement.
- WinRAR rr is Reed-Solomon %-sized — par2 gives equivalent-or-better math.
  FreeArc's XOR-based rr was self-documented as weaker — cautionary tale, use RS.
- Cheap future hardening: duplicate manifest copy at container end.
- SHA-256 ledger *detects* rot; par2 *repairs* it; D5 deep-verify completes the story.

## 3. Safe extraction (beyond C-1)

- One shared path sanitizer used by `extract_stored`, `read_container`,
  `verify_restore`.
- Ledger-bounded extraction (C-3); free-disk preflight; loud failure + temp cleanup
  (D3/D4 cover the rest).
- Symlink policy: compression only adds regular files today; tar `data` filter
  rejects escaping links; make "refuse/skip with warning" explicit in D2 tests
  (Windows symlinks are admin-only anyway).
- Tool minimum-version floors, not just pinned hashes: e.g. 7-Zip ≥ 24.09
  (CVE-2025-0411, Mark-of-the-Web bypass, actively exploited; current 26.02).
- **Mark-of-the-Web propagation** (nice, cheap, marketable): copy the source
  .excmp's `Zone.Identifier` ADS onto extracted files
  **[SOURCE-STUDY: implementation now fully specified — direct ADS file I/O
  (`open(path + ":Zone.Identifier")`, ~40 lines, doc 14 §5), NEVER via
  PowerShell (PeaZip shipped a PowerShell-injection CVE doing exactly this,
  doc 17 §5); skip any archive-embedded `Zone.Identifier` entry (7-Zip's own
  anti-spoof, doc 19 §8); note 7z.exe's CLI default is OFF (`-snz` needed), so
  we must do it ourselves to be safe-by-default]** — the exact behavior whose
  absence was 7-Zip's exploited CVE. ~20 lines.
- Never run anything from inside an archive; no SFX output in v1.

## 4. Supply chain

- E1 downloader as planned (HTTPS + repo-pinned SHA-256 + atomic move + hard fail),
  plus: min-version security floors; verify GitHub Artifact Attestations where
  upstream publishes them; record the verified tool hash into each .excmp manifest.
- 7-Zip binaries are famously **unsigned** (Pavlov declines Authenticode) — the
  pinned SHA-256 IS the trust anchor; cross-check against winget manifests.
- Our own releases: pip `--require-hashes` lockfile, Actions pinned by commit SHA,
  publish SHA256SUMS + GitHub attestations (2 lines of YAML ⇒ SLSA Build L2).
  Bit-reproducible PyInstaller builds are not realistic; provenance attestation is
  the practical substitute.

## 5. AV false positives — posture

Verified triggers: PyInstaller `--onefile` (self-extraction = packer heuristics),
UPX (documented to *increase* detections), SFX stubs (dropper pattern), unsigned
low-reputation exes. Peers: NanaZip ships signed MSIX via the Store and still sees
occasional FPs; PeaZip (unsigned + checksums) fights them constantly. Conclusion:
**signing + reputable channel is the only lever that works** → keep E3 (`--onedir` +
Inno) and E4 (SignPath OV — verified still operating 2026, requires 100%-OSI repo
**[SOURCE-STUDY: SREP is now dropped entirely rather than downloaded — doc 20 §4 /
doc 21 §5 — which makes the OSI-clean story even simpler]**); never UPX; no SFX in v1; submit
FPs to Microsoft Security Intelligence on release day; consider winget/MSIX post-v1.

## 6. Security roadmap by phase (decision)

| When | Ships |
|---|---|
| **D0 (next session, before anything)** | C-1 zip-slip fix + shared sanitizer + malicious-archive tests; C-3 ledger-bounded extraction + manifest cap; C-2 `filter="data"` regression test |
| **Phase D (QA)** | D5 deep-verify; symlink policy tests; SECURITY.md + short threat model (pulled forward from E6) |
| **Phase E (release)** | E1 + attestations + min-version floors; SignPath signing; `--onedir`; SHA256SUMS; hash-pinned deps/actions |
| **Phase F (Protect)** | Optional password: Argon2id + chunked AES-256-GCM over the whole container; keyfile 2FA; par2 recovery records; MotW propagation |

## Sources (highlights)

- peps.python.org/pep-0706 · github.com/lclevy/unarcrypto · en.wikipedia.org/wiki/7z
- C2SP age spec · github.com/woodruffw/pyrage · Picocrypt/Internals.md · RFC 9106
- pypi.org/project/par2cmdline-turbo · win-rar.com/recovery-record · FreeArc 0.36 docs
- cvedetails CVE-2025-0411 · signpath.org/terms · github.com/upx/upx/issues/711
- GitHub Artifact Attestations docs · sourceforge 7-Zip signing thread (#2325)
