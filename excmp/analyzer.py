"""File analysis: what is this file, and is it worth compressing?

Detection order: magic bytes (reliable) -> extension (fallback) -> BINARY.
``sample_entropy`` measures Shannon entropy in bits/byte over up to three
1 MiB samples (head/middle/tail); ~8.0 means already-compressed/encrypted
data that no lossless codec will shrink.

The same read pass also *compresses* those samples (``sample_stats``), which
is what lets the estimator predict output size from a measurement rather than
a lookup table. Doing it here rather than in ``excmp.estimate`` is deliberate:
the samples are already in memory, and re-reading 3 MiB per file would double
the I/O on exactly the kind of slow external drive real corpora live on.

Two ratios come back, and the difference between them carries the signal.
An installer is a compressible stub in front of an incompressible payload, so
its head sample compresses well and its middle and tail do not. The *mean*
ratio therefore promises a win that never arrives; the *worst* sample is the
one that resembles the bulk of the file. Measured on the 2026-08-01 corpus:
predicting from the mean needed a 1.28x fudge factor to match reality, while
predicting from the worst sample needed only 0.95x.
"""

from __future__ import annotations

import math
import struct
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import zipfile
from pathlib import Path

import zstandard

from . import jpeg


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

# Cheap enough to run on every file during analysis, strong enough to rank
# compressibility. The gap between this and the real chains (LZMA2, Precomp) is
# what estimate.Rates.codec_factor corrects for.
_PROBE_LEVEL = 3


@dataclass(frozen=True)
class SampleStats:
    """What one pass over a file's samples tells us."""

    entropy_bps: float
    ratio: float      # packed/raw across all samples - the optimistic reading
    ratio_max: float  # the least compressible single sample - models the bulk
    sampled_bytes: int


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    category: Category
    entropy_bps: float
    zlib_stream: bool = False  # starts with a valid zlib header (precomp food)
    # Measured compressibility of the samples, 1.0 = incompressible. Defaults
    # are neutral so a hand-built FileInfo (tests, planner fixtures) stays valid.
    sample_ratio: float = 1.0
    sample_ratio_max: float = 1.0
    #: K2: the source file's modification time, in nanoseconds.
    #:
    #: Carried from the one `stat()` `analyze_file` already performs, rather
    #: than re-stat-ed in the engine - on a 55,000-file tree over a slow
    #: external drive that second walk is minutes, not milliseconds.
    #:
    #: ``0`` means "unknown", which is what a hand-built FileInfo (tests,
    #: planner fixtures) gets and what makes the field safe to add.
    mtime_ns: int = 0
    #: B5: does this file hold a deflate layer Precomp can actually expand?
    #:
    #: Structural, not statistical, and that is the whole point. `estimate.py`
    #: recorded "no cheap signal separates them" for whether Precomp will find
    #: anything, and for **entropy sampling** that is true - measured on 224
    #: real PDF/Office files, all 224 fail the `zlib_stream` test and their
    #: worst-sample ratios sit at 0.88-0.91, so the bytes honestly say
    #: "incompressible" while `precomp -> 7z` took 50.36% off them.
    #:
    #: An extension list is not sufficient either: 37% of the estimator's own
    #: backtest corpus is a 263 MB **encrypted** `.zip` that measured 2.97%.
    #: So this reads the container - a zip's central directory member flags,
    #: or a bounded head scan for a PDF - and answers for the file in hand.
    expandable: bool = False
    #: B19: a JPEG whose frame header says lepton will refuse it (CMYK, or a
    #: side over 16,386 px; `jpeg.lepton_refuses`). The store route would keep
    #: it raw, so a chain with Precomp pipes it to packJPG instead: 24.5-60.6%
    #: smaller on 16 real files, against 0%.
    lepton_refuses: bool = False
    #: B19: the file *is* a JPEG, by its first bytes. The store route hands
    #: lepton every file whose head says JPEG, whatever it is called, so the
    #: estimate has to ask the same question: one corpus here held 43 PNGs
    #: named `.jpg`, which a suffix test would have priced as photos.
    is_jpeg: bool = False
    #: B19(d): UTF-8 length of the name the archive gives this file
    #: (`archive_name`), which a stored file's zip entry carries twice.
    #: ``0`` means unknown (no root was given), and the estimate then falls
    #: back to the basename.
    arc_name_bytes: int = 0


#: Containers built out of a zip: their members are individually deflated, so
#: Precomp can expand each one - unless they are encrypted.
_ZIP_FAMILY = {".zip", ".docx", ".xlsx", ".pptx", ".jar", ".apk", ".odt",
               ".ods", ".odp", ".epub"}

#: How far into a PDF to look for a Flate stream. PDFs scatter their streams
#: through the body, so offset 0 says nothing - but 11 of 12 real PDFs
#: sampled declare one inside the first 64 KiB, and reading more than that per
#: file is not free on a 55,000-file tree over an external drive. The one that
#: does not is an image-only scan, which genuinely has nothing to expand; the
#: estimate's optimistic end covers being wrong about it.
_PDF_SCAN_BYTES = 64 << 10


#: B20 review: the largest central directory the probe will read. An honest
#: one costs ~50 bytes per member, so this is ~600,000 members; a corrupt end
#: record claiming a whole multi-GB file made zipfile read all of it, during
#: analysis, for any file with a zip head.
_ZIP_CD_LIMIT = 32 << 20

#: B20 review: how much of the file Precomp must have something to do with.
#: "Any deflated member" called the app's own `.excmp` archives expandable (a
#: stored payload beside a deflated manifest) and a zip of deflated random
#: data, piped them, and put the Precomp ceiling under the truth. Two kinds of
#: member count: deflate output that actually compressed (Precomp expands it)
#: and PNG/JPEG images, stored or not (Precomp expands a PNG's own deflate and
#: recodes a JPEG with packJPG). Counting only the first would have dropped
#: 22 of the 38 real Office files B5 measured its 50% on (images in .docx and
#: .pptx); with both, all 38 and all 22 B20 samples clear 0.10 (the lowest
#: real one was 0.63).
_ZIP_MIN_DEFLATE_SHARE = 0.10
_ZIP_MEDIA_MEMBERS = (".png", ".jpg", ".jpeg")


def _zip_cd_size(path: Path) -> int | None:
    """The central directory size the end record claims, or None if there is
    no end record (it always sits in the last 65,557 bytes)."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - 65_557))
        tail = fh.read()
    i = tail.rfind(b"PK\x05\x06")
    if i < 0 or len(tail) - i < 22:
        return None
    cd = struct.unpack("<I", tail[i + 12:i + 16])[0]
    if cd == 0xFFFFFFFF:                       # zip64: the real size is there
        j = tail.rfind(b"PK\x06\x06", 0, i)
        if j < 0 or len(tail) - j < 48:
            return None
        cd = struct.unpack("<Q", tail[j + 40:j + 48])[0]
    return cd


def _zip_is_expandable(path: Path) -> bool:
    """True when this really is a zip whose members Precomp could expand.

    Reads the central directory only - member *flags* and sizes, never member
    data - so it costs one seek and a short read regardless of how large the
    file is.

    Encryption is the case that matters. `Wondershare ... pass=123.zip` is
    263 MB and 37% of the estimator's backtest corpus, and Extreme measured
    **2.97%** on that corpus: Precomp cannot see inside an encrypted member,
    so believing the `.zip` extension would predict a large gain that never
    arrives. And since B20 (review) the deflated members have to be worth
    expanding: see `_ZIP_MIN_DEFLATE_SHARE`.
    """
    try:
        size = path.stat().st_size
        cd = _zip_cd_size(path)
        if cd is None or cd > min(_ZIP_CD_LIMIT, size):
            return False
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
    except Exception:  # noqa: BLE001
        # Not a zip after all, truncated, or one the stdlib can't read: it
        # raises NotImplementedError for a "version needed" above 6.3, which
        # 7-Zip opens fine (B20 review: 288 of 20,000 mutated zips). This
        # runs during analysis, which K3 made incapable of failing a job.
        return False
    if not members or not size:
        return False
    if any(info.flag_bits & 0x1 for info in members):
        return False
    useful = sum(info.compress_size for info in members
                 if info.filename.lower().endswith(_ZIP_MEDIA_MEMBERS)
                 or (info.compress_type == zipfile.ZIP_DEFLATED
                     and info.compress_size < 0.95 * info.file_size))
    return useful >= _ZIP_MIN_DEFLATE_SHARE * size


def _pdf_is_expandable(head: bytes) -> bool:
    """True when the PDF declares a Flate stream in its first pages.

    `/FlateDecode` is the filter Precomp reverses. An image-only PDF wrapping
    DCT data declares `/DCTDecode` instead and has nothing to expand.
    """
    return b"FlateDecode" in head


def probe_expandable(path: Path, head: bytes) -> bool:
    """Will Precomp find a deflate layer in this file? (B5.)

    ``head`` is the buffer `analyze_file` has already read, so the common case
    costs nothing extra; only a zip-family container pays for a second open.
    """
    suffix = path.suffix.lower()
    # B20: by content as well as by name. Android AAR/AAB, NuGet, APPX, VSIX
    # and wheels are all zips under other names; measured, Precomp took
    # 38-57% off them, and none was ever probed.
    if suffix in _ZIP_FAMILY or head[:4] == b"PK\x03\x04":
        return _zip_is_expandable(path)
    if suffix == ".pdf":
        return _pdf_is_expandable(head)
    return False


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


def sample_stats(path: Path, sample: int = _SAMPLE) -> SampleStats:
    """Entropy *and* measured compressibility over up to 3 samples.

    Entropy is computed over the samples concatenated (so it matches what
    ``sample_entropy`` has always returned); the ratios are per-sample, because
    disagreement between them is the whole point - see the module docstring.
    """
    size = path.stat().st_size
    if size == 0:
        return SampleStats(entropy_bps=0.0, ratio=1.0, ratio_max=1.0, sampled_bytes=0)

    counts: Counter[int] = Counter()
    total = packed_total = 0
    ratios: list[float] = []
    cctx = zstandard.ZstdCompressor(level=_PROBE_LEVEL)
    with path.open("rb") as fh:
        offsets = {0}
        if size > sample * 3:
            offsets.update({size // 2, size - sample})
        for off in sorted(offsets):
            fh.seek(off)
            chunk = fh.read(sample)
            if not chunk:
                continue
            counts.update(chunk)
            total += len(chunk)
            # zstd frames incompressible blocks raw plus a small header, so a
            # ratio can land a hair above 1.0. Clamp: we never predict inflation.
            packed = len(cctx.compress(chunk))
            packed_total += packed
            ratios.append(min(1.0, packed / len(chunk)))

    if total == 0:
        return SampleStats(entropy_bps=0.0, ratio=1.0, ratio_max=1.0, sampled_bytes=0)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return SampleStats(
        entropy_bps=entropy,
        ratio=min(1.0, packed_total / total),
        ratio_max=max(ratios) if ratios else 1.0,
        sampled_bytes=total,
    )


def sample_entropy(path: Path, sample: int = _SAMPLE) -> float:
    """Shannon entropy in bits/byte over up to 3 samples (head/middle/tail)."""
    return sample_stats(path, sample).entropy_bps


def archive_name(root: Path, file: Path) -> str:
    """The archive-relative name `engine._collect` gives ``file`` when the user
    added ``root``: the bare name for a file, ``<root>/<path inside>`` for a
    folder. Kept beside the analyzer so the estimate can price it."""
    root, file = Path(root), Path(file)
    if root.is_file():
        return file.name
    return f"{root.name}/{file.relative_to(root).as_posix()}"


def analyze_file(path: Path, root: Path | None = None) -> FileInfo:
    """``root`` is the input this file was found under, when there is one;
    with it the analysis also records the file's archive-name length."""
    path = Path(path)
    st = path.stat()
    size = st.st_size
    with path.open("rb") as fh:
        # 64 KiB rather than 4096: B5's PDF probe has to reach a `/FlateDecode`
        # declaration, and a PDF never puts one at offset 0. Category sniffing
        # and the zlib check still only look at the first few bytes.
        head = fh.read(_PDF_SCAN_BYTES)
    stats = sample_stats(path)
    return FileInfo(
        path=path,
        size=size,
        category=_detect_category(path, head),
        entropy_bps=stats.entropy_bps,
        zlib_stream=_looks_like_zlib(head),
        sample_ratio=stats.ratio,
        sample_ratio_max=stats.ratio_max,
        mtime_ns=st.st_mtime_ns,
        expandable=probe_expandable(path, head),
        # A second open, JPEGs only: the frame can sit far past `head`.
        lepton_refuses=(jpeg.looks_like_jpeg(head) and jpeg.lepton_refuses(path)),
        is_jpeg=jpeg.looks_like_jpeg(head),
        arc_name_bytes=_arc_name_bytes(root, path),
    )


def _arc_name_bytes(root: Path | None, path: Path) -> int:
    if root is None:
        return 0
    try:
        return len(archive_name(root, path).encode("utf-8"))
    except ValueError:      # not under root after all: unknown, not fatal
        return 0


def iter_files(root: Path) -> list[Path]:
    """Every regular file under ``root``, in stable order (``root`` itself if
    it is a file).

    Split out of :func:`analyze_tree` so a caller that wants to report
    progress can learn the denominator before spending minutes on the
    entropy sampling - walking the tree is one cheap pass, reading up to
    3 MiB per file is not.
    """
    root = Path(root)
    if root.is_file():
        return [root]
    return [p for p in sorted(root.rglob("*")) if p.is_file()]


def iter_empty_dirs(root: Path,
                    files: list[Path] | None = None) -> list[Path]:
    """Every directory under ``root`` that holds nothing at all (K2).

    :func:`iter_files` keeps only ``p.is_file()``, so a directory with no files
    in it never reaches the ledger and there is nothing in the manifest to
    recreate. Restoring a folder used to silently drop them.

    Only *wholly* empty directories are returned, and that is sufficient rather
    than a simplification: a directory holding files is already implied by
    those files' relative paths, and a chain like ``deep/empty/chain`` is
    rebuilt from its deepest member with ``mkdir(parents=True)``. Recording the
    shallow ones too would repeat information the paths already carry, which is
    the redundancy K1 spent a whole phase removing.

    ``root`` itself is never returned - the restore recreates the top-level
    directory regardless, and an archive of one empty folder has no ledger and
    no reason to exist.
    """
    root = Path(root)
    if root.is_file():
        return []
    if files is not None:
        # Reuse the walk the caller already paid for. `iter_files` exists
        # precisely because walking is the one cheap pass worth doing once,
        # and on the 57,020-file corpus it costs ~20 s of drive metadata
        # latency - so doing it a second time for a list that is usually
        # empty was the wrong trade.
        #
        # A directory is empty iff no walked file lies inside it. Derived from
        # the file list rather than re-statted, which also makes the two
        # answers incapable of disagreeing.
        occupied: set[Path] = set()
        for f in files:
            for parent in f.parents:
                if parent in occupied:
                    break
                occupied.add(parent)
        dirs = [p for p in sorted(root.rglob("*")) if p.is_dir()]
        # A directory that merely holds *other directories* is not wholly
        # empty, and returning it would repeat what the deeper entry's own
        # `mkdir(parents=True)` already rebuilds - the redundancy K1 spent a
        # phase removing. So `deep/empty/chain` is recorded and `deep` is not.
        has_subdir = {d.parent for d in dirs}
        return [p for p in dirs
                if p not in occupied and p not in has_subdir]
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_dir():
            continue
        try:
            next(p.iterdir())
        except StopIteration:
            out.append(p)
        except OSError:
            # Unreadable directory: K3's problem, not this function's. Saying
            # nothing is right here - a directory we cannot list is not a
            # directory we can call empty.
            continue
    return out


def analyze_tree(root: Path) -> list[FileInfo]:
    return [analyze_file(p, root) for p in iter_files(root)]


def describe_unreadable(path: Path, exc: OSError,
                        label: str | None = None) -> str:
    """One human-readable line for a file we could not read (K3).

    ``label`` is the archive-relative path when the caller has one, and it
    matters more than it looks: a `node_modules` tree holds hundreds of
    ``index.js``, so a message built from ``path.name`` alone identified
    nothing and two different skipped files produced byte-identical sentences.
    A name the user cannot resolve to a file is most of the way back to the
    silence this report exists to prevent - they cannot go and re-archive what
    they cannot find.

    The stdlib text for a share-mode denial is "Permission denied", which on
    Windows is actively misleading: the user's permissions are usually fine
    and the real cause is that another program is holding the file open. Say
    that instead, because the user's next action depends on knowing it -
    closing Excel fixes it, changing an ACL does not.
    """
    who = label or path.name
    if isinstance(exc, PermissionError):
        return (f"{who}: in use by another program (or not readable), "
                f"so it was skipped")
    if isinstance(exc, FileNotFoundError):
        return f"{who}: disappeared while the job was running, so it was skipped"
    return f"{who}: could not be read ({exc.strerror or exc}), so it was skipped"


def analyze_tree_safe(root: Path) -> tuple[list[FileInfo], list[tuple[Path, str]]]:
    """:func:`analyze_tree`, but a file it cannot read is skipped, not fatal.

    K3: `analyze_file` opens the file to sniff its category and sample its
    entropy, so a file held with ``dwShareMode=0`` - what Outlook and Excel do
    - raised `PermissionError` here and took the whole job down with it,
    including the files that *were* readable. Every other archiver skips,
    continues, and reports at the end.

    Returns the analyses that succeeded and ``(path, reason)`` for each that
    did not. Both halves are needed by the caller: the second is not an error
    log, it is part of the job's result, because a skip nobody is told about is
    worse than a failure.
    """
    infos: list[FileInfo] = []
    skipped: list[tuple[Path, str]] = []
    for p in iter_files(root):
        try:
            infos.append(analyze_file(p, root))
        except OSError as exc:
            skipped.append((p, describe_unreadable(p, exc)))
    return infos, skipped
