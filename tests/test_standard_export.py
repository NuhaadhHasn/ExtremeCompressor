"""G4 — writing a plain `.7z` or `.zip` that anyone can open.

The lock-in objection is fair and this is the answer to it: a checkbox that
produces an ordinary archive, openable by 7-Zip, Windows Explorer, macOS
Archive Utility, `unzip`, anything.

**What you give up, stated plainly.** A standard archive has no manifest, so
it has no per-file SHA-256 ledger, so there is nothing for `verify_restore` to
check against later. The verified-restore guarantee is a property of *our*
container, not of us.

**What you keep.** We still verify at *creation*: the archive is extracted to
temp and every file compared against the original by hash before we hand it
over. So the archive you get has been proven to restore once, on this machine,
right now — we simply cannot prove it again in six months the way an `.excmp`
can. That distinction is exactly what the reporting has to say, and the tests
below pin the wording as much as the bytes.
"""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from excmp.engine import compress_standard
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7-Zip not installed")


def _corpus(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"hello there " * 2000)
    (src / "sub" / "b.bin").write_bytes(bytes(range(256)) * 400)
    (src / "sub" / "empty").write_bytes(b"")
    digests = {p.relative_to(src).as_posix():
               hashlib.sha256(p.read_bytes()).hexdigest()
               for p in src.rglob("*") if p.is_file()}
    return src, digests


# ---------------------------------------------------------------------------
# It really is a standard archive
# ---------------------------------------------------------------------------

@needs_7z
def test_a_zip_export_opens_with_the_stdlib(tmp_path):
    """The strongest possible statement that this is not our format: Python's
    own `zipfile` reads it, with no code of ours involved."""
    src, digests = _corpus(tmp_path)
    out = tmp_path / "plain.zip"
    result = compress_standard([src], out, "zip",
                               StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.archive.exists()

    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        names = {n.replace("\\", "/").split("/", 1)[-1] if "/" in n else n
                 for n in zf.namelist()}
        for rel in digests:
            assert any(n.endswith(rel) for n in zf.namelist()), \
                f"{rel} missing from {sorted(zf.namelist())}"


@needs_7z
def test_a_7z_export_opens_with_7zip_itself(tmp_path):
    src, _digests = _corpus(tmp_path)
    out = tmp_path / "plain.7z"
    compress_standard([src], out, "7z",
                      StageContext(temp_dir=tmp_path / "t", threads=2))
    exe = find_tools()["7z"].path
    proc = subprocess.run([exe, "t", "-y", str(out)], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    assert proc.returncode == 0, proc.stdout[-400:]


@needs_7z
def test_there_is_no_manifest_in_it(tmp_path):
    """If a `manifest.json` leaked in, the file would not be a plain archive -
    it would be our container wearing a different extension."""
    src, _ = _corpus(tmp_path)
    out = tmp_path / "plain.zip"
    compress_standard([src], out, "zip",
                      StageContext(temp_dir=tmp_path / "t", threads=2))
    with zipfile.ZipFile(out) as zf:
        assert not any("manifest.json" in n for n in zf.namelist())
        assert not any(n.startswith("stored/") for n in zf.namelist())


# ---------------------------------------------------------------------------
# We still prove it restores, once, now
# ---------------------------------------------------------------------------

@needs_7z
def test_creation_is_verified_by_extracting_and_hashing(tmp_path):
    src, digests = _corpus(tmp_path)
    out = tmp_path / "plain.7z"
    result = compress_standard([src], out, "7z",
                               StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.verified == len(digests), (
        f"verified {result.verified} of {len(digests)} files")


@needs_7z
def test_a_broken_archive_is_never_published(tmp_path, monkeypatch):
    """Same rule as the `.excmp` path: if it does not restore, no file appears
    at the destination. The guarantee we cannot make *later* is still made
    *now*."""
    import excmp.engine as engine

    src, _ = _corpus(tmp_path)
    out = tmp_path / "plain.7z"

    real = engine._hash_tree

    def sabotage(root):
        # Only the *restored* tree comes back wrong. Patching both sides would
        # corrupt them identically and they would still match - which is how
        # the first version of this test passed a broken archive.
        digests = real(root)
        if "check" in Path(root).parts:
            return {k: "0" * 64 for k in digests}
        return digests

    monkeypatch.setattr(engine, "_hash_tree", sabotage)
    with pytest.raises(Exception):
        compress_standard([src], out, "7z",
                          StageContext(temp_dir=tmp_path / "t", threads=2))
    assert not out.exists(), "a failed export left a file behind"


# ---------------------------------------------------------------------------
# Honesty about what is missing
# ---------------------------------------------------------------------------

@needs_7z
def test_the_result_says_it_carries_no_ledger(tmp_path):
    """The whole point of the reporting: a standard archive cannot be
    re-verified later, and the caller must be able to say so rather than
    implying the `.excmp` guarantee."""
    src, _ = _corpus(tmp_path)
    out = tmp_path / "plain.zip"
    result = compress_standard([src], out, "zip",
                               StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.has_ledger is False
    assert "verif" in result.note.lower() or "check" in result.note.lower()
    assert result.note, "no explanation of what was given up"


def test_an_unknown_format_is_refused(tmp_path):
    src, _ = _corpus(tmp_path)
    with pytest.raises(ValueError, match="rar|format"):
        compress_standard([src], tmp_path / "x.rar", "rar",
                          StageContext(temp_dir=tmp_path / "t", threads=2))


# ---------------------------------------------------------------------------
# The combination that used to fail silently
# ---------------------------------------------------------------------------

@needs_7z
def test_a_password_with_a_plain_format_is_refused_not_ignored(tmp_path):
    """The worst bug of its kind: the user asks for protection and gets an
    archive with none, believing otherwise.

    Until 2026-09-03 the GUI called compress_standard() without the password
    at all, so picking .zip and typing a password wrote a plain, unencrypted
    archive and said nothing. Refusing is the only honest answer: wrapping the
    output in our container would stop it being a plain .zip, which is the
    only reason the format exists, and quietly substituting `7z -p` would hand
    them the very scheme F1 was built to replace.
    """
    src, _ = _corpus(tmp_path)
    out = tmp_path / "plain.zip"
    with pytest.raises(ValueError, match="excmp|password|encryption"):
        compress_standard([src], out, "zip",
                          StageContext(temp_dir=tmp_path / "t", threads=2),
                          password="hunter2")
    assert not out.exists(), "a refused job still wrote a file"


@needs_7z
def test_the_refusal_names_the_way_out(tmp_path):
    """An error that only says "no" makes the user guess. This one has to name
    the format that *does* support a password."""
    src, _ = _corpus(tmp_path)
    try:
        compress_standard([src], tmp_path / "p.7z", "7z",
                          StageContext(temp_dir=tmp_path / "t", threads=2),
                          password="pw")
    except ValueError as exc:
        assert "excmp" in str(exc).lower()
    else:
        pytest.fail("the combination was accepted")
