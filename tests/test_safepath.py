"""The shared archive-path validator (D0.1).

The reject matrix below is the *union* of three shipped sanitizers, taken from
the source study: 7-Zip 26.02 ``ExtractingFilePath.cpp`` (research/19 section 7),
NanaZip (research/14 section 6) and PeaZip (research/17 section 5) -- plus the
bidi overrides, which 7-Zip deliberately leaves unsanitized in ordinary path
components (research/14 section 6 rule 10). Every row here is a name a hostile
``.excmp`` could carry.

The accept list matters just as much: a sanitizer that rejects legitimate
filenames would break real archives, and the near-miss rows (``CONSOLE.txt``,
``NULL.txt``, ``a..b``) are the ones a sloppy substring check gets wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.safepath import UnsafePathError, safe_relpath, resolve_within

# --- names that must be refused -----------------------------------------------

TRAVERSAL = [
    "..",
    "../../x",
    r"..\..\x",
    "a/../../b",
    r"stored\..\..\evil.bat",
    ".",
    "./x",
    "a/./b",
    "a/..",
]

ABSOLUTE = [
    "/abs/evil",
    "\\abs\\evil",
    "//server/share",
    r"\\server\share",
    r"\\?\C:\x",
    "/",
]

DRIVE = [
    r"C:\abs",
    "C:rel",
    "c:/x",
    "Z:",
]

ADS = [
    "a:b",
    "a::$DATA",
    "x:Zone.Identifier:$DATA",
    "x.txt:payload",
    "dir/file.txt:stream",
]

RESERVED = [
    "CON",
    "con",
    "NUL.txt",
    "NUL .txt",
    "COM1 .log",
    "COM7.txt",
    "LPT9",
    "LPT0",
    "aux",
    "PRN.dat",
    "sub/NUL.txt",          # every component is checked, not just the last
]

TRAILING = [
    "name.",
    "name ",
    "...",                  # all-dots: not a traversal component, but trailing dots
    "dir./file.txt",
    "dir /file.txt",
    "a/b ",
    "a/b.",
]

ILLEGAL_CHARS = [
    'a<b>c|d"e*f?g',
    "a*b",
    "a?b",
    "a<b",
    "a>b",
    "a|b",
    'a"b',
]

CONTROL_CHARS = [
    "a\x01b",
    "a\x1fb",
    "a\x7fb",
    "a\nb",
    "a\tb",
    "a\rb",
    "a\x00b",
]

BIDI = [
    "a\u202eb",              # RLO -- the row that beats 7-Zip
    "\u202egpj.exe",         # the classic right-to-left extension spoof
    "a\u202db",              # LRO
    "a\u202ab",
    "a\u2066b",
    "a\u2069b",
    "a\u200eb",
    "a\u200fb",
]

EMPTY_PARTS = [
    "",
    "   ",
    "a//b",
    "a/",
    "a/ /b",
]

TOO_LONG = [
    "x" * 256,
    "a/" + "y" * 300,
    "/".join(["dir"] * 2000),
]

UNSAFE = (TRAVERSAL + ABSOLUTE + DRIVE + ADS + RESERVED + TRAILING
          + ILLEGAL_CHARS + CONTROL_CHARS + BIDI + EMPTY_PARTS + TOO_LONG)


@pytest.mark.parametrize("name", UNSAFE)
def test_safe_relpath_refuses(name):
    with pytest.raises(UnsafePathError):
        safe_relpath(name)


# --- names that must keep working ---------------------------------------------

SAFE = [
    "a.txt",
    "a/b/c.txt",
    "deep/nested/path/to/file.bin",
    "file.name.with.dots.txt",
    "my file.txt",
    " leading-space.txt",       # leading is fine; only trailing breaks Windows
    "..hidden",                 # only an exact ".." component is traversal
    "a..b",
    "Zone.Identifier",          # a real filename; only "x:Zone.Identifier" is a trick
    "CONSOLE.txt",              # near-miss: stem is CONSOLE, not CON
    "NULL.txt",                 # near-miss: NULL, not NUL
    "COM.txt",                  # near-miss: no digit
    "COM10.txt",                # near-miss: only COM0-9 are reserved
    "文件.txt",
    "emoji\U0001f600.txt",
    "a.b/c.d",
    "x" * 255,                  # exactly at the component limit
]


@pytest.mark.parametrize("name", SAFE)
def test_safe_relpath_accepts(name):
    assert str(safe_relpath(name)) == name.replace("\\", "/")


def test_safe_relpath_returns_relative_posix_path():
    rel = safe_relpath("a/b/c.txt")
    assert rel.parts == ("a", "b", "c.txt")
    assert not rel.is_absolute()


# --- resolve_within: the canonicalize-compare-reject layer --------------------


def test_resolve_within_joins_safely(tmp_path):
    target = resolve_within(tmp_path, "a/b.txt")
    assert target == tmp_path / "a" / "b.txt"


def test_resolve_within_refuses_escape(tmp_path):
    for name in ("../../evil", r"C:\evil", "/evil"):
        with pytest.raises(UnsafePathError):
            resolve_within(tmp_path, name)


def test_resolve_within_refuses_the_base_itself(tmp_path):
    """A name that resolves to the destination directory is not a file target."""
    with pytest.raises(UnsafePathError):
        resolve_within(tmp_path, ".")


def test_resolve_within_survives_a_symlinked_base(tmp_path):
    """The comparison must canonicalize *both* sides.

    On Windows tmp_path often sits under an 8.3 short name, and a caller may
    hand us a symlinked temp dir. If only the target were resolved, every
    legitimate write would look like an escape.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation needs privileges on this machine")
    target = resolve_within(link, "a/b.txt")
    # returned unresolved, so the caller writes where it asked to
    assert target == link / "a" / "b.txt"
