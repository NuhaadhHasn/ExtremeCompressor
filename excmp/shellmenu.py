"""I5: the Explorer right-click menu, Windows 10 path - per-user registry verbs, no admin.

Writes under ``HKEY_CURRENT_USER\\Software\\Classes``:

* ``*\\shell\\ExtremeCompressor.Compress`` and ``Directory\\shell\\...``: "Compress with
  ExtremeCompressor" on every file and folder;
* the ``ExtremeCompressor.Archive`` ProgID and ``.excmp`` pointing at it: double-click extracts,
  and the menu offers "Extract here" and "Verify archive".

Each verb is a **thin launcher** (the NanaZip shape, docs/research/14): it runs
``<program> <action> "%1"`` and nothing else. No shell extension DLL is loaded into Explorer, so
nothing here can crash it. The Windows 11 top-level menu needs a signed sparse MSIX and is out of
scope until code signing (E4); the verbs still appear under "Show more options" there.

**What this module will not do.** It writes only the keys named below, it removes only those, and it
leaves a ``.excmp`` association alone if some other program already owns it. ``root`` is a
parameter so the tests can write under a throwaway key: a test must never edit the real shell.
"""

from __future__ import annotations

import ntpath
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .intake import ACTIONS

CLASSES_ROOT = r"Software\Classes"
VERB = "ExtremeCompressor.Compress"
PROGID = "ExtremeCompressor.Archive"
EXTENSION = ".excmp"
COMPRESS_LABEL = "Compress with ExtremeCompressor"

#: (key relative to the root, values, action whose command goes in ``<key>\\command``)
#: ``None`` for the action means the key carries values only.
_COMPRESS_KEYS = (r"*\shell\ExtremeCompressor.Compress",
                  r"Directory\shell\ExtremeCompressor.Compress")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_launcher() -> list[str]:
    """The program the verbs start: the frozen exe, or this interpreter running ``run_gui.py``.

    A source checkout cannot use ``python -m gui``: Explorer starts the verb in the selected
    file's folder, where ``gui`` is not importable.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw if pythonw.is_file() else exe), str(repo_root() / "run_gui.py")]


def command_line(action: str, prefix: Sequence[str]) -> str:
    """``"<prefix...>" <action> "%1"``, refusing anything that cannot be quoted safely."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if not prefix:
        raise ValueError("no program to run")
    for part in prefix:
        if (not isinstance(part, str) or not part or '"' in part or "\x00" in part
                or not ntpath.isabs(part)):
            raise ValueError(f"cannot register {part!r}: it must be an absolute path without quotes")
    return " ".join(f'"{p}"' for p in prefix) + f' {action} "%1"'


@dataclass(frozen=True)
class _Entry:
    key: str                       # relative to the root
    values: tuple[tuple[str, str], ...] = ()
    action: str | None = None      # the command under ``<key>\command``


def _entries(prefix: Sequence[str]) -> list[_Entry]:
    exe = prefix[0]
    icon = f'"{exe}",0'
    out = [_Entry(k, (("MUIVerb", COMPRESS_LABEL), ("Icon", icon)), "compress")
           for k in _COMPRESS_KEYS]
    out += [
        _Entry(PROGID, (("", "ExtremeCompressor archive"),)),
        _Entry(rf"{PROGID}\DefaultIcon", (("", icon),)),
        _Entry(rf"{PROGID}\shell", (("", "open"),)),
        _Entry(rf"{PROGID}\shell\open", (("MUIVerb", "Extract with ExtremeCompressor"),
                                         ("Icon", icon)), "extract"),
        _Entry(rf"{PROGID}\shell\ExtractHere", (("MUIVerb", "Extract here"), ("Icon", icon)),
               "extract-here"),
        _Entry(rf"{PROGID}\shell\Verify", (("MUIVerb", "Verify archive"), ("Icon", icon)),
               "verify"),
    ]
    return out


# -- registry plumbing (winreg is imported lazily: this module loads anywhere) ----------------

def _winreg():
    import winreg
    return winreg


def _delete_tree(hive, path: str) -> bool:
    """Delete ``path`` and everything under it. False if it was not there."""
    wr = _winreg()
    try:
        key = wr.OpenKey(hive, path, 0, wr.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return False
    with key:
        while True:
            try:
                sub = wr.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(hive, rf"{path}\{sub}")
    wr.DeleteKey(hive, path)
    return True


def _set(hive, path: str, values) -> None:
    wr = _winreg()
    with wr.CreateKeyEx(hive, path, 0, wr.KEY_WRITE) as key:
        for name, value in values:
            wr.SetValueEx(key, name, 0, wr.REG_SZ, value)


def _get(hive, path: str, name: str = "") -> str | None:
    wr = _winreg()
    try:
        with wr.OpenKey(hive, path) as key:
            value, kind = wr.QueryValueEx(key, name)
            return value if kind == wr.REG_SZ else None
    except FileNotFoundError:
        return None


def install(prefix: Sequence[str] | None = None, *, root: str = CLASSES_ROOT,
            associate: bool = True, check_exists: bool = True) -> list[str]:
    """Write the verbs. Returns the keys written. Idempotent.

    ``check_exists`` refuses a launcher that is not on disk: a menu entry that opens nothing is
    worse than none. (The tests turn it off to register imaginary paths under a throwaway root.)
    """
    wr = _winreg()
    prefix = list(prefix) if prefix is not None else default_launcher()
    command_line("compress", prefix)                      # validates the prefix before any write
    if check_exists:
        for part in prefix:
            if not os.path.isfile(part):
                raise FileNotFoundError(part)
    hive = wr.HKEY_CURRENT_USER
    written: list[str] = []
    for entry in _entries(prefix):
        path = rf"{root}\{entry.key}"
        _set(hive, path, entry.values)
        written.append(entry.key)
        if entry.action:
            _set(hive, rf"{path}\command", (("", command_line(entry.action, prefix)),))
            written.append(rf"{entry.key}\command")
    if associate:
        current = _get(hive, rf"{root}\{EXTENSION}")
        if current in (None, "", PROGID):
            _set(hive, rf"{root}\{EXTENSION}", (("", PROGID),))
            written.append(EXTENSION)
    return written


def uninstall(*, root: str = CLASSES_ROOT) -> list[str]:
    """Remove what :func:`install` wrote, and only that. Returns what was removed."""
    wr = _winreg()
    hive = wr.HKEY_CURRENT_USER
    removed: list[str] = []
    for key in (*_COMPRESS_KEYS, PROGID):
        if _delete_tree(hive, rf"{root}\{key}"):
            removed.append(key)
    path = rf"{root}\{EXTENSION}"
    if _get(hive, path) == PROGID:
        try:
            with wr.OpenKey(hive, path, 0, wr.KEY_WRITE) as key:
                wr.DeleteValue(key, "")
            removed.append(EXTENSION)
            # Leave the key only if somebody else put something in it.
            with wr.OpenKey(hive, path) as key:
                empty = wr.QueryInfoKey(key)[:2] == (0, 0)
            if empty:
                wr.DeleteKey(hive, path)
        except OSError:
            pass
    return removed


@dataclass(frozen=True)
class Status:
    installed: bool                 # every verb is there
    stale: bool                     # ...but at least one runs a different program
    missing: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)


def status(prefix: Sequence[str] | None = None, *, root: str = CLASSES_ROOT) -> Status:
    """Which verbs exist, and whether they run the program ``prefix`` names."""
    hive = _winreg().HKEY_CURRENT_USER
    prefix = list(prefix) if prefix is not None else default_launcher()
    expected = {e.key: command_line(e.action, prefix) for e in _entries(prefix) if e.action}
    missing, found, stale = [], [], False
    for key, cmd in expected.items():
        have = _get(hive, rf"{root}\{key}\command")
        if have is None:
            missing.append(key)
            continue
        found.append(key)
        if have != cmd:
            stale = True
    return Status(installed=not missing, stale=stale and not missing, missing=missing, found=found)
