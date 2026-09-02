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

import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import jpeg
from .analyzer import Category, FileInfo, analyze_tree
from .estimate import estimate_size
from .manifest import (MANIFEST_NAME, ContainerError, Manifest, StageRecord,
                       _read_manifest, declared_total, extract_stored,
                       read_container, write_container)
from .planner import Plan, Profile, plan as make_plan, precomp_inflation, store_reason
from .safepath import resolve_within, safe_relpath
from .slt import classify_failure
from .stages.base import Stage, StageContext, StageError, StageSkip
from .stages.sevenzip import SevenZipStage
from .stages.tarstage import TarStage
from .stages.zstdstage import ZstdStage
from .tools import ToolInfo, find_tools
from .verify import hash_file, verify_restore

# Stages that can consume a directory tree directly (anything else forces a
# leading tar stage so the chain operates on one file).
_TREE_CAPABLE = {"sevenzip", "zstd"}

_PAYLOAD_EXT = {"sevenzip": ".7z", "zstd": ".tar.zst", "tar": ".tar",
                "precomp": ".pcf", "srep": ".srep", "zpaqfranz": ".zpaq"}


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
    zstd = (ZstdStage(level=opts.level) if opts.level is not None
            else ZstdStage())
    registry: dict[str, Stage] = {
        "tar": TarStage(),
        "zstd": zstd,
        "sevenzip": seven,
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


def _collect(inputs: list[Path]) -> tuple[list[FileInfo], dict[Path, str]]:
    """Analyze all inputs; map absolute path -> archive-relative path."""
    infos: list[FileInfo] = []
    relmap: dict[Path, str] = {}
    for inp in inputs:
        inp = Path(inp).resolve()
        for info in analyze_tree(inp):
            rel = info.path.name if inp.is_file() else f"{inp.name}/{info.path.relative_to(inp).as_posix()}"
            if rel in relmap.values():
                raise ValueError(f"duplicate archive path '{rel}' - rename one of the inputs")
            infos.append(info)
            relmap[info.path] = rel
    return infos, relmap


def _write_sidecar(archive: Path) -> Path:
    """`<archive>.sha256` in ``sha256sum`` layout (G6).

    Hashed AFTER the atomic rename, so it describes the file that actually
    shipped rather than the `.tmp` twin that existed a moment earlier. The
    body names the archive by *file name*, not full path: `sha256sum -c`
    resolves relative to the working directory, and an absolute path would
    break the moment the pair is moved - which is the only situation a
    transport sidecar exists for.
    """
    side = Path(str(archive) + ".sha256")
    # newline="\n": see volumes.write_parts_sidecar. Python writes CRLF on
    # Windows by default, and `sha256sum -c` then treats the trailing \r as
    # part of the filename and fails every line. This shipped broken until
    # 2026-09-02 - the sidecar existed for exactly one command and did not
    # survive it.
    side.write_text(f"{hash_file(archive)}  {archive.name}\n",
                    encoding="utf-8", newline="\n")
    return side


def compress(inputs: list[Path], out_path: Path, profile: Profile,
             ctx: StageContext, tools: dict[str, ToolInfo | None] | None = None,
             sidecar: bool = False,
             options: "StageOptions | None" = None) -> CompressResult:
    t0 = time.monotonic()
    tools = tools if tools is not None else find_tools(with_versions=True)
    out_path = Path(out_path)
    infos, relmap = _collect([Path(p) for p in inputs])
    if not infos:
        raise ValueError("nothing to compress")
    the_plan: Plan = make_plan(infos, profile, tools)
    # Before copying a single byte: will this fit? (J4 - the compression-side
    # twin of the check extract() has done since D0.)
    the_plan.warnings.extend(
        _check_compress_space(out_path, ctx.temp_dir, infos, the_plan))

    # B7: the branch filter is decided from what will actually be *piped*,
    # not from the whole input. A folder of installers is mostly stored, and
    # what reaches 7-Zip may look nothing like the folder as a whole.
    _piped = next((r for r in the_plan.routes if r.action == "pipeline"), None)
    _piped_set = set(_piped.files) if _piped else set()
    registry = _stage_factory(
        options, bcj2=_wants_bcj2([i for i in infos if i.path in _piped_set]))
    job_dir = Path(tempfile.mkdtemp(prefix="excmp-", dir=ctx.temp_dir))
    tmp_out: Path | None = None
    try:
        # --- split routes -------------------------------------------------
        pipe_route = next((r for r in the_plan.routes if r.action == "pipeline"), None)
        store_route = next((r for r in the_plan.routes if r.action == "store"), None)

        ledger: dict[str, dict] = {}
        piped_paths = set(pipe_route.files) if pipe_route else set()
        for info in infos:
            route = "pipeline" if info.path in piped_paths else "store"
            entry = {
                "size": info.size,
                "sha256": hash_file(info.path),
                "route": route,
            }
            # B2: a stored JPEG is the one case where "store" is leaving money
            # on the table. Lepton reproduces the file bit-for-bit and measured
            # 33.4% on real photos here. `pack()` round-trips before answering,
            # so a `codec` claim is one we have already honoured once; if it
            # declines - CMYK and >16384px are both common and both refused -
            # the file is simply stored raw as before.
            if route == "store" and jpeg.available():
                try:
                    if jpeg.pack(info.path.read_bytes()) is not None:
                        entry["codec"] = "lepton"
                except OSError:
                    pass    # unreadable here means unreadable later; let the
                            # normal store path produce the error
            ledger[relmap[info.path]] = entry

        # --- run the pipeline chain on a staging copy ----------------------
        payload_path: Path | None = None
        stage_records: list[StageRecord] = []
        chain: list[str] = []
        if pipe_route:
            chain = list(pipe_route.stages)
            if len(chain) > 1 or chain[0] not in _TREE_CAPABLE:
                chain = ["tar", *[s for s in chain if s != "tar"]]
            for sid in chain:
                if sid not in registry:
                    raise StageError(f"stage '{sid}' is not implemented")
            staging = job_dir / "tree"
            for f in pipe_route.files:
                target = staging / relmap[f]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
            current: Path = staging
            skip_notes: list[str] = []
            for i, sid in enumerate(chain):
                _wait_if_paused(ctx)
                stage = registry[sid]
                nxt = job_dir / f"s{i}{_PAYLOAD_EXT.get(sid, '.bin')}"
                consumed = _tree_size(current)
                try:
                    current = stage.compress(current, nxt, ctx)
                except StageSkip as skip:
                    skip_notes.append(str(skip))
                    continue  # pass data through; stage stays out of manifest
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
                            and sid in ("sevenzip", "zstd") else {}),
                ))
            the_plan.warnings.extend(skip_notes)
            payload_path = current
            shutil.rmtree(staging, ignore_errors=True)

        # --- package -------------------------------------------------------
        payload_name = f"payload{_PAYLOAD_EXT.get(chain[-1], '.bin')}" if pipe_route else ""
        manifest = Manifest.new(
            profile=profile.value,
            stages=stage_records,
            inputs=ledger,
            payload_name=payload_name,
            warnings=the_plan.warnings,
            store_reasons={relmap[i.path]: reason for i in infos
                           if (reason := store_reason(i))},
            routes=[{"action": r.action, "stages": r.stages, "reason": r.reason,
                     "files": [relmap[f] for f in r.files]} for r in the_plan.routes],
        )
        stored_map = {relmap[f]: f for f in (store_route.files if store_route else [])}
        tmp_out = out_path.with_suffix(out_path.suffix + ".tmp")
        if payload_path is not None:
            renamed = payload_path.with_name(payload_name)
            payload_path.rename(renamed)
            payload_path = renamed
        write_container(tmp_out, manifest, payload_path, stored_map)

        # --- verify then atomically publish ---------------------------------
        _verify_before_publish(tmp_out, ctx)
        if out_path.exists():
            out_path.unlink()
        tmp_out.replace(out_path)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
        # A cancel or failure between write_container and replace() would
        # otherwise strand a half-written .tmp beside the user's output.
        if tmp_out is not None and tmp_out.exists():
            tmp_out.unlink(missing_ok=True)

    # Only now that the archive is published and verified - a sidecar for an
    # archive that does not exist is worse than no sidecar.
    side = _write_sidecar(out_path) if sidecar else None

    orig = sum(m["size"] for m in ledger.values())
    return CompressResult(
        archive=out_path,
        sidecar=side,
        orig_bytes=orig,
        final_bytes=out_path.stat().st_size,
        routes=manifest.routes,
        warnings=the_plan.warnings,
        elapsed_s=time.monotonic() - t0,
    )


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

    reasons: dict[str, tuple[str, str]] = {}
    for route in manifest.routes:
        for name in route.get("files", []):
            reasons[name] = (route.get("action", ""), route.get("reason", ""))

    entries = [
        ArchiveEntry(
            name=name,
            size=meta.get("size", 0),
            sha256=meta.get("sha256", ""),
            route=reasons.get(name, ("", ""))[0],
            # Per-file first; fall back to the route's joined summary only for
            # archives written before `store_reasons` existed. Only a stored
            # file needs explaining - a pipelined one shrank.
            reason=(manifest.store_reasons.get(name)
                    or reasons.get(name, ("", ""))[1])
            if reasons.get(name, ("", ""))[0] == "store" else "",
        )
        for name, meta in manifest.inputs.items()
    ]
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
             password: str | None = None) -> ArchiveListing:
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
    if is_excmp(archive):
        return list_archive(archive)
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
                password: str | None = None) -> ExtractResult:
    """Extract ours *or* somebody else's (G1).

    Deliberately a separate entry point from :func:`extract`, which stays
    .excmp-only. A caller that wants the ledger-verified path should not be
    able to get a best-effort one by accident, and vice versa - the difference
    is the entire value proposition.
    """
    archive = Path(archive)
    if is_excmp(archive):
        return extract(archive, out_dir, ctx)
    return _extract_foreign(archive, out_dir, ctx, password)


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
                     password: str | None = None) -> ExtractResult:
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
            extract_stored(archive, out_dir, manifest.inputs, only=set(wanted))
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
    finally:
        shutil.rmtree(work, ignore_errors=True)

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
        shutil.rmtree(work, ignore_errors=True)
    return ExtractResult(out_dir=out_dir, files_restored=placed, verified=0,
                         elapsed_s=time.monotonic() - t0, ledger_backed=False)


def verify_archive(archive: Path, ctx: StageContext) -> VerifyResult:
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
    """
    t0 = time.monotonic()
    archive = Path(archive)
    ctx.temp_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="excmp-verify-", dir=ctx.temp_dir))
    try:
        result = extract(archive, work / "restore", ctx)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return VerifyResult(
        archive=archive,
        ok=True,
        files_restored=result.files_restored,
        verified=result.verified,
        elapsed_s=time.monotonic() - t0,
    )


def _verify_before_publish(archive: Path, ctx: StageContext) -> int:
    """The publish gate: verify BEFORE the atomic rename makes this the user's
    output. Deliberately implemented in terms of the public verb, so the button
    and the gate can never drift into meaning different things.

    Progress is muted (the job's bar sits in the 95% band that
    ``gui.progress`` reserves for exactly this); cancel/pause/logs pass through.
    """
    quiet = StageContext(temp_dir=ctx.temp_dir, threads=ctx.threads,
                         log_cb=ctx.log_cb, cancel=ctx.cancel, pause=ctx.pause)
    ctx.log_cb("verify", "restoring the whole archive to check every hash "
                         "before publishing…")
    result = verify_archive(archive, quiet)
    ctx.log_cb("verify", f"self-test passed: {result.files_restored} file(s) "
                         f"restored, {result.verified} hash(es) verified in "
                         f"{result.elapsed_s:.1f}s")
    return result.verified


def extract(archive: Path, out_dir: Path, ctx: StageContext) -> ExtractResult:
    t0 = time.monotonic()
    archive, out_dir = Path(archive), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    registry = _stage_factory()
    job_dir = Path(tempfile.mkdtemp(prefix="excmp-x-", dir=ctx.temp_dir))
    try:
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
                current = stage.extract(current, dst, ctx)
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
        stored = extract_stored(archive, out_dir, manifest.inputs)
        restored += len(stored)
        verified = verify_restore(out_dir, manifest.inputs)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
    return ExtractResult(out_dir=out_dir, files_restored=restored,
                         verified=verified, elapsed_s=time.monotonic() - t0)
