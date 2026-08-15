"""Opening other people's archives, and looking inside our own (wave 3b).

Two capabilities the engine already had and the UI hid:

**G1 — foreign archives.** `SevenZipStage.extract` shells `7z x`, which opens
zip/7z/rar/tar/gz/iso/cab/msi/wim without knowing or caring that we made none
of them. The Extract tab accepted `*.excmp` only. Widening it is a filter
change; the *honest* part is the label, and that is what these tests pin:
a foreign archive has **no SHA-256 ledger**, so "restored" is all we can
truthfully say. Reporting `verified=0` as though it were a verification
result, or silently reusing the .excmp wording, would turn the one guarantee
this project sells into marketing.

**I2-lite — listing.** `_read_manifest` is a zip + JSON read, so the whole
ledger (relpath, size, SHA-256, route, and *why* a file was stored) is
available without extracting a byte. No other archiver can show why a file
did not shrink, because no other archiver records the reason.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.cli import main as cli_main
from excmp.manifest import ContainerError
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

_SEVENZIP = find_tools().get("7z") is not None
needs_7z = pytest.mark.skipif(not _SEVENZIP, reason="7z.exe not installed")


@pytest.fixture
def ours(tmp_path):
    """A real .excmp with one pipelined and one stored file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "readme.txt").write_text("shrink me. " * 3000, encoding="utf-8")
    (src / "noise.bin").write_bytes(bytes((i * 97 + 3) % 256 for i in range(50_000)))
    out = tmp_path / "ours.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


@pytest.fixture
def theirs(tmp_path):
    """A plain zip nobody in this project created."""
    path = tmp_path / "somebody-elses.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 500)
        zf.writestr("docs/data.csv", "a,b,c\n" * 400)
    return path


# ---------------------------------------------------------------------------
# Telling ours from theirs
# ---------------------------------------------------------------------------

def test_an_excmp_is_recognised_by_its_manifest_not_its_extension(ours, tmp_path):
    assert engine.is_excmp(ours) is True

    # A .excmp name on a plain zip is not an .excmp. The manifest is the
    # authority - anything else lets a rename decide which guarantees apply.
    liar = tmp_path / "pretender.excmp"
    with zipfile.ZipFile(liar, "w") as zf:
        zf.writestr("hello.txt", "not really")
    assert engine.is_excmp(liar) is False


def test_a_non_archive_is_not_an_excmp(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("just text", encoding="utf-8")
    assert engine.is_excmp(plain) is False


# ---------------------------------------------------------------------------
# G1: extracting foreign archives
# ---------------------------------------------------------------------------

@needs_7z
def test_a_foreign_zip_extracts(theirs, tmp_path):
    dest = tmp_path / "out"
    result = engine.extract_any(theirs, dest, StageContext(temp_dir=tmp_path / "t"))
    assert result.files_restored == 2
    assert (dest / "docs" / "guide.txt").is_file()


@needs_7z
def test_a_foreign_extract_never_claims_a_verification(theirs, tmp_path):
    """The whole point. There is no ledger, so there is nothing to verify, and
    the result has to say so in a way the UI cannot accidentally render as
    "0 hashes verified OK"."""
    result = engine.extract_any(theirs, tmp_path / "out",
                                StageContext(temp_dir=tmp_path / "t"))
    assert result.ledger_backed is False
    assert result.verified == 0


def test_our_own_archive_still_takes_the_verified_path(ours, tmp_path):
    result = engine.extract_any(ours, tmp_path / "out",
                                StageContext(temp_dir=tmp_path / "t"))
    assert result.ledger_backed is True
    assert result.verified == 2 == result.files_restored


def test_extract_itself_stays_excmp_only(theirs, tmp_path):
    """`extract()` is the ledger-verified path and must not quietly grow a
    fallback - callers that want either open `extract_any` deliberately."""
    with pytest.raises(ContainerError):
        engine.extract(theirs, tmp_path / "out", StageContext(temp_dir=tmp_path / "t"))


# ---------------------------------------------------------------------------
# I2-lite: listing
# ---------------------------------------------------------------------------

def test_listing_reads_the_ledger_without_extracting_anything(ours, tmp_path):
    temp = tmp_path / "listing-temp"
    listing = engine.list_archive(ours)

    assert listing.kind == "excmp"
    assert listing.profile == "fast"
    assert {e.name for e in listing.entries} == {"src/readme.txt", "src/noise.bin"}
    assert listing.total_bytes == sum(e.size for e in listing.entries)
    assert not temp.exists(), "listing extracted something"


def test_every_entry_carries_the_evidence(ours):
    listing = engine.list_archive(ours)
    for entry in listing.entries:
        assert len(entry.sha256) == 64
        assert entry.size > 0
        assert entry.route in {"pipeline", "store"}


def test_a_stored_file_says_why_it_was_stored(ours):
    """The reason is the thing no other archiver can show, because no other
    archiver writes it down."""
    listing = engine.list_archive(ours)
    stored = [e for e in listing.entries if e.route == "store"]
    assert stored, "the corpus produced no stored entry"
    assert stored[0].reason, "a stored file with no explanation"


def test_listing_a_foreign_archive_is_refused_rather_than_faked(theirs):
    """Foreign listing needs the pinned `7z l -slt` grammar (G2). Until then
    the honest answer is "cannot", not an empty list that reads as "empty"."""
    with pytest.raises(ContainerError):
        engine.list_archive(theirs)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_the_list_verb_prints_route_and_reason(ours, capsys):
    assert cli_main(["list", str(ours)]) == 0
    out = capsys.readouterr().out
    assert "readme.txt" in out and "noise.bin" in out
    assert "store" in out


def test_the_list_verb_speaks_json(ours, capsys):
    assert cli_main(["list", str(ours), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "excmp"
    assert len(payload["entries"]) == 2
    assert all(len(e["sha256"]) == 64 for e in payload["entries"])


@needs_7z
def test_the_extract_verb_opens_foreign_archives_and_says_what_it_did(
        theirs, tmp_path, capsys):
    assert cli_main(["extract", str(theirs), "-o", str(tmp_path / "out"),
                     "--temp", str(tmp_path / "t")]) == 0
    out = capsys.readouterr().out.lower()
    assert "2" in out
    # No ledger, so it must not borrow the verified-restore wording.
    assert "verified" not in out
    assert "no sha-256 ledger" in out


def test_each_stored_file_gets_its_own_reason_not_the_groups(tmp_path):
    """The route-level reason is a joined summary of every distinct reason in
    the group. Attributing it to one file says "7.99 bits/byte; 7.98 bits/byte"
    about a file that measured exactly one of them - which is the sort of
    almost-true that this column exists to avoid."""
    src = tmp_path / "src"
    src.mkdir()
    # Two high-entropy files with *different* entropies, so the group reason
    # genuinely differs from either file's own.
    (src / "one.bin").write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))
    (src / "two.bin").write_bytes(bytes((i * 31 + 200) % 251 for i in range(70_000)))
    out = tmp_path / "two-reasons.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))

    listing = engine.list_archive(out)
    stored = [e for e in listing.entries if e.route == "store"]
    assert len(stored) == 2
    for entry in stored:
        assert entry.reason.count("bits/byte") == 1, entry.reason


def test_an_archive_written_before_store_reasons_still_lists(tmp_path):
    """`store_reasons` is defaulted, so older containers load and fall back to
    the route summary rather than raising or showing nothing."""
    from excmp.manifest import Manifest

    payload = json.loads(Manifest.new(
        profile="fast", stages=[], inputs={"a.bin": {"size": 1, "sha256": "x" * 64}},
        payload_name="", routes=[{"action": "store", "reason": "because",
                                  "files": ["a.bin"], "stages": []}]).to_json())
    payload.pop("store_reasons")                    # an archive from before the field
    restored = Manifest.from_json(json.dumps(payload))
    assert restored.store_reasons == {}
    assert restored.inputs["a.bin"]["size"] == 1
