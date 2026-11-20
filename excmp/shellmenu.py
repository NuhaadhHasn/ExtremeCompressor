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

import os
import re
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
        if not _safe_launcher_part(part):
            raise ValueError(f"cannot register {part!r}: it must be a full path (a drive or UNC "
                             "path) with no quote, percent sign, control character or trailing "
                             "backslash")
    return " ".join(f'"{p}"' for p in prefix) + f' {action} "%1"'


_DRIVE_OR_UNC = re.compile(r"^(?:[A-Za-z]:\\|\\\\)")


def _safe_launcher_part(part) -> bool:
    """What the shell does to a command template: it substitutes ``%1``, ``%*``, ``%L`` and friends
    ANYWHERE in it (so a ``%`` in the program path rewrites the program), a backslash before the
    closing quote makes the quote literal, and a rooted path with no drive means a different thing
    to the shell than to Python 3.12's ``ntpath.isabs``."""
    return (isinstance(part, str) and bool(part) and _DRIVE_OR_UNC.match(part) is not None
            and '"' not in part and "%" not in part and not part.endswith("\\")
            and not any(ord(c) < 32 for c in part))


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


def _get_raw(hive, path: str, name: str = ""):
    """``(value, registry type)``, or ``None`` if the key or the value does not exist. A value of
    another type is NOT absent: a foreign ``.excmp`` default stored as REG_EXPAND_SZ is somebody's."""
    wr = _winreg()
    try:
        with wr.OpenKey(hive, path) as key:
            return wr.QueryValueEx(key, name)
    except FileNotFoundError:
        return None


def _get(hive, path: str, name: str = "") -> str | None:
    raw = _get_raw(hive, path, name)
    return raw[0] if raw is not None and raw[1] == _winreg().REG_SZ else None


def _prune(hive, path: str, value_names=()) -> bool:
    """Delete the named values from ``path``, then the key itself if nothing else is left in it.
    Returns True if the key was deleted. What somebody else added to a key of ours stays."""
    wr = _winreg()
    try:
        with wr.OpenKey(hive, path, 0, wr.KEY_ALL_ACCESS) as key:
            for name in value_names:
                try:
                    wr.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            n_subkeys, n_values, _ = wr.QueryInfoKey(key)
    except FileNotFoundError:
        return False
    if n_subkeys == 0 and n_values == 0:
        wr.DeleteKey(hive, path)
        return True
    return False


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
        current = _get_raw(hive, rf"{root}\{EXTENSION}")
        # Free if there is no default value at all, or it is already ours (a REG_SZ). A default
        # of ANY other type is somebody else's association and is left alone.
        if current is None or current == (PROGID, wr.REG_SZ) or current == ("", wr.REG_SZ):
            _set(hive, rf"{root}\{EXTENSION}", (("", PROGID),))
            written.append(EXTENSION)
    return written


def uninstall(*, root: str = CLASSES_ROOT) -> list[str]:
    """Remove what :func:`install` wrote, and only that. Returns what was removed.

    Value by value and key by key, deepest first: every value :func:`install` set is deleted, and
    a key goes only when nothing else is left in it. A subkey or value that a user or another tool
    added under one of our keys survives, and so does the key that holds it."""
    wr = _winreg()
    hive = wr.HKEY_CURRENT_USER
    removed: list[str] = []
    entries = _entries([r"C:\x\ec.exe"])                  # the shape is all that matters here
    parts: list[tuple[str, tuple[str, ...]]] = []
    for e in entries:
        names = tuple(n for n, _ in e.values)
        parts.append((e.key, names))
        if e.action:
            parts.append((rf"{e.key}\command", ("",)))
    for key, names in sorted(parts, key=lambda kv: kv[0].count("\\"), reverse=True):
        if _prune(hive, rf"{root}\{key}", names):
            removed.append(key)
    _prune_empty_parents(hive, root, [k for k, _ in parts])
    path = rf"{root}\{EXTENSION}"
    if _get_raw(hive, path) == (PROGID, wr.REG_SZ):
        with wr.OpenKey(hive, path, 0, wr.KEY_ALL_ACCESS) as key:
            wr.DeleteValue(key, "")
        removed.append(EXTENSION)
        _prune(hive, path)                                # the key too, unless it holds something else
    return removed


def _prune_empty_parents(hive, root: str, keys) -> None:
    """``install`` creates the keys between the root and its own (``*\\shell``, ``Directory``): take
    them away again when nothing else lives there, so a clean machine ends up exactly as it began."""
    parents: set[str] = set()
    for key in keys:
        parts = key.split("\\")
        for i in range(1, len(parts)):
            parents.add("\\".join(parts[:i]))
    for parent in sorted(parents, key=lambda p: p.count("\\"), reverse=True):
        _prune(hive, rf"{root}\{parent}")


@dataclass(frozen=True)
class Status:
    installed: bool                 # every verb is there
    stale: bool                     # ...but at least one runs a different program
    missing: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)


def status(prefix: Sequence[str] | None = None, *, root: str = CLASSES_ROOT) -> Status:
    """Which entries exist, and whether the verbs run the program ``prefix`` names. Every key
    :func:`install` writes counts (a menu with its icon key deleted is half installed), and a
    verb that points elsewhere is reported stale even when something else is also missing."""
    hive = _winreg().HKEY_CURRENT_USER
    prefix = list(prefix) if prefix is not None else default_launcher()
    missing, found, stale = [], [], False
    for e in _entries(prefix):
        if e.action:
            have = _get(hive, rf"{root}\{e.key}\command")
        else:
            have = e.key if _key_exists(hive, rf"{root}\{e.key}") else None
        if have is None:
            missing.append(e.key)
            continue
        found.append(e.key)
        if e.action and have != command_line(e.action, prefix):
            stale = True
    return Status(installed=not missing, stale=stale, missing=missing, found=found)


def _key_exists(hive, path: str) -> bool:
    try:
        _winreg().CloseKey(_winreg().OpenKey(hive, path))
        return True
    except FileNotFoundError:
        return False
