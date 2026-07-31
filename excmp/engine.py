"""The engine: analyze -> plan -> run stage chain -> package -> verify.

Guarantees:
- inputs are never touched; outputs are written to ``<out>.tmp`` and
  atomically renamed only after the archive verifies;
- every original file's SHA-256 is recorded in the manifest, and
  ``extract`` re-checks the ledger before reporting success.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import FileInfo, analyze_tree
from .estimate import estimate_size
from .manifest import (ContainerError, Manifest, StageRecord, declared_total,
                       extract_stored, read_container, write_container)
from .planner import Plan, Profile, plan as make_plan
from .stages.base import Stage, StageContext, StageError, StageSkip
from .stages.sevenzip import SevenZipStage
from .stages.tarstage import TarStage
from .stages.zstdstage import ZstdStage
from .tools import ToolInfo, find_tools
from .verify import VerifyError, hash_file, verify_restore

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
    stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])
    inflation = _PRECOMP_INFLATION if "precomp" in stages else 1

    # Output: the .tmp twin, which is the whole archive. Use the pessimistic end
    # of the estimate - being wrong here means a disk-full failure late in a long
    # job, which is the outcome this function exists to prevent.
    # Temp: the staging copy of the piped files lives until the chain finishes,
    # and the tar that feeds the chain lives beside it. Precomp's output then
    # lands on top of both.
    needs: dict[int, tuple[Path, int, int]] = {}
    for probe, floor, peak in (
        (out_path.parent, size.high, size.high),
        (temp_dir, piped * 2, piped * (2 + inflation) if piped else 0),
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
        _self_test(tmp_out, manifest, registry, ctx, job_dir)
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


def _self_test(archive: Path, manifest: Manifest, registry: dict[str, Stage],
               ctx: StageContext, job_dir: Path) -> None:
    """Cheap integrity gate before publishing: test the payload container
    layer (7z t / zstd stream read) without a full restore."""
    if not manifest.payload_name:
        return
    test_dir = job_dir / "selftest"
    _, payload = read_container(archive, test_dir)
    assert payload is not None
    last = manifest.stages[-1].stage
    stage = registry[last]
    if hasattr(stage, "test"):
        stage.test(payload, ctx)  # type: ignore[attr-defined]
    else:
        probe = test_dir / "probe"
        stage.extract(payload, probe, ctx)
        shutil.rmtree(probe, ignore_errors=True)


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
