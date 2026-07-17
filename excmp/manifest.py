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

    @classmethod
    def new(cls, profile: str, stages: list[StageRecord], inputs: dict[str, dict],
            payload_name: str, warnings: list[str] | None = None) -> "Manifest":
        return cls(
            schema=SCHEMA_VERSION,
            created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            profile=profile,
            stages=stages,
            inputs=inputs,
            payload_name=payload_name,
            warnings=warnings or [],
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        data = json.loads(text)
        data["stages"] = [StageRecord(**s) for s in data.get("stages", [])]
        return cls(**data)


def write_container(archive_path: Path, manifest: Manifest, payload_path: Path) -> None:
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(MANIFEST_NAME, manifest.to_json())
        zf.write(payload_path, arcname=manifest.payload_name)


def read_container(archive_path: Path, extract_dir: Path) -> tuple[Manifest, Path]:
    """Read manifest and extract the payload blob to ``extract_dir``."""
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
        zf.extract(manifest.payload_name, extract_dir)
    return manifest, extract_dir / manifest.payload_name
