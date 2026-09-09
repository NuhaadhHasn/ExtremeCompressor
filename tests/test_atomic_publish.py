"""D8: the output is forced to disk, read back, and only then renamed.

The publish path already had the *atomic* half - a `.tmp` twin and a rename -
and D9 added the *correctness* half, a full restore before that rename. What
neither covered is the gap between them:

**1. `os.replace` does not mean the bytes are on the platter.** A rename can
complete, the job can report success, and a power loss seconds later can still
leave a zero-length or partially-written archive, because the write is sitting
in the OS cache. `fsync` before the rename is the only thing that closes that.

**2. Nothing re-read the artifact after writing it.** A short write - a disk
that filled between the verify and the publish - produces a file that fails no
exit code and no assertion. Hashing the bytes back off the filesystem after
the flush is what catches it.

**3. The destination was deleted before the rename.** `compress()` did
`out_path.unlink()` and *then* `replace()`, so for the width of that window a
user overwriting yesterday's archive had neither: the old one gone, the new one
not yet there. `os.replace` replaces an existing file atomically on Windows and
POSIX both, so the unlink bought nothing and risked the only copy.

These tests pin all three, plus the cheap by-product: the digest computed for
the read-back is the digest the sidecar needs, so the sidecar stops re-reading
the whole archive to learn something we just measured.
"""

import hashlib
import os
import random
from pathlib import Path

import pytest

from excmp import engine
from excmp.atomic import PublishError, atomic_write_text, publish
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools
from excmp.verify import hash_file

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None,
                              reason="7z not installed")

PREVIOUS = b"yesterday's archive, the only copy"


def _tmp_with(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _refuse(src, dst):
    raise OSError(5, "simulated I/O error")


# --------------------------------------------------------------------------
# the flush
# --------------------------------------------------------------------------

def test_the_bytes_are_flushed_before_the_rename(tmp_path, monkeypatch):
    """Order is the whole point: an fsync after the rename protects nothing
    the caller has already been told is durable."""
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd):
        order.append("fsync")
        return real_fsync(fd)

    def spy_replace(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    tmp = _tmp_with(tmp_path / "out.bin.tmp", b"payload" * 100)
    publish(tmp, tmp_path / "out.bin")

    assert order == ["fsync", "replace"], order


def test_publish_returns_the_digest_of_what_landed(tmp_path):
    data = b"the archive" * 5_000
    tmp = _tmp_with(tmp_path / "a.bin.tmp", data)
    final = tmp_path / "a.bin"

    digest = publish(tmp, final)

    assert digest == hash_file(final)
    assert not tmp.exists(), "the .tmp twin outlived the publish"


# --------------------------------------------------------------------------
# the read-back
# --------------------------------------------------------------------------

def test_a_short_write_is_caught_and_nothing_is_published(tmp_path):
    """The disk-full shape: the expectation was computed from what we meant to
    write, the file on disk is shorter, and no exit code says so."""
    want = b"A" * 10_000
    tmp = _tmp_with(tmp_path / "b.bin.tmp", want[:4_096])   # truncated
    final = _tmp_with(tmp_path / "b.bin", PREVIOUS)

    with pytest.raises(PublishError) as err:
        publish(tmp, final, expect_sha256=hashlib.sha256(want).hexdigest())

    assert "4096" in str(err.value) or "4,096" in str(err.value)
    assert final.read_bytes() == PREVIOUS, "the previous file was destroyed"
    assert not tmp.exists(), "the rejected .tmp was left behind"


def test_the_previous_file_survives_a_failed_rename(tmp_path, monkeypatch):
    """The unlink-then-replace defect, at the unit level."""
    tmp = _tmp_with(tmp_path / "c.bin.tmp", b"new content")
    final = _tmp_with(tmp_path / "c.bin", PREVIOUS)

    monkeypatch.setattr(os, "replace", _refuse)
    with pytest.raises(OSError):
        publish(tmp, final)

    assert final.read_bytes() == PREVIOUS


def test_a_filesystem_that_renumbers_the_file_does_not_fail_the_publish(
        tmp_path, monkeypatch):
    """`st_ino` is a real file index on NTFS and survives a rename - measured.
    On FAT32/exFAT, which is what a USB stick arrives formatted as, it is
    synthesised and need not. The cheap identity triple must therefore never
    be the thing that condemns an archive: if it disagrees, the content
    decides."""
    from excmp import atomic

    tmp = _tmp_with(tmp_path / "e.bin.tmp", b"good archive, odd filesystem")
    final = tmp_path / "e.bin"
    real_identity = atomic._identity
    seen: list[int] = []

    def renumbering(path):
        dev, ino, size = real_identity(path)
        seen.append(1)
        return (dev, ino + len(seen), size)     # a different "file" each call

    monkeypatch.setattr(atomic, "_identity", renumbering)
    digest = publish(tmp, final)                # must not raise

    assert final.read_bytes() == b"good archive, odd filesystem"
    assert digest == hash_file(final)


def test_publish_confirms_the_destination_is_the_file_it_hashed(tmp_path,
                                                               monkeypatch):
    """A rename cannot change bytes - so if the thing at the destination is not
    the thing we measured, something else wrote there and we say so."""
    tmp = _tmp_with(tmp_path / "d.bin.tmp", b"measured bytes")
    final = tmp_path / "d.bin"
    real_replace = os.replace

    def impostor(src, dst):
        real_replace(src, dst)
        Path(dst).write_bytes(b"someone else's bytes entirely")

    monkeypatch.setattr(os, "replace", impostor)
    with pytest.raises(PublishError, match="not the file"):
        publish(tmp, final)


# --------------------------------------------------------------------------
# the same treatment for the small metadata files
# --------------------------------------------------------------------------

def test_atomic_write_text_leaves_no_residue_and_reports_its_digest(tmp_path):
    target = tmp_path / "notes.json"
    digest = atomic_write_text(target, '{"a": 1}\n')

    assert target.read_text(encoding="utf-8") == '{"a": 1}\n'
    assert digest == hash_file(target)
    assert list(tmp_path.iterdir()) == [target], "a .tmp was left behind"


def test_atomic_write_text_never_truncates_the_old_copy(tmp_path, monkeypatch):
    target = tmp_path / "notes.json"
    target.write_text("the record so far", encoding="utf-8")

    monkeypatch.setattr(os, "replace", _refuse)
    with pytest.raises(OSError):
        atomic_write_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "the record so far"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_text_writes_lf_not_crlf(tmp_path):
    """`sha256sum -c` reads a trailing CR as part of the filename. Two
    sidecars shipped broken on exactly this before."""
    target = tmp_path / "x.sha256"
    atomic_write_text(target, "abc  x.bin\n")
    assert target.read_bytes() == b"abc  x.bin\n"


# --------------------------------------------------------------------------
# the engine, end to end
# --------------------------------------------------------------------------

def _tree(root: Path) -> Path:
    root.mkdir()
    (root / "doc.txt").write_text(
        "publish only what you have read back. " * 4_000)
    (root / "blob.bin").write_bytes(bytes(random.Random(8).getrandbits(8)
                                          for _ in range(40_000)))
    return root


@needs_7z
def test_the_result_carries_the_digest_of_the_published_archive(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    result = engine.compress([src], arc, Profile.NORMAL, ctx)

    assert result.sha256 == hash_file(arc)


@needs_7z
def test_the_sidecar_records_the_digest_the_publish_already_measured(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")

    result = engine.compress([src], arc, Profile.NORMAL, ctx, sidecar=True)

    assert result.sidecar is not None
    digest, _, name = result.sidecar.read_text(encoding="utf-8").partition("  ")
    assert digest == result.sha256 == hash_file(arc)
    assert name.strip() == arc.name


@needs_7z
def test_a_failed_publish_leaves_yesterdays_archive_intact(tmp_path,
                                                           monkeypatch):
    """The defect this item exists for. `compress()` unlinked the destination
    and *then* renamed, so a failure in between left the user with neither
    archive - and the old one was the only copy."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "out.excmp"
    arc.write_bytes(PREVIOUS)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    real_replace = os.replace

    def refuse_the_excmp(source, dest):
        if str(dest).endswith(".excmp"):
            raise OSError(5, "simulated I/O error at the last step")
        return real_replace(source, dest)

    monkeypatch.setattr(os, "replace", refuse_the_excmp)
    with pytest.raises(OSError):
        engine.compress([src], arc, Profile.NORMAL, ctx)

    assert arc.read_bytes() == PREVIOUS
    leftovers = [p.name for p in tmp_path.glob("out.excmp.*")]
    assert leftovers == [], leftovers


@needs_7z
def test_the_encrypted_archive_that_ships_is_the_ciphertext_we_wrote(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "sealed.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    secret = "correct horse battery staple"

    result = engine.compress([src], arc, Profile.NORMAL, ctx, password=secret)

    assert result.sha256 == hash_file(arc)
    out = tmp_path / "back"
    engine.extract(arc, out, ctx, password=secret)
    assert (out / "src" / "doc.txt").read_bytes() == (src / "doc.txt").read_bytes()


def test_encryption_refuses_a_source_that_changed_since_it_was_verified(tmp_path):
    """The D9 gate proves a *plaintext* restores; what ships is a ciphertext
    produced by a second pass over that file. Nothing checked the handoff."""
    from excmp.crypto import CryptoError, encrypt_file

    plain = _tmp_with(tmp_path / "plain.bin", b"the verified archive" * 1_000)
    sealed = tmp_path / "sealed.bin"

    with pytest.raises(CryptoError, match="changed"):
        encrypt_file(plain, sealed, "pw", expect_src_sha256="00" * 32)

    assert not sealed.exists(), "a ciphertext of unverified bytes was left"


# --------------------------------------------------------------------------
# the two stores that are written after every job
# --------------------------------------------------------------------------

def test_the_calibration_store_survives_a_failed_write(tmp_path, monkeypatch):
    from excmp import calibrate

    target = tmp_path / "calibration.json"
    calibrate.record(["7z"], 50_000_000, 10.0, path=target)
    before = target.read_bytes()
    assert before

    monkeypatch.setattr(os, "replace", _refuse)
    calibrate.record(["7z"], 60_000_000, 12.0, path=target)   # never raises

    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target], "a .tmp was left behind"


def _lying_readback(path):
    """A read-back that disagrees with what was written - the shape a
    truncated write takes, and the one that raises PublishError rather than
    OSError."""
    return "de" * 32, 0


def test_the_calibration_store_never_raises_on_a_bad_readback(tmp_path,
                                                              monkeypatch):
    """`record()` promises never to raise: it runs after a job has already
    succeeded, and failing to learn from it must not turn that into a failure.
    D8 introduced a *new* exception type into that path, and PublishError is a
    RuntimeError - not covered by the OSError the caller was catching."""
    from excmp import atomic, calibrate

    target = tmp_path / "calibration.json"
    calibrate.record(["7z"], 50_000_000, 10.0, path=target)
    before = target.read_bytes()

    monkeypatch.setattr(atomic, "hash_and_size", _lying_readback)
    calibrate.record(["7z"], 60_000_000, 12.0, path=target)   # must not raise

    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_the_history_store_never_raises_on_a_bad_readback(tmp_path,
                                                          monkeypatch):
    from excmp import atomic
    from gui import history

    target = tmp_path / "history.json"
    entry = history.HistoryEntry(
        archive=str(tmp_path / "a.excmp"), inputs=["src"], profile="Normal",
        chain="7z", orig_bytes=100, final_bytes=50, elapsed_s=1.0,
        finished_at="2026-09-09T12:00:00")
    history.append(entry, path=target)
    before = target.read_bytes()

    monkeypatch.setattr(atomic, "hash_and_size", _lying_readback)
    history.append(entry, path=target)                        # must not raise

    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_the_history_store_survives_a_failed_write(tmp_path, monkeypatch):
    from gui import history

    target = tmp_path / "history.json"
    entry = history.HistoryEntry(
        archive=str(tmp_path / "a.excmp"), inputs=["src"], profile="Normal",
        chain="7z", orig_bytes=100, final_bytes=50, elapsed_s=1.0,
        finished_at="2026-09-09T12:00:00")
    history.append(entry, path=target)
    before = target.read_bytes()
    assert before

    monkeypatch.setattr(os, "replace", _refuse)
    history.append(entry, path=target)                        # never raises

    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]
