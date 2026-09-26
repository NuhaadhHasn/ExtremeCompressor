# 24 — The repack toolchain: Razor12911, xtool, and the Oodle wall

> Researched **2026-09-01**, from primary sources (GitHub repos, LICENSE files,
> README text) rather than blog summaries or AI overviews. Where only hearsay
> exists, this doc says so.
>
> **Why this doc exists:** the user asked whether "razor" was a real thing and
> whether we had researched it. Yes on both counts — but the research turned up
> one finding that changes B6's design, and one that closes a question we had
> left open.

---

## 1. Direct answer: who is "razor"

**Razor12911** — the author of **xtool**, the precompressor our roadmap item B6
is built around. Not a codec, a person. The confusion is understandable: his
name is attached to so much of the scene's tooling that people repeat it as if
it were a format.

His tools are the ones the repack scene actually runs. `xtool` is the one that
matters to us.

---

## 2. The finding that changes B6

**There is no open-source Oodle *encoder*. There is only a decoder.**

`powzix/ooz` is the reverse-engineered, open-source
Kraken/Mermaid/Selkie/Leviathan/LZNA/Bitknit implementation everyone cites when
they say "Oodle has been reversed". Its own README (quoted verbatim):

```
-d --decompress    decompress (default)
-z --compress      compress (requires oo2core_7_win64.dll)
```

Read that second line carefully. **`ooz` "compresses" by calling the
proprietary DLL.** The reverse-engineering effort produced a decoder; the
encoder was never reproduced. Its README even tells you where to get the DLL
("from the free game Warframe on steam"). The README states **no license at
all** — which, as with every unlicensed repo, legally means all rights
reserved, not "open source". (A search summary claimed GPL; the README does not
say so, and we should not act on the search summary.)

### Why this is decisive for us

Our whole model is **restore = recompress**: xtool decodes the Oodle stream so
the payload compresses well, then at restore time re-encodes it to reproduce
byte-identical output. That re-encode **cannot be done with open-source code**.
It requires `oo2core_*.dll`, and — confirmed across multiple sources — **the
exact version the game shipped**, because different Oodle versions produce
different bytes.

So the B6 audit's conclusion is not merely prudent, it is forced:

> **The DLL is part of the archive contract.** An `.excmp` built with xtool
> cannot restore without the matching `oo2core` DLL, and "re-resolve it from
> the game folder at restore" fails the moment the game folder is gone —
> which, for an archive, is the normal case.

**This is the single most important constraint on B6 and it is now
source-confirmed rather than inferred.**

---

## 3. xtool: licence and status

| Fact | Value | Evidence |
|---|---|---|
| Author | Razor12911 | github.com/Razor12911/xtool |
| Licence | **MIT**, © 2016-2022 | `LICENSE` in repo |
| Status | **Archived 28 Oct 2023**, read-only | GitHub archive banner |
| Our roadmap said | "MIT but archived upstream" | ✅ **correct** |

So our existing routing for xtool stands: **MIT, so we may use it**, but it is
unmaintained, which is why B6 already requires a pinned version and a verified
roundtrip on every use. The archive date means no upstream fix is coming for
any bug we hit — a real risk to weigh, not a blocker.

**Note on the Patreon builds:** the scene distributes builds beyond the archived
repo. Our standing rule (never bundle xtool Patreon builds) stays, because their
provenance and licence are not the repo's MIT grant.

---

## 4. FitGirl's pipeline, with confidence marked

| Layer | What it is | Confidence |
|---|---|---|
| Container | **FreeArc `.arc`**, split into the `fg-*.bin` files you see on disk | high |
| Extractor | **`unarc.dll`** — FreeArc's own extraction DLL — driven by **`ISDone.dll`** | high |
| Installer shell | **Inno Setup** `setup.exe` | high |
| Precompression | Precomp / xtool-class tools before the final codec | medium |
| Long-range dedup | SREP between precompression and the final codec | medium |
| Final codec | LZMA2, or **LOLZ** on some repacks | medium |

The "medium" rows are the ones repeated everywhere but rarely evidenced with a
primary source; treat the *order* as well-attested and the *exact tool per
release* as varying release to release.

### The detail worth stealing

FreeArc **groups files by data type and picks the most suitable algorithm per
group**. That is the same core idea as our analyzer → planner → chain design.
The scene's own container validates the architecture we already built; where we
differ is that we verify a byte-identical restore before publishing and they
do not.

### The detail worth avoiding

`ISDone.dll` / `unarc.dll` generate a genuinely enormous volume of
"unarc.dll returned an error code -1" support threads — enough that fixing that
error is its own YouTube genre. Our roadmap already encodes the four root
causes as **H4**. Worth noting *why* it is so bad: the extractor reports a
single opaque code for non-Latin paths, insufficient free disk, a missing
volume, and antivirus interference alike. **Four different problems, one
number.** That is precisely the failure our "say which, and say why" copy rule
exists to prevent.

---

## 5. Correction to our own record: why SREP is really out

Our roadmap says SREP is **"not OSI-clean"**. That is **shakier than it should
be**, and the honest version is:

- SREP-adjacent source sits in **GPL-2.0** repositories
  (`Bulat-Ziganshin/MT-LZ`, `j2969719/freearc-old`), and FreeArc itself is
  GPL-2.0. So "not OSI" is not clearly true.
- But the shipped **`srep64.exe` is a freeware binary** distributed via forum
  posts, with no accompanying licence grant of its own. An unlicensed binary is
  not something we can bundle, whatever its neighbours are licensed as.
- **The disqualifying reason is integrity, not licence.** On 2026-08-01
  `srep64.exe` failed its own decompression checksum on **1 of 3 runs over
  byte-identical input**. Intermittent corruption is worse than deterministic
  corruption, and for a product whose entire claim is a verified byte-identical
  restore, that alone ends the discussion.

**Action:** reword the B11/E1 rationale to lead with the integrity failure and
describe the licence as *unclear*, not *non-OSI*. Getting this right matters —
we cite it as precedent elsewhere.

The replacement stands: **zpaqfranz's CDC dedup (B1)** is MIT, maintained, and
matches identical fragments at unlimited distance.

---

## 6. What this research confirms we got right

1. **xtool is MIT and archived** — routing unchanged, pin the version.
2. **Dropping SREP** — right call, better reason than the one we recorded.
3. **LOLZ has no legal path** — nothing found to contradict it. *(Moot since
   the repo went private on 2026-09-01. LOLZ was then measured under B12,
   and zpaqfranz `-m5` beat it on both corpora. That was measured
   2026-09-23, and the deflate row was restore-verified 2026-09-26.)*
4. **Analyzer-per-type architecture** — the same idea FreeArc uses.
5. **B6's DLL-in-the-contract requirement** — now *source-confirmed*, not
   inferred. See §2.

## 7. What we got wrong

1. **The SREP licence claim** (§5).
2. **We had treated "Oodle has been reverse-engineered" as leaving the door
   open to an OSI-only path.** It does not. `ooz` decodes; it cannot encode
   without the proprietary DLL. **There is no legal, OSI-only route to
   Oodle recompression, and there will not be one.** B6 must be designed
   around the DLL, permanently.

## 8. Open questions

- Whether any repack ships the `oo2core` DLL inside the archive, and if so
  under what claimed justification. Unresolved from public sources — and it is
  the design question B6 has to answer for itself regardless.
- FreeArc's current maintenance status (the original is long dormant; forks
  exist). Only matters if we ever read `.arc`, which is not planned.
- Whether newer OSI precompressors for zstd/lz4-in-pak streams have appeared.
  A generic search returned academic noise rather than tooling; needs a
  targeted encode.su sweep, not a web search.

## 9. Sources

- github.com/Razor12911/xtool — repo, `LICENSE`, archive banner
- github.com/powzix/ooz — `README.md` (the `-z` line quoted verbatim in §2)
- github.com/Bulat-Ziganshin/MT-LZ — GPL-2.0, contains `srep.rc`
- freearc.sourceforge.net — FreeArc design and per-type grouping
- en.wikipedia.org/wiki/FitGirl_Repacks — repack model
- encode.su — the scene's primary technical forum
