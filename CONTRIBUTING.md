# Contributing

This repository is **private and single-maintainer** as of 2026-09-01, so this
file is not really a call for pull requests. It is the practical answer to
"how do I work in this codebase without breaking the one thing it promises" —
written down because the answer is specific, and because the rules below were
each learned by something going wrong.

If the repository is ever made public again, revisit this file *and*
`docs/ROADMAP.md`'s licensing note together: several tools now in use carry
obligations that only trigger on distribution.

## The one rule everything else serves

**Lossless is a hard guarantee. Lossy is always opt-in.**

The tagline promises a verified byte-identical restore, so the default path
makes that literally true: `compress()` restores the archive in a temp
directory and hash-compares every file against the ledger *before* the archive
is renamed into place. No hash match, no file — not a warning.

That gate exists because a tool's exit code is not evidence. Precomp `exit(0)`s
on a fatal restore failure, and SREP once failed its own decompression checksum
on 1 run in 3 over byte-identical input. **Never weaken the verification to
make a new tool fit.** Since the licence change any tool may be used, which
makes the gate more load-bearing rather than less — it is now the only thing
between a flaky third-party codec and a corrupt archive.

Two corollaries, both non-negotiable:

- **Inputs are never modified.** Outputs are written to a `.tmp` twin and
  atomically renamed only after the archive verifies.
- **Post-restore SHA-256 comparison is the acceptance gate for every stage.**

## Setting up

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Windows only, and deliberately: `safepath` pins Windows path semantics, `motw`
writes NTFS alternate data streams, and every external tool is an `.exe`.

7-Zip is the one tool worth installing by hand — most of the suite skips
without it. The rest are either pip packages (`zstandard`, `lepton-jpeg-python`,
`par2cmdline-turbo`) or hash-pinned downloads:

```
.venv\Scripts\python.exe -c "from excmp import toolfetch; [print(n, toolfetch.ensure_tool(n)) for n in toolfetch.TOOL_MANIFEST]"
```

To see what your machine actually provides:

```
.venv\Scripts\python.exe -c "from excmp.tools import find_tools; [print(f'{n:12} {t.path if t else chr(45)}') for n, t in find_tools(with_versions=True).items()]"
```

## Running the tests

```
.venv\Scripts\python.exe -m pytest -q
```

Four things about this command that are not obvious:

1. **A clean full pass takes about an hour** on a 2-core machine, and
   `pytest -q` buffers all of its output when stdout is not a terminal — so it
   looks hung the entire time. Check it is alive with
   `Get-Process python | Select Name,Id,CPU`, not by waiting for dots.
2. **Clear `%TEMP%\pytest-of-<you>` first.** Each run leaves 400–770 MB there
   and pytest keeps the last three; an aborted run leaves its tree on top.
   Four leftovers once took a 2.9 GB-free volume to 0.92 GB and the suite
   failed with `No space left on device` inside a compression test — which
   reads exactly like a real defect and is not one.
3. **Do not run a benchmark at the same time.** On two cores, both at once
   produces allocation failures in compression tests that also look like real
   defects.
   And **do not trust the elapsed time if the machine may have slept.** One
   run reported 11 h 28 m; the power log showed two sleep/resume cycles inside
   it. Hold the system awake for the duration of the process, or check
   `Get-WinEvent -ProviderName Microsoft-Windows-Kernel-Power` afterwards.
4. **A test that skips is not a test that passed.** Every chain test is behind
   `skipif(find_tools()[...] is None)`, so a machine without 7-Zip runs a
   green suite that has exercised none of the product. `pytest -q -rs` names
   every skip; read them.

### Before touching the tests, prove the real corpora are untouched

Three tests read the maintainer's actual data folders, read-only. "I read the
code and it looked read-only" is not evidence:

```
.venv\Scripts\python.exe tools\corpus_guard.py snapshot
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\corpus_guard.py compare
```

It records every file's size and mtime under the corpora and diffs after the
run, so any write, delete or create shows up.

### Before calling any GUI change done, render it and look

```
.venv\Scripts\python.exe tools\qa_sweep.py --out .qa
```

19 surfaces × 2 themes. A green suite has never once caught a visual defect
here; this has caught several — a progress bar rendered as a 55px slab, a
muted glyph invisible on a dark surface, a caveat sliced mid-word, and a
chooser advertising "100% or better", which would be an archive of zero bytes
or smaller.

## How the code is laid out

- `excmp/` — the engine, and **Qt-free** so it can be tested on its own:
  `analyzer` → `planner` → `engine` → stages, with `manifest`, `verify`,
  `safepath` and `atomic` as the container and integrity layer.
- `gui/` — PySide6. `gui/suggest.py` is Qt-free prose and heuristics, which is
  where recommendations belong.
- `docs/research/NN-*.md` — research and source studies; 21 is the synthesis.
- `docs/benchmarks/` — every measurement, with the exact file subsets, so a
  run is repeatable.

Keep the engine free of Qt imports. It is what makes the CLI, the tests and
the benchmarks possible without a display.

## Style, such as it is

Match the surrounding code. The one habit worth copying deliberately: **the
comments explain *why*, and cite the measurement.** A comment that says what
the line does is noise; a comment that says "measured: pinning the window at
31 raised peak working set 1,002 → 1,813 MiB" is the reason the next person
does not undo the fix.

## Testing expectations

- **TDD for anything touching security, integrity or estimation accuracy.**
  Write the failing test first. Three defects here shipped for weeks behind 900
  passing tests; what caught them was a property test and *rendering the GUI
  and looking at it*.
- A green suite proves nothing about what the tests do not look at. When you
  fix something, ask what class of thing it belongs to and test the class.
- Prefer a test that states the product's claim as an executable property over
  a test that pins an implementation detail.

## Confirm, do not hypothesise

**Never write down a number, a version, a licence or a behaviour that has not
been reproduced on this machine.** Documentation and third-party surveys are
leads, not evidence: one sweep produced 23 "confirmed" findings of which 7 were
wrong on re-check. Re-run the claim, then record what you measured — and if a
doc disagrees with your measurement, trust the measurement and correct the doc.

## Commits

- **No AI attribution.** No `Co-Authored-By` for an assistant, no "Generated
  with …" trailer.
- **Docs-only changes go straight to `main`.** Code goes on its own branch and
  is left unmerged for review.
- Write the *why* in the message. The commit log here is a usable history of
  what was measured and what it corrected; keep it that way.
- Every test must pass before a commit, and a benchmark claim in a message
  must be one you ran.

## Reporting a bug

Use the issue templates. For anything that lets an archive read or write
outside its destination, execute code, or bypass verification, use
[SECURITY.md](SECURITY.md) instead — privately.
