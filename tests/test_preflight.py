"""Free-disk preflight on the compression side (J4).

D0 shipped this for *extraction*, where it can be exact: the manifest declares
every file's size, so "this restores to 4.2 GB and you have 900 MB" is a fact.

Compression cannot be exact. The output size is an estimate and Precomp's
mid-pipeline inflation is data-dependent (2-5x, research/10 C-3). So there are
two thresholds, and the distinction is the point of these tests:

* below the **floor** the job is arithmetically impossible - refuse, before
  copying a single byte;
* below the **peak** it might still work - warn with the number and continue.

A preflight that refuses jobs that would have succeeded gets switched off, and
then it protects nobody.
"""

import shutil

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")

_REAL_DISK_USAGE = shutil.disk_usage


def _pretend_free(monkeypatch, free_bytes, only_under=None):
    """Report ``free_bytes`` for paths under ``only_under`` (or everywhere),
    and the truth elsewhere - tempfile and pytest still need honest numbers."""
    def fake(path):
        real = _REAL_DISK_USAGE(path)
        if only_under is None or str(path).lower().startswith(str(only_under).lower()):
            return shutil._ntuple_diskusage(real.total, real.total - free_bytes, free_bytes)
        return real
    monkeypatch.setattr(engine.shutil, "disk_usage", fake)


def _compressible_tree(root):
    root = root / "src"
    root.mkdir()
    # ~2 MB of highly compressible text, so the piped byte count is meaningful
    # while the test stays fast.
    for i in range(4):
        (root / f"doc{i}.txt").write_text("the quick brown fox. " * 25_000)
    return root


@needs_7z
def test_a_roomy_disk_adds_no_warning(tmp_path):
    src = _compressible_tree(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    result = engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)
    assert not any("free space" in w or "temp" in w.lower() for w in result.warnings)
    assert (tmp_path / "out.excmp").exists()


@needs_7z
def test_an_impossible_job_is_refused_before_any_work_happens(tmp_path, monkeypatch):
    src = _compressible_tree(tmp_path)
    out = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    _pretend_free(monkeypatch, 64 * 1024)   # 64 KB free: cannot hold anything

    with pytest.raises(RuntimeError) as excinfo:
        engine.compress([src], out, Profile.NORMAL, ctx)

    message = str(excinfo.value)
    assert "MiB" in message, "the refusal has to state the number"
    assert not out.exists()
    assert not out.with_suffix(".excmp.tmp").exists()
    # And the input is untouched - the non-negotiable rule.
    assert len(list(src.iterdir())) == 4


@needs_7z
def test_a_tight_but_possible_job_warns_and_still_runs(tmp_path, monkeypatch):
    """Enough room for the archive and the staging copy, not enough for the
    worst case Precomp could inflate to. That is a warning, not a refusal."""
    src = _compressible_tree(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    _pretend_free(monkeypatch, 6 * 1024 * 1024)   # 6 MB against a ~2 MB input

    result = engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)

    assert (tmp_path / "out.excmp").exists()
    assert any("free" in w.lower() for w in result.warnings), result.warnings


def test_the_needs_add_up_when_temp_and_output_share_a_volume(tmp_path):
    """Two directories on one disk compete for the same free bytes, so the
    check has to sum them rather than testing each in isolation."""
    from excmp.analyzer import analyze_tree
    from excmp.planner import plan as make_plan

    src = _compressible_tree(tmp_path)
    infos = analyze_tree(src)
    the_plan = make_plan(infos, Profile.NORMAL, find_tools())

    shared = engine.compress_space_needs(tmp_path / "out.excmp", tmp_path / "tmp",
                                         infos, the_plan)
    assert len(shared) == 1, "one volume, one requirement"
    (_probe, floor, peak), = shared
    assert 0 < floor <= peak


def test_a_store_only_job_needs_no_temp_headroom(tmp_path):
    """Nothing is piped, so nothing is staged or inflated - the only requirement
    is room for the archive itself."""
    from excmp.analyzer import analyze_tree
    from excmp.planner import plan as make_plan

    root = tmp_path / "media"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + bytes(range(256)) * 400)
    infos = analyze_tree(root)
    the_plan = make_plan(infos, Profile.NORMAL, find_tools())

    (_probe, floor, peak), = engine.compress_space_needs(
        tmp_path / "out.excmp", tmp_path / "tmp", infos, the_plan)
    assert floor == peak, "no pipeline means no inflation risk to warn about"
