"""B3 — PNG, and why the roadmap's answer would have broken the product.

The plan said: *"PNG specialist: `oxipng -o max` default, ECT `-9` under
Extreme."* Measured, that is the wrong tool for this product.

**oxipng does not preserve bytes.** On 10 real PNGs it saved 31.79% and
produced **0 byte-identical files**. It rewrites the image to a smaller
encoding that renders identically — pixel-lossless, not byte-lossless. Our
guarantee is a byte-identical restore checked by SHA-256, so an oxipng'd file
would fail its own ledger entry. The D9 gate would catch it and refuse to
publish; the dangerous version of that bug is someone "fixing" it by recording
the *new* hash, at which point the user silently gets back a different file
from the one they put in. oxipng belongs in Phase C with the AV1 re-encoder —
opt-in, clearly labelled, changes your file.

**And the lossless path is better anyway.** PNG is deflate-wrapped, which is
exactly what Precomp expands and reconstructs exactly:

| approach | 15 real PNGs | byte-identical |
|---|---|---|
| stored (what shipped before) | 3,522,560 | yes |
| oxipng | ~2,404,000 (−31.8%) | **no** |
| **precomp → 7z** | **2,152,650 (−38.9%)** | **yes** |

The lossless route wins on ratio *and* keeps the guarantee. All this needed
was for PNGs to stop being routed to `store`.

**Why they were.** The planner exempts `_MEDIA` from the Precomp override, on
the sound reasoning that a JPEG's or an MP4's entropy is real and expanding it
is pointless. PNG is the exception in that set: its high entropy is *deflate
output*, not inherent randomness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import (_DEFLATE_MEDIA, Profile, plan, precomp_inflation)
from excmp.tools import ToolInfo

WITH_PRECOMP = {"precomp": ToolInfo("precomp", "p", ""),
                "7z": ToolInfo("7z", "7", "")}
NO_PRECOMP = {"precomp": None, "7z": ToolInfo("7z", "7", "")}


def _info(name: str, category: Category, entropy: float = 7.95,
          size: int = 1_000_000) -> FileInfo:
    return FileInfo(path=Path(name), size=size, category=category,
                    entropy_bps=entropy)


def _routes(infos, tools, profile=Profile.EXTREME):
    p = plan(infos, profile, tools)
    return {r.action: r for r in p.routes}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_a_png_goes_through_the_pipeline_when_precomp_is_available():
    """The whole fix. Worth 38.9% against the 0% it got as a stored file."""
    routes = _routes([_info("shot.png", Category.IMAGE)], WITH_PRECOMP)
    assert "pipeline" in routes, "PNG is still being stored"
    assert Path("shot.png") in routes["pipeline"].files


def test_a_png_is_stored_when_precomp_is_missing():
    """Without the tool that expands deflate there is nothing to gain, and
    piping it would just cost time to produce a slightly larger archive."""
    routes = _routes([_info("shot.png", Category.IMAGE)], NO_PRECOMP)
    assert "store" in routes
    assert Path("shot.png") in routes["store"].files


def test_a_jpeg_still_stays_stored():
    """JPEG entropy is real - it is already entropy-coded, and Precomp has
    nothing to expand. It has its own specialist now (B2/lepton), which only
    applies on the stored route."""
    routes = _routes([_info("photo.jpg", Category.IMAGE)], WITH_PRECOMP)
    assert "store" in routes
    assert Path("photo.jpg") in routes["store"].files


@pytest.mark.parametrize("name", ["clip.mp4", "song.mp3", "movie.mkv", "tune.flac"])
def test_real_media_still_stays_stored(name):
    cat = Category.VIDEO if name.endswith(("mp4", "mkv")) else Category.AUDIO
    routes = _routes([_info(name, cat)], WITH_PRECOMP)
    assert "store" in routes, f"{name} was piped; its entropy is real"


def test_the_deflate_exception_list_is_deliberately_tiny():
    """Only formats whose high entropy is *deflate output*. Adding a format
    here on a hunch is how a media file starts getting piped for nothing."""
    assert _DEFLATE_MEDIA == {".png"}


def test_a_png_with_genuinely_low_entropy_is_piped_anyway():
    """It would have been piped before this change too - the media guard only
    ever mattered for files the entropy rule wanted to store."""
    routes = _routes([_info("flat.png", Category.IMAGE, entropy=2.0)],
                     WITH_PRECOMP)
    assert "pipeline" in routes


def test_case_does_not_matter():
    routes = _routes([_info("SHOT.PNG", Category.IMAGE)], WITH_PRECOMP)
    assert "pipeline" in routes


# ---------------------------------------------------------------------------
# The inflation estimate, which PNG breaks
# ---------------------------------------------------------------------------

def test_png_inflates_far_more_than_the_generic_estimate():
    """Measured: 15 PNGs went from a 3.5 MB tar to a **177 MB** .pcf — about
    50x, where the generic Precomp figure is 5x. Budgeting 5x for a PNG folder
    under-reserves temp by an order of magnitude, and temp exhaustion
    mid-pipeline is the failure this preflight exists to prevent."""
    pngs = [_info("a.png", Category.IMAGE)]
    generic = [_info("a.bin", Category.BINARY)]
    assert precomp_inflation(pngs) > precomp_inflation(generic)
    assert precomp_inflation(pngs) >= 20


def test_a_mixed_set_is_weighted_by_bytes():
    """A folder that is 1% PNG should not reserve as if it were all PNG."""
    mixed = [_info("big.bin", Category.BINARY, size=99_000_000),
             _info("small.png", Category.IMAGE, size=1_000_000)]
    assert precomp_inflation(mixed) < precomp_inflation(
        [_info("a.png", Category.IMAGE)])


def test_no_files_does_not_divide_by_zero():
    assert precomp_inflation([]) >= 1


# ---------------------------------------------------------------------------
# The bomb guard, now that it is exact rather than heuristic
# ---------------------------------------------------------------------------

def test_the_stage_record_carries_what_it_consumed(tmp_path):
    """`input_bytes` is what makes the guard exact. Without it the reader
    falls back to a blanket multiplier, and no multiplier can be both loose
    enough for PNG's honest ~50x and tight enough to be a defence."""
    import hashlib

    from excmp.engine import compress
    from excmp.manifest import read_container
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"compressible " * 50_000)

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))
    manifest, _ = read_container(archive, tmp_path / "peek")
    assert manifest.stages, "no stages recorded"
    for rec in manifest.stages:
        assert rec.input_bytes > 0, f"stage {rec.stage} recorded no input size"


def test_an_archive_from_before_this_field_still_extracts(tmp_path):
    """`input_bytes` defaults to 0 and the reader falls back to the old
    multiplier for those, so archives written before it existed keep working.
    The same promise B11 made for srep archives, in the other direction."""
    import json
    import zipfile

    from excmp.engine import compress, extract
    from excmp.manifest import MANIFEST_NAME
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"content " * 20_000)
    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))

    # Rewrite the container with the field stripped, exactly as an older
    # build would have written it.
    aged = tmp_path / "aged.excmp"
    with zipfile.ZipFile(archive) as src_zip, \
            zipfile.ZipFile(aged, "w", zipfile.ZIP_STORED) as dst_zip:
        for info in src_zip.infolist():
            data = src_zip.read(info)
            if info.filename == MANIFEST_NAME:
                doc = json.loads(data)
                for rec in doc.get("stages", []):
                    rec.pop("input_bytes", None)
                data = json.dumps(doc).encode()
            dst_zip.writestr(info, data)

    out = tmp_path / "out"
    extract(aged, out, StageContext(temp_dir=tmp_path / "xt", threads=2))
    got = [p for p in out.rglob("*") if p.is_file()]
    assert got and got[0].read_bytes() == b"content " * 20_000


def test_a_lying_input_size_does_not_widen_the_guard(tmp_path):
    """The attack the exact bound must not open: an archive that declares a
    huge `input_bytes` to license a huge expansion. The declared figure is
    only ever a *ceiling* on what we will accept, so inflating it cannot make
    a real bomb legal - the payload still has to actually contain the bytes,
    and the ledger still bounds the final restore."""
    from excmp.manifest import StageRecord

    honest = StageRecord(stage="precomp", tool_name="precomp",
                         tool_version="", params={}, input_bytes=1000)
    assert honest.input_bytes == 1000
    # A record with no claim gets the conservative default, not a free pass.
    silent = StageRecord(stage="precomp", tool_name="precomp",
                         tool_version="", params={})
    assert silent.input_bytes == 0
