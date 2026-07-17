"""The .excmp container: a STORED zip holding manifest.json + one payload blob.

The manifest records the exact stage chain (in the order it ran), tool
versions, and a SHA-256 ledger of every original input file, so extraction
can replay the chain in reverse and prove the restore is byte-identical.
The zip layer is STORED (no compression) because the payload is already
maximally compressed by the final stage.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"


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

    @classmethod
    def new(cls, profile: str, stages: list[StageRecord], inputs: dict[str, dict],
            payload_name: str, warnings: list[str] | None = None,
            routes: list[dict] | None = None) -> "Manifest":
        return cls(
            schema=SCHEMA_VERSION,
            created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            profile=profile,
            stages=stages,
            inputs=inputs,
            payload_name=payload_name,
            warnings=warnings or [],
            routes=routes or [],
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        data = json.loads(text)
        data["stages"] = [StageRecord(**s) for s in data.get("stages", [])]
        return cls(**data)


STORED_PREFIX = "stored/"


def write_container(archive_path: Path, manifest: Manifest,
                    payload_path: Path | None = None,
                    stored_files: dict[str, Path] | None = None) -> None:
    """Write the container. ``stored_files`` maps relpath -> source path for
    files that skip the pipeline; they land as ZIP_STORED ``stored/<relpath>``
    entries so no time is wasted recompressing them."""
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=True) as zf:
        zf.writestr(MANIFEST_NAME, manifest.to_json())
        if payload_path is not None:
            zf.write(payload_path, arcname=manifest.payload_name)
        for rel, src in (stored_files or {}).items():
            zf.write(src, arcname=STORED_PREFIX + rel.replace("\\", "/"))


def read_container(archive_path: Path, extract_dir: Path) -> tuple[Manifest, Path | None]:
    """Read manifest and extract the payload blob (if any) to ``extract_dir``."""
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(archive_path):
        raise ContainerError(f"{archive_path} is not an .excmp container")
    with zipfile.ZipFile(archive_path) as zf:
        try:
            manifest = Manifest.from_json(zf.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError as exc:
            raise ContainerError(f"{archive_path} has no {MANIFEST_NAME}") from exc
        if manifest.payload_name:
            zf.extract(manifest.payload_name, extract_dir)
            return manifest, extract_dir / manifest.payload_name
    return manifest, None


def extract_stored(archive_path: Path, out_dir: Path) -> list[Path]:
    """Extract every ``stored/`` entry into ``out_dir`` (prefix removed)."""
    out_dir = Path(out_dir)
    written: list[Path] = []
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if not info.filename.startswith(STORED_PREFIX) or info.is_dir():
                continue
            rel = info.filename[len(STORED_PREFIX):]
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            written.append(target)
    return written
