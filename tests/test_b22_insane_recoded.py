"""B22: Insane's time on media Precomp recodes, measured.

Insane (`precomp -cn -intense` then zpaqfranz -m58) was priced at one chain
rate for every piped byte (0.091 MB/s compress, 0.107 self-test) plus what the
recoder added beyond Precomp's generic chain. That was 2-3x too high on JPEG and
MP3 (zpaqfranz runs about 3x faster on packJPG/packMP3 output than on Silesia)
and 2.3-2.7x too LOW on PNG (Precomp expands ~50x into pixels and zpaqfranz
pays for every one).

Eight corpora through engine.compress (D9 included) and engine.extract, an
independent SHA-256 of every restored file (0 mismatches in 21 rows), three
rounds on the five small ones, two on the others, 2026-11-16/17
(docs/benchmarks/2026-11-16-b22-insane-recoded.md). The machine was not quiet:
a runaway `find` held ~24% of the CPU through round 1 and most of round 2, and
free memory fell to 0.5-0.6 GB in four rows. So the QUIET figure is each
corpus's least-contended row (the CPU share of everything else under ~15%, 4+ GB
free), and the others are the contended rows the range's high side must hold.

    corpus      bytes        quiet compress+D9    contended rows
    cmyk2        8,386,049     56.5 s (r3)         86.0, 94.4
    mp3-music   33,922,849    312.1 s (r3)         489.0, 1,118.2
    mp3-misc    80,307,437    871.8 s (r2)         1,641.5
    design     151,290,870    924.3 s (r2)         1,670.3
    gif-dl1      5,990,579     87.7 s (r3)         107.0, 180.1
    gif-dl      30,035,992    595.7 s (r2)         836.0
    png-dl       8,192,542    565.4 s (r3)         780.6, 1,621.5
    png-dl1      8,181,831    484.5 s (r3)         753.4, 2,096.1
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.estimate import (Rates, estimate_time, pack_cost, recode_cost,
                            recoded_seconds, time_split)
from excmp.planner import Profile, plan
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}
JPEG = Rates(ogg_pack=False, jpeg_pack=True)


@pytest.fixture(autouse=True)
def _balrogg_is_installed_in_the_plan(monkeypatch):
    from excmp import oggpack
    monkeypatch.setattr(oggpack, "available", lambda: True)


def _jpeg(name, size, refuses=False):
    return FileInfo(path=Path(name), size=size, category=Category.IMAGE,
                    entropy_bps=7.97, is_jpeg=True, lepton_refuses=refuses)


def _mp3(name, size):
    return FileInfo(path=Path(name), size=size, category=Category.AUDIO,
                    entropy_bps=7.99)


def _image(name, fmt, size):
    return FileInfo(path=Path(name), size=size, category=Category.IMAGE,
                    entropy_bps=7.95, sample_ratio=0.99, sample_ratio_max=0.99,
                    image_format=fmt)


def _even(make, prefix, suffix, total, n, **kw):
    return [make(f"{prefix}{i}{suffix}", total // n, **kw) for i in range(n)]


def _evenimg(fmt, total, n):
    return [_image(f"i{i}.{fmt}", fmt, total // n) for i in range(n)]


CORPORA = {
    "cmyk2": lambda: [_jpeg("c1.jpg", 12_112, True), _jpeg("c2.jpg", 8_373_937, True)],
    "mp3-music": lambda: _even(_mp3, "m", ".mp3", 33_922_849, 5),
    "mp3-misc": lambda: _even(_mp3, "m", ".mp3", 80_307_437, 16),
    "design": lambda: (_even(_jpeg, "d", ".jpg", 135_503_920, 14, refuses=True)
                       + _even(_jpeg, "p", ".jpg", 15_786_950, 24)),
    "gif-dl1": lambda: _evenimg("gif", 5_990_579, 24),
    "gif-dl": lambda: _evenimg("gif", 30_035_992, 64),
    "png-dl": lambda: _evenimg("png", 8_192_542, 70),
    "png-dl1": lambda: _evenimg("png", 8_181_831, 80),
}

#: (quiet seconds, contended seconds). Compress including D9, Insane.
MEASURED = {
    "cmyk2": (56.5, [86.0, 94.4]),
    "mp3-music": (312.1, [489.0, 1_118.2]),
    "mp3-misc": (836.2, [1_641.5, 871.8]),
    "design": (924.3, [1_670.3, 1_115.6]),
    "gif-dl1": (87.7, [107.0, 180.1]),
    "gif-dl": (454.0, [836.0, 595.7]),
    "png-dl": (565.4, [780.6, 1_621.5]),
    "png-dl1": (484.5, [753.4, 2_096.1]),
}


def _insane(corpus):
    infos = CORPORA[corpus]()
    return infos, estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), JPEG)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_a_quiet_insane_run_sits_in_the_range(corpus):
    _, t = _insane(corpus)
    quiet = MEASURED[corpus][0]
    assert t.low <= quiet <= t.high, (corpus, t.low, t.expected, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_expected_figure_is_close_to_a_quiet_insane_run(corpus):
    """Before: CMYK 3.2x high, MP3 1.9-2.3x, design 3.2x, PNG 2.3-2.7x LOW.
    One rate per kind, byte-weighted over two corpora each, so the corpora
    themselves differ from it by 13% or less. (GIF differed by up to 33% until
    B24: the 30 MB corpus's "quiet" row was contended; its third round, 454 s
    on a quiet machine, put both corpora within 5% of one rate.)"""
    _, t = _insane(corpus)
    quiet = MEASURED[corpus][0]
    assert quiet / 1.25 <= t.expected <= quiet * 1.25, (corpus, t.expected, quiet)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_range_holds_the_contended_insane_runs(corpus):
    """Contention only slows a job. The high side has to hold the slow rows:
    MP3 music went 3.6x its quiet time beside a runaway search and a memory
    squeeze, PNG up to 4.3x."""
    _, t = _insane(corpus)
    for measured in MEASURED[corpus][1]:
        assert measured <= t.high, (corpus, measured, t.high)


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_the_low_end_stays_informative(corpus):
    """Review (B19): a symmetric spread put a low end at a quarter of the
    fastest run. Contention only slows a job, so the quiet run is near the
    floor."""
    _, t = _insane(corpus)
    assert t.low >= MEASURED[corpus][0] / 2.5, (corpus, t.low)


def test_insane_prices_recoded_media_by_what_it_is_not_one_chain_rate():
    """The same bytes, five kinds: Insane is fastest on packJPG output and
    slowest on PNG, which Precomp expands ~50x. Quiet seconds per MB,
    compress plus self-test: JPEG 6.8, MP3 10.4, GIF 15.0, PNG 64."""
    per_mb = {}
    for kind, make in (("jpeg", lambda: _even(_jpeg, "c", ".jpg", 10_000_000, 4, refuses=True)),
                       ("mp3", lambda: _even(_mp3, "m", ".mp3", 10_000_000, 4)),
                       ("gif", lambda: _evenimg("gif", 10_000_000, 4)),
                       ("png", lambda: _evenimg("png", 10_000_000, 4))):
        infos = make()
        per_mb[kind] = estimate_time(infos, plan(infos, Profile.INSANE, TOOLS), JPEG).expected / 10
    assert per_mb["jpeg"] < per_mb["mp3"] < per_mb["gif"] < per_mb["png"], per_mb
    # Seconds per MB, 10 MB of each, with the job's fixed 2 s (0.2 s/MB) in.
    assert 5.5 <= per_mb["jpeg"] <= 8.5 and 50 <= per_mb["png"] <= 80, per_mb
    assert 9.5 <= per_mb["mp3"] <= 12.0 and 14.0 <= per_mb["gif"] <= 17.0, per_mb


def test_the_pre_b22_chain_rate_still_prices_everything_else_at_insane():
    """Text, and the B20 containers nobody measured at Insane, keep the chain's
    own rates (0.091 MB/s compress, 0.107 self-test)."""
    text = [FileInfo(path=Path(f"t{i}.txt"), size=5_000_000, category=Category.TEXT,
                     entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)
            for i in range(4)]
    stages = [s for r in plan(text, Profile.INSANE, TOOLS).routes
              if r.action == "pipeline" for s in r.stages]
    compress, verify = time_split(0, 20_000_000, stages)
    # Plus the 2 s every Insane job costs before it moves a byte (see below).
    assert compress - 2.0 == pytest.approx(20_000_000 / 0.091e6, rel=1e-3)
    assert verify == pytest.approx(20_000_000 / 0.107e6, rel=1e-3)


def test_the_recode_extras_go_negative_where_the_recoder_beats_the_chain():
    """The extras are relative to the chain's rate and so are signed here:
    packJPG output is 3x faster than Silesia under zpaqfranz. The progress
    bar's split and the calibration read them as `compress_seconds`, and
    `time_split` adds them to the chain's own time, so the sum is the
    measured time."""
    infos = _even(_jpeg, "c", ".jpg", 10_000_000, 4, refuses=True)
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    rc = recode_cost(infos, the_plan)
    stages = [s for r in the_plan.routes if r.action == "pipeline" for s in r.stages]
    compress, verify = time_split(0, 10_000_000, stages, recode=rc)
    assert rc.compress_seconds < 0 and rc.verify_seconds < 0
    assert 30 <= compress <= 42 and 28 <= verify <= 36, (compress, verify)


def test_the_recoded_seconds_are_the_whole_time_of_these_files_at_insane():
    """`recoded_seconds` answers "how long do these files take" for the
    suggestion text; at Insane that is the files' own measured time."""
    infos = _even(_jpeg, "c", ".jpg", 10_000_000, 4, refuses=True)
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    stages = [s for r in the_plan.routes if r.action == "pipeline" for s in r.stages]
    compress, verify = recoded_seconds(recode_cost(infos, the_plan), stages)
    assert compress == pytest.approx(10_000_000 / 0.277e6, rel=0.02)
    assert verify == pytest.approx(10_000_000 / 0.312e6, rel=0.02)


def test_extreme_is_untouched():
    """These are Insane's rates; Extreme's (precomp + 7-Zip) keep the
    B19/B21 ones."""
    infos = _even(_mp3, "m", ".mp3", 33_922_849, 5)
    t = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS), JPEG)
    assert 51.1 / 1.25 <= t.expected <= 126.8 * 1.25, t.expected


def test_a_pack_phase_is_not_double_counted_beside_the_recoded_files():
    """The design folder's 24 photos lepton takes are packed on the store
    route; only the 14 files lepton refuses are Precomp's at Insane."""
    infos = CORPORA["design"]()
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    assert pack_cost(infos, the_plan, JPEG).jpeg_bytes == 15_786_950 // 24 * 24
    assert recode_cost(infos, the_plan).bytes == 135_503_920 // 14 * 14


def _calibrated(monkeypatch, insane_rate, insane_verify):
    """What `blended_rates()` hands the progress bar after a few text jobs
    taught this machine a different Insane chain rate."""
    from excmp import calibrate
    from excmp.estimate import _CODEC_RATE, _VERIFY_RATE
    rates = Rates(codec={**_CODEC_RATE, "precomp+zpaqfranz": insane_rate},
                  verify={**_VERIFY_RATE, "precomp+zpaqfranz": insane_verify},
                  ogg_pack=False, jpeg_pack=True)
    monkeypatch.setattr(calibrate, "blended_rates", lambda: rates)
    return rates


@pytest.mark.parametrize("learned", [(0.050e6, 0.060e6), (0.091e6, 0.107e6),
                                     (0.160e6, 0.200e6)])
def test_the_bar_s_split_ignores_a_learned_insane_chain_rate_on_recoded_media(
        monkeypatch, learned):
    """The summary's extras are made with the default rates and the bar adds
    them to the *calibrated* chain's time (`queue_manager._time_split`). If
    the extras were relative to the chain's rate, a machine that had learned
    0.16 MB/s from text would show a CMYK job's bar with negative times
    (10 MB, compress: 10/0.16 + (10/0.277 - 10/0.091) = 62.5 + 36.1 - 109.9 =
    -11.3 s, against 67.7 s in the table)."""
    from gui.queue_manager import _time_split
    from gui.suggest import summarize
    infos = _even(_jpeg, "c", ".jpg", 10_000_000, 4, refuses=True)
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    summary = summarize(infos, the_plan, TOOLS)
    rates = _calibrated(monkeypatch, *learned)
    compress, verify = _time_split(summary)
    table = estimate_time(infos, the_plan, rates).expected
    assert compress + verify == pytest.approx(table, rel=0.01), (compress, verify, table)
    assert compress + verify == pytest.approx(
        10_000_000 / 0.277e6 + 10_000_000 / 0.312e6 + 2.0, rel=0.02)


# -- the fixed cost of a job ---------------------------------------------------

def _text(n, size):
    return [FileInfo(path=Path(f"t{i}.txt"), size=size, category=Category.TEXT,
                     entropy_bps=4.5, sample_ratio=0.3, sample_ratio_max=0.35)
            for i in range(n)]


#: Compress including D9, three runs each (2026-11-17; the first run after idle
#: is the slow one; the contention log covers only the first run, others 9%,
#: and the logger was reaped after it). A one-file 2 KB job and twenty 4 KB
#: files; the B21 6 MB GIF folder stored at Fast and Normal. Every file
#: restored, 0 mismatches in 30 runs.
FIXED = {
    ("tiny-1", Profile.FAST): (lambda: _text(1, 2048), [2.4, 0.5, 0.5]),
    ("tiny-1", Profile.NORMAL): (lambda: _text(1, 2048), [1.3, 0.7, 0.7]),
    ("tiny-1", Profile.EXTREME): (lambda: _text(1, 2048), [1.9, 0.8, 1.3]),
    ("tiny-1", Profile.INSANE): (lambda: _text(1, 2048), [5.2, 1.1, 3.8]),
    ("tiny-20", Profile.FAST): (lambda: _text(20, 4096), [1.6, 1.0, 0.8]),
    ("tiny-20", Profile.NORMAL): (lambda: _text(20, 4096), [1.0, 1.2, 1.0]),
    ("tiny-20", Profile.EXTREME): (lambda: _text(20, 4096), [1.1, 1.7, 1.2]),
    ("tiny-20", Profile.INSANE): (lambda: _text(20, 4096), [3.5, 2.7, 2.2]),
    ("gif-dl1 stored", Profile.FAST): (lambda: _evenimg("gif", 5_990_579, 24), [1.1, 1.0, 1.0]),
    ("gif-dl1 stored", Profile.NORMAL): (lambda: _evenimg("gif", 5_990_579, 24), [0.8, 0.8, 0.9]),
}


@pytest.mark.parametrize("key", sorted(FIXED, key=str))
def test_a_near_empty_job_has_a_cost_the_model_did_not(key):
    """The model said ~0 s for a 2 KB job and for a stored folder (0.12 s for
    the 6 MB of GIFs); the engine takes about a second to set up, write and
    prove an archive, and about two at Insane (zpaqfranz). The handoff's
    10-50 s did not reproduce: that was never a fixed cost."""
    make, runs = FIXED[key]
    infos = make()
    t = estimate_time(infos, plan(infos, key[1], TOOLS), JPEG)
    assert t.low <= min(runs) and max(runs) <= t.high, (key, t.low, t.expected, t.high, runs)
    # Between the fastest run's half and the slowest's 1.25x: the old model's
    # ~0 s (and ~1.7 s for twenty files at Insane) fell outside it everywhere
    # but there.
    assert min(runs) / 2 <= t.expected <= max(runs) * 1.25, (key, t.expected, runs)


def test_the_fixed_cost_does_not_scale_with_the_spread():
    """It is a setup cost, not throughput: a contended machine slows the
    codec, and the high side of the range must not multiply the second by
    the chain's 3.2x on top of its own margin."""
    infos = _text(1, 2048)
    t = estimate_time(infos, plan(infos, Profile.EXTREME, TOOLS), JPEG)
    # 1 s x the 3.0 high margin, plus a few hundredths for 2 KB: not x3.2 on
    # top (3.2 s plus the margin would be 9.6) and not the old ~0.2 s.
    assert 3.0 <= t.high <= 3.3, t
    assert 0.3 <= t.low <= 0.5, t


def test_the_bar_and_the_table_agree_about_the_fixed_cost():
    infos = _text(20, 4096)
    the_plan = plan(infos, Profile.INSANE, TOOLS)
    stages = [s for r in the_plan.routes if r.action == "pipeline" for s in r.stages]
    compress, verify = time_split(0, 20 * 4096, stages)
    t = estimate_time(infos, the_plan, JPEG)
    assert compress + verify == pytest.approx(t.expected, rel=0.01)
    assert compress >= 2.0, compress        # the setup cost is on the bar's side


@pytest.mark.parametrize("stages,fixed", [(["sevenzip"], 1.0),
                                          (["precomp", "zpaqfranz"], 2.0)])
def test_calibration_does_not_learn_the_setup_cost_as_codec_time(
        tmp_path, monkeypatch, stages, fixed):
    """The model now bills a job's setup second on its own (`time_split`), so
    `_calibrate` must not also fold it into the learned chain rate: an 8 MiB
    job at 7-Zip's speed takes ~2.5 s, and the second inside it taught a rate
    29% low, which `time_split` then charged the setup on top of (review)."""
    from types import SimpleNamespace

    from excmp.tools import find_tools

    from gui.models import Job
    from gui.queue_manager import CompressWorker, WorkerSignals

    recorded = []
    monkeypatch.setattr("excmp.calibrate.record",
                        lambda *a, **kw: recorded.append((a, kw)))
    worker = CompressWorker(Job(inputs=[tmp_path], out_path=tmp_path / "x.excmp",
                                profile=Profile.NORMAL),
                            WorkerSignals(), tmp_path / "t", find_tools())
    result = SimpleNamespace(piped_bytes=50_000_000, elapsed_s=30.0,
                             routes=[{"action": "pipeline", "stages": stages}])
    worker._calibrate(result)
    (_args, kwargs), = recorded
    assert kwargs["elapsed_s"] == pytest.approx(30.0 - fixed)
