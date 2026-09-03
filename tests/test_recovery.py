"""F3 — recovery records: the one feature WinRAR has that no OSS archiver does.

A verified archive tells you *that* it broke. A recovery record lets you fix
it. Those are different promises and this product should make both, because
the failure it protects against is the ordinary one: a bad sector, a truncated
download, a USB stick pulled early. Every other guarantee in this codebase
detects that and then shrugs.

Proven end-to-end before a line of this was written: 200 KB zeroed out of the
middle of a 5.7 MB archive, `par2 repair` restored it **byte-identically**, and
our own `verify` then passed 32/32 hashes.

**Why par2 as a subprocess.** PAR2 is Reed-Solomon over GF(2^16) with
self-describing, MD5-checked packets — strictly stronger than the XOR `-rr`
FreeArc used, where two bad sectors in one residue class are unrecoverable
(research/18 §5). `par2cmdline-turbo` ships a real Windows binary in its wheel,
and driving it as a separate process is what keeps its GPL out of our
in-process code, exactly as planned for every other tool here.

par2's exit codes, measured on this machine rather than assumed:

| code | meaning |
|------|---------|
| 0 | healthy |
| 1 | damaged, and the records are enough to fix it |
| 2 | damaged beyond what the records can fix |
| 3 | no recovery records found |
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from excmp.recovery import (RecoveryStatus, available, create, default_percent,
                            recovery_files, repair, verify)
from excmp.stages.base import StageContext

needs_par2 = pytest.mark.skipif(not available(), reason="par2 not installed")


def _archive(tmp_path: Path, size: int = 400_000) -> Path:
    """Stand-in for a real archive. Content is incompressible-ish so par2's
    block maths behaves like it would on a genuine one."""
    p = tmp_path / "a.excmp"
    p.write_bytes(bytes((i * 37 + 11) % 251 for i in range(size)))
    return p


def _damage(path: Path, start: int, length: int) -> None:
    raw = bytearray(path.read_bytes())
    raw[start:start + length] = b"\x00" * length
    path.write_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# How much protection to buy
# ---------------------------------------------------------------------------

def test_small_archives_get_a_bigger_share():
    """FreeArc's tiering, and the logic is sound: 4% of a 10 MB archive is
    400 KB, which is nothing, and the archive is small enough that losing it
    outright is the likely failure. 4% of 50 GB is 2 GB, which is absurd."""
    assert default_percent(5 << 20) > default_percent(500 << 20)
    assert default_percent(500 << 20) > default_percent(50 << 30)


def test_the_dose_stays_in_a_sane_band():
    for size in (1, 1 << 20, 1 << 30, 1 << 40):
        pct = default_percent(size)
        assert 1 <= pct <= 10, f"{size} bytes -> {pct}%"


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------

@needs_par2
def test_creating_records_produces_sidecars(tmp_path):
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    made = create(archive, 5, ctx)
    assert made, "no .par2 files were written"
    assert all(p.suffix == ".par2" for p in made)
    assert all(p.exists() and p.stat().st_size > 0 for p in made)


@needs_par2
def test_the_archive_itself_is_not_touched(tmp_path):
    """Recovery records are sidecars. Rewriting the archive to embed them
    would invalidate every hash already published for it."""
    archive = _archive(tmp_path)
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    create(archive, 5, StageContext(temp_dir=tmp_path / "t", threads=2))
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before


@needs_par2
def test_recovery_files_finds_what_was_written(tmp_path):
    archive = _archive(tmp_path)
    made = create(archive, 5, StageContext(temp_dir=tmp_path / "t", threads=2))
    assert set(recovery_files(archive)) == set(made)


def test_recovery_files_is_empty_when_there_are_none(tmp_path):
    assert recovery_files(_archive(tmp_path)) == []


# ---------------------------------------------------------------------------
# Verifying - the four states, measured
# ---------------------------------------------------------------------------

@needs_par2
def test_a_healthy_archive_verifies(tmp_path):
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 5, ctx)
    assert verify(archive, ctx) is RecoveryStatus.OK


@needs_par2
def test_light_damage_is_reported_as_repairable(tmp_path):
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 10, ctx)
    _damage(archive, 50_000, 10_000)
    assert verify(archive, ctx) is RecoveryStatus.REPAIRABLE


@needs_par2
def test_damage_beyond_the_records_says_so(tmp_path):
    """The honest answer when it cannot be fixed. Saying "repairable" here and
    failing later would be worse than saying nothing."""
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 5, ctx)
    _damage(archive, 10_000, 350_000)
    assert verify(archive, ctx) is RecoveryStatus.UNREPAIRABLE


@needs_par2
def test_no_records_is_its_own_answer(tmp_path):
    """Not an error and not damage. An archive without recovery records is
    the normal case - the feature is opt-in."""
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    assert verify(archive, ctx) is RecoveryStatus.NO_RECORDS


# ---------------------------------------------------------------------------
# Repairing - the point of the whole thing
# ---------------------------------------------------------------------------

@needs_par2
def test_a_damaged_archive_is_repaired_byte_identically(tmp_path):
    """The headline. Not "it opens again" - the exact original bytes."""
    archive = _archive(tmp_path, 800_000)
    pristine = hashlib.sha256(archive.read_bytes()).hexdigest()
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 10, ctx)

    _damage(archive, 300_000, 40_000)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() != pristine

    assert repair(archive, ctx) is True
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == pristine


@needs_par2
def test_repair_refuses_rather_than_half_fixing(tmp_path):
    """When the damage exceeds the records, repair must return False and not
    leave a plausible-looking wreck behind."""
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 5, ctx)
    _damage(archive, 10_000, 350_000)
    assert repair(archive, ctx) is False


@needs_par2
def test_repairing_a_healthy_archive_is_a_no_op(tmp_path):
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    create(archive, 5, ctx)
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert repair(archive, ctx) is True
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before


@needs_par2
def test_repairing_without_records_is_false_not_an_exception(tmp_path):
    archive = _archive(tmp_path)
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    assert repair(archive, ctx) is False


# ---------------------------------------------------------------------------
# The real thing, end to end
# ---------------------------------------------------------------------------

@needs_par2
def test_a_real_excmp_survives_damage_and_still_restores(tmp_path):
    """The whole feature in one test: build a genuine archive, protect it,
    shoot a hole in it, repair it, and prove the *files inside* come back."""
    from excmp.engine import compress, extract
    from excmp.planner import Profile

    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"recoverable content " * 20_000)
    (src / "sub" / "b.bin").write_bytes(bytes(range(256)) * 2_000)
    want = {p.relative_to(src).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in src.rglob("*") if p.is_file()}

    archive = tmp_path / "real.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)
    compress([src], archive, Profile.FAST, ctx)
    create(archive, 10, ctx)

    _damage(archive, archive.stat().st_size // 3, 20_000)
    assert verify(archive, ctx) is RecoveryStatus.REPAIRABLE
    assert repair(archive, ctx) is True

    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))
    got = {p.relative_to(out).as_posix():
           hashlib.sha256(p.read_bytes()).hexdigest()
           for p in out.rglob("*") if p.is_file()}
    for rel, digest in want.items():
        match = [v for k, v in got.items() if k.endswith(rel)]
        assert match and match[0] == digest, f"{rel} did not survive the repair"
