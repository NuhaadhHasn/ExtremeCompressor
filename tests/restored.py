"""One correct way to compare a restore against its source.

Six test files each grew their own version of "did this file come back?", and
all six matched on a filename **suffix**:

    match = [v for k, v in got.items() if k.endswith(rel)]

That is wrong in both directions, and Hypothesis proved it on 2026-09-04 by
shrinking to the smallest tree that exposes it::

    {'0': b'', '.0': b'repeating block '}

``'.0'.endswith('0')`` is True, so the empty file ``0`` matched the restored
``.0``, compared its hash against the wrong file's content, and reported a
corruption that had not happened. The product had restored both perfectly.

The false-*pass* is the worse half and nobody had hit it yet: if ``a.txt`` were
missing from a restore but ``backup-a.txt`` were present, the suffix match
would find it and the test would go green on a lost file.

This is the same defect an audit found in ``engine.compress_standard`` the day
before, where it was fixed by comparing whole sets. The fix never reached the
tests, which is exactly how a flawed idiom survives: it lived in helpers nobody
re-read.

So: **exact relative paths, compared as whole sets.** The one real complication
is that a restore reproduces the source *directory* too, so ``src/a.txt``
arrives as ``out/src/a.txt`` - handled by finding that common root once rather
than by matching loosely per file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def hash_tree(root: Path) -> dict[str, str]:
    """``{relative posix path: sha256}`` for every file under ``root``."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).rglob("*") if p.is_file()}


def _strip_common_root(got: dict[str, str], want: dict[str, str]) -> dict[str, str]:
    """Drop the wrapping directory a restore recreates, if there is one.

    Only ever strips a **whole leading component**, never a suffix, and only
    when doing so matches *more* of ``want`` than leaving it on. Callers pass
    anything from the complete tree to a single file, so "strip only on an
    exact set match" was too strict - it left `src/a.txt` unstripped when the
    caller asked about `a.txt` alone.

    Repeats while it keeps helping, because a restore can nest more than one
    level (an archive of a folder of a folder).
    """
    if not got or not want:
        return got
    current = got
    while True:
        matched = len(set(want) & set(current))
        if matched == len(want):
            return current
        roots = {key.split("/", 1)[0] for key in current if "/" in key}
        if len(roots) != 1 or not roots:
            return current
        stripped = {key.split("/", 1)[1]: value
                    for key, value in current.items() if "/" in key}
        if len(set(want) & set(stripped)) <= matched:
            return current          # stripping did not help; stop here
        current = stripped


def assert_restored_exactly(out_dir: Path, want: dict[str, str]) -> None:
    """Every file in ``want`` came back, byte-identical, and nothing else did.

    ``want`` is ``{relative posix path: sha256}`` - use :func:`hash_tree` on the
    source to build it.
    """
    got = _strip_common_root(hash_tree(out_dir), want)

    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    assert not missing, f"did not come back: {missing[:5]} (got {sorted(got)[:8]})"
    assert not extra, f"appeared from nowhere: {extra[:5]}"
    for rel, digest in want.items():
        assert got[rel] == digest, f"{rel!r} came back with different bytes"


def assert_all_present(out_dir: Path, want: dict[str, str]) -> None:
    """Every file in ``want`` came back byte-identical; extras are tolerated.

    For the cases that legitimately produce more than they were given - a
    foreign archive listing, say. Still an exact-name comparison: tolerating
    extras is not the same as matching loosely.
    """
    got = _strip_common_root(hash_tree(out_dir), want)
    for rel, digest in want.items():
        assert rel in got, f"{rel!r} did not come back (got {sorted(got)[:8]})"
        assert got[rel] == digest, f"{rel!r} came back with different bytes"
