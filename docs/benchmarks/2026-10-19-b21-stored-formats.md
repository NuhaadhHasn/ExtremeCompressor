# 2026-10-19: B21, the stored formats nobody had measured

**Machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads), 15.9 GB
(`Win32_Processor` checked). Every benchmark process ran at below-normal
priority. **Not a quiet day:** the owner ran other sessions throughout, and
two things made contention worse than usual. Free memory ran down to
617-741 MB from 14:40 to 15:28 and 7-Zip paged (§2.3), and another Claude
session's plugin hooks (`remember`'s `post-tool-hook.sh`, ~60 s of CPU each
at worst) held 30-70% of the four logical CPUs on average per run, peaks
96%, for most of the afternoon. **Sizes and restore
results don't depend on any of that; times are pinned only where three
rounds agreed** (§4).

Harnesses: `C:\excmp-bench\b21\` — `gif_perfile.py` (per file, B20's
pattern), `head_scan.py` (first bytes of every listed file),
`setup_misnamed.py`, `setup_png.py`, `b21_app.py` (B13's `b13_app.py`:
`engine.compress` with D9, `engine.extract`, an independent SHA-256 of every
restored file), `b21_media.py` (B18's `b18_media.codec`, unchanged),
`estimate_vs_e2e.py`, `contention_by_row.py`. B19's `jpeg_perfile.py` for
lepton against packJPG. Rows: `perfile-*.jsonl`, `e2e\`, `timing\`,
`timing2\`, `timing3\`, `media\`. File names from the owner's data are not
recorded here.

**Every file restored byte-identically, in every run below: 0 mismatches.**

---

## 1. GIF through Precomp

Precomp recodes a GIF's LZW itself (`-t` lists `F = GIF`), and every GIF was
stored: the planner exempts media from its Precomp override, and only PNG
and MP3 had been let through.

### The corpora

Every `*.gif` on both drives: 122 in `Downloads` (33.5 MB) and 93 in
`Desktop\Downloads-1` (7.6 MB), as the handoff counted. Deduplicated by
SHA-256 across both: **64 files, 30,035,992 B** and **24 files, 5,990,579 B**
(127 duplicates). All 88 are real GIFs (63 + 24 `89a`, one `87a`); 52 are
animated, 10 interlaced.

### Per file

`precomp -cn -intense` exactly as `PrecompStage` builds it, `precomp -r`
back and compared, then 7-Zip on the `.pcf` (or on the GIF when Precomp
found nothing) as `SevenZipStage` builds it, extracted and compared.

| corpus | files | stored (today) | Precomp → 7-Zip |
|---|---:|---:|---:|
| Downloads | 64 | 0% | **25.66%** |
| Downloads-1 | 24 | 0% | **6.85%** |

| group | files | bytes | Precomp → 7-Zip |
|---|---:|---:|---:|
| Precomp recoded the GIF (Downloads) | 41 | 21,552,547 | 34.93% |
| Precomp recoded the GIF (Downloads-1) | 19 | 1,569,061 | 20.30% |
| Precomp could not (both) | 28 | 12,904,963 | 2.1% |

Over 1 KB, two of the recoded files came out **bigger**: 1.254 and 1.176
of 18 KB and 72 KB. Both are noisy few-frame images whose LZW beat LZMA on
the raw pixels (their `.pcf` was 12.6-12.8× the GIF). 90 KB of 36 MB;
nothing cheap (entropy, probe, frame count) separates them from the files
that won. Over 1 KB the worst file Precomp passed through came out at
1.0003. Under 1 KB, per file, 7-Zip's own container outweighs the GIF (16
of the 60 recoded files "grew", 14 of them 43-752 B files, 43 → 186 B;
two 42 B pass-throughs went to 4.3×); a solid archive pays that once. The
engine has no "store it if the pipeline grew it" fallback, for PNG either;
that would mean compressing twice.

Precomp's `.pcf` was **2.02×** the input byte-weighted over all 88 (2.12×
over the 63 it wrote a `.pcf` for), inside the preflight's default 5×; one
1600×1124 single frame reached 27.5× alone.

### End to end

| corpus | profile | `main` (stored) | GIFs piped |
|---|---|---:|---:|
| Downloads | Extreme | −0.040% | **25.782%** |
| Downloads-1 | Extreme | −0.083% | **6.984%** |
| Downloads-1 | Insane | −0.083% | **11.294%** |

The estimate brackets both piped archives under its ceiling with no GIF
constant: a piped GIF is priced like any media file Precomp is let at
(`_OVERRIDE_LOW` 0.30, its own probe, 1.0), the probe reads ~1.0 on GIF, and
under a Precomp chain `expected` is an upper bound anyway.

**Rule:** a GIF joins PNG in `planner._PRECOMP_IMAGES`, piped on any chain
with Precomp. Fast and Normal keep storing it.

---

## 2. PNG (and GIF) by content

### What the names were hiding

`head_scan.py` read the first 16 bytes of every `.png`, `.jpg` and `.jpeg`
on both drives:

| named | is | files |
|---|---|---:|
| `.png` (10,359) | PNG | 10,082 |
| | **JPEG** | **268** |
| | empty / macOS fork / WebP | 4 / 4 / 1 |
| `.jpg`/`.jpeg` (6,648) | JPEG | 6,628 |
| | **PNG** | **10** |
| | WebP / macOS fork | 6 / 4 |

**B19 recorded 43 PNGs named `.jpg`; today there are 10.** B19's own listing
of the same two drives also yields 10 when re-scanned, and 38 of its `.jpeg`
entries no longer exist; the 43 could not be reproduced.

The PNG exception keyed on the suffix while the store route claims a JPEG by
content (`FileInfo.is_jpeg`, B19), so the two disagreed both ways:

- the PNGs named `.jpg` were **stored at 0%**;
- the JPEGs named `.png` were **piped to Precomp's packJPG**, where B19's
  rule ("lepton keeps every JPEG it accepts") says lepton.

### Per file, deduplicated

| set | files | bytes | today | by content |
|---|---:|---:|---:|---:|
| JPEGs named `.png` | 249 | 20,882,935 | Precomp → 7-Zip **27.05%** | lepton **28.34%** |
| PNGs named `.jpg` | 8 | 2,033,229 | stored 0% | Precomp → 7-Zip **6.75%** |

Lepton was smaller on 244 of the 248 it encoded (all three-component, 248
of 249 baseline); it declined one 453-byte file, which stays raw. Every one of the 8 PNGs shrank (0.319-0.981).

### End to end, `main` against the branch

| set | `main` (by name) | branch (by content) |
|---|---:|---:|
| JPEGs named `.png` | 26.572%, 482.9 s, one contended run (Precomp) | **28.115%**, 56-112 s over four runs (lepton on 248) |
| PNGs named `.jpg` | −0.097% (stored) | **6.779%** |

**Rule:** `FileInfo.image_format` records `"png"`, `"gif"` or `""` from the
full signature; the planner and the temp budget (`precomp_inflation`) read
it. A hand-built `FileInfo` (`image_format=None`) is taken at its name.

### 2.3 A run that paged

The first Downloads GIF run took **2,604 s**: free memory fell as low as
617 MB (WSL's `vmmem` held 5.7 GB private, the owner's other sessions most
of the rest), 7-Zip's 673 MB of private
memory sat mostly in the page file at below-normal priority, and it read
the 66 MB `.pcf` at ~1 MB per minute with ~0 CPU. Its size matched the
per-file run; its time is discarded.

---

## 3. MKV, WebM and M4A under B18's probe rule

Every file of the three types on both drives (`find`, then `b21_media.py
probe`, which drops same-size duplicates by SHA-256): **MKV 16 files,
2,066,300,589 B** and **M4A 25, 355,699,815 B**, all on `Downloads-1`;
**WebM 3, 618,713 B** (two drives, 7 copies). The MKVs are 14 programming
course recordings, a music video and a project video; the M4As a Django
course (8), a PL/SQL course (14), ringtones and an Android resource.

### Per file

B18's method unchanged (`b18_media.codec`): `7z -mx9 -mmt2` and `zstd -19`
per file, each restored and compared. **Every file restored.** The MKV run
was stopped by Claude Code's low-memory reaper after 10 of 16 on
2026-10-19 and resumed on 2026-11-12 for the other six (same files, same
sizes).

| type | probe flags it | | probe doesn't | |
|---|---|---:|---|---:|
| MKV | 12 files, 1,673,873,517 B | **3.68%** (1.25-27.9%) | 4, 392,427,072 B | **2.23%** (0.42-3.31%) |
| M4A | 2, 1,059,161 B | **7.37%** (5.1-9.2%) | 23, 354,640,654 B | **1.79%** (0.62-3.47%) |
| WebM | 1, 163,498 B | **6.97%** | 2, 455,215 B | **0.57%** |

(7-Zip. zstd -19 ran 0.1-0.96 points higher on every MKV and WebM and on
23 of the M4As; on the two flagged M4As it was 0.07 and 0.78 points lower.)
For comparison, B18's MP4s split 9.20% / 1.61% and 3.77% / 0.32%.

**MKV separates weakly**: every file shrank, and the four the probe passes
over still gave 2.23%. But the probe routes 81% of the MKV bytes, and its
choice takes 61.5 MB of the 70.2 MB that piping all of them would: 88%.
That is the trade B18 made on MP4 (1.61% left on the table), so ffprobe
wasn't needed. M4A's flagged files are the two small ones (an Android
resource and a ringtone); the course audio's head sample compresses (mean
probe 0.82-0.99) but its worst sample doesn't, and 7-Zip took 0.6-3.5%
off it. WebM is too small a corpus to stand alone; it is Matroska, like
MKV, and split the same way.

**The rule was held back from B21's merge** and merged with B21b (§5):
`.mkv`, `.webm` and `.m4a` join `planner._PROBE_DECIDES`. The owner held
it on 2026-11-12 after review found a regression: piping video raises the disk preflight's floor (`piped × 2 +
total + out`), so the owner's 16 MKVs (1.92 GiB), which store with a
3.85 GiB floor, need 6.97 GiB and are **refused at every profile** when C:
has 3.9-7.0 GiB free. It had 6.37 GiB when the reviewer ran it and 8.7 an
hour later. MP4 and MOV have done the same since B18/B19. B21b merges with
a fallback: when only the store-only floor fits, store the probe-piped
media and say so, rather than refuse a job for 2-4%.

Two more things the same review found, both true of MP4 since B18:
**the recommendation picks Extreme for a video folder** ("lots of
compressible data", because 81% of the bytes are piped) while the table
flags Extreme as no better than Normal; and **Extreme's calibration
learns from video** that Precomp passes straight through (~3.1 MB/s
against the 1.41 prior, one run). AVI, WMV, FLV and AAC stay stored until
measured.

### End to end

`main` against `b21b-media-probe`'s rule (`EXCMP_REPO`), Normal and
Extreme, every file restored (2026-11-12). M4A and WebM whole; MKV a 201 MB sample of 7 (five
the probe flags, 5.4-93 MB, the 27.9% outlier among them; the music video
and one course file it doesn't), not 2 GB of 7-Zip.

| corpus | profile | `main` (stored) | branch | piped |
|---|---|---:|---:|---:|
| WebM, 3 files, 618,713 B | Normal | −0.157% | **1.668%** | 1 file |
| | Extreme | −0.157% | **1.643%** | |
| M4A, 25 files, 355,699,815 B | Normal | −0.001% | **0.021%** | 2 files, 1.06 MB |
| | Extreme | −0.001% | **0.021%** | |
| MKV, 7 files, 201,080,274 B | Normal | −0.001% | **4.533%**, 42.5 s | 5 files, 172 MB |
| | Extreme | −0.001% | **4.530%**, 68.0 s | |

Extreme buys nothing over Normal on video (Precomp has no video codec, as
B18 found on MP4) and costs 60% more time; the table flags that row, but
the recommendation still picks it (above). Against the estimate (with the
rule): MKV inside the range in size and time at both profiles, WebM inside
in size. **Outside:** M4A at Normal came in 12.7 KB (0.004%) under the size
range (a piped file under 3 MiB is one probe sample, so `low` equals
`expected` and any miss is outside; true of any small flagged MP4 too), and
the time of the small and store-heavy jobs ran far over (WebM 1.1 s against
a 0.1-0.4 s high; M4A 36-40 s against 7.8-9.7 s, where `main` storing the
same files took 14-24 s): the per-job fixed cost B22 is to add.

---

## 4. Time: PNG and GIF had no term

`estimate.py` billed a piped PNG at the generic Precomp chain's 1.41 MB/s
since B3; B3 itself had recorded 32.7 s for 7 MB at Extreme. Precomp expands
each PNG and GIF into raw pixels (a 1.4 KB PNG became a 704 KB `.pcf`), and
7-Zip then pays for the pixels.

### Corpora

GIF: the two above. PNG: two new samples, PNGs by content spread evenly by
size, **70 files / 8,192,542 B** from `Downloads` (3,699 PNGs) and **80 /
8,181,831 B** from `Downloads-1` (6,383).

### Rounds

Three interleaved rounds per the quiet protocol, at Extreme with the
branch's code, `contention.ps1` beside them. **The first set (`timing\`)
ran mostly beside the other session's hooks (per-run means 6-71%, peaks
96%) and its total times swung 1.7-4.7× between rounds; it is not used**,
though its least contended PNG run (17.5%) went 0.41 MB/s, 2× the pin, and
the low end holds it. The second (`timing2\`), others ~30-60% on average
per run (peaks 79%): the compress rates agreed within ~20% on three of the
four corpora, GIF Downloads-1 spread 1.5×, and the self-test up to 1.8×:

| corpus | pipeline MB/s (3 runs) | D9 MB/s (3 runs) | total s (median) | saved |
|---|---|---|---:|---:|
| GIF Downloads | 0.275 / 0.334 / 0.315 | 2.61 / 2.28 / 2.48 | 107.6 | 25.782% |
| GIF Downloads-1 | 0.605 / 0.922 / 0.631 | 1.93 / 3.15 / 1.87 | 12.7 | 6.984% |
| PNG Downloads | 0.216 / 0.201 / 0.187 | 0.99 / 0.77 / 1.37 | 49.9 | 36.670% |
| PNG Downloads-1 | 0.209 / 0.211 / 0.218 | 0.62 / 0.68 / 0.58 | 51.7 | 31.718% |

Total bytes over total seconds across the six runs: **PNG 0.21 MB/s
compress, 0.76 self-test; GIF 0.34 and 2.40.** Pinned as `_RECODE_RATE` /
`_RECODE_VERIFY_RATE` `"png"` and `"gif"`, kinds read by content. (A median
of six, the quiet re-measure's method, gave GIF 0.47: it fell between the
two corpora's clusters and put the larger one's expected 76.5 s under all
three of its runs. Review caught it.)

### Against the estimate (branch, byte-weighted rates)

| rows | inside the range |
|---|---|
| `timing2\`, 12 | **12** (PNG expected 49.8 s, measured 46-52; GIF Downloads 100.9 s, measured 104-121; GIF Downloads-1 20.1 s, measured 8.8-13.0) |
| `timing\` (contended), 12 | 10: png-dl1 r3 beside 71% (peak 95%) took 289 s; gif-dl1 r2 at 6% took 6.7 s, 16% under the low end, the 6 MB corpus running 2× faster per byte than the 30 MB one |
| PNGs named `.jpg`, 3 rounds | 3; expected 12.4 s, the one quiet run 17.0 s, the others 35-39 s |
| JPEGs named `.png` (lepton), 3 rounds | 2; round 1 beside 72% took 111.5 s. Lepton's quiet-pinned model, unchanged |
| the two `e2e\` branch runs of those sets | 0: PNGs named `.jpg` 123.5 s (high 49.4), JPEGs named `.png` 90.7 s (high 72.5), both in the afternoon's worst spell. With them, lepton is 2 of 4 |

**The cost follows pixels, not bytes.** The 8 PNGs named `.jpg` expand
~500× at worst and run ~1.4× the per-byte estimate on a quiet machine. A
folder of small, large-canvas images will run slower than expected; the
slow side holds what was measured.

`gui/queue_manager.py` already keeps recoded bytes out of calibration
(`_recode_bytes`, B19), and it reads `recode_cost`, so a PNG-heavy job no
longer teaches Extreme a chain rate several times too slow.

### Found on the way, not fixed here

- **A store-only job's fixed cost.** Stored GIF folders took 17-20 s at
  Extreme (51 s at Insane) against 0.1-0.6 s estimated: the per-job cost the
  model doesn't have (B22).
- **The store-only size estimate misses by a few bytes, both ways**: 141-245
  B high on five corpora (3-64 files), but **16-18 B low** on the 25 M4As.
  Not always the safe direction, though it never moved a decision.
- **Insane on GIF ran 565 s** for 6 MB against 132 s expected (high 313 s),
  with 2.6-4.5 GB free (no paging) and others at 16-75%. One run, so not a
  pin, but 1.8× over the high end is more than contention explains, and
  not by expansion alone: that corpus's `.pcf` was only 1.14× its GIFs
  (2.2× on the Downloads set). zpaqfranz `-m58` on Precomp's pixel output
  ran ~0.011 MB/s where the model bills 0.091 per input byte. Insane on PNG
  (~50× expansion) is unmeasured and likely worse. **This is the opposite
  direction from Insane on packJPG/packMP3 output (estimated 2-3× high).**
  A strict xfail pins the run (`test_insane_on_gifs_holds_the_one_measured_run`);
  B22 takes PNG and GIF on Insane.

---

## 5. B21b (2026-11-12): the probe rule merges, with a way out

§3's rule merged with three fixes the review asked for, all test-first
(`tests/test_b21b_media_fallback.py`):

- **Store instead of refuse.** `engine._plan_that_fits`: when the plan
  doesn't fit the disk, the same files with the probe-flagged media stored
  (`planner.plan(probe_media=False)`) are tried; if they fit, the job runs
  and its warnings say how many files and MiB were stored and why.
  Otherwise the refusal quotes the smaller floor. With the owner's 16 MKVs
  and free space between the two floors, every profile now stores them
  instead of refusing; an MP3 on a Precomp chain stays piped (packMP3).
- **No Extreme for a video folder.** `AnalysisSummary.floor_probe_bytes`
  (bytes piped only by the probe, in formats Precomp can't recode) no
  longer count as a reason for Extreme. The 201 MB MKV sample now
  pre-selects Normal ("Extreme adds only time on video"); an MP3 folder
  still gets Extreme.
- **The gain note** on a mostly-video folder says "a few percent, no more"
  instead of "worth compressing".

**A GUI bug found rendering it**, older than B21: the intake chip took its
total from the summary but was refreshed only when the recommendation moved
the selected profile, so a drop that kept the same recommendation showed
the previous total ("4 items · 228.5 KB" for 521.5 KB) or "0 B". It
refreshes on every analysis now (`tests/test_gui_compact.py`).

Not done: keeping pass-through video out of Extreme's calibration (one
run learned 3.1 MB/s against the 1.41 prior). Recorded for later.
