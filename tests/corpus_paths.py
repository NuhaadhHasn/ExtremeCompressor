"""Where a test finds a real corpus: the original while it is complete, else a verified copy.

The owner deletes the originals file by file, so "the folder exists" is not enough: a Programs
folder with three of its six backtest files gone still exists and made six tests skip. A candidate
is taken only if it holds every file the test names; otherwise the first one is returned (the
caller's own skip or size gate then reports what is missing, as before).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def first_holding(candidates: Iterable[Path], names: Iterable[str]) -> Path:
    candidates = tuple(candidates)
    names = tuple(names)
    return next((c for c in candidates if all((c / n).is_file() for n in names)), candidates[0])
