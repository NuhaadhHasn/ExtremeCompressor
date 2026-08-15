# 2026-08-07 — UI v3 wave 3b: foreign archives (G1) and listing (I2-lite)

Machine: i7-3540M, 16 GB, Windows 10 19045.

Two capabilities the engine already had and the UI hid. `SevenZipStage.extract`
shells `7z x`, which opens zip/7z/rar/tar/iso/cab/msi/wim without caring who
made them — the Extract tab accepted `*.excmp` only. And `_read_manifest` is a
zip-directory read plus one JSON parse, so the entire ledger was one call away
and never shown.

---

## 1. The honesty boundary is the feature

An `.excmp` restore is checked against a SHA-256 ledger. **A foreign archive
cannot be, because there is no ledger in it.** If the UI renders both the same
way, the guarantee stops meaning anything.

`ExtractResult` gained `ledger_backed: bool`. It exists because `verified == 0`
is ambiguous — "nothing to check against" and "checked, found zero good" are
very different sentences — and the first thing the flag caught was a real one:

> **"0 SHA-256 hashes verified — byte-identical to the originals"**

which is what the results panel rendered for a foreign zip before the fix. A
test now pins that the two paths cannot share wording.

Three more boundaries, each pinned:

| where | ours | theirs |
|---|---|---|
| **Verify only** button | enabled | disabled, tooltip says *why* — no ledger to check against |
| **What's inside** | lists from the manifest | disabled; listing other formats needs `7z l -slt` (G2) |
| card blurb | "Every file's SHA-256 was recorded…" | "…those carry no SHA-256 ledger" |

`engine.extract()` deliberately stays `.excmp`-only; `extract_any()` is the
new dispatcher. A caller that wants the ledger-verified path should not get a
best-effort one by accident.

**`is_excmp()` trusts the manifest, never the extension.** Renaming a plain zip
to `.excmp` must not decide which guarantees apply to it.

## 2. Real data

A genuine third-party zip from the Programs corpus (`BlueScreen microsoft.zip`,
63,833 bytes — nothing in this project made it):

```
restored 2 file(s) in 0.5s -> ...\out
note: this archive was not created by ExtremeCompressor, so it carries no
      SHA-256 ledger - the contents could not be checked against one

$ excmp list "BlueScreen microsoft.zip"
error: ... is not an .excmp container - listing other formats needs `7z l`
       support, which is not wired up yet
```

Refusing to list is deliberate: an empty list reads as "this archive is empty".

## 3. The bug the listing found on real data

First run of `excmp list` on a real mixed archive:

```
DB.Browser...win64.msi   18.9 MB  store   high-entropy (7.99 bits/byte)...; high-entropy (7.98 bits/byte)...
BlueScreen microsoft.zip 62.3 KB  store   high-entropy (7.99 bits/byte)...; high-entropy (7.98 bits/byte)...
```

Both files carried **both** reasons. The manifest only recorded a merged
per-*route* reason, and `planner.store_reason`'s own docstring had said so all
along: *"the route-level reason is a joined summary and loses the detail."*
Attributing it to an individual file claims a file measured 7.99 **and** 7.98
bits/byte — the sort of almost-true that the one column no other archiver has
cannot afford.

`Manifest` gained `store_reasons: dict[str, str]`, populated from the per-file
`store_reason()` at compress time. It is **defaulted**, so archives written
before the field still load (`from_json` passes `**data`; the default fills
in) and fall back to the route summary. After:

```
DB.Browser...win64.msi   18.9 MB  store     high-entropy data (7.99 bits/byte): already compressed...
Composer-Setup.exe        1.7 MB  pipeline
BlueScreen microsoft.zip 62.3 KB  store     high-entropy data (7.98 bits/byte): already compressed...
```

## 4. The QA sweep found the other one

The Extract card's standing subtitle — *"Every file's SHA-256 was recorded when
the archive was written… re-checks each hash"* — sat directly above a status
line saying *"this one has no SHA-256 ledger"*. A contradiction the user reads
first, in the tab whose whole job is saying which guarantees apply. The blurb
is now written per archive kind.

That is two waves running where the sweep caught something the suite could not.
It is now 14 surfaces × 2 themes and covers both archive kinds.

## 5. New CLI surface

```
excmp list <archive> [--json]     what is inside, from the manifest, no extraction
excmp extract <any archive>       ours (verified) or theirs (honestly unverified)
```

## 6. Suite

`.venv\Scripts\python.exe -m pytest -q` → **415 passed, 1 xfailed**
(390 + 1 after wave 3a). New: `tests/test_foreign_and_listing.py` (15),
`tests/test_gui_foreign.py` (10).

Three wave-3a tests were updated rather than deleted: they used a placeholder
file as a stand-in for an archive, which `is_excmp` now correctly refuses. The
tightening was right; the stubs became real `.excmp` fixtures.
