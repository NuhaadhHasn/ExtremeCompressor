# Benchmark: B1 — the zpaqfranz stage (Insane made real)

- Machine: Nuhaadh-Laptop, Intel i7-3540M (2C/4T), 16 GB, threads=2
- Date: 2026-09-02
- Tools: 7-Zip **26.02**, Precomp, zpaqfranz **v64.8j**
- Every number below includes the D9 pre-publish gate (full restore +
  SHA-256 against the ledger) **and** a second, independent extract-and-hash
  by the harness.

**Headline: the stage works and every restore was byte-identical — and it did
not earn its place in the Insane chain on this data.** Recording that plainly
because the roadmap predicted the opposite.

---

## Corpus B — 163 MB, 5 installers, no cross-file duplication

The same 5 files B11 used, so the numbers are directly comparable.

| profile | chain | final bytes | saved | compress+verify | extract | verified |
|---|---|---|---|---|---|---|
| extreme | `precomp → sevenzip` | 95,089,705 | **41.75%** | 254.0 s | 56.2 s | 5/5 |
| insane | `precomp → zpaqfranz` | 96,676,610 | **40.77%** | 593.3 s | 269.1 s | 5/5 |

| comparison | delta |
|---|---|
| zpaqfranz vs 7-Zip, ratio | **−0.97 points** |
| zpaqfranz vs 7-Zip, compress | **2.3× slower** |
| zpaqfranz vs 7-Zip, extract | **4.8× slower** |

### Two findings that contradict the plan

**1. The 3.5 points SREP took away came back without zpaqfranz.** B11 recorded
this corpus at 41.39% with SREP and 37.91% without. Extreme now measures
**41.75%** on an *unchanged* chain — better than the SREP era ever was.

The most likely cause is the **7-Zip 24.07 → 26.02** upgrade that happened
this session. It is **not confirmed**: 24.07 is no longer installed, so there
is no A/B, and other code has moved since August. Recorded as the leading
hypothesis, not as a fact. If it matters later, pin both 7-Zip builds and
re-run — that is a cheap experiment we simply have not done.

**2. zpaqfranz `-m4` is a worse final codec than LZMA2 `-mx9` on this data,
and much slower.** Not a defect: after Precomp there is a single tar stream of
five *distinct* installers, so CDC dedup has nothing to find, and what is left
is a straight CM-vs-LZMA2 contest that LZMA2 wins here. research/20 §8's
warning that `-m5` is not worth 2-3× the CPU on two cores looks, if anything,
too generous about `-m4`.

---

## Corpus D — 52 MB, deliberately 49% exact duplicates

Built to make dedup pay: two files present twice, the realistic "downloaded it
twice / kept a copy in another folder" case.

| profile | final bytes | saved | compress+verify | extract | verified |
|---|---|---|---|---|---|
| extreme | 49,146,313 | 5.22% | 5.7 s | 1.7 s | 5/5 |
| insane | 49,156,048 | 5.21% | 11.4 s | 5.5 s | 5/5 |

**Both profiles saved ~5% on a corpus that is nearly half duplicate bytes.**
That is the interesting result, and it is not zpaqfranz's fault.

### Why: the store route never reaches the deduplicator

```
pipeline  stages=['precomp','zpaqfranz']  files=3  bytes=4,295,711
store     stages=[]                       files=2  bytes=47,559,664
    HandBrake-1.8.2-x86_64-Win_GUI.exe
    HandBrake-copy-in-another-folder.exe
```

The two identical 23.8 MB executables are high-entropy, so the analyzer routes
them to **store** — copied verbatim into the container, correctly, because
recompressing them gains ~0%. But stored files never enter the pipeline, so
**no compression stage can ever see that they are identical.** We write both
copies in full.

The 1.8 MB Composer pair *was* piped, and *was* deduplicated. That is the
entire 5.2%.

**This is a bigger prize than B1 was.** We already compute a SHA-256 for every
file — it is the ledger, the thing the whole product is built on. Two ledger
entries with the same hash are the same bytes, by definition. Storing one copy
and pointing both names at it is nearly free, exactly lossless, and would have
saved **45% of corpus D** where both compressors managed 5%. Filed as **G9**.

It also reframes the SREP story: SREP sat *inside* the pipeline too, so it
never saw stored duplicates either. Long-range dedup between installers was
never the thing that was missing.

---

## What B1 actually delivered

- **Insane is real.** `precomp → zpaqfranz` runs, and both corpora restored
  **5/5 byte-identical** under an independent SHA-256 check. The profile no
  longer prints *"zpaqfranz backend not integrated yet"* while quietly running
  the Extreme chain.
- **Dedup demonstrably fires** where it can reach the data
  (`test_dedup_actually_finds_distant_duplicates`: the same blob twice in one
  stream compresses to under one copy).
- **It is not currently the right default**, and the docs now say so.

## Two bugs found by running it, not by testing it

**The D9 gate refused to publish a broken archive.** The first Insane run died
in `_verify_before_publish` with `precomp: restore produced no output`. No
`.excmp` was written. That gate is the thing we said must never be weakened,
and it paid for itself on the first codec added after the licence rules were
relaxed.

The cause: **zpaqfranz stores the absolute path it is handed**, drive letter
mangled (`C:` → `C_`), and `add` has no switch to store a relative one — it
resolves the argument before recording it, so `cwd` does not help either. So
`x -to <dir>` faithfully rebuilds `<dir>/C_/Users/…/payload.pcf`, which (a)
can exceed `MAX_PATH`, and Precomp is not long-path aware and *exits 0 while
producing nothing*, and (b) as a final stage would bury every file under a
`C_` prefix where no ledger key could match it. `-flat` is not a fix: it
base64-mangles names into `00000001_00152_c2luZ2xl.pcf`.

**Fix:** zpaqfranz is deliberately **not** tree-capable, so a tar always
precedes it and it only ever receives one file; `extract` then relocates that
single file to its real name. Dedup is unaffected — CDC works on the byte
stream, so identical fragments inside the tar are still matched.

**A chain could end on an intermediate stage.** `_resolve_chain` drops a stage
whose tool is missing; applied to the new Insane chain with zpaqfranz absent
that left `["precomp"]`, and the engine would have published a raw `.pcf` as
the archive. Now there is a `_FINAL_CODEC_FALLBACK`, and a test walks every
profile × every tool combination asserting no chain ends on `precomp`, `tar`
or `srep`.

## Recommendation

Keep the stage — it is correct, it makes Insane honest, and it is the only
maintained long-range deduplicator we can drive. **But do not present Insane as
strictly better than Extreme**, because on both corpora measured it is not.
Its ratio advantage needs redundancy *inside the piped stream*; its cost is
2-5× the time either way.

**Do G9 next.** The duplicate-file win the roadmap attributed to SREP and then
to zpaqfranz is, measured, neither — it is sitting unclaimed in the store
route, and we already have the hashes to claim it.

## Reproduce

```
.venv\Scripts\python.exe -m pytest tests/test_zpaqfranz.py -q
```

Corpus B = the 5 files listed in `2026-08-01-estimator-backtest.md` §"Corpus B".
Corpus D = HandBrake + Composer + RAMMap from that set, with HandBrake and
Composer each duplicated under a second name.
