"""G7 + B9: make extraction memory predictable, then bound it.

**What the measurement found** (2026-09-11, Silesia 211,938,580 B, `-md=64m`,
2-core i7-3540M; harness `tools/ram_backtest.py`, peak read from
`GetProcessMemoryInfo` on the exited child):

| extract flags | peak working set |
|---|---|
| none - what shipped | **255 MiB** |
| `-mmt=1` | **71 MiB** |
| `-mmt=2` | 255 MiB |
| `-mmt=4` | 255 MiB |

Three things follow, and they close two roadmap items at once.

**1. `ram.lzma2_decompress_ram` was not wrong - it was unreachable.** It
returns `dict + 2 MiB`, source-pinned to `CompressDialog.cpp:3016`, which is
66 MiB at `-md=64m`. Measured single-threaded: 71 MiB. The formula is right
for a *single-threaded* decode, and the extract command never passed `-mmt`,
so the figure the app computed was ~3.9x optimistic against what 7-Zip
actually did. B9's "finish the formula" turned out to be "make the formula's
precondition true".

**2. G7's premise needed correcting.** The roadmap said "cap dict/window and
spill to temp". At extract time the dictionary is fixed by whoever *created*
the archive and the zstd window comes out of the frame header - neither is the
extractor's to choose. The one real lever is the decoder thread count, and it
is a big one: 3.6x.

**3. On this hardware it is free.** Single-threaded extraction measured 2.5-2.7 s
against 2.9-3.0 s for the default, twice each - *faster*, because on two cores
the extra decoder threads cost more in contention than they win back. That is
one corpus on one machine and it is not generalised here: the mode stays
opt-in, and the honest claim is "costs nothing measurable on the target
hardware", not "is always faster".
"""

from __future__ import annotations

import pytest

from excmp import ram
from excmp.stages.sevenzip import SevenZipStage

MIB = 1 << 20


# --------------------------------------------------------------------------
# B9: the formula, and the precondition it depends on
# --------------------------------------------------------------------------

def test_the_single_threaded_figure_is_the_source_pinned_one():
    """Unchanged, and now known to be accurate: 66 MiB predicted against
    71 MiB measured at -md=64m."""
    assert ram.lzma2_decompress_ram(64 * MIB) == 64 * MIB + 2 * MIB


def test_more_decoder_threads_cost_proportionally_more():
    """Measured 255 MiB at -md=64m with threaded decoding, against 71 MiB
    single-threaded - 3.6x. The model is a *bound*, not a fit: 7-Zip's decoder
    thread count is not simply the core count (a 2-core machine produced a
    peak consistent with four dictionary buffers), so this deliberately
    over-books rather than pretending to predict it."""
    one = ram.lzma2_decompress_ram(64 * MIB, threads=1)
    four = ram.lzma2_decompress_ram(64 * MIB, threads=4)
    assert four > one
    assert four >= 255 * MIB, (
        "the bound must cover the 255 MiB actually measured at -md=64m")


def test_the_threaded_bound_covers_what_was_measured():
    """The two real measurements, as a regression gate. A future 'improvement'
    to this formula must still cover them."""
    for dict_mib, measured_mib in [(16, 33), (64, 255)]:
        bound = ram.lzma2_decompress_ram(dict_mib * MIB, threads=4)
        assert bound >= measured_mib * MIB, (
            f"-md={dict_mib}m measured {measured_mib} MiB, bound says "
            f"{bound / MIB:.0f} MiB")


def test_compression_ram_no_longer_under_books():
    """Measured peaks against the old prediction were 198/176 = 1.12 and
    686/680 = 1.01 - under-booking, which is the dangerous direction, because
    it is what lets a job be accepted that then thrashes.

    A **flat** process baseline was the first fix and measurement rejected it:
    +32 MiB covered all three large rows and then predicted 64.7 MiB for a job
    that measures 15.8, re-creating the "6.0 GB for a 371 KB job" failure
    `effective_dict` exists to prevent. The margin is proportional instead -
    see `_SAFETY_MARGIN` in excmp/ram.py for the four measurements."""
    for dict_mib, measured_mib in [(16, 198), (64, 686), (192, 2006)]:
        predicted = ram.lzma2_compress_ram(dict_mib * MIB, threads=2, level=9)
        assert predicted >= measured_mib * MIB, (
            f"-md={dict_mib}m used {measured_mib} MiB, formula promises "
            f"{predicted / MIB:.0f} MiB")


def test_the_baseline_does_not_swamp_a_small_job():
    """The other half of the same constraint: the safety margin must not make
    a tiny job look enormous. A 300 KB input measures **15.8 MiB**, so a model
    that says hundreds of MiB is not being cautious, it is being wrong in the
    one panel that must never frighten anyone."""
    tiny = ram.lzma2_compress_ram(ram.effective_dict(256 * MIB, 300 * 1024),
                                  threads=2)
    assert tiny < 128 * MIB, tiny


# --------------------------------------------------------------------------
# G7: the lever
# --------------------------------------------------------------------------

def test_extraction_asks_for_one_thread_when_ram_is_limited():
    stage = SevenZipStage()
    cmd = stage.build_extract_cmd(__file__, "out", "7z.exe", threads=1)
    assert "-mmt=1" in cmd


def test_extraction_is_unchanged_when_no_limit_is_asked_for():
    """The default must stay exactly what shipped. This is a mode, not a new
    default - the speed finding is one corpus on one 2-core machine, and
    generalising it to every machine from that is precisely the mistake B8
    caught in the estimator."""
    stage = SevenZipStage()
    cmd = stage.build_extract_cmd(__file__, "out", "7z.exe")
    assert not any(part.startswith("-mmt") for part in cmd), cmd


def test_the_thread_cap_is_a_real_switch_not_a_string_append():
    """`-mmt` has to arrive as its own argv element. 7-Zip parses switches
    positionally and a concatenated one is silently treated as part of the
    archive name - which is the shape of bug that makes a 'limit' quietly do
    nothing."""
    stage = SevenZipStage()
    cmd = stage.build_extract_cmd(__file__, "out", "7z.exe", threads=1)
    assert cmd.count("-mmt=1") == 1
    assert cmd.index("-mmt=1") < len(cmd) - 1, "switch must precede the archive"


@pytest.mark.parametrize("threads", [0, -1, None])
def test_a_meaningless_thread_count_is_ignored_rather_than_passed(threads):
    """`-mmt=0` means "use all cores" to 7-Zip - the exact opposite of what a
    caller asking for a RAM limit wants. Refusing to emit it is safer than
    trusting every caller to sanitise first."""
    stage = SevenZipStage()
    cmd = stage.build_extract_cmd(__file__, "out", "7z.exe", threads=threads)
    assert not any(part.startswith("-mmt") for part in cmd), cmd


# --------------------------------------------------------------------------
# the wiring, because a limit that never reaches 7-Zip is worse than none
# --------------------------------------------------------------------------

def test_the_context_defaults_to_the_tools_own_choice():
    """0, not 1. The shipped behaviour has to stay reachable and stay the
    default - see `test_extraction_is_unchanged_when_no_limit_is_asked_for`
    for why this is a mode rather than a new default."""
    from excmp.stages.base import StageContext

    ctx = StageContext(temp_dir=".")
    assert ctx.extract_threads == 0
    assert ctx.threads == 0, "the compressor's thread count is a separate knob"


def test_the_context_value_reaches_the_command(tmp_path, monkeypatch):
    """The gap this closes: `build_extract_cmd` accepting a `threads`
    argument proves nothing if `extract()` never passes one. That is exactly
    the shape of F2's defect this session - a parameter plumbed into a
    signature and into no call site - so the path is asserted, not assumed."""
    from excmp.stages import sevenzip
    from excmp.stages.base import StageContext

    seen: list[list[str]] = []
    monkeypatch.setattr(sevenzip, "run_tool",
                        lambda cmd, *a, **k: seen.append(list(cmd)))
    stage = sevenzip.SevenZipStage()
    monkeypatch.setattr(stage, "_exe", lambda: "7z.exe")

    archive = tmp_path / "a.7z"
    archive.write_bytes(b"not really an archive")
    stage.extract(archive, tmp_path / "out",
                  StageContext(temp_dir=tmp_path, extract_threads=1))
    assert seen and "-mmt=1" in seen[0], seen

    seen.clear()
    stage.extract(archive, tmp_path / "out2",
                  StageContext(temp_dir=tmp_path))
    assert seen and not any(p.startswith("-mmt") for p in seen[0]), seen


def test_the_cli_flag_sets_it():
    """`--low-memory` has to end up as `extract_threads=1`. Checked through
    the parser rather than by reading the source, because the defaults an
    argparse action produces are easy to get subtly wrong."""
    from excmp.cli import build_parser

    args = build_parser().parse_args(["extract", "a.excmp", "-o", "out",
                                      "--low-memory"])
    assert args.low_memory is True

    plain = build_parser().parse_args(["extract", "a.excmp", "-o", "out"])
    assert plain.low_memory is False
