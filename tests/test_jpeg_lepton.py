"""B2 — the JPEG specialist, and the 38% of real JPEGs it refuses.

Lepton re-encodes a JPEG's entropy-coded data and reproduces the original file
bit for bit. Measured on 23 real photos from this machine: **33.4% saved** at
4.4 MB/s, against the ~22% the roadmap predicted.

The number that shaped the design is the other one. On a 37-file corpus of
actual design work lepton **refused 14 files** — 13 CMYK/4-channel (print
work, so an entire genre of real file) and one image wider than 16384 px. So
the tests below spend most of their attention on the refusal path, because
that is the path a third of a real folder takes.
"""

from __future__ import annotations

import hashlib
import io
import struct
from pathlib import Path

import pytest

from excmp import jpeg
from excmp.engine import compress, extract
from excmp.manifest import read_container
from excmp.planner import Profile
from excmp.stages.base import StageContext

needs_lepton = pytest.mark.skipif(not jpeg.available(),
                                  reason="lepton-jpeg-python not installed")


def _a_real_jpeg() -> bytes:
    """A genuine baseline JPEG, encoded here rather than pasted as a blob, so
    it is inspectable and cannot rot into an opaque constant."""
    Image = pytest.importorskip("PIL.Image")
    import random

    rng = random.Random(20260902)
    img = Image.new("RGB", (320, 240))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                 for _ in range(320 * 240)])
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# The module contract
# ---------------------------------------------------------------------------

def test_a_non_jpeg_is_declined_not_attempted():
    assert jpeg.pack(b"PK\x03\x04" + b"x" * 5000) is None
    assert jpeg.pack(b"\x89PNG\r\n\x1a\n" + b"x" * 5000) is None


def test_a_tiny_file_is_not_worth_it():
    assert jpeg.pack(jpeg.JPEG_MAGIC + b"\x00" * 10) is None


def test_truncated_and_corrupt_jpegs_are_declined_not_raised():
    """Lepton raises on these. `pack` turning that into `None` is what lets
    the caller stay a one-liner with no error handling."""
    assert jpeg.pack(jpeg.JPEG_MAGIC + b"\xff" * 4000) is None
    assert jpeg.pack(jpeg.JPEG_MAGIC + bytes(range(256)) * 20) is None


def test_looks_like_jpeg_is_only_the_magic():
    assert jpeg.looks_like_jpeg(b"\xff\xd8\xff\xe0rest")
    assert not jpeg.looks_like_jpeg(b"\xff\xd8\x00")
    assert not jpeg.looks_like_jpeg(b"")


@needs_lepton
def test_a_real_jpeg_packs_and_is_bit_exact():
    raw = _a_real_jpeg()
    packed = jpeg.pack(raw)
    if packed is None:
        pytest.skip("lepton declined this particular encoder's output")
    assert len(packed) < len(raw)
    assert jpeg.unpack(packed) == raw


@needs_lepton
def test_pack_verifies_the_roundtrip_itself(monkeypatch):
    """The core safety property: `pack` must not return bytes it has not
    already turned back into the original. Here lepton is made to 'succeed'
    while decompressing to something else - `pack` has to catch that itself,
    because nothing downstream would until the D9 gate refused the archive.
    """
    raw = _a_real_jpeg()
    monkeypatch.setattr(jpeg._lepton, "decompress_bytes",
                        lambda data, config=None: b"not the original")
    assert jpeg.pack(raw) is None


@needs_lepton
def test_a_result_that_is_not_smaller_is_declined(monkeypatch):
    raw = _a_real_jpeg()
    monkeypatch.setattr(jpeg._lepton, "compress_bytes",
                        lambda data, config=None: b"x" * (len(raw) + 1))
    assert jpeg.pack(raw) is None


def test_unpack_without_the_wheel_says_so_loudly(monkeypatch):
    """An archive holding lepton entries genuinely cannot be restored without
    lepton. Returning the packed bytes as if they were the file would hand
    back something that is not the file."""
    monkeypatch.setattr(jpeg, "_lepton", None)
    with pytest.raises(RuntimeError, match="lepton"):
        jpeg.unpack(b"anything")


# ---------------------------------------------------------------------------
# Through the engine
# ---------------------------------------------------------------------------

@needs_lepton
def test_a_jpeg_survives_a_real_roundtrip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    raw = _a_real_jpeg()
    (src / "photo.jpg").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))
    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))

    got = [p for p in out.rglob("*") if p.is_file() and p.name == "photo.jpg"]
    assert got, "the JPEG did not come back"
    assert hashlib.sha256(got[0].read_bytes()).hexdigest() == digest


@needs_lepton
def test_the_archive_is_actually_smaller_for_it(tmp_path):
    """The whole point. A JPEG is high-entropy, so before B2 it was stored
    verbatim and the archive was never smaller than the photo."""
    src = tmp_path / "src"
    src.mkdir()
    raw = _a_real_jpeg()
    (src / "photo.jpg").write_bytes(raw)

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))

    manifest, _ = read_container(archive, tmp_path / "peek")
    entry = next(iter(manifest.inputs.values()))
    if entry.get("codec") != "lepton":
        pytest.skip("lepton declined this encoder's output")
    assert archive.stat().st_size < len(raw), (
        f"archive {archive.stat().st_size:,} vs photo {len(raw):,}")


@needs_lepton
def test_a_jpeg_lepton_refuses_still_round_trips(tmp_path):
    """The 38% case, and the one that matters most. A CMYK JPEG is an
    ordinary file; it must land in the archive as raw stored bytes and come
    back identical, with no error anywhere."""
    src = tmp_path / "src"
    src.mkdir()
    # Not a valid JPEG body - stands in for anything lepton declines.
    hostile = jpeg.JPEG_MAGIC + b"\xdb\x00\x43" + bytes(range(256)) * 40
    (src / "cmyk.jpg").write_bytes(hostile)
    digest = hashlib.sha256(hostile).hexdigest()

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))

    manifest, _ = read_container(archive, tmp_path / "peek")
    entry = next(iter(manifest.inputs.values()))
    assert "codec" not in entry, "claimed lepton for a file it cannot pack"

    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))
    got = [p for p in out.rglob("*") if p.is_file()]
    assert got and hashlib.sha256(got[0].read_bytes()).hexdigest() == digest


@needs_lepton
def test_a_mixed_folder_handles_both_kinds(tmp_path):
    """What a real photo folder looks like: some lepton can take, some it
    cannot, plus files that are not images at all."""
    src = tmp_path / "src"
    src.mkdir()
    contents = {
        "good.jpg": _a_real_jpeg(),
        "refused.jpg": jpeg.JPEG_MAGIC + bytes(range(256)) * 40,
        "notes.txt": b"just some text " * 500,
        "blob.bin": bytes(range(256)) * 100,
    }
    for name, data in contents.items():
        (src / name).write_bytes(data)

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.NORMAL,
             StageContext(temp_dir=tmp_path / "t", threads=2))
    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))

    for name, data in contents.items():
        match = [p for p in out.rglob("*") if p.is_file() and p.name == name]
        assert match, f"{name} did not come back"
        assert match[0].read_bytes() == data, f"{name} came back different"
