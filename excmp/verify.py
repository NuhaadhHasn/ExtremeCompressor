"""Integrity: SHA-256 ledgers and restore verification."""

from __future__ import annotations

import hashlib
import os
import stat as _stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from .safepath import Within


class VerifyError(RuntimeError):
    """Restored data does not match the manifest's hash ledger."""


class SourceCheck(NamedTuple):
    """What re-reading the originals found (D5's ``v -ssd`` half).

    Three lists rather than one, because they are three different pieces of
    news and merging them would lose the distinction that matters:

    ``changed`` is the serious one - a file that is still there and no longer
    matches what the archive recorded. Short of a deliberate edit, that is
    bit-rot, and the archive is the only reference copy able to notice.

    ``missing`` is usually not a fault at all: files get moved and deleted, and
    an archive exists precisely so that can happen safely.

    ``extra`` is a file the archive never saw. Also not a fault - it normally
    means the source has moved on since - so it is reported and does not make
    the verdict false.
    """

    checked: int
    changed: list[str]
    missing: list[str]
    extra: list[str]


def verify_source(source_root: Path, ledger: dict[str, dict]) -> SourceCheck:
    """Re-read the *originals* and compare them against the archive (D5).

    The other direction from :func:`verify_restore`, and a different question:
    not "can this archive still produce its bytes?" but "are the originals
    still the bytes it recorded?". zpaqfranz splits these into ``t`` and
    ``v -ssd`` for the same reason.

    ``source_root`` is the directory the archive-relative keys hang off - the
    *parent* of what was archived, since a ledger key is
    ``<input name>/<path inside it>``.

    **Extras are only looked for inside what the archive covered.** Scanning
    all of ``source_root`` would report the archive itself, any temp directory
    beside it and every unrelated file in that folder - so the walk is limited
    to the top-level names the ledger mentions. Anything outside those is not
    this archive's business.

    Strictly read-only, including mtimes: a tool that disturbs the originals
    while checking on them has no business calling itself a backup check.
    """
    source_root = Path(source_root)
    changed: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    checked = 0

    within = Within(source_root)
    for rel, meta in ledger.items():
        p = within(rel)
        size = _regular_size(p)
        if size is None:
            missing.append(rel)
            continue
        checked += 1
        if size != meta["size"]:
            changed.append(f"{rel}: {size:,} bytes now, {meta['size']:,} "
                           f"when archived")
            continue
        if hash_file(p) != meta["sha256"]:
            changed.append(f"{rel}: same size, different content")

    known = set(ledger)
    tops = {rel.replace("\\", "/").split("/", 1)[0] for rel in ledger}
    for top in sorted(tops):
        base = within(top)
        if not base.is_dir():
            # A single-file input: its own ledger entry is the whole scope,
            # and it has already been checked above.
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(source_root).as_posix()
            if rel not in known:
                extra.append(rel)

    return SourceCheck(checked=checked, changed=changed,
                       missing=missing, extra=sorted(extra))


def _regular_size(path: Path) -> int | None:
    """The size of a regular file, or None when ``path`` is not one.

    ``is_file()`` followed by ``stat()`` asked the filesystem the same
    question twice for every restored file; one ``os.stat`` answers both, and
    follows links exactly as those two calls did.
    """
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return st.st_size if _stat.S_ISREG(st.st_mode) else None


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


#: Files up to this size are hashed a few at a time by `hash_files`; larger
#: ones one after another, where the bytes are the cost and two readers on a
#: spinning disk would only fight over the head.
_SMALL_FILE_BYTES = 1 << 20
#: How many small files are hashed at once. The wait being shared out is not
#: ours: measured 2026-11-25 on the i5-7200U, the *first* open of a file that
#: has just been written takes 15-19 ms while real-time protection scans it
#: (0.3 ms for the second open, 0.9 ms to create it), and a restore is
#: nothing but files that have just been written. 500 such files took 9.3-9.7 s
#: to read one at a time, 5.0-5.6 s two at a time and 3.9-7.2 s four at a time.
_HASH_WORKERS = max(1, min(4, os.cpu_count() or 1))
#: Below this many small files a pool costs more than it saves.
_POOL_FROM = 16


def hash_files(paths: list[Path], sizes: list[int]) -> list[str]:
    """:func:`hash_file` of every path, in the order given.

    The same function over the same files, so the digests are the ones a
    plain loop gives; only the waiting overlaps. An error reading any file
    propagates, as it does from the loop.
    """
    digests: list[str | None] = [None] * len(paths)
    small = [i for i, size in enumerate(sizes) if size <= _SMALL_FILE_BYTES]
    if len(small) >= _POOL_FROM and _HASH_WORKERS > 1:
        with ThreadPoolExecutor(_HASH_WORKERS,
                                thread_name_prefix="excmp-hash") as pool:
            for i, digest in zip(small, pool.map(hash_file,
                                                 [paths[i] for i in small])):
                digests[i] = digest
    for i, path in enumerate(paths):
        if digests[i] is None:
            digests[i] = hash_file(path)
    return digests          # type: ignore[return-value]


def tree_hash(digests: dict[str, str]) -> str:
    """One SHA-256 for a whole tree, independent of the order given (D5).

    The model is ``zpaqfranz sum``: combine per-file digests into a single
    value, so "these two trees are identical" becomes one comparison a user
    can write down today and check in a year.

    **Order-independent by canonicalisation, not by an order-free operator.**
    Combining digests with XOR or addition is the tempting shortcut and it is
    unusable here: XOR is self-cancelling, so a tree holding the same content
    at two paths collapses to the value of a tree holding *neither* copy. This
    program deduplicates identical files as a feature, so duplicate content is
    the ordinary case rather than a contrived one. Sorting the lines and
    hashing the result costs a sort and has none of that.

    **Each digest is bound to its path**, so two files swapping names is a
    different tree - a hash that said otherwise would call a scrambled restore
    correct.

    **Separators are normalised, case is not.** Ledger keys are always posix,
    but a caller may pass a Windows path for the same file. Case is left alone
    deliberately: ``a.txt`` and ``A.TXT`` are two files on the filesystems this
    project is tested against, and folding them would hide a real difference.

    The line format is `sha256sum`'s - digest, two spaces, path - so the value
    is reproducible outside this program:
    ``sort file.sha256 | sha256sum``.
    """
    lines = sorted(f"{digest}  {str(path).replace(chr(92), '/')}\n"
                   for path, digest in digests.items())
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def validate_ledger_entries(ledger: object) -> None:
    """Refuse a ledger whose entries this gate cannot read (D6).

    Raises :class:`VerifyError`, not ContainerError: by the time verification
    runs, "this archive is malformed" and "this restore does not match" are
    both answers about *this archive being unusable*, and the caller here is
    always somebody asking "is it good?". A `KeyError` was not an answer to
    that question.
    """
    if not isinstance(ledger, dict):
        raise VerifyError(
            f"the ledger is a {type(ledger).__name__}, not an object mapping "
            f"names to metadata - nothing can be verified against it")
    for rel, meta in ledger.items():
        if not isinstance(rel, str) or not isinstance(meta, dict):
            raise VerifyError(
                f"ledger entry {rel!r} is not a name mapped to metadata")
        for key in ("size", "sha256"):
            if key not in meta:
                raise VerifyError(
                    f"ledger entry {rel!r} has no {key!r}, so there is "
                    f"nothing to verify it against")
        if not isinstance(meta["size"], int) or isinstance(meta["size"], bool):
            raise VerifyError(
                f"ledger entry {rel!r} declares a size of type "
                f"{type(meta['size']).__name__}")
        if not isinstance(meta["sha256"], str):
            raise VerifyError(
                f"ledger entry {rel!r} declares a non-string sha256")


def verify_restore(out_dir: Path, ledger: dict[str, dict],
                   digests_out: dict[str, str] | None = None) -> int:
    """Check every ledger entry exists under ``out_dir`` with matching size
    and SHA-256. Returns the number of verified files; raises VerifyError.

    Ledger keys come out of the archive, so they are validated too. A hostile
    key raises :class:`~excmp.safepath.UnsafePathError` immediately rather than
    joining the ``problems`` list below: "this archive is malicious" and "this
    restore is corrupt" are different findings and should not share a message.
    Read-only, but a naive join still probes arbitrary files for size and hash.

    ``digests_out`` (D5), if a dict is passed, is filled with the digests this
    pass already computed. Every one of them is read and hashed here anyway,
    and :func:`tree_hash` needs exactly that map - so a deep verify gets its
    whole-tree value for the cost of a dict insert rather than a second full
    pass over the restored data.
    """
    out_dir = Path(out_dir)
    # D6. `meta["size"]` and `meta["sha256"]` below are direct subscripts on
    # archive-supplied metadata, so a ledger entry missing either one raised
    # KeyError out of the acceptance gate the whole product rests on. The
    # manifest parser validates the ledger's shape now, but this function is
    # public and is also called with ledgers that never came from a manifest -
    # so it refuses one it cannot read rather than trusting its caller.
    validate_ledger_entries(ledger)
    problems: list[str] = []
    # One `Within` for the pass: every name is still validated and its
    # canonical target still compared against the canonical `out_dir`; only
    # the canonicalization of `out_dir` itself is not repeated per file.
    within = Within(out_dir)
    found: dict[str, str] = {}
    present: list[tuple[str, Path, int]] = []
    for rel, meta in ledger.items():
        p = within(rel)
        size = _regular_size(p)
        if size is None:
            found[rel] = f"missing: {rel}"
        elif size != meta["size"]:
            found[rel] = f"size mismatch: {rel}"
        else:
            present.append((rel, p, size))
    # Every file that is there at the right size is read back and hashed, as
    # before; `hash_files` only lets the small ones wait on the disk together.
    digests = dict(zip((rel for rel, _, _ in present),
                       hash_files([p for _, p, _ in present],
                                  [size for _, _, size in present])))
    for rel, meta in ledger.items():        # ledger order, as it always was
        if rel in found:
            problems.append(found[rel])
        elif digests[rel] != meta["sha256"]:
            problems.append(f"hash mismatch: {rel}")
        elif digests_out is not None:
            digests_out[rel] = digests[rel]
    if problems:
        raise VerifyError(
            "restore verification FAILED:\n  " + "\n  ".join(problems[:20])
        )
    return len(ledger)
