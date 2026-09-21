# B13 — still blocked on both halves, and a defect found while proving it

**2026-09-20**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).

B13 is *"balrogg — lossless Vorbis/Opus recompression"*, logged 2026-09-15 as
**the strongest untested lead in the project** because it targets a bucket
scored at 0%. It could not be executed this session, and the reason is not a
judgement call: **neither the tool nor a corpus exists on this machine, and
both were re-checked by searching rather than by reading last week's note.**

What *was* possible was to establish the gate — the numbers balrogg has to
beat — and that produced a finding worth more than the blocked item.

---

## 1. Blocker (a): there is no balrogg binary, and there is no way to get one here

The download is `balrogg-lossless-vorbis-opus-recompressor.601` on
**krinkels.org**, which is behind a login; the handoff records the account as
*awaiting email confirmation*. Creating or confirming an account is not
something this session does on the owner's behalf, so the download stands
blocked until it is fetched by hand.

Searched today, bounded, and empty in every one: `Downloads`, `Desktop`,
`Documents`, `PycharmProjects`, `AppData\Roaming`, `AppData\Local`, `C:\` to
depth 2, both `Program Files` trees, `C:\excmp-bench`, and
`ExtremeCompressor-refs` (all 14 clones). `tools/bin` holds only `flac`,
`qpdf` and `zpaqfranz.exe`. The string `balrogg` appears in this repo in
exactly two files, both documentation.

**One honest caveat about that search**: an unbounded
`find C:/Users/nuhaa -iname '*balrogg*'` was attempted and **timed out at
480 s** without completing. The conclusion rests on targeted searches of the
plausible locations, not an exhaustive sweep.

## 2. Blocker (b): there is no game-audio corpus, and that was searched properly

The B4 lesson — *"a negative result from a search is only as good as the
search"*, where a previous session declared B4 blocked having never looked in
`Desktop\Downloads-1`, which held 5.07 GiB of audio — was taken literally.

| location | `.ogg` | `.opus` | `.wem` | `.fsb` | `.bnk` |
|---|---:|---:|---:|---:|---:|
| `C:\Users\nuhaa\Downloads` | **39** | 0 | 0 | 0 | 0 |
| `AppData\Local`, `Program Files`, `Program Files (x86)` | 10 | 0 | 0 | 0 | 0 |
| `Desktop\Downloads-1` (the external drive, **all 412,055 files**) | **0** | 0 | 0 | 0 | 0 |
| `C:\excmp-bench`, `Music`, `Videos`, `Documents`, `Pictures` | 0 | 0 | 0 | 0 | 0 |
| `F:\` (a mounted 31 GB volume) | 0 | 0 | 0 | 0 | 0 |

That external-drive row is not a bounded search that gave up: the whole tree
was enumerated, **412,055 files**, and an extension histogram over all of them
returns nothing for `.ogg`, `.opus`, `.wem`, `.fsb`, `.bnk` or `.oga`. (It is
184,255 `.js` files and 26,865 `.json`, which is what a tree of programming
tutorials looks like.) This is the search B4's post-mortem asked for.

There is **no game installed on this machine at all** — no
`Steam\steamapps`, no Epic, no GOG, no Riot, no Unity. Every `.ogg` found is a
5–30 KB UI sound effect inside the `odoo18` / `odoo19` source trees; the 10
system hits are Android SDK ringtones. Zero Opus, zero Wwise, zero FMOD.

**This is the same gap that blocks B6.** One download of a real game's audio
archive unblocks both.

---

## 3. The premise is confirmed, by running the planner rather than reading it

Real headers, not empty files, so content sniffing is exercised rather than
just the extension table:

| file | bytes at offset 0 | Normal | Extreme | Insane |
|---|---|---|---|---|
| `real.ogg` | `OggS…\x01vorbis` | store | store | store |
| `real.opus` | `OggS…OpusHead` | store | store | store |
| `wwise.wem` | `RIFF….WAVE` | store | store | store |
| `fmod.fsb` | `FSB5` | store | store | store |
| **`named.dat`** | `OggS…\x01vorbis` | **store** | **store** | **store** |

That last row matters for any future patch: `analyzer._MAGIC` carries
`(0, b"OggS", Category.AUDIO)` and is checked **before** the extension table,
so an Ogg is detected whatever it is called. A B13 opt-out that edited only
`_EXT` would be bypassed. The decision itself is not in `analyzer.py` at all —
it is `planner.store_reason`, gated on `_MEDIA`, which runs **before** the
entropy check and has exactly one escape hatch, `_DEFLATE_MEDIA = {".png"}`.

The sentence the user is shown, verbatim:

> media file: already compressed by its codec; stored losslessly so quality is
> untouched (enable Shrink mode to re-encode smaller)

And Precomp confirms it reaches nothing: on a tar of the Ogg corpus it printed
**`Recompressed streams: 0/0`** and made the file 19 bytes *bigger*
(351,744 → 351,763).

---

## 4. The finding: on this data the app inflates the file and says it is optimal

The only real Vorbis on this machine — **31 unique files, 326,692 B**,
deduplicated by SHA-256 out of the 39 found — run through the product's own
`engine.compress`, not a hand-rolled `7z` call:

| what ran | bytes out | saved |
|---|---:|---:|
| **Normal, `engine.compress`** | 333,314 | **−2.0%** |
| **Extreme, `engine.compress`** | 333,317 | **−2.0%** |
| `7z -mx9 -ms=off` (non-solid) | 256,784 | **21.4%** |
| `7z -mx9` (solid) | 189,826 | **41.9%** |

The archive is **6.6 KB larger than the input** — container and manifest
overhead on top of bytes copied verbatim — while the reason line says the data
is already compressed by its codec. The analyzer had *already measured* these
files as compressible and the planner discarded it: `sample_ratio` across the
31 runs **0.687 – 0.945**, where 1.0 means incompressible.

This is the exact shape of the defect B4 found for WAV, which is the only
specialist in this project to have beaten the existing chain.

### What this does **not** establish, and it matters

- **The 41.9% is mostly not a Vorbis result.** Solid mode is 41.9%, non-solid
  21.4%; the gap is cross-file redundancy between 31 near-identical UI blips
  taken from two versions of the same product. Do not quote 41.9% as
  "LZMA beats Vorbis".
- **21.4% is intra-file and is real** — but on 5–30 KB *low-bitrate* sound
  effects. High-bitrate Vorbis music is expected near 0%, and there is none
  here to check against.
- **326 KB is not a corpus.** Per CLAUDE.md, no ratio measured on it goes into
  a roadmap claim.

**So nothing was changed.** Routing 10 audio extensions differently on the
strength of 326 KB of UI sounds would be exactly the mistake this project
keeps writing down: a plausible model fitted to the one regime that was
sampled. The finding is recorded; the fix waits for data.

---

## 5. The gate, ready to run the day the binary lands

Unchanged from the roadmap, now with its numbers filled in:

1. Beat `precomp → 7z` **on our own corpus**. On the Ogg corpus that bar is
   **189,826 B solid / 256,784 B non-solid from 326,692 B** — and note the
   bar is *7-Zip*, not `store`, because the honest comparison is against what
   the chain could do if audio were simply allowed through it.
2. Prove a byte-identical restore through `verify_restore`. Untrusted binary:
   pinned hash, no faith in its exit code.
3. The structural hook already exists and is **`_UNCOMPRESSED_AUDIO`**
   (`planner.py:173`), B4's precedent — an audio extension set checked before
   the `_MEDIA` branch that keeps the file off the pipeline and hands it to a
   specialist packer. Not `_DEFLATE_MEDIA`, which throws the file into
   `precomp` where, as measured above, nothing is waiting for it.

Reproduce everything here with the script recorded in the session scratchpad,
or by hand:

```
.venv\Scripts\python.exe -c "from excmp.analyzer import analyze_file; from excmp.planner import store_reason; print(store_reason(analyze_file(r'some.ogg')))"
```

---

## 6. One correction to CLAUDE.md, measured today

CLAUDE.md records the Programs corpus as **"6.4 GB across 42 files" as measured
2026-08-07**. Today it is **29 files, 4,992,790,741 B**. The folder is live and
has shrunk; the doc already warns to re-measure before quoting it, and this is
that warning being right.
