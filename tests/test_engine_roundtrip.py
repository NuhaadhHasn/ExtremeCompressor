import random
import zipfile

import pytest

from excmp import engine
from excmp.manifest import ContainerError
from excmp.planner import Profile
from excmp.stages.base import StageContext, StageError
from excmp.tools import find_tools
from excmp.verify import VerifyError

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


def _mixed_tree(root):
    root.mkdir()
    (root / "readme.txt").write_text("compress me please. " * 20_000)  # ~400 KB text
    (root / "movie.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + random.randbytes(80_000))
    (root / "random.bin").write_bytes(random.randbytes(60_000))
    (root / "sub").mkdir()
    (root / "sub" / "notes.md").write_text("# notes\n" + "abc def ghi\n" * 5_000)
    return root


def _tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


@needs_7z
def test_normal_roundtrip_mixed(tmp_path):
    src = _mixed_tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    arc = tmp_path / "out.excmp"

    result = engine.compress([src], arc, Profile.NORMAL, ctx)
    assert arc.exists()
    assert result.orig_bytes > 0 and result.final_bytes < result.orig_bytes
    actions = {r["action"] for r in result.routes}
    assert actions == {"pipeline", "store"}  # media+random stored, text piped

    out = tmp_path / "restore"
    xr = engine.extract(arc, out, ctx)
    assert _tree_bytes(out / "data") == _tree_bytes(src)
    assert xr.verified == 4


def test_fast_roundtrip(tmp_path):
    src = _mixed_tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    arc = tmp_path / "out.excmp"
    engine.compress([src], arc, Profile.FAST, ctx)
    out = tmp_path / "restore"
    engine.extract(arc, out, ctx)
    assert _tree_bytes(out / "data") == _tree_bytes(src)


@needs_7z
def test_corruption_is_detected(tmp_path):
    src = _mixed_tree(tmp_path / "data")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    arc = tmp_path / "out.excmp"
    engine.compress([src], arc, Profile.NORMAL, ctx)

    data = bytearray(arc.read_bytes())
    for off in range(len(data) // 2, len(data) // 2 + 64):  # stomp 64 payload bytes
        data[off] ^= 0xFF
    bad = tmp_path / "bad.excmp"
    bad.write_bytes(bytes(data))

    with pytest.raises((VerifyError, StageError, ContainerError, zipfile.BadZipFile)):
        engine.extract(bad, tmp_path / "restore-bad", ctx)


@needs_7z
def test_input_files_untouched(tmp_path):
    src = _mixed_tree(tmp_path / "data")
    before = _tree_bytes(src)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "o.excmp", Profile.NORMAL, ctx)
    assert _tree_bytes(src) == before
