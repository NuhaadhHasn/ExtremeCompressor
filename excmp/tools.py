"""Discovery of the external CLI tools the engine can orchestrate.

Tools are looked up in well-known install locations first, then on PATH,
then in the app-managed ``tools/bin`` directory. A missing tool is not an
error at discovery time — profiles degrade gracefully; stages that need a
missing tool raise :class:`ToolMissingError` when actually used.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

APP_BIN = Path(__file__).resolve().parent.parent / "tools" / "bin"

CANDIDATES: dict[str, list[str]] = {
    "7z": [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"],
    "precomp": [r"C:\Program Files\precomp\windows\precomp.exe"],
    "srep": [r"C:\Program Files\srep\srep64.exe", r"C:\Program Files\srep\srep.exe"],
    "zpaqfranz": [],
    "zstd": [],
    "ffmpeg": [],
    "ffprobe": [],
}

_VERSION_ARGS: dict[str, list[str]] = {
    "7z": [],           # 7z prints a banner with no args
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
    "zstd": ["--version"],
    "zpaqfranz": [],
}


class ToolMissingError(RuntimeError):
    """Raised when a stage requires a tool that is not installed."""


@dataclass(frozen=True)
class ToolInfo:
    name: str
    path: str
    version: str = ""


def _probe_version(name: str, path: str) -> str:
    args = _VERSION_ARGS.get(name)
    if args is None:
        return ""
    try:
        proc = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
        first = (proc.stdout or proc.stderr).strip().splitlines()
        return first[0][:120] if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def find_tools(with_versions: bool = False) -> dict[str, ToolInfo | None]:
    """Locate every known tool. Returns a dict with an entry per tool name."""
    found: dict[str, ToolInfo | None] = {}
    for name, paths in CANDIDATES.items():
        located: str | None = None
        for p in paths:
            if Path(p).is_file():
                located = p
                break
        if located is None:
            app_exe = APP_BIN / f"{name}.exe"
            if app_exe.is_file():
                located = str(app_exe)
        if located is None:
            located = shutil.which(name)
        if located is None:
            found[name] = None
        else:
            version = _probe_version(name, located) if with_versions else ""
            found[name] = ToolInfo(name=name, path=located, version=version)
    return found


def require(tools: dict[str, ToolInfo | None], name: str) -> ToolInfo:
    tool = tools.get(name)
    if tool is None:
        raise ToolMissingError(
            f"'{name}' is required for this operation but was not found. "
            f"Install it or pick a profile that does not need it."
        )
    return tool
