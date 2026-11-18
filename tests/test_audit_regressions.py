"""The four critical defects an adversarial audit found on 2026-09-03.

Every one of them was reachable from a shipped surface, every one passed the
811-test suite, and three of the four **reported success** while doing the
wrong thing. That last property is what they have in common and why they are
grouped here rather than filed with their features: a loud failure is a bug, a
quiet one is a broken promise.

1. `compress_standard` archived only `inputs[0]` and silently dropped the
   rest — data loss, reported as a 99% saving.
2. The same function verified **nothing** whenever the input was not exactly
   one directory, while its own note said every file had been checked.
3. An encrypted `.excmp` was unopenable by every shipped surface. `list_any`
   told the user the archive "appears damaged" — the precise lie
   `crypto.py`'s docstring warns is how archives get deleted.
4. A split `.excmp` extracted through the GUI's code path fell through to the
   foreign-archive branch: 7-Zip joined the volumes generically, dumped the
   container's own `manifest.json` into the destination, and reported success
   with `verified=0`.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext, StageError
from excmp.tools import find_tools
from excmp.volumes import split_file

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7-Zip not installed")


def _ctx(tmp_path: Path, name: str = "t") -> StageContext:
    return StageContext(temp_dir=tmp_path / name, threads=2)


def _tree(root: Path, count: int = 3, size: int = 4000) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    out = {}
    for n in range(count):
        p = root / f"f{n}.txt"
        p.write_bytes(bytes((i * 7 + n) % 251 for i in range(size)))
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# 1 + 2. compress_standard
# ---------------------------------------------------------------------------

@needs_7z
def test_every_input_reaches_a_plain_archive(tmp_path):
    """It archived `inputs[0]` and threw the rest away, then reported the
    original size of *all* of them - so three files in, one file archived,
    and a headline "99% saved"."""
    src = tmp_path / "src"
    digests = _tree(src)
    files = sorted(src.iterdir())
    out = tmp_path / "multi.7z"

    engine.compress_standard(files, out, "7z", _ctx(tmp_path))

    listing = subprocess.run(
        [find_tools()["7z"].path, "l", "-ba", str(out)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    for name in digests:
        assert name in listing, f"{name} never reached the archive:\n{listing}"


@needs_7z
def test_a_plain_export_verifies_every_file_it_archived(tmp_path):
    """`want` was built from a `source` that is None unless the input is
    exactly one directory, so the comparison loop never ran, `verified` stayed
    0, and the archive published anyway."""
    src = tmp_path / "src"
    digests = _tree(src)
    result = engine.compress_standard(sorted(src.iterdir()), tmp_path / "m.zip",
                                      "zip", _ctx(tmp_path))
    assert result.verified == len(digests), (
        f"verified {result.verified} of {len(digests)}")


@needs_7z
def test_a_single_file_export_is_verified_too(tmp_path):
    """The most ordinary input of all, and the one that verified nothing."""
    lone = tmp_path / "lone.txt"
    lone.write_bytes(b"just the one file " * 500)
    result = engine.compress_standard([lone], tmp_path / "one.7z", "7z",
                                      _ctx(tmp_path))
    assert result.verified == 1


@needs_7z
def test_a_plain_export_that_verifies_nothing_is_refused(tmp_path):
    """The general rule behind both of the above: a gate that can legitimately
    pass having checked zero files is not a gate."""
    src = tmp_path / "src"
    _tree(src, count=1)
    import excmp.engine as eng

    real = eng._hash_tree
    # Make the *restored* tree look empty, as if nothing came back out.
    eng._hash_tree = lambda root: ({} if "check" in Path(root).parts
                                   else real(root))
    try:
        with pytest.raises(StageError):
            eng.compress_standard([src], tmp_path / "x.7z", "7z", _ctx(tmp_path))
        assert not (tmp_path / "x.7z").exists()
    finally:
        eng._hash_tree = real


# ---------------------------------------------------------------------------
# 3. Encrypted archives must be reachable
# ---------------------------------------------------------------------------

@needs_7z
def test_an_encrypted_archive_extracts_through_the_shipped_entry_point(tmp_path):
    """`extract_any` is what both the CLI and the GUI call. Encryption made
    every one of them fail, so F1 archives were write-only."""
    src = tmp_path / "src"
    digests = _tree(src)
    arc = tmp_path / "locked.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path), password="hunter2")

    out = tmp_path / "out"
    result = engine.extract_any(arc, out, _ctx(tmp_path, "x"), password="hunter2")
    assert result.verified == len(digests)
    assert result.ledger_backed is True
    for name, digest in digests.items():
        match = [p for p in out.rglob("*") if p.is_file() and p.name == name]
        assert match, f"{name} did not come back"
        assert hashlib.sha256(match[0].read_bytes()).hexdigest() == digest
        assert len(match) == 1, f"{name} came back more than once"


@needs_7z
def test_an_encrypted_archive_without_a_password_says_so(tmp_path):
    """It said "the file appears damaged" - the exact lie crypto.py's own
    docstring calls out as how archives get deleted."""
    src = tmp_path / "src"
    _tree(src, count=1)
    arc = tmp_path / "locked.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path), password="pw")

    with pytest.raises(engine.EncryptedArchiveError):
        engine.extract_any(arc, tmp_path / "out", _ctx(tmp_path, "x"))


@needs_7z
def test_listing_an_encrypted_archive_asks_for_the_password(tmp_path):
    src = tmp_path / "src"
    _tree(src, count=1)
    arc = tmp_path / "locked.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path), password="pw")

    with pytest.raises(engine.EncryptedArchiveError):
        engine.list_any(arc, _ctx(tmp_path, "x"))

    listing = engine.list_any(arc, _ctx(tmp_path, "x2"), password="pw")
    assert listing.entries, "the listing came back empty with the right password"


@needs_7z
def test_verifying_an_encrypted_archive_works_with_the_password(tmp_path):
    src = tmp_path / "src"
    digests = _tree(src)
    arc = tmp_path / "locked.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path), password="pw")

    result = engine.verify_archive(arc, _ctx(tmp_path, "x"), password="pw")
    assert result.verified == len(digests)


# ---------------------------------------------------------------------------
# 4. Split archives must not fall through to the foreign path
# ---------------------------------------------------------------------------

@needs_7z
def test_a_split_archive_extracts_with_its_ledger_intact(tmp_path):
    """`is_excmp('.001')` is False, so this fell through to the foreign
    branch: 7-Zip joined the volumes generically, wrote the container's own
    `manifest.json` into the destination, and returned verified=0 with
    ledger_backed=False - reporting success the whole way."""
    src = tmp_path / "src"
    digests = _tree(src, count=3, size=80_000)
    arc = tmp_path / "big.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path))

    parts = split_file(arc, arc.stat().st_size // 4)
    assert len(parts) > 1, "the corpus did not actually split"
    arc.unlink()

    out = tmp_path / "out"
    result = engine.extract_any(parts[0], out, _ctx(tmp_path, "x"))

    landed = {p.name for p in out.rglob("*") if p.is_file()}
    assert "manifest.json" not in landed, "container internals leaked out"
    assert "payload.7z" not in landed
    assert result.ledger_backed is True, "the ledger guarantee was lost"
    assert result.verified == len(digests)
    for name, digest in digests.items():
        match = [p for p in out.rglob("*") if p.is_file() and p.name == name]
        assert match and hashlib.sha256(
            match[0].read_bytes()).hexdigest() == digest


@needs_7z
def test_a_split_and_encrypted_archive_works(tmp_path):
    """Both container shapes at once - the case that proves they compose
    rather than each being special-cased."""
    src = tmp_path / "src"
    digests = _tree(src, count=2, size=60_000)
    arc = tmp_path / "both.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path), password="pw")

    parts = split_file(arc, arc.stat().st_size // 3)
    assert len(parts) > 1
    arc.unlink()

    out = tmp_path / "out"
    result = engine.extract_any(parts[0], out, _ctx(tmp_path, "x"), password="pw")
    assert result.verified == len(digests)
    assert result.ledger_backed is True


# ---------------------------------------------------------------------------
# The HIGH findings from the same audit
# ---------------------------------------------------------------------------

def _packable_jpeg() -> bytes | None:
    """A real JPEG lepton will accept, or None. Lepton refuses CMYK and
    anything wider than 16384px, which is 38% of one real folder here."""
    import excmp.jpeg as jpeg

    if not jpeg.available():
        return None
    # The original folder was moved to C:\DevCache\_trash on 2026-11-16, so the
    # test skipped silently. A byte-identical copy (123 files, 666,560,229 B,
    # hash-compared) sits in the bench folder for exactly this; remove it and
    # this line together when the corpus is no longer needed.
    roots = (Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
                  r"\0No Need To Check\My Graphical Projects"),
             Path(r"C:\excmp-bench\corpora\My Graphical Projects"))
    root = next((r for r in roots if r.exists()), None)
    if root is None:
        return None
    for candidate in root.rglob("*.jpg"):
        try:
            raw = candidate.read_bytes()
        except OSError:
            continue
        if len(raw) < 3_000_000 and jpeg.pack(raw) is not None:
            return raw
    return None


def test_two_identical_packable_jpegs_do_not_break_compression(tmp_path):
    """This failed the whole compress, and two copies of one photo is all it
    took.

    The G9 duplicate pass copied the *source* entry's member across verbatim,
    but for a lepton entry that member holds packed bytes - smaller than the
    JPEG it restores to - so the size check fired: "holds 20162 bytes, the
    ledger declares 23906".
    """
    raw = _packable_jpeg()
    if raw is None:
        pytest.skip("no lepton-packable JPEG available on this machine")

    src = tmp_path / "src"
    src.mkdir()
    (src / "one.jpg").write_bytes(raw)
    (src / "two.jpg").write_bytes(raw)          # identical -> same_as
    (src / "three.jpg").write_bytes(raw[:-100] + b"x" * 100)   # different
    want = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in src.iterdir()}

    arc = tmp_path / "photos.excmp"
    engine.compress([src], arc, Profile.FAST, _ctx(tmp_path))

    out = tmp_path / "out"
    engine.extract(arc, out, _ctx(tmp_path, "x"))
    for name, digest in want.items():
        match = [p for p in out.rglob("*") if p.is_file() and p.name == name]
        assert match, f"{name} did not come back"
        assert hashlib.sha256(match[0].read_bytes()).hexdigest() == digest
        assert len(match) == 1, f"{name} came back more than once"


def test_the_plaintext_container_never_appears_beside_the_output(tmp_path):
    """With a password, the complete unencrypted archive used to sit at
    `<out>.tmp` in the destination folder for the whole pre-publish restore -
    the one place a user would least expect to find it."""
    src = tmp_path / "src"
    _tree(src, count=2)
    dest = tmp_path / "dest"
    dest.mkdir()

    seen: set[str] = set()

    def watch(stage: str, pct: float) -> None:
        seen.update(p.name for p in dest.iterdir())

    ctx = StageContext(temp_dir=tmp_path / "t", threads=2, progress_cb=watch)
    engine.compress([src], dest / "x.excmp", Profile.FAST, ctx, password="pw")

    assert not seen, f"these appeared in the destination mid-job: {sorted(seen)}"
    assert [p.name for p in dest.iterdir()] == ["x.excmp"]


def test_needs_keyfile_does_not_read_the_whole_archive(tmp_path):
    """It used `read_bytes()[:n]` to look at 55 bytes of header, which pulls
    the entire archive into memory first."""
    import tracemalloc

    from excmp.crypto import Argon2Params, encrypt_file, needs_keyfile

    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (40 << 20))          # 40 MiB
    enc = tmp_path / "big.enc"
    encrypt_file(big, enc, "pw", Argon2Params(memory_kib=8, time_cost=1,
                                              parallelism=1))

    tracemalloc.start()
    needs_keyfile(enc)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < (4 << 20), f"peaked at {peak >> 20} MiB reading a header"


def test_an_absurd_lane_count_for_the_memory_is_refused(tmp_path):
    """argon2 requires memory >= 8 * lanes. Without the check its own
    HashingError escapes as a bare library exception instead of "this archive
    is malformed"."""
    from excmp.crypto import (Argon2Params, CorruptArchiveError, _HEADER,
                              decrypt_file, encrypt_file)

    plain = tmp_path / "p.bin"
    plain.write_bytes(b"content")
    enc = tmp_path / "e"
    encrypt_file(plain, enc, "pw", Argon2Params(memory_kib=8, time_cost=1,
                                                parallelism=1))
    raw = bytearray(enc.read_bytes())
    fields = list(_HEADER.unpack(bytes(raw[:_HEADER.size])))
    fields[5] = 16              # 16 lanes against 8 KiB of memory
    raw[:_HEADER.size] = _HEADER.pack(*fields)
    enc.write_bytes(bytes(raw))

    with pytest.raises(CorruptArchiveError):
        decrypt_file(enc, tmp_path / "d", "pw")
