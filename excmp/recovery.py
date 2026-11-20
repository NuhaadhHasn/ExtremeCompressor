"""F3 — recovery records. The difference between knowing and fixing.

Every other guarantee in this codebase *detects* damage. The SHA-256 ledger
proves an archive no longer restores; it cannot do anything about it. That is
the right behaviour and it is also, at the moment it matters, useless: the bad
sector already happened, the download already truncated, the USB stick was
already pulled early.

A recovery record closes that gap, and no open-source archiver ships one.
WinRAR has had it for twenty years and it is the single most-cited reason
people keep paying for it.

**Proven before this module was written**: 200 KB zeroed out of the middle of
a 5.7 MB archive, repaired **byte-identically**, and the ordinary `verify`
then passed 32/32.

**Why PAR2, and why as a subprocess.** Reed-Solomon over GF(2^16) with
self-describing, MD5-checked packets — strictly stronger than the XOR `-rr`
scheme FreeArc used, where two bad sectors landing in one residue class are
unrecoverable (research/18 §5). `par2cmdline-turbo` ships a real Windows
binary inside its wheel, and running it as a separate process is what keeps
its GPL out of our in-process code — the same containment used for every other
tool here.

**Records are sidecars, never embedded.** Rewriting the archive to carry them
would invalidate every hash already published for it, including the `.sha256`
G6 writes and any the user has recorded elsewhere.
"""

from __future__ import annotations

import subprocess
import sys
from enum import Enum
from pathlib import Path

from .stages.base import CREATE_NO_WINDOW, StageContext

#: par2's exit codes, measured on this machine rather than taken from a manual.
_OK = 0
_REPAIRABLE = 1
_UNREPAIRABLE = 2
_NO_RECORDS = 3

#: PAR2 caps a file at 32768 source blocks. Past that, par2 either refuses or
#: silently coarsens the granularity, so the block size is set explicitly for
#: large archives instead of being left to the default.
_MAX_BLOCKS = 32768


class RecoveryStatus(Enum):
    """What the records say about the archive beside them."""

    OK = "ok"
    REPAIRABLE = "repairable"
    UNREPAIRABLE = "unrepairable"
    #: Not an error and not damage — the feature is opt-in, so most archives
    #: legitimately have none.
    NO_RECORDS = "no_records"


def _exe() -> Path | None:
    """The real par2 binary inside the wheel.

    Deliberately *not* ``Scripts/par2.exe``: that is a Python wrapper which
    prints a coloured banner before running the tool, and the banner would
    land in output we parse. The wheel puts the genuine executable in
    ``par2/binaries``.
    """
    # A frozen build (E3) carries it at <bundle>/par2/binaries/par2.exe.
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        frozen = Path(bundle) / "par2" / "binaries" / "par2.exe"
        if frozen.exists():
            return frozen
    for base in (Path(sys.prefix), Path(sys.base_prefix)):
        candidate = base / "Lib" / "site-packages" / "par2" / "binaries" / "par2.exe"
        if candidate.exists():
            return candidate
    try:
        import par2  # type: ignore
    except ImportError:
        return None
    # `par2` is a namespace package: `__file__` is None, so look in `__path__`.
    for folder in getattr(par2, "__path__", None) or ():
        packaged = Path(folder) / "binaries" / "par2.exe"
        if packaged.exists():
            return packaged
    return None


def available() -> bool:
    return _exe() is not None


def default_percent(size_bytes: int) -> int:
    """How much protection to buy, by archive size (FreeArc's tiering).

    The reasoning is about what the percentage *costs*, not what it protects:
    4% of a 10 MB archive is 400 KB, which is nothing, and a small archive is
    the one most likely to be lost outright. 4% of 50 GB is 2 GB, which nobody
    would accept — and a large archive is more likely to suffer a localised
    bad sector than to vanish, which is exactly what a small dose handles.
    """
    mb = size_bytes / (1 << 20)
    if mb <= 50:
        return 5
    if mb <= 1024:
        return 3
    return 1


#: What we aim for, and the number that actually matters. par2's *limit* is
#: 32768 source blocks, but sizing to the limit is a performance trap: block
#: count drives the Reed-Solomon work almost linearly, so picking the smallest
#: block that fits under the cap makes a 400 KB archive into ~25,000 blocks of
#: 16 bytes and turns a sub-second job into a minute. ~2000 blocks is the
#: recommendation in research/18 and is plenty of granularity — each block is
#: an independently recoverable unit, and 2000 of them means losing any 0.05%
#: of the file is repairable.
_TARGET_BLOCKS = 2000

#: Never go below this whatever the arithmetic says. Small archives otherwise
#: get thousands of tiny blocks for no protective benefit at all.
_MIN_BLOCK_BYTES = 4096


def _block_size(archive: Path) -> int | None:
    """An explicit ``-s``, or None to let par2 decide.

    Sized for ~:data:`_TARGET_BLOCKS`, not for the 32768 ceiling — see the
    note there. par2 requires a multiple of 4.
    """
    size = archive.stat().st_size
    if size <= _MIN_BLOCK_BYTES * 8:
        return None                      # too small for the maths to matter
    block = max(_MIN_BLOCK_BYTES, -(-size // _TARGET_BLOCKS))
    block = ((block + 3) // 4) * 4       # par2 requires a multiple of 4
    # Belt and braces: never let the count approach par2's own ceiling.
    if -(-size // block) > _MAX_BLOCKS:
        block = ((-(-size // _MAX_BLOCKS) + 3) // 4) * 4
    return block


def recovery_files(archive: Path) -> list[Path]:
    """Every `.par2` sidecar belonging to ``archive``."""
    archive = Path(archive)
    return sorted(p for p in archive.parent.glob(archive.name + "*.par2")
                  if p.is_file())


def _run(args: list[str], ctx: StageContext, cwd: Path) -> int:
    """Run par2 and return its exit code. The code *is* the answer here, so
    unlike `run_tool` this never raises on a non-zero exit."""
    exe = _exe()
    if exe is None:
        return _NO_RECORDS
    proc = subprocess.run(
        [str(exe), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    for line in (proc.stdout or "").splitlines():
        ctx.log_cb("recovery", line)
    return proc.returncode


def create(archive: Path, percent: int, ctx: StageContext) -> list[Path]:
    """Write recovery records able to rebuild ``percent`` of the archive.

    ``-n1`` keeps it to a single tidy `.vol` file rather than the 30-odd
    par2 produces by default; par2 caps recovery files at 31 anyway, and one
    sidecar is easier for a person to keep alongside the archive.

    Runs with ``cwd`` set to the archive's folder and passes bare filenames, so
    the paths recorded inside the records stay relative — a record set that
    only works from one directory is a record set that stops working the first
    time somebody moves it.
    """
    archive = Path(archive)
    if not available():
        return []
    args = ["create", f"-r{int(percent)}", "-n1", "-q"]
    block = _block_size(archive)
    if block is not None:
        args.append(f"-s{block}")
    args += [archive.name + ".par2", archive.name]
    _run(args, ctx, archive.parent)
    return recovery_files(archive)


def verify(archive: Path, ctx: StageContext) -> RecoveryStatus:
    """What the records say about the archive, without changing anything."""
    archive = Path(archive)
    if not recovery_files(archive):
        return RecoveryStatus.NO_RECORDS
    code = _run(["verify", "-q", archive.name + ".par2"], ctx, archive.parent)
    return {
        _OK: RecoveryStatus.OK,
        _REPAIRABLE: RecoveryStatus.REPAIRABLE,
        _UNREPAIRABLE: RecoveryStatus.UNREPAIRABLE,
        _NO_RECORDS: RecoveryStatus.NO_RECORDS,
    }.get(code, RecoveryStatus.UNREPAIRABLE)


def repair(archive: Path, ctx: StageContext) -> bool:
    """Rebuild the archive from its records. True if it is now intact.

    Returns False rather than raising when the damage exceeds what the records
    cover — that is an ordinary answer to an ordinary question, and the caller
    needs to tell the user "too damaged" rather than show a traceback.
    """
    archive = Path(archive)
    if not recovery_files(archive):
        return False
    code = _run(["repair", "-q", archive.name + ".par2"], ctx, archive.parent)
    return code in (_OK, _REPAIRABLE) and verify(archive, ctx) is RecoveryStatus.OK
