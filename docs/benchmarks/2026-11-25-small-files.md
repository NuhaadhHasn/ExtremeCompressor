# Many small files: fewer opens, and a per-file term in the time estimate (2026-11-25)

Machine: Dell Inspiron 15-3567, i5-7200U (2 cores / 4 threads), Windows 10 with
real-time protection on. **Not a quiet machine**: a second agent was running
its own jobs on the same two cores for the whole session, taking turns on a
shared lock. Every figure is wall time of `engine.compress` (analysis, codec,
D9 self-test and publish) in a fresh process. Before and after were run
interleaved, the order swapped each round; medians of three.

## Where the time went

A profile of the 1,801-file job at Fast put it in per-file work, not the
codec: 10,776 `open` calls (six a file), two `realpath` calls per path check,
a staging copy of every file. A probe then found the largest single cost:

| operation on a 24 KB file | per file |
|---|---|
| create and write | 0.9 ms |
| **first read after it was written** | **14.8 - 19.4 ms** |
| second read | 0.3 ms |
| the same first read, 2 / 4 at a time | 10.1 - 11.2 / 7.9 - 14.5 ms |
| create, then read back through the same handle | 1.0 ms |

The first open of a file that has just been written waits on the scanner. The
self-test restores every file and then opens it to hash it, and a staged copy
is opened by 7-Zip the same way.

## What changed

- Analysis reads the head and the samples through one handle (was two).
- A piped file's ledger SHA-256 is taken by the read that archives it: the
  tar/zstd stage reads the sources directly and hashes the buffers it writes
  (no staging copy at Fast, Extreme or Insane); the staging copy, where one
  is still made, hashes what it copies.
- Normal: 7-Zip reads the sources in place from a list file when every input
  shares one parent folder; otherwise, or if 7-Zip does not exit 0, the files
  are staged as before. Our hashing read comes first and the D9 gate is what
  proves the two reads agreed.
- `safepath.Within`: the destination is canonicalized once per pass; every
  name is still validated and every target still canonicalized and compared.
- The self-test hashes files of 1 MiB or less four at a time (same function,
  same files, same comparison); it no longer sets mtimes on a restore it is
  about to delete.

Opens of 1,801 files at Fast: 10,875 before, 7,291 after (counted).

## Before and after (medians of three, seconds; runs in brackets)

| corpus | profile | before | after | |
|---|---|---|---|---|
| Python source, 1,801 files, 43.4 MB (`.venv` pip, setuptools, cryptography, PIL) | Fast | 41.0 (53.6, 39.5, 41.0) | 19.6 (22.4, 18.1, 19.6) | 2.1x |
| | Normal | 45.6 (55.9, 40.0, 45.6) | 27.2 (30.2, 27.2, 26.7) | 1.7x |
| node_modules, 3,912 files, 20.6 MB (`@upstash`; 2,580 piped, 1,332 stored) | Fast | 98.0 (110.1, 98.0, 97.3) | 36.2 (35.1, 36.2, 38.6) | 2.7x |
| | Normal | 78.3 (84.0, 74.3, 78.3) | 47.4 (47.4, 42.9, 56.8) | 1.7x |
| installers, 13 files, 55.7 MB (`C:\excmp-bench\b12\programs`), the big-file control | Fast | 3.3 (3.3, 3.1, 6.1) | 3.6 (5.4, 3.2, 3.6) | no difference these runs can resolve |
| | Normal | 5.1 (5.1, 4.7, 5.6) | 4.2 (4.2, 4.2, 5.7) | |

Every archive passed D9. The Fast payload is the same stream as before (the
tar members, order, modes and times are those of the staged tree; pinned by a
test); the timed "after" runs predate a fix to the mode bits of
`.exe/.bat/.cmd/.com` members and were 26 and 11 bytes off for that reason.

## The per-file term

`estimate._PER_FILE_SECONDS = (0.003, 0.0057)`: 8.7 ms a file, charged for
files past the 24 that B22's fixed second already covers, with margins
0.3x / 2.5x. Residual = (median - the byte-only estimate) / (files - 24):

| tree | profile | files | byte-only estimate | measured median | residual | new expected | new range |
|---|---|---|---|---|---|---|---|
| python 1,801 | Fast | 1,801 | 3.9 | 19.6 | 8.9 ms | 19.4 | 6.8 - 46.7 |
| python 1,801 | Normal | 1,801 | 15.9 | 27.2 | 6.4 | 31.4 | 13.4 - 69.4 |
| node 3,912 | Fast | 3,912 | 2.0 | 36.2 | 8.8 | 35.8 | 11.1 - 89.2 |
| node 3,912 | Normal | 3,912 | 5.4 | 47.4 | 10.8 | 39.3 | 13.0 - 95.7 |
| python 2,245 (hypothesis, pygments, _pytest, PyInstaller; 21.4 MB) | Fast | 2,245 | 2.4 | 20.0 | 7.9 | 21.8 | 7.0 - 53.8 |
| | Normal | 2,245 | 8.3 | 22.6 | 6.4 | 27.7 | 10.3 - 65.0 |
| repo docs+tests+gui+excmp, 307 files, 5.8 MB | Fast | 307 | 1.3 | 3.9 | 9.1 | 3.8 | 1.2 - 9.6 |
| | Normal | 307 | 2.4 | 4.9 | 8.7 | 4.8 | 1.8 - 11.7 |

Checked, not fitted:

- Extreme: repo 9.1 s (8.3 - 9.6) against 14.8 expected; python 1,801 took
  34.6 s and node 40.3 s against 53.9 and 45.8. Their second runs, beside a
  heavy job (analysis alone took 72 s on the node tree), took 141.1 and
  253.2 s; the first is inside the range (146.8 s high), the node one is
  outside it (118.1 s high).
- Stored mid-sized files run over the figure, inside the range: 238 PNG/GIF
  (52.4 MB) 5.2 s (5.1 - 6.0) against 3.9; 150 phone photos with lepton off
  5.9 s (5.2 - 6.5) against 3.1, high 6.7. Analysis samples up to 1 MiB of
  each file and that is not modelled.
- Insane on the 307-file repo tree took 259 and 343 s (two runs) against
  139.6 expected, range 86 - 410: inside the range, 1.9 - 2.5x over the
  figure. The per-file term is 2.5 s of that; the rest is zpaqfranz's own
  rate on a small job and is not addressed here.

## Left out

- Reading each restored file back through the handle that wrote it would
  remove the scanner wait (1.0 ms against 15 - 19 ms a file), but the digest
  would then be taken before the restore has finished writing, and a later
  member can alias an earlier one. The gate keeps its separate pass.
- Hard-linking instead of copying into the staging tree: deleting a link to
  a read-only file clears the attribute on the source.
