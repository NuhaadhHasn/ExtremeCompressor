"""I3 — job history that outlives the queue.

`clear_finished()` used to delete a finished job outright, and closing the
window did the same, so the record of what was compressed, how well it went and
which settings produced it vanished the moment somebody tidied up. That record
is the one thing this app is uniquely placed to keep: it knows the profile, the
resolved chain, the real elapsed time and the achieved ratio for every job that
has ever run on this machine.

Deliberately dull: a JSON file with a hard cap, newest first, and a corrupt one
costs the history and nothing else. It is a convenience, not a ledger — the
manifest inside each archive is the thing that carries guarantees.

**No secret ever goes in here.** There is no field for a password or a keyfile,
which is the only reliable way to be sure none is written: this file outlives
the session, and the whole reason the app prompts rather than accepting a
password on argv is that it should not end up written down.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from excmp.atomic import PublishError, atomic_write_text

#: Beside the app's other state, so clearing ``~/.excmp`` clears this too.
DEFAULT_PATH = Path.home() / ".excmp" / "history.json"

#: Enough to be useful, small enough that the file stays trivial to read and
#: the oldest entries are the ones that go.
MAX_ENTRIES = 200


@dataclass
class HistoryEntry:
    """One finished job. Note what is absent: any secret at all."""

    archive: str
    inputs: list[str]
    profile: str
    chain: str
    orig_bytes: int
    final_bytes: int
    elapsed_s: float
    finished_at: str
    state: str = "done"
    error: str = ""
    #: Only the non-defaults, so "Compress again" reproduces the job rather
    #: than an approximation of it.
    archive_format: str = "excmp"
    recovery: int | None = None
    split: int | None = None
    #: True when the job was encrypted. The fact, never the password - so the
    #: UI can say "this one needed a password" and prompt for it again.
    encrypted: bool = False

    @property
    def saved_percent(self) -> float:
        if not self.orig_bytes:
            return 0.0
        return 100.0 * (1 - self.final_bytes / self.orig_bytes)


def _coerce(entry: object) -> HistoryEntry | None:
    """One entry from the file, or None. The file is user-editable, so nothing
    here trusts its shape."""
    if not isinstance(entry, dict):
        return None
    known = {f.name: f for f in fields(HistoryEntry)}
    required = [n for n, f in known.items()
                if f.default is field(default=None).default
                and f.default_factory is not list]  # type: ignore[misc]
    try:
        kwargs = {}
        for name, spec in known.items():
            if name not in entry:
                continue
            value = entry[name]
            if name == "inputs":
                if not isinstance(value, list):
                    return None
                kwargs[name] = [str(v) for v in value]
            elif name in ("orig_bytes", "final_bytes"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None
                kwargs[name] = int(value)
            elif name == "elapsed_s":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None
                kwargs[name] = float(value)
            elif name in ("recovery", "split"):
                kwargs[name] = int(value) if isinstance(value, (int, float)) else None
            elif name == "encrypted":
                kwargs[name] = bool(value)
            else:
                if not isinstance(value, str):
                    return None
                kwargs[name] = value
        return HistoryEntry(**kwargs)
    except TypeError:
        return None


def load(path: Path | None = None) -> list[HistoryEntry]:
    """Newest first. A missing or damaged file is simply empty history."""
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    out = []
    for item in (raw.get("entries") or [])[:MAX_ENTRIES]:
        parsed = _coerce(item)
        if parsed is not None:
            out.append(parsed)
    return out


def append(entry: HistoryEntry, path: Path | None = None) -> None:
    """Record one finished job. Never raises.

    This runs after a job has ended, and failing to write history is not a
    reason to turn a finished job into a failed one.
    """
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        entries = [entry] + load(target)
        payload = {"entries": [asdict(e) for e in entries[:MAX_ENTRIES]]}
        # D8: flushed and read back, and a failed write leaves the previous
        # record whole rather than truncated. This is the user's own log of
        # every job they have run - losing the lot to a bad moment while
        # appending one line to it is not an acceptable failure.
        atomic_write_text(target, json.dumps(payload, indent=2))
    except (OSError, ValueError, TypeError, PublishError):
        # PublishError is a RuntimeError and so is named explicitly - see the
        # same clause in excmp.calibrate. Losing one history line is fine;
        # turning a finished job into a failed one over it is not.
        return


def clear(path: Path | None = None) -> None:
    """Forget everything. Explicit, because history is the user's record."""
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        target.unlink(missing_ok=True)
    except OSError:
        return
