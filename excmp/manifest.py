"""The .excmp container: a STORED zip holding manifest.json + one payload blob.

The manifest records the exact stage chain (in the order it ran), tool
versions, and a SHA-256 ledger of every original input file, so extraction
can replay the chain in reverse and prove the restore is byte-identical.
The zip layer is STORED (no compression) because the payload is already
maximally compressed by the final stage.
"""

from __future__ import annotations

import json
import stat
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .safepath import UnsafePathError, resolve_within, safe_relpath

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"

# manifest.json is parsed before anything in it can be validated, so an
# unbounded json.loads on attacker-supplied bytes is a free memory bomb.
MAX_MANIFEST_BYTES = 8 << 20

# Floor for the payload budget, so tiny archives (where container overhead
# dominates the declared size) are not tripped up by their own arithmetic.
_PAYLOAD_FLOOR_BYTES = 64 << 20


class ContainerError(RuntimeError):
    """Raised when an archive is not a valid .excmp container."""


@dataclass
class StageRecord:
    stage: str
    tool_name: str
    tool_version: str
    params: dict


@dataclass
class Manifest:
    schema: int
    created_utc: str
    profile: str
    stages: list[StageRecord]
    inputs: dict[str, dict]
    payload_name: str
    warnings: list[str] = field(default_factory=list)
    routes: list[dict] = field(default_factory=list)
    # relpath -> why THIS file was stored. The route-level reason is a joined
    # summary of every distinct reason in the group, so attributing it to an
    # individual file says "7.99 bits/byte; 7.98 bits/byte" about a file that
    # measured one of them. Defaulted, so archives written before this field
    # existed still load - `from_json` passes **data and the default fills in.
    store_reasons: dict[str, str] = field(default_factory=dict)

    @classmethod
    def new(cls, profile: str, stages: list[StageRecord], inputs: dict[str, dict],
            payload_name: str, warnings: list[str] | None = None,
            routes: list[dict] | None = None,
            store_reasons: dict[str, str] | None = None) -> "Manifest":
        return cls(
            schema=SCHEMA_VERSION,
            created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            profile=profile,
            stages=stages,
            inputs=inputs,
            payload_name=payload_name,
            warnings=warnings or [],
            routes=routes or [],
            store_reasons=store_reasons or {},
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        data = json.loads(text)
        data["stages"] = [StageRecord(**s) for s in data.get("stages", [])]
        return cls(**data)


STORED_PREFIX = "stored/"


def declared_total(ledger: dict[str, dict]) -> int:
    """Total restored size the manifest's own ledger promises."""
    return sum(int(meta.get("size", 0)) for meta in ledger.values())


def _payload_budget(ledger: dict[str, dict]) -> int:
    """Ceiling for the payload blob at the zip layer.

    The payload is the *final compressed* artifact, so it should never exceed
    the data it restores to by more than container overhead -- even for wholly
    incompressible input, where the final stage roughly breaks even.
    """
    return int(declared_total(ledger) * 1.1) + _PAYLOAD_FLOOR_BYTES


def _copy_bounded(src, dst, limit: int, what: str) -> int:
    """Copy at most ``limit`` bytes, refusing the moment one more appears.

    The bound is enforced on the real stream rather than on the zip header,
    because a header is just more attacker-supplied data. Reading ``limit + 1``
    is what turns a lie into a refusal instead of a disk full of it.
    """
    written = 0
    while True:
        chunk = src.read(min(1 << 20, limit - written + 1))
        if not chunk:
            return written
        written += len(chunk)
        if written > limit:
            raise ContainerError(
                f"{what} is larger than the {limit} bytes the manifest declares"
            )
        dst.write(chunk)


def write_container(archive_path: Path, manifest: Manifest,
                    payload_path: Path | None = None,
                    stored_files: dict[str, Path] | None = None) -> None:
    """Write the container. ``stored_files`` maps relpath -> source path for
    files that skip the pipeline; they land as ZIP_STORED ``stored/<relpath>``
    entries so no time is wasted recompressing them.

    Every archive-supplied name is validated *before* the file is created, so
    we can never produce an archive our own reader would refuse -- a container
    that is dead on arrival is a worse outcome than a clear failure here.
    """
    archive_path = Path(archive_path)
    for key in manifest.inputs:
        safe_relpath(key)
    if manifest.payload_name:
        safe_relpath(manifest.payload_name)
    stored_norm = {str(safe_relpath(rel)): src
                   for rel, src in (stored_files or {}).items()}

    # G9: identical files are written once.
    #
    # Two ledger entries with the same SHA-256 are the same bytes, and we have
    # already paid for that hash - it *is* the ledger. So the first entry of
    # each hash carries the bytes and the rest carry a `same_as` pointing at
    # it. Measured worth: a corpus that was 49% duplicates compressed by ~5%
    # before this, because the duplicated files were high-entropy and so were
    # stored verbatim, where no compressor could ever see them
    # (benchmarks/2026-09-02).
    #
    # Only *stored* entries are considered. A pipelined file is inside the
    # payload, where the codec's own dedup applies and this pointer means
    # nothing. A file with no recorded hash is never deduplicated: an empty
    # `sha256` means "we do not know", which is not a statement about equality.
    first_by_hash: dict[str, str] = {}
    for rel in stored_norm:
        digest = str(manifest.inputs.get(rel, {}).get("sha256", ""))
        if not digest:
            continue
        if digest in first_by_hash:
            manifest.inputs[rel]["same_as"] = first_by_hash[digest]
        else:
            first_by_hash[digest] = rel

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=True) as zf:
        # The manifest goes in first and now carries the `same_as` pointers,
        # so the dedup pass above has to run before this line.
        zf.writestr(MANIFEST_NAME, manifest.to_json())
        if payload_path is not None:
            zf.write(payload_path, arcname=manifest.payload_name)
        for rel, src in stored_norm.items():
            if "same_as" in manifest.inputs.get(rel, {}):
                continue
            zf.write(src, arcname=STORED_PREFIX + rel)


def _read_manifest(zf: zipfile.ZipFile, archive_path: Path) -> Manifest:
    try:
        info = zf.getinfo(MANIFEST_NAME)
    except KeyError as exc:
        raise ContainerError(f"{archive_path} has no {MANIFEST_NAME}") from exc
    if info.file_size > MAX_MANIFEST_BYTES:  # cheap fail-fast on the header
        raise ContainerError(
            f"{MANIFEST_NAME} declares {info.file_size} bytes, over the "
            f"{MAX_MANIFEST_BYTES} byte limit")
    with zf.open(info) as fh:
        raw = fh.read(MAX_MANIFEST_BYTES + 1)   # authoritative: the real stream
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ContainerError(
            f"{MANIFEST_NAME} is larger than the {MAX_MANIFEST_BYTES} byte limit")
    try:
        return Manifest.from_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ContainerError(
            f"{archive_path} has a malformed {MANIFEST_NAME}: {exc}") from exc


def read_container(archive_path: Path, extract_dir: Path) -> tuple[Manifest, Path | None]:
    """Read manifest and extract the payload blob (if any) to ``extract_dir``."""
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(archive_path):
        raise ContainerError(f"{archive_path} is not an .excmp container")
    with zipfile.ZipFile(archive_path) as zf:
        manifest = _read_manifest(zf, archive_path)
        if not manifest.payload_name:
            return manifest, None
        # payload_name is attacker-controlled: joined naively, "C:/x" would
        # discard extract_dir entirely and hand back an arbitrary path.
        target = resolve_within(extract_dir, manifest.payload_name)
        try:
            info = zf.getinfo(manifest.payload_name)
        except KeyError as exc:
            raise ContainerError(
                f"{archive_path} declares payload '{manifest.payload_name}' "
                f"but does not contain it") from exc
        budget = _payload_budget(manifest.inputs)
        if info.file_size > budget:
            raise ContainerError(
                f"payload declares {info.file_size} bytes, beyond the {budget} "
                f"byte budget implied by the manifest ledger")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(info) as src, target.open("wb") as dst:
                _copy_bounded(src, dst, budget, "payload")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return manifest, target


def extract_stored(archive_path: Path, out_dir: Path,
                   ledger: dict[str, dict],
                   only: set[str] | None = None) -> list[Path]:
    """Extract every ``stored/`` entry into ``out_dir`` (prefix removed).

    ``ledger`` is ``manifest.inputs`` and is **required**: it is what makes the
    bomb defense exact rather than heuristic. The manifest already declares
    every file's name and byte count, so each entry is capped at precisely the
    size it claims, and an entry nobody declared is refused outright.

    ``only`` narrows what is **written** (G2's selective extract) and
    deliberately does *not* narrow what is checked. Every entry in the
    container is still validated against the full ledger on the way past, so
    a selective restore cannot be used to walk an archive that a full one
    would have refused - the bomb bound, the duplicate check and the
    undeclared-entry check all still see everything.
    """
    out_dir = Path(out_dir)
    written: list[Path] = []
    seen: set[str] = set()
    total = 0
    budget = declared_total(ledger)
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if not info.filename.startswith(STORED_PREFIX) or info.is_dir():
                continue
            rel = info.filename[len(STORED_PREFIX):]
            key = str(safe_relpath(rel))
            # Only the file-type bits are meaningful here, and only when the
            # archive actually recorded them: a zip may carry no Unix mode at
            # all, or permission bits with no type (what writestr produces).
            # Absent type bits means "unspecified", which we read as a regular
            # file; a type that is present and says symlink or device is a
            # deliberate attempt to plant something we would later follow.
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type and file_type != stat.S_IFREG:
                raise UnsafePathError(
                    f"stored entry {key!r} is not a regular file "
                    f"(type bits {file_type:#o})")
            if key in seen:
                # A zip may carry two entries with one name. Whichever we hash
                # last, the other already reached the disk.
                raise ContainerError(f"duplicate stored entry {key!r}")
            seen.add(key)
            meta = ledger.get(key)
            if meta is None:
                raise ContainerError(
                    f"stored entry {key!r} is not declared in the manifest ledger")
            declared = int(meta.get("size", 0))
            if info.file_size > declared:
                raise ContainerError(
                    f"stored entry {key!r} declares {info.file_size} bytes but "
                    f"the ledger says {declared}")
            total += declared
            if total > budget or len(written) >= len(ledger) + 1:
                # Belt-and-braces: ledger membership plus the dedup above
                # already bound this, but a future refactor might loosen one.
                raise ContainerError("stored entries exceed the manifest ledger")
            if only is not None and key not in only:
                # Validated, counted against the bomb budget, and then not
                # written. The checks above are the point of walking past it.
                continue
            target = resolve_within(out_dir, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src, target.open("wb") as dst:
                    got = _copy_bounded(src, dst, declared,
                                        f"stored entry {key!r}")
                if got != declared:
                    raise ContainerError(
                        f"stored entry {key!r} holds {got} bytes, the ledger "
                        f"declares {declared}")
            except BaseException:
                # Never leave a truncated file behind on refusal.
                target.unlink(missing_ok=True)
                raise
            written.append(target)

        # G9 second pass: entries whose bytes live under another entry's name.
        #
        # Read from the zip rather than from whatever landed on disk, so a
        # selective extract that asks only for the duplicate still works.
        for key, meta in ledger.items():
            source_key = meta.get("same_as")
            if not source_key:
                continue
            if only is not None and key not in only:
                continue
            source_meta = ledger.get(source_key)
            if source_meta is None:
                raise ContainerError(
                    f"stored entry {key!r} claims to duplicate "
                    f"{source_key!r}, which is not in the ledger")
            # One hop, never a chain. A chain that terminates is still a
            # reader an archive can walk, and nothing we write ever emits one
            # - the writer always points at the *first* entry for that hash.
            # This is also what makes a cycle impossible rather than merely
            # bounded.
            if source_meta.get("same_as"):
                raise ContainerError(
                    f"stored entry {key!r} points at {source_key!r}, which is "
                    f"itself a duplicate - chains are not followed")
            # The pointer is a claim; the hashes are the evidence. Believing
            # the pointer over them would let an archive serve one file's
            # bytes under another file's name *and* another file's hash.
            if (not source_meta.get("sha256")
                    or source_meta.get("sha256") != meta.get("sha256")
                    or int(source_meta.get("size", -1)) != int(meta.get("size", -2))):
                raise ContainerError(
                    f"stored entry {key!r} claims to duplicate {source_key!r} "
                    f"but their ledger hashes or sizes disagree")
            member = STORED_PREFIX + str(safe_relpath(source_key))
            try:
                info = zf.getinfo(member)
            except KeyError:
                raise ContainerError(
                    f"stored entry {key!r} duplicates {source_key!r}, whose "
                    f"bytes are not in the archive") from None
            declared = int(meta.get("size", 0))
            target = resolve_within(out_dir, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src, target.open("wb") as dst:
                    got = _copy_bounded(src, dst, declared,
                                        f"stored entry {key!r}")
                if got != declared:
                    raise ContainerError(
                        f"stored entry {key!r} holds {got} bytes, the ledger "
                        f"declares {declared}")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            written.append(target)
    return written
