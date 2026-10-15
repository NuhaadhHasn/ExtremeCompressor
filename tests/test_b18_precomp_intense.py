"""B18(b): Precomp runs without `-intense`, measured (2026-10-15, i5-7200U,
docs/benchmarks/2026-10-15-b18-settings.md).

`-intense` was in the chain from the start. On both B12 corpora, through
both final codecs that follow Precomp in the app, every archive restored and
SHA-256 compared (the .pcf through `precomp -r` too), it cost bytes:

    installers   .pcf        62,482,862 -> 59,895,108   -4.14%
                 Extreme 7z  46,048,132 -> 45,686,925   -0.78%
                 Insane -m58 45,915,379 -> 45,523,860   -0.85%
    deflate      Extreme 7z  51,827,160 -> 51,745,074   -0.16%
                 Insane -m58 42,852,397 -> 42,816,077   -0.08%

(The deflate -m58 figure with -intense is B17's: the regenerated .pcf hashed
identical to the one B17 compressed, so it was not compressed again.)

It was added for raw zlib streams in game paks, and no game data has been
measured (B6 is blocked on a sample), so the option stays and B6 reopens it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_the_default_chain_runs_without_intense(tmp_path, monkeypatch):
    assert PrecompStage().intense is False
    cmd = _cmd_for(PrecompStage(), tmp_path, monkeypatch)
    assert "-intense" not in cmd
    assert cmd[1] == "-cn"


def test_intense_is_still_available_for_game_data(tmp_path, monkeypatch):
    """Kept for B6: game paks are the case it was added for, and unmeasured."""
    cmd = _cmd_for(PrecompStage(intense=True), tmp_path, monkeypatch)
    assert "-intense" in cmd


def test_the_engine_builds_the_default_stage():
    from excmp.engine import _stage_factory
    stage = _stage_factory()["precomp"]
    assert isinstance(stage, PrecompStage) and stage.intense is False


@pytest.mark.parametrize("flag", ["-cn"])
def test_internal_compression_stays_off(tmp_path, monkeypatch, flag):
    """Unchanged by B18: the final codec does the compressing."""
    assert flag in _cmd_for(PrecompStage(), tmp_path, monkeypatch)
