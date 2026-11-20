"""A string with an invalid escape sequence in it works today and is a SyntaxError in a future Python.
The suite only showed it as a warning in a summary nobody reads; this fails on it."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(p for folder in ("excmp", "gui", "packaging") for p in (ROOT / folder).rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_source_file_has_a_syntax_warning(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(path.read_bytes(), str(path), "exec")
