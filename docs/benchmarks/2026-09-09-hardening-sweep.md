# D5 · D6 · D7 · E2 · E6 · B10 · F5 — and two defects in features already marked DONE

**2026-09-09**, this laptop (2-core i7-3540M, 16 GB, Windows 10 Pro 19045).
Companion to [the D8 doc](2026-09-09-d8-atomic-publish.md), same day.

Seven roadmap items, and the two most important things in this document were
not any of them. Both were found by *auditing what already existed* rather than
by building what was next.

---

## 1. F2's keyfile was write-only ⚠️

The single serious finding. F2 shipped 2026-09-03 and is marked DONE in the
roadmap: "a keyfile as a real second factor", with an HKDF ordering argument,
a format bump to v2, a flags byte, and tests.

`engine.compress` accepted `keyfile=`. **Nothing on the read side passed one.**
Reproduced before anything was changed:

```
engine.compress([src], arc, NORMAL, ctx, password="pw", keyfile=kf)
  -> created: sealed.excmp 855 bytes

engine.extract(arc, out, ctx, password="pw")
  -> KeyfileRequired: sealed.excmp was created with a keyfile;
     supply the same file as well as the password

engine.extract(arc, out, ctx, password="pw", keyfile=kf)
  -> TypeError: extract() got an unexpected keyword argument 'keyfile'
```

So the engine could **write an archive that no code path in the engine could
read**. `excmp verify` — the product's central promise — could not open one
either. And the error message instructed the user to do something the API did
not permit: `--keyfile` existed on no subcommand, the word appeared **zero**
times in `excmp/cli.py`, and once in all of `gui/` — in a docstring saying
there is no keyfile field.

### Why nothing caught it

Two independent reasons, and both are worth remembering:

1. **`tests/test_keyfile.py` tests `crypto.encrypt_file`/`decrypt_file`
   directly**, where the parameter has always worked. The gap was between
   `crypto` and `engine`, which no test crossed with a keyfile.
2. **The D9 publish gate verifies the plaintext, by design.** F1's comment
   says it outright: "encrypt *after* the D9 gate and *before* the rename".
   The gate is the thing that would otherwise notice an unopenable archive, and
   it never sees the ciphertext. Nothing on either side of that seam tried to
   decrypt what was published.

### The fix, and the shape of the mistake

Threading `keyfile` through `opened_for_reading`, `extract`, `extract_any`,
`extract_selected`, `list_any` and `verify_archive` — and there were **two**
decryption sites, not one: `engine.extract` resolves an encrypted archive
itself rather than going through `opened_for_reading`. The one that would have
been missed by a careless patch is the one on the ordinary path.

**A factor plumbed through one of two sites is not plumbed.** That is the
generalisable lesson, and it is the same shape as K2's `dirs` field: a rule was
followed for the case in front of the author and not for the second instance of
it.

### Two more, found by running the command rather than the tests

The engine fix was green across 45 tests. Then a real CLI run:

| what was run | what happened |
|---|---|
| `verify sealed.excmp --password --keyfile my.key --deep` | **rc=2, "unrecognized arguments: --password"** — `excmp verify` had no `--password` flag at all, so no encrypted archive could ever be verified from the command line |
| `extract ... --password --keyfile wrong.key` | **`error: wrong password`** — the password was correct |

The second is not a wording quibble. It sends someone hunting for a password
they already have, and the conclusion after *"my password is right and it still
says wrong password"* is *"the archive is broken"* — which is how archives get
deleted. `decrypt_file` knows whether a keyfile was in play, so it now says so.

Final state, all six paths exercised through the real CLI:

| case | result |
|---|---|
| password + keyfile, compress | rc=0, 67 files, 840,958 → 233,414 B (72.24%) |
| password only, keyfile withheld | rc=1, names the **keyfile** |
| wrong keyfile | rc=1, "the password and keyfile together did not open … check both" |
| both factors, extract | rc=0, **67 restored, 67 verified** |
| both factors, `verify --deep` | rc=0, tree SHA-256 `4db468210b726345…` |
| `--keyfile` with no `--password` | rc=2, refused before writing anything |
| typo'd keyfile path | rc=1, "does not exist - nothing was written" |

---

## 2. D6 — fuzzing found eleven unhandled exception shapes

D0 hardened the parser **by hand** against the attacks somebody thought of.
Nothing had ever generated input at it. Every one of these was reproduced
before a line changed, and all are on the path `excmp list` takes for any file
a user points at:

| call | escaped as |
|---|---|
| `declared_total({"a": "not a dict"})` | `AttributeError` |
| `declared_total({"a": {"size": "abc"}})` | `ValueError` |
| `declared_total({"a": {"size": [1,2]}})` | `TypeError` |
| `declared_total({"a": {"size": None}})` | `TypeError` |
| `declared_total({"a": {"size": nan}})` | `ValueError` |
| `declared_total(["a"])` | `AttributeError` |
| `declared_total({"a": {"size": 10**400}})` | **returned happily** |
| `Manifest.from_json("[1,2,3]")` | `AttributeError` |
| `parse_size("1e400m")` | `OverflowError` |
| `parse_size("inf m")` / `"1e308t"` / 400 digits | `OverflowError` |
| `parse_size("nanm")` | `ValueError` |
| `verify_restore(d, {"a.txt": {}})` | `KeyError` |

The contract everywhere else in this codebase is that a malformed archive
raises `ContainerError`, which `cli.main` prints as one line and every caller
catches. An `AttributeError` escaping means the failure was never anticipated —
in code that reads attacker-chosen bytes.

### The one that is not cosmetic

`declared_total` was one line:

```python
return sum(int(meta.get("size", 0)) for meta in ledger.values())
```

Its result **is** the payload budget and D0.3's decompression-bomb budget. So
`{"size": 10 ** 400}` did not crash — it became a bound, and a bound of
10^400 bounds nothing. That is why the fix **refuses the archive** rather than
clamping the number: a ledger whose sizes cannot be read is a ledger whose
bounds cannot be trusted, and a guessed bound defeats the guard it exists to
enforce.

### One validation point, not four

`manifest.validate_ledger` runs once, in `Manifest.from_json`, on the same
principle that makes `safepath` the only place an archive-supplied *name* is
judged. Four readers downstream — `declared_total`, `verify_restore`,
`list_archive`, and the per-stage budget arithmetic — had each been trusting
the dict's shape independently. `verify_restore` keeps its own guard as well,
because it is public and gets ledgers that never came from a manifest.

### The soak

HypoFuzz was **not** used and is not installed (absent from `.venv`, from
`venvPython`, and from `requirements-dev.txt`). It was not needed: the
interesting surface is pure byte-in — a manifest string, a ledger dict, a
sidecar text, a name — so Hypothesis, a dev dependency since D1, generates at
it fast enough.

```
.venv\Scripts\python.exe tools\fuzz_container.py --examples 5000
```

| property | time |
|---|---:|
| `manifest.from_json` (text) | 10.8 s |
| `manifest.from_json` (json) | 47.4 s |
| `manifest.declared_total` | 54.4 s |
| `safepath.safe_relpath` | 4.9 s |
| `volumes.parse_size` | 3.8 s |
| `slt.parse_slt` | 10.2 s |
| `slt.classify_failure` | 4.1 s |
| **total** | **135.7 s** |

**35,000 examples, no property violated.** Which is not proof of absence — it
is the absence of a counterexample at that example count, and the tool says so
in those words when it passes.

---

## 3. D5 — the deep verify, and what it costs

`verify_archive` already was zpaqfranz's `t`: decompress everything, re-hash
every file against the ledger, need no source. The missing verb was `v -ssd` —
re-read the **originals** off disk and compare them against what the archive
recorded. Different question, and one nothing else here could answer: *are my
originals still the bytes I archived?* The archive is the only reference copy
of that answer.

### Measured on real data

56 files, 2.5 MB (the repo's own `docs/` tree), archive 2.1 MB:

| run | elapsed |
|---|---:|
| shallow verify ×3 | 3.8 / 4.3 / 4.7 s — mean **4.27 s** |
| deep verify ×3 | 4.1 / 3.6 / 4.7 s — mean **4.13 s** |

**Deep mode costs nothing measurable**, because the tree hash is built from
digests `verify_restore` already computed — one dict insert per file instead of
a second pass. The tree SHA-256 was identical on all three runs
(`4bf9ccee6c8bd98c…`). The `--source` pass adds one read of the originals
(2.5 MB here, 7.1 s total).

### And it detects what it is for

One bit flipped in `ROADMAP.md` (size unchanged at 120,313 bytes), one file
deleted, one file added:

```
OK: 56 file(s) restored and 56 SHA-256 hash(es) verified … in 3.0s
     tree SHA-256 4bf9ccee6c8bd98c8d81dae232405a33fa0e204e5af83e9c88d9fea7485f8820
Source re-read: 55 original(s) compared against the archive
  CHANGED  docs/ROADMAP.md: same size, different content
  missing  docs/NEXT-SESSION-START-HERE.md
  new      docs/appeared-later.txt
exit=1
```

Note what did **not** change: the tree hash. The archive is fine; the source
decayed. Those are separate findings and the output keeps them separate — a
deletion is not corruption (an archive exists so deleting an original is safe),
a new file is news, and only the *changed* one sets the exit code.

### Sort-then-hash, not XOR

Combining digests with XOR is order-free without needing a sort, and unusable
here: XOR is self-cancelling, so a tree holding the same content at two paths
hashes **identically to a tree holding neither copy**. This program
deduplicates identical files as a feature, so duplicate content is the ordinary
case rather than a contrived one. Sorting `digest  path` lines and hashing the
result is order-independent by canonicalisation, binds each digest to its path
(two files swapping names is a different tree), and is reproducible outside
this program with `sort file.sha256 | sha256sum`.

---

## 4. D7 — two "green means nothing" holes in my own first draft

Both were in the CI file I had just written, and both would have produced a
green build that proved nothing:

1. **`ensure_tool` returns `None` on failure and never raises** — correct for
   the app ("a download that fails should look exactly like a tool that was
   never there rather than crash a job"), wrong for a job whose entire purpose
   is that those tools exist. The `pinned-tools` job would have printed
   `qpdf None`, exited 0, skipped every chain test and reported success.
2. **Every chain test is behind `skipif(find_tools()["7z"] is None)`** — so a
   runner image without 7-Zip yields a *green* suite that has exercised none of
   the compression, publishing or verification paths. The roadmap asserted
   7-Zip ships on `windows-latest`; that could not be verified from here, so
   the gate job now checks, installs from Chocolatey if the image lacks it, and
   **fails loudly** if it still cannot get one.

`pytest -q -rs` everywhere, so silent skips stop being silent.

**And a third, in my own test file:** the corpus-path guard —
`test_no_ungated_corpus_paths`, the one test protecting CI from a future
hard-coded absolute path — was behind the module's `importorskip("yaml")`. A
half-installed dev environment would have silently disabled it. It takes no
yaml fixture now.

**D7 stays amber.** A workflow that has never run is not evidence.

---

## 5. E2 — 40 licences, read from files

Every claim in `THIRD-PARTY-NOTICES.md` now cites the path it came from. 39 of
40 confirmed; **1 explicitly not**. What re-reading corrected:

| component | the old file said | the files say |
|---|---|---|
| 7-Zip | "LGPL-2.1 + unRAR restriction" | a per-component mix: LGPL main, LGPL+unRAR for the RAR engine, BSD-3 for LZFSE (Apple) and ZSTD decode (Facebook), BSD-2 for XXH64 — `C:\Program Files\7-Zip\License.txt`, 6,031 bytes, 7 mentions of unRAR |
| qpdf | "Apache-2.0" | Apache-2.0 **with an at-your-option fallback to Artistic-2.0**, in every shipped header |
| Precomp | "Apache-2.0" | Apache-2.0 *itself*, but bundles packJPG, packMP3, bZip2, zLib and GifLib whose licence texts are **not present here** |
| FLAC | "BSD (libFLAC) / GPL (flac CLI)" | correct, and we invoke the **GPL** half |
| par2cmdline-turbo | "GPL binary, subprocess only" | `License-Expression: GPL-2.0-or-later`, and it is a **runtime pip dependency** whose wheel ships `par2.exe` |
| zpaqfranz | "FOSS (GPL/MIT heritage)" | ⚠️ **no licence file exists beside the binary.** `tools/bin` holds exactly `flac/`, `qpdf/` and a bare 4,288,000-byte `zpaqfranz.exe` |

The zpaqfranz row is the point of doing this properly. It is used, it is not
redistributed, so nothing is broken — but the previous file asserted a licence
no file here supports, and that is the kind of claim that only gets caught when
somebody goes looking. Recorded as a gap rather than guessed.

Also found: `pyoxipng` 9.1.1 is installed, imported nowhere, and in no
requirements file — a leftover from B3's evaluation, which oxipng lost.

---

## 6. B10 — half already true, half saying something false

Lepton **is** the in-process wheel (`excmp/jpeg.py` imports
`lepton_jpeg_python`, round-trips through `compress_bytes`/`decompress_bytes`,
and self-checks bit-exactness), and it is in no tool manifest. But `zstd` was
still a row in `tools.CANDIDATES` with an empty path list, so the Settings tab
printed:

```
zstd — not installed
```

…for the codec that runs the entire Fast profile, in-process, whose stage's
`available()` is literally `return True  # pure pip dependency`. That reads as
a degraded install and invites a pointless download.

Fixed with a **qualifier, not a deletion**, following the `LEGACY_ONLY`
precedent already in `tools.py`. It now reads *"zstd — built in, no executable
needed (in-process via the zstandard wheel)"*, sitting next to `ffmpeg — not
installed`, which genuinely is absent. Rendered in both themes and looked at.

Deleting the row was the tempting option and is worse: `zstd` is also a
**stage** id — the planner, the estimator and the progress model all speak that
name — so removing it would leave a name with no entry anywhere explaining why
it has no binary, and would break the tool-table shape `tests/test_tools.py`
pins.

---

## 7. F5 — the wording was honest, the delivery was not

An audit of **all 42 user-visible crypto strings** across `gui/` and
`excmp/cli.py`. The findings, each verified in the source before it was
changed:

| where | the problem |
|---|---|
| `preset_cards.py:136-139` | the clearest sentence in the app is a **tooltip** — it needs a mouse hover, so a keyboard or screen-reader user could set a password having never been shown it |
| `preset_cards.py:236-247` | `_show_protect` **replaced** the consequence with "The two entries do not match yet." for the whole time somebody was typing the confirmation — the exact moment they are deciding. Its own docstring reads *"Say the unrecoverable part while they are still typing it"* |
| `preset_cards.py:134` | the placeholder read "leave empty for no password" — the only text in the field before anybody types, framing it as a costless convenience |
| `preset_cards.py:135`, `:143` | the accessible **names** carry no consequence, and a screen reader commonly does not announce a tooltip |
| `cli.py:312` | the create prompt said **nothing**. The most complete statement of the consequence anywhere in the codebase is `_new_password`'s **docstring**, printed to nobody |

Now: the consequence stands from the first keystroke with the mismatch notice
*appended*; it is in `accessibleDescription`, which is the channel announced
after the name; the placeholder says "empty for none - if set, there is no
recovery"; and the CLI prints it before prompting — **to stderr**, so `--json`
output stays parseable, because a human-readable warning on stdout would make
the honest thing a bug.

**The existing test could not have caught any of it.**
`test_the_password_warning_says_there_is_no_recovery` builds
`password.toolTip() + " " + protect_note.text()` from a fixture where nothing
has been typed — so `protect_note` is `""` and it asserts on the tooltip alone.
The visible warning could have been deleted entirely and it would still have
passed. The 12 new tests type into the fields.

---

## 8. How this session was run, and what that cost

Worth recording because it was avoidable:

- **Three full-suite runs were started; two were invalidated** by editing
  `excmp/` while they ran. A run against a tree that no longer exists proves
  nothing. **Freeze the code, then start the suite.**
- **The suite failed once with a genuine `No space left on device`** inside
  `test_zstd_window.py`, which reads exactly like a K4 regression. It was four
  leftover `%TEMP%\pytest-of-nuhaa` trees (400–770 MB each; pytest keeps three,
  and aborted runs leave theirs on top) taking `C:` from 2.9 GB to 0.92 GB.
  All 13 tests in that file pass with the directory cleared.
- **The runtime is unstable by 4.5x and the cause is not established.** Three
  runs of the same 1,174 tests, system held awake for each:

  | date | free on `C:` | wall clock |
  |---|---:|---:|
  | 2026-09-09 | 2.9 GB | 1 h 07 m |
  | 2026-09-10 | 14 GB | **14 m 52 s** |

  Free space is the variable that moved most, and this suite writes 400-770 MB
  per run into `%TEMP%` on a volume that was 99% full - but **two points do not
  prove a mechanism**, and it is recorded here as unexplained rather than
  attributed. The earlier ~31-minute figure is separately void: that run had
  two tests fail early and never do their work. **Do not quote a runtime for
  this suite; measure it.**
- **And one run reported 11 h 28 m, which was the laptop sleeping.** The
  System event log settles it: `Microsoft-Windows-Kernel-Power` recorded the
  machine entering sleep at 23:59:20, thirty-nine minutes after the suite
  started, again at 04:32:07, with `ResumeCount` reaching 3 by the time it
  finished. **`pytest`'s own elapsed time is not a measurement on a machine
  that can sleep**, and neither is any benchmark left running overnight here.
  Hold the system awake for the duration of the process
  (`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`, which is
  scoped to the calling process and touches no power setting), or check the
  power log before believing a long wall-clock.
- **One API break got through to the full run**: `verify_restore` gained an
  optional `digests_out` for D5 and the caller passed it *positionally*, which
  broke the two-argument spies `tests/test_publish_gate.py` uses to prove the
  D9 gate verifies the full ledger. Fixed at the caller, not in the test - an
  optional parameter must not change the shape of the call every existing
  caller was written against, and a pin that precise should not have to be
  edited because somebody added an argument it does not care about.
- The parallel audit that found F2's defect, all 42 crypto strings, the fuzz
  targets and the 40 licence paths ran as **46 read-only agents in ~107
  minutes**, while implementation continued. Its own output flagged one of its
  line-number passes as wrong by a uniform 35 lines and said so, which is why
  every load-bearing claim here was re-verified by hand before being written
  down.
