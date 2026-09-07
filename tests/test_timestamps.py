"""K2: restored files keep their original date, and empty folders come back.

Reproduced 2026-09-04. Two files given an mtime of 2023-07-31, compressed,
restored:

    text.txt  (pipeline route)  ->  2023-07-31   tar carries mtime
    rand.bin  (store route)     ->  2026-09-04   today
    emptydir/                   ->  did not come back at all

The bytes were always identical, so the lossless claim held *literally*. But
restore a photo archive and every file is dated today, which breaks
sort-by-date and reads as data loss to anyone who did not read the fine print.

Two separate causes, and fixing one does not fix the other:

* **Timestamps**: there was no `mtime`, `utime` or `st_mtime` anywhere in
  `excmp/`. The pipeline route got it for free only because `tarfile` records
  one; the store route went through `write_container`'s `zf.write` (a zip
  timestamp no reader applies) and `extract_stored`'s `target.open("wb")`,
  which sets nothing.
* **Empty directories**: `analyzer.analyze_tree` is
  `[analyze_file(p) for p in iter_files(root)]` and `iter_files` keeps only
  `p.is_file()`, so a directory with nothing in it never enters the ledger and
  there is nothing in the manifest to recreate.

The fix applies mtimes in **one pass at the end of `engine.extract`**, from the
ledger, for both routes - rather than teaching the store route to do what tar
already did. Two reasons. It makes the two routes agree by construction instead
of by coincidence, and it runs *after* F4's Mark-of-the-Web propagation, which
writes an alternate data stream and therefore updates the very timestamp we
just restored (`test_the_zone_marker_does_not_clobber_the_restored_date`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext

# 2023-07-31 12:34:56 UTC, and a second distinct date so a test cannot pass by
# setting every file to the same thing.
OLD = 1690806896
OLDER = 1279368000          # 2010-07-17


def _stamp(path: Path, when: int) -> int:
    """Set mtime and return what the filesystem actually stored, which is the
    only value a round-trip can be compared against - NTFS keeps 100 ns ticks
    and the value handed in may not land on one."""
    os.utime(path, (when, when))
    return path.stat().st_mtime_ns


def _tree(root: Path) -> tuple[Path, dict[str, int]]:
    """Both routes, plus an empty directory and a nested empty directory."""
    root.mkdir(parents=True)
    want: dict[str, int] = {}

    text = root / "text.txt"                       # compressible -> pipeline
    text.write_text("the quick brown fox\n" * 2000, encoding="utf-8")
    want["text.txt"] = _stamp(text, OLD)

    rand = root / "rand.bin"                       # high-entropy -> store
    rand.write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))
    want["rand.bin"] = _stamp(rand, OLDER)

    sub = root / "sub"
    sub.mkdir()
    nested = sub / "more.txt"
    nested.write_text("lorem ipsum dolor\n" * 2000, encoding="utf-8")
    want["sub/more.txt"] = _stamp(nested, OLD)

    (root / "emptydir").mkdir()
    (root / "deep" / "empty" / "chain").mkdir(parents=True)
    return root, want


def _roundtrip(tmp_path: Path, profile: Profile = Profile.NORMAL) -> tuple[Path, dict[str, int]]:
    src, want = _tree(tmp_path / "src")
    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, profile, StageContext(temp_dir=tmp_path / "t"))
    out = tmp_path / "restored"
    engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    return out / "src", want


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------

def test_both_routes_restore_the_original_mtime(tmp_path):
    """The headline. `rand.bin` is the one that used to come back dated today;
    `text.txt` is the control that always worked, and must not regress."""
    root, want = _roundtrip(tmp_path)
    for rel, expected in want.items():
        got = (root / rel).stat().st_mtime_ns
        assert got == expected, (
            f"{rel}: restored {got} ({(root / rel).stat().st_mtime}), "
            f"expected {expected} ({expected / 1e9})")


def test_the_store_route_specifically(tmp_path):
    """Named separately so a failure says *which* half broke. This is the
    exact file and the exact symptom from the 2026-09-04 reproduction."""
    root, want = _roundtrip(tmp_path)
    restored = (root / "rand.bin").stat().st_mtime_ns
    assert restored == want["rand.bin"]
    # And not "today", which is what it used to be.
    assert restored < 1600000000 * 10**9


def test_mtime_survives_the_fast_profile_too(tmp_path):
    """Fast is zstd rather than 7-Zip, i.e. a different tar and a different
    stage. The ledger is what carries the timestamp now, so both must work."""
    root, want = _roundtrip(tmp_path, Profile.FAST)
    for rel, expected in want.items():
        assert (root / rel).stat().st_mtime_ns == expected, rel


def test_the_zone_marker_does_not_clobber_the_restored_date(tmp_path):
    """F4 writes a Zone.Identifier alternate data stream onto restored files,
    and writing an ADS updates the host file's last-write time on NTFS. So the
    mtime pass has to run *after* propagation, not inside `extract_stored`.

    Marking the archive is what makes this path run at all; without a zone on
    the source there is nothing to propagate and the test would pass for the
    wrong reason.
    """
    src, want = _tree(tmp_path / "src")
    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    try:
        with open(f"{archive}:Zone.Identifier", "w", encoding="utf-8") as fh:
            fh.write("[ZoneTransfer]\nZoneId=3\n")
    except OSError:
        pytest.skip("filesystem does not support alternate data streams")

    out = tmp_path / "restored"
    engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    for rel, expected in want.items():
        assert (out / "src" / rel).stat().st_mtime_ns == expected, \
            f"{rel} lost its date to the zone marker"


def test_a_pre_k2_archive_still_verifies(tmp_path):
    """`verify_restore` must NOT start comparing timestamps.

    Every archive written before K2 has no mtime in its ledger. If
    verification began requiring one, all of them would fail to verify - and
    "your archive is corrupt" is a far worse outcome than "your file is dated
    today". So an entry with no mtime restores without complaint.
    """
    from excmp.verify import verify_restore

    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_bytes(b"hello")
    from excmp.verify import hash_file
    ledger = {"a.txt": {"size": 5, "sha256": hash_file(out / "a.txt"),
                        "route": "store"}}          # no mtime_ns key at all
    assert verify_restore(out, ledger) == 1


def test_an_mtime_free_ledger_entry_restores_without_error(tmp_path):
    """The other half of backward compatibility: extraction must not assume
    the key exists. Pinned through the real container writer."""
    from excmp.manifest import Manifest, extract_stored, write_container
    from excmp.verify import hash_file

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.bin"
    f.write_bytes(b"A" * 100)
    ledger = {"a.bin": {"size": 100, "sha256": hash_file(f), "route": "store"}}
    arc = tmp_path / "old.excmp"
    write_container(arc, Manifest.new(profile="fast", stages=[], inputs=ledger,
                                      payload_name=""), None, {"a.bin": f})
    out = tmp_path / "out"
    written = extract_stored(arc, out, ledger)
    assert len(written) == 1 and (out / "a.bin").read_bytes() == b"A" * 100


# --------------------------------------------------------------------------
# empty directories
# --------------------------------------------------------------------------

def test_an_empty_directory_comes_back(tmp_path):
    root, _want = _roundtrip(tmp_path)
    assert (root / "emptydir").is_dir(), "an empty folder was silently dropped"


def test_a_chain_of_empty_directories_comes_back(tmp_path):
    """`deep/empty/chain` has no files at any level. Recording only the
    deepest one is enough, because recreating it with parents rebuilds the
    rest - but the *deepest* is the one that has to be recorded, not the
    shallowest."""
    root, _want = _roundtrip(tmp_path)
    assert (root / "deep" / "empty" / "chain").is_dir()


def test_a_directory_that_only_holds_files_is_not_recorded_twice(tmp_path):
    """The manifest should not carry directories that the file paths already
    imply - that was the whole `routes[].files` mistake K1 just removed."""
    import zipfile, json
    from excmp.manifest import MANIFEST_NAME

    src, _want = _tree(tmp_path / "src")
    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    with zipfile.ZipFile(archive) as zf:
        data = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    dirs = data.get("dirs", [])
    assert "src/sub" not in dirs, "sub holds a file; its path is already implied"
    assert sorted(dirs) == ["src/deep/empty/chain", "src/emptydir"], dirs


def test_the_empty_directory_list_cannot_escape_the_output(tmp_path):
    """`dirs` is archive-supplied, so it is exactly as untrusted as every
    ledger key and payload name D0 hardened. A hostile entry must never reach
    the filesystem.

    It is **skipped rather than raised on**, and that is deliberate. This pass
    runs after `verify_restore`, so raising would report a restore whose every
    byte verified byte-identical as a failure - which an audit caught the first
    version of this code doing for an entirely innocent input: a destination
    that already held a file where an empty chain's parent had to go.
    Containment is the property that matters here; refusing loudly is what
    `safepath` does at the points where nothing has been restored yet.
    """
    import zipfile, json
    from excmp.manifest import MANIFEST_NAME, ContainerError, read_container
    from excmp.safepath import UnsafePathError

    manifest = {
        "schema": 2, "created_utc": "", "profile": "fast", "stages": [],
        "inputs": {}, "payload_name": "", "warnings": [], "routes": [],
        "reasons": [], "dirs": ["../../escaped"],
    }
    arc = tmp_path / "evil.excmp"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest))
    out = tmp_path / "deep" / "deeper" / "out"
    out.mkdir(parents=True)
    engine.extract(arc, out, StageContext(temp_dir=tmp_path / "t"))
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "deep" / "escaped").exists()
    assert not (tmp_path / "deep" / "deeper" / "escaped").exists()
    assert list(out.rglob("*")) == [], \
        "a hostile dirs entry created something in the destination"
