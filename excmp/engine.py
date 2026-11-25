"""The engine: analyze -> plan -> run stage chain -> package -> verify.

Guarantees:
- inputs are never touched; outputs are written to ``<out>.tmp`` and
  atomically renamed only after the archive has been FULLY restored in temp
  and every ledger hash verified (``_verify_before_publish`` - the same
  ``extract()`` path users run, because tool exit codes cannot be trusted);
- every original file's SHA-256 is recorded in the manifest, and
  ``extract`` re-checks the ledger before reporting success.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import jpeg
# Imported as a module as well as by name: `write_container` reads the cap from
# the module global, so the compress-side preflight has to read the same one or
# the two can disagree about what is writable.
from . import manifest as _manifest
from .analyzer import (Category, FileInfo, analyze_tree, analyze_tree_safe,
                       describe_unreadable, iter_empty_dirs)
from .atomic import atomic_write_text, publish
from .estimate import estimate_size
from .manifest import (MANIFEST_NAME, ContainerError, Manifest, StageRecord,
                       _read_manifest, declared_total, extract_stored,
                       manifest_size_estimate, read_container, write_container)
from .planner import (_NO_ROOM, Plan, Profile, _probe_pipes, plan as make_plan,
                      precomp_inflation, store_reason)
from .tempclean import rmtree_force
from .safepath import UnsafePathError, resolve_within, safe_relpath
from .slt import classify_failure
from .stages.base import QuietSkip, Stage, StageContext, StageError, StageSkip
from .stages.dedup import DedupStage
from .stages.sevenzip import SevenZipStage
from .stages.tarstage import TarStage
from .stages.zstdstage import FAST_ZSTD_LEVEL, ZstdStage
from .tools import ToolInfo, find_tools
from .verify import (SourceCheck, hash_file, tree_hash, verify_restore,
                     verify_source)

# Stages that can consume a directory tree directly (anything else forces a
# leading tar stage so the chain operates on one file).
_TREE_CAPABLE = {"sevenzip", "zstd"}

_PAYLOAD_EXT = {"sevenzip": ".7z", "zstd": ".tar.zst", "tar": ".tar",
                "precomp": ".pcf", "srep": ".srep", "zpaqfranz": ".zpaq",
                "dedup": ".dd"}

#: B31: the long-range dedup stage is not planned, it is *offered*. The
#: planner's chain stays ``precomp -> sevenzip`` (the estimator, calibration
#: and the GUI all key on that), and the engine puts ``dedup`` in front of
#: 7-Zip on a Precomp chain. The stage then skips itself unless the stream is
#: larger than 7-Zip's dictionary and holds repeats beyond its reach, so an
#: archive records a dedup stage only when one really ran.
#:
#: Not before zpaqfranz: Insane's codec dedups at any distance itself.
_DEDUP_BEFORE = "sevenzip"


def _with_dedup(chain: list[str]) -> list[str]:
    """``chain`` with the dedup stage offered before a final 7-Zip, on a
    chain that has Precomp (Extreme, as resolved on this machine)."""
    if ("precomp" in chain and chain[-1] == _DEDUP_BEFORE
            and "dedup" not in chain):
        return [*chain[:-1], "dedup", chain[-1]]
    return list(chain)


# A restored stage output beyond this multiple of the declared total is a
# runaway. Deliberately loose: Precomp legitimately inflates 2-5x mid-pipeline
# (research/10 section C-3), so this is a "1 MB archive cannot become 500 GB"
# backstop, not a precise bound.
_STAGE_INFLATION_LIMIT = 8
_STAGE_FLOOR_BYTES = 64 << 20

# Precomp legitimately inflates its output 2-5x mid-pipeline (research/10 C-3),
# which is why temp space - not the output path - is what actually runs out.
_PRECOMP_INFLATION = 5


def _tree_size(path: Path) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _check_free_space(out_dir: Path, ledger: dict[str, dict]) -> None:
    """Fail before doing work, not half way through writing the user's disk
    full. Precomp inflates mid-pipeline, so the margin is on top of the total."""
    need = int(declared_total(ledger) * 1.05)
    free = shutil.disk_usage(out_dir).free
    if free < need:
        raise RuntimeError(
            f"not enough free space in {out_dir}: this archive restores to about "
            f"{need >> 20} MiB but only {free >> 20} MiB is available")


def _free_bytes(path: Path) -> tuple[int, int] | None:
    """``(free_bytes, volume_id)`` for the volume holding ``path``.

    Walks up to the nearest existing ancestor, because the output folder may not
    exist yet. Returns None when nothing on the path exists - an unknown volume
    is not grounds for refusing a job.
    """
    for candidate in [path, *path.parents]:
        if not candidate.exists():
            continue
        try:
            return shutil.disk_usage(candidate).free, candidate.stat().st_dev
        except OSError:
            return None
    return None


def compress_space_needs(out_path: Path, temp_dir: Path, infos: list[FileInfo],
                         the_plan: Plan) -> list[tuple[Path, int, int]]:
    """What compressing this will need, as ``(probe_path, floor, peak)`` per volume.

    ``floor`` is what the job cannot possibly run without; ``peak`` adds Precomp's
    worst-case mid-pipeline inflation. Requirements are grouped by volume because
    the temp folder and the output folder are usually the same disk, and then they
    compete for the same free bytes.

    Public so the GUI can show the number before the user commits, and so the
    arithmetic is testable without filling a disk.
    """
    size = estimate_size(infos, the_plan)
    piped = size.piped_bytes
    total = size.stored_bytes + size.piped_bytes
    stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])
    # B3: the multiplier is per data type, not a flat 5x. A PNG folder inflates
    # ~50x through Precomp (deflate all the way down, so expanding it yields
    # raw pixels), and reserving 5x for one would under-book temp by an order
    # of magnitude - which is the exact failure this preflight exists to catch.
    piped_infos = next(
        (set(r.files) for r in the_plan.routes if r.action == "pipeline"), set())
    inflation = (precomp_inflation([i for i in infos if i.path in piped_infos])
                 if "precomp" in stages else 1)

    # Output: the .tmp twin, which is the whole archive. Use the pessimistic end
    # of the estimate - being wrong here means a disk-full failure late in a long
    # job, which is the outcome this function exists to prevent.
    # Temp: the staging copy of the piped files lives until the chain finishes,
    # the tar that feeds the chain lives beside it, and Precomp's output lands
    # on top of both. Then the pre-publish self-test (D9) restores the ENTIRE
    # archive into temp - stored files included - so every job needs the full
    # input size there again, even a store-only one.
    needs: dict[int, tuple[Path, int, int]] = {}
    for probe, floor, peak in (
        (out_path.parent, size.high, size.high),
        (temp_dir, piped * 2 + total,
         (piped * (2 + inflation) if piped else 0) + total),
    ):
        found = _free_bytes(probe)
        if found is None:
            continue
        _free, volume = found
        if volume in needs:
            first, prev_floor, prev_peak = needs[volume]
            needs[volume] = (first, prev_floor + floor, prev_peak + peak)
        else:
            needs[volume] = (probe, floor, peak)
    return list(needs.values())


def _check_compress_space(out_path: Path, temp_dir: Path, infos: list[FileInfo],
                          the_plan: Plan) -> list[str]:
    """Refuse impossible jobs, warn about tight ones. Returns the warnings.

    Extraction can hard-fail on an exact figure - the manifest declares every
    size. Compression cannot: the output size is an estimate and Precomp's
    inflation is data-dependent. Two thresholds keep that honest. A preflight
    that refuses jobs which would have succeeded gets switched off, and then it
    protects nobody.
    """
    warnings: list[str] = []
    for probe, floor, peak in compress_space_needs(out_path, temp_dir, infos, the_plan):
        found = _free_bytes(probe)
        if found is None:
            continue
        free, _volume = found
        if free < floor:
            raise RuntimeError(
                f"not enough free space on the volume holding {probe}: this job "
                f"needs at least {floor >> 20} MiB (archive plus a staging copy) "
                f"but only {free >> 20} MiB is available")
        if free < peak:
            warnings.append(
                f"free space on {probe} is {free >> 20} MiB; this job should fit "
                f"in {floor >> 20} MiB but Precomp can inflate mid-pipeline and "
                f"the worst case is {peak >> 20} MiB - point the temp folder at a "
                f"roomier drive if it fails")
    return warnings


def _plan_that_fits(infos: list[FileInfo], profile: Profile,
                    tools: dict[str, ToolInfo | None], out_path: Path,
                    temp_dir: Path) -> Plan:
    """The plan, checked against free disk space (J4), with one way out (B21b).

    Piping the media the probe flags (MKV, MP4, MOV, M4A... `_PROBE_DECIDES`)
    buys a few percent and doubles their bytes in temp. On the owner's laptop
    that took a 2 GB video folder's floor from 3.85 to 6.97 GiB, and a job
    that storing them had always fitted was refused outright. So when the
    plan doesn't fit, the same files with that media stored are tried; if
    they fit, the job runs and says what it stored. Lossless either way.
    If neither fits, the refusal is the chosen plan's own (review: the lean
    plan stores more, so on a separate output volume its floor can be the
    larger one, and name a volume the job never needed).
    """
    the_plan = make_plan(infos, profile, tools)
    try:
        the_plan.warnings.extend(
            _check_compress_space(out_path, temp_dir, infos, the_plan))
        return the_plan
    except RuntimeError as refusal:
        lean = make_plan(infos, profile, tools, probe_media=False)

        def piped(p: Plan) -> set[Path]:
            return {f for r in p.routes if r.action == "pipeline" for f in r.files}

        moved = piped(the_plan) - piped(lean)
        if not moved:
            raise
        try:
            lean.warnings.extend(
                _check_compress_space(out_path, temp_dir, infos, lean))
        except RuntimeError:
            raise refusal from None
    # The floor counts piped bytes twice (staging plus the tar), so the gap is
    # about twice the files' size on real video: quote the gap itself.
    gap = sum(f for _, f, _ in compress_space_needs(out_path, temp_dir, infos, the_plan)) \
        - sum(f for _, f, _ in compress_space_needs(out_path, temp_dir, infos, lean))
    size = sum(i.size for i in infos if i.path in moved)
    lean.warnings.insert(0, (
        f"not enough free disk space to also recompress {len(moved)} "
        f"video/audio file(s) ({size >> 20} MiB, which would have shrunk a few "
        f"percent): they were stored as-is, losslessly. Free about "
        f"{max(gap, 0) >> 20} MiB more to have them recompressed"))
    return lean


def _check_manifest_size(relmap: dict[Path, str], the_plan: Plan,
                         empty_dirs: list[str] | None = None) -> list[str]:
    """K1: refuse a selection whose manifest we could not read back.

    The cap exists because `manifest.json` is parsed before anything in it can
    be validated. It was only ever enforced on the *read* side, which put the
    refusal at the bottom of `_verify_before_publish` -> `verify_archive` ->
    `extract` -> `read_container` - i.e. after the whole archive had been
    built. A user with a `node_modules` tree waited out a full compress and
    then lost it.

    Nothing about that was the user's mistake, so the message names the count
    and points at the way out. Two thresholds, matching
    `_check_compress_space`: warn when the manifest is close enough that a
    growing folder will hit the wall, refuse when it is already through it.
    """
    cap = _manifest.MAX_MANIFEST_BYTES
    stored = sum(len(r.files) for r in the_plan.routes if r.action == "store")
    projected = manifest_size_estimate(relmap.values(), stored_count=stored,
                                       dirs=empty_dirs or ())
    if projected > cap:
        # Name whichever list is actually the problem. Saying "N file(s),
        # whose names and hashes" is simply false for a selection of 300 files
        # and 200,000 empty directories, and it sends the user off to split a
        # folder that was never the cause.
        n_dirs = len(empty_dirs or ())
        what = f"{len(relmap):,} file(s), whose names and hashes"
        if n_dirs > len(relmap):
            what = (f"{len(relmap):,} file(s) and {n_dirs:,} empty "
                    f"director{'y' if n_dirs == 1 else 'ies'}, whose names")
        raise RuntimeError(
            f"this selection has {what} need about "
            f"{projected / 2**20:.1f} MiB of manifest - past "
            f"the {cap / 2**20:.1f} MiB an archive may carry. Archive the "
            f"subfolders separately.")
    if projected > cap * 4 // 5:
        return [f"the manifest for these {len(relmap):,} file(s) will be about "
                f"{projected / 2**20:.1f} MiB, near the {cap / 2**20:.1f} MiB "
                f"ceiling - a much larger selection would be refused"]
    return []


def _relabel(reason: str, path: Path, rel: str) -> str:
    """Swap a basename-only skip sentence for one naming the relative path.

    `analyze_tree_safe` builds the sentence (it has the exception), but only
    `_collect` knows the archive-relative name, and a sentence saying just
    "index.js" identifies nothing in a tree with hundreds of them.
    """
    if rel and reason.startswith(path.name + ":"):
        return rel + reason[len(path.name):]
    return reason


#: Errnos from a staging copy that are about the **volume**, not the file, and
#: must therefore abort rather than be skipped past (D4).
#:
#: `ENOSPC` is the one that was measured: a full destination turned into "they
#: may be open in another program", which sends the user to close programs
#: that are not the problem. `EDQUOT` is the same condition behind a quota and
#: `EFBIG`/`EROFS` are equally unfixable by moving to the next file. Anything
#: not listed here keeps K3's graceful per-file skip, which exists because one
#: locked file used to destroy an entire job.
_FATAL_COPY_ERRNOS = frozenset({
    errno.ENOSPC,      # no space left on device
    errno.EDQUOT,      # over the disk quota
    errno.EFBIG,       # file too large for the filesystem
    errno.EROFS,       # read-only filesystem
})


def _nothing_readable(skipped: list[str]) -> str:
    """K3: "nothing to compress" reads as "the folder was empty", which is the
    one thing it was not when every file in it was locked."""
    if not skipped:
        return "nothing to compress"
    return (f"none of the {len(skipped)} file(s) selected could be read - they "
            f"may be open in another program. " + "; ".join(skipped[:3]))


def _restore_empty_dirs(out_dir: Path, dirs: object) -> int:
    """Recreate K2's wholly-empty directories under ``out_dir``.

    ``dirs`` comes out of the archive, so it is exactly as untrusted as a
    ledger key or a payload name and goes through the same validator - a
    `mkdir` is a filesystem write and `../../` would land it anywhere the user
    can write. `resolve_within` raises rather than mangling, which is the D0
    rule.

    **The shape is checked before the contents.** `Manifest.from_json` does
    `cls(**data)` with no coercion, so this field is whatever JSON held: a
    dict iterates its *keys* and created directories named after them, and a
    bare string iterates characters and created ``a/``, ``b/``, ``c/``.
    safepath still held - nothing escaped `out_dir` - but those were
    archive-controlled filesystem writes with names that had never been in any
    archive.

    **And it cannot fail the restore.** This runs at the very end of
    `extract`, after `extract_stored`, `verify_restore` and MOTW propagation,
    so an unguarded `mkdir` meant an OSError here reported a restore whose
    every byte had verified byte-identical as a *failure* - the CLI printing
    `error:` and exiting 1, the GUI painting the tab red. It did not even need
    a hostile archive: a destination that already holds a file where a parent
    of an empty chain must go is enough. An empty directory is cosmetic in
    precisely the way `_apply_mtimes` documents a timestamp to be, so it gets
    the same policy - try, count what worked, and never undo a good restore.
    """
    if not isinstance(dirs, (list, tuple)):
        return 0
    made = 0
    for rel in dirs:
        if not isinstance(rel, str):
            continue
        try:
            target = resolve_within(out_dir, rel)
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                made += 1
        except (OSError, UnsafePathError):
            continue
    return made


def _apply_mtimes(out_dir: Path, ledger: dict[str, dict]) -> int:
    """Stamp every restored file with the mtime its ledger entry records (K2).

    Done in one pass here rather than inside `extract_stored` and the tar
    stage, for two reasons that are both about correctness rather than tidiness:

    * The two routes used to disagree - tar carried an mtime, the stored route
      set nothing - and the disagreement was invisible because each half looked
      reasonable alone. One pass over the ledger makes them agree by
      construction.
    * It has to run **after** F4's Mark-of-the-Web propagation. Writing a
      Zone.Identifier alternate data stream updates the host file's last-write
      time on NTFS, so a mtime applied before propagation is overwritten by it.

    An entry with no ``mtime_ns`` is skipped, not defaulted: every archive
    written before K2 has none, and inventing a timestamp for those would be
    worse than leaving the restore-time one alone. Failures are ignored for the
    same reason the zone marker's are - a file whose bytes verified is a
    successful restore, and a timestamp we could not set does not undo that.
    """
    stamped = 0
    for rel, meta in ledger.items():
        ns = meta.get("mtime_ns")
        # `type(ns) is int` rather than isinstance: `True` is an int in
        # Python, so `"mtime_ns": true` passed an isinstance guard and stamped
        # the file to 1 nanosecond after the epoch. A bool is not a timestamp.
        #
        # The upper bound is not decoration either. This value is
        # archive-supplied, and `os.utime(ns=...)` raises **OverflowError**
        # past `time_t` - an ArithmeticError, not an OSError, so the handler
        # below did not catch it and a crafted manifest aborted `extract` with
        # a raw traceback *after* the restore had completed and verified.
        if type(ns) is not int or not 0 < ns < 2 ** 63:
            continue
        try:
            target = resolve_within(out_dir, rel)
            os.utime(target, ns=(ns, ns))
            stamped += 1
        except (OSError, OverflowError, ValueError, UnsafePathError):
            continue
    return stamped


def _wait_if_paused(ctx: StageContext) -> None:
    """Block while the caller holds ``ctx.pause``. Called only at stage
    boundaries: a half-finished tool cannot be suspended safely, so pausing
    means "let this stage finish, then wait". Cancel always wins."""
    while ctx.pause.is_set() and not ctx.cancel.is_set():
        time.sleep(0.1)


@dataclass(frozen=True)
class StageOptions:
    """What the user chose, if anything. All None means "the tool decides".

    Carried explicitly rather than read from settings inside the engine: the
    engine has no idea a GUI exists, and an archive has to be reproducible
    from what the manifest records.
    """

    level: int | None = None
    dict_size: str | None = None          # "256m", as -md= wants it
    extra_args: tuple[str, ...] = ()

    def as_params(self) -> dict:
        """What goes in `StageRecord.params` - only what was actually set,
        so an archive built with defaults does not claim otherwise."""
        out: dict = {}
        if self.level is not None:
            out["level"] = self.level
        if self.dict_size:
            out["dict"] = self.dict_size
        if self.extra_args:
            out["extra"] = list(self.extra_args)
        return out


#: Fraction of *piped bytes* that must be executable before we force BCJ2.
#: Deliberately low, because the payoff is asymmetric: measured, being right
#: is worth 1.3% and being wrong costs 0.04%.
BCJ2_BYTE_SHARE = 0.25


def _wants_bcj2(infos: "list[FileInfo]") -> bool:
    """Is this job executable-heavy enough for the x86 branch filter? (B7)

    Weighed by **bytes, not file count**: one 50 MB DLL beside a hundred 1 KB
    text files is an executable job, and counting files would call it a text
    job and leave the 1.3% on the table.
    """
    total = sum(i.size for i in infos)
    if not total:
        return False        # an all-stored job pipes nothing to filter
    exe = sum(i.size for i in infos if i.category is Category.EXECUTABLE)
    return exe / total >= BCJ2_BYTE_SHARE


def _stage_factory(options: StageOptions | None = None,
                   bcj2: bool = False) -> dict[str, Stage]:
    opts = options or StageOptions()
    seven = (SevenZipStage(level=opts.level if opts.level is not None else 9,
                           dict_size=opts.dict_size,
                           extra_args=list(opts.extra_args), bcj2=bcj2)
             if (opts.level is not None or opts.dict_size or opts.extra_args
                 or bcj2)
             else SevenZipStage())
    zstd = ZstdStage(level=opts.level if opts.level is not None else FAST_ZSTD_LEVEL)
    registry: dict[str, Stage] = {
        "tar": TarStage(),
        "zstd": zstd,
        "sevenzip": seven,
        # B31. Pure Python, so always here: an archive that recorded a dedup
        # stage extracts on any machine. Its window is the dictionary 7-Zip
        # will really run with, because that is the reach it makes up for.
        "dedup": DedupStage(window=seven.dict_bytes()),
    }
    try:  # optional stages, present once task 9 lands / tools installed
        from .stages.precomp import PrecompStage
        from .stages.srep import SrepStage
        from .stages.zpaqfranz import ZpaqfranzStage
        registry["precomp"] = PrecompStage()
        registry["srep"] = SrepStage()
        registry["zpaqfranz"] = ZpaqfranzStage()
    except ImportError:
        pass
    return registry


@dataclass
class CompressResult:
    archive: Path
    orig_bytes: int
    final_bytes: int
    routes: list[dict]
    warnings: list[str]
    elapsed_s: float
    # Path to the `.sha256` written beside the archive, or None. Opt-in: a
    # second file nobody asked for beside every archive is exactly the kind of
    # surprise output this engine has refused since its first commit.
    sidecar: Path | None = None
    #: Original bytes that actually went through the codec chain, as opposed to
    #: the stored bucket. This is the only figure J7's self-calibration may
    #: learn from - a store-only job is disk-bound and says nothing about how
    #: fast a codec runs. Reported here because the engine has the ledger in
    #: hand and knows it exactly; the GUI used to reconstruct it by stat-ing
    #: archive-relative paths against its own working directory, which never
    #: worked (K1).
    piped_bytes: int = 0
    #: K3: one sentence per file that could not be read and was left out.
    #:
    #: Not a log and not a warning subset - it is part of the result, because
    #: a file the user believes is backed up and is not is the worst outcome
    #: this program can produce. `warnings` carries a summary line for the
    #: places that only surface warnings; this carries the names.
    skipped: list[str] = field(default_factory=list)
    #: D8: SHA-256 of the archive as it exists at `archive`, read back off the
    #: filesystem after the flush and before the rename.
    #:
    #: Not a convenience field. It is the one number that ties the file the
    #: user now has to the artifact the D9 gate accepted, and because the
    #: publish has to read the bytes back anyway it costs nothing to report.
    #: Empty only for results built by something other than `compress()`.
    sha256: str = ""

    @property
    def ratio(self) -> float:
        return self.final_bytes / self.orig_bytes if self.orig_bytes else 1.0


@dataclass
class ExtractResult:
    out_dir: Path
    files_restored: int
    verified: int
    elapsed_s: float
    # False for archives we did not create. There is no SHA-256 ledger in a
    # foreign zip, so `verified == 0` there means "nothing to check against",
    # NOT "checked and found zero good". The UI must not render the two the
    # same way - the verified restore is the one guarantee this project sells.
    ledger_backed: bool = True


class EncryptedArchiveError(ContainerError):
    """This archive needs a password we do not have (or were given a wrong one).

    A **subclass** of ContainerError on purpose: every existing
    ``except ContainerError`` keeps behaving exactly as it did, while the
    surfaces that can actually do something about it - the Extract tab, the
    CLI - catch the narrower type and ask. "Needs a password" and "this file
    is damaged" send a user to completely different places, so collapsing
    them into one error would make the prompt impossible to write.
    """


@dataclass
class ArchiveEntry:
    """One file inside an archive.

    Two dialects share this shape. Ours fills ``sha256``, ``route`` and
    ``reason`` from the manifest. A foreign archive fills ``crc`` and leaves
    ``sha256`` **empty**, because 7-Zip reports a CRC-32 and a 32-bit error
    check is not this project's integrity guarantee. They are separate fields
    all the way to the screen so that no surface can print one under the
    other's name - the same mistake as the "0 SHA-256 hashes verified"
    wording that shipped once already.
    """

    name: str
    size: int
    sha256: str
    route: str      # "pipeline" | "store"; empty for foreign archives
    reason: str     # why it was stored; empty for pipelined and foreign files
    # --- foreign archives only ------------------------------------------
    crc: str = ""             # CRC-32 as 7-Zip printed it. NOT a SHA-256.
    # None = 7-Zip printed nothing (every solid-block member after the
    # first). Not the same fact as zero bytes, so not the same value.
    packed_size: int | None = None
    modified: str = ""
    encrypted: bool = False
    is_dir: bool = False


@dataclass
class ArchiveListing:
    archive: Path
    kind: str                 # "excmp", or 7-Zip's own type: zip/7z/rar5/iso…
    profile: str
    created_utc: str
    stages: list[str]
    entries: list[ArchiveEntry]
    # False for archives we did not create. There is no SHA-256 ledger in a
    # foreign zip, so an empty `sha256` there means "there was never anything
    # to compare against", NOT "we looked and found nothing". Same companion
    # flag, same reason, as ExtractResult.ledger_backed.
    ledger_backed: bool = True
    # The row cap stopped us before the archive did, so `entries` is a
    # prefix. A truncated listing renders exactly like a complete one, which
    # is why this has to travel with it rather than be inferred.
    truncated: bool = False
    # Some or all of the data needs a password to extract, even though the
    # names listed fine (an AES zip lists happily; only its payload is
    # locked).
    encrypted: bool = False
    # The payload is one stream, so reaching any single member decodes
    # everything before it. True for every .excmp with a pipeline route, and
    # for a foreign archive whenever 7-Zip says `Solid = +`.
    solid: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries)

    @property
    def file_count(self) -> int:
        """Directories are archive bookkeeping, not files anyone chose."""
        return sum(1 for e in self.entries if not e.is_dir)


@dataclass
class VerifyResult:
    """The answer to "is this archive still good?".

    ``ok`` is True whenever this object exists at all - a failed verification
    raises - but it is carried explicitly so the CLI's JSON and the GUI's
    result panel can state the verdict without inferring it from an absence.
    """

    archive: Path
    ok: bool
    files_restored: int
    verified: int
    elapsed_s: float
    problem: str = ""
    #: D5. One SHA-256 for the whole restored tree, order-independent, or ""
    #: when the verify was not deep.
    #:
    #: Empty rather than plausible-looking on purpose: a caller comparing a
    #: field that was never computed is a worse failure than a missing one.
    tree_sha256: str = ""
    #: D5's `v -ssd` half: how many originals were re-read, and what re-reading
    #: them found. All zero/empty unless a source root was given.
    source_checked: int = 0
    #: Still present and no longer matching the archive - bit-rot, or an edit.
    source_changed: list[str] = field(default_factory=list)
    #: Gone from the source. Usually not a fault; an archive exists so that
    #: deleting an original is safe.
    source_missing: list[str] = field(default_factory=list)
    #: Present in the source and never in the archive. News, not corruption.
    source_extra: list[str] = field(default_factory=list)


def _collect(inputs: list[Path]) -> tuple[list[FileInfo], dict[Path, str],
                                          list[str], list[str]]:
    """Analyze all inputs; map absolute path -> archive-relative path.

    The third return value is K2's list of archive-relative directories that
    hold nothing at all. They cannot come from ``relmap``, which is keyed on
    files, so they are walked alongside it and travel in the manifest's own
    ``dirs`` field.

    The fourth is K3's list of files that could not be read, already turned
    into sentences. Analysis is where a locked file is first touched, so it is
    where the skip has to be taken - and it is returned rather than logged,
    because a skipped file is part of the job's result and the user has to be
    told which one.
    """
    infos: list[FileInfo] = []
    relmap: dict[Path, str] = {}
    empty_dirs: list[str] = []
    skipped: list[str] = []
    for inp in inputs:
        inp = Path(inp).resolve()
        analyses, unreadable = analyze_tree_safe(inp)
        for bad, reason in unreadable:
            # Relabel with the archive-relative path, computed the same way
            # `rel` is below - `analyze_tree_safe` cannot know it.
            try:
                rel = (bad.name if inp.is_file()
                       else f"{inp.name}/{bad.relative_to(inp).as_posix()}")
            except ValueError:
                rel = bad.name
            skipped.append(_relabel(reason, bad, rel))
        for info in analyses:
            rel = info.path.name if inp.is_file() else f"{inp.name}/{info.path.relative_to(inp).as_posix()}"
            if rel in relmap.values():
                raise ValueError(f"duplicate archive path '{rel}' - rename one of the inputs")
            infos.append(info)
            relmap[info.path] = rel
        # Reuse the walk `analyze_tree_safe` already did, and derive the empty
        # set from the files that were actually *analyzed*. That does two jobs
        # at once.
        #
        # It stops the second full `rglob` over a tree we have just walked -
        # ~20 s of drive metadata latency on the 57,020-file corpus, paid for a
        # list that is usually empty.
        #
        # And it closes a K3/K2 interaction that would otherwise lose a folder:
        # a directory whose *only* file was unreadable is in neither list - not
        # in the ledger, because its file was skipped, and not in `dirs`,
        # because it was not empty when the tree was walked. Keyed on the
        # analyzed files it is empty, which is exactly what the restore can
        # faithfully reproduce, and the user hears about the skipped file
        # instead of silently losing the directory.
        for d in iter_empty_dirs(inp, files=[i.path for i in analyses]):
            empty_dirs.append(f"{inp.name}/{d.relative_to(inp).as_posix()}")
    return infos, relmap, empty_dirs, skipped


def _write_sidecar(archive: Path, digest: str | None = None) -> Path:
    """`<archive>.sha256` in ``sha256sum`` layout (G6).

    The digest describes the file that actually shipped, never the `.tmp` twin
    that existed a moment earlier. It used to guarantee that by re-reading the
    published archive; since D8 the publish itself reads the bytes back off
    the filesystem, so ``digest`` is that same measurement passed in - one
    fewer full pass over a multi-gigabyte file, for the identical number.
    Falling back to a fresh hash keeps the function usable on an archive
    nobody just published.

    The body names the archive by *file name*, not full path: `sha256sum -c`
    resolves relative to the working directory, and an absolute path would
    break the moment the pair is moved - which is the only situation a
    transport sidecar exists for.
    """
    side = Path(str(archive) + ".sha256")
    # atomic_write_text, not write_text: LF endings (`sha256sum -c` reads a
    # trailing CR as part of the filename, which shipped broken until
    # 2026-09-02) and a flushed `.tmp` rename, so an interrupted write cannot
    # leave a truncated digest that would condemn a good archive.
    atomic_write_text(
        side, f"{digest or hash_file(archive)}  {archive.name}\n")
    return side


@dataclass
class StandardResult:
    """What a plain-format export produced, and what it cannot promise."""

    archive: Path
    orig_bytes: int
    final_bytes: int
    elapsed_s: float
    #: Files compared against the original by SHA-256 after a real extract.
    verified: int
    #: Always False here. A standard archive carries no per-file ledger, so
    #: nothing can re-check it later - which is the honest difference from an
    #: `.excmp` and the reason this field exists rather than being implied.
    has_ledger: bool
    #: One sentence for the user about that trade.
    note: str
    #: K3: files that could not be read and are therefore NOT in this archive.
    #:
    #: Added after an audit found that `compress_standard` bound `_collect`'s
    #: skip list and then consumed it only in the "nothing readable at all"
    #: branch - so a partially-locked selection published silently, with the
    #: missing names recorded nowhere. The plain-export path cannot fall back
    #: on a ledger either: there is none, which is the whole point of this
    #: result type, so this list is the only record that a file was left out.
    skipped: list[str] = field(default_factory=list)


def _hash_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hash_file(p)
            for p in Path(root).rglob("*") if p.is_file()}


def _ensure_output_folder(out_path: Path) -> None:
    """Create the folder the archive goes in, if it is missing (found by the user guide: a missing folder
    failed with Python's raw ``[Errno 2] ... a.excmp.tmp``). Called only once there is something to write, so
    a job with no readable input leaves no empty folder behind."""
    folder = Path(out_path).parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"cannot create the output folder {folder}: {exc.strerror or exc}") from None


def compress_standard(inputs: list[Path], out_path: Path, fmt: str,
                      ctx: StageContext,
                      tools: dict[str, ToolInfo | None] | None = None,
                      level: int = 9,
                      password: str | None = None) -> StandardResult:
    """Write a plain `.7z` or `.zip` — one anybody can open (G4).

    The lock-in objection is fair and this is the answer: no container, no
    manifest, just an archive that 7-Zip, Explorer, macOS and `unzip` all
    read.

    **What is given up** is the *later* half of the guarantee. Without a ledger
    there is nothing to re-check against, so `excmp verify` can say nothing
    about this file in six months.

    **What is kept** is the *now* half, and it is not a token: the archive is
    extracted to temp and every file compared against the original by SHA-256
    before it is published. Same rule as the `.excmp` path — if it does not
    restore, no file appears at the destination. So this archive has been
    proven to restore once, on this machine; we simply cannot prove it again.
    """
    if password:
        # Refused rather than ignored, and refused rather than quietly
        # substituting 7-Zip's own encryption.
        #
        # Wrapping the output in our AES-256-GCM container would make it stop
        # being a plain .7z/.zip, which is the only reason this function
        # exists. And 7z -p is what F1 was built to replace: its salt lines
        # are commented out, so identical passwords give identical keys
        # (research/19 section 1). Silently doing either would hand the user
        # an archive whose protection is not what they think it is.
        raise ValueError(
            "a plain .7z/.zip cannot carry our encryption - it would stop "
            "being readable by other tools, which is the whole point of the "
            "format. Use the .excmp format for a password-protected archive, "
            "or write the plain archive without one")
    fmt = str(fmt).lower()
    if fmt not in {"7z", "zip"}:
        raise ValueError(
            f"unsupported format {fmt!r}: choose '7z' or 'zip'. RAR creation "
            f"is not legally possible for any tool but WinRAR")

    t0 = time.monotonic()
    tools = tools if tools is not None else find_tools(with_versions=True)
    out_path = Path(out_path)
    infos, _relmap, _dirs, skipped = _collect([Path(p) for p in inputs])
    if not infos:
        raise ValueError(_nothing_readable(skipped))
    _ensure_output_folder(out_path)
    orig = sum(i.size for i in infos)

    job_dir = Path(tempfile.mkdtemp(prefix="excmp-std-", dir=ctx.temp_dir))
    tmp_out = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        # Stage every input into one tree first.
        #
        # This used to pass `roots[0]` straight to the stage, which takes ONE
        # path - so `compress a.txt b.txt c.txt --format 7z` archived a.txt,
        # discarded the rest, and reported the original size of all three as a
        # 99% saving. Reusing `_collect`'s relmap gives the same
        # archive-relative names the .excmp route uses and rejects duplicates
        # the same way.
        staged = job_dir / "staged"
        staged.mkdir(parents=True, exist_ok=True)
        for info in infos:
            rel = _relmap[info.path]
            target = resolve_within(staged, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(info.path, target)
            except OSError as exc:
                # Same guard the .excmp path has. Without it a mid-job lock is
                # fatal here while `compress` survives it.
                skipped.append(describe_unreadable(info.path, exc))
                target.unlink(missing_ok=True)
                continue

        # Same stage the .excmp route uses - the output path staying last, the
        # password redaction, the progress parsing all come for free. Only the
        # container type differs.
        stage = SevenZipStage(level=level, archive_type=fmt)
        stage.compress(staged, tmp_out, ctx)

        # Prove it restores, right now, the only moment we can.
        check_dir = job_dir / "check"
        stage.extract(tmp_out, check_dir, ctx)
        want = _hash_tree(staged)
        got = _hash_tree(check_dir)
        # Compared as whole sets, not by filename suffix. Suffix matching
        # false-passes a missing file whose name happens to end another's.
        if set(got) != set(want):
            missing = sorted(set(want) - set(got))
            extra = sorted(set(got) - set(want))
            raise StageError(
                f"{fmt} export did not round-trip: "
                f"{len(missing)} missing {missing[:3]}, "
                f"{len(extra)} unexpected {extra[:3]} - refusing to publish it")
        for rel, digest in want.items():
            if got[rel] != digest:
                raise StageError(
                    f"{fmt} export did not restore {rel!r} identically - "
                    f"refusing to publish it")
        verified = len(want)
        # A gate that can pass having checked nothing is not a gate. This is
        # what let the multi-input loss above ship in silence.
        if not verified:
            raise StageError(
                f"{fmt} export verified no files at all - refusing to publish "
                f"an archive nothing has vouched for")

        # D8: flushed, read back and renamed without deleting whatever the
        # user already had at that path. Same publish path as the .excmp
        # route - a plain export is not a lesser output.
        publish(tmp_out, out_path)
        tmp_out = None
    finally:
        if tmp_out is not None:
            Path(tmp_out).unlink(missing_ok=True)
        rmtree_force(job_dir)

    return StandardResult(
        archive=out_path,
        orig_bytes=orig,
        final_bytes=out_path.stat().st_size,
        elapsed_s=time.monotonic() - t0,
        verified=verified,
        has_ledger=False,
        note=("standard %s: any tool can open it, and it was verified by "
              "extracting and hashing every file just now - but it carries no "
              "ledger, so it cannot be re-verified later the way an .excmp can"
              % fmt),
        skipped=skipped,
    )


def compress(inputs: list[Path], out_path: Path, profile: Profile,
             ctx: StageContext, tools: dict[str, ToolInfo | None] | None = None,
             sidecar: bool = False,
             options: "StageOptions | None" = None,
             password: str | None = None,
             keyfile: Path | None = None) -> CompressResult:
    t0 = time.monotonic()
    tools = tools if tools is not None else find_tools(with_versions=True)
    out_path = Path(out_path)
    infos, relmap, empty_dirs, skipped = _collect([Path(p) for p in inputs])
    if not infos:
        raise ValueError(_nothing_readable(skipped))
    _ensure_output_folder(out_path)
    # Before copying a single byte: will this fit? (J4 - the compression-side
    # twin of the check extract() has done since D0.) B21b: if it only fits
    # with the probe-flagged media stored, it runs that way and says so.
    the_plan: Plan = _plan_that_fits(infos, profile, tools, out_path, ctx.temp_dir)
    # ...and will the manifest itself be readable? (K1.)
    the_plan.warnings.extend(
        _check_manifest_size(relmap, the_plan, empty_dirs))

    # B7: the branch filter is decided from what will actually be *piped*,
    # not from the whole input. A folder of installers is mostly stored, and
    # what reaches 7-Zip may look nothing like the folder as a whole.
    _piped = next((r for r in the_plan.routes if r.action == "pipeline"), None)
    _piped_set = set(_piped.files) if _piped else set()
    registry = _stage_factory(
        options, bcj2=_wants_bcj2([i for i in infos if i.path in _piped_set]))
    job_dir = Path(tempfile.mkdtemp(prefix="excmp-", dir=ctx.temp_dir))
    tmp_out: Path | None = None
    # F1: with a password, the container is built and verified inside temp and
    # only the ciphertext is ever written beside the user's output. Building it
    # at `<out>.tmp` as the plaintext path does would leave the complete
    # unencrypted archive sitting in the destination folder for the whole
    # pre-publish restore - which is the one place the user is least likely to
    # expect it, and contradicted the comment beside it.
    stage_dir = job_dir if password else None
    try:
        # --- split routes -------------------------------------------------
        pipe_route = next((r for r in the_plan.routes if r.action == "pipeline"), None)
        store_route = next((r for r in the_plan.routes if r.action == "store"), None)

        ledger: dict[str, dict] = {}
        piped_paths = set(pipe_route.files) if pipe_route else set()
        # K3: a file readable at analysis time can be locked before it is
        # hashed - a real race, not a theoretical one, since the analysis of a
        # large tree takes minutes. Anything dropped here has to leave the
        # route lists too, or the staging copy would still try to read it.
        dropped: set[Path] = set()
        for info in infos:
            route = "pipeline" if info.path in piped_paths else "store"
            try:
                digest = hash_file(info.path)
            except OSError as exc:
                skipped.append(describe_unreadable(info.path, exc,
                                                   label=relmap[info.path]))
                dropped.add(info.path)
                continue
            entry = {
                "size": info.size,
                "sha256": digest,
                "route": route,
                # K2: from the stat the analyzer already did. Applied on the
                # way out by `_apply_mtimes`, for both routes, so the two
                # cannot drift apart again.
                "mtime_ns": info.mtime_ns,
            }
            # B2 (JPEG packing) is decided in `write_container`, not here.
            # Deciding it here meant packing every JPEG once as a predicate,
            # discarding the bytes, and packing it again at write time - and
            # the two calls could disagree, leaving the ledger claiming a
            # codec the bytes did not honour.
            ledger[relmap[info.path]] = entry

        if dropped:
            if pipe_route:
                pipe_route.files = [f for f in pipe_route.files if f not in dropped]
            if store_route:
                store_route.files = [f for f in store_route.files if f not in dropped]
            piped_paths -= dropped
            if not ledger:
                raise ValueError(_nothing_readable(skipped))

        # --- run the pipeline chain on a staging copy ----------------------
        payload_path: Path | None = None
        stage_records: list[StageRecord] = []
        chain: list[str] = []
        if pipe_route:
            chain = list(pipe_route.stages)
            if len(chain) > 1 or chain[0] not in _TREE_CAPABLE:
                chain = ["tar", *[s for s in chain if s != "tar"]]
            chain = _with_dedup(chain)
            for sid in chain:
                if sid not in registry:
                    raise StageError(f"stage '{sid}' is not implemented")
            staging = job_dir / "tree"
            for f in pipe_route.files:
                target = staging / relmap[f]
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(f, target)
                except OSError as exc:
                    # D4: a full destination volume raises OSError from this
                    # very call, and K3's skip-and-carry-on is exactly wrong
                    # for it. Measured before this guard existed: a disk-full
                    # job skipped every file in turn and then failed with
                    # "none of the 2 file(s) selected could be read - they may
                    # be open in another program". Every word of that is
                    # false. The files are readable, the *destination* is
                    # full, and the user is sent to close programs that are
                    # not the problem.
                    #
                    # The distinction is per-file versus per-volume. A
                    # share-mode denial is a property of one file and
                    # skipping it is the graceful thing; ENOSPC is a property
                    # of the volume, so every subsequent file will fail the
                    # same way and "skip it" just launders the real cause.
                    # Narrow on purpose - K3 exists because one locked file
                    # used to destroy a whole job, and that stays true.
                    if exc.errno in _FATAL_COPY_ERRNOS:
                        raise
                    # K3, last window: hashed successfully and locked before
                    # the copy. It must come out of the ledger as well, or D9
                    # would refuse to publish an archive whose ledger promises
                    # a file the payload does not contain - turning a graceful
                    # skip into a total failure one stage later.
                    skipped.append(describe_unreadable(f, exc,
                                                       label=relmap[f]))
                    ledger.pop(relmap[f], None)
                    target.unlink(missing_ok=True)
                    continue
            current: Path = staging
            skip_notes: list[str] = []
            for i, sid in enumerate(chain):
                _wait_if_paused(ctx)
                stage = registry[sid]
                nxt = job_dir / f"s{i}{_PAYLOAD_EXT.get(sid, '.bin')}"
                consumed = _tree_size(current)
                before = current
                try:
                    current = stage.compress(current, nxt, ctx)
                except QuietSkip as skip:
                    # B31: an opportunistic stage that stepped aside. Logged,
                    # not a warning, and no progress report from here: the
                    # stage sent its own if it had done any work.
                    ctx.log_cb(sid, str(skip))
                    continue
                except StageSkip as skip:
                    skip_notes.append(str(skip))
                    # B23: a skipped stage is over, so say so: without it the
                    # GUI never saw Precomp finish and, when zpaqfranz (which
                    # prints nothing) came next, the bar sat still all of it.
                    ctx.progress_cb(sid, 100.0)
                    continue  # pass data through; stage stays out of manifest
                if sid == "dedup" and before.is_file() and before.parent == job_dir:
                    # Its input (Precomp's output, the largest file of the
                    # job) is now held twice over. Nothing reads it again.
                    before.unlink(missing_ok=True)
                tool_name = getattr(stage, "tool_name", sid)
                tool = tools.get(tool_name) if tools else None
                stage_records.append(StageRecord(
                    stage=sid,
                    tool_name=tool.name if tool else "python",
                    tool_version=tool.version if tool else "",
                    # What actually ran, so the archive can be reproduced and
                    # "copy as command" is not guessing. Empty when the user
                    # chose nothing, rather than claiming the tool's defaults
                    # as deliberate settings.
                    input_bytes=consumed,
                    params=(options.as_params() if options
                            and sid in ("sevenzip", "zstd")
                            else getattr(stage, "record_params", dict)()),
                ))
            the_plan.warnings.extend(skip_notes)
            payload_path = current
            rmtree_force(staging)

        # --- package -------------------------------------------------------
        if skipped:
            # One summary line for the places that only render warnings (the
            # CLI's note list, the GUI's results screen); the names themselves
            # travel in CompressResult.skipped.
            the_plan.warnings.append(
                f"{len(skipped)} file(s) could not be read and were left out "
                f"of the archive: " + "; ".join(skipped[:5])
                + ("" if len(skipped) <= 5 else f" (and {len(skipped) - 5} more)"))

        payload_name = f"payload{_PAYLOAD_EXT.get(chain[-1], '.bin')}" if pipe_route else ""
        stored_paths = {f for r in the_plan.routes if r.action == "store" for f in r.files}
        manifest = Manifest.new(
            profile=profile.value,
            stages=stage_records,
            inputs=ledger,
            payload_name=payload_name,
            warnings=the_plan.warnings,
            # B21b (review): a file `_plan_that_fits` stored has no
            # `store_reason` of its own; give it the plan's, not a joined one.
            store_reasons={relmap[i.path]: reason for i in infos
                           if (reason := store_reason(i) or (
                               _NO_ROOM if i.path in stored_paths
                               and _probe_pipes(i) else None))},
            # No `files` list: it repeated every relative path a second time,
            # and the ledger above already records a route per file.
            # `Manifest.new` derives the count from it (K1).
            routes=[{"action": r.action, "stages": r.stages, "reason": r.reason}
                    for r in the_plan.routes],
            dirs=empty_dirs,
        )
        # K3 + K2 interaction: a directory whose *only* file was skipped is
        # now in neither list - not in the ledger (its file is gone) and not
        # in `dirs` (it was not empty when the tree was walked). The restore
        # would silently lose a folder that exists in the source, and the user
        # would be told about a skipped *file* rather than a missing *folder*.
        #
        # Recording it as an empty directory is the honest outcome: that is
        # exactly what the restore can faithfully reproduce.
        if skipped:
            for rel in sorted({p.rsplit("/", 1)[0] for p in
                               (relmap[f] for f in dropped) if "/" in p}):
                if not any(k == rel or k.startswith(rel + "/") for k in ledger):
                    if rel not in empty_dirs:
                        empty_dirs.append(rel)

        stored_map = {relmap[f]: f for f in (store_route.files if store_route else [])}
        # K3, the window the first pass missed. A store-route file is never
        # staged: its bytes are first read *inside* `write_container`, by
        # `jpeg.pack(read_bytes())` and `zf.write(src, ...)`, neither of which
        # can drop a file - so a lock there escaped as a raw PermissionError
        # and destroyed the job, which is exactly what K3 exists to prevent.
        # The analyzer puts ~42% of the real corpus's bytes on this route, so
        # this is the more likely half of the window rather than an edge case.
        #
        # Probing with a one-byte read is enough: the failure mode is a
        # share-mode denial on open, which `open()` reproduces exactly and
        # cheaply, and the same drop bookkeeping as the copy guard applies.
        for rel, source in list(stored_map.items()):
            try:
                with open(source, "rb") as probe:
                    probe.read(1)
            except OSError as exc:
                skipped.append(describe_unreadable(source, exc, label=rel))
                stored_map.pop(rel, None)
                ledger.pop(rel, None)

        # (4) ...and now the ledger may be empty for a second reason. The
        # guard after the hash loop cannot see a drop that happened in the
        # staging copy or in the probe above. `compress_standard` has always
        # refused this case - "a gate that can pass having checked nothing is
        # not a gate" - because an archive with an empty ledger publishes
        # happily and then passes `excmp verify` forever, reporting 0 verified
        # files as success.
        if not ledger:
            raise ValueError(_nothing_readable(skipped))
        # With a password the plaintext container is built inside temp; without
        # one it is the usual `<out>.tmp` twin beside the destination. See the
        # `stage_dir` note above.
        tmp_out = (stage_dir / (out_path.name + ".plain") if stage_dir is not None
                   else out_path.with_suffix(out_path.suffix + ".tmp"))
        if payload_path is not None:
            renamed = payload_path.with_name(payload_name)
            payload_path.rename(renamed)
            payload_path = renamed
        write_container(tmp_out, manifest, payload_path, stored_map,
                        ctx=ctx, profile=profile)

        # --- verify then atomically publish ---------------------------------
        _verify_before_publish(tmp_out, ctx)
        # D8. `expect` stays None on the plain path, deliberately: there, the
        # only thing between the gate and the rename is the rename, so a
        # digest taken here could only ever be compared against a digest of
        # the same untouched file half a second later. It would cost a full
        # extra pass over the archive and detect nothing - Python's own
        # `write()`/`close()` raise on a full volume rather than short-writing
        # silently. publish() still reads the bytes back off the filesystem
        # after the flush and returns the digest, which is what the sidecar
        # and the result want.
        #
        # With a password the gap is real, and the check is not free-riding on
        # resemblance: a second process pass reads the plaintext out of temp
        # and writes a different file. See below.
        expect: str | None = None
        if password:
            # F1: encrypt *after* the D9 gate and *before* the rename, so the
            # plaintext container never exists at the destination and what
            # gets encrypted is an archive already proven to restore. The
            # plaintext does live in temp for the length of the verify, which
            # is unavoidable: we cannot verify what we cannot read.
            from .crypto import encrypt_file
            # The ciphertext is the only thing that ever lands beside the
            # user's output, and even that as a .tmp until the rename.
            sealed = out_path.with_suffix(out_path.suffix + ".tmp")
            crypto_digests: dict[str, str] = {}
            # The one place the anchor is worth a full read: the plaintext is
            # about to be re-read by a separate pass, from a temp directory,
            # and what ships is a *different* file derived from it. So measure
            # what the gate accepted...
            verified_digest = hash_file(tmp_out)
            try:
                # ...make the encryptor prove it read exactly those bytes (it
                # is streaming them anyway, so the check itself is free)...
                encrypt_file(tmp_out, sealed, password, keyfile=keyfile,
                             expect_src_sha256=verified_digest,
                             digests=crypto_digests)
            finally:
                tmp_out.unlink(missing_ok=True)
            tmp_out = sealed
            # ...and hand the ciphertext's streamed digest to the publish, so
            # its read-back proves the file at the destination is the
            # ciphertext this run produced and not a truncated tail of it.
            expect = crypto_digests.get("dst")
        # No unlink of out_path first: os.replace overwrites atomically, and
        # deleting the destination only created a window in which the user had
        # neither yesterday's archive nor today's. See excmp.atomic.
        published_digest = publish(tmp_out, out_path, expect_sha256=expect)
    finally:
        rmtree_force(job_dir)
        # A cancel or failure between write_container and replace() would
        # otherwise strand a half-written .tmp beside the user's output.
        if tmp_out is not None and tmp_out.exists():
            tmp_out.unlink(missing_ok=True)

    # Only now that the archive is published and verified - a sidecar for an
    # archive that does not exist is worse than no sidecar.
    side = (_write_sidecar(out_path, digest=published_digest)
            if sidecar else None)

    orig = sum(m["size"] for m in ledger.values())
    return CompressResult(
        archive=out_path,
        sidecar=side,
        sha256=published_digest,
        orig_bytes=orig,
        final_bytes=out_path.stat().st_size,
        routes=manifest.routes,
        warnings=the_plan.warnings,
        elapsed_s=time.monotonic() - t0,
        piped_bytes=sum(m["size"] for m in ledger.values()
                        if m.get("route") == "pipeline"),
        skipped=skipped,
    )


@contextmanager
def opened_for_reading(archive: Path, ctx: StageContext,
                       password: str | None = None,
                       keyfile: Path | None = None):
    """Yield a plain, readable archive path, whatever shape it arrived in.

    An ``.excmp`` can reach a reader wearing two disguises, and both defeated
    every entry point until 2026-09-03:

    **Split into volumes.** ``big.excmp.001`` is not a zip, so ``is_excmp``
    said no and the caller fell through to the foreign-archive branch. 7-Zip
    then joined the set generically and extracted the *container* - writing
    ``manifest.json`` into the user's destination and returning
    ``verified=0``, while reporting success. The ledger guarantee silently
    evaporated for every split archive.

    **Encrypted.** Ciphertext is not a zip either, so the same fall-through
    happened, and ``list_any`` announced that the archive "appears damaged" -
    the precise lie ``crypto.py``'s docstring warns is how archives get
    deleted.

    Handling both here, once, is the point. Each surface used to decide for
    itself and three of them decided differently. Volumes are joined first and
    decryption second, because that is the order they were applied.
    """
    from .crypto import (WrongPasswordError, decrypt_file,
                         is_encrypted as _is_encrypted)
    from .volumes import is_first_part, join_parts

    archive = Path(archive)
    scratch: Path | None = None
    current = archive
    try:
        if is_first_part(current):
            scratch = Path(tempfile.mkdtemp(prefix="excmp-join-", dir=ctx.temp_dir))
            current = join_parts(current, scratch / current.with_suffix("").name)

        if _is_encrypted(current):
            if not password:
                raise EncryptedArchiveError(
                    f"{archive.name} is password-protected; supply the password")
            if scratch is None:
                scratch = Path(tempfile.mkdtemp(prefix="excmp-dec-",
                                                dir=ctx.temp_dir))
            plain = scratch / "decrypted.excmp"
            try:
                # F2's second factor, and the reason this parameter now
                # exists: `compress` has accepted `keyfile=` since F2 shipped
                # and this call did not pass one, so the engine could write an
                # archive it had no way to open - while telling the user to
                # "supply the same file as well as the password" through an API
                # that would not take it. Reproduced 2026-09-09; see
                # tests/test_keyfile_roundtrip.py.
                current = decrypt_file(current, plain, password, keyfile)
            except WrongPasswordError as exc:
                # Re-raised as the archive-level error the surfaces already
                # know how to turn into a password prompt.
                raise EncryptedArchiveError(str(exc)) from exc
        yield current
    finally:
        if scratch is not None:
            rmtree_force(scratch)


def is_excmp(path: Path) -> bool:
    """True when this really is one of ours.

    The manifest is the authority, never the extension: renaming a plain zip
    to ``.excmp`` must not decide which guarantees apply to it.
    """
    path = Path(path)
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return MANIFEST_NAME in zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def list_archive(archive: Path) -> ArchiveListing:
    """Everything the manifest knows, without extracting a byte.

    A zip directory read plus one JSON parse - free even on a 700 GB archive,
    because the ledger lives in the container, not the payload. The `reason`
    on a stored entry is the thing no other archiver can show, since no other
    archiver writes down *why* a file did not shrink.

    Foreign archives raise: listing those needs the pinned ``7z l -slt``
    grammar (G2), and an empty list would read as "this archive is empty".
    """
    archive = Path(archive)
    if not is_excmp(archive):
        raise ContainerError(
            f"{archive} is not an .excmp container - listing other formats "
            f"needs `7z l` support, which is not wired up yet")
    with zipfile.ZipFile(archive) as zf:
        manifest = _read_manifest(zf, archive)

    # The route comes from the ledger, which has carried one per file for as
    # long as `_extract_selected` and `extract` have read it from there. v1
    # also listed every name under `routes[].files`; that is the fallback for
    # the oldest archives, whose ledger entries predate the `route` key.
    summary = {r.get("action", ""): r.get("reason", "") for r in manifest.routes}
    legacy: dict[str, str] = {}
    for route in manifest.routes:
        for name in route.get("files", []):
            legacy[name] = route.get("action", "")

    def _entry(name: str, meta: dict) -> ArchiveEntry:
        route = meta.get("route") or legacy.get(name, "")
        return ArchiveEntry(
            name=name,
            size=meta.get("size", 0),
            sha256=meta.get("sha256", ""),
            route=route,
            # Only a stored file needs explaining - a pipelined one shrank.
            # `reason_for` reads v2's interned index, then v1's per-file
            # sentence, then the route's joined summary, which is all the
            # oldest archives ever had.
            reason=(manifest.reason_for(name, summary.get("store", ""))
                    if route == "store" else ""),
        )

    entries = [_entry(name, meta) for name, meta in manifest.inputs.items()]
    entries.sort(key=lambda e: e.size, reverse=True)
    return ArchiveListing(
        archive=archive,
        kind="excmp",
        profile=manifest.profile,
        created_utc=manifest.created_utc,
        stages=[st.stage for st in manifest.stages],
        entries=entries,
        # Anything that went through the chain lives in one solid payload.
        solid=any(e.route == "pipeline" for e in entries),
    )


def list_any(archive: Path, ctx: StageContext,
             password: str | None = None,
             keyfile: Path | None = None) -> ArchiveListing:
    """List ours *or* somebody else's (G2).

    Deliberately a separate entry point from :func:`list_archive`, exactly as
    :func:`extract_any` is from :func:`extract`. The split is not tidiness:
    ``list_archive`` is a zip-directory read plus one JSON parse, with no
    subprocess anywhere, and callers rely on that - ``ExtractTab``'s
    destination suggestion runs it synchronously on the GUI thread for every
    file dropped. Widening it in place would have put a ``7z.exe`` launch on
    that path for every foreign drop.

    Raises :class:`EncryptedArchiveError` when the archive's own file names
    are encrypted and the password is missing or wrong; plain
    :class:`ContainerError` when it simply cannot be read.
    """
    archive = Path(archive)
    with opened_for_reading(archive, ctx, password, keyfile) as opened:
        if is_excmp(opened):
            return list_archive(opened)
        return _list_foreign(opened, ctx, password)


def _list_foreign(archive: Path, ctx: StageContext,
                  password: str | None = None) -> ArchiveListing:
    """The 7-Zip half of :func:`list_any`, split out so the shared
    volume/decryption handling in `opened_for_reading` has somewhere to
    hand a plain path."""
    if not archive.is_file():
        raise ContainerError(f"{archive} does not exist")

    doc, output = SevenZipStage().list_entries(archive, ctx, password)
    verdict = classify_failure(output)
    if verdict == "encrypted":
        raise EncryptedArchiveError(
            f"{archive.name} is encrypted: its file names cannot be read "
            f"without the password"
            + (" (the one supplied did not open it)" if password else ""))
    if verdict or (not doc.entries and not doc.archive):
        # No entries AND no archive block means 7-Zip never recognised the
        # file. An archive that genuinely holds nothing still produces an
        # archive block, so the two are distinguishable - and reporting an
        # unreadable file as "empty" is the exact failure this listing
        # refused to ship with in wave 3b.
        raise ContainerError(
            f"{archive.name} could not be read as an archive"
            + (" (the file appears damaged or is not an archive)"
               if verdict == "corrupt" else ""))

    entries = [
        ArchiveEntry(
            name=e.name, size=e.size,
            # Empty, and deliberately so. The checksum goes in `crc`.
            sha256="", route="", reason="",
            crc=e.crc, packed_size=e.packed_size, modified=e.modified,
            encrypted=e.encrypted, is_dir=e.is_dir,
        )
        for e in doc.entries
    ]
    entries.sort(key=lambda e: e.size, reverse=True)
    return ArchiveListing(
        archive=archive,
        kind=doc.kind or archive.suffix.lstrip(".").lower(),
        # We do not know these and will not invent them. A foreign archive
        # records no profile, no stage chain and no creation time of ours.
        profile="", created_utc="", stages=[],
        entries=entries,
        ledger_backed=False,
        truncated=doc.truncated,
        encrypted=doc.encrypted,
        solid=doc.solid,
    )


def extract_any(archive: Path, out_dir: Path, ctx: StageContext,
                password: str | None = None,
                keyfile: Path | None = None) -> ExtractResult:
    """Extract ours *or* somebody else's (G1).

    Deliberately a separate entry point from :func:`extract`, which stays
    .excmp-only. A caller that wants the ledger-verified path should not be
    able to get a best-effort one by accident, and vice versa - the difference
    is the entire value proposition.
    """
    archive = Path(archive)
    with opened_for_reading(archive, ctx, password, keyfile) as opened:
        if is_excmp(opened):
            return extract(opened, out_dir, ctx)
        return _extract_foreign(opened, out_dir, ctx, password)


def _extract_foreign(archive: Path, out_dir: Path, ctx: StageContext,
                     password: str | None = None,
                     include: list[str] | None = None) -> ExtractResult:
    """Hand it to 7-Zip, then count what landed.

    No ledger exists, so there is nothing to verify and we say so. The count
    comes from walking the output rather than parsing 7-Zip's chatter: the
    number of files on disk is a fact, and its stdout format is not a contract.
    """
    t0 = time.monotonic()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.log_cb("sevenzip", f"opening {archive.name} with 7-Zip - this archive "
                           f"has no SHA-256 ledger, so its contents cannot be "
                           f"checked against one")
    try:
        SevenZipStage().extract(archive, out_dir, ctx, password=password,
                                include=include)
    except StageError as exc:
        # 7-Zip's exit code alone cannot tell "wrong password" from "broken
        # file", but its output can, and the two need different offers from
        # the surface above: a prompt, or an apology.
        if classify_failure(str(exc)) == "encrypted":
            raise EncryptedArchiveError(
                f"{archive.name} is encrypted and cannot be opened"
                + (" with the password supplied" if password
                   else " without a password")) from exc
        raise
    restored = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return ExtractResult(
        out_dir=out_dir,
        files_restored=restored,
        verified=0,
        elapsed_s=time.monotonic() - t0,
        ledger_backed=False,
    )


@dataclass
class SelectionCost:
    """What pulling these particular files out is going to cost.

    ``solid`` means the requested set cannot be read piecemeal: the payload is
    one stream and reaching any byte of it replays the whole chain. That is
    inherent to solid compression, not a defect - but a user who ticked one
    3 KB file deserves to hear "this replays 4.2 GB" *before* pressing the
    button, not after.
    """

    solid: bool
    bytes_to_replay: int


def selection_cost(archive: Path, names: list[str]) -> SelectionCost:
    """Price a selection from the manifest alone - free, no extraction.

    `.excmp` only: our ledger records each file's route, so the answer is a
    set membership test. For a foreign archive 7-Zip decides internally how
    much it must decode, and pricing that would need a listing this function
    may not have - :attr:`ArchiveListing.solid` carries 7-Zip's own answer to
    the surface that does.
    """
    listing = list_archive(Path(archive))
    wanted = {str(safe_relpath(n)) for n in names}
    piped = [e for e in listing.entries if e.route == "pipeline"]
    if not any(e.name in wanted for e in piped):
        return SelectionCost(solid=False, bytes_to_replay=0)
    # Everything in the stream, not just what was asked for: that is the work
    # the chain actually does.
    return SelectionCost(solid=True, bytes_to_replay=sum(e.size for e in piped))


def extract_selected(archive: Path, names: list[str], out_dir: Path,
                     ctx: StageContext,
                     password: str | None = None,
                     keyfile: Path | None = None) -> ExtractResult:
    """Restore only ``names`` (G2).

    Every requested name is validated **before** anything runs. For a foreign
    archive that is load-bearing rather than defensive: the names become
    ``-i!`` include patterns, 7-Zip matches those as globs with no literal
    mode, and ``safe_relpath`` already refuses ``*`` and ``?`` in a filename -
    so no name we accept can quietly match more than it says.

    Selecting from one of ours keeps the guarantee: the chosen files are
    hash-checked against the ledger exactly as a full restore would check all
    of them.
    """
    with opened_for_reading(Path(archive), ctx, password, keyfile) as _opened:
        return _extract_selected(_opened, names, out_dir, ctx, password)


def _extract_selected(archive: Path, names: list[str], out_dir: Path,
                      ctx: StageContext,
                      password: str | None = None) -> ExtractResult:
    """The real work, once `archive` is a plain readable file.

    Split from the public name so a split or encrypted archive is resolved
    exactly once, in one place, the way every other reader now does it.
    """
    t0 = time.monotonic()
    archive, out_dir = Path(archive), Path(out_dir)
    if not names:
        raise ValueError(
            "nothing was selected - refusing to guess that this means "
            "'extract everything'")
    wanted = [str(safe_relpath(n)) for n in names]
    out_dir.mkdir(parents=True, exist_ok=True)

    if not is_excmp(archive):
        return _extract_foreign_selected(archive, wanted, out_dir, ctx,
                                         password, t0)

    with zipfile.ZipFile(archive) as zf:
        manifest = _read_manifest(zf, archive)
    missing = [n for n in wanted if n not in manifest.inputs]
    if missing:
        raise KeyError(f"not in this archive: {', '.join(sorted(missing))}")
    ledger = {name: manifest.inputs[name] for name in wanted}

    work = Path(tempfile.mkdtemp(prefix="excmp-sel-", dir=ctx.temp_dir))
    try:
        stored_only = all(manifest.inputs[n].get("route") == "store"
                          for n in wanted)
        if stored_only:
            # A zip-directory read. The full ledger still goes in, because it
            # is what makes the bomb defence exact; `only` limits what gets
            # written, not what gets validated.
            extract_stored(archive, out_dir, manifest.inputs, only=set(wanted),
                           ctx=ctx)
        else:
            ctx.log_cb("extract", f"this archive is solid - reaching "
                                  f"{len(wanted)} file(s) means replaying the "
                                  f"whole chain")
            extract(archive, work / "all", ctx)
            for name in wanted:
                source = resolve_within(work / "all", name)
                target = resolve_within(out_dir, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
        verified = verify_restore(out_dir, ledger)
        # K2 for the selective path too. The solid branch goes through
        # `extract`, which already stamped them, and `shutil.move` carries the
        # timestamp across - but the `stored_only` branch calls
        # `extract_stored` directly and would otherwise hand back files dated
        # today. Applying it to both keeps one rule instead of two.
        _apply_mtimes(out_dir, ledger)
    finally:
        rmtree_force(work)

    # K2 for the selective path as well. Without this, "extract everything"
    # and "extract these files" produced different trees from the same
    # archive - and a user pulling one file out is not asking for a different
    # directory layout than the one the archive records.
    _restore_empty_dirs(out_dir, manifest.dirs)
    return ExtractResult(out_dir=out_dir, files_restored=len(wanted),
                         verified=verified, elapsed_s=time.monotonic() - t0)


def _extract_foreign_selected(archive: Path, wanted: list[str], out_dir: Path,
                              ctx: StageContext, password: str | None,
                              t0: float) -> ExtractResult:
    """Stage into temp, then place exactly what was asked for.

    Extracting straight into ``out_dir`` would trust ``-i!`` to have matched
    precisely, and would trust 7-Zip's own path handling to keep every member
    inside the destination. Landing in a private directory and moving named
    files out re-uses the ``resolve_within`` check on the way, and keeps the
    standing promise that outputs are placed, never streamed into position.
    """
    work = Path(tempfile.mkdtemp(prefix="excmp-sel-", dir=ctx.temp_dir))
    try:
        _extract_foreign(archive, work, ctx, password, include=wanted)
        placed = 0
        missing: list[str] = []
        for name in wanted:
            source = resolve_within(work, name)
            if not source.is_file():
                missing.append(name)
                continue
            target = resolve_within(out_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            placed += 1
        if missing:
            raise KeyError(f"not in this archive: {', '.join(sorted(missing))}")
    finally:
        rmtree_force(work)
    return ExtractResult(out_dir=out_dir, files_restored=placed, verified=0,
                         elapsed_s=time.monotonic() - t0, ledger_backed=False)


def verify_archive(archive: Path, ctx: StageContext,
                   password: str | None = None, *,
                   keyfile: Path | None = None,
                   deep: bool = False,
                   source: Path | None = None) -> VerifyResult:
    """Prove an archive still restores byte-for-byte. Read-only, produces
    nothing, raises :class:`~excmp.verify.VerifyError` if it does not.

    This is the D9 acceptance gate as a public verb. It always was the honest
    definition of "verified" - a **full restore of every byte, compared against
    the ledger** - and the only reason it lived behind a private name was that
    it had one caller. It has three now: compress (before publishing), the CLI
    (``excmp verify``), and the Verify button.

    What it deliberately is *not* is a container self-test. ``7z t`` checks
    only the last stage's own framing, which let a broken stage underneath sail
    through: srep64.exe once failed its decompression checksum at extract time
    on an archive compress() had already called a success
    (benchmarks/2026-08-01-estimator-backtest.md). Tool exit codes cannot be
    trusted. If this function is ever "optimised" into a cheaper check, the
    product's first sentence stops being true.

    The restore goes to a private temp directory and is deleted whether it
    passes or fails - verifying a 700 GB archive must not fill the drive, and
    nobody asked for the files.

    **D5, ``deep``.** Adds two things to the same restore, neither of which
    costs a second pass over the data:

    * an order-independent :func:`~excmp.verify.tree_hash` of the whole
      restored tree, built from the digests the verification pass already
      computed. One value for "this is the same tree", recordable and
      checkable a year later.
    * a check for files in the restore that the ledger does **not** account
      for. `verify_restore` walks the *ledger* and so cannot see an extra
      file, which would be an archive producing data nothing vouches for.
      Comparing whole-tree hashes is exactly what catches that, and it is the
      reason the tree hash is computed from the restore rather than from the
      manifest.

    **D5, ``source``.** The other direction, and zpaqfranz's ``v -ssd`` rather
    than its ``t``: re-read the *originals* off disk and compare them against
    what the archive recorded. That answers a question nothing else here can -
    "are my originals still the bytes I archived?" - because the archive is
    the only reference copy of that answer. Requires ``deep``; the shallow path
    has no ledger in hand to compare against.

    ``source`` is the *parent* of what was archived, because a ledger key is
    ``<input name>/<path inside it>``.
    """
    if source is not None and not deep:
        raise ValueError(
            "source verification needs deep=True - re-reading the originals "
            "is a comparison against the ledger, which the shallow path does "
            "not read")
    t0 = time.monotonic()
    archive = Path(archive)
    ctx.temp_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="excmp-verify-", dir=ctx.temp_dir))
    digests: dict[str, str] = {}
    ledger: dict[str, dict] = {}
    tree = ""
    try:
        with opened_for_reading(Path(archive), ctx, password, keyfile) as opened:
            restore_root = work / "restore"
            result = extract(opened, restore_root, ctx, password=password,
                             digests_out=digests if deep else None,
                             keyfile=keyfile)
            if deep or source is not None:
                # A zip-directory read and one JSON parse - free even on a
                # 700 GB archive, and it has to happen inside this block: for
                # an encrypted archive `opened` is a decrypted copy that stops
                # existing when the context manager exits.
                with zipfile.ZipFile(opened) as zf:
                    ledger = _read_manifest(zf, opened).inputs
        if deep:
            tree = hash_tree_of_ledger = tree_hash(digests)
            unaccounted = sorted(
                p.relative_to(restore_root).as_posix()
                for p in restore_root.rglob("*")
                if p.is_file()
                and p.relative_to(restore_root).as_posix() not in digests)
            if unaccounted:
                raise VerifyError(
                    f"the restore produced {len(unaccounted)} file(s) the "
                    f"ledger does not account for, so its whole-tree hash is "
                    f"not {hash_tree_of_ledger[:16]}...: "
                    f"{unaccounted[:5]} - an archive that returns data nothing "
                    f"vouches for has not verified")
    finally:
        rmtree_force(work)

    check = (verify_source(Path(source), ledger) if source is not None
             else SourceCheck(0, [], [], []))
    return VerifyResult(
        archive=archive,
        ok=True,
        files_restored=result.files_restored,
        verified=result.verified,
        elapsed_s=time.monotonic() - t0,
        tree_sha256=tree,
        source_checked=check.checked,
        source_changed=check.changed,
        source_missing=check.missing,
        source_extra=check.extra,
    )


#: I11: seconds between the self-test's "still running" reports.
_VERIFY_HEARTBEAT_S = 1.0


@contextmanager
def _heartbeat(beat, interval: float):
    """Call ``beat()`` every ``interval`` seconds until the block exits."""
    stop = threading.Event()

    def run() -> None:
        while not stop.wait(interval):
            beat()

    thread = threading.Thread(target=run, name="excmp-verify-heartbeat",
                              daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def _verify_before_publish(archive: Path, ctx: StageContext) -> int:
    """The publish gate: verify BEFORE the atomic rename makes this the user's
    output. Deliberately implemented in terms of the public verb, so the button
    and the gate can never drift into meaning different things.

    The restore's own stage reports are muted: they describe the restore, not
    the job. What the job hears instead (I11) is ``("verify", 0.0)`` when the
    self-test starts, the same again every ``_VERIFY_HEARTBEAT_S`` while it
    runs and the job is not paused, and ``("verify", 100.0)`` only once every
    hash matched. The 0.0 is
    not a measurement: zpaqfranz prints nothing during a restore, so there is
    none to give. The heartbeat is what lets the GUI time the phase against
    its estimate without a timer of its own. Cancel/pause/logs pass through.
    """
    quiet = StageContext(temp_dir=ctx.temp_dir, threads=ctx.threads,
                         log_cb=ctx.log_cb, cancel=ctx.cancel, pause=ctx.pause)
    ctx.log_cb("verify", "restoring the whole archive to check every hash "
                         "before publishing…")
    ctx.progress_cb("verify", 0.0)

    def beat() -> None:
        # A paused job holds the restore at its next stage boundary. The beats
        # stop with it: a bar and a countdown that kept moving through a pause
        # would charge the hold against the self-test's estimate, and the
        # taskbar would flip from "paused" back to "normal" every second.
        if not ctx.pause.is_set():
            ctx.progress_cb("verify", 0.0)

    with _heartbeat(beat, _VERIFY_HEARTBEAT_S):
        result = verify_archive(archive, quiet)
    ctx.progress_cb("verify", 100.0)
    ctx.log_cb("verify", f"self-test passed: {result.files_restored} file(s) "
                         f"restored, {result.verified} hash(es) verified in "
                         f"{result.elapsed_s:.1f}s")
    return result.verified


def extract(archive: Path, out_dir: Path, ctx: StageContext,
            password: str | None = None,
            digests_out: dict[str, str] | None = None,
            keyfile: Path | None = None) -> ExtractResult:
    """Restore an ``.excmp`` and hash-verify every file against its ledger (see `_extract`).

    A destination folder THIS call created is taken away again if the restore fails: a
    password-protected or unreadable archive used to leave an empty ``junk/`` beside it (found by
    the I5 review, where "Extract here" makes it one right-click). A folder that was already there
    stays, and so does one the restore had started to fill - ``rmdir`` refuses a non-empty one.
    """
    out_dir = Path(out_dir)
    created = not out_dir.exists()
    try:
        return _extract(archive, out_dir, ctx, password, digests_out, keyfile)
    except BaseException:
        if created:
            try:
                out_dir.rmdir()
            except OSError:
                pass
        raise


def _extract(archive: Path, out_dir: Path, ctx: StageContext,
             password: str | None = None,
             digests_out: dict[str, str] | None = None,
             keyfile: Path | None = None) -> ExtractResult:
    """Restore an ``.excmp`` and hash-verify every file against its ledger.

    ``digests_out`` (D5) is handed straight to
    :func:`excmp.verify.verify_restore`: pass a dict and it comes back holding
    the digest of every restored file. Those digests are computed by the
    verification pass regardless, so a caller that wants
    :func:`excmp.verify.tree_hash` gets it without a second pass over the
    data.
    """
    t0 = time.monotonic()
    archive, out_dir = Path(archive), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    registry = _stage_factory()
    job_dir = Path(tempfile.mkdtemp(prefix="excmp-x-", dir=ctx.temp_dir))
    # The zone lives on the file the user actually downloaded. `archive` is
    # rebound below when the archive is encrypted, so keep the original.
    source_archive = archive
    try:
        # F1: an encrypted archive is decrypted into the job dir first, and
        # everything after this line is the ordinary path. Same shape as the
        # volume join in the CLI - one format concern handled once, at the
        # edge, rather than threaded through the reader.
        from .crypto import decrypt_file, is_encrypted
        if is_encrypted(archive):
            if not password:
                raise EncryptedArchiveError(
                    f"{archive.name} is password-protected; supply the password")
            # keyfile, not just password: this is the *second* decryption
            # site in this module - `extract` resolves an encrypted archive
            # itself rather than going through `opened_for_reading` - and a
            # factor plumbed through only one of two sites is how F2's
            # keyfile came to be write-only.
            archive = decrypt_file(archive, job_dir / "decrypted.excmp",
                                   password, keyfile)
        manifest, payload = read_container(archive, job_dir)
        _check_free_space(out_dir, manifest.inputs)
        stage_budget = max(declared_total(manifest.inputs) * _STAGE_INFLATION_LIMIT,
                           _STAGE_FLOOR_BYTES)
        restored = 0
        if payload is not None:
            current = payload
            stages = [s.stage for s in manifest.stages]
            for i, sid in enumerate(reversed(stages)):
                _wait_if_paused(ctx)
                stage = registry.get(sid)
                if stage is None:
                    raise StageError(f"archive needs stage '{sid}' which is not available")
                is_last = i == len(stages) - 1
                dst = out_dir if is_last else job_dir / f"r{i}"
                # The chain runs backwards, so this stage should reproduce
                # what the *corresponding* compress stage consumed. When the
                # archive recorded that number, use it: an exact figure plus
                # slack is a far tighter bound than a blanket multiplier, and
                # it is the only way to allow Precomp's honest ~50x on PNG
                # without weakening the guard for everything else.
                record = manifest.stages[len(stages) - 1 - i]
                declared_in = getattr(record, "input_bytes", 0) or 0
                budget = (int(declared_in * 1.25) + _STAGE_FLOOR_BYTES
                          if declared_in else stage_budget)
                ctx.output_limit = budget
                consumed_path = current
                current = stage.extract(current, dst, ctx)
                if (sid == "dedup" and consumed_path.is_file()
                        and job_dir in consumed_path.parents):
                    # B31: the rebuilt stream replaces it; do not hold both.
                    consumed_path.unlink(missing_ok=True)
                produced = _tree_size(current)
                if produced > budget:
                    raise ContainerError(
                        f"stage '{sid}' produced {produced >> 20} MiB, beyond "
                        f"the {budget >> 20} MiB this archive declares for it "
                        f"- refusing to continue")
                if not is_last and current.is_dir():
                    # intermediate extract of a single-file payload: descend
                    inner = [p for p in current.rglob("*") if p.is_file()]
                    if len(inner) != 1:
                        raise StageError(f"stage '{sid}' produced {len(inner)} files, expected 1")
                    current = inner[0]
        restored += len([1 for m in manifest.inputs.values() if m.get("route") == "pipeline"])
        stored = extract_stored(archive, out_dir, manifest.inputs, ctx=ctx)
        restored += len(stored)
        # `digests_out` is passed as a keyword, and only when a caller asked
        # for it. It is an optional addition (D5), so it must not change the
        # shape of the call every existing caller and test double was written
        # against - `tests/test_publish_gate.py` replaces this function with a
        # two-argument spy to prove the D9 gate verifies the FULL ledger, and
        # a pin that precise should not have to be edited because somebody
        # added a parameter it does not care about.
        verified = (verify_restore(out_dir, manifest.inputs,
                                   digests_out=digests_out)
                    if digests_out is not None
                    else verify_restore(out_dir, manifest.inputs))
        # F4: carry the archive's Mark of the Web onto what came out of it.
        # After verification, never before: a file that failed its hash is not
        # one we want to have touched, and a mark is cosmetic beside that.
        # Never raises - see motw.propagate.
        from .motw import propagate as _propagate_zone
        _propagate_zone(source_archive, out_dir)
        # K2, and deliberately the last thing that touches these files: the
        # zone marker above is an alternate data stream, and writing one
        # updates the host file's last-write time.
        _apply_mtimes(out_dir, manifest.inputs)
        # Deliberately NOT added to `restored`. That field has always meant
        # "ledger entries written back" and equalled `verified` for every
        # ledger-backed archive; folding a directory count into it made the
        # GUI hero read "Restored 4 files" beside "2 SHA-256 hashes verified"
        # on a two-file tree, and broke the invariant two existing tests
        # assert - which passed only because their fixtures had no empty
        # directories.
        _restore_empty_dirs(out_dir, manifest.dirs)
    finally:
        rmtree_force(job_dir)
    return ExtractResult(out_dir=out_dir, files_restored=restored,
                         verified=verified, elapsed_s=time.monotonic() - t0)
