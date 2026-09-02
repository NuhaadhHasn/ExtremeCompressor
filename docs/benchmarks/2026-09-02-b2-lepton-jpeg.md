# Benchmark: the JPEG specialist (B2), on a real photo folder

- Machine: Nuhaadh-Laptop, i7-3540M (2C/4T), 16 GB, threads=2
- `lepton-jpeg-python` **0.5.8** (Microsoft's Rust port, Apache-2.0, in-process wheel)
- Corpus: **37 real JPEGs, 151,250,320 bytes** — actual design work from
  `My Graphical Projects`, not synthetic images
- Date: 2026-09-02

## Codec-level: what lepton can and cannot do

| | files | bytes | result |
|---|---|---|---|
| **accepted** | **23** | 15,746,400 → 10,484,698 | **33.42% saved**, all bit-exact |
| **refused** | **14** | 135,503,920 | 13 CMYK/4-channel, 1 wider than 16384 px |

Throughput on the accepted set: **4.4 MB/s**.

**33.4% beats the roadmap's ~22% prediction.** That is the good news, and it
is the smaller half of the result.

## The number that shaped the design

**Lepton refused 38% of a real JPEG folder.** Thirteen of the fourteen were
CMYK — print/design work, an entire ordinary genre of file, not an edge case.
A specialist that fails on more than a third of real input cannot be wired in
as "compress the JPEGs"; it has to be "try, and shrug it off".

Worse for the headline number: **the refused files are the big ones.** They
are 135 MB of the 151 MB. So the folder-level saving is dominated by files
lepton cannot touch.

## End-to-end through the engine

| | |
|---|---|
| input | 151,250,320 bytes (37 files) |
| output | 146,009,027 bytes |
| **saved** | **3.47%** |
| lepton-packed | 23 |
| stored raw (refused) | 14 |
| compress + verify | 14.3 s |
| extract | 2.8 s |
| **verified** | **37/37 byte-identical** |

**Before B2 this folder compressed by approximately nothing** — JPEGs are
high-entropy, so every one of them was stored verbatim. 3.47% of 151 MB is
5.2 MB that used not to exist.

## How to read the 3.47%

It is entirely a property of *this* folder, and the honest way to state the
feature is:

- **RGB photos** (cameras, phones, screenshots — most people's photo folders):
  expect around **33%**.
- **CMYK print work**: expect **0%**, and no error.
- A mixed folder lands in between, weighted by bytes rather than file count —
  which is exactly why this one came out at 3.47% despite 23 of 37 files
  packing successfully.

## The safety design, and why it costs double

`jpeg.pack()` compresses **and immediately decompresses**, comparing against
the original bytes, and returns `None` unless they match exactly. That doubles
the work on every JPEG. It buys the ability to *fall back* instead of *fail*:
a file lepton would mishandle is caught while storing it raw is still free,
rather than at restore time when the whole archive would be refused by the D9
gate.

`None` covers every uninteresting outcome — not a JPEG, too small, wheel
missing, lepton refused, result not smaller, round-trip mismatch — so the call
site has no error handling and no way to skip the check.

The writer re-packs at container-write time and **drops the `codec` claim** if
lepton declines on the second attempt, rather than recording an entry it
cannot honour.

## Reproduce

```
.venv\Scripts\python.exe -m pytest tests/test_jpeg_lepton.py -q
```

12 tests; the ones that matter are `test_pack_verifies_the_roundtrip_itself`
(monkeypatches lepton into lying about a successful decompress) and
`test_a_jpeg_lepton_refuses_still_round_trips` (the 38% case).
