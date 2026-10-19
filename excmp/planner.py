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
#
# SREP was removed from every chain on 2026-08-01 (roadmap B11). Two reasons,
# either sufficient: it failed a real restore on 1 of 3 runs over byte-identical
# input (intermittent checksum mismatch inside srep64.exe itself - see
# benchmarks/2026-08-01-estimator-backtest.md), and it is closed freeware in an
# OSI-clean project, already slated for replacement by zpaqfranz's dedup (B1).
# Its long-range-dedup job falls to LZMA2's dictionary until B1 lands. Archives
# that recorded an srep stage before this change still extract: the stage stays
# registered in the engine - it just is never planned again.
_CHAINS: dict[str, list[tuple[str, str | None]]] = {
    "fast": [("zstd", None)],
    "normal": [("sevenzip", "7z")],
    "extreme": [("precomp", "precomp"), ("sevenzip", "7z")],
    # INSANE swaps 7-Zip for zpaqfranz (B1): same place in the chain, but it
    # also brings unlimited-distance CDC dedup, which is what B11 took away
    # when SREP came out. Falls back to the extreme chain when zpaqfranz is
    # absent - see _FINAL_CODEC_FALLBACK.
    "insane": [("precomp", "precomp"), ("zpaqfranz", "zpaqfranz")],
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


#: Stages that emit something which is *not* a finished archive. Dropping a
#: missing tool's stage is fine anywhere else in a chain, but if the chain
#: ends on one of these the engine would publish an intermediate stream - a
#: .pcf or a .tar - as though it were the archive.
_INTERMEDIATE = {"precomp", "tar", "srep"}

#: When a final codec's tool is missing, what to try instead, in order.
_FINAL_CODEC_FALLBACK: list[tuple[str, str]] = [("sevenzip", "7z"), ("zstd", "")]


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
    # A chain that lost its final codec must borrow another one, not simply
    # run shorter. Insane is the case that made this necessary: without
    # zpaqfranz it degraded to ["precomp"], whose output is an intermediate
    # precomp stream, and the engine would have published that as the archive.
    if stages and stages[-1] in _INTERMEDIATE:
        for stage_id, tool in _FINAL_CODEC_FALLBACK:
            if not tool or tools.get(tool) is not None:
                stages.append(stage_id)
                warnings.append(
                    f"{profile.value}: falling back to '{stage_id}' as the final codec"
                )
                break
        else:
            stages = [s for s in stages if s not in _INTERMEDIATE]
    if not stages:
        stages = ["zstd"]
        warnings.append(f"{profile.value}: no external tools found - fell back to zstd")
    return stages, warnings


def resolved_chain(profile: Profile, tools: dict[str, ToolInfo | None]) -> list[str]:
    """The stages ``profile`` will really run on this machine.

    Public because degradation collapses profiles together: with Precomp
    absent, Extreme resolves to Normal's chain exactly, and anything that
    *measures* a profile (I6) would otherwise run the same work twice and
    report two independent-looking numbers for one chain.
    """
    return _resolve_chain(profile, tools)[0]


def store_reason(info: FileInfo) -> str | None:
    """The plain-English sentence explaining why this file won't be piped,
    or None if it will be. Public because the GUI shows it per file - the
    route-level reason is a joined summary and loses the detail."""
    if info.path.suffix.lower() in _UNCOMPRESSED_AUDIO:
        # B4: a WAV is NOT "already compressed by its codec" - it has no
        # codec. Saying so was false, and it was shown to the user beside 0%
        # savings on 5.07 GiB of real audio. FLAC gets 43.15% on it, byte for
        # byte, so what the file needs is a specialist rather than an excuse.
        from . import flacaudio
        if flacaudio.available():
            return ("uncompressed PCM audio: packed with FLAC, which restores "
                    "it byte for byte (measured ~43% smaller)")
        return ("uncompressed PCM audio: stored as-is because the FLAC tool "
                "is not installed - fetching it would shrink this ~43% with "
                "no loss")
    if info.path.suffix.lower() in _OGG_AUDIO:
        # B13: with balrogg installed an Ogg file is not piped at all. It
        # stays on the store route and is packed there, like a WAV with FLAC:
        # 13.358% smaller on 18 real music files, byte-identical, where piping
        # them through 7-Zip saved 1.112% (B13a). Checked before the probe
        # rule below, which only applies when the specialist is absent.
        from . import oggpack
        if oggpack.available():
            return ("Ogg audio: repacked with balrogg where it can be, which "
                    "restores it byte for byte (measured 4-15% smaller); a "
                    "file it declines is stored as-is")
    if (info.path.suffix.lower() in _PROBE_DECIDES
            and info.sample_ratio_max < 1.0):
        # B13, measured on 18 real music files: the Ogg files the probe
        # could shrink compressed 1.7-6.0% under 7-Zip, byte-identically, and
        # the ones it could not stayed within 1.24% (the five Opus files at
        # ~0%). B18 found the same split on MP3 and MP4 (see _PROBE_DECIDES).
        # Checked before the entropy rule on purpose: container framing makes
        # the bytes look random, and the probe is a measurement of this file
        # rather than a statistic about it.
        return None
    if info.lepton_refuses:
        # B19. Only seen where the file stays stored: on a chain with Precomp
        # `plan()` pipes it to packJPG and this reason is overridden.
        return ("JPEG that lepton can't pack (CMYK, or a side over 16,386 px): "
                "stored as-is on this profile; where Precomp is installed, "
                "Extreme recodes it losslessly (measured 24-61% smaller), and "
                "Insane runs the same Precomp step")
    if image_format(info) in _PRECOMP_IMAGES:
        # B21 (review): only seen where the file stays stored. On a chain with
        # Precomp `plan()` pipes it, so this never shows beside Extreme.
        return ("PNG or GIF image: stored as-is on this profile; where Precomp "
                "is installed, Extreme recodes it losslessly (measured 7-38% "
                "smaller)")
    if info.category in _MEDIA:
        return (
            "media file: already compressed by its codec; stored losslessly so "
            "quality is untouched (enable Shrink mode to re-encode smaller)"
        )
    if info.expandable and info.entropy_bps >= ENTROPY_STORE_THRESHOLD:
        # B20. Its bytes look random because they are deflate output, which
        # Precomp reverses; on a chain with Precomp `plan()` pipes it.
        return ("container of deflated files (zip, EPUB, Office, PDF...): "
                "stored as-is on this profile; where Precomp is installed, "
                "Extreme expands and recompresses it losslessly (measured "
                "11-64% smaller per file)")
    if info.entropy_bps >= ENTROPY_STORE_THRESHOLD:
        return (
            f"high-entropy data ({info.entropy_bps:.2f} bits/byte): "
            "already compressed or encrypted; recompression would gain ~0%"
        )
    return None


# Archive types whose inner streams precomp can expand and thus beat "store".
# B20: no longer the only door. Any file the analyzer's structural probe calls
# `expandable` (a zip with deflated, unencrypted members, or a PDF with Flate
# streams) is piped too; this list stays for what the probe can't see, such
# as `.gz`, a single deflate stream rather than a zip.
_PRECOMP_EXPANDABLE = {".zip", ".gz", ".jar", ".apk", ".docx", ".xlsx", ".pptx", ".pdf"}

#: Images whose high entropy is a **layer Precomp undoes**, not real
#: randomness: the one exception to the "media stays stored" rule, because
#: Precomp expands the layer and reconstructs the original bytes exactly.
#: Matched by content (`FileInfo.image_format`, B21), not by name.
#:
#: PNG (B3) is deflate all the way down. Measured on 15 real PNGs: stored
#: 3,522,560 bytes; `precomp -> 7z` **2,152,650**, a 38.9% saving with a
#: byte-identical restore. For comparison `oxipng` — which the roadmap
#: originally specified — managed 31.8% and produced **zero** byte-identical
#: files, because it rewrites the image to a smaller encoding. That is
#: pixel-lossless, not byte-lossless, so it cannot satisfy a SHA-256 ledger
#: and belongs in Phase C beside the AV1 re-encoder.
#:
#: GIF (B21, 2026-10-19) is LZW, which Precomp recodes too (`-t` lists
#: "F = GIF"). `precomp -cn -intense` then 7-Zip, file by file, every file
#: restored: **25.66%** off 64 GIFs from Downloads (30.0 MB) and **6.85%**
#: off 24 from Downloads-1 (6.0 MB), against 0% stored. Precomp couldn't
#: re-create the LZW of 28 of the 88, and those pass through (2.1% smaller
#: under 7-Zip). Over 1 KB, two it did recode came out *bigger*, 1.176 and
#: 1.254 of 72 KB and 18 KB: noisy frames whose LZW beat LZMA on the raw
#: pixels. 90 KB of 36 MB, and nothing cheap tells them apart. (Under 1 KB,
#: per file, 7-Zip's own container outweighs the GIF; a solid archive pays
#: that once.)
#:
#: Kept deliberately tiny. JPEG must NOT be here: its entropy is real, and it
#: has its own specialist on the stored route (B2/lepton).
_PRECOMP_IMAGES = {"png", "gif"}

#: What a name says, for a FileInfo nobody read (`image_format` is None).
_IMAGE_SUFFIXES = {".png": "png", ".gif": "gif"}


def image_format(info: FileInfo) -> str:
    """``"png"``, ``"gif"`` or ``""``: what the file's first bytes said, or
    its name when nobody read them (a hand-built FileInfo).

    By content because the store route claims a JPEG by content: keyed on
    the name, the two disagreed on 278 files on the owner's drives (B21).
    """
    if info.image_format is not None:
        return info.image_format
    return _IMAGE_SUFFIXES.get(info.path.suffix.lower(), "")


#: Media a chain *with Precomp* pipes whatever its probe says, because Precomp
#: itself recompresses it losslessly: PNG and GIF (above, by content), and MP3,
#: which Precomp v0.4.7 recodes with its built-in packMP3 (`-t` lists
#: "3 = MP3"). The probe cannot see packMP3's gain: it measures what zstd
#: finds. End to end at Extreme, every file restored (B18, 2026-10-16):
#:
#:                  Normal (probe)   Extreme (probe)   Extreme, every MP3
#:     MP3 music         2.98%           13.69%            18.02%
#:     MP3 misc         11.22%            8.42%            15.87%
#:
#: Without Precomp (Fast, Normal) an MP3 is left to the probe rule.
_PRECOMP_MEDIA = {".mp3"}

#: Audio containers holding **uncompressed** PCM (B4).
#:
#: These are `Category.AUDIO` and therefore in `_MEDIA`, which is what made
#: the engine store them and tell the user they were "already compressed by
#: its codec". They are not compressed at all, and their entropy does not
#: reveal it: real music measures 7.7-7.9 bits/byte, which every entropy
#: heuristic reads as incompressible. Only knowing the *format* tells you that
#: an audio predictor will take 43% off.
#:
#: This is the audio twin of `_PRECOMP_IMAGES` above, and it is a separate set
#: because the remedy is different: a PNG is routed *into* the pipeline for
#: Precomp to expand, whereas a WAV stays on the store route and is packed
#: there by `flacaudio`, the way B2 packs a JPEG with lepton.
_UNCOMPRESSED_AUDIO = {".wav", ".aiff", ".aif", ".w64", ".rf64"}

#: Ogg audio containers (Vorbis, Opus), the one compressed-media family that
#: has been measured (B13). With balrogg installed an Ogg file stays on the
#: store route and is repacked there (`oggpack`, `store_reason`); without it,
#: one whose own probe says it shrinks is piped (B13a,
#: tests/test_b13_ogg_probe.py). Every other media file keeps "stored as-is"
#: until its format is measured too.
from .oggpack import SUFFIXES as _OGG_AUDIO  # noqa: E402  (one set, two readers)

#: Compressed media whose own probe decides whether it is piped: B13a's Ogg,
#: plus MP3 and MP4 since B18, and MOV since B19. Measured under 7-Zip,
#: every file restored, the files the probe flagged against the ones it did
#: not (group totals; per file the groups overlap, 0.17% flagged to 5.81%
#: not):
#:
#:     MP3, music (5)              4.17% saved    0.35%
#:     MP3, misc (16)              5.24%          0.45%
#:     phone video, MP4 (51)       9.20%          1.61%
#:     downloaded video, MP4 (9)   3.77%          0.32%
#:     Takeout MOV (64)            1.01%          0.046%   (B19)
#:     Downloads-1 MOV (2)         none flagged   0.015%   (B19)
#:
#: An MP3 on a chain with Precomp is piped regardless (`_PRECOMP_MEDIA`).
#: Every other container (MKV, WebM, M4A...) keeps "stored as-is" until it
#: is measured too: sharing a codec with MP4 is not the same as having been
#: looked at. With balrogg installed an Ogg file never reaches this rule
#: (`store_reason` packs it first).
_PROBE_DECIDES = _OGG_AUDIO | {".mp3", ".mp4", ".mov"}

#: How far Precomp inflates its output mid-pipeline, per data type. The
#: generic figure is 5x (research/10 C-3), but **PNG measured ~50x** — 15 PNGs
#: took a 3.5 MB tar to a 177 MB .pcf — because a PNG is deflate all the way
#: down and expanding it yields raw pixels. Budgeting 5x for a PNG folder
#: under-reserves temp by an order of magnitude, and running out of temp
#: mid-pipeline is exactly what the preflight exists to prevent.
#:
#: B20 (review): the containers it pipes by structure, measured the same way,
#: `.pcf` over input: EPUB 18.2x byte-weighted (9.4-96.7x per file: they carry
#: PNGs), ODT/ODS 10.4x (6.3-16.5x). AAR, APPX and NuGet came to ~3x, inside
#: the default.
#:
#: B21: a PNG is one by content, like its routing. GIF came to 2.02x
#: byte-weighted over 88 real files (2.12x over the 63 Precomp wrote a .pcf
#: for), inside the default; one 1600x1124 single frame reached 27.5x alone.
_INFLATION_PNG = 50
_INFLATION_BY_EXT = {".epub": 20, ".odt": 12, ".ods": 12, ".odp": 12}
_INFLATION_DEFAULT = 5


def _inflation(info: FileInfo) -> int:
    if image_format(info) == "png":
        return _INFLATION_PNG
    return _INFLATION_BY_EXT.get(info.path.suffix.lower(), _INFLATION_DEFAULT)


def precomp_inflation(infos: list[FileInfo]) -> int:
    """Worst-case temp multiplier for this input, weighted by bytes.

    Byte-weighted rather than worst-file, so a folder that is 1% PNG does not
    reserve as though it were all PNG - a preflight that refuses jobs which
    would have succeeded gets switched off, and then it protects nobody.
    """
    total = sum(i.size for i in infos)
    if not total:
        return _INFLATION_DEFAULT
    weighted = sum(i.size * _inflation(i) for i in infos)
    return max(_INFLATION_DEFAULT, round(weighted / total))


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
        # PNG and GIF are the media whose entropy is a layer Precomp undoes
        # rather than real, so they get the override the rest of _MEDIA is
        # denied (B3, B21), by content. A JPEG lepton will refuse joins
        # them (B19): the store route would keep it raw, and Precomp's
        # packJPG recodes it losslessly.
        deflate_media = (image_format(info) in _PRECOMP_IMAGES
                         or info.path.suffix.lower() in _PRECOMP_MEDIA
                         or info.lepton_refuses)
        if reason is not None and has_precomp and (
                info.category not in _MEDIA or deflate_media):
            if (deflate_media
                    or info.zlib_stream
                    or info.category is Category.BINARY
                    or info.expandable          # B20: by structure, not name
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
