from pathlib import Path

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS_ALL = {
    "7z": ToolInfo("7z", r"C:\Program Files\7-Zip\7z.exe"),
    "precomp": ToolInfo("precomp", r"C:\x\precomp.exe"),
    "srep": ToolInfo("srep", r"C:\x\srep64.exe"),
    "zpaqfranz": None, "zstd": None, "ffmpeg": None, "ffprobe": None,
}
TOOLS_MINIMAL = {**TOOLS_ALL, "precomp": None, "srep": None}


def fi(name, cat, size=1000, entropy=4.0):
    return FileInfo(path=Path(name), size=size, category=cat, entropy_bps=entropy)


def test_video_routes_to_store():
    p = plan([fi("m.mp4", Category.VIDEO, entropy=7.99)], Profile.NORMAL, TOOLS_ALL)
    (route,) = p.routes
    assert route.action == "store"
    assert "quality" in route.reason.lower()


def test_text_routes_to_pipeline_normal():
    p = plan([fi("a.txt", Category.TEXT)], Profile.NORMAL, TOOLS_ALL)
    (route,) = p.routes
    assert route.action == "pipeline"
    assert route.stages == ["sevenzip"]


def test_fast_uses_zstd():
    p = plan([fi("a.txt", Category.TEXT)], Profile.FAST, TOOLS_ALL)
    assert p.routes[0].stages == ["zstd"]


def test_extreme_full_chain_with_tools():
    """B11: SREP is out of every compression chain. It failed a real restore on
    1 of 3 runs over byte-identical input (see benchmarks/2026-08-01-estimator-
    backtest.md), and it was already slated for removal as non-OSI. Old archives
    that recorded an srep stage still extract - the stage stays registered."""
    p = plan([fi("data.pak", Category.BINARY)], Profile.EXTREME, TOOLS_ALL)
    assert p.routes[0].stages == ["precomp", "sevenzip"]


def test_insane_runs_the_same_chain_until_zpaqfranz_lands():
    p = plan([fi("data.pak", Category.BINARY)], Profile.INSANE, TOOLS_ALL)
    assert p.routes[0].stages == ["precomp", "sevenzip"]


def test_no_profile_ever_plans_an_srep_stage():
    for profile in Profile:
        p = plan([fi("data.pak", Category.BINARY)], profile, TOOLS_ALL)
        for route in p.routes:
            assert "srep" not in route.stages, profile


def test_extreme_degrades_without_precomp():
    p = plan([fi("data.pak", Category.BINARY)], Profile.EXTREME, TOOLS_MINIMAL)
    assert p.routes[0].stages == ["sevenzip"]
    assert any("precomp" in w for w in p.warnings)
    # And it must not nag about a tool that is no longer part of any chain.
    assert not any("srep" in w for w in p.warnings)


def test_high_entropy_archive_stored():
    p = plan([fi("x.rar", Category.COMPRESSED_ARCHIVE, entropy=7.98)], Profile.NORMAL, TOOLS_ALL)
    assert p.routes[0].action == "store"


def test_zip_archive_goes_to_pipeline_when_precomp_available():
    # zip/gzip streams can be expanded by precomp, so under EXTREME they are
    # pipeline-routed despite high entropy
    p = plan([fi("x.zip", Category.COMPRESSED_ARCHIVE, entropy=7.98)], Profile.EXTREME, TOOLS_ALL)
    assert p.routes[0].action == "pipeline"


def test_mixed_inputs_grouped_into_two_routes():
    infos = [fi("a.txt", Category.TEXT), fi("m.mkv", Category.VIDEO, entropy=7.9)]
    p = plan(infos, Profile.NORMAL, TOOLS_ALL)
    actions = sorted(r.action for r in p.routes)
    assert actions == ["pipeline", "store"]
