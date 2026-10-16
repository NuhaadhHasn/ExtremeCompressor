# 2026-10-17: the quiet-machine re-measure of B13's, B19's and B20's time priors

**Machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads), 15.9 GB
(`Win32_Processor` checked). **Quiet, as far as this machine gets:** Docker
Desktop and WSL were stopped (the owner's doing, not this session's), and a
CPU log beside the runs (`C:\excmp-bench\contention.tsv`, every 15–30 s)
put the other processes at **6–32% of the four logical CPUs per row, about
12% typically** (Chrome, Explorer, IntelliJ, another Claude session). The
B19/B20 afternoon had WSL's `vmmem` alone near 50%. One caveat: Defender's
process is protected, so its CPU doesn't appear in that log, and a few rows
ran 3–4× slow with nothing visible beside them. Every bench process ran at
below-normal priority. `main` at `763f046` (B19 + B20).

Harness: `C:\excmp-bench\quiet\run_quiet.cmd`, B19's `b19_app.py` (B13's
`b13_app.py` underneath: `engine.compress` with D9, `engine.extract`, an
independent SHA-256 of every restored file). **Three rounds, each running
every measure once**, so a busy spell spreads across all the priors instead
of landing on one prior's three runs. Phase times come from the app's own
progress events (`C:\excmp-bench\phase_rates.py`, which reproduces B19's
recorded 0.41 / 0.83 MB/s from B19's own rows): the pipeline phase runs from
the start to the first pack event, or to D9 when nothing is packed. Rows:
`C:\excmp-bench\quiet\e2e\`, summary `quiet\rates.jsonl`, contention per row
`quiet\contention_by_row.py`.

**37 rows, 0 mismatches.** Every archive is within 4 bytes of the earlier
runs on the same corpus (B13, B18, B19, B20), and repeats differ by 0–3
bytes, so only the times moved.

---

## 1. What was measured (median, then the range of three)

| prior | corpus | profile | phase | median | range |
|---|---|---|---|---:|---:|
| packJPG (`_RECODE_RATE["jpeg"]`) | design, 151 MB (135.5 piped) | Extreme | compress | 1.027 MB/s | 0.574–1.032 |
| | other CMYK, 8.4 MB | Extreme | compress | 1.133 MB/s | 0.839–1.252 |
| packJPG self-test | design / CMYK | | D9 | 0.934 / 1.133 MB/s | 0.890–1.355 |
| packMP3 (`_RECODE_RATE["mp3"]`) | MP3 music, 33.9 MB | Extreme | compress | 1.225 MB/s | 0.308–1.385 |
| | MP3 misc, 80.3 MB | Extreme | compress | 1.131 MB/s | 1.034–1.411 |
| packMP3 self-test | music / misc | | D9 | 1.461 / 1.521 MB/s | 1.015–1.695 |
| lepton (`_LEPTON_*`) | phone, 150 files, 49.1 MB | Fast | pack / D9 | 21.6 s / 13.3 s | 15.6–22.4 / 9.4–17.9 |
| | web, 299 files, 20.4 MB | Fast | pack / D9 | 19.2 s / 14.1 s | 14.9–21.0 / 13.2–14.8 |
| balrogg decode (`_PACK_DECODE_RATE`) | B13 music, 170 MB | Normal | D9 | 181.2 s = 0.94 MB/s | 122.1–182.7 s |
| B20 containers (`_RECODE_RATE["zip"]`) | AAR / APPX / EPUB / NuGet, 1.4–6 MB | Extreme | compress | 0.177 / 0.315 / 0.195 / 0.263 MB/s | 0.084–0.514 |

Across both corpora: **packJPG 1.03 MB/s compress, 1.02 self-test (six
runs); packMP3 1.18 and 1.49.** The contended priors were 0.41 / 0.83 and
0.35 / 0.72, so **compress was 2.5–3.4× slow**. Lepton, fitted as bytes plus
a per-file cost through both corpora's medians (the counts the model sees):
**pack 3.25 MB/s + 0.043 s/file, decode 6.2 MB/s + 0.036 s/file**, against
2.3 + 0.04 and 5.8 + 0.04 contended. That fit then predicts the design
folder's 24 photos at 5.9 s against 4.5–6.3 s measured. **Balrogg's decode
went the other way:** D9 took 181 s for 170 MB (0.94 MB/s, extract 0.88)
against the 1.5 MB/s B13 took from the CLI per file. B13's contended runs
had suggested it might be ~3× slower; through the app on a quiet machine,
it's 1.6×.

**The containers did not get faster.** On the quiet night the 1–6 MB
samples ran 0.08–0.51 MB/s, under the afternoon's contended 0.26–0.79. On
jobs that small a fixed start-up cost, which the model doesn't have,
outweighs the rate. The same night's big containers (B20 record §8: two
AABs, 121 MB, and a 36.8 MB ODT) ran 0.446 and 0.439 MB/s, so
**0.46 stands**, and so does the 1.5 MB/s self-test (AAB 1.68).

---

## 2. What changed in `excmp/estimate.py`

- `_RECODE_RATE` jpeg 0.41 → **1.03**, mp3 0.35 → **1.18** MB/s;
  `_RECODE_VERIFY_RATE` jpeg 0.83 → **1.02**, mp3 0.72 → **1.49**; zip
  unchanged.
- `_LEPTON_PACK_RATE` 2.3 → **3.25** MB/s, `_LEPTON_PER_FILE_S` 0.04 →
  **0.043**, `_LEPTON_DECODE_RATE` 5.8 → **6.2**,
  `_LEPTON_DECODE_PER_FILE_S` 0.04 → **0.036**.
- `_PACK_DECODE_RATE` 1.5 → **0.94** MB/s.
- **The recoders' time gets its own spread, on the slow side.** Pinning the
  quiet rates alone would have pushed B18's contended MP3 run (179.9 s) 56%
  over the new high end, and the night's own 144 s outlier out too. The
  range only spread the chain's codec term, and the recoders swing ~4× on
  this machine. The high end now spreads the time the recoders pace,
  compress and self-test (`recoded_seconds()`: their extras plus the chain's
  share of their bytes, capped at the generic Precomp chain's rate so that
  Insane's slower zpaqfranz keeps its own term), by **`_RECODE_SPREAD =
  4.0`**: B18's contended packMP3 run (0.30 MB/s) against the quiet median.
  **The low end is the chain's as before**, because the priors are quiet
  medians and contention only slows a job down. `expected` is unchanged in
  form.

**Against every end-to-end row there is** (`main`'s code against the
branch's, `C:\excmp-bench\est_check.py`; after: `quiet\est_after.txt`):

| rows | time outside the range, before | after |
|---|---:|---:|
| the night's quiet rows (35) | **12**: CMYK ×3, MP3 music ×2, MP3 misc ×3, Insane MP3, Insane design, AAR, EPUB | **4**: Insane MP3 and design (under the low end, §4), AAR 72.1 s and EPUB 64.7 s (6 MB jobs, a few seconds over) |
| B18/B19/B20 contended rows (13) | 2: B19's 1,749 s design run, a 64 KB ODT | the same 2 (the design run overlapped GUI renders and tests; the ODT is all start-up) |

The expected figure now lands near the quiet medians: MP3 music 52 s against
51.1 s, misc 122 against 126.8, CMYK 16 against 15.0, design 274 against
283.8, Ogg 509 against 485.5, AAB 344 against 343.3. Before: 144, 341, 31,
506, 374, 344. The low ends stay under the fastest runs and near them:
design 179 s (fastest 279), MP3 music 32 (44.8), misc 75 (107), CMYK 11
(14.5). Rendered in both themes: design at Extreme reads "~5 min, 2–19 min"
(4.7 min quiet, 9.1 contended), the CMYK pair "~20s, a few seconds – 2 min"
(15 s / 28 s).

**Photo folders, though, now come out 15–19% under their quiet runs as a
whole** (phone 35.9 s against 44.1, web 33.6 against 39.5; inside the
range). The pack and D9 phases fit exactly, but each job spends 6–10 s
outside them (analysis, the archive itself) that the model bills at under
a second. The contended constants had been absorbing it. The phases are what
the progress bar's pack band reads, so they stay true, and the gap goes with
the fixed per-job cost the model lacks (§5).

---

## 3. A defect the faster rates exposed

`recommend_profile` picks between "Small enough that the full chain costs
seconds" and "Precomp recodes these files slowly — minutes, not seconds" by
`strongest_recode_seconds ≥ 60`. That field held only the recoders' *extra*
over the chain rate, compress side. At 0.41 MB/s the extra on 50 MB of CMYK
was 86 s, so the sentence was right by accident. At the measured rate it's
13 s, and the folder was told "seconds" for a job the model itself puts at
~98 s. B19's own test caught it on the first run.

The review then showed it was never only about recoders: 25 MB of CMYK
beside 35 MB of text (the table says ~2 min), 30 MB of MP3 beside 30 MB of
text (~2 min), and 60 MB of Ogg that balrogg repacks (~5 min) were all told
"seconds", on `main` too. "Seconds" is a claim about the whole job, so the
summary now carries the strongest plan's whole expected time
(`strongest_seconds`), and the sentence reads that. It names Precomp's
recoders as the cause only when their time is at least half the job;
otherwise it says "the full chain still takes minutes here".

---

## 4. Insane on recoded media: the estimate is 2–3× high

| Insane | measured | estimate before | after |
|---|---:|---|---|
| MP3 music, quiet (one run) | 335.3 s | 498–1,785 (805) | 453–1,634 (712) |
| MP3 music, contended (B18) | 1,025.4 s | 498–1,785 | 453–1,634 |
| design JPEGs, quiet (one run) | 1,045.8 s | 1,954–6,955 (3,144) | 1,860–6,785 (2,913) |

**Both quiet runs finish under the low end, before and after.** Insane
bills recoded bytes at `precomp+zpaqfranz`'s Silesia rate (0.091 MB/s
compress, 0.107 self-test), and on packJPG/packMP3 output the whole pipeline
ran at 0.26 and 0.19 MB/s. A first version of this change spread the
recoded time both ways and so "held" these rows, but only by widening the
range to 731–11,636 s; the review called that what it was. One run per media
type is too thin to pin a rate for zpaqfranz on recoded output, so both
rows are a strict xfail in `tests/test_quiet_rates.py` that will flip when
someone measures it. Insane also bought nothing on the design JPEGs
(42.827% against Extreme's 42.829%; B19 record).

---

## 4a. The review

Two reviewers (the estimator's arithmetic and data; the consumers and the
tests), every finding reproduced before its fix. The arithmetic itself was
clean: 4,000 random plans across every profile and seven rate variants
(calibrated, zero, fallback), `expected` equal to `time_split` and to the old
formula to 1e-12, low ≤ expected ≤ high throughout; rerun after the fixes.

| finding | evidence | fix |
|---|---|---|
| the "seconds" sentence ignored everything but recoders | the three folders in §3, "seconds" beside ~2–5 min | the whole job's time (§3) |
| a symmetric spread emptied the low end | design low 71.5 s, fastest run 279 s | high side only |
| on Insane the "recoded" time was 95% zpaqfranz, and its self-test got spread too | design high 6,955 → 11,636 s | the chain's share capped at the generic Precomp rate |
| the edited B19 bar test could no longer fail | it compared `summarize` with the call it makes | asserts the bar's halves hold the recoded files' whole time |
| comments claimed 4.0× was the slowest run, and blamed start-up for the small containers | B19's 0.09 MB/s run; a 64 KB ODT takes ~2 s | reworded |
| photo folders 15–19% under as a whole | §2 | recorded (§5), not tuned away |
| the suggestion reads default rates, the table calibrated ones; the recode extras sit on a fixed 1.41 MB/s base | a learned `precomp+sevenzip` of 4 MB/s would bill packJPG at 1.95 MB/s | recorded (§5): this machine has learned no Precomp rate yet |

---

## 5. Left open

- **Insane's rate on recoded media**: three quiet runs each on JPEG and MP3
  output would pin it (the xfail above).
- **A fixed per-job cost**: photo folders spend 6–10 s outside the phases
  the model knows, a 64 KB ODT ~2 s on start-up, and two 6 MB containers
  ran 3–4× slow for no visible reason.
- **Calibration and the recoders**: the extras are measured against a fixed
  1.41 MB/s base, so a learned Precomp rate would speed packJPG up with it;
  and `summarize` reads default rates where the table reads calibrated
  ones. Neither shows until this machine learns a Precomp chain's rate.
- **Defender's share is invisible** to the contention log. The 3–4× slow
  rows (`mp3-music-q3`, `aar-q3`) had no visible CPU beside them.
- Balrogg's encode-side rates (`_PACK_ENCODE_RATE`) weren't re-measured. The
  pack phase at Normal ran 246–372 s against the model's 325 s (with the new
  decode rate), inside its range.
