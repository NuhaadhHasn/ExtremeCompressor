"""Verification, exposed (UI v3 wave 3 / research/23 §5).

The engine has always done a full restore + per-file SHA-256 before it lets an
archive become the user's output (`_verify_before_publish`, the D9 gate). But
that only ever ran *implicitly*, at compress time. There was no way to ask
"is this archive still good?" about a file that has been sitting on a drive,
copied over a network, or backed up and restored - which is precisely when
people want to know, and precisely what this project claims to be for.

So the gate becomes a public verb: `engine.verify_archive`, `excmp verify`,
and a button. The rule these tests exist to pin: **verification means a real
restore of every byte, compared against the ledger** - never a container
self-test, never a size check. Tool exit codes cannot be trusted (srep64.exe
once exit(0)'d on an archive it had corrupted), which is why the D9 gate
replaced `7z t` in the first place, and why this verb must not quietly become
a cheap lookalike later.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.cli import main as cli_main
from excmp.manifest import STORED_PREFIX
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.verify import VerifyError, hash_file


@pytest.fixture
def archive(tmp_path):
    """A real .excmp with both a pipelined and a stored file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "notes.txt").write_text("compressible. " * 2000, encoding="utf-8")
    # High entropy, so the planner routes it to store/ and we get a stored
    # entry to tamper with later.
    (src / "random.bin").write_bytes(bytes((i * 137 + 11) % 256 for i in range(60_000)))

    out = tmp_path / "bundle.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], out, Profile.FAST, ctx)
    return out


def _ctx(tmp_path):
    return StageContext(temp_dir=tmp_path / "vtmp")


# ---------------------------------------------------------------------------
# engine.verify_archive
# ---------------------------------------------------------------------------

def test_a_good_archive_verifies_every_file(archive, tmp_path):
    result = engine.verify_archive(archive, _ctx(tmp_path))
    assert result.ok is True
    assert result.files_restored == 2
    assert result.verified == 2
    assert result.problem == ""


def test_verification_is_a_real_restore_not_a_container_test(archive, tmp_path):
    """Corrupt a *stored* entry's bytes, leaving the zip structurally valid and
    its own CRC intact - `7z t` would pass this. A ledger-backed restore must
    not, because the file no longer matches the SHA-256 recorded at compress
    time. This is the exact failure mode that made D9 replace `7z t`."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        stored = [n for n in names if n.startswith(STORED_PREFIX)]
        assert stored, "corpus produced no stored entry to corrupt"
        payload = {n: zf.read(n) for n in names}

    victim = stored[0]
    payload[victim] = b"\x00" + payload[victim][1:]      # one byte, same length
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
        for name, data in payload.items():
            zf.writestr(name, data)

    with pytest.raises(VerifyError) as excinfo:
        engine.verify_archive(archive, _ctx(tmp_path))
    assert "hash mismatch" in str(excinfo.value)


def test_verifying_never_touches_the_archive_or_leaves_a_restore_behind(
        archive, tmp_path):
    """Inputs are never modified - a verify is read-only - and a full restore
    of a large archive must not silently fill the temp drive."""
    before = hash_file(archive)
    temp = tmp_path / "vtmp"
    engine.verify_archive(archive, StageContext(temp_dir=temp))
    assert hash_file(archive) == before

    leftovers = [p for p in temp.rglob("*") if p.is_file()] if temp.exists() else []
    assert leftovers == [], f"verify left {len(leftovers)} file(s) behind"


def test_the_publish_gate_and_the_verb_are_the_same_code(archive, tmp_path,
                                                         monkeypatch):
    """D9's promise is that nothing publishes without a verified restore. If
    the button and the gate ever diverge, one of them is a lie - so the gate
    is implemented *in terms of* the public verb."""
    calls = []
    real = engine.verify_archive

    def spy(arc, ctx, **kw):
        calls.append(Path(arc))
        return real(arc, ctx, **kw)

    monkeypatch.setattr(engine, "verify_archive", spy)
    src = tmp_path / "s2"
    src.mkdir()
    (src / "a.txt").write_text("x" * 5000, encoding="utf-8")
    engine.compress([src], tmp_path / "two.excmp", Profile.FAST,
                    StageContext(temp_dir=tmp_path / "t2"))
    assert calls, "compress() published without going through verify_archive"


# ---------------------------------------------------------------------------
# excmp verify / excmp hash
# ---------------------------------------------------------------------------

def test_the_verify_verb_reports_success(archive, capsys):
    assert cli_main(["verify", str(archive)]) == 0
    out = capsys.readouterr().out
    assert "2" in out and "verified" in out.lower()


def test_the_verify_verb_fails_loudly_on_a_bad_archive(tmp_path, capsys):
    broken = tmp_path / "broken.excmp"
    broken.write_bytes(b"not a zip at all")
    assert cli_main(["verify", str(broken)]) == 1
    assert "error" in capsys.readouterr().err.lower()


def test_the_verify_verb_speaks_json(archive, capsys):
    assert cli_main(["verify", str(archive), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["verified"] == 2
    assert payload["archive"].endswith("bundle.excmp")


def test_the_hash_verb_prints_a_sha256_per_file(tmp_path, capsys):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"hello")
    b.write_bytes(b"world")

    assert cli_main(["hash", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert hash_file(a) in out and hash_file(b) in out
    # sha256sum's own layout: "<hash>  <path>", so the output pipes into the
    # tools people already have.
    assert f"{hash_file(a)}  {a}" in out


def test_the_hash_verb_speaks_json(tmp_path, capsys):
    a = tmp_path / "a.bin"
    a.write_bytes(b"hello")
    assert cli_main(["hash", str(a), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["sha256"] == hash_file(a)
    assert payload[0]["size"] == 5


def test_hashing_a_missing_file_is_an_error_not_a_crash(tmp_path, capsys):
    assert cli_main(["hash", str(tmp_path / "nope.bin")]) == 1
    assert "error" in capsys.readouterr().err.lower()
