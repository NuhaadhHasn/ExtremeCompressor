# B5 — PDF/Office: measurements

**2026-09-07**, branch `phase-b5-pdf-office`, this laptop
(2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

Everything here was reproduced before it was written down.

---

## 0. B5 is not the job the roadmap describes

The plan reads: *"PDF/Office: qpdf `--object-streams=generate
--recompress-flate`; docx/xlsx members unpacked into the solid stage (they're
just ZIPs)"*.

Two facts, both checked first, change the job:

1. **These types are already piped, not stored.** `.pdf`, `.docx`, `.xlsx` and
   `.pptx` are all in `planner._PRECOMP_EXPANDABLE`, so Precomp already
   expands them and 7-Zip already sees the result.
2. **B3 is the precedent.** There the roadmap proposed `oxipng` for PNG;
   measuring showed the existing lossless `precomp → 7z` route already beat it
   (38.41% vs 31.79%) *and* that oxipng produced **0 byte-identical files**. So
   the first question for any specialist is not "does it shrink things" but
   "does it beat the route we already have, losslessly".

So the baseline came first.

---

## 1. The corpus

Every PDF and Office file in the tutorial corpus: **238 files, 433.4 MiB**.
The five files over 12 MiB (four 30 MB+ `.docx`, one 33 MB `.pdf`) are held
back so they cannot dominate an average, leaving the measured sample at:

| type | files | bytes |
|---|---:|---:|
| `.pdf` | 137 | 77.9 MiB |
| `.docx` | 48 | 31.1 MiB |
| `.pptx` | 35 | 27.5 MiB |
| `.xlsx` | 4 | 0.0 MiB |
| **total** | **224** | **136.5 MiB** (143,097,157 B) |

Read-only: files are copied into a scratch tree and the originals are never
opened for writing. Corpus guard clean before and after.

---

## 2. The baseline, and the 40 points nobody was being told about

| profile | chain | archive | saved | time |
|---|---|---:|---:|---:|
| Normal | `7z` | 128,261,167 | **10.37%** | 0.9 min |
| Extreme | `precomp → 7z` | 71,026,597 | **50.36%** | 4.3 min |

**Precomp is doing essentially all of the work** — 4.9× better than plain
7-Zip on the same bytes. Any specialist has to beat 50.36% losslessly to earn
a place.

That is a useful number on its own. The defect is what the *estimator* said
about it:

| profile | predicted `expected` | measured | error |
|---|---:|---:|---:|
| Normal | 9.40% | 10.37% | fine |
| **Extreme** | **13.78%** | **50.36%** | **−36.6 points** |

The truth was inside the range (`[7.5 .. 71.4]`), so this is not a broken
bound — it is a broken *recommendation*. `compare_profiles` renders `expected`,
so the comparison table showed **Extreme beating Normal by 4 points where the
truth is 40**, on two of the most ordinary document formats there are. A user
reading that table would reasonably choose Normal and lose half their
compression.

---

## 3. Why the old signal could not see it

`_piped_ratios` has a branch for exactly this case — `_ZLIB_LOW/EXPECTED/HIGH`
= 0.28/0.45/1.0, for "Precomp will crack this". It never fired:

```
ext     store_reason?  zlib_stream?  in _PRECOMP_EXPANDABLE?  count
.docx   False          False         True                       27
.docx   True           False         True                       21
.pdf    False          False         True                       68
.pdf    True           False         True                       69
.pptx   False          False         True                       15
.pptx   True           False         True                       20
.xlsx   False          False         True                        4
```

**`zlib_stream` is False for all 224 files.** It checks for a zlib header at
offset 0; a `.docx` begins `PK\x03\x04`, and a PDF scatters its Flate streams
through the body. And the entropy probe is not wrong either — worst-sample
ratios are 0.910 (pdf), 0.902 (docx), 0.878 (pptx), i.e. "barely
compressible". The compressible data is one deflate layer down, which is
precisely what Precomp exists to reach and precisely what sampling raw bytes
cannot see.

`estimate.py` recorded this as a permanent limitation:

> Measured on two real installers with near-identical probe readings […]
> Precomp found nothing in one and cut the other by a further 33 percentage
> points. **No cheap signal separates them**, so this is a documented
> limitation and not a tuning problem.

That is true of **the bytes**. It is not true of **the container**.

---

## 4. Why an extension list is not the fix either

The tempting repair is "if the extension is in `_PRECOMP_EXPANDABLE`, expect a
win". That would have broken a passing test, and the reason is worth keeping:

```
Programs backtest corpus, 721,076,752 B, Extreme measured 2.97% saved
  Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip   263,670,338 B
```

**37% of that corpus is a single encrypted `.zip`.** Precomp cannot see inside
an encrypted member, which is why Extreme saved 2.97% there. An
extension-based rule predicts a large win on 263 MB that never arrives.

Two real corpora, the same extension list, opposite answers. That is what
forces a probe rather than a table.

---

## 5. The probe: structure, not statistics

`analyzer.probe_expandable` answers for the file in hand:

- **zip family** (`.zip .docx .xlsx .pptx .jar .apk .odt .ods .odp .epub`) —
  open the central directory and read member **flags only**, never member
  data. Expandable iff no member is encrypted and at least one is deflated.
  One seek and a short read, whatever the file's size.
- **`.pdf`** — scan the first 64 KiB for `/FlateDecode`.
- everything else — `False`.

Measured on real files:

| file | probe | expandable |
|---|---|---|
| `pass=123.zip` (263 MB) | 4 members, **3 encrypted, 0 deflated** | **no** |
| `.docx` | 16 members, 0 encrypted, 12 deflated | yes |
| `.pptx` | 136 members, 0 encrypted, 116 deflated | yes |
| `.xlsx` | 13 members, 0 encrypted, 13 deflated | yes |

The PDF window is a measured trade, not a guess: **11 of 12** real PDFs
sampled declare `/FlateDecode` inside the first 64 KiB. The twelfth is an
image-only scan, which genuinely has nothing for Precomp to expand — and being
wrong about one file is covered by the range's optimistic end. `analyze_file`'s
head read grew 4 KiB → 64 KiB to serve this, which costs one read per file
rather than a second pass.

### Result

| profile | predicted before | predicted after | measured |
|---|---:|---:|---:|
| Normal | 9.40% | 9.40% | 10.37% |
| **Extreme** | **13.78%** | **46.32%** | **50.36%** |

Error on the Extreme `expected`: **36.6 points → 4.0 points**, and still on
the conservative side, which is the bias `estimate.py` documents throughout —
never oversell a win that may not arrive. The Programs backtest is unchanged
and still passes, because the encrypted zip is correctly not claimed.

---

## 6. qpdf: still unevaluated, and expected to land in Phase C

Not measured yet, and the roadmap's framing should be treated with suspicion
until it is. `--recompress-flate` **rewrites the file's streams**, which is the
same property that disqualified `oxipng` in B3: pixel/semantically lossless is
not byte-lossless, and a SHA-256 ledger cannot be satisfied by a file whose
bytes changed. The prediction is that qpdf moves to Phase C beside the AV1
re-encoder and C6's `oxipng`.

It has to beat **50.36%** to be worth having even there, and there is no qpdf
binary on this machine, so this is left open rather than guessed at.

The other half of the roadmap's B5 — unpacking docx members into the solid
stage — is *already achieved* by Precomp for Extreme/Insane. Doing it
explicitly would only help profiles without Precomp, and would need the B2
lepton pattern (pack, immediately unpack, compare, fall back) to stay
byte-lossless, because rebuilding a zip bit-exactly is not guaranteed.

---

## 7. Reproducing this

```
# the probe, including both real corpora
.venv\Scripts\python.exe -m pytest tests\test_expandable_probe.py -q

# the estimator against the measured baseline
.venv\Scripts\python.exe -m pytest tests\test_estimate_backtest.py -q
```
