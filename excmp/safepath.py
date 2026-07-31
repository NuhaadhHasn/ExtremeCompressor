"""One shared validator for every path that comes out of an archive.

An archiver parses untrusted input, so any path an archive supplies -- a zip
entry name, ``manifest.payload_name``, a ledger key -- is attacker-controlled
and must pass through here before it touches the filesystem.

**We reject rather than rewrite**, which is a deliberate departure from 7-Zip,
NanaZip and PeaZip: all three *mangle* hostile names (``..`` dropped, bad
characters replaced with ``_``). They have to, because they read foreign
archives whose names were legal on the machine that made them. Our situation is
different in a way that settles the question: the manifest's SHA-256 ledger
keys are the authoritative filenames, so a rewritten name could never satisfy
:func:`excmp.verify.verify_restore` anyway. Mangling would only convert a clear
"this archive is hostile" into a puzzling hash mismatch. Anything reaching these
rules is corrupt or malicious, and saying so plainly is the honest outcome.

The rule set is the union of those three shipped sanitizers -- 7-Zip 26.02
``ExtractingFilePath.cpp`` (research/19 section 7), NanaZip (research/14
section 6) and PeaZip (research/17 section 5) -- plus the bidi controls, which
7-Zip deliberately leaves unsanitized in ordinary path components (its
replacement is commented out at ``ExtractingFilePath.cpp:33,47``). The Windows
rules are applied on every OS: an ``.excmp`` is a portable container, and a
name that cannot be restored on Windows would make it silently non-portable.

PeaZip shipped a traversal CVE in 2026 *despite* having a sanitizer, so the
lesson taken from all three is redundancy: validate the name, then
canonicalize the join and compare it against the destination again.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import NoReturn

# A component longer than this cannot be created on any mainstream filesystem;
# an over-long total path is a cheap way to provoke filesystem errors.
MAX_COMPONENT_CHARS = 255
MAX_PATH_CHARS = 4096

# Illegal on Windows in a filename. ':' is handled separately so the error can
# say whether it looked like a drive letter or an alternate data stream.
_ILLEGAL_CHARS = frozenset('*?<>|"')

# Bidirectional formatting controls. "\u202egpj.exe" renders in Explorer as
# "exe.jpg" while still executing as an .exe -- the classic extension spoof.
_BIDI_CONTROLS = frozenset(
    "\u200e\u200f"                    # LRM, RLM
    "\u202a\u202b\u202c\u202d\u202e"  # embeddings and overrides (RLO = U+202E)
    "\u2066\u2067\u2068\u2069"        # isolates
)

_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{d}" for d in "0123456789"]
    + [f"LPT{d}" for d in "0123456789"]
)

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class UnsafePathError(ValueError):
    """An archive-supplied path is not safe to use as a destination."""


def _reject(name: str, reason: str) -> NoReturn:
    shown = name if len(name) <= 120 else name[:117] + "..."
    raise UnsafePathError(f"unsafe archive path {shown!r}: {reason}")


def _device_stem(part: str) -> str:
    """The name Windows compares against its device list.

    Everything before the first dot, with trailing dots and spaces stripped,
    upper-cased -- which is why ``NUL.txt`` and ``COM1 .log`` are every bit as
    dangerous as a bare ``NUL``, and why a substring check would be wrong
    (``CONSOLE.txt`` and ``NULL.txt`` are perfectly ordinary filenames).
    """
    return part.split(".", 1)[0].rstrip(" .").upper()


def _check_component(part: str, name: str) -> None:
    if part == "":
        _reject(name, "empty path component")
    if part in (".", ".."):
        _reject(name, f"path traversal component {part!r}")
    if len(part) > MAX_COMPONENT_CHARS:
        _reject(name, f"component longer than {MAX_COMPONENT_CHARS} characters")
    for ch in part:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            _reject(name, f"control character U+{ord(ch):04X} in {part!r}")
        if ch in _BIDI_CONTROLS:
            _reject(name, f"bidirectional override U+{ord(ch):04X} in {part!r}")
    if ":" in part:
        if _DRIVE_RE.match(part):
            _reject(name, "drive letter")
        _reject(name, "':' (NTFS alternate data stream)")
    illegal = sorted(set(part) & _ILLEGAL_CHARS)
    if illegal:
        _reject(name, f"character(s) {''.join(illegal)!r} not allowed in a filename")
    if part[-1] in ". ":
        _reject(name, "component ends with a dot or a space")
    stem = _device_stem(part)
    if stem in _RESERVED_NAMES:
        _reject(name, f"reserved Windows device name {stem}")


def safe_relpath(name: str) -> PurePosixPath:
    """Validate an archive-supplied name and return it as a relative path.

    Raises :class:`UnsafePathError` with a specific reason. Both ``/`` and
    ``\\`` are treated as separators: our writer only ever emits ``/``, but
    splitting on both means ``..\\..\\x`` is reported as traversal rather than
    sneaking through as one odd-looking filename.
    """
    if not isinstance(name, str):
        _reject(str(name), f"expected a string, got {type(name).__name__}")
    if name == "":
        _reject(name, "empty name")
    if len(name) > MAX_PATH_CHARS:
        _reject(name, f"longer than {MAX_PATH_CHARS} characters")
    if "\x00" in name:
        _reject(name, "NUL byte")

    parts = name.replace("\\", "/").split("/")
    if parts[0] == "":
        # Covers "/x", "\\x", UNC "\\\\server\\share" and "\\\\?\\C:\\x", all of
        # which produce a leading empty component once split.
        _reject(name, "absolute path")
    for part in parts:
        _check_component(part, name)
    return PurePosixPath(*parts)


def resolve_within(base: Path, name: str) -> Path:
    """Validate ``name`` and join it under ``base``, refusing any escape.

    The second, redundant layer: even with every component validated, the
    canonicalized join is compared against the canonicalized destination
    before the caller is allowed to write. Both sides are resolved, because on
    Windows ``base`` is often reached through an 8.3 short name or a symlinked
    temp directory -- resolving only the target would make every legitimate
    write look like an escape.

    Returns the *unresolved* join, so the caller writes exactly where it asked
    to rather than through a canonicalized path.
    """
    rel = safe_relpath(name)
    base = Path(base)
    target = base.joinpath(*rel.parts)
    try:
        resolved = target.resolve()
        base_resolved = base.resolve()
    except OSError as exc:  # pragma: no cover - platform dependent
        _reject(name, f"cannot be resolved ({exc})")
    if resolved == base_resolved:
        _reject(name, "resolves to the destination directory itself")
    if not resolved.is_relative_to(base_resolved):
        _reject(name, f"escapes the destination directory {str(base)!r}")
    return target
