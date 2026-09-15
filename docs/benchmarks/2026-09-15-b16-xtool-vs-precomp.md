# B16 — xtool against Precomp, and the claim that did not reproduce

**2026-09-15**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

B16 was written yesterday on the strength of the author's own published
benchmark, which showed `xtool -mzlib` beating `precomp -brute` by 2,673,415
bytes **and** running 4.7× faster on a GTA V archive. The roadmap entry said
the gate was "measure it against `precomp -> 7z` on our own corpora".

Measured. **It loses by 8.5%**, and the reason is worth more than the number.

---

## 1. The result

Corpus: **Silesia, zipped by 7-Zip with `-mm=Deflate -mx9`** — 64,726,889 B of
genuine deflate over 12 heterogeneous real files. The final compressor is
`7z -t7z -mx9 -mmt2` in **every** row, so the only variable is the
precompressor. Every route was restored and compared against the original by
SHA-256.

| route | archive | saved | compress | restore |
|---|---:|---:|---:|---|
| 7-Zip alone | 64,559,858 | 0.26% | 24.4 s | n/a |
| **`precomp -cn` → 7z** | **51,745,050** | **20.06%** | 208.9 s | identical |
| `xtool -mreflate` → 7z | 57,857,303 | 10.61% | 114.1 s | identical |

And xtool given its best shot, four configurations against precomp's one:

| xtool configuration | inflated | final | vs precomp |
|---|---:|---:|---:|
| `-mreflate -d1` | 228,817,382 (3.54×) | **56,149,054** | **+4,404,004 (+8.51%)** |
| `-mreflate+preflate -d1` | 228,817,391 (3.54×) | 56,152,950 | +8.52% |
| `-mreflate -c64mb` | 221,102,955 (3.42×) | 57,860,358 | +11.82% |
| `-mzlib+reflate+preflate` | 221,102,969 (3.42×) | 57,862,292 | +11.82% |
| `precomp -cn` | 236,956,196 (3.66×) | 51,745,050 | — |

**Precomp reconstructs more streams** (3.66× inflation against xtool's best
3.54×) and turns that into 4.4 MB. xtool is **1.95× faster**, which is real and
is not the axis this project optimises: the archive outlives the job.

---

## 2. The error that nearly became a finding

The first run reported xtool **losing by 12,814,837 bytes**. That number was
wrong, and it was mine.

`-mzlib` — the exact flag from the author's benchmark — found **nothing** on
this corpus: 64,726,889 B in, 64,726,979 B out. Ninety bytes. The same ninety
bytes an earlier smoke test had produced on a completely different file, and
*that* was the tell: two unrelated inputs cannot both yield a 90-byte delta
unless the tool is doing nothing at all.

The cause is in the author's own manual (`xtool.chm`, shipped in the release
and decompiled with `hh.exe -decompile`):

> xtool's **zlib** codec reconstructs streams by trial and error against
> `zlibwapi.dll`.

It can therefore only match streams **zlib itself would have produced**. This
corpus was deflated by **7-Zip's** encoder, whose output zlib cannot reproduce,
so the zlib codec correctly found nothing and said so silently. `reflate`
reconstructs arbitrary deflate regardless of which encoder made it — hence
1.00× against 3.42× from the same input.

**The operational lesson, if this is ever wired in:** the codec has to match
the encoder that produced the streams, a mismatch fails **silently** rather
than loudly, and the failure looks exactly like "this data has nothing to
precompress". Any integration needs a positive check that the precompressor
actually did something, not merely that it exited 0.

---

## 3. Why the author's number and this one can both be true

He measured `x64w.rpf` from **Grand Theft Auto V** — streams written by a game
engine's own zlib. This is a **7-Zip-authored** zip. The entire distinction
between the `zlib` and `reflate` codecs is *which encoder produced the stream*,
so a benchmark's stream provenance is not a detail of the setup; it is the
variable under test.

That cuts both ways, and it is the honest limit of this result:

- **What is established:** on 7-Zip-produced deflate, `precomp -cn -> 7z` beats
  every xtool configuration tried, by 8.5% at best, and xtool is ~2× faster.
- **What is not:** anything about game archives. xtool's case is Oodle, Kraken,
  LZ4 and engine-authored zlib, and **none of that exists on this machine** —
  the same gap that blocks B6.

One corpus decides one corpus. This one is enough to stop B16 being adopted on
someone else's numbers; it is not enough to close the item.

---

## 4. Verdict

**Not adopted. Not closed.**

`precomp -> 7z` stays the route. This is the fourth of five proposed
specialists to lose to it — B3's `oxipng`, B5's `qpdf`, K4's wide window and
now xtool — against B4's FLAC, which won because it targeted a bucket that was
being **stored** rather than one the chain already handled.

That is the pattern worth carrying to B13: **the specialists that win here are
the ones competing with `store`, not the ones competing with `precomp`.**

Revisit B16 only with a real game corpus, and measure the Oodle codecs rather
than the deflate ones — deflate is the case precomp is already good at.

---

## 5. Provenance

`xtool 0.7.9` (the final release), downloaded from the author's own GitHub
releases rather than any forum mirror or repack bundle:

```
098ac99fa6375eec2318d60e6d6edc27dd6443f3a2d66ffee9ce255caefdbbae  xtool_0.7.9_hotfix.zip  18,816,967 B
c146101f0ce1182196267dd99463ba24d3d8b183bc298dc7716c3c3e415f7bbe  xtool_0.7.9.zip         18,816,082 B
```

Two things found in passing that any future integration has to account for:

- **`--dedup=xtool.bin` writes state outside the archive.** The author: *"this
  file must always exist else xtool will always fail restoring the data"*. It
  would have to live **inside** our container, or we would ship archives that
  cannot restore. Not used here.
- **`xtool.exe` is a GUI-subsystem binary** and prints nothing to a console
  when `xtoolui.dll` is present; it opens a window instead and blocks. It is
  driven through its documented `- -` stdio mode with real file handles — not
  through a shell, which mangles the quoting.
