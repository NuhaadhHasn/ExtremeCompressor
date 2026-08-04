# ExtremeCompressor — working agreement

MIT-licensed Windows compression app: Python + PySide6 orchestrating
7z/zstd/Precomp as subprocesses. Analyzes every file, routes it to the pipeline
that suits that data, and verifies a byte-identical restore before claiming
success.

## How to resume work

**If the user says "continue", "next", "go", `/next`, or gives no specific
task: read `docs/NEXT-SESSION-START-HERE.md` first, then the phase it names in
`docs/ROADMAP.md`, then start that phase.** Do not ask which phase — the handoff
doc names it and contains the decisions already made. Ask only if a genuine
blocking ambiguity remains after reading both.

At the end of a phase, rewrite `docs/NEXT-SESSION-START-HERE.md` for the next one:
repo state, what shipped, findings worth not rediscovering, decisions already made
(so they are not re-litigated), and the next phase's spec pointer.

## Pace

**One phase per session, little by little.** Finish the phase, update the docs,
commit, stop. Do not roll into the following phase.

## Commits

- **Never add AI attribution.** No `Co-Authored-By`, no "Generated with Claude
  Code", no Anthropic address. These are public portfolio repos and the trailer
  would put an AI in the GitHub contributors graph. Audit the message before
  committing.
- **Docs-only changes commit straight to `main`.** Code goes on a branch, left
  unmerged for review unless told otherwise.
- Pending files often sit in the **main checkout** even when the session runs from
  a worktree — check `git status` there too, not only in the worktree.

## Non-negotiable product rules

- **Lossless is a hard guarantee; lossy is always opt-in.** This is the product's
  identity, not a default to tune.
- **Post-restore SHA-256 comparison is the acceptance gate for every stage.** Tool
  exit codes cannot be trusted — Precomp `exit(0)`s even on fatal restore failure.
- **The repo stays 100% OSI-clean** (required for free SignPath code signing).
  Never bundle SREP, lolz, Oodle/oo2core DLLs, unrar.dll, or xtool Patreon builds.
- **Inputs are never modified.** Outputs are written to `.tmp` and atomically
  renamed only after the archive verifies.
- **Target hardware is weak on purpose**: 2-core i7-3540M, 16 GB, no hardware video
  encoder. Default threads is **2**, not 4. Calibrate every RAM/thread decision
  to it.

## Testing

```
.venv\Scripts\python.exe -m pytest -q
```

324 tests as of 2026-08-04; all must pass before a commit. Use TDD for anything
security- or integrity-related: write the failing test first.

Real corpora for end-to-end runs (slow external drive — never run recursive `du`,
it times out):

- `C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check\Programs`
  — 5.76 GB of installers and archives, 81% already-compressed. Worst-case ratio
  corpus, and a good false-positive check for the path validator.
- `...\Programming Tutorials, Guides, Course, and Files` — deep tree, likely more
  compressible, untested so far.

`docs/benchmarks/` records exact file subsets so runs are repeatable.

## Layout

- `excmp/` — engine (Qt-free, independently testable): `analyzer` → `planner` →
  `engine` → stages, with `manifest`/`verify`/`safepath` as the container +
  integrity layer.
- `gui/` — PySide6. `gui/suggest.py` is Qt-free prose/heuristics and is where
  recommendations live.
- `docs/research/NN-*.md` — research, source studies (13-22), 21 is the synthesis.
