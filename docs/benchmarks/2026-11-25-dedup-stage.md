# 2026-11-25: B31, a long-range block dedup stage in front of 7-Zip at Extreme

**Machine:** Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads), 15.9 GB, Windows 10, shared with
other sessions. 7-Zip 26.02, Precomp from `C:\Program Files\precomp` (the unpinned copy). Every row
is `engine.compress` at Extreme (D9 self-test included), then a user-side `engine.extract`, then an
independent SHA-256 of every restored file against its original
(`C:\excmp-bench\b29\scratch-dedup\measure.py`, on a frozen copy of the branch's code, one row at a
time under `C:\excmp-bench\b29\timing.lock`). "Without" is the same code with the stage switched off
(`engine._with_dedup` replaced by the identity), which is the chain every earlier build ran.
**10 rows on 5 corpora: 0 mismatches.**

## The gap

LZMA2 finds a repeat only inside its dictionary, 256 MiB at `-mx9`. `Backup_of_menu card.cdr` and
`menu card.cdr` (154.8 MB and 154.7 MB, two versions of one CorelDRAW file) reach 7-Zip as a 666 MB
Precomp stream in which the second copy starts about 330 MB after the first. SREP covered this
until B11 removed it for failing a restore.

Scanned with the new chunker (8 KiB average), that stream holds **327.3 MB of repeated chunks, 317.6 MB
of them further back than 256 MiB**, in 340 runs. The raw tar of the same two files holds only 8.6 MB:
the repeats exist after Precomp opens the deflate streams, not before.

One thing that was *not* true and is therefore not in the code: 7-Zip does not lose repeats at
256 MiB block boundaries. 160 MiB of random bytes written twice (320 MiB) came out at 167,807,761
bytes at both `-mmt2` and `-mmt1`, so it found a repeat 160 MiB back across the 256 MiB mark.
Distance is the only limit.

## Results

Archive bytes are exact and do not depend on what else the machine was doing. Times do.

| corpus | input | stream to 7-Zip | archive without | archive with | change |
|---|---:|---:|---:|---:|---:|
| menu-card pair (2 files) | 309,440,083 | 666,478,338 -> 339,684,843 | 222,142,873 | **112,033,110** | **-110.1 MB (-49.6%)** |
| My Graphical Projects (123 files) | 666,560,229 | 1,616,219,515 -> 1,046,272,637 | 370,481,927 | **258,443,387** | **-112.0 MB (-30.2%)** |
| two versions of a folder (143 files) | 299,737,367 | 860,767,744 -> 312,029,207 | 104,549,736 | **54,189,813** | **-50.4 MB (-48.2%)** |
| apk set (11 files), control inside the window | 119,982,781 | 219,045,131 (not read) | 34,868,943 | 34,868,943 | 0 |
| unique text (5 files), control past the window | 335,544,320 | 335,554,560 (read, left alone) | 257,635,717 | 257,635,717 | 0 |

"Two versions of a folder" is the B27 jar and zip sets (71 files, 149.9 MB) beside a copy in which
three archives were rebuilt with one member edited, one file removed and one added
(`scratch-dedup\mkversions.py`): a different kind of repeat from the design files, whole files and
deflate members that are identical before Precomp as well as after.

| corpus | compress s (without / with) | of which 7-Zip | dedup stage | D9 self-test | extract | peak RAM, compress (tree) |
|---|---|---|---:|---|---|---|
| pair | 526 / 401 | 190 / 73 | 24.1 s | 65 / 51 | 43 / 70 | 2,738 / 2,678 MiB |
| My Graphical Projects | 1,267* / 710 | 359 / 165 | 84.9 s | 253 / 264 | 185 / 220 | 2,730 / 2,741 MiB |
| two versions | 1,891 / slept* | 270 / 109 | 39.1 s | 181 / 206 | 212 / 170 | 2,742 / 2,646 MiB |
| apk (control) | 186 / 164 | 82 / 52 | 0 (not read) | 31 / 40 | 25 / 33 | 2,184 / 2,186 MiB |
| unique (control) | 316 / 398 | 271 / 321 | 10.9 s (scan only) | 33 / 56 | 28 / 61 | 2,673 / 2,610 MiB |

\* **Not clean timings.** The design "without" row ran beside another job (system 73% busy against
41% for its "with" row; its Precomp took 625 s against 412 s), so 1,267 s overstates it; the
like-for-like part is 7-Zip's own time, 359 s against 165 s. The machine **slept through the
"two versions, with" row** (Precomp reads 64,205 s), so its compress total is discarded; its dedup
and 7-Zip stage times were taken after it woke. The apk rows differ by 30 s in 7-Zip on identical
input, which is the size of the noise on this machine: no time difference under about 20% means
anything here.

What the times do support:

- **7-Zip's time falls with the bytes it is handed**: 190 -> 73 s, 359 -> 165 s, 270 -> 109 s.
- **The stage itself costs 19 to 28 MB/s of stream** when it runs to the end (scan, write, and its
  own restore check): 666 MB in 24.1 s, 861 MB in 39.1 s, 1,616 MB in 84.9 s.
- **Restore is not faster and may be slower.** The rebuilt stream is as long as it ever was and
  Precomp still has to re-deflate all of it; the stage adds one more copy. Extract read 43 -> 70 s,
  185 -> 220 s and 212 -> 170 s: no consistent direction, inside the noise.
- **Peak RAM is 7-Zip's** (2.6-2.7 GiB at `-mx9`, two threads) with or without the stage. The
  Python process peaked at 62-64 MiB while the stage ran, against 31-36 MiB without it. The stage
  never runs at the same time as 7-Zip or Precomp.

## What it costs where there is nothing to find

- A stream no larger than the dictionary is **not read**: the apk rows are byte-identical
  (34,868,943) with no stage record.
- A larger stream with no far repeats is read once and then left alone: 335 MB of seeded random
  text in 5 files was scanned in **10.9 s (30.8 MB/s)**, found 0 MiB of repeats, and produced the
  same 257,635,717 bytes with no stage record and no warning. (Its 7-Zip stage read 271 s without and
  321 s with on identical input, and its extract 28 s against 61 s: the other session's job was
  running, and that is noise, not the stage, which had already finished.) So unique data past the
  window pays about one second per 30 MB of stream, and nothing in bytes.

## Insane

Not changed. zpaqfranz deduplicates at any distance itself (content-defined fragments against the
whole archive), so the stage is offered only in front of 7-Zip. The research run that prompted this
reported the pair at 150.5 MB for one copy and 157.8 MB for both under `zpaqfranz -m1`; that was
**not re-measured here** (zpaqfranz is not installed where this worktree looks for it), and it is a
lead, not a figure.

## Not measured

- One quiet timing round per row, no repeats: the times are single runs on a shared machine.
- No corpus above 2 GB of stream, so the chunk-size doubling (above 4 GiB) has only unit tests.
- An explicit small dictionary (`-md=64m`) widens what the stage finds; only tested at 1 MiB in the
  unit tests, not benchmarked.
