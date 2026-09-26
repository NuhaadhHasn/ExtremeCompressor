# B12 — LOLZ against `precomp → 7z`, on two corpora, and why the second one matters

> **Superseded on the verdict, not on the numbers (2026-09-23).** This
> round's conclusion, that LOLZ "qualifies as an Insane-tier alternative", did
> not survive the next measurement. Against zpaqfranz, Insane's actual final
> codec, `-m5` is smaller on both corpora below. See
> [2026-09-23-b12-round3](2026-09-23-b12-lolz-vs-zpaqfranz.md).

**2026-09-20**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

The 2026-09-11 session measured LOLZ against **7-Zip alone** and found a
per-category specialist: +11.93% on an x-ray image, −2.93% on English prose.
It closed by naming the measurement that would actually decide the item:

> It was not compared against the real route. 7-Zip alone is not what this app
> ships — `precomp → 7z` is. […] That is the next measurement, and it is the
> one that decides whether any of this becomes code.

That measurement is below. Every LOLZ row was decompressed and SHA-256
compared before its number was allowed to count, and the deflate corpus was
carried all the way back through `precomp -r` to the original bytes.

---

## 1. Headline: it wins on both corpora, and only one of those wins matters

**Corpus A — deflate.** Silesia zipped by 7-Zip (`64,726,889 B`, the exact B16
corpus), then `precomp -cn -intense` → `236,958,376 B`.

| final codec | archive | vs best 7-Zip | compress |
|---|---:|---:|---:|
| `7z -mx9 -mmt1` | **51,820,126** | baseline | 162.7 s |
| `7z -mx9 -mmt2` | 51,827,136 | +0.01% | 107.6 s |
| **`lolz -d64m`** (single-threaded) | **50,233,466** | **−3.06%** | 776.7 s |
| `lolz -d64m -mt2` | 50,797,463 | −1.97% | 772.3 s |

**Corpus B — real installers.** 13 files / 55,733,142 B chosen from the live
`Programs` folder by `excmp.sample.pick_sample` (I6's own sampler), tarred to
`55,743,488 B`, then `precomp -cn -intense` → `62,482,862 B` (1.12×).

| final codec | archive | vs 7-Zip | compress |
|---|---:|---:|---:|
| `7z -mx9 -mmt1` | **46,048,116** | baseline | 28.0 s |
| `7z -mx9 -mmt2` | **46,048,116** | *byte-identical* | 13.3 s |
| **`lolz -d64m`** | **45,933,664** | **−0.249%** | 186.4 s |
| `lolz -d64m -mt2` | 46,052,632 | **+0.01% (loses)** | 157.9 s |

Every LOLZ archive above restored byte-identically. The deflate one went the
whole way home: `cls-lolz d` → `.pcf` identical → `precomp -r` → **the original
64,726,889 B, SHA-256 `4e874e8d…c19d`**.

---

## 2. The verdict, which is not the one the first corpus suggested

**3.06% is a deflate-stream result. On the data this app is actually for, the
win is 0.249% — 114,452 bytes out of 46 MB — for 6.7× the compression time.**

That is the difference between "the first specialist to beat `precomp → 7z`"
and "wins, but by an amount inside the margin of a dictionary-size choice".
One corpus would have shipped the first sentence.

**It is still a win, and this project has said out loud that slow-and-smaller
is the axis it optimises** — B16 declined to credit xtool for being 1.95×
faster on exactly that reasoning. So LOLZ is not rejected the way xtool was.
It qualifies as what the roadmap already specified: **an Insane-tier
alternative to the 7-Zip stage, never a default, degrading when absent.**
Whether 0.25% is worth 6.7× on installer data is the owner's call, and the
numbers to make it now exist.

### Three findings that fall out of the table

- **`-mt2` costs LOLZ ratio.** 1.12% on the deflate corpus, 0.26% on the
  installers — enough to turn its win into a loss on corpus B. Its default
  `-mt1` is its best setting, and anyone wiring it in must not "helpfully"
  hand it the project's calibrated two threads.
- **`-mmt` costs 7-Zip almost nothing.** Byte-identical on corpus B, 7,010 B
  (0.014%) on the larger corpus A. The round-1 thread asymmetry was not the
  explanation for anything.
- **Precomp finds very little in installers** — 1.12× inflation, against 3.66×
  on the deflate corpus. The two corpora are stressing different things, which
  is exactly why both were run.

---

## 3. `-intense` is in the app's chain and it costs 82 KB here

Worth recording because it corrects a number in a committed document. B16 ran
`precomp -cn`; `excmp/stages/precomp.py:46-48` actually runs **`-cn -intense`**,
which is what was used here.

| | `.pcf` | → `7z -mx9 -mmt2` |
|---|---:|---:|
| B16, `precomp -cn` | 236,956,196 | **51,745,050** |
| today, `precomp -cn -intense` | 236,958,376 | 51,827,136 |

`-intense` finds 25 of 28 extra zlib streams, inflates 2,180 bytes further, and
the final archive comes out **82,086 bytes bigger**. Not chased here — it is a
Precomp tuning question, not a B12 one — but **B16's 51,745,050 is not the
figure the shipped chain produces**, and anything comparing against "our route"
should use 51,827,136 or re-run it.

---

## 4. The failure mode any integration has to handle

Probed deliberately, because the project's rule is that exit codes cannot be
trusted:

- `cls-lolz_x64.exe` given a **corrupted** `.lolz` **segfaults (rc 139) and
  still leaves a 0-byte output file.**
- Given a **nonexistent** input it **silently creates a 0-byte output** and
  returns −1, printing nothing to either stream.
- Both binaries return −1 on their usage path, which Bash reports as 127 — the
  same code as "command not found".

So a stage that checks "did the output file appear?" — which is what
`PrecompStage` does at `excmp/stages/precomp.py:60` — passes both failures.
The post-restore SHA-256 gate is genuinely the only thing that catches this,
which is the standing rule restated with a fresh example.

`cls-lolz_x64.exe` also prints **nothing at all** — no banner, no version, no
usage. Its version has to come from `lolz_x64.exe` or from the file hashes.

---

## 5. Provenance

`C:\Users\nuhaa\Downloads\Compressed\lolz22c4b.7z`, 437,444 B, sha256
`ac6730b3041a3a05b62ec6a033e9447f7dc87171751c19704ee10d7eb0093cb6` — verified
today, matches the pin recorded on 2026-09-11. Extracted to
`C:\excmp-bench\lolz\`; 8 files, 1,421,541 B:

```
749,056  pack/lolz_x64.exe        1a70827ef4062f8bb744a4b9d944e13f9b48453970e3c910268bd276399c8d42
343,040  unpack/cls-lolz_x64.exe  d92f7c60256509f74e36d9b5aab041fe44999b1a3910d70aa83c9d01f062ea29
312,320  unpack/cls-lolz_x86.exe  6ea07aa4f5565ac289402ade3b2e52bf8089ad6185e0ecf0e1f36cea39c091a9
 16,384  unpack/cls-lolz.dll      87df573ac240e09ea4941e169fb2d15d5316a1b0e053446b8144e04b1154f061
```

`lolz v22c4b [Dec 30 2018 16:44:58]`, closed source, a forum download. Its
defaults are **`-d16m` and `-mt1`** — the `-d64m` used throughout here is a
non-default and omitting it silently measures a different codec. The shipped
`pack.bat` / `unpack.bat` cannot run: they call `arc.exe` and `unarc.exe`,
neither of which is in the distribution, and both begin by clearing `PATH`.

---

## 6. What is still not established

- **No DXT or game data.** LOLZ's headline claim is its texture and raw-graphic
  models and **none of that has been tested** — the same corpus gap that blocks
  B6 and B13.
- **LOLZ has never been measured against `zpaqfranz`.** If it goes in as an
  Insane-tier option, Insane's current final codec is zpaqfranz, not 7-Zip.
  That comparison is the one that decides where it actually belongs, and it has
  not been run.
  **→ Run 2026-09-23, and it decided against LOLZ:** zpaqfranz `-m5` is
  smaller on both corpora, and `-m4` is 7.3% smaller on this deflate corpus.
  See [2026-09-23-b12-round3](2026-09-23-b12-lolz-vs-zpaqfranz.md).
- **Wall times from ~20:57 onward were taken with the full pytest suite running
  on the same two cores.** That covers `lolz -mt2` on corpus A and every corpus
  B row. Sizes are unaffected — all four rows reproduce byte-for-byte — and
  corpus B's 7-Zip and LOLZ rows were contended equally, so the 6.7× ratio
  holds. The absolute seconds do not.

---

## 7. Reproducing it

Scripts are in the session scratchpad (`b12_run.py`, `b12_round2.py`); the raw
logs and a machine-readable table are at `C:\excmp-bench\b12\`:
`b12-log.txt`, `b12-results.json`, `b12-round2-log.txt`, `b12-round2.json`.

```
precomp.exe -cn -intense -o<out>.pcf <in>
7z.exe a -t7z -mx9 -bsp1 -y -mqs -mmt1 <out>.7z <out>.pcf
lolz_x64.exe -d64m <out>.pcf <out>.lolz
cls-lolz_x64.exe d <out>.lolz <back>        # run from the unpack dir, CLS.ini beside it
```

…and then compare SHA-256, every time, because nothing above reports its own
failure.
