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

from .analyzer import FileInfo, analyze_tree
from .estimate import estimate_size
from .manifest import (MANIFEST_NAME, ContainerError, Manifest, StageRecord,
                       _read_manifest, declared_total, extract_stored,
                       read_container, write_container)
from .planner import Plan, Profile, plan as make_plan, store_reason
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
                "precomp": ".pcf", "srep": ".srep"}


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
    inflation = _PRECOMP_INFLATION if "precomp" in stages else 1

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


def _stage_factory() -> dict[str, Stage]:
    registry: dict[str, Stage] = {
        "tar": TarStage(),
        "zstd": ZstdStage(),
        "sevenzip": SevenZipStage(),
    }
    try:  # optional stages, present once task 9 lands / tools installed
        from .stages.precomp import PrecompStage
        from .stages.srep import SrepStage
        registry["precomp"] = PrecompStage()
        registry["srep"] = SrepStage()
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


@dataclass
class ArchiveEntry:
    """One file inside an archive, as the manifest recorded it."""

    name: str
    size: int
    sha256: str
    route: str      # "pipeline" | "store"
    reason: str     # why it was stored; empty for pipelined files


@dataclass
class ArchiveListing:
    archive: Path
    kind: str                 # "excmp" (foreign listing is G2)
    profile: str
    created_utc: str
    stages: list[str]
    entries: list[ArchiveEntry]

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries)


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


def compress(inputs: list[Path], out_path: Path, profile: Profile,
             ctx: StageContext, tools: dict[str, ToolInfo | None] | None = None) -> CompressResult:
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

    registry = _stage_factory()
    job_dir = Path(tempfile.mkdtemp(prefix="excmp-", dir=ctx.temp_dir))
    tmp_out: Path | None = None
    try:
        # --- split routes -------------------------------------------------
        pipe_route = next((r for r in the_plan.routes if r.action == "pipeline"), None)
        store_route = next((r for r in the_plan.routes if r.action == "store"), None)

        ledger: dict[str, dict] = {}
        for info in infos:
            ledger[relmap[info.path]] = {
                "size": info.size,
                "sha256": hash_file(info.path),
                "route": "pipeline" if pipe_route and info.path in set(pipe_route.files) else "store",
            }

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
                    params={},
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

    orig = sum(m["size"] for m in ledger.values())
    return CompressResult(
        archive=out_path,
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
    )


def extract_any(archive: Path, out_dir: Path, ctx: StageContext) -> ExtractResult:
    """Extract ours *or* somebody else's (G1).

    Deliberately a separate entry point from :func:`extract`, which stays
    .excmp-only. A caller that wants the ledger-verified path should not be
    able to get a best-effort one by accident, and vice versa - the difference
    is the entire value proposition.
    """
    archive = Path(archive)
    if is_excmp(archive):
        return extract(archive, out_dir, ctx)
    return _extract_foreign(archive, out_dir, ctx)


def _extract_foreign(archive: Path, out_dir: Path, ctx: StageContext) -> ExtractResult:
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
    SevenZipStage().extract(archive, out_dir, ctx)
    restored = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return ExtractResult(
        out_dir=out_dir,
        files_restored=restored,
        verified=0,
        elapsed_s=time.monotonic() - t0,
        ledger_backed=False,
    )


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
                current = stage.extract(current, dst, ctx)
                produced = _tree_size(current)
                if produced > stage_budget:
                    raise ContainerError(
                        f"stage '{sid}' produced {produced >> 20} MiB, far beyond "
                        f"the {stage_budget >> 20} MiB implied by the manifest "
                        f"ledger - refusing to continue")
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
