"""The Fast profile must actually be fast: zstd level 12, not 19.

Fast used to run zstd at its slowest useful setting (level 19 with long-distance matching), no faster than
Normal. A Fable research pass flagged it; measured end to end through the engine (compress plus the restore and
SHA-256 gate, quiet machine, best of two, 2026-11-25):

    corpus                      level 19      level 12      level 9
    office zip containers 120MB  14.1 s 5.19%   9.0 s 4.96%   8.4 s 4.81%
    installers 56 MB              7.7 s 12.49%  4.2 s 12.26%  4.6 s 12.18%
    python source 43 MB          64.7 s 74.17% 44.1 s 71.42% 42.0 s 70.77%

So 1.5-1.8x faster end to end (codec alone: 15-60x, but a job's time is mostly per-file work), for 0.2-2.8 points.
Levels 12 and 9 take the same time and 12 saves more, so Fast is level 12. An explicit Level in Advanced still wins.
"""

from __future__ import annotations

from excmp import engine
from excmp.engine import StageOptions
from excmp.stages.zstdstage import FAST_ZSTD_LEVEL, ZstdStage


def test_fast_is_zstd_level_12():
    assert FAST_ZSTD_LEVEL == 12


def test_the_fast_stage_uses_it_when_no_level_is_chosen():
    stage = engine._stage_factory(None)["zstd"]
    assert isinstance(stage, ZstdStage) and stage.level == FAST_ZSTD_LEVEL
    stage = engine._stage_factory(StageOptions())["zstd"]
    assert stage.level == FAST_ZSTD_LEVEL


def test_an_explicit_level_still_wins():
    assert engine._stage_factory(StageOptions(level=19))["zstd"].level == 19
    assert engine._stage_factory(StageOptions(level=3))["zstd"].level == 3


def test_the_bare_stage_default_is_unchanged_so_old_callers_and_archives_behave_as_before():
    assert ZstdStage().level == 19


def test_a_fast_archive_round_trips_at_the_new_level(tmp_path):
    from excmp.planner import Profile
    from excmp.stages.base import StageContext
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello world " * 20_000)
    (src / "b.bin").write_bytes(bytes((i * 31 + 7) % 256 for i in range(50_000)))
    out = tmp_path / "a.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    res = engine.extract_any(out, tmp_path / "back", StageContext(temp_dir=tmp_path / "t2"))
    assert res.verified == 2 and res.ledger_backed


def test_the_fast_estimate_is_no_longer_priced_at_level_19_speed():
    """3.5 MB/s was level 19. Level 12 measured 20-105 MB/s on the codec; the estimate must say 'much faster
    than Normal's 7-Zip', not 'the same'."""
    from excmp.estimate import _CODEC_RATE
    assert _CODEC_RATE["zstd"] >= 15e6
    assert _CODEC_RATE["zstd"] > 4 * _CODEC_RATE["sevenzip"]
