"""A missing output folder is created, and an impossible one is explained.

Found by the user guide: compressing to a folder that does not exist failed with Python's raw
``[Errno 2] No such file or directory: '...\\a.excmp.tmp'`` (and the GUI showed that string).
"""

from __future__ import annotations

import hashlib

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None, reason="7z.exe not installed")


def _src(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello " * 2000)
    return src


@needs_7z
def test_compress_creates_a_missing_output_folder(tmp_path):
    out = tmp_path / "new" / "deeper" / "a.excmp"
    engine.compress([_src(tmp_path)], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    assert out.is_file() and not list(out.parent.glob("*.tmp"))


@needs_7z
def test_a_plain_7z_creates_it_too(tmp_path):
    out = tmp_path / "x" / "y" / "a.7z"
    engine.compress_standard([_src(tmp_path)], out, "7z", StageContext(temp_dir=tmp_path / "t"))
    assert out.is_file()


@needs_7z
def test_the_archive_still_round_trips(tmp_path):
    out = tmp_path / "n" / "a.excmp"
    engine.compress([_src(tmp_path)], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    res = engine.extract_any(out, tmp_path / "back", StageContext(temp_dir=tmp_path / "t2"))
    got = next((tmp_path / "back").rglob("a.txt"))
    assert hashlib.sha256(got.read_bytes()).hexdigest() == hashlib.sha256(("hello " * 2000).encode()).hexdigest()
    assert res.verified == 1


@needs_7z
def test_an_output_folder_that_cannot_exist_is_explained_not_a_raw_errno(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("i am a file, not a folder")
    with pytest.raises(OSError) as exc:
        engine.compress([_src(tmp_path)], blocker / "sub" / "a.excmp", Profile.FAST,
                        StageContext(temp_dir=tmp_path / "t"))
    message = str(exc.value)
    assert "output folder" in message and str(blocker) in message
    assert "Errno" not in message


def test_nothing_is_created_when_there_is_nothing_to_compress(tmp_path):
    out = tmp_path / "should-not-appear" / "a.excmp"
    with pytest.raises(ValueError):
        engine.compress([tmp_path / "does-not-exist"], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    assert not (tmp_path / "should-not-appear").exists()
