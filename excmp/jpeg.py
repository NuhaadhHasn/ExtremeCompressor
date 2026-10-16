"""B2 — the JPEG specialist, and the rule that it must never cost anything.

Lepton (Microsoft's Rust port, Apache-2.0, shipped as the
``lepton-jpeg-python`` wheel so there is no exe to find) re-encodes a JPEG's
entropy-coded data with an arithmetic coder and reproduces the original file
**bit for bit**. Measured on 23 real photos from this machine: **33.4%
saved** at 4.4 MB/s — comfortably better than the ~22% the roadmap predicted.

The reason this module exists rather than a two-line call at the call site is
everything below.

**Lepton refuses a lot of real JPEGs.** On a 37-file corpus of actual design
work it rejected **14 of them** — 13 CMYK/4-channel files (print work, so an
entire genre) and one image wider than 16384 px. A specialist that fails on
38% of a real folder cannot be wired in as "compress the JPEGs"; it has to be
"try, and shrug it off".

**And it must prove itself per file, at compress time.** :func:`pack`
round-trips every candidate immediately and compares against the original
bytes, discarding the result unless they match exactly. That doubles the work
on JPEGs, and it buys the one thing worth paying for: a file lepton would
mis-handle is detected *now*, while falling back to storing it raw is free,
rather than at restore time when the whole archive fails. The D9 gate would
catch it either way — but "caught and worked around" beats "caught and
refused to publish".

So the contract here is deliberately narrow: :func:`pack` returns bytes we
have *already restored once*, or ``None``. There is no error to handle at the
call site and no way to opt out of the check.
"""

from __future__ import annotations

import struct

#: JPEG's start-of-image marker. Cheap gate before handing bytes to a codec.
JPEG_MAGIC = b"\xff\xd8\xff"

#: Below this there is nothing to win and the per-file overhead dominates.
MIN_SIZE = 1024

try:  # pragma: no cover - presence depends on the wheel being installed
    import lepton_jpeg_python as _lepton
except ImportError:  # pragma: no cover
    _lepton = None


def available() -> bool:
    """Is the wheel installed? Absence is normal and never an error — the
    JPEG simply gets stored raw, exactly as it was before B2."""
    return _lepton is not None


def looks_like_jpeg(data: bytes) -> bool:
    return data[:3] == JPEG_MAGIC


#: Lepton's largest side, measured on 0.5.8 (B19): 16,386 px is accepted and
#: 16,387 refused, on either axis ("image dimensions larger than 16386x16386").
LEPTON_MAX_SIDE = 16386

#: Start-of-frame markers: baseline, extended, progressive, lossless, and the
#: hierarchical and arithmetic variants. Not C4/C8/CC, which share the range.
_SOF_MARKERS = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})

#: Markers with no length field: TEM, RST0-7, and a stray SOI. T.81 allows
#: none of them before the frame (B.2), but a decoder may still read such a
#: file, so they are stepped over rather than read as a segment whose
#: "length" is the next marker's bytes (review, B19). A miss here was only
#: ever the old route, never a lossless risk.
_STANDALONE = frozenset({0x01, *range(0xD0, 0xD9)})

#: How many markers to walk before giving up. Real files had at most 17
#: before their frame header (a print ICC profile is split across several),
#: but Photoshop splits extended XMP into 64 KB pieces, so the bound is
#: generous: each step reads four bytes and seeks.
_MAX_SEGMENTS = 4096


def frame_header(path) -> tuple[int, int, int] | None:
    """``(components, width, height)`` from the JPEG's frame header, or None.

    Walks the marker chain, seeking over each segment, so it reads a few
    bytes per segment however large they are. It has to: in every CMYK file
    measured (B19) the frame sat 565 KB in, behind a print ICC profile, far
    past the analyzer's 64 KiB head. None for anything that isn't a readable
    JPEG up to its frame - a PNG named .jpg, a truncated file - because this
    runs during analysis, which K3 made incapable of failing a job.
    """
    try:
        with open(path, "rb") as fh:
            if fh.read(2) != b"\xff\xd8":
                return None
            for _ in range(_MAX_SEGMENTS):
                mark = fh.read(2)
                if len(mark) < 2 or mark[0] != 0xFF:
                    return None
                if mark[1] == 0xFF:          # fill byte before a marker
                    fh.seek(-1, 1)
                    continue
                if mark[1] in _STANDALONE:
                    continue
                size = fh.read(2)
                if len(size) < 2:
                    return None
                length = struct.unpack(">H", size)[0]
                if mark[1] in _SOF_MARKERS:
                    body = fh.read(6)        # precision, height, width, components
                    if len(body) < 6:
                        return None
                    height, width = struct.unpack(">HH", body[1:5])
                    return body[5], width, height
                if mark[1] == 0xDA or length < 2:   # scan data before any frame
                    return None
                fh.seek(length - 2, 1)
    except OSError:
        return None
    return None


def lepton_refuses(path) -> bool:
    """Will lepton refuse this JPEG, by what its frame header says?

    The two refusals the header shows, both measured on lepton 0.5.8 (B19):
    4 colour channels (CMYK/YCCK: "Unsupported4Colors") and a side over
    `LEPTON_MAX_SIDE`. Together they were 143.9 of the 144.1 MB lepton
    declined across four corpora. Its other refusals are scan-structure
    quirks of small progressive files the header can't reveal; those stay
    stored, as before. Grayscale is accepted.
    """
    frame = frame_header(path)
    if frame is None:
        return False
    components, width, height = frame
    return components == 4 or max(width, height) > LEPTON_MAX_SIDE


def pack(raw: bytes, ctx: object = None, effort: int | None = None) -> bytes | None:
    """Lepton-compress ``raw``, or ``None`` if it is not worth it.

    ``None`` covers every uninteresting outcome — not a JPEG, too small, the
    wheel is missing, lepton refused it (CMYK, oversized), the result came out
    bigger, or **it did not round-trip bit-exactly**. The caller stores the
    original bytes and nothing anywhere has to know why.

    The round-trip is the point. Lepton's own success return is not evidence
    that we can get the file back; only getting the file back is.
    """
    if _lepton is None or len(raw) < MIN_SIZE or not looks_like_jpeg(raw):
        return None
    try:
        packed = _lepton.compress_bytes(raw)
    except Exception:
        # Lepton raises on CMYK/4-channel, on a side over 16,386 px, and on
        # some progressive scan layouts, all of them ordinary files someone
        # might hand us. Refusing to compress is not an error condition. (On
        # a chain with Precomp the first two never get here: the planner
        # pipes them to packJPG, B19.)
        return None
    if not packed or len(packed) >= len(raw):
        return None
    try:
        if _lepton.decompress_bytes(packed) != raw:
            return None
    except Exception:
        return None
    return bytes(packed)


def unpack(packed: bytes, limit: int | None = None) -> bytes:
    """Restore the original JPEG. Raises if the wheel is missing.

    Deliberately loud rather than lenient: an archive that recorded a lepton
    entry cannot be restored without lepton, and pretending otherwise would
    hand back a file that is not the file.
    """
    if _lepton is None:
        raise RuntimeError(
            "this archive contains lepton-compressed JPEGs and the "
            "'lepton-jpeg-python' package is not installed")
    return bytes(_lepton.decompress_bytes(packed))


def looks_like(head: bytes) -> bool:
    """Registry-facing alias. `manifest._CODECS` asks every codec the same
    question, so the name has to be the same on each of them."""
    return looks_like_jpeg(head)
