"""Integrity: SHA-256 ledgers and restore verification."""

from __future__ import annotations

import hashlib
from pathlib import Path


class VerifyError(RuntimeError):
    """Restored data does not match the manifest's hash ledger."""


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify_restore(out_dir: Path, ledger: dict[str, dict]) -> int:
    """Check every ledger entry exists under ``out_dir`` with matching size
    and SHA-256. Returns the number of verified files; raises VerifyError."""
    out_dir = Path(out_dir)
    problems: list[str] = []
    for rel, meta in ledger.items():
        p = out_dir / rel
        if not p.is_file():
            problems.append(f"missing: {rel}")
            continue
        if p.stat().st_size != meta["size"]:
            problems.append(f"size mismatch: {rel}")
            continue
        if hash_file(p) != meta["sha256"]:
            problems.append(f"hash mismatch: {rel}")
    if problems:
        raise VerifyError(
            "restore verification FAILED:\n  " + "\n  ".join(problems[:20])
        )
    return len(ledger)
