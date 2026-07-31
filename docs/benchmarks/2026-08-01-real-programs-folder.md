# Benchmark: real installer/archive corpus (Phase D0 acceptance run)

- Machine: Nuhaadh-Laptop, Intel i7-3540M (2C/4T), 16 GB
- Date: 2026-08-01
- Corpus: 6 real files, **721 MB** (688 MiB), from
  `Downloads-1\PalluVaapaHDD\0No Need To Check\Programs`
- Purpose: verify Phase D0 (path validator + ledger-bounded extraction) against
  real multi-hundred-MB files, not just synthetic test fixtures.

## Corpus and routing

| file | category | entropy | size | routed |
|---|---|---|---|---|
| `R-4.5.1-win.exe` | executable | 7.78 | 85.9 MB | pipeline |
| `Windows-KB890830-x64-V5.129.exe` | executable | 7.93 | 73.1 MB | store |
| `lghub_installer.exe` | executable | 6.51 | 55.5 MB | pipeline |
| `DB.Browser.for.SQLite-v3.13.0-win64.msi` | binary | 7.99 | 18.9 MB | store |
| `Winxvideo.AI.3.5.0.0.w64.rar` | compressed_archive | 8.00 | 202.9 MB | store |
| `Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip` | compressed_archive | 8.00 | 251.5 MB | store |

The router did the right thing unprompted: 4 of 6 files are already-compressed
(entropy ≥ 7.93) and were stored bit-exact, so only the two genuinely
compressible executables went through the chain. **That is why the saving is
2.8% and not 60%** — and the app says so before starting rather than after.

## Results

| profile | original | compressed | saved | compress | extract+verify |
|---|---|---|---|---|---|
| normal | 721.1 MB | 700.9 MB | 2.80% | 62.4 s | 36.9 s |
| extreme | 721.1 MB | 699.6 MB | 2.97% | 166.3 s | 57.9 s |

Derived throughput on this machine (useful as estimator calibration):

| profile | compress | extract |
|---|---|---|
| normal | ~11.6 MB/s | ~19.5 MB/s |
| extreme | ~4.3 MB/s | ~12.4 MB/s |

**Extreme cost 2.7× the time for 0.17 extra percentage points here.** On a corpus
this incompressible that is a bad trade, and it is exactly the judgement
`recommend_profile()` exists to make.

## Integrity

Both profiles: `6 files restored, 6 hashes verified OK`, plus an **independent**
SHA-256 comparison of every restored file against its original (run outside the
app, so it does not share code with `verify_restore()`): **6/6 byte-identical**.

Two D0-specific checks passed on real data:

- The validator did **not** reject legitimate awkward filenames — spaces,
  parentheses and `=` (`Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip`)
  all round-tripped. This is the false-positive half of the D0 test matrix,
  confirmed against real files rather than fixtures.
- Ledger-bounded extraction handled 200-250 MB single entries through the new
  exact-size stream cap without issue.

## Caveat

This corpus is deliberately *unfavourable* (81% already-compressed bytes). It
measures correctness and worst-case ratio honesty, **not** peak compression —
the 72.4% figure in `2026-07-18-Nuhaadh-Laptop.md` came from repack-style
zlib-wrapped data. Both numbers are real; they answer different questions.
Roadmap B8 replaces both with a Silesia + real-game-folder run.
