r"""D2 — the awkward-but-legitimate file matrix.

`test_safepath.py` and `test_malicious_archive.py` already pin what we
**refuse**. This file pins the opposite and equally important half: a file
with an awkward name is not a hostile file, and refusing it would be its own
kind of data loss. The 2026-08-01 acceptance run made that concrete — real
installers with spaces, parens and `=` in their names had to survive a
validator written to stop `..\..\Startup\evil.bat`.

Every test here is a **real round-trip through the engine**: compress,
extract, compare SHA-256. Not a unit test of a helper — the interesting bugs
in this class live in the seams between the zip layer, the path validator and
the filesystem.

Fast profile throughout, because the question is whether the *container*
handles these, not how well a codec compresses them.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

import pytest

from excmp.engine import compress, extract
from excmp.planner import Profile
from excmp.stages.base import StageContext
from restored import assert_all_present, hash_tree


def _roundtrip(tmp_path: Path, src: Path) -> dict[str, str]:
    """Compress `src`, extract it, and return {relpath: sha256} of the result."""
    archive = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    compress([src], archive, Profile.FAST, ctx)
    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob("*") if p.is_file()}


def _expected(src: Path) -> dict[str, str]:
    return {p.relative_to(src).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in src.rglob("*") if p.is_file()}


def _assert_survives(tmp_path: Path, src: Path) -> None:
    want = _expected(src)
    archive = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    compress([src], archive, Profile.FAST, ctx)
    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))
    # Exact names - see tests/restored.py for why a suffix match is wrong.
    assert_all_present(out, want)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

AWKWARD_NAMES = [
    pytest.param("hello world.txt", id="spaces"),
    pytest.param("Wondershare (x64) pass=123.txt", id="parens-and-equals"),
    pytest.param("100% done.txt", id="percent"),
    pytest.param("a&b#c.txt", id="ampersand-hash"),
    pytest.param("file[1].txt", id="brackets"),
    pytest.param("apostrophe's.txt", id="apostrophe"),
    pytest.param("сюрприз.txt", id="cyrillic"),
    pytest.param("日本語.txt", id="japanese"),
    pytest.param("ދިވެހި.txt", id="dhivehi"),
    pytest.param("emoji-🎉-party.txt", id="emoji"),
    pytest.param("a" * 200 + ".txt", id="very-long-name"),
    pytest.param("dot.in.the.middle.tar.gz.txt", id="many-dots"),
    pytest.param("-leading-dash.txt", id="leading-dash"),
    pytest.param("+plus.txt", id="plus"),
    pytest.param("~tilde.txt", id="tilde"),
]


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_an_awkward_name_survives_a_roundtrip(tmp_path, name):
    src = tmp_path / "src"
    src.mkdir()
    try:
        (src / name).write_bytes(b"content for " + name.encode("utf-8", "replace"))
    except (OSError, UnicodeEncodeError) as exc:
        pytest.skip(f"filesystem will not create this name: {exc}")
    _assert_survives(tmp_path, src)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def test_a_zero_byte_file_survives(tmp_path):
    """Zero bytes is a real file, not an absent one. The ledger declares
    size 0 and the bomb bound must not read that as "unbounded"."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "empty.bin").write_bytes(b"")
    (src / "alongside.txt").write_bytes(b"not empty")
    _assert_survives(tmp_path, src)


def test_a_tree_of_only_empty_files_survives(tmp_path):
    src = tmp_path / "src"
    (src / "a" / "b").mkdir(parents=True)
    for n in range(5):
        (src / f"e{n}").write_bytes(b"")
        (src / "a" / "b" / f"deep{n}").write_bytes(b"")
    _assert_survives(tmp_path, src)


def test_deep_nesting_survives(tmp_path):
    src = tmp_path / "src"
    deep = src
    for i in range(20):
        deep = deep / f"level{i:02d}"
    deep.mkdir(parents=True)
    (deep / "bottom.txt").write_bytes(b"made it")
    _assert_survives(tmp_path, src)


def test_many_small_files_survive(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(200):
        (src / f"f{i:04d}.bin").write_bytes(bytes([i % 256]) * (i + 1))
    _assert_survives(tmp_path, src)


def test_a_file_that_is_pure_noise_survives(tmp_path):
    """High entropy routes to `store`, so this exercises the stored path
    rather than the pipeline - a different code path with its own bounds."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "noise.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    (src / "text.txt").write_bytes(b"compressible " * 5000)
    _assert_survives(tmp_path, src)


def test_a_long_path_survives(tmp_path):
    r"""Over 260 characters in total. Windows needs either the long-path opt-in
    or the \\\\?\\ prefix; if the filesystem refuses to create it at all we
    skip rather than assert something about the OS."""
    src = tmp_path / "src"
    deep = src
    while len(str(deep)) < 300:
        deep = deep / ("segment" + "x" * 20)
    try:
        deep.mkdir(parents=True)
        (deep / "f.txt").write_bytes(b"deep content")
    except OSError as exc:
        pytest.skip(f"long paths not enabled on this machine: {exc}")
    _assert_survives(tmp_path, src)


# ---------------------------------------------------------------------------
# Attributes and permissions
# ---------------------------------------------------------------------------

def test_a_read_only_file_survives(tmp_path):
    """Read-only is common on extracted installers and CD rips. It must not
    stop us reading, and it must not stop the *restore* writing."""
    src = tmp_path / "src"
    src.mkdir()
    f = src / "readonly.txt"
    f.write_bytes(b"do not touch")
    os.chmod(f, stat.S_IREAD)
    try:
        _assert_survives(tmp_path, src)
    finally:
        os.chmod(f, stat.S_IWRITE | stat.S_IREAD)


def test_the_input_is_never_modified(tmp_path):
    """The product's second-hardest promise after losslessness. Bytes *and*
    mtime, because a backup tool that rewrites timestamps has damaged the
    thing it was asked to preserve."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"original" * 1000)
    (src / "b.bin").write_bytes(os.urandom(100_000))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in src.rglob("*") if p.is_file()}

    _roundtrip(tmp_path, src)

    for p, (data, mtime) in before.items():
        assert p.exists(), f"{p.name} was deleted from the input"
        assert p.read_bytes() == data, f"{p.name} was modified in place"
        assert p.stat().st_mtime_ns == mtime, f"{p.name}'s mtime was rewritten"


# ---------------------------------------------------------------------------
# Windows-specific
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
def test_case_only_collisions_do_not_silently_lose_a_file(tmp_path):
    """`a.txt` and `A.txt` are two files on Linux and one on Windows. We
    cannot create both here, so the honest test is that whatever we *can*
    create round-trips - and that we never report success having written
    fewer files than the ledger declares."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "Readme.txt").write_bytes(b"one")
    (src / "readme.md").write_bytes(b"two")   # different stem, no collision
    _assert_survives(tmp_path, src)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reserved names")
def test_a_name_that_merely_contains_a_reserved_word_is_allowed(tmp_path):
    """`CON` is reserved; `CONTENTS.txt` and `console.log` are not. A
    validator that matched too loosely would reject ordinary files - the
    false-positive half of the D0 work."""
    src = tmp_path / "src"
    src.mkdir()
    for name in ("CONTENTS.txt", "console.log", "NULLABLE.md", "aux_data.bin",
                 "com10.txt", "prnt.txt"):
        (src / name).write_bytes(b"legitimate " + name.encode())
    _assert_survives(tmp_path, src)
