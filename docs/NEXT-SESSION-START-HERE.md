# 🚦 START HERE — handoff (written 2026-09-26)

> **B12 is closed: measured, not integrated.** LOLZ lost to zpaqfranz, the
> codec it would have displaced. Docs-only session, committed and pushed to
> `main`; no code changed, no branch awaiting review.
>
> **Next phase: B17 — should Insane run zpaqfranz `-m5`?** It came out of
> B12's last measurement and is the biggest unclaimed ratio gain on the
> table: **−7.26%** on deflate data (−0.60% on installers, for 3.0× the
> compress time there). The deflate timings aren't clean yet, and restore ran
> 5.3–5.8× slower. §3 has the spec: plumbing first, then four measurements
> before any default moves.
>
> The Chrome downloads brief (§5) is still open. It needs the owner at the
> keyboard to confirm each file.

```
.venv\Scripts\python.exe -m pytest -q
```

Three things about that command, all measured, none guessable:

- **The runtime is not a stable number.** 1 h 07 m with 2.9 GB free on `C:`,
  14 m 52 s with 14 GB, 20 m 10 s with 101 GB free while a benchmark had one
  of the two cores. Free space and contention both move it. Measure it; do not
  quote any of these.
- **`pytest`'s elapsed time is not a measurement on this laptop, because it
  sleeps.** Hold the machine awake with
  `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)` —
  process-scoped, touches no power setting.
- **Clear `%TEMP%\pytest-of-<you>` first, and freeze the code before
  starting.** Editing `excmp/`, `gui/`, `tools/` or `tests/` mid-run
  invalidates the run. Editing `docs/` does not.

---

## 0. State of the repo

| | |
|---|---|
| `main` | this session's docs commit, pushed. Code is unchanged since `609bc07` (the I6 merge) |
| branches | none awaiting review. `phase-i6-measured-presets` is merged and safe to delete |
| tests | **not re-run this session, because no code changed.** Last full run: **1,292 passed, 2 skipped, 1 xfailed** (2026-09-21, the J8 re-pin) |
| corpus guard | not needed: nothing that touches the tests changed |
| AI attribution | none, anywhere. Audited before the commit |

---

## 1. What shipped: B12 closed on measurement

Full record:
[benchmarks/2026-09-23-b12-round3](benchmarks/2026-09-23-b12-lolz-vs-zpaqfranz.md).

B12's two earlier rounds measured LOLZ against 7-Zip. **Insane's final codec is
zpaqfranz**, so that was the one comparison between B12 and a decision. Same
two `.pcf` intermediates as 2026-09-20. Every zpaqfranz and LOLZ row was
restored and SHA-256 compared. The 7-Zip row is carried over from 2026-09-20
and was never restore-verified:

| final codec | installers (62.5 MB `.pcf`) | deflate (237 MB `.pcf`) |
|---|---:|---:|
| `7z -mx9` (Extreme) | 46,048,116 | 51,827,136 |
| `lolz -d64m` | 45,933,664 | 50,233,466 |
| **`zpaqfranz -m4`** (Insane today) | 46,191,810 | **46,575,605** |
| **`zpaqfranz -m5`** | **45,915,367** | **43,194,463** |

**`-m5` is smaller than LOLZ on both corpora** (a tie on installers, 14.0% on
deflate), and today's `-m4` is 7.3% smaller on deflate. LOLZ doesn't win
anywhere by a margin that matters, so it doesn't go into Insane, and it
doesn't go beside Extreme either: Insane beats it on both corpora once it
runs `-m5`. That last clause is a dependency: see the reopening conditions
below. **No stage was written.** That's the right outcome of a
measure-first item, not a failed phase. The 2026-09-20 handoff said LOLZ
"qualifies as an Insane-tier alternative"; the third measurement removed
the case for it.

**What would reopen it, and nothing else:**
(a) a game corpus with DXT textures. That's LOLZ's headline claim, still
untested. If B6/B13's downloads produce one, the rematch is **against
zpaqfranz `-m5`**, not 7-Zip.
(b) B17 ending with Insane on `-m4` and **no** `-m5` option. Then LOLZ's
0.25% (vs Extreme) and 0.56% (vs Insane) on installers is unmatched again,
and whether that is worth a stage is the owner's call.
**B12a (plain FreeArc) was never measured and is not closed.** It now lives
under B14 (DArc 3.04, the maintained fork).

---

## 2. Findings worth not rediscovering

### The incumbent is whatever ships in the slot, not the nearest familiar tool

LOLZ was measured twice against 7-Zip and won both times. Against zpaqfranz,
the codec actually in the Insane slot, it lost. Two rounds of careful,
restore-verified work compared it against the wrong opponent. The
2026-09-20 session named the mistake itself ("Insane's final codec is
zpaqfranz, not 7-Zip"), and running that one comparison settled in an
afternoon what two rounds had left open. **Before measuring a challenger,
write down what currently occupies the slot it would take.**

### `-m5` was a source reading, and half of it was wrong

research/20 §8 recommends "`-m4 -t2`; `-m5` only for small precious sets",
and its Gotchas section adds "On 2 cores, -m4 is the realistic Insane
default". First measurement: right on installers (−0.60% for 3.02× the
compress time), **wrong on deflate data (−7.26%)**. `DEFAULT_METHOD = 4` in
`excmp/stages/zpaqfranz.py` still cites that reading. This is B17.
research/20 §8 now carries a dated correction note.

### zpaqfranz thread count never touches the bytes, and the app never sets it

`-t1` and `-t2` gave **byte-identical archives on both corpora**. It
compresses independent 64 MiB blocks, so on a single-block input `-t2` buys
nothing (111.6 s vs 119.0 s), and on four blocks it buys 241 s → 168 s for
2.2× the RAM. The opposite of LOLZ, where `-mt2` costs ratio.

**The app passes no `-t` by default.** The threads setting defaults to 0
("each tool chooses") in the CLI, the Settings tab and the Advanced panel,
and `ZpaqfranzStage` emits nothing for 0. zpaqfranz then picks **2 threads
on this laptop**. Measured: no switch reports `2T`, `-ht` reports `4T`. It
counts physical cores, which corrects research/20 §8's "all cores". So the
`-t2` rows are what default Insane runs *here*.

**Worth checking next session, not acted on:** CLAUDE.md says "Default
threads is **2**, not 4". The code's default is 0, the tool's choice. For
zpaqfranz that happens to come out as 2. For 7-Zip, what it picks with no
`-mmt` was not measured here, so whether the rule holds for Normal and
Extreme is open.

### Context mixing decodes as slowly as it encodes, and D9 pays that on every publish

zpaqfranz `-m4` restore: 110.5 s on 62 MB, 186.2 s on 237 MB. At `-m5`:
297.9 s on 62 MB, and 1,076.7 s / 986.5 s on 237 MB. LOLZ restores the same
62 MB in **0.4 s**. Every Insane
job replays the restore in the D9 gate before publishing, so Insane's real
wait is compress **plus** a near-equal decode. B17 must measure that total,
not the compress figure alone.

### A measurement launched from a session dies with it

The 2026-09-23 run stopped mid-restore at about the time the session ended:
exit code 4, no traceback, `x-deflate/` half-written. That fits the session's
end killing it, but it is not proven. **Every finished row survived,
because each was appended to a JSONL file as it landed** rather than being
collected and written at the end. The row in flight lost its compress time.
Its size was **not used** until the archive had been restored and hashed on
2026-09-26. For anything longer than a few minutes, keep doing both: write
each row as it lands, and never record a size whose restore you haven't
seen.

**And a re-run on a busy machine is not a timing.** The deflate `-m5`
compress, timed on 2026-09-26 while the doc-audit agents shared the cores,
took 1,070.4 s. File timestamps from the uncontended 2026-09-23 run put the
same compress at about 541 s. The input was byte-identical and so was the
output size. Don't quote either figure as `-m5`'s speed.

### Everything already established, still true

- **Two corpora, or don't quote the first.** B12's verdict changed every
  time a corpus or an opponent was added, across three rounds.
- **Never pin a single timing run, and never pin the first one.** The OS file
  cache alone moved an identical run 1.77×; zpaqfranz's three `-m4` repeats
  here spread 1.17×.
- **A silent no-op looks exactly like a negative result.** Exit 0 is not
  evidence; `cls-lolz` writes a 0-byte file and reports nothing on bad input.
- **The specialists that win compete with `store`, not with the chain.**
  xtool (B16) and LOLZ (B12) competed with the chain and both lost in the
  end; B4's FLAC, which competes with `store`, is still the only clear win.
- **`precomp -intense` is in the chain** and costs 82,086 B on B16's corpus;
  anything comparing against "our route" uses 51,827,136, not 51,745,050.
- **A measured ratio ranks the profiles; it does not forecast the job** (I6).
- **"Green" is a claim about what the tests look at.** Three defects shipped
  behind 900 passing tests; `tools/qa_sweep.py` has now caught five.
- **`~/.excmp/calibration.json` is global state** — the conftest fixture routes
  it to `tmp_path`; keep any new global file isolated the same way.
- **The archive is not byte-reproducible.** Compare payload size, never the
  archive digest.

---

## 3. Next phase: B17 — Insane at zpaqfranz `-m5`?

Spec: [ROADMAP.md, B17](ROADMAP.md) (directly under B12). The numbers so far are
bare zpaqfranz on B12's two `.pcf` intermediates:

| | `-m5` vs `-m4` size | compress | restore | peak RAM (compress) |
|---|---:|---:|---:|---:|
| installers, 62.5 MB | **−0.60%** | 3.02× | 2.70× | 2.0× |
| deflate, 237 MB | **−7.26%** | 3.2–6.4× (not clean) | 5.3–5.8× | 2.0× |

Sizes are firm: two `-m5` runs both produced 43,194,463 B and both restored
byte-identically. The deflate times are not (see §2).

**0. Plumbing first, on a branch. Nothing can run Insane at `-m5` today.**
`engine._stage_factory` builds `ZpaqfranzStage()` with no argument.
`StageOptions` (so the CLI's `--params`) reaches only 7-Zip and zstd.
`tools/bench.py` calls `engine.compress` with no options at all. And
`test_m5_is_reachable_but_deliberate` only covers the stage's own command
builder. So the first job is a way to select the method, with TDD. That's
code, so it goes on its own branch.

**Then, before any default moves, measure all four:**

1. **End to end through `engine.compress`**, not bare zpaqfranz: Silesia
   (B8's Insane anchor, **80.55%** at `-m4`, 16.7 min), the B12 installer
   sample, and B16's deflate zip. Use `tools/bench.py <dir> --profiles
   insane` once it can select the method. Repeat the runs on a quiet
   machine.
2. **The D9 verify pass.** At `-m5` the restore ran 2.70× slower on
   installers and 5.3–5.8× on deflate data. D9 replays it, so the user's
   total wait is what matters, not compress time.
3. **Peak RAM on multi-block input.** Measured at `-t2` on the 4-block
   deflate `.pcf`: **1,819 MiB** compressing at `-m5` (915 MiB at `-m4`) and
   1,691 MiB restoring. `excmp/ram.py` has a budget (`_RAM_BUDGET = 0.55`)
   but **no zpaqfranz model**. Build one from these numbers, and don't
   extrapolate past them.
4. **Everything downstream that assumes `-m4`**: `estimate.py`'s
   `precomp+zpaqfranz` slope (0.873, one Silesia anchor at `-m4`). Note also
   that **`_CODEC_RATE` and `_VERIFY_RATE` have no `precomp+zpaqfranz` key at
   all today**. So Insane's time estimate falls back to `_FALLBACK_RATE`
   (2.5 MB/s) and `_FALLBACK_VERIFY_RATE` (15 MB/s), unless J7 has learned
   a compress rate on the machine in question (`calibrate.blended_rates`
   never touches the verify rate). Bare zpaqfranz `-m4` measured here ran
   at about 0.53 / 0.57 MB/s (compress / restore) on the 62 MB installer
   `.pcf`, and 1.41 / 1.27 MB/s on the 237 MB deflate one.
   Those are not the same unit as the estimator's piped-bytes-through-the-
   whole-chain rate, so treat this as a lead, not a proof: **the fallback
   looks several times too optimistic already**, before `-m5` enters the
   picture. Then `gui/progress.py`'s `zpaqfranz` weight (50), and the
   preset card's "an overnight job" sentence.

**Options, deliberately not decided:** keep `-m4`; move Insane to `-m5`; or
keep `-m4` and offer `-m5` as a choice. That is the owner's call once (1)–(3)
exist. If `-m5` becomes a choice, note that `StageRecord.params` records only
`sevenzip`/`zstd` options today, so the method would have to be recorded too.
Restoring isn't the obstacle: one `zpaqfranz x` command, with no method
switch, restored `-m0`, `-m4` and `-m5` archives byte-identically.

TDD applies. The stage-level switch is already covered
(`tests/test_zpaqfranz.py`, `test_m5_is_reachable_but_deliberate`). What
needs a failing test first is the engine selecting it (step 0).

---

## 4. B13 — blocked on both halves (unchanged since 2026-09-20)

Full record:
[benchmarks/2026-09-20-b13](benchmarks/2026-09-20-b13-vorbis-baseline.md).
**Do not re-search for these**: no balrogg binary on this machine (the download
is behind a krinkels.org login), no game-audio corpus anywhere (the external
tree was fully enumerated, 412,055 files), no game installed.

**The defect found while establishing the gate still stands, unfixed on
purpose:** on the only Ogg on this machine (326 KB of UI blips), `engine.compress`
writes an archive 6,625 B *larger* than the input and tells the user the data is
"already compressed by its codec", while plain `7z -mx9` takes 21.4% off.
Nothing changed on 326 KB. When real data arrives the hook is
**`_UNCOMPRESSED_AUDIO`** (`planner.py:184`), not `_DEFLATE_MEDIA`. A patch to
`analyzer._EXT` alone is bypassed by the `OggS` magic-byte rule at
`analyzer.py:52`.

---

## 5. The downloads, in Chrome — needs the owner present

Unblocks B13 and B6, and gives LOLZ its only possible rematch (§1).

| target | unblocks | note |
|---|---|---|
| `balrogg` v1.1, krinkels.org resource `…-recompressor.601` | **B13** | behind a login. **Do not create or confirm an account.** If the address is still unconfirmed, that step is the owner's |
| genuine Ogg Vorbis / Opus **music**, not UI blips | **B13**'s gate | open-source games ship real libvorbis: 0 A.D., SuperTuxKart, Xonotic, OpenRA |
| `.wem` (Wwise) / `.fsb` (FMOD) banks | **B13 + B6** | Wwise's and FMOD's own free sample projects. **Not** repack or warez bundles |
| an Oodle/Kraken-compressed archive | **B6** | the untested half of B16 |

**Rules that do not bend:** confirm each download with the owner by name,
source and size before fetching; treat every binary as untrusted and pin its
SHA-256 on arrival; nothing measured on it moves routing until it has beaten
the shipped route **and** restored byte-identically through `verify_restore`.
High-bitrate Vorbis is *expected* near 0%. **B13 dying on real data is a
legitimate outcome**, and a cheaper one than keeping the item open.

---

## 6. Everything still open

### Small / medium
| item | what |
|---|---|
| **B17** | **recommended next**: Insane at `-m5`, §3 |
| **B13** | blocked on a krinkels.org download **and** a game-audio corpus (§5) |
| **B14** | DArc 3.04, the maintained FreeArc fork, now also carrying B12a (plain FreeArc, never measured). It must beat the *shipped* route, including zpaqfranz in Insane's slot, which is what sank LOLZ |
| **D6b** | more fuzz targets if wanted; the parser is covered |
| **I5** | Explorer context menu — **ask first**, writes to HKCU |
| **I10** | settings search, drag-out extract, jump list — the unfinished half |

### Large, or blocked
| item | status |
|---|---|
| **B6** | xtool + Oodle — blocked, no game corpus (same download as B13) |
| **B15** | ADDeX 0.1 — too early |
| **D4b** | the real-volume half — needs an elevated session for a VHDX |
| **Phase C** | C1–C7, the opt-in lossy phase |
| **Phase H** | H1–H6, Inno Setup generation |
| **E3–E5** | PyInstaller, signing, auto-update — only if this is ever shared |
| **I7** | ❌ won't do |
| **B12** | ❌ closed 2026-09-23. Reopens on (a) game/DXT data measured against `-m5`, or (b) B17 leaving Insane with no `-m5` at all (§1) |
| **B16** | ❌ closed 2026-09-15 |

---

## 7. Things not to re-litigate

- **LOLZ is not being integrated.** Measured against 7-Zip twice and
  zpaqfranz once; `-m5` beats it on both corpora. It reopens only on the
  two conditions in §1: game/DXT data measured against `-m5`, or B17
  leaving Insane with no `-m5` at all.
- **The repo is private and the OSI rule is retired.** Any tool may be used;
  the lossless guarantee matters *more* as a result.
- **Never weaken verification to fit a tool in.**
- **No AI attribution in commit messages, ever.**
- **`os.replace` needs no `unlink()` first.**
- **Windows cannot flush a directory.**
- **Extraction memory is controlled by `-mmt`, not the dictionary.**
- **Insane is data-dependent, not stronger.** Still true at `-m4`: it lost to
  Extreme by 0.31% on installers and won by 10.1% on deflate data this round.
- **SREP stays out** — it failed its own checksum 1 run in 3.
- **Four top-level tabs is the ceiling.**
- **A measured ratio ranks the profiles; it does not forecast the job.**
- **Run `tools/qa_sweep.py` and look at the images** before calling any GUI
  change done.
