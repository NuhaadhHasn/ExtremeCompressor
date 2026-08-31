# 2026-08-07 — the level/dictionary knobs, the RAM column, the Parameters line

The last item of research/23 §5, and the only one that was never glue.
`_stage_factory()` hard-coded `SevenZipStage(level=9, dict_size=None)`, and
`StageRecord.params` was always `{}` — so no setting could be chosen, and an
archive could not say what settings produced it.

---

## 1. The RAM figure is the formula, not the multiplier

`excmp/ram.py` implements `CompressDialog.cpp:2942-3017` as doc 19 §3 backs
it out, because the source study says in bold to do exactly that:

```
size1  = hs*4 + dict*4 + dict*4 (level>=5) + 2 MiB (+6 MiB at 2 threads)
window = (dict + 64 KiB) * 1.5
1 block thread (solid)   -> size1 + window
N block threads          -> N * (size1 + window + chunk) + chunk
                            chunk = dict*4, clamped [1 MiB, 256 MiB]
decompress               -> dict + 2 MiB
```

`-mmt=N` at mx9 gives **N/2 block threads** (C/LzmaEnc.c:103-109,
C/Lzma2Enc.c:262). The familiar "≈13× dict per block thread" falls out of
this, and a test asserts the formula stays inside a 10–16× band so the two
cannot drift apart silently.

Also corrected from the source study: **mx9's default dictionary is 256 MiB**
since 24.09 (C/LzmaEnc.c:76-81). Anything still assuming 64 MB is off by 4×
on every RAM number.

### The clamp the QA sweep caught

First render showed **6.0 GB** for a 371 KB job. LZMA2 never allocates a
dictionary bigger than the data (`reduceSize`; `CompressDialog` applies the
same clamp before quoting its own estimate), so the figure was both false and
frightening — in the panel whose entire purpose is being neither.

`effective_dict(dict, input)` rounds the input up to a power of two and takes
the smaller. Measured after:

| input | Normal peak RAM |
|---|---|
| 371 KB | **32.7 MB** |
| 50 MB | 2.1 GB |
| 721 MB | 6.0 GB |
| 6.4 GB | 6.0 GB (dictionary caps at 256 MiB) |

6 GB on a 16 GB machine for a real job is precisely the warning worth having
before you start — which is why the column exists. Fast shows "—": zstd's
window is a tenth of this and is never what runs the machine out of memory,
so it says nothing rather than a number nobody needs.

## 2. B9's cap, applied to the menu

`max_safe_dict()` returns the largest **power of two** (7-Zip accepts nothing
else) whose peak fits ~55 % of physical RAM. On this machine:

```
total RAM : 15 GiB
offered   : 16m 32m 64m 128m 256m 512m
```

512 MiB, exactly B9's rule for the 16 GB / 2-core target. The menu simply
stops there — a choice the machine cannot honour is a trap, not an option.

## 3. The Parameters line is an allowlist

There is no shell here (stages build argument *lists*), so this is not an
injection surface. What it is: a way to hand 7-Zip a switch that breaks a
promise the engine already made.

| refused | why |
|---|---|
| `-p` | would put a password in the job log |
| `-o` | would move output away from the verified atomic publish |
| `-w` | would move the work folder the free-space check was made against |
| `@listfile` | would change the contents after the ledger was built |
| `-sfx` | unsigned SFX is SmartScreen-flagged forever (Phase H) |
| `--` | ends switch parsing; everything after is a path |

Allowlisted, not blocklisted — a blocklist is a promise to have thought of
everything. Only `-m…` method switches pass.

Measured end to end:

```
$ excmp compress ... --params=-phunter2
error: -p is not allowed here: would put a password in the job log
secret leaked in the message: False
```

The refusal names the switch and the reason but never repeats its *value*
(PeaZip's redaction rule, doc 17 §4). In the GUI it stops the job in the
banner with an "Edit it" action, rather than three minutes into a chain with
7-Zip's own error.

**argparse quirk worth knowing:** every value this flag takes begins with `-`,
which argparse reads as another option. It must be spelled `--params="-mqs"`.
The help text says so, because otherwise everyone hits it on their first try.

## 4. The manifest finally records what ran

```
$ excmp compress ... --level 5 --dict 64m --params=-mqs
done: 1.7 MB -> 1.1 MB (35.1% saved) in 1.0s

recorded params: {'sevenzip': {'level': 5, 'dict': '64m', 'extra': ['-mqs']}}
```

Only what was actually *set* — an archive built with defaults does not claim
the tool's defaults as deliberate choices. Three dictionary sizes over the
same input produce three different archives, so the switch demonstrably
reaches 7-Zip rather than merely being written down.

## 5. Suite

`.venv\Scripts\python.exe -m pytest -q` → **468 passed, 1 xfailed**
(432 before). New: `tests/test_ram_and_knobs.py` (37).
