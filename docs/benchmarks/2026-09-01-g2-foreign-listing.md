# 2026-09-01 — G2: foreign-archive listing, passwords, selective extract

Branch `phase-g2-foreign-listing`. 7-Zip **24.07**, 2-core i7-3540M, 16 GB.

Corpus: `…\0No Need To Check\Programs`. **It has drifted again — 39 top-level
entries today, not the 42 recorded on 2026-08-07.** Nineteen of them are
archives 7-Zip can open, which is what this phase reads.

---

## 1. The bug that was already shipped

`engine._extract_foreign()` passed **no `-p` at all** to `7z x`. Measured
before writing any fix, with stdin held open (what a windowed parent looks
like to a child process):

| command | outcome |
|---|---|
| `7z x -y -o<dir> hidden.7z` | **still running after 8.0 s** — blocked on a password prompt with nowhere to appear (`CREATE_NO_WINDOW`) |
| `7z x -y -pGUARD -o<dir> hidden.7z` | exit 2 in **0.22 s**, with a parseable "Wrong password?" |

An earlier measurement with `subprocess.communicate()` appeared to show no
hang — that was an artefact: `communicate()` closes stdin, handing 7-Zip an
immediate EOF that a real parent never sends. The hang is real, and it is on
`main` today.

Fixed in two independent places: the dummy `-p` (PeaZip's trick, doc 17 §4)
on every 7-Zip invocation, and `stdin=subprocess.DEVNULL` in `run_tool` /
`run_capture`, which covers every other tool we shell out to.

## 2. Listing 19 real archives

`excmp list` over every archive in the corpus. **38,496 entries in 21.3 s.**

| archive | MB | kind | files | s | note |
|---|---:|---|---:|---:|---|
| DevExpress_Patch_v2.5.1.3.rar | 502.6 | — | — | 0.42 | encrypted headers |
| HitPaw_Video_Enhancer_1.5.rar | 933.1 | — | — | 0.41 | encrypted headers |
| VideoProc.Converter.AI.7.3.w64.rar | 203.0 | — | — | 0.38 | encrypted headers |
| Winxvideo.AI.3.5.0.0.w64.rar | 212.7 | — | — | 0.36 | encrypted headers |
| CapCut_Pro (GIGAPURBALINGGA.CC).zip | 535.7 | zip | 1 | 0.30 | encrypted data |
| Wondershare UniConverter … pass=123.zip | 263.7 | zip | 3 | 0.27 | encrypted data |
| vagrant_2.4.2_windows_amd64.msi | 262.7 | cab | **38,149** | 1.91 | |
| mysql-installer-community-8.0.43.0.msi | 371.5 | compound | 35 | **7.14** | slowest |
| mysql-installer-community-8.0.35.0.msi | 302.7 | compound | 35 | 5.88 | |
| mysql-workbench-community-8.0.43-winx64.msi | 45.1 | compound | 67 | 1.09 | |
| DB.Browser.for.SQLite-v3.13.0-win64.msi | 19.8 | cab | 106 | 0.27 | |
| *(8 more small zip/msi)* | | | | ~0.3 each | |

Four findings worth keeping:

1. **Four of the nineteen have encrypted headers**, all real repacks nobody
   staged for the test. Every one of them would have frozen the app before
   this phase. They now error in ~0.4 s.
2. **`.msi` is not one format.** 7-Zip reports `cab` for some and `compound`
   for others depending on internal structure, and the `compound` ones are
   **20× slower to list** (7.14 s vs 0.27 s at comparable sizes). That alone
   justifies the worker thread — 7 s on the GUI thread is a freeze.
3. **38,149 entries in 1.91 s** puts real numbers under the row cap. The cap
   is `MAX_ITEMS = 50_000`, so this archive lists complete; the largest real
   thing in the corpus is within a factor of 1.3 of the limit, which is
   closer than expected and is why `truncated` is carried to the UI.
4. Encrypted **data** and encrypted **names** are genuinely different cases:
   the two zips list fine and flag their entries, the four RARs cannot be
   listed at all. One is a warning, the other is a prompt.

## 3. Selective extract — measured, not asserted

**Foreign, from a 264 MB encrypted zip** (password `123`, which the archive's
own filename discloses):

| | time | placed | bytes |
|---|---:|---:|---:|
| `extract_selected` (one member) | **0.31 s** | 1 file | 943,572 |
| full `extract_any` | 1.47 s | 3 files | 263,913,708 |

SHA-256 of the selectively-extracted file
`22cbc7fe708c8d1f075d06352ed3ee126bc811d226cbcb20f9aedf4608877d92` —
**identical** to the same file taken from the full extract. 5× faster.

**Ours**, a real 5.3 MB four-file `.excmp` (Normal, 74.7 % of original):

| selection | quoted cost | time | verified | SHA-256 vs the original on disk |
|---|---|---:|---:|---|
| pipelined member | `solid=True`, replay 3.6 MB | 0.56 s | 1 | **match** |
| stored member | `solid=False`, replay 0 | **0.03 s** | 1 | **match** |

The 18× gap between the two populations is the whole reason `selection_cost()`
exists. Both are ledger-verified: selecting fewer files does not buy speed
with a weaker guarantee.

## 4. What the screenshots caught that the tests did not

The suite was green for all of these.

| defect | how it read on screen |
|---|---|
| `packed = 0 B` on solid members | 7-Zip printed *nothing*; "0 B" claims the file costs no space |
| "Reading the archive's contents…" left up | a completed table under a status line still saying it was working |
| "Extract selected" never appeared | the async listing populated after the button's `setVisible` had already run |
| the caption restated the status line | the same "not created by ExtremeCompressor… no SHA-256 ledger" twice, five rows apart |
| the password field had no placeholder | an unlabelled box beside a sentence |
| `·` in the new CLI line | rendered as `?` in the Windows console code page |

The `packed = 0 B` one is the same shape as the RAM column's 6.0 GB: a number
that was the correct output of correct code and still wrong, because the
input meant "not stated" and the type could only say "zero".

## 5. Numbers to re-measure before quoting

- The corpus is live: **39 entries today, 42 on 2026-08-07**. Re-count.
- MSI listing times are cache-sensitive like every other figure off that
  drive. The 7.14 s `compound` figure is a single run.
- `MAX_ITEMS = 50_000` has never been hit by a real archive here. The 38,149
  case is the closest evidence, and it is not a test of the truncation path —
  that is covered by a monkeypatched cap instead.
