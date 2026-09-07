"""Manifest schema v2 (K1): a real folder has to be archivable at all.

`MAX_MANIFEST_BYTES = 8 << 20` refused a live 57,020-file tree outright, and it
refused it *after* the whole job had run, because the cap was only ever checked
on the read side - inside the D9 publish gate, at the end.

Measured end to end on 2026-09-06 by actually archiving the `node_modules`
subtree that broke - 55,477 files, 338.5 MiB - and reconstructing the v1
document for that same job from the v2 manifest it produced:

| the same real job          | bytes      |          |          |
|----------------------------|-----------:|----------|----------|
| **v1 manifest**            | 22,611,183 | 21.56 MiB| REFUSED  |
| **v2 manifest**            | 12,782,745 | 12.19 MiB| ok       |
| **v2, deflated in the zip**|  2,720,064 |  2.59 MiB|          |

22,611,183 is byte-for-byte the figure in the pre-K1 build's own error
message, which is how we know the reconstruction is faithful and that this is
the folder that failed.

The load-bearing finding: **trimming fields is not enough.** The relative paths
average 152 bytes each in a `node_modules` tree, so millions of bytes of that
manifest are pure path text and clear an 8 MiB cap before any other field is
written. So v2 does two things - it removes the genuine redundancy *and* the
cap rises to a figure justified by the measured parse cost (1.2-1.7 s and
32.1 MiB resident for 14.8 MiB of JSON: 2.2x the bytes, 590 B per file).

Everything here is about not breaking the archives that already exist. v1
containers must keep loading and restoring: `Manifest.from_json` splats the raw
dict into `cls(**data)`, so a field that v1 wrote and v2 deleted is not a
migration - it is a `TypeError` and an unreadable archive.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.manifest import (
    MAX_MANIFEST_BYTES,
    MANIFEST_NAME,
    SCHEMA_VERSION,
    ContainerError,
    Manifest,
    StageRecord,
    manifest_size_estimate,
    read_container,
    write_container,
)
from excmp.planner import Profile
from excmp.stages.base import StageContext

_MEDIA_REASON = (
    "media file: already compressed by its codec; stored losslessly so "
    "quality is untouched (enable Shrink mode to re-encode smaller)"
)


# --------------------------------------------------------------------------
# v1 archives must keep working
# --------------------------------------------------------------------------

def _as_v1(manifest_json: str) -> str:
    """Turn a v2 manifest back into the exact shape a pre-K1 build wrote.

    Not an approximation: the transformation v2 applies is invertible, so this
    reconstructs the real v1 document - `schema: 1`, a sentence per file in
    `store_reasons`, every relative path listed a second time under
    `routes[].files`, and no `reasons` table.
    """
    data = json.loads(manifest_json)
    table = data.pop("reasons", [])
    store_reasons = {}
    for rel, meta in data["inputs"].items():
        idx = meta.pop("reason", None)
        if idx is not None:
            store_reasons[rel] = table[idx]
    data["store_reasons"] = store_reasons
    for route in data["routes"]:
        route.pop("count", None)
        route["files"] = [rel for rel, meta in data["inputs"].items()
                          if meta.get("route") == route["action"]]
    data["schema"] = 1
    return json.dumps(data, indent=2)


def _rewrite_manifest(archive: Path, text: str) -> Path:
    """Copy an archive, replacing only its manifest. Every other member is
    carried across byte-for-byte, with its compression method intact."""
    out = archive.with_name(archive.stem + "-v1" + archive.suffix)
    with zipfile.ZipFile(archive) as src, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as dst:
        dst.writestr(MANIFEST_NAME, text)
        for info in src.infolist():
            if info.filename == MANIFEST_NAME:
                continue
            dst.writestr(info, src.read(info.filename),
                         compress_type=info.compress_type)
    return out


def _tree(root: Path) -> Path:
    """A tree with both routes in it: text that pipelines, high-entropy bytes
    that get stored and therefore need a reason."""
    root.mkdir(parents=True)
    (root / "notes.txt").write_text("the quick brown fox\n" * 2000, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "more.txt").write_text("lorem ipsum dolor\n" * 2000, encoding="utf-8")
    (root / "one.bin").write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))
    (root / "two.bin").write_bytes(bytes((i * 31 + 200) % 251 for i in range(70_000)))
    return root


def test_a_v1_manifest_still_loads_and_keeps_its_per_file_reasons():
    """The `cls(**data)` hinge. `store_reasons` stays on the dataclass so a v1
    document is accepted, and `reason_for` reads it - a v1 archive must not
    quietly lose the one thing no other archiver records."""
    v1 = json.dumps({
        "schema": 1,
        "created_utc": "2026-08-01T00:00:00+00:00",
        "profile": "fast",
        "stages": [],
        "inputs": {"a.bin": {"size": 1, "sha256": "x" * 64, "route": "store"}},
        "payload_name": "",
        "warnings": [],
        "routes": [{"action": "store", "stages": [], "reason": "group summary",
                    "files": ["a.bin"]}],
        "store_reasons": {"a.bin": "because it was already compressed"},
    })
    m = Manifest.from_json(v1)
    assert m.schema == 1
    assert m.reasons == [], "a v1 document carries no interned table"
    assert m.reason_for("a.bin") == "because it was already compressed"


def test_a_v1_manifest_from_before_store_reasons_falls_back():
    """Older still: no `store_reasons` key at all. The route summary is all
    there is, and showing it beats showing nothing."""
    v1 = json.dumps({
        "schema": 1, "created_utc": "", "profile": "fast", "stages": [],
        "inputs": {"a.bin": {"size": 1, "sha256": "x" * 64, "route": "store"}},
        "payload_name": "", "warnings": [],
        "routes": [{"action": "store", "stages": [], "reason": "group summary",
                    "files": ["a.bin"]}],
    })
    m = Manifest.from_json(v1)
    assert m.reason_for("a.bin", "group summary") == "group summary"


def test_a_genuine_v1_archive_still_restores_and_lists(tmp_path):
    """The B11 precedent (tests/test_extreme_chain.py:64): remove a shape from
    what we *write*, never from what we can *read*. These are the real bytes a
    pre-K1 build produced, not a hand-rolled stand-in."""
    src = _tree(tmp_path / "src")
    v2 = tmp_path / "v2.excmp"
    engine.compress([src], v2, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))

    with zipfile.ZipFile(v2) as zf:
        v1_text = _as_v1(zf.read(MANIFEST_NAME).decode("utf-8"))
    assert '"schema": 1' in v1_text
    assert '"store_reasons"' in v1_text and '"files"' in v1_text
    v1 = _rewrite_manifest(v2, v1_text)

    result = engine.extract(v1, tmp_path / "out", StageContext(temp_dir=tmp_path / "t2"))
    assert result.verified == result.files_restored > 0

    listing = engine.list_archive(v1)
    stored = [e for e in listing.entries if e.route == "store"]
    assert stored, "the .bin files are high-entropy and should be stored"
    for entry in stored:
        assert entry.reason.count("bits/byte") == 1, entry.reason


# --------------------------------------------------------------------------
# what v2 writes
# --------------------------------------------------------------------------

def test_the_reason_table_cannot_grow_past_twelve_sentences():
    """The interning is only worth anything if the table has a hard ceiling,
    and `_MANIFEST_BASE_BYTES` budgets 12 KiB on the strength of it.

    Enumerated rather than reasoned about, because the reasoning was wrong: the
    comment beside that constant claimed "~52 entries, ~5.3 KB", which is the
    figure for a 7.5 threshold. `ENTROPY_STORE_THRESHOLD` is **7.9**, so the
    entropy sentences run 7.90 to 8.00 at two decimals - eleven of them - plus
    the one fixed media sentence. Twelve, and 1,232 bytes.

    Pinned here so that moving the threshold fails loudly instead of quietly
    invalidating the head budget.
    """
    from excmp.analyzer import Category, FileInfo
    from excmp.planner import ENTROPY_STORE_THRESHOLD, store_reason

    seen = set()
    step = 0.0005
    v = ENTROPY_STORE_THRESHOLD - 0.1
    while v <= 8.0 + step / 2:
        reason = store_reason(FileInfo(path=Path("x.bin"), size=1,
                                       category=Category.BINARY, entropy_bps=v))
        if reason:
            seen.add(reason)
        v += step
    seen.add(store_reason(FileInfo(path=Path("x.mp4"), size=1,
                                   category=Category.VIDEO, entropy_bps=0.0)))

    assert len(seen) == 12, sorted(seen)
    table = len(json.dumps(sorted(seen), separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8"))
    assert table == 1232, table
    from excmp.manifest import _MANIFEST_BASE_BYTES
    assert table < _MANIFEST_BASE_BYTES, \
        "the head budget has to cover the largest table that can exist"


def test_v2_interns_the_reasons_instead_of_repeating_the_sentence():
    """`store_reason()` can only ever produce 12 distinct sentences - one for
    media, plus one per two-decimal entropy value from the 7.9 threshold to
    8.00. So the table is a fixed 1,232 bytes however many files there are, and
    the per-file cost becomes an integer instead of a paragraph."""
    inputs = {f"f{i}.bin": {"size": 1, "sha256": "x" * 64, "route": "store"}
              for i in range(50)}
    m = Manifest.new(profile="fast", stages=[], inputs=inputs, payload_name="",
                     store_reasons={rel: _MEDIA_REASON for rel in inputs})

    assert m.reasons == [_MEDIA_REASON], "one distinct sentence, stored once"
    assert m.inputs["f7.bin"]["reason"] == 0
    assert m.reason_for("f7.bin") == _MEDIA_REASON
    assert m.to_json().count(_MEDIA_REASON) == 1


def test_v2_does_not_list_every_file_a_second_time():
    """`routes[].files` duplicated every relative path, and the ledger already
    carries the route per file. A count is all the CLI ever wanted from it."""
    inputs = {"a.txt": {"size": 1, "sha256": "a" * 64, "route": "pipeline"},
              "b.bin": {"size": 2, "sha256": "b" * 64, "route": "store"},
              "c.bin": {"size": 3, "sha256": "c" * 64, "route": "store"}}
    m = Manifest.new(profile="fast", stages=[], inputs=inputs, payload_name="p.7z",
                     routes=[{"action": "pipeline", "stages": ["tar"], "reason": "r"},
                             {"action": "store", "stages": [], "reason": "s"}])
    assert all("files" not in r for r in m.routes)
    counts = {r["action"]: r["count"] for r in m.routes}
    assert counts == {"pipeline": 1, "store": 2}


def test_v2_json_is_compact():
    """The cap is measured in uncompressed bytes, and `indent=2` was 12% of the
    budget - 2.2 MiB on the tree that could not be archived."""
    m = Manifest.new(profile="fast", stages=[], inputs={}, payload_name="")
    assert "\n" not in m.to_json()


def test_the_manifest_is_deflated_in_the_container(tmp_path):
    """The payload stays STORED because the last stage already compressed it.
    manifest.json is JSON - measured 12.19 MiB -> 2.59 MiB on the real
    55,477-file archive - and paying its full size on disk was never anything
    but waste."""
    payload = tmp_path / "p.bin"
    payload.write_bytes(b"DATA" * 1000)
    inputs = {f"f{i}.txt": {"size": 4, "sha256": f"{i:064d}", "route": "pipeline"}
              for i in range(400)}
    arc = tmp_path / "out.excmp"
    write_container(arc, Manifest.new(profile="normal", stages=[], inputs=inputs,
                                      payload_name="p.bin"), payload)

    with zipfile.ZipFile(arc) as zf:
        man = zf.getinfo(MANIFEST_NAME)
        pay = zf.getinfo("p.bin")
    assert man.compress_type == zipfile.ZIP_DEFLATED
    assert man.compress_size < man.file_size / 2
    assert pay.compress_type == zipfile.ZIP_STORED, "the payload is already packed"


def test_a_deflated_manifest_still_round_trips(tmp_path):
    payload = tmp_path / "p.bin"
    payload.write_bytes(b"DATA" * 1000)
    m = Manifest.new(profile="normal",
                     stages=[StageRecord("sevenzip", "7z", "26.02", {"mx": 9})],
                     inputs={"a.txt": {"size": 4, "sha256": "aa", "route": "pipeline"}},
                     payload_name="p.bin")
    arc = tmp_path / "out.excmp"
    write_container(arc, m, payload)
    m2, payload2 = read_container(arc, extract_dir=tmp_path / "x")
    assert m2.schema == SCHEMA_VERSION == 2
    assert m2.stages[0].params == {"mx": 9}
    assert payload2.read_bytes() == payload.read_bytes()


# --------------------------------------------------------------------------
# the cap, on both sides
# --------------------------------------------------------------------------

def test_the_cap_is_high_enough_for_a_real_tree():
    """57,020 files at this corpus's 152-byte average path need ~14.8 MiB with
    every file stored, and the real archive of its largest subtree needed
    12.19 MiB. A cap that refuses that is not protecting anybody from
    anything."""
    assert MAX_MANIFEST_BYTES >= 15 << 20


def test_write_container_refuses_a_manifest_it_could_not_read_back(tmp_path, monkeypatch):
    """The asymmetry that caused K1: the cap was enforced on read and not on
    write, so `compress` cheerfully built an archive its own reader refused -
    and only found out at the very end, from inside the publish gate."""
    monkeypatch.setattr("excmp.manifest.MAX_MANIFEST_BYTES", 4096)
    inputs = {f"{'d/' * 20}file{i}.bin": {"size": 1, "sha256": "x" * 64,
                                          "route": "store"}
              for i in range(200)}
    with pytest.raises(ContainerError, match="manifest"):
        write_container(tmp_path / "too-big.excmp",
                        Manifest.new(profile="fast", stages=[], inputs=inputs,
                                     payload_name=""))
    assert not (tmp_path / "too-big.excmp").exists(), \
        "refusing must not leave a container behind"


def test_a_newer_schema_is_refused_rather_than_misread(tmp_path):
    """There was no schema check at all: an archive from a future build loaded
    and was quietly misinterpreted. Saying so is the honest failure."""
    future = json.dumps({
        "schema": SCHEMA_VERSION + 1, "created_utc": "", "profile": "fast",
        "stages": [], "inputs": {}, "payload_name": "", "warnings": [],
        "routes": [], "reasons": [],
    })
    arc = tmp_path / "future.excmp"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr(MANIFEST_NAME, future)
    with pytest.raises(ContainerError, match="newer"):
        read_container(arc, extract_dir=tmp_path / "x")


# --------------------------------------------------------------------------
# the estimate that has to hold up before any work starts
# --------------------------------------------------------------------------

def test_the_size_estimate_matches_a_real_serialised_manifest():
    """This is the number the pre-flight refuses on, so it has to be right and
    it has to err high - under-reading it would put the refusal back at the end
    of the job, which is the whole defect."""
    inputs = {}
    reasons = {}
    for i in range(3000):
        rel = f"project/node_modules/@scope/pkg-{i % 90}/dist/esm/chunk-{i}.js"
        inputs[rel] = {"size": 4096 + i, "sha256": f"{i:064x}", "route":
                       "store" if i % 3 else "pipeline"}
        if i % 3:
            reasons[rel] = _MEDIA_REASON
    m = Manifest.new(profile="extreme", stages=[], inputs=inputs,
                     payload_name="payload.7z", store_reasons=reasons)
    actual = len(m.to_json().encode("utf-8"))
    predicted = manifest_size_estimate(inputs.keys(), stored_count=len(reasons))

    assert predicted >= actual, "the estimate must never under-read the cap"
    assert predicted <= actual * 2.0, \
        f"estimate {predicted} is more than 2x the real {actual}"


def test_the_size_estimate_survives_what_write_container_adds_afterwards():
    """The preflight measures the manifest `Manifest.new` produces. It is not
    the manifest that gets written.

    `write_container` mutates the same ledger twice more, *after* the estimate
    has already decided the job may proceed: G9 stamps a duplicate stored entry
    with ``"same_as": "<the other file's whole relative path>"``, and B2 stamps
    a packed JPEG with ``"codec": "lepton"``. Neither existed when the number
    was taken.

    Measured before this was budgeted for: 5,000 stored files whose relative
    paths are all duplicates came out at **0.758x** the estimate - a 24%
    under-read. That is K1 all over again with a different trigger, because an
    under-read preflight waves the job through and the refusal lands back where
    it always did, at `write_container`, after every byte has been written.
    """
    n = 5000
    stem = "project/node_modules/@scope/package-name-here/dist/esm/internal"
    inputs = {f"{stem}/chunk-{i}.js": {"size": 4096, "sha256": "a" * 64,
                                       "route": "store"}
              for i in range(n)}

    # Taken exactly where the engine takes it: before anything has run.
    predicted = manifest_size_estimate(inputs.keys(), stored_count=n)

    m = Manifest.new(profile="extreme", stages=[], inputs=inputs,
                     payload_name="", store_reasons={r: _MEDIA_REASON
                                                     for r in inputs})
    # ...and now what write_container does to that very dict. Every entry a
    # duplicate of the first is the worst case G9 can produce, and it is not a
    # contrived one: a folder of media with a duplicated subfolder is exactly
    # the shape the dedup was built for.
    first = next(iter(inputs))
    for rel in list(inputs)[1:]:
        inputs[rel]["same_as"] = first
    actual = len(m.to_json().encode("utf-8"))

    assert predicted >= actual, (
        f"estimate {predicted:,} under-reads the {actual:,} bytes actually "
        f"written - the job would be accepted and then refused at the end")


@pytest.mark.parametrize("label,name", [
    ("ascii", "file"),
    ("cyrillic", "файл"),
    ("japanese", "ファイル"),
    ("dhivehi", "ފައިލު"),
    ("emoji", "🎉"),
])
def test_the_size_estimate_holds_for_non_ascii_names(label, name):
    """The estimate costs a path at `len(rel.encode("utf-8"))`, so the document
    it is predicting has to be written as UTF-8 too.

    `json.dumps` defaults to ``ensure_ascii=True``, which emits every non-ASCII
    character as a 6-byte ``\\uXXXX`` escape (12 for an astral pair). Against a
    2-UTF-8-byte Cyrillic character that is 3x, and measured on a pipelined
    tree of Dhivehi names the estimate came out at **0.55x** what was really
    written - an under-read of 45%, on a language this product has an explicit
    edge-case test for (D2, `tests/test_edge_cases.py`).

    A *pipelined* tree is the case that exposes it: `stored_count` is 0, so
    none of the `same_as`/`codec` allowance is there to absorb the difference
    by accident. That is why this test asserts on a tree with no stored files
    at all rather than on a mixed one, where it passed while still being wrong.
    """
    inputs = {f"каталог/{name * 8}-{i}.bin":
              {"size": 1, "sha256": "a" * 64, "route": "pipeline"}
              for i in range(500)}
    predicted = manifest_size_estimate(inputs.keys(), stored_count=0)
    m = Manifest.new(profile="fast", stages=[], inputs=inputs, payload_name="")
    actual = len(m.to_json().encode("utf-8"))

    assert predicted >= actual, (
        f"{label}: estimate {predicted:,} under-reads the {actual:,} bytes "
        f"really written ({predicted / actual:.2f}x)")


def test_non_ascii_names_survive_the_container(tmp_path):
    """The other half of writing the manifest as UTF-8: it still has to read
    back. `_read_manifest` decodes UTF-8 and `zipfile` encodes a str member as
    UTF-8, so the two agree - but nothing pinned that until this test."""
    names = ["файл.bin", "ファイル.bin", "ފައިލު.bin", "photo-🎉.bin", "plain.bin"]
    inputs = {n: {"size": 1, "sha256": "a" * 64, "route": "store"} for n in names}
    arc = tmp_path / "unicode.excmp"
    write_container(arc, Manifest.new(profile="fast", stages=[], inputs=inputs,
                                      payload_name=""))
    back, _payload = read_container(arc, extract_dir=tmp_path / "x")
    assert list(back.inputs) == names


def test_the_size_estimate_counts_the_empty_directory_list():
    """K2 added `dirs`, an unbounded top-level field of full relative paths -
    and the preflight only ever saw *file* paths.

    Measured before this was fixed: 20,000 empty directories beside 10 files
    predicted 14,498 B against 1,550,859 B actually written - **0.009x, a 100x
    under-read**. The `dirs` field alone was 1,548,889 B of it.

    This is K1's defect for the third time, and this time it was introduced by
    the very phase that had just documented the rule: *a preflight has to model
    the artifact that is actually produced.* Every new manifest field costs
    bytes, and the estimate is what stands between a job and a refusal that
    arrives after all the work.
    """
    stem = "project/node_modules/@scope/package-name-here/dist/esm/internal"
    dirs = [f"{stem}/empty-{i}" for i in range(20_000)]
    inputs = {f"{stem}/f{i}.js": {"size": 10, "sha256": "a" * 64,
                                  "route": "pipeline"}
              for i in range(10)}

    predicted = manifest_size_estimate(inputs.keys(), stored_count=0, dirs=dirs)
    m = Manifest.new(profile="fast", stages=[], inputs=inputs, payload_name="",
                     dirs=dirs)
    actual = len(m.to_json().encode("utf-8"))

    assert predicted >= actual, (
        f"estimate {predicted:,} under-reads the {actual:,} bytes written - "
        f"{predicted / actual:.3f}x")


def test_the_size_estimate_still_holds_with_no_directories():
    """The default has to stay harmless: `dirs` is optional and almost every
    real job has none."""
    inputs = {f"a/b/c/file{i}.txt": {"size": 1, "sha256": "a" * 64,
                                     "route": "pipeline"}
              for i in range(200)}
    predicted = manifest_size_estimate(inputs.keys(), stored_count=0)
    actual = len(Manifest.new(profile="fast", stages=[], inputs=inputs,
                              payload_name="").to_json().encode("utf-8"))
    assert predicted >= actual


# --------------------------------------------------------------------------
# the tree that could not be archived, measured against the real thing
# --------------------------------------------------------------------------

_CORPUS = Path(
    r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check"
    r"\Programming Tutorials, Guides, Course, and Files\5React, ReactNative"
)

# Walking 57,020 files costs ~60s of pure drive metadata latency, which is not
# a price every `pytest -q` should pay. Opt in with EXCMP_SLOW_CORPUS=1; the
# result of the run that shipped K1 is in docs/ROADMAP.md.
needs_corpus = pytest.mark.skipif(
    not (_CORPUS.is_dir() and os.environ.get("EXCMP_SLOW_CORPUS")),
    reason="set EXCMP_SLOW_CORPUS=1 with the React tutorial corpus present")


@needs_corpus
def test_the_real_57k_file_tree_now_fits_the_cap(tmp_path):
    """Read-only: walks the live tree for its names, builds the manifest those
    names produce, and checks it both fits the cap and survives a container
    round-trip. Not a compress - 33.83 GiB of it would take hours, and the
    manifest is the only thing K1 changed."""
    rels = []
    for dirpath, _dirs, files in os.walk(_CORPUS):
        rel = Path(dirpath).relative_to(_CORPUS)
        rels.extend(str(rel / f).replace("\\", "/") for f in files)
    assert len(rels) > 50_000, f"expected a very large tree, walked {len(rels)}"

    inputs = {rel: {"size": 1024, "sha256": "0" * 64, "route": "store"}
              for rel in rels}
    m = Manifest.new(profile="extreme", stages=[], inputs=inputs,
                     payload_name="", store_reasons={r: _MEDIA_REASON for r in rels})
    size = len(m.to_json().encode("utf-8"))
    assert size <= MAX_MANIFEST_BYTES, \
        f"{len(rels)} files still produce {size >> 20} MiB of manifest"
    assert manifest_size_estimate(rels, stored_count=len(rels)) <= MAX_MANIFEST_BYTES

    # The cap is checked twice on the way in - once on the zip header, once on
    # the real stream - so fitting the number is not the same as being readable.
    arc = tmp_path / "real-names.excmp"
    write_container(arc, m)
    with zipfile.ZipFile(arc) as zf:
        info = zf.getinfo(MANIFEST_NAME)
    back, _payload = read_container(arc, extract_dir=tmp_path / "x")
    assert len(back.inputs) == len(rels)
    print(f"\n{len(rels):,} real paths -> {size:,} B of JSON, "
          f"{info.compress_size:,} B deflated in the container")
