import pytest

from excmp.stages.base import StageContext, StageError
from excmp.stages.sevenzip import SevenZipStage
from excmp.tools import find_tools

pytestmark = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


def _make_tree(root):
    root.mkdir()
    (root / "a.txt").write_text("hello" * 5000)
    (root / "sub").mkdir()
    (root / "sub" / "b.bin").write_bytes(bytes(range(256)) * 100)


def test_sevenzip_roundtrip(tmp_path):
    src = tmp_path / "src"
    _make_tree(src)
    seen = []
    ctx = StageContext(temp_dir=tmp_path / "tmp", progress_cb=lambda s, p: seen.append(p))
    stage = SevenZipStage()

    arc = stage.compress(src, tmp_path / "out.7z", ctx)
    assert arc.exists() and arc.stat().st_size > 0
    assert arc.stat().st_size < 30000  # highly repetitive text must shrink

    out = tmp_path / "ext"
    stage.extract(arc, out, ctx)
    assert (out / "a.txt").read_text() == "hello" * 5000
    assert (out / "sub" / "b.bin").read_bytes() == bytes(range(256)) * 100
    assert all(0 <= p <= 100 for p in seen)


def test_sevenzip_single_file_roundtrip(tmp_path):
    f = tmp_path / "single.dat"
    f.write_bytes(b"ABCD" * 10_000)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = SevenZipStage()
    arc = stage.compress(f, tmp_path / "one.7z", ctx)
    out = tmp_path / "ext"
    stage.extract(arc, out, ctx)
    assert (out / "single.dat").read_bytes() == b"ABCD" * 10_000


def test_sevenzip_test_archive(tmp_path):
    src = tmp_path / "src"
    _make_tree(src)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = SevenZipStage()
    arc = stage.compress(src, tmp_path / "t.7z", ctx)
    stage.test(arc, ctx)  # must not raise
    corrupted = tmp_path / "c.7z"
    data = bytearray(arc.read_bytes())
    data[len(data) // 2] ^= 0xFF
    corrupted.write_bytes(bytes(data))
    with pytest.raises(StageError):
        stage.test(corrupted, ctx)
