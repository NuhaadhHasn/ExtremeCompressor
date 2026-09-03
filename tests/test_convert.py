"""G5 — take somebody else's archive and make it smaller, honestly.

Point it at a `.zip`, `.rar`, `.7z` or `.iso`, and it extracts to temp,
analyses what was actually inside, runs our pipeline, and **says whether that
was worth doing**. Other tools have a "recompress" button. The part nobody
else has is the last clause: our analyser already knows why each file did or
did not shrink, so a conversion that gained nothing can say so in words
instead of leaving the user to compare two numbers.

The honesty rules, which are what the tests below are mostly about:

- **The source archive is never touched.** Not moved, not deleted, not even on
  success. Deleting the only copy of somebody's data because we think ours is
  better is not a decision this program gets to make.
- **A conversion that does not help must say it did not help.** Silence, or a
  cheerful "done!", is how a tool trains people to stop reading it.
- **Nothing is published that does not verify.** Same rule as every other
  path: the new archive is restored and hashed against what came out of the
  old one before it replaces anything.
"""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from excmp.convert import ConvertResult, convert_archive
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7-Zip not installed")


def _source_zip(tmp_path: Path, *, compressible: bool = True) -> tuple[Path, dict]:
    """A plain .zip standing in for whatever the user actually has."""
    src = tmp_path / "payload"
    (src / "sub").mkdir(parents=True)
    if compressible:
        # Big and *varied*, not tiny and repetitive. Deflate already handles
        # "the same sentence 4000 times" almost perfectly, so a small corpus
        # leaves LZMA2 nothing to win and our manifest overhead then makes the
        # converted archive larger - which the tool correctly reports as "keep
        # the original", and which is a fact about 940-byte archives rather
        # than about the feature. A few MB of varied English is where LZMA2's
        # bigger window actually beats deflate.
        words = [f"word{n % 977} " for n in range(200_000)]
        (src / "a.txt").write_text("".join(words), encoding="utf-8")
        (src / "sub" / "b.txt").write_text(
            "".join(reversed(words)) + "".join(words[::3]), encoding="utf-8")
    else:
        import os
        (src / "a.bin").write_bytes(os.urandom(300_000))
        (src / "sub" / "b.bin").write_bytes(os.urandom(300_000))

    digests = {p.relative_to(src).as_posix():
               hashlib.sha256(p.read_bytes()).hexdigest()
               for p in src.rglob("*") if p.is_file()}

    archive = tmp_path / "theirs.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src).as_posix())
    return archive, digests


# ---------------------------------------------------------------------------
# It converts
# ---------------------------------------------------------------------------

@needs_7z
def test_a_zip_becomes_an_excmp_with_the_same_contents(tmp_path):
    source, digests = _source_zip(tmp_path)
    out = tmp_path / "ours.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t", threads=2)

    result = convert_archive(source, out, Profile.NORMAL, ctx)
    assert result.archive.exists()

    from excmp.engine import extract
    restored = tmp_path / "restored"
    extract(out, restored, StageContext(temp_dir=tmp_path / "x", threads=2))
    got = {p.relative_to(restored).as_posix():
           hashlib.sha256(p.read_bytes()).hexdigest()
           for p in restored.rglob("*") if p.is_file()}
    for rel, digest in digests.items():
        match = [v for k, v in got.items() if k.endswith(rel)]
        assert match, f"{rel} did not survive the conversion"
        assert match[0] == digest, f"{rel} came back different"


@needs_7z
def test_the_source_archive_is_never_touched(tmp_path):
    """Not moved, not deleted, not even on success. Deleting the only copy of
    somebody's data because ours is smaller is not our call to make."""
    source, _ = _source_zip(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    mtime = source.stat().st_mtime_ns

    convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t", threads=2))

    assert source.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert source.stat().st_mtime_ns == mtime


@needs_7z
def test_temp_is_cleaned_up_afterwards(tmp_path):
    """A conversion stages the entire archive on disk. Leaving that behind
    would quietly cost the user the size of their own archive, twice."""
    source, _ = _source_zip(tmp_path)
    temp = tmp_path / "t"
    convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                    StageContext(temp_dir=temp, threads=2))
    leftovers = [p for p in temp.rglob("*") if p.is_file()] if temp.exists() else []
    assert not leftovers, f"temp still holds {[p.name for p in leftovers][:5]}"


# ---------------------------------------------------------------------------
# It reports honestly
# ---------------------------------------------------------------------------

@needs_7z
def test_the_result_carries_both_sizes_and_the_verdict(tmp_path):
    source, _ = _source_zip(tmp_path)
    result = convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "t", threads=2))
    assert isinstance(result, ConvertResult)
    assert result.source_bytes > 0
    assert result.archive_bytes > 0
    assert result.verdict, "no verdict was produced"
    assert result.files > 0


@needs_7z
def test_a_conversion_that_helps_says_by_how_much(tmp_path):
    source, _ = _source_zip(tmp_path, compressible=True)
    result = convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.improved is True, (
        f"{result.source_bytes} -> {result.archive_bytes}")
    assert "%" in result.verdict


@needs_7z
def test_a_conversion_that_does_not_help_admits_it(tmp_path):
    """Random data cannot be compressed by anyone. A tool that says "done!"
    here is training its user to stop reading it."""
    source, _ = _source_zip(tmp_path, compressible=False)
    result = convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.improved is False
    lowered = result.verdict.lower()
    assert any(w in lowered for w in
               ("no smaller", "not smaller", "bigger", "no better", "already",
                "keep")), result.verdict


@needs_7z
def test_it_explains_why_when_nothing_shrank(tmp_path):
    """The part no other converter has: the analyser already knows *why* each
    file was stored, so the verdict can be a sentence rather than two numbers
    the user has to compare themselves."""
    source, _ = _source_zip(tmp_path, compressible=False)
    result = convert_archive(source, tmp_path / "ours.excmp", Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "t", threads=2))
    assert result.reasons, "no per-file explanation was produced"
    assert any("entropy" in r.lower() or "compressed" in r.lower()
               for r in result.reasons)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_converting_something_that_is_not_an_archive_fails_clearly(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_bytes(b"just some text, definitely not an archive")
    with pytest.raises(Exception) as exc:
        convert_archive(junk, tmp_path / "out.excmp", Profile.FAST,
                        StageContext(temp_dir=tmp_path / "t", threads=2))
    assert "archive" in str(exc.value).lower()


def test_converting_a_missing_file_fails_clearly(tmp_path):
    with pytest.raises(Exception):
        convert_archive(tmp_path / "gone.zip", tmp_path / "out.excmp",
                        Profile.FAST,
                        StageContext(temp_dir=tmp_path / "t", threads=2))


@needs_7z
def test_an_empty_archive_is_refused_rather_than_producing_an_empty_one(tmp_path):
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    with pytest.raises(Exception):
        convert_archive(empty, tmp_path / "out.excmp", Profile.FAST,
                        StageContext(temp_dir=tmp_path / "t", threads=2))
