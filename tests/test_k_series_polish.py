"""The minor K-series audit findings, fixed rather than filed.

Each of these was reported by the adversarial audit of the K2-K5 diff, judged
minor, and recorded in the roadmap instead of being fixed. They are cheap
individually and they share a theme worth closing properly: **K2 added two new
things to the archive - empty directories and timestamps - and not every
consumer learned about them.**

A selective restore did not recreate directories. The preflight did not count
them. The refusal message blamed the wrong field for being too big. And a
directory whose only file was skipped disappeared from the restore entirely,
which is the one that actually loses user-visible structure.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.manifest import MANIFEST_NAME
from excmp.planner import Profile
from excmp.stages.base import StageContext


def _tree(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "a.txt").write_text("alpha\n" * 900, encoding="utf-8")
    (root / "b.txt").write_text("beta\n" * 900, encoding="utf-8")
    (root / "emptydir").mkdir()
    (root / "deep" / "empty" / "chain").mkdir(parents=True)
    return root


def _archive(tmp_path: Path) -> Path:
    arc = tmp_path / "out.excmp"
    engine.compress([_tree(tmp_path / "src")], arc, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    return arc


def test_a_selective_restore_also_recreates_empty_directories(tmp_path):
    """`extract` recreates them; `extract_selected` did not, so "extract
    everything" and "extract these files" produced different trees from the
    same archive.

    The asymmetry is the bug rather than the missing mkdir: a user who pulls
    one file out of an archive is not asking for a different directory layout
    than the one the archive records.
    """
    arc = _archive(tmp_path)
    out = tmp_path / "some"
    engine.extract_selected(arc, ["src/a.txt"], out,
                            StageContext(temp_dir=tmp_path / "t2"))

    assert (out / "src" / "a.txt").is_file()
    assert (out / "src" / "emptydir").is_dir(), \
        "a selective restore dropped the empty directories"
    assert (out / "src" / "deep" / "empty" / "chain").is_dir()


def test_the_manifest_preflight_counts_the_directory_list(tmp_path):
    """K1's whole lesson, applied to K2's new field.

    `manifest_size_estimate` is what stops a job whose manifest could not be
    read back, and `dirs` is a new **unbounded** top-level list: 20,000 empty
    directories are 20,000 relative paths the estimate never counted. Measured
    before this: 14,498 B predicted against 1,550,859 B written, a 100-fold
    under-read.
    """
    from excmp.manifest import Manifest, manifest_size_estimate

    rels = [f"project/mod{i}/empty" for i in range(4000)]
    inputs = {"a.txt": {"size": 1, "sha256": "a" * 64, "route": "pipeline"}}
    predicted = manifest_size_estimate(inputs.keys(), stored_count=0,
                                       dirs=rels)
    m = Manifest.new(profile="fast", stages=[], inputs=inputs,
                     payload_name="p.zst", dirs=rels)
    actual = len(m.to_json().encode("utf-8"))

    assert predicted >= actual, (
        f"the preflight under-reads the directory list: {predicted:,} < "
        f"{actual:,}")


def test_the_refusal_names_the_field_that_is_actually_too_big(tmp_path):
    """The message said "N file(s), whose names and hashes need about X MiB".
    With a huge `dirs` list and few files that is simply false, and it sends
    the user off to split a folder that is not the problem."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "one.txt").write_text("x" * 4000, encoding="utf-8")
    for i in range(300):
        (src / f"empty{i:04d}").mkdir()

    import excmp.manifest as m
    original = m.MAX_MANIFEST_BYTES
    m.MAX_MANIFEST_BYTES = 2048
    try:
        with pytest.raises(RuntimeError) as exc:
            engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL,
                            StageContext(temp_dir=tmp_path / "t"))
    finally:
        m.MAX_MANIFEST_BYTES = original

    message = str(exc.value)
    assert "director" in message.lower(), \
        f"the refusal blames files when the directories are the cause: {message}"


def test_a_directory_whose_only_file_is_skipped_still_comes_back(tmp_path):
    """The one with real user-visible consequences.

    K3 drops an unreadable file from the ledger. If that file was the *only*
    thing in its directory, the directory is now in neither list: not in the
    ledger (its file is gone) and not in `dirs` (it was not empty when the tree
    was walked). So the restore silently loses a folder that exists in the
    source - and the user is told about a skipped *file*, not a missing
    *folder*.
    """
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows share-mode locking")
    from tests.test_locked_files import DenyAll

    src = tmp_path / "src"
    (src / "lonely").mkdir(parents=True)
    (src / "keep.txt").write_text("readable\n" * 900, encoding="utf-8")
    only = src / "lonely" / "held.bin"
    only.write_bytes(bytes((i * 31) % 251 for i in range(40_000)))

    arc = tmp_path / "out.excmp"
    with DenyAll(only):
        result = engine.compress([src], arc, Profile.NORMAL,
                                 StageContext(temp_dir=tmp_path / "t"))
    assert result.skipped

    out = tmp_path / "restored"
    engine.extract(arc, out, StageContext(temp_dir=tmp_path / "t2"))
    assert (out / "src" / "lonely").is_dir(), \
        "the directory holding the skipped file vanished from the restore"


def test_the_empty_dir_walk_reuses_the_file_walk(tmp_path):
    """`iter_empty_dirs` did its own `rglob("*")`, which is a second full pass
    over a tree `iter_files` has just walked - and `iter_files` exists
    precisely because walking is the cheap pass worth doing once. On the
    57,020-file corpus that walk costs ~20 s of drive metadata latency, so
    doing it twice is a measurable cost for a list that is usually empty.
    """
    from excmp.analyzer import iter_empty_dirs, iter_files

    src = _tree(tmp_path / "src")
    files = iter_files(src)
    reused = iter_empty_dirs(src, files=files)
    fresh = iter_empty_dirs(src)
    assert sorted(reused) == sorted(fresh), "the reused walk disagrees"
    assert {p.name for p in fresh} == {"emptydir", "chain"}


# --------------------------------------------------------------------------
# the Peak RAM column, which was blank for Fast on a falsified rationale
# --------------------------------------------------------------------------

def test_the_zstd_ram_model_covers_both_measured_points():
    """`excmp/ram.py` modelled LZMA2 only, so the GUI's peak-RAM column was
    blank for Fast because "zstd's window is a tenth of it and never the thing
    that runs a 16 GB laptop out of memory". K4 measured **1,813 MiB** for that
    exact stage with the window pinned wide.

    Both measurements this model has to cover, taken on this machine:

        window_log 27, 96 MiB input   ->   163 MiB
        window_log 31, 1.8 GiB input -> 1,813 MiB

    It must never *under*-read - a "will this fit in RAM?" number that reads
    low is worse than no number - and the constants are deliberately above the
    clean `99 MiB + 0.5 x window` fit for that reason.
    """
    from excmp.ram import zstd_compress_ram

    assert zstd_compress_ram(27) >= 163 * (1 << 20)
    assert zstd_compress_ram(31) >= 1813 * (1 << 20)
    # ...but not absurdly high: a column nobody believes is a column nobody
    # reads. Twice the measurement is the outer limit.
    assert zstd_compress_ram(27) <= 2 * 163 * (1 << 20)
    assert zstd_compress_ram(31) <= 2 * 1813 * (1 << 20)


def test_the_ram_model_never_calls_the_api_that_crashes():
    """`estimated_compression_context_size()` would answer this exactly and
    kills the process with STATUS_INTEGER_DIVIDE_BY_ZERO (0xC0000094) inside
    libzstd for the parameter sets `ZstdStage` builds - a crash, not an
    exception, so nothing downstream can recover from it.

    Pinned as a test because it is the obvious "improvement" for somebody to
    reach for later, and the failure would be a hard crash in the GUI.
    """
    import ast
    import excmp.ram as ram

    tree = ast.parse(Path(ram.__file__).read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)}
    assert "estimated_compression_context_size" not in called, \
        "ram.py must not call estimated_compression_context_size - it crashes"
    # Naming it in a comment is fine, and in fact required: the reason it is
    # off limits has to travel with the decision. Parsing the AST rather than
    # grepping the text is what lets both be true at once.
    assert "estimated_compression_context_size" in \
        Path(ram.__file__).read_text(encoding="utf-8"), \
        "the reason this API is avoided must stay documented beside the model"


def test_fast_reports_a_peak_ram_figure_that_moves_with_the_input():
    """A blank cell in a *comparison* table implies Fast is free rather than
    unmeasured, which is the worse of the two errors this column can make.

    The figure tracks the input because `ZstdStage` fits its window to the
    data rather than pinning it, so a small job honestly reports a small
    number.
    """
    from excmp.planner import Profile
    from gui.suggest import _ram_words

    small = _ram_words(Profile.FAST, 2, 10 << 20)
    large = _ram_words(Profile.FAST, 2, 2000 << 20)
    assert small and large, "Fast must not report an empty peak-RAM cell"
    assert small != large, "the figure has to move with the input"
    assert "GB" in large, large
