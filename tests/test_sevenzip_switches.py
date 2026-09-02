"""B7/B9 — the two 7-Zip switches, and when each is worth passing.

Both were in the roadmap as assertions rather than measurements. Measured on
this machine (7-Zip 26.02, mx9, 2 threads), across three deliberately
different corpora:

| corpus                     | `-mqs`   | `-mf=BCJ2` | both     |
|----------------------------|----------|------------|----------|
| 23.5 MB of DLLs/EXEs       | −0.026%  | **−1.296%**| −1.353%  |
| 163 MB of installers       |  0.000%  | +0.000%    | −0.002%  |
| 3.2 MB of source/docs      | **−0.130%** | +0.043% |  −0.088% |

Two conclusions, and one non-conclusion:

- **`-mqs` is free.** It never cost anything on any corpus and helped most on
  text. Sorting by type inside a solid block is off by default in 7-Zip
  (research/19 §5); we now always pass it.
- **`-mf=BCJ2` is conditional.** A real 1.3% on actual executable code, and a
  very slight *loss* (+0.04%) on text. So it is applied only when the piped
  set is executable-heavy, not unconditionally as the roadmap implied.
- **The roadmap's "5-10% on x86" figure is not supported.** Measured here it
  is **1.3%**. The item already flagged that number as benchmark-derived with
  no source-level basis; this is our own measurement replacing it.

Also measured and deliberately **not** adopted: `-md=192m` changed the output
by **zero bytes** on all three corpora while costing up to 27% more time. It
stays available as a user knob and stays out of the defaults.
"""

from __future__ import annotations

from pathlib import Path

from excmp.analyzer import Category, FileInfo
from excmp.engine import _stage_factory, _wants_bcj2
from excmp.stages.sevenzip import SevenZipStage

EXE = "C:/7z.exe"


def _info(name: str, size: int, category: Category) -> FileInfo:
    return FileInfo(path=Path(name), size=size, category=category,
                    entropy_bps=6.0)


# ---------------------------------------------------------------------------
# -mqs: always
# ---------------------------------------------------------------------------

def test_solid_sort_is_always_on():
    """Measured never-harmful and sometimes free money. 7-Zip leaves it off by
    default, so not passing it is a choice we were making by accident."""
    cmd = SevenZipStage().build_compress_cmd(Path("i"), Path("o.7z"), 2, EXE)
    assert "-mqs" in cmd


def test_solid_sort_survives_the_other_knobs():
    cmd = SevenZipStage(level=5, dict_size="64m",
                        extra_args=["-mhe=on"]).build_compress_cmd(
        Path("i"), Path("o.7z"), 2, EXE)
    assert "-mqs" in cmd


# ---------------------------------------------------------------------------
# -mf=BCJ2: only for executables
# ---------------------------------------------------------------------------

def test_bcj2_is_off_by_default():
    """Because on text it measured +0.043% — small, but the wrong direction,
    and most archives are not executables."""
    cmd = SevenZipStage().build_compress_cmd(Path("i"), Path("o.7z"), 2, EXE)
    assert not any("BCJ2" in a for a in cmd)


def test_bcj2_is_passed_when_asked_for():
    cmd = SevenZipStage(bcj2=True).build_compress_cmd(
        Path("i"), Path("o.7z"), 2, EXE)
    assert "-mf=BCJ2" in cmd


def test_an_executable_heavy_set_wants_bcj2():
    assert _wants_bcj2([_info("a.dll", 10_000_000, Category.EXECUTABLE),
                        _info("b.txt", 1_000_000, Category.TEXT)])


def test_a_text_heavy_set_does_not():
    assert not _wants_bcj2([_info("a.dll", 100_000, Category.EXECUTABLE),
                            _info("b.txt", 10_000_000, Category.TEXT)])


def test_nothing_at_all_does_not_crash_or_ask_for_bcj2():
    """An all-stored job pipes nothing. Dividing by that total is the obvious
    way to write this function and the obvious way to break it."""
    assert not _wants_bcj2([])


def test_a_pure_executable_set_wants_it():
    assert _wants_bcj2([_info("a.exe", 5_000_000, Category.EXECUTABLE)])


def test_the_threshold_is_on_bytes_not_file_count():
    """One huge DLL beside a hundred tiny text files is an executable job.
    Counting files would call it a text job and leave 1.3% behind."""
    files = [_info("big.dll", 50_000_000, Category.EXECUTABLE)]
    files += [_info(f"t{i}.txt", 1_000, Category.TEXT) for i in range(100)]
    assert _wants_bcj2(files)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_the_factory_can_build_a_bcj2_stage():
    reg = _stage_factory(None, bcj2=True)
    cmd = reg["sevenzip"].build_compress_cmd(Path("i"), Path("o.7z"), 2, EXE)
    assert "-mf=BCJ2" in cmd and "-mqs" in cmd


def test_the_factory_defaults_to_no_bcj2():
    reg = _stage_factory()
    cmd = reg["sevenzip"].build_compress_cmd(Path("i"), Path("o.7z"), 2, EXE)
    assert not any("BCJ2" in a for a in cmd)


def test_bcj2_does_not_displace_the_output_path():
    """The output path must stay where 7-Zip expects it however many switches
    precede it — the same property `build_compress_cmd` was split out to make
    checkable in the first place."""
    stage = SevenZipStage(bcj2=True, dict_size="192m", extra_args=["-mhe=on"])
    cmd = stage.build_compress_cmd(Path("in"), Path("out.7z"), 2, EXE)
    assert cmd[-2] == "out.7z"
    assert cmd[-1] == "in"


def test_the_big_dictionary_is_not_a_default():
    """Measured zero bytes of benefit on all three corpora and up to 27% more
    time. It stays a knob the user can reach, not something we impose."""
    cmd = SevenZipStage().build_compress_cmd(Path("i"), Path("o.7z"), 2, EXE)
    assert not any(a.startswith("-md=") for a in cmd)
