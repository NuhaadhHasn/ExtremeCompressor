"""B13 - the Ogg specialist: balrogg recompresses Vorbis and Opus losslessly.

Measured on 18 real music files from Wikimedia Commons (169,975,314 B,
2026-10-06, balrogg 1.4) against the best route the app had before:

==========================================  ========  ==============
route                                          saved  byte-identical
==========================================  ========  ==============
store (before B13a)                            -0.004%  n/a
piped through 7-Zip, B13a (Normal)               1.112%  yes
**balrogg -9, per file**                       **13.358%**  **yes, 18/18**
==========================================  ========  ==============

Vorbis alone saved 15.100% and Opus 3.893%. A 7-Zip pass over an Ogg file finds
almost nothing because Ogg's entropy coding already looks random to a general
compressor; balrogg models the codec's own symbols, so it reaches the redundancy
7-Zip cannot see. This is the second specialist that beats the existing chain
rather than merely joining it (FLAC, B4, was the first), and for the same
structural reason: it competes with *storing the file*, not with a codec that
already works.

The contract mirrors :mod:`excmp.flacaudio` and :mod:`excmp.jpeg`: :func:`pack`
returns bytes that have **already been restored once and compared**, or
``None``, and ``None`` is always a correct answer. balrogg documents its own
exit codes (0 ok, 1 refused input, 4 internal error) and none of them are the
gate. The byte comparison is. A binary downloaded from the internet is
untrusted until it has restored the file in front of it.

Two things differ from the earlier specialists, both because of how slow this
one is. balrogg encodes at roughly 0.1-0.3 MB/s at ``-9`` on the target (36 MB
in about 5 minutes, measured), against FLAC's tens of MB/s:

* **Cancel.** It prints nothing while it works, so a cancel check that only
  runs when the tool prints (as ``run_capture``'s does) would wait out the
  entire encode. :func:`_run` polls instead; the same lesson as K6.
* **Effort follows the profile** (:func:`effort_for`), because the curve is
  flat at the top: ``-5`` saves all but 0.04 points of what ``-9`` does in a
  third of the time or less.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .stages.base import CREATE_NO_WINDOW, StageError
from .tempclean import rmtree_force

#: Ogg's capture pattern. Cheap gate before touching a subprocess. It also
#: matches Theora video, Ogg FLAC and Speex, none of which balrogg handles; it
#: refuses them (exit 1) and :func:`pack` returns ``None`` for the file.
OGG_MAGIC = b"OggS"

#: The extensions of Ogg audio containers (Vorbis, Opus). The planner routes
#: them and the estimator predicts them from this one set.
SUFFIXES = frozenset({".ogg", ".oga", ".opus"})

#: Below this the per-entry cost of a subprocess outweighs anything saved.
MIN_SIZE = 1024

#: The whole file is read into memory to be packed, and again to be compared.
#: The largest real Ogg measured so far is 38 MB; 512 MiB is a ceiling for
#: something malformed rather than a limit anyone should reach.
MAX_SIZE = 512 << 20

#: Used when the profile is unknown. ``-5`` saved 11.547% against ``-9``'s
#: 11.586% on three real files, at under a third of the time.
DEFAULT_EFFORT = 5

#: Measured on three real files (19.3 MB). Saved: -1 9.448%, -2 10.879%,
#: -3 11.039%, -4 11.242%, -5 11.547%, -6 11.570%, -7 11.572%, -8 11.575%,
#: -9 11.586%. Encode time rises steeply past -4 and the saving does not, so
#: only Insane (the owner's "best for compression") pays for -9.
_EFFORT_BY_PROFILE = {"fast": 1, "normal": 4, "extreme": 5, "insane": 9}


def effort_for(profile: object) -> int:
    """balrogg's ``-1``..``-9`` for a profile (an enum or its string value)."""
    name = str(getattr(profile, "value", profile)).lower()
    return _EFFORT_BY_PROFILE.get(name, DEFAULT_EFFORT)


def _balrogg_exe() -> Path | None:
    """The pinned ``balrogg``, or ``None``.

    Looked up through E1's manifest so there is one place that knows where
    tools live, and so a missing or tampered binary is a normal answer rather
    than an exception: the file is simply stored, exactly as before B13.
    """
    from . import toolfetch

    spec = toolfetch.TOOL_MANIFEST.get("balrogg")
    if spec is None:
        return None
    return toolfetch.installed_path(spec)


def available() -> bool:
    """Is balrogg present *and* still the bytes E1 pinned?"""
    return _balrogg_exe() is not None


def looks_like(head: bytes) -> bool:
    return len(head) >= len(OGG_MAGIC) and head[:len(OGG_MAGIC)] == OGG_MAGIC


def _argv(exe: Path, effort: int, mode: str, src: Path, dst: Path) -> list[str]:
    """The command line. A function of its own so tests can swap the tool for
    a script and exercise cancel, timeout and the verification gate without
    waiting on a real multi-minute encode."""
    if mode == "e":
        return [str(exe), f"-{effort}", "e", str(src), str(dst)]
    return [str(exe), "d", str(src), str(dst)]


def _encode_budget(size: int, effort: int) -> float:
    """Seconds an encode may take before it is killed and the file stored.

    Measured 2026-10-06 with the machine contended (a WSL VM was using ~2.7 of
    4 logical cores): 36.3 MB at ``-9`` took 306 s, 8.4 s/MB. The budget is
    ``120 + (3 + 3*effort) s/MB``, which is 30 s/MB at ``-9`` and so clears the
    worst measured case by 3.5x. It is a backstop against a hang, not a
    deadline anyone should meet: the file is stored if it is ever reached.
    """
    return 120.0 + (size / 1e6) * (3.0 + 3.0 * effort)


def _decode_budget(size: int) -> float:
    """Decoding measured 0.7 s/MB contended; this allows ten times that."""
    return 120.0 + (size / 1e6) * 8.0


def _run(argv: list[str], budget: float, cancel: threading.Event | None,
         watch: tuple[Path, int] | None = None) -> int | None:
    """Run the tool; its exit code, or ``None`` if it outlived ``budget``.

    Raises :class:`StageError` ``"balrogg: cancelled"`` the way ``run_tool``
    does. ``watch`` is ``(output_path, limit)``: the process is killed and
    ``None`` returned the moment the output file passes ``limit`` bytes, so a
    hostile archive cannot make a decode fill the disk.
    """
    if cancel is not None and cancel.is_set():
        raise StageError("balrogg: cancelled")
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)
    deadline = time.monotonic() + budget
    try:
        while True:
            try:
                return proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise StageError("balrogg: cancelled")
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                return None
            if watch is not None:
                try:
                    if watch[0].stat().st_size > watch[1]:
                        proc.kill()
                        proc.wait()
                        return None
                except OSError:
                    pass
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise


def pack(raw: bytes, ctx: object = None, effort: int | None = None,
         cancel: threading.Event | None = None) -> bytes | None:
    """Recompress an Ogg file, verify the round trip, and return the bytes.

    ``None`` means "store this raw", which is always a correct answer: no
    caller has to tell "balrogg is missing" from "balrogg refused this file"
    from "balrogg produced something that did not restore" from "it ran out
    of time".

    The immediate decode-and-compare is the point, not a belt-and-braces
    extra. Paying for the round trip here means a file balrogg would mishandle
    is caught while storing it raw is still free, rather than at restore time
    when D9 would refuse to publish the whole archive.
    """
    if cancel is None and ctx is not None:
        cancel = getattr(ctx, "cancel", None)
    if not (MIN_SIZE <= len(raw) <= MAX_SIZE) or not looks_like(raw[:4]):
        return None
    exe = _balrogg_exe()
    if exe is None:
        return None
    if cancel is not None and cancel.is_set():
        raise StageError("balrogg: cancelled")
    level = effort if effort is not None else DEFAULT_EFFORT

    work = Path(tempfile.mkdtemp(prefix="excmp-blr-"))
    try:
        src = work / "in.ogg"
        src.write_bytes(raw)
        packed_path = work / "out.blr"
        code = _run(_argv(exe, level, "e", src, packed_path),
                    _encode_budget(len(raw), level), cancel)
        if code != 0 or not packed_path.is_file():
            return None
        packed = packed_path.read_bytes()
        # Never ship a "win" that is not one. The store route is free.
        if len(packed) >= len(raw):
            return None

        back = work / "back.ogg"
        code = _run(_argv(exe, level, "d", packed_path, back),
                    _decode_budget(len(packed)), cancel,
                    watch=(back, len(raw)))
        if code != 0 or not back.is_file():
            return None
        if back.read_bytes() != raw:
            return None
        return packed
    except OSError:
        return None
    finally:
        rmtree_force(work)


def unpack(packed: bytes, ctx: object = None, limit: int | None = None,
           cancel: threading.Event | None = None) -> bytes:
    """Restore an Ogg file from :func:`pack`'s output.

    Raises :class:`RuntimeError` on failure. Unlike ``pack`` there is no
    fallback: the ledger says this entry is balrogg's, so being unable to
    decode it is a genuine restore failure and must be loud.

    ``limit`` is the size the ledger declares for the file. A decode that grows
    past it is killed rather than allowed to fill the disk: the archive is
    attacker-supplied data and balrogg's output size is not bounded by its
    input size.
    """
    if cancel is None and ctx is not None:
        cancel = getattr(ctx, "cancel", None)
    exe = _balrogg_exe()
    if exe is None:
        raise RuntimeError(
            "this archive holds Ogg audio packed with balrogg and the pinned "
            "balrogg binary is not installed - fetch it to restore these files")

    work = Path(tempfile.mkdtemp(prefix="excmp-blr-"))
    try:
        src = work / "in.blr"
        src.write_bytes(packed)
        out = work / "out.ogg"
        watch = (out, limit) if limit is not None else None
        code = _run(_argv(exe, 0, "d", src, out), _decode_budget(len(packed)),
                    cancel, watch=watch)
        if code is None:
            raise RuntimeError("balrogg did not finish decoding this entry "
                               "within its time or size limit")
        if code != 0:
            raise RuntimeError("balrogg could not decode this entry")
        if not out.is_file():
            raise RuntimeError("balrogg produced no output for this entry")
        return out.read_bytes()
    finally:
        rmtree_force(work)
