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


def pack(raw: bytes) -> bytes | None:
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
        # Lepton raises on CMYK/4-channel and on images wider than 16384 px,
        # both of which are ordinary files someone might hand us. Refusing to
        # compress is not an error condition.
        return None
    if not packed or len(packed) >= len(raw):
        return None
    try:
        if _lepton.decompress_bytes(packed) != raw:
            return None
    except Exception:
        return None
    return bytes(packed)


def unpack(packed: bytes) -> bytes:
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
