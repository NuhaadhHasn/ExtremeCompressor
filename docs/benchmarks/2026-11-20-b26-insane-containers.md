# 2026-11-20: B26, the B20 zip containers at Insane

**Machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads; `Win32_Processor`
checked 2026-11-19), 15.9 GB, shared with other Claude sessions, Firefox and WSL.
Every row ran `engine.compress` (D9 included) then `engine.extract`, below-normal
priority, one process at a time, an independent SHA-256 of every restored file.
**16 valid rows on six corpora, plus 2 on a JPEG album: 0 mismatches.** Harness:
`C:\excmp-bench\b26\run_insane_b20.cmd` and `run_album.cmd` (B21's `b21_app.py` on
main's code, frozen); contention log `C:\excmp-bench\contention.tsv`.

The handoff called this "unmeasured, keeps the chain's rate and the old extra".
It was measured because EPUB ran past its range.

---

## 1. Rows

Compress including D9, then extract (seconds). The fastest row of each corpus is
the quiet figure.

| corpus | bytes | archive (saved) | r1 | r2 | r3 |
|---|---:|---|---|---|---|
| nupkg (3 files) | 1,392,266 | 547,993 (60.64%) | 313.2 / 26.8 | **29.4** / 13.4 | 35.0 / 13.6 |
| appx (2) | 6,015,103 | 2,908,598-9 (51.65%) | 339.6 / 91.3 | 183.2 / 65.5 | **138.4** / 63.3 |
| aar (7) | 5,665,058 | 2,350,115-6 (58.52%) | 135.4 / 72.0 | **109.4** / 46.3 | 110.6 / 50.4 |
| epub (6) | 5,686,653 | 3,953,298-9 (30.48%) | 1,020.3 / 346.0 | **455.4** / 349.8 | 589.6 / 271.8 |
| odt-big (1) | 36,764,796 | 24,322,979 (33.84%) | **1,417.7** / 693.5 | 1,464.2 / 688.6 | not run |
| aab (2) | 121,000,789 | 37,619,997 (68.91%) | **1,890.7** / 827.8 | 2,594.8 / 838.8 | not run |
| album (23 JPEGs) | 11,620,228 | 8,058,334 (30.65%) | 198.3 / 45.2 | **91.4** / 49.0 | not run |

- **Round 1 of the four small corpora ran beside a runaway `find`** (13-20% of the
  CPU, another session's, since stopped by its owner) **and a memory squeeze to
  0.6 GB free**: `nupkg-r1` took 10.7x its round-2 time and is not asserted. The
  others from round 1 are contended rows the high side holds.
- **The machine slept 15.7 h through the first `odt-big` attempt** (Kernel-Power
  42 at 19:01 on 11-19, back 10:40; the contention log has the gap). The harness
  times with `time.monotonic`, which counts sleep, so that row was stopped and
  rerun. Its staging showed `m.excmp` finished at 18:44:30, 698 s after the
  process started; the rerun's compress was 724 s (a note, not a measurement).
- `odt-big` r1 and r2 agree to 3% (others about 10%, 2.5+ GB free) so round 3 was
  skipped. The AABs, 68% of the bytes, have two rows; round 2 was 37% slower with
  others at 17% against 14%, so round 1 is the floor (the self-test agrees to
  1.3%). **Self-test is steady across rounds; compress is what contention moves.**
- **The album's round 1 (198.3 s) was 2.2x its round 2 (91.4 s)** with others at
  24%: a contended row, like the others.
- **Savings.** Insane takes 3-9 points more than Extreme found (B20: AAB 65.56% at
  Extreme against 68.91% here, ODT 24.55% against 33.84%, EPUB 22.09% against
  30.48%).

## 2. Why the old pricing failed: expansion, not size

The chain's rate plus B20's extra priced each file by its own size. Seconds per
input MB (compress + D9, fastest row) ran from **16 (AAB) to 80 (EPUB)**.
Precomp hands zpaqfranz the *expanded* stream, and per MB of that the spread is
**4.4 to 7.2 s**:

| corpus | input | `.pcf` | expansion | s per input MB | s per `.pcf` MB |
|---|---:|---:|---:|---:|---:|
| nupkg | 1.4 MB | 4.1 MB | 2.9x | 21 | 7.2 |
| appx | 6.0 MB | 19.6 MB | 3.3x | 23 | 7.1 |
| aar | 5.7 MB | 16.4 MB | 2.9x | 19 | 6.7 |
| epub | 5.7 MB | 103.4 MB | 18.2x | 80 | 4.4 |
| odt-big | 36.8 MB | 215.5 MB | 5.9x | 39 | 6.6 |
| aab | 121.0 MB | 368.4 MB | 3.0x | 16 | 5.1 |

Against the old model (low / expected / high, seconds): NuGet 20/33/80 (29.4
inside), APPX 83/136/328, AAR 78/128/309 (inside), **EPUB 79/129/310 against a
fastest 455.4: out, 3.5x over the expected**, ODT 506/822/1,971 (1,417.7: 0.58x of
the expected, inside), AAB 1,664/2,702/6,473 (inside, 1.43x high).

**The zip central directory predicts the `.pcf` for plain deflate content.** The
sum of the deflated members' uncompressed sizes is **0.94-1.00 of the `.pcf` on
13 of the 14 NuGet, APPX, AAR and AAB files** (per corpus 0.94-0.99); the 14th, a
295 KB AAR, is 0.50: it holds a deflated `libs/*.jar`, a nested archive Precomp
expands again, so such a file is priced about 2x low. It fails exactly where the
container holds PNGs: EPUB 0.09, ODT 0.03 of the `.pcf`. Precomp expands a PNG
member's own deflate into pixels, **6x (ODT) to 106x (an EPUB) per PNG byte**,
which a directory cannot show (it would take the member's data). So PNG members
are priced as the PNGs they are, at B22's standalone rates, which came from other
corpora.

## 3. The model and the fit

Per container: `deflated / R_c + png / R_png_c + jpeg / R_jpeg_c + other / R_chain_c`
(and the same with the self-test rates), the four counts read from the central
directory (`FileInfo.zip_deflated_bytes`, `zip_png_bytes`, `zip_jpeg_bytes`,
`zip_other_bytes`). Only `R` for deflated bytes is new:

| corpus | deflated MB | compress | self-test | MB/s per corpus |
|---|---:|---:|---:|---|
| nupkg | 4.00 | 16.6 s | 12.0 s | 0.241 / 0.332 |
| appx | 19.29 | 71.4 s | 66.7 s | 0.270 / 0.289 |
| aar | 16.17 | 65.0 s | 44.4 s | 0.249 / 0.364 |
| aab | 346.15 | 849.6 s | 947.5 s | 0.407 / 0.365 |

The fastest row of each, each split **by its own phase events** (the compress
phase ends at the first `verify` event; the D9 phase is the rest), PNG and
residual bytes taken out at the other rates, byte-weighted:
**`_INSANE_ZIP_RATE` 0.385 MB/s, `_INSANE_ZIP_VERIFY_RATE` 0.360 MB/s.**

- **The AABs are 90% of the fit's deflated bytes** (68% of the six corpora's input
  bytes): this is the AABs' rate. The three small corpora agree on compress
  within 12% and run 30-37% under it, sitting 17-23% under their quiet rows
  (expected over fastest 0.77-0.83). The AABs are two apps from one toolchain
  that share most of their expanded bytes: the per-file model cannot see it (the
  known near-duplicate gap).
- **The split.** B22 split by `extract_s`. On the AAB row the in-job D9 phase is
  990.6 s against `extract_s` 827.8 (20% longer; round 2 1,270 against 839), on
  eight other rows within 7%, on `epub-r2` 226 against 350. The split by events
  (0.385 / 0.360) is the one the progress bar's phases need; split by `extract_s`
  it was 0.331 / 0.425. The sums agree, so the ranges do not move much.
- **JPEG members** are priced at B22's JPEG rates. One album of 23 stored
  photographs (11.6 MB, ordinary JPEGs from the design corpus, plus a tiny
  deflated page) ran 91.4 s (compress 45.8 + D9 45.6) fastest and 198.3 s
  contended, against 79 s at the JPEG rates and 238 s at the chain's; the model
  says 81 s. **One album is one corpus.** (A first version priced the residual at
  the chain's rate, which put the low end above the album's fastest row.)
- **GIF, stored members and other methods** are priced at the chain's rate:
  unmeasured, so the safe way round. EPUB holds 0.9 MB of JPEG, ODT 2.5 MB.
- **The PNG low-end allowance.** The ODT's self-test ran at 0.63x the model's
  (665 s against 1,057 s): its PNGs expand 6x per byte, the least of any
  container measured, and one PNG rate prices all of them. The low end may
  undercut the PNG members' self-test by 1.6x (`_ZIP_PNG_VERIFY_LOW`); without
  it the ODT's low end sat 1.3% under its one quiet row.

| corpus | low / expected / high | fastest | expected / fastest |
|---|---|---:|---:|
| nupkg | 15 / 24 / 95 | 29.4 | 0.83x |
| appx | 70 / 106 / 422 | 138.4 | 0.77x |
| aar | 59 / 89 / 354 | 109.4 | 0.81x |
| epub | 143 / 302 / 1,205 | 455.4 | 0.66x |
| odt-big | 1,025 / 2,223 / 8,890 | 1,417.7 | 1.57x |
| aab | 1,286 / 1,956 / 7,823 | 1,890.7 | 1.03x |
| album | 51 / 81 / 323 | 91.4 | 0.89x |

Every fastest row and every contended row is inside its range **except
`nupkg-r1` (313.2 s)**. The worst miss of the expected is 1.57x (ODT), down from
3.5x (EPUB). **Out of sample is true only for the PNG rate** (it came from B22's
corpora); the 1.7x band and the ODT low-end pin in the tests were set after seeing
the two results, so they are a regression pin, not validation.

**What stays wrong.** One PNG rate prices containers whose PNGs expand 6x and
106x; the high side (4x) holds an EPUB's 1,020 s row. A nested archive is priced
about 2x low (`aar-01`). `.png` is matched by name (a deflated text member called
`c.PNG` counts as a PNG). B5's types (`.docx .xlsx .pptx .zip .jar .apk`) keep the
chain rate at Insane although the probe now fills their counts: nobody has
measured them there. The AABs' self-test is steadier than their compress (839 s
against 828 s; compress 2,595 s against 1,891 s).

## 4. The review

Two reviewers on different lenses (estimator and evidence; the analyzer under
hostile input), each told to reproduce; I reproduced every finding before
touching the code (a skeptic's role), then fixed once, on the frozen tree.

| | finding | reproduced | fix |
|---|---|---|---|
| 1 | **a container of JPEGs and one small deflated page priced at ~0 s** (both reviewers) | 20 MB EPUB: 448 s on main, 2.0 s with the new fields | JPEG and residual bytes counted (`zip_jpeg_bytes`, `zip_other_bytes`); the album measured |
| 2 | a header claiming 10 TB: 24 years (2**64-1: 3 million) | 234-byte zip: 763,882,301 s | a deflated member counts at most 1032x its compressed bytes, a stored one its own |
| 3 | the split by `extract_s` is wrong for the dominant row | AAB D9 990.6 s vs 827.8 s; refit 0.384 / 0.360 reproduced | the split by phase events (0.385 / 0.360) |
| 4 | comments overclaimed | "all 14 files" was 13; "AABs 68%" is 90% of the fit; "17 rows" was 16; "4.4-9.3" was 4.4-7.2; ratios 0.64/0.65 | corrected, and the nested-jar file named |
| 5 | three mutants passed every test | stored members as deflated, `.jpeg`, `.webp` as PNG | tests; **my own mutation run found a fourth** (a stored PNG's claimed size): test. 13 mutations, all caught |
| 6 | the ODT's low end sat 2% under its one quiet row | 1,399 s vs 1,418 s | the PNG low-end allowance (1.6x on their self-test) |

Not changed: B5's types stay on the chain rate at Insane (item 8, a decision);
`.png` stays by-name (a nit, now stated). **Checked and clean:** `probe_expandable`
answers exactly what main's did on about two dozen odd inputs (valid, stored,
truncated, encrypted flag, zip64, wrong end record, a non-zip with a zip head,
PDFs, an empty or missing file, a directory) and on 2,000 single-byte mutations
of a zip; `analyze_file` never raised on 2**64 sizes, a 500,000-member directory,
invalid UTF-8 names or duplicate names; the added passes cost 4% of the zip parse
on a maximum-size directory; no `inf` or `NaN` came out of the estimate; no code
outside the tests builds or copies `FileInfo` positionally. What the comments
said and the reviewers could check reproduced: the probe sums on all six corpora,
the per-corpus rates and the weighted fit, every fastest row, the before and
after ranges.

## 5. What changed

- `analyzer.probe_container(path, head)` returns a `ContainerProfile(expandable,
  deflated, png, jpeg, other)`; `probe_expandable` keeps answering a bool;
  `_zip_profile` is the one pass over the central directory.
  `FileInfo.zip_deflated_bytes`, `zip_png_bytes`, `zip_jpeg_bytes`,
  `zip_other_bytes` (all 0 = unknown, the hand-built default).
- `estimate._insane_own_seconds(kind, info)` replaces the own-rate branch of
  `recode_cost`; all-zero counts keep the chain's rate and the old extra.
  `RecodeCost.zip_png_verify_seconds` feeds the low-end allowance. Extreme is
  untouched.

Tests: `tests/test_b26_zip_insane.py` (66). With the container branch switched
off, 8 of the first version's tests failed; 13 mutations of the probe and the
estimate are each caught. **Full suite on the final tree: 1,927 passed, 1
skipped, 1 xfailed** (638 + 639 + 650 in three parts, 3 min 58 s + 5 min 25 s +
2 min 42 s at below-normal priority on a quieter machine), **corpus guard clean:
0 added, 0 removed, 0 modified** over `Programs` (34 files) and the bench copy of
`My Graphical Projects` (123). The first tree, before the review's fixes, was
1,904 / 1 / 1, also clean.

## 6. Left open

- **GIF, stored and nested containers at Insane** (a GIF album, a zip of MP4s, a
  jar inside an AAR) are priced at the chain's rate and unmeasured.
- **B5's types at Insane.** `.docx .pptx .xlsx .zip .jar .apk` keep the chain's
  rate; the new model could price them, and nobody has timed one.
- **A second JPEG album, and a PNG-heavy container other than EPUB and ODT.** Each
  of those rates rests on one corpus.
- **The harness clock counts sleep.** The next bench should use an unbiased clock
  (`QueryUnbiasedInterruptTime`); this one lost a row to a 15.7 h sleep.
