"""File analysis: what is this file, and is it worth compressing?

Detection order: magic bytes (reliable) -> extension (fallback) -> BINARY.
``sample_entropy`` measures Shannon entropy in bits/byte over up to three
1 MiB samples (head/middle/tail); ~8.0 means already-compressed/encrypted
data that no lossless codec will shrink.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Category(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    COMPRESSED_ARCHIVE = "compressed_archive"
    EXECUTABLE = "executable"
    TEXT = "text"
    BINARY = "binary"


# (offset, magic bytes) -> category. Checked longest-match wins is not needed;
# these signatures are unambiguous at their offsets.
_MAGIC: list[tuple[int, bytes, Category]] = [
    (4, b"ftyp", Category.VIDEO),              # MP4/MOV family
    (0, b"\x1a\x45\xdf\xa3", Category.VIDEO),  # Matroska/WebM
    (0, b"ID3", Category.AUDIO),
    (0, b"fLaC", Category.AUDIO),
    (0, b"OggS", Category.AUDIO),
    (0, b"\xff\xd8\xff", Category.IMAGE),      # JPEG
    (0, b"\x89PNG", Category.IMAGE),
    (0, b"GIF8", Category.IMAGE),
    (0, b"PK\x03\x04", Category.COMPRESSED_ARCHIVE),  # zip/docx/apk...
    (0, b"7z\xbc\xaf\x27\x1c", Category.COMPRESSED_ARCHIVE),
    (0, b"Rar!", Category.COMPRESSED_ARCHIVE),
    (0, b"\x1f\x8b", Category.COMPRESSED_ARCHIVE),    # gzip
    (0, b"\x28\xb5\x2f\xfd", Category.COMPRESSED_ARCHIVE),  # zstd
    (0, b"\xfd7zXZ", Category.COMPRESSED_ARCHIVE),    # xz
    (0, b"MZ", Category.EXECUTABLE),
]

# RIFF containers share a magic; disambiguate by the format tag at offset 8.
_RIFF_FORMS = {b"AVI ": Category.VIDEO, b"WAVE": Category.AUDIO, b"WEBP": Category.IMAGE}

_EXT: dict[str, Category] = {
    **{e: Category.VIDEO for e in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v",
                                    ".mpg", ".mpeg", ".ts", ".flv", ".bik", ".bk2", ".usm")},
    **{e: Category.AUDIO for e in (".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac",
                                    ".wma", ".wem", ".fsb")},
    **{e: Category.IMAGE for e in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".dds",
                                    ".tga", ".heic")},
    **{e: Category.COMPRESSED_ARCHIVE for e in (".zip", ".7z", ".rar", ".gz", ".bz2", ".xz",
                                                 ".zst", ".cab", ".arc", ".excmp")},
    **{e: Category.EXECUTABLE for e in (".exe", ".dll", ".sys", ".so")},
    **{e: Category.TEXT for e in (".txt", ".md", ".json", ".xml", ".html", ".css", ".js",
                                   ".py", ".ini", ".cfg", ".log", ".csv", ".yaml", ".yml",
                                   ".srt", ".lua")},
}

_SAMPLE = 1_048_576


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    category: Category
    entropy_bps: float
    zlib_stream: bool = False  # starts with a valid zlib header (precomp food)


def _looks_like_zlib(head: bytes) -> bool:
    # zlib header: CMF=0x78 (deflate, 32K window) and (CMF<<8|FLG) % 31 == 0
    return len(head) >= 2 and head[0] == 0x78 and ((head[0] << 8) | head[1]) % 31 == 0


def _detect_category(path: Path, head: bytes) -> Category:
    for offset, magic, cat in _MAGIC:
        if head[offset:offset + len(magic)] == magic:
            return cat
    if head[:4] == b"RIFF" and len(head) >= 12:
        form = _RIFF_FORMS.get(head[8:12])
        if form:
            return form
    ext_cat = _EXT.get(path.suffix.lower())
    if ext_cat:
        return ext_cat
    # Heuristic: mostly printable head -> text
    if head and sum(32 <= b < 127 or b in (9, 10, 13) for b in head) / len(head) > 0.95:
        return Category.TEXT
    return Category.BINARY


def sample_entropy(path: Path, sample: int = _SAMPLE) -> float:
    """Shannon entropy in bits/byte over up to 3 samples (head/middle/tail)."""
    size = path.stat().st_size
    if size == 0:
        return 0.0
    counts: Counter[int] = Counter()
    total = 0
    with path.open("rb") as fh:
        offsets = {0}
        if size > sample * 3:
            offsets.update({size // 2, size - sample})
        for off in sorted(offsets):
            fh.seek(off)
            chunk = fh.read(sample)
            counts.update(chunk)
            total += len(chunk)
    if total == 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def analyze_file(path: Path) -> FileInfo:
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(4096)
    return FileInfo(
        path=path,
        size=size,
        category=_detect_category(path, head),
        entropy_bps=sample_entropy(path),
        zlib_stream=_looks_like_zlib(head),
    )


def analyze_tree(root: Path) -> list[FileInfo]:
    root = Path(root)
    if root.is_file():
        return [analyze_file(root)]
    return [analyze_file(p) for p in sorted(root.rglob("*")) if p.is_file()]
