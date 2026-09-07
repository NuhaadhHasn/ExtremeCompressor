"""B4 — the WAV specialist, and the first one in this project that wins.

Measured on 4 real WAVs from this machine (335,536,808 B) before anything here
was written:

===================================  ========  ================
method                                  saved  byte-identical
===================================  ========  ================
store (what shipped before B4)          0.00%  n/a
7z mx9, default filters                 9.45%  yes
7z mx9 ``-mf=Delta:4``                  3.07%  yes
7z mx9 ``-mf=Delta:2``                  1.67%  yes
**flac -8 --keep-foreign-metadata**   **43.15%**  **yes, 4/4**
===================================  ========  ================

B3's ``oxipng``, B5's ``qpdf`` and K4's wide zstd window all *lost* to the
existing ``precomp -> 7z`` route once real files went through both. B4 is
different for a structural reason rather than a lucky one: a PDF or a docx is
already deflate output one layer down, which is exactly what Precomp reaches,
while a WAV is **genuinely uncompressed PCM** and no general-purpose
compressor models audio. 7-Zip's own Delta filter, which exists for this, made
things *worse* - mastered music is loud enough that differencing raises the
entropy it was supposed to lower.

Two findings shaped this module.

**A WAV was stored and the reason shown was false.** ``Category.AUDIO`` is in
``planner._MEDIA``, so every WAV got "already compressed by its codec; stored
losslessly so quality is untouched". A WAV has no codec. 5.07 GiB of WAV on
this machine compressed by nothing while being told it was already optimal.

**Plain ``flac -8`` is not byte-lossless on a WAV *file*.** It is lossless
about *audio*. On a real track the ``data`` chunk came back identical
(``0x031899f0`` on both sides) and the file was **458,114 bytes shorter**,
because the original carries non-audio RIFF chunks that ``flac -d`` silently
discards. ``--keep-foreign-metadata`` preserves them and reproduces the file
exactly, for 458,198 bytes - the chunks plus framing. Without that flag B4
would have been another Phase C item, and the ledger would have caught it at
restore time instead of here.

The contract mirrors :mod:`excmp.jpeg` deliberately: :func:`pack` returns bytes
that have **already been restored once and compared**, or ``None``. There is no
error to handle at the call site and no way to skip the check.
"""

from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path

from .tempclean import rmtree_force

#: Below this the FLAC container's own header costs more than the audio saves,
#: and every packed entry buys a subprocess at restore time.
MIN_SIZE = 4096

#: Refuse absurd inputs outright rather than handing them to a subprocess.
#: The largest real WAV on this machine is 142 MiB; 4 GiB is the RIFF format's
#: own 32-bit ceiling, so anything past it is malformed by definition.
MAX_SIZE = 4 << 30

_TIMEOUT = 900


def _flac_exe() -> Path | None:
    """The pinned `flac.exe`, or ``None``.

    Looked up through E1's manifest so there is exactly one place that knows
    where tools live, and so a missing binary is a normal answer rather than
    an exception - the WAV is stored raw, exactly as before B4.
    """
    from . import toolfetch

    spec = toolfetch.TOOL_MANIFEST.get("flac")
    if spec is None:
        return None
    return toolfetch.installed_path(spec)


def available() -> bool:
    """Is the flac binary present *and* still the bytes E1 pinned?

    `installed_path` re-hashes, so this is not merely "does a file exist".
    """
    return _flac_exe() is not None


def looks_like_wav(head: bytes) -> bool:
    """A RIFF/WAVE container. Cheap gate before touching a subprocess.

    Checks the WAVE form tag, not just ``RIFF``: an AVI is also RIFF and is
    not something to hand to a lossless audio coder.
    """
    return (len(head) >= 12 and head[:4] == b"RIFF"
            and head[8:12] == b"WAVE")


def _run(exe: Path, args: list[str]) -> bool:
    try:
        done = subprocess.run([str(exe), *args], capture_output=True,
                              timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def pack(raw: bytes) -> bytes | None:
    """FLAC-encode a WAV, verify the round-trip, and return the bytes.

    ``None`` means "store this raw", which is always a correct answer: no
    caller has to distinguish "flac is missing" from "flac declined this file"
    from "flac produced something that did not restore".

    The immediate decode-and-compare is the point, not a belt-and-braces
    extra. FLAC's own losslessness claim is about *audio*, and this project's
    ledger is about *files* - which is precisely where plain ``flac -8`` fails.
    Paying for the round-trip here means a file FLAC would mishandle is caught
    while storing it raw is still free, rather than at restore time when D9
    would refuse to publish the whole archive.
    """
    if not (MIN_SIZE <= len(raw) <= MAX_SIZE):
        return None
    if not looks_like_wav(raw[:12]):
        return None
    exe = _flac_exe()
    if exe is None:
        return None

    work = Path(tempfile.mkdtemp(prefix="excmp-flac-"))
    try:
        wav = work / "in.wav"
        wav.write_bytes(raw)
        packed_path = work / "out.flac"
        if not _run(exe, ["-8", "--keep-foreign-metadata", "--totally-silent",
                          "-f", "-o", str(packed_path), str(wav)]):
            return None
        if not packed_path.is_file():
            return None
        packed = packed_path.read_bytes()
        # Never ship a "win" that is not one. A WAV of pure noise can encode
        # larger than it started, and the store route is free.
        if len(packed) >= len(raw):
            return None

        back = work / "back.wav"
        if not _run(exe, ["-d", "--keep-foreign-metadata", "--totally-silent",
                          "-f", "-o", str(back), str(packed_path)]):
            return None
        if not back.is_file() or back.read_bytes() != raw:
            return None
        return packed
    finally:
        rmtree_force(work)


def unpack(packed: bytes) -> bytes:
    """Restore a WAV from :func:`pack`'s output.

    Raises :class:`RuntimeError` on failure. Unlike `pack` there is no
    fallback here: the ledger says this entry is FLAC, so being unable to
    decode it is a genuine restore failure and must be loud.
    """
    exe = _flac_exe()
    if exe is None:
        raise RuntimeError(
            "this archive holds FLAC-packed audio and the pinned flac binary "
            "is not installed - fetch it to restore these files")

    work = Path(tempfile.mkdtemp(prefix="excmp-flac-"))
    try:
        src = work / "in.flac"
        src.write_bytes(packed)
        out = work / "out.wav"
        if not _run(exe, ["-d", "--keep-foreign-metadata", "--totally-silent",
                          "-f", "-o", str(out), str(src)]):
            raise RuntimeError("flac could not decode this entry")
        if not out.is_file():
            raise RuntimeError("flac produced no output for this entry")
        return out.read_bytes()
    finally:
        rmtree_force(work)


def looks_like(head: bytes) -> bool:
    """Registry-facing alias, matching :mod:`excmp.jpeg`."""
    return looks_like_wav(head)
