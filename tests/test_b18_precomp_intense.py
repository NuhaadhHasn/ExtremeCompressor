"""B18(b): `precomp -intense`, measured both ways, and kept on
(2026-10-15/16, i5-7200U, docs/benchmarks/2026-10-15-b18-settings.md).

On both B12 corpora, through both final codecs that follow Precomp, every
archive restored and SHA-256 compared (the .pcf through `precomp -r` too),
turning `-intense` OFF saved bytes:

    installers   .pcf        62,482,862 -> 59,895,108   -4.14%
                 Extreme 7z  46,048,132 -> 45,686,925   -0.78%
                 Insane -m58 45,915,379 -> 45,523,860   -0.85%
    deflate      Extreme 7z  51,827,160 -> 51,745,074   -0.16%
                 Insane -m58 42,852,397 -> 42,816,077   -0.08%

(The deflate -m58 figure with -intense is B17's: the regenerated .pcf hashed
identical to the one B17 compressed, so it was not compressed again.)

But `-intense` is what finds raw zlib streams, data with no container
around it, the shape of game paks. Without it Precomp finds nothing in such
data: a synthetic raw-zlib asset came out 16.8% bigger through Extreme
(241,589 B against 201,094), and `test_extreme_chain` caught Extreme
silently degrading to Normal's chain. A sub-1% win against a whole-stream
loss on data nobody has measured: it stays on, and B6's game data settles it.
"""

from __future__ import annotations

from pathlib import Path

from excmp.stages import precomp as precomp_mod
from excmp.stages.base import StageContext
from excmp.stages.precomp import PrecompStage


def _cmd_for(stage: PrecompStage, tmp_path: Path, monkeypatch) -> list[str]:
    seen = []

    def fake_run_tool(cmd, ctx, stage_id, parse, cwd=None):
        seen.append(list(cmd))
        Path(next(a[2:] for a in cmd if a.startswith("-o"))).write_bytes(b"pcf")

    monkeypatch.setattr(precomp_mod, "run_tool", fake_run_tool)
    monkeypatch.setattr(PrecompStage, "_exe", lambda self: "precomp.exe")
    src = tmp_path / "in.bin"
    src.write_bytes(b"x")
    stage.compress(src, tmp_path / "out.pcf", StageContext(temp_dir=tmp_path / "t"))
    assert len(seen) == 1
    return seen[0]


def test_the_default_chain_keeps_intense(tmp_path, monkeypatch):
    assert PrecompStage().intense is True
    cmd = _cmd_for(PrecompStage(), tmp_path, monkeypatch)
    assert "-intense" in cmd
    assert cmd[1] == "-cn"   # the final codec does the compressing


def test_the_engine_builds_the_default_stage():
    from excmp.engine import _stage_factory
    stage = _stage_factory()["precomp"]
    assert isinstance(stage, PrecompStage) and stage.intense is True


def test_intense_can_still_be_turned_off(tmp_path, monkeypatch):
    """What B18 measured as 0.08-0.85% smaller on installers and deflate
    archives. Kept reachable for B6, which can decide per data type."""
    cmd = _cmd_for(PrecompStage(intense=False), tmp_path, monkeypatch)
    assert "-intense" not in cmd
