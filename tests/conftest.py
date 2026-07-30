"""Shared pytest setup.

The GUI tests must never pop a real window - on a developer machine that
steals focus mid-run, and on CI there is no display at all. Setting the Qt
platform plugin here works because pytest imports ``conftest.py`` before any
test module, and therefore before PySide6 is first imported.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
