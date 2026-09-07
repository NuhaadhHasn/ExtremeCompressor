"""The .excmp container: a zip holding manifest.json + one payload blob.

The manifest records the exact stage chain (in the order it ran), tool
versions, and a SHA-256 ledger of every original input file, so extraction
can replay the chain in reverse and prove the restore is byte-identical.

The payload and the ``stored/`` tree are STORED (no compression) because a
real codec has already had its turn at them. ``manifest.json`` is the one
DEFLATED member: it is JSON, and on the real 55,477-file archive K1 was
measured against that is the difference between 12.19 MiB and 2.59 MiB.
"""

from __future__ import annotations

import json
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import jpeg
from .safepath import UnsafePathError, resolve_within, safe_relpath

SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.json"

# manifest.json is parsed before anything in it can be validated, so an
# unbounded json.loads on attacker-supplied bytes is a free memory bomb.
#
# K1: this was `8 << 20`, and it was a guess that refused real data. Archiving
# a live 55,477-file `node_modules` tree produces 12.19 MiB of manifest **after**
# every redundancy has been squeezed out of the schema - the same job needed
# 21.56 MiB under v1 - because those relative paths average 152 bytes each and
# millions of bytes of the document are therefore pure path text. No amount of
# field-trimming reaches 8 MiB; the cap was simply too low.
#
# This number is now measured rather than guessed. Parsing 14.8 MiB of manifest
# (57,020 entries) costs **1.2-1.7 s and 32.1 MiB resident** - 2.2x the JSON
# size, 590 B per file. So 64 MiB is ~139 MiB and ~5 s in the worst case, on a
# target machine that already budgets ~2 GB for a single LZMA2 dictionary, and
# it covers roughly a quarter of a million files at this corpus's path lengths.
# Still a hard bound, and now one with a reason.
MAX_MANIFEST_BYTES = 64 << 20

# Per-ledger-entry cost of the v2 document, excluding the relative path itself:
# the two quotes and the colon around the key, the braces, `"size":<up to 11
# digits>`, `"sha256":"<64 hex>"`, `"route":"pipeline"` and the separating
# comma. Counted from the format rather than fitted to a corpus, and rounded up
# - `manifest_size_estimate` decides whether a job is refused, so it must err
# high. A stored entry additionally carries `,"reason":<index>`.
#
# K2 added `,"mtime_ns":<19 digits>` to every entry, which is 32 bytes: the key
# and its quotes and colon (12) plus a nanosecond epoch (19) plus the comma.
# **Any new ledger key has to be added here.** Leave it out and
# `manifest_size_estimate` under-reads, the preflight waves a job through, and
# the refusal lands back at `write_container` after every byte is written -
# which is K1's original defect, and it was re-introduced twice during K1
# itself before being caught.
_MANIFEST_ENTRY_BYTES = 152
_MANIFEST_REASON_BYTES = 16
# `write_container` mutates the same ledger again *after* the estimate has been
# taken and the job has been allowed to start, so these have to be budgeted for
# here or the preflight waves through a job that dies at the very end - which is
# the K1 defect itself, reached by a different route. Measured at 0.758x the
# estimate before this term existed.
#
#   `,"same_as":"<relpath>"`   G9, on every duplicate stored entry: 13 + the
#                              whole relative path of the entry holding the bytes
#   `,"codec":"lepton"`        B2, on every packed JPEG
#
# Never both on one entry - the packing loop skips anything already carrying a
# `same_as` - so the allowance is the larger of the two, and the path it points
# at is bounded only by the longest name in the selection.
_MANIFEST_SAME_AS_BYTES = 13
_MANIFEST_CODEC_BYTES = 17
# K2's `dirs` entry: the two quotes around the path and the separating comma.
_MANIFEST_DIR_BYTES = 3
# The fixed head: schema/created/profile/payload_name, the stage records, the
# routes, the warnings, and the interned reason table. The table is the only
# part that grows, and it cannot pass **12** entries: `planner.store_reason`
# emits one fixed media sentence plus one per two-decimal entropy value from
# `ENTROPY_STORE_THRESHOLD` (7.9) to 8.00 inclusive, which is 11. Enumerated,
# the whole table is **1,232 bytes** however many files there are - so 12 KiB
# of head covers it eight times over.
#
# An earlier revision of this comment said "~52 entries, ~5.3 KB". That is the
# figure for a 7.5 threshold, which is not the one the planner uses; it was
# never measured. `test_the_reason_table_cannot_grow_past_twelve_sentences`
# now pins the real bound, so moving ENTROPY_STORE_THRESHOLD fails loudly here
# instead of silently invalidating the budget.
_MANIFEST_BASE_BYTES = 12 << 10

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
    #: Bytes this stage **consumed** at compress time.
    #:
    #: On extraction the chain runs backwards, so this is exactly what the
    #: stage should produce - which turns the decompression-bomb guard from a
    #: blanket multiplier into a number we actually measured. That matters
    #: because Precomp's legitimate inflation is wildly data-dependent: 2-5x
    #: on installers, but ~50x on PNG, where expanding deflate yields raw
    #: pixels. A multiplier loose enough for PNG would be no defence at all.
    #:
    #: ``0`` means "not recorded" - every archive written before this field
    #: existed - and the reader falls back to the old multiplier for those.
    input_bytes: int = 0


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
    #: **v1 only.** relpath -> why THIS file was stored, as a whole English
    #: sentence per file. The route-level reason is a joined summary of every
    #: distinct reason in the group, so attributing it to an individual file
    #: says "7.99 bits/byte; 7.98 bits/byte" about a file that measured one of
    #: them - hence the per-file record.
    #:
    #: v2 interns the same information into :attr:`reasons` and an index on the
    #: ledger entry, which is 13 MiB smaller on a 57,020-file tree because it
    #: does not repeat every relative path a second time. The field stays here,
    #: and stays empty in what we write, because `from_json` splats the raw
    #: document into `cls(**data)`: deleting it would turn every v1 archive
    #: into a `TypeError` and an unreadable file. Read it through
    #: :meth:`reason_for`, never directly.
    store_reasons: dict[str, str] = field(default_factory=dict)
    #: v2: the distinct store reasons, referenced by index from
    #: ``inputs[rel]["reason"]``. Bounded at 12 strings by construction.
    reasons: list[str] = field(default_factory=list)
    #: K2: directories that hold nothing at all, which no ledger entry implies.
    #: Only the deepest of a chain is recorded; the restore uses
    #: ``mkdir(parents=True)``. Archive-supplied, so every entry is validated
    #: through `safepath` before it is created, exactly like a ledger key.
    dirs: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, profile: str, stages: list[StageRecord], inputs: dict[str, dict],
            payload_name: str, warnings: list[str] | None = None,
            routes: list[dict] | None = None,
            store_reasons: dict[str, str] | None = None,
            dirs: list[str] | None = None) -> "Manifest":
        """Build a v2 manifest. ``store_reasons`` is still taken as
        ``{relpath: sentence}`` - that is the shape the planner produces - and
        interned here, so exactly one place knows the storage format.

        ``inputs`` is **mutated**: each stored entry gains a ``reason`` index.
        `write_container` mutates the same dict again (``same_as``, ``codec``)
        before serialising, so this is the established contract rather than a
        new one.
        """
        table: list[str] = []
        seen: dict[str, int] = {}
        for rel, sentence in (store_reasons or {}).items():
            meta = inputs.get(rel)
            # Only a *stored* file needs explaining; a pipelined one shrank.
            # v1 recorded a sentence for every high-entropy file whether or not
            # it ended up stored - Precomp can claim a file the entropy check
            # would have stored - and `list_archive` then suppressed it on the
            # way out. Those entries were pure weight.
            if meta is None or meta.get("route") != "store":
                continue
            idx = seen.get(sentence)
            if idx is None:
                idx = seen[sentence] = len(table)
                table.append(sentence)
            meta["reason"] = idx

        # `routes[].files` named every file a second time; the ledger above
        # already carries a route per file, and a count is all any reader
        # wanted from the list. Derived here so the two can never disagree.
        lean_routes = []
        for route in (routes or []):
            route = {k: v for k, v in route.items() if k != "files"}
            route["count"] = sum(1 for meta in inputs.values()
                                 if meta.get("route") == route.get("action"))
            lean_routes.append(route)

        return cls(
            schema=SCHEMA_VERSION,
            created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            profile=profile,
            stages=stages,
            inputs=inputs,
            payload_name=payload_name,
            warnings=warnings or [],
            routes=lean_routes,
            store_reasons={},
            reasons=table,
            dirs=sorted(dirs or []),
        )

    def to_json(self) -> str:
        # Compact: the cap is measured in uncompressed bytes and `indent=2` was
        # 12% of the budget - 2.2 MiB on the tree that could not be archived.
        #
        # `ensure_ascii=False` is load-bearing, not cosmetic. The default emits
        # every non-ASCII character as a 6-byte `\uXXXX` escape - 12 for an
        # astral pair - which is 3x what a 2-byte Cyrillic character costs in
        # UTF-8 and 3x for an emoji. `manifest_size_estimate` costs a path at
        # its UTF-8 length, so with escaping on it under-read a pipelined tree
        # of Dhivehi names by 45% (0.55x) and would have let the job start and
        # then die at `write_container` - K1's own failure, in a language this
        # product has an explicit edge-case test for. Writing real UTF-8 makes
        # the estimate's model true *and* makes those manifests smaller.
        #
        # Safe on both sides: `zipfile.writestr` encodes a str member as UTF-8,
        # and `_read_manifest` decodes UTF-8. Pinned by
        # `test_non_ascii_names_survive_the_container`.
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        data = json.loads(text)
        schema = data.get("schema", 0)
        # There was no check here at all, so an archive from a future build
        # loaded and was quietly misread. Saying so is the honest failure.
        if isinstance(schema, int) and schema > SCHEMA_VERSION:
            raise ContainerError(
                f"this archive declares manifest schema {schema}, and this "
                f"build understands up to {SCHEMA_VERSION} - it was written by "
                f"a newer version of ExtremeCompressor")
        data["stages"] = [StageRecord(**s) for s in data.get("stages", [])]
        return cls(**data)

    def reason_for(self, relpath: str, fallback: str = "") -> str:
        """Why this file was stored, whichever schema wrote the archive.

        v2's interned index first, then v1's per-file sentence, then whatever
        the caller offers - in practice the route's joined summary, which is
        all the oldest archives ever had.
        """
        idx = self.inputs.get(relpath, {}).get("reason")
        if isinstance(idx, int) and 0 <= idx < len(self.reasons):
            return self.reasons[idx]
        return self.store_reasons.get(relpath) or fallback


#: A lepton member is always smaller than the JPEG it restores to, but a
#: very small file can still carry framing overhead, so the bound is the
#: larger of the declared size and this floor.
_LEPTON_MEMBER_FLOOR = 64 * 1024

STORED_PREFIX = "stored/"


def declared_total(ledger: dict[str, dict]) -> int:
    """Total restored size the manifest's own ledger promises."""
    return sum(int(meta.get("size", 0)) for meta in ledger.values())


def manifest_size_estimate(relpaths: Iterable[str], stored_count: int = 0,
                           dirs: Iterable[str] = ()) -> int:
    """How large the manifest for this selection will be, in bytes.

    Public and pure so the answer is available *before* any work starts, and
    testable without building a 57,000-file archive - the same split as
    ``engine.compress_space_needs`` against ``_check_compress_space``.

    K1 exists because the cap was only ever checked on the way back **in**:
    `compress` wrote the manifest unchecked, and the refusal arrived from
    `_read_manifest` at the bottom of the D9 publish gate, after the entire
    archive had been built. This is the number that lets the refusal happen at
    the front instead.

    Biased high on purpose. Refusing a job that would have worked is bad;
    accepting one that cannot finish is the defect being fixed. The same logic
    forces the worst case on the `same_as` term below: which stored files turn
    out to be duplicates of each other is not knowable until every one of them
    has been hashed, which is most of the job.
    """
    total = _MANIFEST_BASE_BYTES + stored_count * _MANIFEST_REASON_BYTES
    longest = 0
    for rel in relpaths:
        encoded = len(rel.encode("utf-8"))
        longest = max(longest, encoded)
        total += encoded + _MANIFEST_ENTRY_BYTES
    # K2's `dirs`: one full relative path each, and unbounded. Measured before
    # this term existed, 20,000 empty directories beside 10 files predicted
    # 14,498 B against 1,550,859 B written - a 100x under-read, and K1's defect
    # for the third time.
    for d in dirs:
        total += len(d.encode("utf-8")) + _MANIFEST_DIR_BYTES
    # The keys write_container stamps on after this number has been taken.
    return total + stored_count * max(_MANIFEST_SAME_AS_BYTES + longest,
                                      _MANIFEST_CODEC_BYTES)


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

    # B2: settle the JPEG packing BEFORE the manifest is serialised.
    #
    # This used to happen inside the write loop, i.e. after the manifest JSON
    # was already in the zip, which made the fallback `meta.pop("codec")` dead
    # code: an entry that failed to pack the second time shipped carrying a
    # `codec: lepton` its bytes did not honour. Doing it here also means each
    # JPEG is compressed **once** - the engine used to pack every one merely to
    # decide, throw the bytes away, and pack it again down here.
    packed_bytes: dict[str, bytes] = {}
    if jpeg.available():
        for rel, src in stored_norm.items():
            meta = manifest.inputs.get(rel, {})
            if "same_as" in meta:
                continue
            try:
                packed = jpeg.pack(Path(src).read_bytes())
            except OSError:
                packed = None
            if packed is not None:
                packed_bytes[rel] = packed
                meta["codec"] = "lepton"
            else:
                meta.pop("codec", None)
    else:
        for rel in stored_norm:
            manifest.inputs.get(rel, {}).pop("codec", None)

    # K1: the cap used to be enforced only on the way back in, so `compress`
    # would build an archive its own reader refused and find out at the bottom
    # of the publish gate - after every byte had been written. Checked here the
    # asymmetry is gone, and the docstring's promise above ("we can never
    # produce an archive our own reader would refuse") covers size as well as
    # names. `engine.compress` has a preflight that catches this before any
    # work starts; this is the backstop that makes it impossible.
    document = manifest.to_json()
    encoded = document.encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ContainerError(
            f"this archive's manifest would be {len(encoded)} bytes, over the "
            f"{MAX_MANIFEST_BYTES} byte limit its reader enforces - refusing to "
            f"write a container we could not open ({len(manifest.inputs)} files)")

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=True) as zf:
        # The manifest goes in first and now carries both the `same_as`
        # pointers and the settled `codec` keys, so both passes above have to
        # run before this line.
        #
        # DEFLATED, unlike everything else in the container: the payload and
        # the stored tree are already packed by a real codec, but this is JSON.
        # Measured 12.19 MiB -> 2.59 MiB on the real 55,477-file archive (a
        # synthetic ledger deflates far better; real sha256s barely do). It does not
        # widen the bomb surface - `_read_manifest` bounds the *decompressed*
        # stream at MAX + 1 bytes, and `info.file_size` is the uncompressed
        # size either way.
        zf.writestr(MANIFEST_NAME, document,
                    compress_type=zipfile.ZIP_DEFLATED)
        if payload_path is not None:
            zf.write(payload_path, arcname=manifest.payload_name)
        for rel, src in stored_norm.items():
            meta = manifest.inputs.get(rel, {})
            if "same_as" in meta:
                continue
            if rel in packed_bytes:
                zf.writestr(STORED_PREFIX + rel, packed_bytes[rel])
            else:
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
            # A lepton entry is *smaller* on disk than the file it restores to,
            # so the raw-size comparison below would be meaningless for it.
            # The ledger's size still bounds the restored bytes, which is what
            # the bomb defence actually cares about.
            if meta.get("codec") != "lepton" and info.file_size > declared:
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
                if meta.get("codec") == "lepton":
                    target.write_bytes(
                        _read_lepton_member(zf, info, declared, key))
                else:
                    with zf.open(info) as src, target.open("wb") as dst:
                        got = _copy_bounded(src, dst, declared,
                                            f"stored entry {key!r}")
                    if got != declared:
                        raise ContainerError(
                            f"stored entry {key!r} holds {got} bytes, the "
                            f"ledger declares {declared}")
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
                if source_meta.get("codec") == "lepton":
                    # The member holds the SOURCE entry's lepton bytes, which
                    # are smaller than the JPEG they restore to. Copying them
                    # across verbatim produced "holds 20162 bytes, the ledger
                    # declares 23906" and failed the entire compress - two
                    # identical photos in one folder was all it took.
                    target.write_bytes(
                        _read_lepton_member(zf, info, declared, key))
                else:
                    with zf.open(info) as src, target.open("wb") as dst:
                        got = _copy_bounded(src, dst, declared,
                                            f"stored entry {key!r}")
                    if got != declared:
                        raise ContainerError(
                            f"stored entry {key!r} holds {got} bytes, the "
                            f"ledger declares {declared}")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            written.append(target)
    return written


def _read_lepton_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo,
                        declared: int, key: str) -> bytes:
    """Unpack one lepton member, bounded at both ends.

    Two amplification steps live here and both used to be unbounded: a plain
    ``zf.read()`` of an archive-supplied member, and then ``jpeg.unpack()`` of
    whatever that produced. The ledger already declares what the file restores
    to, so both are checked against that number - the lepton branch previously
    skipped the member-size check every other stored entry gets.
    """
    if info.file_size > max(declared, _LEPTON_MEMBER_FLOOR):
        raise ContainerError(
            f"stored entry {key!r} holds {info.file_size} packed bytes for a "
            f"file the ledger says is {declared} - refusing to expand it")
    with zf.open(info) as fh:
        packed = fh.read(info.file_size + 1)
    if len(packed) > info.file_size:
        raise ContainerError(f"stored entry {key!r} is larger than it declares")
    if not jpeg.available():
        raise ContainerError(
            f"stored entry {key!r} needs the 'lepton-jpeg-python' package to "
            f"restore, and it is not installed")
    try:
        restored = jpeg.unpack(packed)
    except RuntimeError as exc:
        # lepton's own error text carries the Rust build machine's paths, which
        # is not something to show somebody about their own photo.
        raise ContainerError(
            f"stored entry {key!r} is not valid lepton data") from exc
    if len(restored) != declared:
        raise ContainerError(
            f"stored entry {key!r} restored to {len(restored)} bytes, the "
            f"ledger declares {declared}")
    return restored
