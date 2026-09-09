# D8 — the flush, the read-back, and the one-byte scare

**2026-09-09**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

D8's brief was one line in the roadmap: *"atomic-write upgrade: temp + `fsync`
+ read-back hash + `os.replace`"*. Two of those four were already there. What
the implementation found was that the two missing ones cost almost nothing, one
of the two present ones had a real defect in it, and the benchmark comparison
produced a one-byte discrepancy that took three measurements to explain.

---

## 1. The defect the item existed for

`compress()` published like this:

```python
if out_path.exists():
    out_path.unlink()
tmp_out.replace(out_path)
```

`os.replace` overwrites an existing file atomically on Windows and POSIX both.
The `unlink` therefore bought nothing, and it opened a window in which a user
overwriting yesterday's archive had **neither file** — the old one deleted, the
new one not yet renamed. The rename is the single moment a whole job's work is
on the line, and this was the one place where failing it also destroyed the
previous copy.

It has been there since the engine's first commit (`e625137`, "atomic
outputs"), untouched through D9 and the K series, because every test asserted
what the *new* archive looked like and none asserted what happened to the
**old** one.

Pinned now by `test_a_failed_publish_leaves_yesterdays_archive_intact`, which
puts sentinel bytes at the output path, makes `os.replace` fail, and requires
them to still be there.

---

## 2. Silesia, normal profile — what the new work costs

Corpus `C:\excmp-bench\silesia`, 12 files, **211,938,580 B** (identical to the
figure B8 recorded). Archive written to `C:`, pipeline temp on `D:` — `C:` had
2.3 GB free and the job needs more than that in temp, which is also why the
total time below is not comparable to B8's.

| | |
|---|---:|
| archive | **48,689,446 B** |
| saved | **77.03%** |
| total job | 116.07 s |
| restore | 12 files, 12 verified, 14.1 s, **12/12 byte-identical** |
| archive flush (`fsync`, 48.7 MB) | **5.3 ms** |
| archive read-back (SHA-256 off the filesystem) | **266.5 ms** (182.7 MB/s) |
| **D8 overhead, total** | **0.272 s = 0.234% of the job** |
| D8 overhead **with `--sidecar`** | **5.3 ms = 0.0046%** |

The second overhead figure is the interesting one. The sidecar used to hash the
published archive itself; the publish now hashes it as the read-back and hands
the digest over, so with a sidecar requested **the read-back is not a new cost
at all** and what remains is the flush. Without a sidecar, D8 costs one extra
pass over the archive: 0.23% here, and it scales with the archive rather than
the corpus, which is the cheap direction.

### A small measured surprise

| what | bytes | fsync |
|---|---:|---:|
| `silesia.excmp.tmp` | 48,689,446 | 5.3 ms |
| `silesia.excmp.sha256.tmp` | 80 | **26.3 ms** |

Flushing the 80-byte sidecar took **five times longer** than flushing the
48.7 MB archive. Nothing is wrong with either number: the archive's pages had
been trickling out to disk during the two minutes it took to write, so its
`fsync` had almost nothing left to do, while the sidecar was created
milliseconds earlier and pays the whole metadata barrier. It is worth writing
down because it inverts the intuition that would otherwise be used to decide
where a flush is "too expensive" — the cost tracks *how recently* the file was
written, not how big it is.

---

## 3. The split path got faster, not slower

`split_file` now flushes each part as it finishes and, if handed a dict,
records each part's SHA-256 from the bytes it just wrote. `write_parts_sidecar`
takes those instead of re-reading the set.

| | |
|---|---:|
| split into 3 × 16 MiB parts | 2.32 s |
| parts sidecar, digests from the split | **15.7 ms** |
| parts sidecar, re-reading every part (old behaviour) | **218.2 ms** |
| digests agree with a fresh hash of every part | yes |

**13.9× on the sidecar**, ~4.2 s per GB of archive saved. Splitting a 4 GB
archive used to read 4 GB, write 4 GB, and then read all 4 GB *again* to learn
digests the split pass had had every byte of in hand.

---

## 4. The one-byte discrepancy, and why it is not a regression

B8 recorded Silesia/normal at **48,689,445 B**. This run produced
**48,689,446 B**. One byte, on the corpus that exists to make estimator
changes comparable — so it had to be explained rather than rounded away.

**Measurement 1 — where the byte lives.** The container has two members:

| member | raw | stored | method |
|---|---:|---:|---|
| `manifest.json` | 2,299 | **1,005** | deflate |
| `payload.7z` | 48,688,221 | 48,688,221 | store |

plus 220 bytes of zip overhead. The compressed data is the payload, and it is
stored, so any change in *compression* would show up there.

**Measurement 2 — the manifest's compressed size moves on its own.** Take this
run's own `manifest.json`, substitute a different `created_utc`, and deflate:
the output length changes by up to 3 bytes with nothing else altered.
Sweeping every second of 2026-09-08 (86,400 timestamps):

| deflated manifest | frequency | implied archive |
|---:|---:|---:|
| 1,000 B | 0.01% | 48,689,441 |
| 1,001 B | 0.20% | 48,689,442 |
| 1,002 B | 0.04% | 48,689,443 |
| 1,003 B | 5.39% | 48,689,444 |
| **1,004 B** | **0.08%** | **48,689,445 ← B8's number** |
| 1,005 B | 48.24% | **48,689,446 ← today's number** |
| 1,006 B | 46.04% | 48,689,447 |

B8's total is exactly what this manifest produces at 67 of the day's 86,400
timestamps. The byte is a wall clock, not a codec.

**Measurement 3 — two runs today, and a second surprise.** Re-running the
identical job:

| run | archive | payload raw/stored | payload CRC32 |
|---|---:|---:|---|
| 1 | 48,689,446 | 48,688,221 | `f516777a` |
| 2 | 48,689,446 | 48,688,221 | **`5f4ddd7c`** |

Same total, same payload **size**, **different payload bytes**. 7-Zip's output
here is length-deterministic and not byte-deterministic.

### The rule that follows

**Compare payload size, never the archive digest, when comparing two
benchmark runs.** An `.excmp` is not reproducible to the byte and was never
designed to be: `manifest.json` carries `created_utc`, and the payload's own
bytes shift between runs. Two consequences:

- A future benchmark that finds a few bytes of difference has found a clock,
  not a codec. Record the payload size — it is the number that means
  something, and it was not recorded before this session.
- `result.sha256` is the identity of *this file*, which is what verification
  needs, and it is **not** a build fingerprint. Nothing should ever compare it
  across runs.

---

## 5. What the implementation corrected about the plan

**1. The read-back does not want an expectation on the plain path.** The first
version hashed the archive after the D9 gate and passed that digest to
`publish` as `expect_sha256`, which reads it back and compares. That is two
full passes over the archive to compare a file against itself: nothing runs
between the two reads, and Python's `write()`/`close()` raise on a full volume
rather than short-writing silently, so the second pass could not detect
anything the first had not. Removed before it was measured — it would have
made D8 cost 0.47% instead of 0.23%, for zero detection.

The expectation is kept exactly where a real gap exists: **with a password**,
where a second pass reads the plaintext back out of temp and writes a
different file. There, `encrypt_file` now takes `expect_src_sha256` (it is
streaming those bytes anyway, so the check is free) and reports the
ciphertext's digest, which the publish read-back then verifies. That closes a
hole nothing had covered: the D9 gate proves a *plaintext* restores, and what
ships is a ciphertext produced afterwards by something the gate never saw.

This is B8's rule arriving from the other direction. B8's lesson was that a
*mechanically correct* proxy can still cost more than it buys; this one is a
check that is mechanically **vacuous** in one branch and load-bearing in the
other, and the resemblance between the two branches is what made it look
uniformly worthwhile.

**2. Windows cannot flush a directory, and that is stated rather than
implied.** A POSIX implementation would `fsync` the parent directory so the
rename itself is durable. There is no directory handle to flush on Windows, so
`excmp/atomic.py` says so in its module docstring instead of leaving a reader
to assume the guarantee is complete. The file's *contents* are flushed, which
is the half that decides whether the archive is readable at all.

**3. Identity beats a second hash — but must never be the thing that
refuses.** After the rename, confirming the destination is the file we just
measured is done with `(st_dev, st_ino, st_size)`, not by hashing it again —
measured on this machine: the Windows file ID survives `os.replace` on the
same volume. A rename cannot alter bytes, so this is complete at no I/O cost,
where re-hashing a 4 GB archive would be minutes.

The first version raised on any mismatch, which was wrong: `st_ino` is a real
file index on **NTFS**, and a synthesised value on **FAT32/exFAT** — which is
what a USB stick arrives formatted as, and copying an archive to one is an
entirely ordinary thing to do. A cheap check that can condemn a good archive
is worse than no cheap check, so a disagreement now re-hashes the destination
and only refuses if the *content* differs. Pinned by
`test_a_filesystem_that_renumbers_the_file_does_not_fail_the_publish`.

**4. The small stores were leaking `.tmp` files on failure.** `calibrate._save`
and `gui/history.append` both did tmp-write-then-replace inside a
never-raises wrapper, so a failed rename left `calibration.json.tmp` /
`history.json.tmp` behind forever. Found by the two tests that assert the
directory contains exactly one file afterwards, not by reading the code.

**5. And a hole this session put there itself, found by auditing the finished
work rather than by the suite.** Both of those stores promise *never to raise*
— they run after a job has already succeeded, and failing to learn from it
must not turn a completed job into a failed one. Both caught
`(OSError, ValueError, TypeError)`. `PublishError` is a **RuntimeError**, so
D8's own read-back had quietly added a way for `calibrate.record()` and
`history.append()` to break their contract: a bad read-back would propagate
out of a finished job. The two tests written against it fail on the tree as I
first wrote it and pass now (`*_never_raises_on_a_bad_readback`). The lesson
is not about exception hierarchies — it is that *adding a check to a path adds
a failure mode to it*, and every caller that was catching by type needed
re-reading, not just the write site.

### One thing left open, deliberately

If the **sidecar** write fails, `compress()` raises after the archive has
already been published — so the user has a good, verified archive and is told
the job failed. That predates D8 (`write_text` could always raise on a full
volume) and D8 adds one more way for it to happen. It is left as it is because
an unwritable sidecar is worth reporting loudly, and inverting it would mean
reporting success while an output the user asked for is missing. Worth a
decision of its own if it ever bites; the honest fix is a result field saying
"archive published, sidecar failed", not swallowing it.

---

## 6. A process note, because it cost a suite run

The full suite failed twice in `tests/test_zstd_window.py` with
`OSError: [Errno 28] No space left on device`, which reads exactly like a
defect in K4's window code. It is not. The suite leaves **400-770 MB per run**
under `%TEMP%\pytest-of-nuhaa` and pytest keeps the last three; two runs
aborted earlier in this session had left their trees behind as well, four
leftovers totalled 2 GB, and `C:` fell to **0.92 GB** free. All 13 tests in
that file pass on a re-run with the directory cleared, and the clean full
pass afterwards was **1,074 passed, 2 skipped, 1 xfailed in 1 h 07 m**.
`tools/corpus_guard.py` reported the real corpora untouched through all of it.

The 31-minute figure often quoted for this suite is a run in which those two
tests failed early and never did their work; a full pass is **an hour**.

Clear that directory before a full run on this machine. `C:` has under 5 GB
free and the suite needs about 1 GB of it.

---

## 7. How to reproduce

```
.venv\Scripts\python.exe -m pytest tests\test_atomic_publish.py -q
```

18 tests: the flush ordering, the short-write refusal, the previous file
surviving a failed rename, the destination-identity check, `atomic_write_text`
(residue, LF endings, old copy intact), the engine's published digest and its
sidecar, the encrypted archive round-trip, the encryption source check, and
four on the two metadata stores - two for a failed rename, two for a bad
read-back.

The Silesia numbers above came from a one-off harness that wraps
`atomic.fsync_file` and `atomic.hash_and_size` with timers and then runs
`engine.compress([silesia], ..., Profile.NORMAL, ctx, sidecar=True)` followed
by a full `extract` and a per-file hash comparison. The corpus is
`C:\excmp-bench\silesia` (kept on disk deliberately — see the handoff).
