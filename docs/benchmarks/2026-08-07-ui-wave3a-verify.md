# 2026-08-07 — UI v3 wave 3a: verification, exposed

Machine: i7-3540M (2 cores / 4 threads), 16 GB, Windows 10 19045, threads = 2.

The engine has always done a full restore + per-file SHA-256 before letting an
archive become the user's output (the D9 gate). It only ever ran *implicitly*,
at compress time, on an archive you had just made — which is the moment you
need it least. Wave 3a makes it a verb: `engine.verify_archive`,
`excmp verify`, `excmp hash`, and a **Verify only** button.

---

## 1. The rule this ships with

**Verification means a real restore of every byte, compared against the
ledger.** Not `7z t`, not a size check, not a CRC.

That is not a preference. `7z t` checks only the last stage's own framing,
which let a broken stage underneath sail through: `srep64.exe` once failed its
decompression checksum at extract time on an archive `compress()` had already
reported as a success ([2026-08-01](2026-08-01-estimator-backtest.md)). Tool
exit codes cannot be trusted, which is why D9 replaced `7z t` with a real
restore in the first place.

So the publish gate is now implemented **in terms of the public verb** rather
than beside it — `_verify_before_publish` calls `verify_archive`. A test
(`test_the_publish_gate_and_the_verb_are_the_same_code`) fails if they ever
diverge, because if the button and the gate mean different things, one of them
is a lie.

## 2. Real corpus, both verdicts

Corpus A — the same 6 files, 721,076,752 bytes, external HDD, profile
`normal`.

| step | result |
|---|---|
| `excmp compress` | **700,884,250 bytes** |
| `excmp verify` (intact) | **exit 0** — 6 files restored, 6/6 SHA-256 verified, 34.4 s |
| one byte flipped in a stored entry | **exit 1** — `hash mismatch: Windows-KB890830-x64-V5.129.exe` |
| `excmp hash` on the archive | `17206b6d2fcd1f4f…` in `sha256sum` layout |

Two things worth recording:

1. **700,884,250 bytes for the third independent time** — matching the
   2026-08-02 record and the wave-2a re-run exactly. The engine has not moved
   across four sessions of UI work.
2. **The corruption was a single byte, XORed with 0xFF, inside a `stored/`
   entry** — length unchanged, zip structure intact, the zip's own CRC
   rewritten to match. `7z t` would pass this file. The ledger comparison
   named the exact file it broke.

The tampered run took **49.8 s** versus 34.4 s for the clean one: a failing
verify still restores everything before it can prove the mismatch, so failure
is not the fast path. Worth knowing before anyone tries to "optimise" it.

## 3. What the verb refuses to do

- **It writes nothing.** The restore goes to a private temp directory and is
  deleted whether it passes or fails, so verifying a 700 GB archive cannot
  fill the drive. Pinned by
  `test_verifying_never_touches_the_archive_or_leaves_a_restore_behind`.
- **It never touches the archive.** Read-only; the same test hashes the file
  before and after.
- **It ignores the Extract tab's destination field.** The whole promise is
  that nothing is produced, so aiming a verify at the user's output folder
  would be a contradiction. Pinned by
  `test_verify_never_writes_into_the_destination_folder`.

## 4. In the GUI

A verify is a **job**, not a modal: queued, cancellable, logged, reported —
because at 721 MB it is a 34-second full restore, and at 100 GB it is not.

- **Verify only** sits beside **Restore and verify** on the Extract tab, and
  enables as soon as an archive is chosen — it needs no destination.
- The queue row reads `verify` where a compress row reads its profile.
- The results panel says **"Verified 6 files"**, and the subline states what
  was actually done: *"Every file was restored to a temporary folder and its
  SHA-256 compared with the archive's ledger · 34.0s · nothing was written to
  disk."* The number is the evidence; a bare "OK" is what every other archiver
  already says without checking.
- No **Open output folder** button, because there is no output. The dismiss
  button says "Done" rather than "Compress something else".

Reviewed in both themes via `tools/qa_sweep.py` (now 13 surfaces × 2 themes).

## 5. Suite

`.venv\Scripts\python.exe -m pytest -q` → **390 passed, 1 xfailed**
(372 + 1 at the end of wave 2). New: `tests/test_verify_archive.py` (10),
`tests/test_gui_verify.py` (7).
