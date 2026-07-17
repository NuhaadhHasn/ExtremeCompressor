import random
import zlib

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

_tools = find_tools()
needs_chain = pytest.mark.skipif(
    any(_tools[t] is None for t in ("7z", "precomp", "srep")),
    reason="7z+precomp+srep required for extreme chain",
)


def _gamey_tree(root):
    """Data shaped like game assets: zlib streams + duplicated blocks."""
    root.mkdir()
    rng = random.Random(42)
    base = bytes(rng.randrange(256) for _ in range(64_000))
    # zlib-wrapped payloads (what precomp expands)
    (root / "assets1.dat").write_bytes(zlib.compress(base * 3, level=9))
    (root / "assets2.dat").write_bytes(zlib.compress(base * 3, level=9))  # dup for srep
    (root / "script.lua").write_text("function f()\n  return 42\nend\n" * 2_000)
    return root


def _tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


@needs_chain
def test_extreme_chain_roundtrip_and_beats_normal(tmp_path):
    src = _gamey_tree(tmp_path / "game")
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    normal = engine.compress([src], tmp_path / "n.excmp", Profile.NORMAL, ctx)
    extreme = engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, ctx)

    out = tmp_path / "restore"
    engine.extract(tmp_path / "e.excmp", out, ctx)
    assert _tree_bytes(out / "game") == _tree_bytes(src)

    # precomp opened the zlib streams, srep deduped them: extreme must win
    assert extreme.final_bytes < normal.final_bytes


@needs_chain
def test_extreme_manifest_records_chain(tmp_path):
    from excmp.manifest import read_container
    src = _gamey_tree(tmp_path / "game")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, ctx)
    manifest, _ = read_container(tmp_path / "e.excmp", tmp_path / "peek")
    assert [s.stage for s in manifest.stages] == ["tar", "precomp", "srep", "sevenzip"]
