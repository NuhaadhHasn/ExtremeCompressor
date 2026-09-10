# Security Policy

ExtremeCompressor parses untrusted input by design — an archive is attacker-controlled
data from the moment it arrives. That makes a disclosure channel a prerequisite, not a
formality.

## Supported versions

Pre-1.0. Only the tip of `main` receives fixes; there are no maintained release
branches yet. Current version: `0.1.0`.

## Reporting a vulnerability

Please report privately through **GitHub's private vulnerability reporting** on this
repository: *Security → Report a vulnerability*. It creates a draft advisory visible
only to the maintainer, so nothing is public while a fix is being written.

> **The repository has been private since 2026-09-01**, so in practice there is nobody
> outside to report anything. This policy is kept current rather than deleted because it
> becomes live again the moment the repo is public, and a threat model written after the
> fact is worth less than one that was maintained.

Please don't open a public issue for anything that lets an archive read or write
outside its destination, execute code, or bypass verification.

Useful in a report: the crafted archive (or a script that generates it), the command
run, what happened, and what you expected. A proof of concept that stays inside a
temporary directory is easier to act on than one aimed at a system path.

Expect an acknowledgement within about a week. This is a personal project, not a
funded product — there is no bug bounty, and no formal SLA beyond a good-faith effort
to fix real issues promptly and credit reporters who want it.

## Threat model

What the design actually assumes, and what it does not.

### 1. Malicious archive

**Assumed hostile.** Every path an archive supplies — zip entry names,
`manifest.payload_name`, SHA-256 ledger keys — is validated by
[`excmp/safepath.py`](excmp/safepath.py) before it reaches the filesystem. Names are
**rejected, not rewritten**: traversal (`..`), absolute paths, drive letters, UNC and
`\\?\` prefixes, NTFS alternate data streams (`:`), control characters,
bidirectional overrides (including RLO `U+202E`), Windows-illegal characters,
trailing dots and spaces, and reserved device names (`CON`, `NUL.txt`, `COM1 .log`).
The validated join is then canonicalized and compared against the destination again,
so a name has to defeat two independent layers.

Extraction is bounded by the archive's own ledger: each stored entry is capped at
precisely the size the manifest declares, enforced on the real stream rather than the
zip header, and an entry the manifest never declared is refused. `manifest.json` is
capped before it is parsed. Tar extraction uses PEP 706 `filter="data"`, pinned by
tests. Symlink and device entries are refused; nothing from inside an archive is ever
executed.

### 2. Tampered tool binary

**Partially addressed — the weakest link today.** Stages shell out to `7z.exe`,
`precomp` and friends. Tool paths and versions are recorded in each archive's
manifest. The SHA-256-pinned downloader with minimum-version security floors is
planned (roadmap E1) and **not yet implemented**, so a tool already on `PATH` is
currently trusted as found. Until then, treat the tool fleet as part of your trusted
computing base. Tool subprocesses do not yet run under Windows process mitigations
(roadmap D0.6).

### 3. Tampered archive

**Detected, not repaired.** Every input file's SHA-256 is recorded at compression
time and re-checked after restore; extraction reports success only if every hash
matches. Compression verifies its own output before atomically publishing it, and
inputs are never modified. This detects corruption and tampering but cannot repair
it — Reed-Solomon recovery records are planned (roadmap F3). Note the ledger proves
*integrity*, not *authenticity*: an attacker who rewrites both the payload and the
manifest produces a self-consistent archive. Signing is not in scope for v1.

### 4. Lost password, or lost keyfile

**No recovery, by design.** Optional encryption **shipped 2026-09-03** (roadmap F1) and
uses Argon2id (m=64 MiB, t=3, p=4) with a random salt over chunked AES-256-GCM, with the
header as AAD for every chunk. There is no backdoor, no escrow and no reset: a lost
password means lost data.

**A lost keyfile is exactly as final**, and users do not expect that. A keyfile (roadmap
F2) is folded into the key with HKDF, so the archive needs *that file, byte for byte* as
well as the password — a re-saved or re-downloaded copy will not do. Both factors are
now reachable from the CLI (`--keyfile` on `compress`, `extract`, `list`, `convert` and
`verify`); until 2026-09-09 the engine could create a keyfile archive it had no way to
open, which is recorded in the changelog rather than quietly fixed.

The UI says all of this plainly rather than implying otherwise — and F5 (2026-09-09) had
to fix *where* it said it, not what it said: the honest sentence was in a tooltip that
needed a mouse hover, and the visible note was replaced by "the two entries do not match
yet" for the whole time somebody was typing the confirmation.

## Not defended against

Stated explicitly, because a vague threat model is worse than a narrow one:

- **A hostile machine.** Malware with your privileges can read plaintext before
  compression and after extraction.
- **Side channels.** Archive size and timing leak information about content; only
  encrypted archives hide filenames.
- **Denial of service via resource exhaustion.** Bounds are in place for
  decompression bombs, but a deliberately pathological archive can still waste
  substantial CPU.
- **Supply chain of Python dependencies.** Hash-pinned lockfiles are planned
  (roadmap E-series), not yet in place.
