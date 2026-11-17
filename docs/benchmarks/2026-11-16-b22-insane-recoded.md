# B22: Insane on recoded media, and a per-job cost (2026-11-16/17)

Machine: Dell Inspiron 15-3567, **Intel i5-7200U, 2 cores / 4 threads**
(`Win32_Processor` checked 2026-11-16), 15.9 GB. Code under test: `main` at
`c30d742` (the bench ran `engine.compress`/`engine.extract` from the main
checkout; the estimator was changed in a worktree meanwhile). Harness:
`C:\excmp-bench\b22\run_insane.cmd` -> `b21_app.py` -> `b13_app.py`
(`engine.compress` with D9, `engine.extract`, an independent SHA-256 of every
restored file), `start /belownormal /wait`, one process at a time,
`C:\excmp-bench\contention.ps1` beside it. **Every row restored byte-identical:
0 mismatches in all 21 valid Insane rows and in 30 tiny-job runs.**

## 1. The question

Insane (`precomp -cn -intense` then zpaqfranz `-m58`) was priced at one chain
rate for every piped byte (0.091 MB/s compress, 0.107 self-test, from Silesia
and an installer sample) plus what the recoder added beyond Precomp's generic
chain. B21 and the 2026-10-17 re-measure had found it **2-3x high on packJPG /
packMP3 output** (two strict xfails), **low on GIF** (one run, 564.7 s against
a 333 s high) and PNG (~50x Precomp expansion) **unmeasured**.

## 2. Rows (compress including D9 / extract, seconds)

CPU share of everything else over each row's window (`contention.tsv`) and the
lowest free memory in it. **The machine was not quiet.** A `find / -iname
*hms*.sql` (another session's, started 00:42, 27,000 CPU-seconds, parent gone)
held ~24% of the CPU through round 1 and most of round 2; the owner stopped
it mid-round-2, with the owner's OK (it is gone from round 3). Free memory fell to 0.5-0.6 GB in
four rows (paging). The reaper killed the batch three times; every killed row
was rerun from scratch. **Quiet row** = the least contended of a corpus
(others about 15% or less, 4+ GB free), marked `*`. Two are borderline,
`gif-dl1` r3 (14-16%, peak 27%) and `png-dl1` r3 (15%, peak 52%), and
`mp3-misc` r2 (mean 10%) had another session's `find`/`du` running in its first
~4 minutes (others 14-45%), which may bias the MP3 rate low.

| corpus | bytes | r1 | r2 | r3 |
|---|---|---|---|---|
| CMYK JPEG `jpg-cmyk2` (2) | 8,386,049 | 86.0 / 30.0 (32%, 4.6 GB) | 94.4 / 49.5 (35%, 5.4 GB) | **56.5 / 26.5 \*** (4%, 5.0 GB) |
| design JPEG `jpg-design` (14 refused + 24 lepton) | 151,290,870 | 1,670.3 / 750.6 (39%, 3.6 GB) | **924.3 / 434.6 \*** (5%, 5.1 GB) | 1,115.6 / 554.3 (17%, 5.1 GB) |
| MP3 `mp3-music` (5) | 33,922,849 | 489.0 / 796.2 (38%, **0.5 GB**) | 1,118.2 / 460.7 (40%, **0.6 GB**) | **312.1 / 148.9 \*** (5%, 4.8 GB) |
| MP3 `mp3-misc` (16) | 80,307,437 | 1,641.5 / 504.9 (41%, 2.6 GB) | 871.8 / 367.4 (10%, 5.8 GB) | **836.2 / 593.2 \*** (17%, peak 48%, 4.5 GB) |
| GIF `gif-dl1` (24) | 5,990,579 | 107.0 / 47.2 (35%, 3.4 GB) | 180.1 / 60.0 (47%, 5.5 GB) | **87.7 / 37.9 \*** (14-16%, 4.9 GB) |
| GIF `gif-dl` (64) | 30,035,992 | 836.0 / 459.9 (37%, **0.5 GB**) | 595.7 / 217.3 (6%, 4.2 GB) | **454.0 / 205.5 \*** (5%, 5.1 GB) |
| PNG `png-dl` (70) | 8,192,542 | 780.6 / 307.7 (35%, 3.0 GB) | 1,621.5 / 1,602.5 (38%, **0.6 GB**) | **565.4 / 260.2 \*** (8%, 4.1 GB) |
| PNG `png-dl1` (80) | 8,181,831 | 753.4 / 436.9 (40%, 3.7 GB) | 2,096.1 / 670.6 (24%, 1.3 GB) | **484.5 / 491.8 \*** (15%, 3.7 GB) |

(The design folder's round 2 first came out as 57,207 s: the machine slept at
19:18 and woke at 10:56 (Kernel-Power 42/107), and `time.monotonic` counted it.
That row is kept as `b13-app-jpg-design-r2.jsonl.invalid-machine-slept` and was
rerun: 924.3 s. Round 3 was run on the five small corpora only, after the
reaper had stopped the large ones three times.)

Sizes are identical across rounds (CMYK 44.691%, design 42.827%, MP3 music
18.971%, MP3 misc 15.835%, `gif-dl1` 11.294%, `gif-dl` 35.144%, `png-dl`
52.549%, `png-dl1` 45.049% saved): only the time moves.

## 3. The rates

Bytes over (compress incl. D9 - extract), and bytes over extract (B17's
method), from the quiet rows; byte-weighted where two corpora disagree:

| kind | compress MB/s | self-test MB/s | total MB/s (compress + D9) | model before (bytes over its expected) |
|---|---|---|---|---|
| **JPEG lepton refuses** (CMYK 8 MB, design 135 MB) | 0.2795, 0.2767: **0.277** | 0.3165, 0.3118: **0.312** | **0.147** | 0.047 (3.1x slow) |
| **MP3** (music, misc) | 0.208, 0.159: **0.171** | 0.228, 0.219: **0.221** | **0.0965** | 0.048 (2.0x slow) |
| **GIF** (`gif-dl1`, `gif-dl`) | 0.1203, 0.1209: **0.121** | 0.158, 0.146: **0.148** | **0.0665** | 0.044 (1.5x slow) |
| **PNG** (`png-dl`, `png-dl1`) | **0.0289** | **0.0339** | **0.0156** | 0.039 (2.5x fast) |

- Two JPEG corpora 18x apart in size give compress rates within 1% of each
  other and self-test rates within 1.5%. The design folder's figures are raw:
  its 24 lepton-packed photos add a few seconds each way, which the model also
  bills through its pack term (about 1% of that folder's time).
- GIF (refit in B24, section 9): with `gif-dl` round 3 at 454.0 s the two
  corpora agree on the compress rate to 0.5% (0.1203 and 0.1209 MB/s) and on
  the total rate to 3% (0.0683 and 0.0662). B22 shipped 0.084 / 0.141 (total
  0.0527), from a `gif-dl` row, 595.7 s at 6% contention, that was not quiet.
- **PNG's split is one corpus's.** `png-dl1`'s extract (491.8 s in r3, 436.9,
  670.6) is as long as its whole compress+D9 (484.5 s), and `png-dl`'s r2
  extract is 1,602.5 s against 1,621.5 s of compress+D9; compress minus
  extract is unusable there. Total rate: over both r3 rows, 0.0156 MB/s, split
  54:46 by `png-dl`'s r3 (305.2 s compress, 260.2 s extract). The total is
  measured; the split is a single corpus's.
- The earlier B18/B19 quiet figures hold: MP3 music 335.3 s (r3 312.1 s),
  design 1,045.8 s (r2 924.3 s).

## 4. What the 564.7 s was

B21 recorded Insane on `gif-dl1` at 564.7 s (one run, 16-75% of the CPU
beside it) against a 333 s high. Three runs now: **87.7, 107.0, 180.1 s**. So
564.7 s was **6.4x the quiet time**, not a rate the model missed, and the
strict xfail's premise did not hold. It is replaced by a test of the three
reproduced rows; 564.7 s stays outside the range (4x on the slow side).

## 5. Contention: how far the high side has to reach

Slow-side multiples of each corpus's quiet row, over the contended rows:
MP3 music 1.6x and **3.6x** (0.5-0.6 GB free), design 1.8x, MP3 misc 1.9x,
CMYK 1.5x and 1.7x, GIF 1.2x, 1.4x and 2.0x, PNG **1.4x, 2.9x, 1.6x and 4.3x**.
`_RECODE_SPREAD` is 4.0. **One row sits 8 s inside the high** (`png-dl1` r2,
2,096.1 s against 2,104 s, 0.4%): it held, but by luck, and a heavier squeeze
would leave it out, as B19's contended design run did (`estimate.py` records
that).

## 6. A fixed per-job cost (item 2)

Near-empty jobs through `engine.compress` (D9 included) and `extract`, three
runs per cell, every file restored: a 2 KB file and twenty 4 KB files at all
four profiles, and the B21 6 MB GIF folder stored at Fast and Normal. How
quiet the machine was is known for the first run only (8 samples: others 9%
mean, 15% max, 4.8 GB free); the contention logger was reaped after it, so the
other runs are unlogged (6.5 GB was free before the batch started).

| job | Fast | Normal | Extreme | Insane |
|---|---|---|---|---|
| 1 x 2 KB | 2.4, 0.5, 0.5 | 1.3, 0.7, 0.7 | 1.9, 0.8, 1.3 | 5.2, 1.1, 3.8 |
| 20 x 4 KB | 1.6, 1.0, 0.8 | 1.0, 1.2, 1.0 | 1.1, 1.7, 1.2 | 3.5, 2.7, 2.2 |
| 6 MB of GIFs, stored | 1.1, 1.0, 1.0 | 0.8, 0.8, 0.9 | | |

**A job costs about a second, and about two at Insane** (zpaqfranz allocates
before it starts). Insane's two cells disagree (medians 3.8 and 2.7 s) and the
second holds ~1.7 s the chain's own rates already bill for its 80 KB, so 2.0 s is
what keeps all six Insane runs (1.1-5.2 s) inside the range. The first run
after idle is the slow one (2.4 and 5.2 s), which the 3x high margin holds. **The handoff's "10-50 s
a job" and "stored GIF folders 17-20 s" did not reproduce**: the stored 6 MB
folder takes 0.8-1.1 s. Whatever made B21's runs slow was not the job. The
model said 0.12 s for that folder and about 0 for the 2 KB file.

## 7. What changed

- `estimate.py`: Insane prices JPEG (lepton-refused), MP3, GIF and PNG at the
  rates above (`_INSANE_RECODE_RATE`, `_INSANE_RECODE_VERIFY_RATE`); the signed
  extras are measured against fixed constants, and `time_split` takes the
  own-rated bytes out of the chain's term, so a learned chain rate moves
  everything but them. (A first version made the extras relative to the
  calibrated chain rate; a test through `queue_manager._time_split` showed the
  progress bar going **negative** after a text job taught Insane 0.16 MB/s.)
  The B20 containers (unmeasured at Insane) keep the chain's rate.
- A fixed per-job term: 1.0 s, 2.0 s at Insane, flat in the range (x0.3 low,
  x3.0 high), not multiplied by the chain's spread; zero for an empty job.
  Calibration no longer learns it as codec time (`queue_manager._calibrate`
  subtracts it; found in review: folded into the learned rate it was counted
  twice, 29% low on an 8 MiB job at 7-Zip's speed).
- Tests: `tests/test_b22_insane_recoded.py` (55), the two strict xfails in
  `test_quiet_rates.py` flipped, the GIF xfail in `test_b21_stored_formats.py`
  replaced by the three reproduced rows.

Model against the quiet rows, Insane, before and after (low / expected /
high):

| corpus | quiet | before | after |
|---|---|---|---|
| CMYK | 56.5 | 115 / 180 / 418 | 37 / 59 / 235 |
| MP3 music | 312.1 | 453 / 712 / 1,634 | 216 / 354 / 1,414 |
| MP3 misc | 871.8 | 1,071 / 1,686 / 3,868 | 511 / 835 / 3,338 |
| design | 924.3 | 1,860 / 2,913 / 6,785 | 593 / 935 / 3,724 |
| GIF 6 MB | 87.7 | 82 / 137 / 333 | 65 / 116 / 461 (B24: 57 / 92 / 366) |
| GIF 30 MB | 454.0 | 413 / 686 / 1,668 | 325 / 572 / 2,287 (B24: 281 / 453 / 1,811) |
| PNG 8 MB (`png-dl`) | 565.4 | 125 / 209 / 544 | 331 / 527 / 2,107 |
| PNG 8 MB (`png-dl1`) | 484.5 | 124 / 209 / 543 | 330 / 526 / 2,104 |

(Before: the quiet CMYK, MP3 and design rows sat **under the low end**, and
`png-dl`'s 565.4 s above the high of 544. "After" includes the fixed term of
section 6. Its tiny-job ranges, low / expected / high: 1 x 2 KB at Extreme
0.30 / 1.00 / 3.00, at Insane 0.63 / 2.04 / 6.09; 20 x 4 KB at Insane
1.65 / 3.67 / 9.65, against runs of 3.5, 2.7 and 2.2 s, so that cell is about
1.4x high.)

## 8. Not done

- (Done in B24, section 9: round 3 for the design, MP3 misc and `gif-dl`
  corpora.)
- The B20 containers at Insane (unmeasured): they keep the chain's rate, and
  their share of a job's calibration subtraction follows the old extras.
  Insane on a pass-through mix.
- A quieter MP3 rate: `mp3-misc` r3 (836.2 s, others 17%, peak 48%) is the
  fastest of its three rows but not a quiet one.
- The tiny-job rows beyond the first are unlogged for contention.
- Why B21's stored-GIF folders took 17-20 s.

## 9. Round 3 of the three large corpora (B24, 2026-11-17)

The reaper had stopped round 3 of these three corpora three times, so each
rested on one least-contended row. Run later the same day (the logger on; the
reaper stopped the batch once more after the first row, and the dead staging
dir, 19 files, 228,265,325 B, went to the trash folder; the rest ran
unattended). Every file restored, 0 mismatches.

| corpus | round 3 compress / extract | others mean / peak | free | the row it replaces as fastest |
|---|---|---|---|---|
| GIF `gif-dl` (30 MB) | **454.0 / 205.5 s** | 5% / 17% | 5.1 GB | 595.7 s (6%) |
| MP3 `mp3-misc` (80 MB) | 836.2 / 593.2 s | 17% / 48% | 4.5 GB | 871.8 s (10%) |
| design JPEG (151 MB) | 1,115.6 / 554.3 s | 17% / 60% | 5.1 GB | none: 924.3 s stays the fastest |

- **GIF moved: the 595.7 s row was not quiet.** The model's GIF rate (0.0527
  MB/s total) was 26% under the two corpora's agreed 0.0665. Refitted:
  compress **0.121**, self-test **0.148** MB/s (`_INSANE_RECODE_RATE` /
  `_INSANE_RECODE_VERIFY_RATE`). Against the quiet rows: `gif-dl` 453 s modelled
  for 454.0, `gif-dl1` 92 s for 87.7 (it was 0.77x and 1.04x).
- **MP3 holds**: round 3 is 4% under the old quiet row; byte-weighted over the
  fastest rows (312.1 and 836.2 s) the total is 0.0995 MB/s against the 0.0965
  the model uses, 3% apart. Left alone.
- **JPEG holds**: the design folder's round 3 was slower than its quiet row.
- **24 valid rows now (3 rounds x 8 corpora), 0 mismatches.** The contended
  rows of every corpus are inside the range: MP3 misc 1,641.5 and 871.8 s,
  design 1,670.3 and 1,115.6 s, `gif-dl` 836.0 and 595.7 s.
- **A "quiet" row at 6% contention was 31% slow.** What the others' CPU share
  and free memory do not show (cache, thermal state, the other session's I/O)
  is not in the protocol. The fastest row of three is a floor, not a
  measurement of a quiet machine, and a corpus with one row is a guess.
