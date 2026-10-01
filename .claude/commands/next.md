---
description: Resume ExtremeCompressor at the next roadmap phase (or the owner's agenda) from the handoff doc
---

Continue ExtremeCompressor. Do not ask me which phase or for any prompt — work it
out from the docs.

## 0. Name the session first

**Before anything else**, name this session. `set_session_title` is a deferred
tool, so load it explicitly — this step has been skipped before because the tool
was not loaded:

1. `ToolSearch` with query `select:mcp__ccd_session_mgmt__set_session_title`.
2. Read the first screen of `docs/NEXT-SESSION-START-HERE.md` to learn the phase
   or agenda.
3. Call `mcp__ccd_session_mgmt__set_session_title` with `session_id: "self"` and a
   title naming the work, e.g. "I11 verify progress + B13 balrogg + B14 DArc".
   Never "/next", never "Next steps".

## 1. Read before writing

1. Read `docs/NEXT-SESSION-START-HERE.md` in full. It names the phase — or, when
   the owner has asked for several things, an **agenda** in a fixed order — plus
   the repo state and the decisions already made. **Do not re-litigate those.**
2. Read each item's section in `docs/ROADMAP.md`, plus any `docs/research/` or
   `docs/benchmarks/` record it cites.
3. Read the source files the handoff names before writing anything. Where it says
   something already exists, **extend it rather than rebuilding it**.
4. If the handoff says to **open browser tabs for the owner** (sites they sign in
   to and download from themselves), open them in the built-in browser pane
   straight away, then carry on with the first item while they download. Never
   type credentials or create accounts yourself.
5. If the handoff flags a decision for the owner at the start, ask that one
   question now, before writing code. Otherwise proceed.

## 2. Work each item

- **Downloads**: ask the owner once per batch, naming each file, its source and
  its size, before fetching anything. Prefer a GitHub release asset with a
  published SHA-256 (fetch through `excmp/toolfetch.py`'s pinned path where it
  fits). Pin every hash on arrival. Treat every binary as untrusted: nothing it
  produces counts until `verify_restore` has restored it byte-identically.
- **TDD**: failing tests first, especially for anything touching security,
  integrity, or estimation accuracy.
- **Measure, don't assume**: a real end-to-end run on a corpus from `CLAUDE.md`
  or the handoff, two corpora before quoting a ratio, and the actual numbers
  reported. Check `Win32_Processor` before quoting a speed.
- Run the full suite with the corpus guard around it
  (`C:\excmp-bench\b17\suite.py`, or the three commands in `CLAUDE.md`). Every
  test must pass. For a GUI change, also run `tools/qa_sweep.py` and look at the
  images, in both themes.
- Before merging, an adversarial review: two or three reviewers on different
  lenses, plus a skeptic who tries to refute each finding. Fix only what
  reproduces.

## 3. Commit, merge, document

- **No AI attribution** in any commit message. Audit each one.
- Docs-only changes go straight to `main`.
- Code goes on its **own branch per item**. Push the branch and wait for **CI
  green on the branch** (CI runs on every branch push). Then merge to `main`
  with `--no-ff`, push, and **delete the branch** locally and on GitHub. The
  owner asked for this on 2026-10-01 in place of leaving branches for review.
- Tick the completed items in `docs/ROADMAP.md` and record anything the work
  corrected about the plan, including numbers that came out different.
- Rewrite `docs/NEXT-SESSION-START-HERE.md` for what comes next.

## 4. Scope and stopping

Do the phase, or the agenda in its order. If context runs short, finish the item
in hand, commit and merge it, and rewrite the handoff so the remaining items are
the next session's agenda. Say clearly what was left out and why.
