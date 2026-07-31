"""``TarStage.extract`` must stay pinned to ``filter="data"`` (D0.4).

The tar path was already correct before D0 -- ``tarstage.py`` passes PEP 706's
``filter="data"``, which refuses traversal, absolute members and escaping
links. These tests exist so it can never be silently removed.

It takes *two* tests to actually pin it, and the reason is a moving target in
CPython: on 3.12 (our floor) ``TarFile.extraction_filter`` defaults to ``None``,
so dropping the argument would reopen the hole and the behavioural test below
would catch it. From 3.14 the default becomes ``data``, and that test would keep
passing with the argument gone -- at which point only the explicit assertion
still holds the line. Neither test alone survives both versions.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from excmp.stages.base import StageContext
from excmp.stages.tarstage import TarStage

CANARY = "CANARY.txt"


def _member(tar: tarfile.TarFile, name: str, *, data: bytes = b"x",
            kind: bytes = tarfile.REGTYPE, linkname: str = "") -> None:
    """Add a member with the name taken verbatim (TarInfo does not normalize)."""
    ti = tarfile.TarInfo(name)
    ti.type = kind
    ti.linkname = linkname
    ti.size = len(data) if kind == tarfile.REGTYPE else 0
    tar.addfile(ti, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def _hostile_tar(path: Path, name: str, *, kind: bytes = tarfile.REGTYPE,
                 linkname: str = "") -> Path:
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as tar:
        _member(tar, name, kind=kind, linkname=linkname)
    return path


HOSTILE = [
    pytest.param(f"../../{CANARY}", tarfile.REGTYPE, "", id="traversal"),
    pytest.param(f"../{CANARY}", tarfile.REGTYPE, "", id="traversal-shallow"),
    pytest.param(f"C:/{CANARY}", tarfile.REGTYPE, "", id="absolute-drive"),
    pytest.param(rf"C:\{CANARY}", tarfile.REGTYPE, "", id="absolute-drive-backslash"),
    pytest.param("link", tarfile.SYMTYPE, f"../../{CANARY}", id="symlink-escape"),
    pytest.param("link", tarfile.SYMTYPE, f"/{CANARY}", id="symlink-absolute"),
    pytest.param("link", tarfile.LNKTYPE, f"../../{CANARY}", id="hardlink-escape"),
]


@pytest.mark.parametrize("name,kind,linkname", HOSTILE)
def test_tar_extract_refuses_hostile_members(tmp_path, name, kind, linkname):
    src = _hostile_tar(tmp_path / "evil.tar", name, kind=kind, linkname=linkname)
    dst = tmp_path / "deep" / "out"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    with pytest.raises(tarfile.FilterError):
        TarStage().extract(src, dst, ctx)
    assert list(tmp_path.rglob(CANARY)) == [], "hostile tar member escaped"


def test_tar_extract_contains_leading_slash_members(tmp_path):
    """A leading-``/`` member is *contained*, not rejected -- and that is
    correct, not a gap.

    PEP 706's ``data`` filter strips the leading separator (tar's own
    convention for storing absolute paths) and only raises ``AbsolutePathError``
    if the name is still absolute afterwards, which on Windows means a drive
    letter. Pinning the containment is what matters; asserting a raise here
    would encode a misreading of the filter.
    """
    src = _hostile_tar(tmp_path / "abs.tar", f"/{CANARY}")
    dst = tmp_path / "deep" / "out"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    TarStage().extract(src, dst, ctx)
    assert (dst / CANARY).is_file()
    assert list(tmp_path.rglob(CANARY)) == [dst / CANARY]


def test_tarstage_passes_filter_data_explicitly(tmp_path, monkeypatch):
    """Assert on the argument itself, not just its effect -- see the module
    docstring for why the behavioural test above is not sufficient forever."""
    captured: dict[str, object] = {}
    real = tarfile.TarFile.extractall

    def spy(self, path=".", members=None, *, numeric_owner=False, filter=None):
        captured["filter"] = filter
        return real(self, path, members, numeric_owner=numeric_owner, filter=filter)

    monkeypatch.setattr(tarfile.TarFile, "extractall", spy)

    src = tmp_path / "ok.tar"
    with tarfile.open(src, "w", format=tarfile.PAX_FORMAT) as tar:
        _member(tar, "a.txt", data=b"hello")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    TarStage().extract(src, tmp_path / "out", ctx)

    assert captured["filter"] == "data", \
        'TarStage.extract must pass filter="data" explicitly (PEP 706)'


def test_tar_roundtrip_still_works(tmp_path):
    """Guard against a fix that breaks ordinary extraction."""
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "a.txt").write_bytes(b"aaa")
    (tree / "sub" / "b.txt").write_bytes(b"bbbb")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = TarStage()
    tarball = stage.compress(tree, tmp_path / "t.tar", ctx)
    out = stage.extract(tarball, tmp_path / "out", ctx)
    assert (out / "a.txt").read_bytes() == b"aaa"
    assert (out / "sub" / "b.txt").read_bytes() == b"bbbb"
