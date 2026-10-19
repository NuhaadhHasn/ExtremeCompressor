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

*(pending: `media\*.jsonl`)*

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
- **The store-only size estimate is 171-245 B high** on 8-64 files, 4-21 B
  per file; the safe direction.
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
