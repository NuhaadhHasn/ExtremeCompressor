# General-purpose "extreme" compression landscape, state 2026

> **⚠ Source-study update (2026-07-31):** corrections from the line-by-line
> source studies (docs 13-21, read
> [21-source-study-synthesis.md](21-source-study-synthesis.md) first) are
> flagged inline as **[SOURCE-STUDY …]**.

## The ratio-vs-time spectrum (mixed real-world data, rough orders)

| Method | Ratio vs 7z-max | Speed | RAM | Notes |
|---|---|---|---|---|
| zstd -19 --long=31 | ~5–10% worse | **10–30× faster** | ~2–4 GB | BSD, maintained, the "fast" profile |
| 7z LZMA2 `-mx=9 -md=192m` | baseline | baseline | dict×~10 compress | LGPL, maintained, safe default "extreme" |
| zpaqfranz -m5 | ~5–15% better on dedup-heavy data | slower | several GB | maintained, journaling+dedup built in |
| PAQ8px / cmix | 10–25% better | **100–1000× slower**, GBs of RAM | impractical | leaderboard toys, not product material |
| lolz / RAZOR | ~10–20% better on game data | slow | high | closed/frozen — not buildable-on |

Context-mixing champions (PAQ/cmix) win benchmarks but take *days* per GB — they can be an
"Insane (bragging rights)" preset at most, and only for small files.

## Useful preprocessors/filters that are safe to use

- **BCJ2 / exe filters** (built into 7-Zip): +5–15% on executables — free win.
  **[SOURCE-STUDY ⚠ the % figure is benchmark-derived — 7-Zip's source carries NO
  percentage claims (doc 19 §4). And it's not automatic: 7z only auto-selects BCJ2
  at mx≥8 *with* the MT mixer, else plain BCJ — pass `-mf=BCJ2` explicitly]**
- **Delta filter**: helps on some tables/audio.
- **Precomp/xtool recompression**: the big win on game-style data (see doc 02).
- **wav→FLAC / TAK** routing: lossless ~40–60% on raw audio found in corpora.
- **Dedup before codec**: SREP (frozen) vs `zstd --long` vs zpaqfranz dedup (maintained).
  **[SOURCE-STUDY ✓ SETTLED — doc 20 §4: SREP dropped (closed, no license); lrzip
  rejected (GPL + hard-POSIX, no Windows path); `zstd --long=31`/7z big-dict for
  ≤2 GB distances + zpaqfranz CDC for unlimited distance is the final answer]**

## Practical profile ladder for the app

| Profile | Pipeline | Expected feel |
|---|---|---|
| Fast | zstd -19 --long=31 | Minutes, good ratio |
| Normal | 7z LZMA2 -mx=9 (multithreaded) | Baseline extreme |
| Extreme | precompress (precomp/xtool) → dedup → 7z LZMA2 -md=192m+ | Hours on big inputs, repack-class ratio on game data |
| Insane | precompress → dedup → zpaqfranz -m5 | Overnight+, maximum practical |

All profiles must show ETA estimates and warn when input analysis predicts near-zero gain
(already-compressed data).

## Output format decision inputs

- Plain `.7z`/`.zpaq` outputs = openable by standard tools, zero lock-in, but cannot express
  a *multi-stage* pipeline (precomp+srep steps need reversal order and tool versions).
- Repack world solves this with installers (Inno Setup + custom decompression DLLs).
- Sane modern equivalent: **a manifest** — `archive.7z` + `archive.excmp.json` (or a small
  header container) recording the exact stage chain, tool versions, and hashes so extraction
  is deterministic and verifiable. Self-extracting `.exe` can come later.
