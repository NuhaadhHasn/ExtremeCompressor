---
description: Resume ExtremeCompressor at the next roadmap phase from the handoff doc
---

Continue ExtremeCompressor. Do not ask me which phase or for any prompt — work it
out from the docs.

1. Read `docs/NEXT-SESSION-START-HERE.md`. It names the next phase, records the
   repo state, and lists decisions already made — **do not re-litigate those**.
2. Read that phase's section in `docs/ROADMAP.md` for the numbered items, plus any
   `docs/research/` docs it cites.
3. Read the source files the handoff names before writing anything. Where it says
   something already exists, **extend it rather than rebuilding it**.
4. If the handoff flags a decision for me to make at the start of the session, ask
   that one question now, before writing code. Otherwise proceed.

Then implement the phase:

- **TDD**: failing tests first, especially for anything touching security,
  integrity, or estimation accuracy.
- Run the full suite (`.venv\Scripts\python.exe -m pytest -q`) — every existing
  test must still pass.
- Do a **real end-to-end run**, not just unit tests, using a corpus from
  `CLAUDE.md`. Report the actual numbers.
- Tick the completed items in `docs/ROADMAP.md` and record anything the
  implementation corrected about the plan — including numbers that turned out
  different from predicted.
- Rewrite `docs/NEXT-SESSION-START-HERE.md` for the following phase.
- Commit: **no AI attribution** in the message. Docs-only → straight to `main`;
  code → its own branch, left for me to review. Tell me the branch name and the
  merge command.

Stop after the one phase. If the phase is large enough that context runs short,
finish a coherent subset, commit it, and write the handoff so the remainder is the
next session's job — say clearly what you left out.
