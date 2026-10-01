# 2026-10-01: default threads measured, real music measured, new target machine

**This laptop, from today: Dell Inspiron 15-3567, Intel i5-7200U (2 cores /
4 threads), 15.9 GB RAM, Kingston 960 GB SSD, Windows 10 Pro 19045.** The
owner confirmed it's the target from now on. Until 2026-09-27 Windows
reported an i7-3540M, so **every timing in earlier records is an i7-3540M
number.** Sizes and peak RAM don't depend on the CPU; times do.

Tools: 7-Zip 26.02, zpaqfranz v64.8j, Precomp, zstandard (in-process).

---

## 1. Default threads: the docs said 2, the code let 7-Zip take 4

CLAUDE.md said "Default threads is 2, not 4". The code's default was 0,
which every stage passed through as "tool's choice", so 7-Zip took all 4
logical processors. Measured with the exact switches `SevenZipStage` builds
for the 7z format (`a -t7z -mx9 -bsp1 -y -mqs`), varying only `-mmt`. Every
archive was restored with `7z x` and SHA-256 compared, and peak working set
was read from the exited process handle.

| input | `-mmt` | archive | peak RAM | compress |
|---|---|---:|---:|---:|
| 645 MB installers, 3 LZMA2 blocks | none (old default) | 635,994,583 | 5,549 MiB | 176.1 s |
| | 4 | 635,994,583 | 5,738 MiB | 183.3 s |
| | **2** | **635,110,280** | **2,702 MiB** | 309.1 s |
| | 1 | 635,108,251 | 2,695 MiB | 628.6 s |
| Silesia tar, 212 MB, 1 block | none | 48,680,741 | 2,089 MiB | 142.7 s |
| | **2** | 48,680,741 | 2,088 MiB | **114.3 s** |
| | 4 | 48,680,741 | 2,089 MiB | 173.2 s |

"None" is byte-identical to `-mmt4`. With two threads, the multi-block input
came out **0.14% smaller** than the old default at **under half its peak RAM**,
and 1.75× slower. On a single-block input the bytes and RAM matched, and two
threads was the fastest setting. One thread saves another 2,029 B in 645 MB
at twice the time again.

**Decision:** "auto" now gives 7-Zip one thread per physical core (2 here),
passed explicitly. That's the smallest archive measured short of `-mmt1`, the
RAM fits a 16 GB machine with room to spare, and it's what zpaqfranz already
does with no switch. Fast's in-process zstd keeps its own default
(`threads=-1`), which hasn't been measured against 2. The table's RAM cell,
the Advanced panel's note, the spinbox labels ("auto (2 cores)") and the
big-job recommendation now count physical cores too. Before, the
recommendation said "on 4 cores" to a 2-core laptop.

### The backtest, re-measured on this machine with the new default

Same six files, same measurement (`engine.compress` wall time with the D9
gate), three runs each, median pinned:

| profile | archive | runs | median | old pin (i7-3540M, 4 threads) |
|---|---:|---|---:|---:|
| Normal | 707,893,728 | 100.3 / 70.1 / 91.0 s | **91.0 s** | 100.7 s |
| Extreme | 706,559,667 | 454.1 / 475.4 / 334.5 s | **454.1 s** | 355.9 s |

Normal's bytes are unchanged: 160 MB piped is one LZMA2 block. Extreme pipes
444 MB (423 MiB), already more than one block, and that's where two threads
trades time for RAM. All 8 backtest tests pass against the new pins with the
shipped estimator unchanged. The corpus guard was clean around the run.

---

## 2. B13: real music, and what the app was doing with it

### The corpus

18 files from **Wikimedia Commons**, downloaded with the owner's approval and
verified against the SHA-1 Commons publishes for each: **13 Ogg Vorbis and
5 Opus, 169,975,314 B**. They span 86 kbps to 1.4 Mbps and include
orchestral, jazz, electronic and indie recordings, plus 78 rpm transfers.
Manifest: `C:\excmp-bench\b13\commons-manifest.json`. Results:
`C:\excmp-bench\b13\run\b13-music.jsonl`.

### The finding

The handoff predicted "high-bitrate Vorbis is expected near 0%". On real
music it wasn't quite:

| | archive | vs input |
|---|---:|---:|
| the app before, Normal (all 18 stored) | 169,982,319 | **+0.004%** (larger) |
| 7-Zip `-mx9 -mmt2`, per file, summed | 167,385,777 | −1.52% |
| zstd 19, per file, summed | 167,223,990 | −1.62% |
| 7-Zip solid, all 18 | 167,384,496 | −1.52% (no cross-file gain) |

Every restore was byte-identical. The gain was concentrated, and **the
analyzer's own probe had already found it**:

| probe `sample_ratio_max` | 7-Zip | file |
|---:|---:|---|
| 0.9487 | −5.98% | Paul De Bra – Haydn 83 |
| 0.9768 | −4.47% | NBC – Toscanini / Horowitz |
| 0.9782 | −3.93% | Victor Concert Orchestra 1917 |
| 0.9894 | −2.63% | Musopen – Mendelssohn 3 |
| 0.9971 | −1.68% | Evergreen – Haydn 104 |
| 1.0 (the other 13) | −1.24% to +0.02% | the five Opus files are 0.00–0.02% |

### The change

**An Ogg file (`.ogg`, `.oga`, `.opus`) whose own probe says it shrinks is
now piped, and the rest stay stored.** It's checked before the entropy rule,
because Ogg's framing makes the bytes look random, and the probe is a
measurement of the file rather than a statistic about it. It's restricted to
Ogg because Ogg is the only compressed-media format measured. Video, JPEG
(lepton's route), MP3 and the rest are unchanged until they're measured too.

**After, end to end through `engine.compress`, 18/18 restored and verified:**

| profile | archive | saved | piped | time |
|---|---:|---:|---:|---:|
| Fast | 168,023,577 | 1.148% | 50,386,789 | 52.8 s |
| Normal | 168,085,761 | **1.112%** | 50,386,789 | 45.2 s (was 20.0 s stored) |
| Extreme | 168,085,621 | 1.112% | 50,386,789 | 54.6 s |

That's 1.9 MB saved, where before the archive grew by 7 KB. Only the 30% of
bytes the probe flagged pays the codec's time. Piping all 18 would have taken
1.52% for the full 7-Zip time on 170 MB.

### What B13 itself still needs

This settles the general-codec question for Ogg. **balrogg**, a dedicated
Vorbis/Opus recompressor claimed at up to 15%, is still the open part, and it
needs the owner to sign in to krinkels.org. This corpus is now the gate it
has to beat: 1.112% end to end, every byte restored.

---

## 3. Reproducing it

- Threads: `C:\excmp-bench\b17\threads_7z.py` → `threads\threads-7z.jsonl`
- Backtest: `C:\excmp-bench\b17\backtest_remeasure.py` → `backtest-remeasure.jsonl`
- Music: `C:\excmp-bench\b13\fetch_commons.py` (download and verify),
  `b13_music.py` (baseline), `b13_after.py` (after the rule)
