# B12, round 3 — LOLZ against zpaqfranz, the codec it would actually displace

**Measured 2026-09-23, one row finished 2026-09-26**, this laptop (2-core
i7-3540M, 16 GB, Windows 10 Pro 19045). zpaqfranz **v64.8j** (`tools/bin`),
LOLZ **v22c4b** (the pinned distribution at `C:\excmp-bench\lolz\`, hashes in
[2026-09-20-b12](2026-09-20-b12-lolz-vs-precomp-7z.md) §5).

The 2026-09-20 session measured LOLZ against `precomp → 7z` and closed on:

> LOLZ has never been measured against `zpaqfranz`. If it goes in as an
> Insane-tier option, Insane's current final codec is zpaqfranz, not 7-Zip.
> That comparison is the one that decides where it actually belongs.

That comparison is below. **It decides against LOLZ.** Every zpaqfranz and
LOLZ row was restored and SHA-256 compared against its input `.pcf` before its
size was allowed to count. The 7-Zip rows are carried over from 2026-09-20 and
were never restore-verified (`restore_ok: null` in `b12-round2.json`). Peak
memory is `PeakWorkingSetSize` read from the exited process
handle — the `tools/ram_backtest.py` method, not a sampled poll.

---

## 1. Headline

**zpaqfranz `-m5` is smaller than LOLZ on both corpora.** On the installers it
wins by 18,297 bytes (0.04%) — a tie in practice. On the deflate corpus it wins
by **7,039,003 bytes (14.0%)**. And the zpaqfranz setting Insane already ships,
`-m4`, beats LOLZ by **7.3%** on the deflate corpus while losing to it by 0.56%
on the installers.

LOLZ doesn't win anywhere by a margin that matters, and it loses badly on
one of the two corpora. **B12 closes as measured and not integrated.** No stage
was written.

---

## 2. Corpus B — real installers

13 files / 55,733,142 B picked from the live `Programs` folder by
`excmp.sample.pick_sample`, tarred, then `precomp -cn -intense` →
`programs.pcf`, **62,482,862 B**, SHA-256 `c2e96779…9782e` — the exact
intermediate the 2026-09-20 rows used.

| final codec | archive | vs 7-Zip | vs Insane today | compress | restore | peak RAM (c / x) |
|---|---:|---:|---:|---:|---:|---:|
| `7z -mx9` (Extreme) † | 46,048,116 | baseline | −0.31% | 13.3–28.0 s | — | — |
| **`zpaqfranz -m4 -t2`** (**Insane today**) | 46,191,810 | **+0.31%** | baseline | **119.0 s** median of 3 | **110.5 s** median of 3 | 441 / 396 MiB |
| `zpaqfranz -m4 -t1` | 46,191,810 | +0.31% | *byte-identical* | 111.6 s | 115.0 s | 442 / 395 MiB |
| **`zpaqfranz -m5 -t2`** | **45,915,367** | **−0.29%** | **−0.60%** | 359.7 s | 297.9 s | 895 / 850 MiB |
| `lolz -d64m` | 45,933,664 | −0.25% | −0.56% | 106.8 s ‡ | **0.4 s** | 653 / 118 MiB |
| `zpaqfranz -m0` → `lolz -d64m` | 45,966,694 | −0.18% | −0.49% | 1.0 + 112.2 s | 0.3 + 0.7 s | 647 / 117 MiB |

† From 2026-09-20; its times were taken while the pytest suite shared both
cores, so they are a range, not a figure.
‡ One run today, uncontended. The 2026-09-20 run of the same command took
186.4 s under contention. Treat 106.8 s as one data point, not a pin.

The three `-m4 -t2` repeats took 119.0, 134.9 and 115.1 s to compress
(1.17× spread) and 136.9, 110.5 and 106.9 s to restore, on byte-identical
input, with the file already in cache (a straight read of the 62 MB input took
0.58 s). The repeats are there because a single run is not a timing.

## 3. Corpus A — deflate

B16's Silesia zip (64,726,889 B, 7-Zip deflate) → `precomp -cn -intense` →
`fresh.pcf`, **236,958,376 B**, SHA-256 `c0fc71cb…c0984` — again the exact
intermediate from 2026-09-20.

| final codec | archive | vs 7-Zip | vs Insane today | compress | restore | peak RAM (c / x) |
|---|---:|---:|---:|---:|---:|---:|
| `7z -mx9 -mmt1` † | 51,820,126 | baseline | +11.26% | 162.7 s | — | — |
| `7z -mx9 -mmt2` (Extreme) † | 51,827,136 | +0.01% | +11.28% | 107.6 s | — | — |
| `lolz -d64m` † | 50,233,466 | −3.06% | **+7.85%** | 776.7 s | 5.6 s | — |
| **`zpaqfranz -m4 -t2`** (**Insane today**) | 46,575,605 | **−10.12%** | baseline | 168.4 s | 186.2 s | 915 / 786 MiB |
| `zpaqfranz -m4 -t1` | 46,575,605 | −10.12% | *byte-identical* | 241.2 s | 176.7 s | 421 / 786 MiB |
| **`zpaqfranz -m5 -t2`** | **43,194,463** | **−16.65%** | **−7.26%** | ~541 s § / 1,070.4 s ¶ | 1,076.7 s / 986.5 s ¶ | 1,819 / 1,691 MiB |

† From 2026-09-20. LOLZ's restore time is `cls-lolz d` back to the `.pcf`, as
recorded in `b12-results.json`.
§ From file timestamps, not a timed run. The `-m4 -t1` archive finished at
15:15:39 and its restore took 176.7 s, so `-m5` started at about 15:18:37. Its
archive's last write was 15:27:38.
¶ Timed on 2026-09-26, while the read-only doc-audit agents for this record were
running on the same two cores. The timed compress took twice as long as the
timestamp estimate from 2026-09-23, on byte-identical input with an identical
output size. **Neither figure is a clean measurement of `-m5`'s speed.** B17
has to re-time it on a quiet machine, with repeats. The sizes are not in
doubt: both runs produced 43,194,463 B and both restored byte-identically.

The `-m5` archive above was compressed on 2026-09-23, and that session
ended part-way through restoring it. The Python harness stopped with exit
code 4 and printed no traceback. That is consistent with the process being
killed when the session went away, but it doesn't prove it. The rows
already written survived, because each was appended to the log as it
landed. The row in flight lost its compress time. **Its size was not used
until the archive had been restored and hashed**, which happened on
2026-09-26 (1,076.7 s, byte-identical). A second compress run that day
reproduced the size exactly, 43,194,463 B, and restored byte-identically
too (986.5 s).

**There is no `-m0 → lolz` row for corpus A.** It was scheduled as the next
step after `-m5`, and the interrupted 2026-09-23 run never reached it. It was
**deliberately not re-run** on 2026-09-26. The combination's whole premise is
that zpaqfranz's dedup finds something to hand LOLZ, and here it finds almost
nothing: the `-m4` run reports `236,958,376 -> 236,952,106`, which
is 6,270 bytes of dedup across 237 MB. There is nothing for the combination to
exploit, and on corpus B, where dedup found 692,231 bytes, the combination
still *lost* to plain LOLZ (see §4).

---

## 4. What the tables say

### LOLZ doesn't belong in Insane

Swapping zpaqfranz `-m4` for LOLZ would take 0.56% off installer archives
and **add 7.85% to deflate-rich ones**. And that 0.56% is available without
LOLZ: `-m5` gets 0.60%. There's no corpus measured here on which LOLZ is the
right Insane final codec.

### It doesn't belong beside Extreme either

The remaining argument would be "an opt-in LOLZ alternative to 7-Zip in
Extreme". On installers that buys 0.25% over Extreme. But Insane at `-m5`
buys 0.29%, and on deflate data 16.66% where LOLZ buys 3.07% (both measured
against Extreme's `-mmt2` archive, 51,827,136 B). Someone who
wants smaller than Extreme is better served by Insane in both cases, so a
LOLZ option would be a third place to be slow without being smallest.

**That argument depends on Insane gaining `-m5`.** At today's `-m4`, LOLZ
is the smallest codec measured on installers: 0.25% under Extreme and 0.56%
under Insane. If B17 keeps `-m4` and offers no `-m5` at all, that small niche
is unmatched again. The roadmap records this as B12's second reopening
condition.

### zpaqfranz's dedup doesn't help LOLZ

`-m0` (content-defined dedup, no compression) found **692,231 bytes** on corpus
B — the zpaqfranz status line reads `62,482,862 -> 61,790,631`. Feeding that
deduplicated stream to LOLZ came out **33,030 bytes bigger** than giving LOLZ
the `.pcf` directly. The likely reason is that LOLZ runs its own long-distance
matchfinder (`-ldmf`, on by default per its settings banner) and already finds
those repeats. The byte counts are measured. That explanation is a reading of
the banner, not something tested here.

### The finding worth more than the verdict: `-m5` is not a niche

The zpaqfranz stage runs `-m4` on research/20's advice. Its Gotchas section
says: "Don't assume `-m5` ≫ `-m4` … On 2 cores, -m4 is the realistic Insane
default." §8's recommendation is "`-m4 -t2`; `-m5` only for small precious
sets". That advice came from reading source. This is the first measurement of it, and it is half right:

| | `-m5` vs `-m4`, size | compress time | restore time | peak RAM (compress) |
|---|---:|---:|---:|---:|
| corpus B, installers | **−0.60%** | 3.02× | 2.70× | 2.0× |
| corpus A, deflate | **−7.26%** | 3.2× § to 6.4× ¶ | 5.3–5.8× ¶ | 2.0× |

(§ and ¶ as in §3: the deflate timings aren't clean, and the sizes are.)

On installers the source reading holds: 0.6% for three times the wait. On
deflate-expanded data it doesn't. 7.26% is more than twice LOLZ's best
corpus-level result against `precomp → 7z` (3.06%), and Insane is already
labelled "an overnight job". **Whether Insane should move to `-m5` is its own
item** (filed as B17 in the roadmap), and it gets the same treatment as
everything else. That means measuring it end to end through `engine.compress`
on both corpora, and checking the D9 verify time, before any default changes.
**Nothing was changed on the strength of these two corpora.**

### Threads cost zpaqfranz nothing, unlike LOLZ, and the app never sets them

`-m4 -t1` and `-m4 -t2` produced **byte-identical archives on both corpora**.
zpaqfranz compresses independent 64 MiB blocks, so thread count changes only
how many blocks are in flight. On corpus B, which is a single block, `-t2`
bought no speed (111.6 s vs a 119.0 s median). On corpus A, four blocks,
it cut the time from 241.2 s to 168.4 s for about 2.2× the peak RAM. This is the opposite of
LOLZ, where `-mt2` cost 0.26% to 1.12% of ratio (2026-09-20).

**The app doesn't pass `-t` at all by default.** Its threads setting defaults
to 0 ("each tool chooses") in the CLI, the GUI's Settings tab and the Advanced
panel, and `ZpaqfranzStage` emits no `-t` for 0. zpaqfranz then chooses 2
threads on this laptop. Measured on a 1 MB file: no switch reports `2T`,
`-t1` reports `1T`, `-t2` reports `2T`, and `-ht` reports `4T`. So it counts
physical cores, not the "all cores" research/20 §8 read from the source.
**The `-t2` rows above are therefore what default Insane runs on this
machine**, even though it gets there through zpaqfranz's default rather than
a setting of ours.

### LOLZ's one real distinction is how fast it restores

LOLZ decoded corpus B in **0.4 s**. zpaqfranz took 110.5 s at `-m4` and
297.9 s at `-m5`, because context mixing is symmetric and runs the whole
model again on the way out. That's a 276× gap at `-m4`. On corpus A it was
5.6 s for LOLZ against 186.2 s. This matters twice over here, because the D9
gate replays the full restore before every publish, so each Insane job pays
zpaqfranz's decode time once before the user sees anything.

**It is not a reason to integrate LOLZ now.** B12 was about ratio, and on
ratio LOLZ is beaten. A "fast-to-extract strong codec" is a different
question with different competitors, and nobody has asked it yet. It's
recorded here so the number isn't lost.

---

## 5. What is still not established

- **No DXT or game data.** LOLZ's headline claim is its texture and
  raw-graphics models, and this is still untested. It's the same corpus gap
  that blocks B6 and B13. If a game corpus arrives, the rematch is **LOLZ
  against zpaqfranz `-m5`**, not against 7-Zip. Anything less repeats the
  mistake this round corrected.
- **Two corpora, again.** The verdict holds on both, which is why it's worth
  stating. It is still two corpora.
- **LOLZ's dictionary was not swept.** Every row is `-d64m`, the setting the
  first two rounds used. Corpus B's 62 MB fits inside it anyway. Corpus A's
  237 MB does not, and a larger `-d` might close part of the 7.3% gap to
  `-m4`. Closing the 14.0% gap to `-m5` would take more than a dictionary.
  (Both are measured against LOLZ's archive: `-m4` is 7.3% smaller than LOLZ,
  and `-m5` is 14.0% smaller.) This
  is recorded as an unmeasured possibility, not a result.

---

## 6. Reproducing it

The scripts (`b12z_run.py`, `b12z_m5_redo.py`) and the raw rows
(`b12z-results.jsonl`, one JSON object per line, with every exit code, peak
working set and restore verdict) are all in `C:\excmp-bench\b12z\`, beside
the archives they produced. `b12z_run.py` reads its `.pcf` inputs from
`C:\excmp-bench\b12\`.

```
zpaqfranz.exe a <out>.zpaq <in>.pcf -m4 -longpath -t2      # = default Insane here (2T)
zpaqfranz.exe a <out>.zpaq <in>.pcf -m5 -longpath -t2
zpaqfranz.exe x <out>.zpaq -to <dir> -longpath              # then SHA-256 the one file
zpaqfranz.exe a <out>.zpaq <in>.pcf -m0 -longpath -t1       # dedup only, no compression
lolz_x64.exe -d64m <in> <out>.lolz
cls-lolz_x64.exe d <out>.lolz <back>
```

zpaqfranz's `-m0` is confirmed to be dedup-and-store by its own status line,
`(1.000.000 -> 1.000.000 -> 1.001.157)` on a 1 MB smoke file. `-store` is
the switch that disables dedup as well.
