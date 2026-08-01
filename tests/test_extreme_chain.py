import random
import zlib

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

_tools = find_tools()
needs_chain = pytest.mark.skipif(
    any(_tools[t] is None for t in ("7z", "precomp")),
    reason="7z+precomp required for extreme chain",
)


def _gamey_tree(root):
    """Data shaped like game assets: zlib streams + duplicated blocks."""
    root.mkdir()
    rng = random.Random(42)
    base = bytes(rng.randrange(256) for _ in range(64_000))
    # zlib-wrapped payloads (what precomp expands). The duplicate block now
    # falls to LZMA2's dictionary instead of SREP - at this size it dedupes
    # just as well, which is part of why dropping SREP was affordable.
    (root / "assets1.dat").write_bytes(zlib.compress(base * 3, level=9))
    (root / "assets2.dat").write_bytes(zlib.compress(base * 3, level=9))
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

    # precomp opened the zlib streams Normal had to store: extreme must win
    assert extreme.final_bytes < normal.final_bytes


@needs_chain
def test_extreme_manifest_records_chain(tmp_path):
    from excmp.manifest import read_container
    src = _gamey_tree(tmp_path / "game")
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], tmp_path / "e.excmp", Profile.EXTREME, ctx)
    manifest, _ = read_container(tmp_path / "e.excmp", tmp_path / "peek")
    assert [s.stage for s in manifest.stages] == ["tar", "precomp", "sevenzip"]


@needs_chain
def test_an_old_archive_with_an_srep_stage_still_extracts(tmp_path, monkeypatch):
    """B11 removes SREP from what we *create*, never from what we can *read*.
    A user's archive from before the change records an srep stage in its
    manifest, and refusing it would strand their data.

    The fixture is built by putting the OLD chain back into the planner's table
    and running the real engine - the exact bytes a pre-B11 build would have
    produced, not a hand-rolled approximation."""
    if _tools["srep"] is None:
        pytest.skip("srep not installed - cannot build the legacy fixture")

    from excmp import planner
    from excmp.manifest import read_container

    src = _gamey_tree(tmp_path / "game")
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    monkeypatch.setitem(
        planner._CHAINS, "extreme",
        [("precomp", "precomp"), ("srep", "srep"), ("sevenzip", "7z")])
    engine.compress([src], tmp_path / "legacy.excmp", Profile.EXTREME, ctx)
    monkeypatch.undo()

    manifest, _ = read_container(tmp_path / "legacy.excmp", tmp_path / "peek")
    assert "srep" in [s.stage for s in manifest.stages], "fixture must be legacy-shaped"

    result = engine.extract(tmp_path / "legacy.excmp", tmp_path / "restore", ctx)
    assert result.verified == len(manifest.inputs)
    assert _tree_bytes(tmp_path / "restore" / "game") == _tree_bytes(src)
