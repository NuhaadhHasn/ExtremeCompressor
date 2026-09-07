"""Prove the test suite never modifies the real corpora.

Two tests read from folders that hold the user's actual data:

- ``tests/test_estimate_backtest.py`` -> ``0No Need To Check\\Programs``
- ``tests/test_audit_regressions.py`` -> ``My Graphical Projects``

Both only call ``read_bytes()`` and ``stat()``, and the engine's own contract
is that inputs are never touched. But "I read the code and it looked read-only"
is not evidence, and this is the user's data. So: snapshot every file's name,
size and mtime before a suite run, snapshot again after, and diff.

Metadata is sufficient and cheap. Any write changes the size or the mtime, a
delete removes the entry, and a new file adds one - so a clean diff over
name+size+mtime is a real proof of "nothing was touched", without re-hashing
gigabytes on a slow external drive.

    .venv\\Scripts\\python.exe tools\\corpus_guard.py snapshot
    .venv\\Scripts\\python.exe -m pytest -q
    .venv\\Scripts\\python.exe tools\\corpus_guard.py compare
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Every folder the suite is known to read from. Add to this, never remove.
WATCHED = [
    Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
         r"\0No Need To Check\Programs"),
    Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
         r"\0No Need To Check\My Graphical Projects"),
]

STORE = Path(__file__).resolve().parent.parent / ".corpus-snapshot.json"


def snapshot() -> dict[str, list]:
    """``{path: [size, mtime_ns]}`` for every file under every watched root."""
    out: dict[str, list] = {}
    for root in WATCHED:
        if not root.exists():
            print(f"  (skipped, not present: {root})")
            continue
        count = 0
        for path in root.rglob("*"):
            try:
                if not path.is_file():
                    continue
                info = path.stat()
            except OSError:
                continue        # unreadable is not the same as modified
            out[str(path)] = [info.st_size, info.st_mtime_ns]
            count += 1
        print(f"  {count:>6,} files under {root.name}")
    return out


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "snapshot"

    if mode == "snapshot":
        print("Snapshotting the real corpora (metadata only, nothing is read)...")
        data = snapshot()
        STORE.write_text(json.dumps(data), encoding="utf-8")
        print(f"\n{len(data):,} files recorded -> {STORE.name}")
        return 0

    if mode == "compare":
        if not STORE.exists():
            print("No snapshot to compare against. Run 'snapshot' first.")
            return 2
        before = json.loads(STORE.read_text(encoding="utf-8"))
        print("Re-reading the real corpora...")
        after = snapshot()

        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(p for p in set(before) & set(after)
                         if before[p] != after[p])

        print()
        print(f"  files before : {len(before):,}")
        print(f"  files after  : {len(after):,}")
        print(f"  added        : {len(added)}")
        print(f"  removed      : {len(removed)}")
        print(f"  modified     : {len(changed)}")
        for label, group in (("ADDED", added), ("REMOVED", removed),
                             ("MODIFIED", changed)):
            for path in group[:10]:
                print(f"    {label}: {path}")

        if added or removed or changed:
            print("\n>>> THE SUITE TOUCHED YOUR DATA. This must be fixed.")
            return 1
        print("\n>>> Clean: not one file was added, removed or modified.")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
