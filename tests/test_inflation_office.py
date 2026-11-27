"""The disk preflight reserves what Precomp really makes of Word, PowerPoint and PDF files.

Measured 2026-11-27, file by file at ``-cn -intense`` on the 51 Office/PDF files in ``temp-copies`` (ONE corpus), `.pcf` over input:

    .docx  15 files   19.3x byte-weighted   (per file: median 6.1x, max 84x)
    .pdf   25 files    6.3x byte-weighted   (median 1.2x, max 39x)
    .pptx  11 files    1.3x byte-weighted   (median 6.0x, max 8x: a few big decks hold media that does not expand)
    all    51 files    4.94x

so the generic 5x is right for a typical mix and badly wrong for a folder of small Word files. A real job on a 39 MB slice of
the smallest of those files needed 610 MB of temp against the 346 MB the preflight had booked; small files expand
more than their type's average, so the figures below still come in under that slice (the 462 MB booked now is a warning, not a
refusal).
"""

from __future__ import annotations

from pathlib import Path

from excmp import engine
from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, precomp_inflation
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t") for n in ("7z", "precomp", "zpaqfranz")}


def _file(name, size=2_000_000):
    return FileInfo(path=Path(name), size=size, category=Category.COMPRESSED_ARCHIVE, entropy_bps=7.99,
                    sample_ratio=1.0, sample_ratio_max=1.0, expandable=True)


def test_word_files_reserve_what_they_were_measured_to_need():
    assert precomp_inflation([_file("notes.docx")]) >= 19       # 19.3x byte-weighted


def test_a_pdf_reserves_more_than_the_generic_figure():
    assert precomp_inflation([_file("book.pdf")]) >= 6          # 6.3x byte-weighted


def test_a_deck_reserves_what_a_small_one_needs():
    assert precomp_inflation([_file("talk.pptx")]) >= 8         # up to 8x per file


def test_a_mixed_folder_is_weighted_by_bytes_not_by_its_worst_file():
    """1% Word files in a folder of PDFs must not reserve as though it were all Word."""
    mix = [_file("a.docx", 20_000), _file("b.pdf", 1_980_000)]
    assert precomp_inflation(mix) < precomp_inflation([_file("a.docx")])
    assert precomp_inflation(mix) >= 6


def test_the_existing_figures_do_not_move():
    assert precomp_inflation([_file("b.epub")]) >= 18
    assert precomp_inflation([_file("d.odt")]) >= 10
    assert precomp_inflation([_file("l.aar")]) == 5
    assert precomp_inflation([_file("misc.bin")]) == 5


def test_the_temp_the_preflight_books_grows_for_word_files(tmp_path):
    """The figures reach the number the app shows and warns with, not just the table."""
    def peak(name):
        infos = [_file(name, 5_000_000)]
        the_plan = plan(infos, Profile.EXTREME, TOOLS)
        return sum(p for _probe, _floor, p in engine.compress_space_needs(tmp_path / "o.excmp", tmp_path / "t", infos, the_plan))
    assert peak("report.docx") > peak("notes.bin") * 2           # 20x against 5x of the piped bytes
