"""The router: decides, per file, whether compressing is worth it and how.

This is the component whose absence made the original prototype spend hours
on video files for 0% gain. Rules:

- Media (video/audio/image) -> ``store`` by default: lossless, quality
  untouched, honest about why. (A future opt-in shrink mode re-encodes.)
- Already-compressed data with near-8.0 bits/byte entropy -> ``store``,
  EXCEPT zip/gzip-family archives under a profile that has precomp, which
  can expand those streams and recompress them harder.
- Everything else -> the profile's stage chain, degraded to whatever tools
  are actually installed (with a warning per missing tool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .analyzer import Category, FileInfo
from .tools import ToolInfo

ENTROPY_STORE_THRESHOLD = 7.9  # bits/byte; above this LZMA gains ~nothing

_MEDIA = {Category.VIDEO, Category.AUDIO, Category.IMAGE}

# Chains are expressed as (stage_id, required_tool | None); zstd needs no tool.
_CHAINS: dict[str, list[tuple[str, str | None]]] = {
    "fast": [("zstd", None)],
    "normal": [("sevenzip", "7z")],
    "extreme": [("precomp", "precomp"), ("srep", "srep"), ("sevenzip", "7z")],
    # INSANE upgrades the final codec to zpaqfranz when a stage exists for it;
    # until then it is the extreme chain (a warning tells the user).
    "insane": [("precomp", "precomp"), ("srep", "srep"), ("sevenzip", "7z")],
}


class Profile(StrEnum):
    FAST = "fast"
    NORMAL = "normal"
    EXTREME = "extreme"
    INSANE = "insane"


@dataclass
class Route:
    files: list[Path]
    action: str  # "store" | "pipeline"
    stages: list[str]
    reason: str


@dataclass
class Plan:
    profile: Profile
    routes: list[Route]
    warnings: list[str] = field(default_factory=list)


def _resolve_chain(profile: Profile, tools: dict[str, ToolInfo | None]) -> tuple[list[str], list[str]]:
    stages: list[str] = []
    warnings: list[str] = []
    for stage_id, tool in _CHAINS[profile.value]:
        if tool is None or tools.get(tool) is not None:
            stages.append(stage_id)
        else:
            warnings.append(
                f"{profile.value}: stage '{stage_id}' skipped - tool '{tool}' not installed"
            )
    if profile is Profile.INSANE:
        warnings.append(
            "insane: zpaqfranz backend not integrated yet - using extreme chain"
        )
    if not stages:
        stages = ["zstd"]
        warnings.append(f"{profile.value}: no external tools found - fell back to zstd")
    return stages, warnings


def store_reason(info: FileInfo) -> str | None:
    """The plain-English sentence explaining why this file won't be piped,
    or None if it will be. Public because the GUI shows it per file - the
    route-level reason is a joined summary and loses the detail."""
    if info.category in _MEDIA:
        return (
            "media file: already compressed by its codec; stored losslessly so "
            "quality is untouched (enable Shrink mode to re-encode smaller)"
        )
    if info.entropy_bps >= ENTROPY_STORE_THRESHOLD:
        return (
            f"high-entropy data ({info.entropy_bps:.2f} bits/byte): "
            "already compressed or encrypted; recompression would gain ~0%"
        )
    return None


# Archive types whose inner streams precomp can expand and thus beat "store".
_PRECOMP_EXPANDABLE = {".zip", ".gz", ".jar", ".apk", ".docx", ".xlsx", ".pptx", ".pdf"}


def plan(infos: list[FileInfo], profile: Profile, tools: dict[str, ToolInfo | None],
         shrink_media: bool = False) -> Plan:
    stages, warnings = _resolve_chain(profile, tools)
    has_precomp = "precomp" in stages

    store_files: list[Path] = []
    store_reasons: list[str] = []
    pipe_files: list[Path] = []

    for info in infos:
        reason = store_reason(info)
        # precomp can expand zlib/deflate wrapped data no matter how random it
        # looks on the surface - exactly the shape of game pak files. Media
        # stays stored (its entropy is real), known non-deflate archives
        # (.rar/.7z/.zst) stay stored too.
        if reason is not None and has_precomp and info.category not in _MEDIA:
            if (info.zlib_stream
                    or info.category is Category.BINARY
                    or info.path.suffix.lower() in _PRECOMP_EXPANDABLE):
                reason = None
        if reason is not None:
            store_files.append(info.path)
            store_reasons.append(reason)
        else:
            pipe_files.append(info.path)

    routes: list[Route] = []
    if pipe_files:
        routes.append(Route(files=pipe_files, action="pipeline", stages=stages,
                            reason=f"profile '{profile.value}' chain: {' -> '.join(stages)}"))
    if store_files:
        routes.append(Route(files=store_files, action="store", stages=[],
                            reason="; ".join(dict.fromkeys(store_reasons))))
    return Plan(profile=profile, routes=routes, warnings=warnings)
