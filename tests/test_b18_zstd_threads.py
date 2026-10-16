"""B18(a): zstd's thread count, measured (2026-10-15, i5-7200U, every frame
restored and SHA-256 compared; docs/benchmarks/2026-10-15-b18-settings.md).

Silesia tar (212 MB), level 19 + LDM, three pairs (-1 always first):

    threads=-1   132.4 s median (91-149)   735 MiB peak   52,595,898 B
    threads=2    162.9 s median (109-188)  552 MiB peak   52,595,898 B

Identical bytes. The timings don't settle speed: the order was fixed, and on
the contended machine the same 4-thread setting took 37.1 s and 19.6 s on the
installer tar. zstd's output does not depend on the worker count (threads 1,
2, 4 and -1 all wrote 46,982,246 B there; only 0, no worker threads, differs),
unlike 7-Zip's, so nothing measured argues for moving the default. It stays.

What B18 changes: an *explicit* Worker threads setting used to be ignored.
It now reaches zstd. "Auto" (0) keeps the measured -1.
"""

from __future__ import annotations

import pytest
import zstandard

from excmp.stages.base import StageContext
from excmp.stages.zstdstage import ZstdStage

#: python-zstandard resolves -1 to the logical processor count when it builds
#: the parameters (4 on the i5-7200U), so -1 is asserted by what it becomes.
ALL = zstandard.ZstdCompressionParameters.from_level(1, threads=-1).threads


def test_auto_keeps_all_logical_processors():
    assert ALL >= 1
    assert ZstdStage()._params(10_000_000).threads == ALL
    assert ZstdStage()._params(10_000_000, threads=0).threads == ALL


@pytest.mark.parametrize("n", [1, 2])
def test_an_explicit_thread_count_reaches_zstd(n):
    assert ZstdStage()._params(10_000_000, threads=min(n, ALL)).threads == min(n, ALL)


@pytest.mark.parametrize("n", [5, 8, 16, 64])
def test_an_explicit_count_never_exceeds_the_measured_default(n):
    """Review, B18: the spin box allows up to 4x the logical processors, and
    `ram.zstd_compress_ram` was fitted at -1 (every logical processor). Each
    worker holds its own window-sized buffers, so 16 workers would blow past
    the peak the GUI quotes. The setting exists to *lower* the load, so a
    count above the default is capped at it rather than passed through."""
    assert ZstdStage()._params(10_000_000, threads=n).threads == min(n, ALL)


@pytest.mark.parametrize("requested, expected", [(0, ALL), (1, 1), (3, min(3, ALL))])
def test_compress_passes_the_settings_thread_count(tmp_path, monkeypatch,
                                                    requested, expected):
    seen = []
    real = ZstdStage._params

    def spy(self, total_bytes=0, threads=0):
        p = real(self, total_bytes, threads)
        seen.append(p.threads)
        return p

    monkeypatch.setattr(ZstdStage, "_params", spy)
    src = tmp_path / "a.txt"
    src.write_text("measured, not assumed. " * 20_000)
    ctx = StageContext(temp_dir=tmp_path / "tmp", threads=requested)
    ZstdStage().compress(src, tmp_path / "a.tar.zst", ctx)
    assert seen == [expected]
