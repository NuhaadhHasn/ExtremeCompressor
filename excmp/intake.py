"""I5: what the Explorer verbs hand the app, and the wire a second process uses to hand it on.

Qt-free on purpose: the CLI's ``excmp shell`` and the GUI both read this contract, and a test
can exercise it without a display.

**The command line.** The right-click verbs run ``<program> <action> "%1"``:

    compress      PATH...   queue files and folders on the Compress tab
    extract       ARCHIVE   open the Extract tab on the archive
    extract-here  ARCHIVE   open it and start extracting to the suggested folder
    verify        ARCHIVE   open it and start the restore check

A bare path (a file dragged onto the exe, "Open with") names no action, and is read as
``extract`` for one ``.excmp`` and ``compress`` for anything else.

**The wire.** Explorer starts one process per selected file, so the first process becomes the
window and the others forward what they were given to it over a per-user local pipe. Any
process of the same user can write to that pipe, so :func:`from_wire` believes nothing: a size
limit, a known action, a bounded list of plain strings, no NUL. It answers ``None`` to anything
else and never raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ACTIONS = ("compress", "extract", "extract-here", "verify")
#: These act on one archive; extra paths are ignored.
ONE_ARCHIVE_ACTIONS = frozenset({"extract", "extract-here", "verify"})
ARCHIVE_SUFFIX = ".excmp"

MAX_PATHS = 5_000
MAX_PATH_CHARS = 32_767          # the longest path Windows has
MAX_WIRE_BYTES = 1 << 20

#: Qt's own options that take a value: skipped together with it, so ``-platform offscreen`` never
#: reads "offscreen" as a path. Any other ``-flag`` is skipped alone.
_QT_OPTIONS_WITH_VALUE = frozenset({"-platform", "-style", "-stylesheet", "-geometry", "-title",
                                    "-display", "-platformtheme", "-plugin"})


@dataclass(frozen=True)
class Intake:
    action: str
    paths: tuple[Path, ...]


def _clean(text: str) -> str:
    return text.strip().strip('"').strip()


def _normalised(action: str, raw: Sequence[str]) -> Intake | None:
    seen: set[str] = set()
    paths: list[Path] = []
    for text in raw:
        text = _clean(text)
        if not text or "\x00" in text or len(text) > MAX_PATH_CHARS:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(Path(text))
        if len(paths) >= MAX_PATHS:
            break
    if not paths:
        return None
    if action in ONE_ARCHIVE_ACTIONS:
        paths = paths[:1]
    return Intake(action, tuple(paths))


def parse_intake(argv: Sequence[str]) -> Intake | None:
    """``argv`` without the program name. ``None`` means a plain launch: nothing to do."""
    words: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            skip = arg.lower() in _QT_OPTIONS_WITH_VALUE
            continue
        words.append(arg)
    if not words:
        return None
    action = words[0].strip().lower()
    if action in ACTIONS:
        return _normalised(action, words[1:])
    # No verb: decide from what was given.
    one_archive = len([w for w in words if _clean(w)]) == 1 and \
        _clean(words[0]).lower().endswith(ARCHIVE_SUFFIX)
    return _normalised("extract" if one_archive else "compress", words)


def to_wire(intake: Intake) -> bytes:
    return json.dumps({"v": 1, "action": intake.action,
                       "paths": [str(p) for p in intake.paths]},
                      ensure_ascii=False).encode("utf-8")


def from_wire(data: bytes) -> Intake | None:
    """Parse what arrived on the pipe, or ``None``. Never raises."""
    try:
        if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= MAX_WIRE_BYTES:
            return None
        obj = json.loads(bytes(data).decode("utf-8"))
        if not isinstance(obj, dict):
            return None
        action, paths = obj.get("action"), obj.get("paths")
        if not isinstance(action, str) or action not in ACTIONS:
            return None
        if not isinstance(paths, list) or not 0 < len(paths) <= MAX_PATHS:
            return None
        for p in paths:
            if not isinstance(p, str) or "\x00" in p or not 0 < len(p) <= MAX_PATH_CHARS:
                return None
        return _normalised(action, paths)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
