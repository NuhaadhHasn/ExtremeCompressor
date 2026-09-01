"""G2: pulling one file out of an archive without unpacking the rest.

The interesting part is not the extraction, it is what the archive's shape
costs. `.excmp` has two populations with wildly different prices:

* a **stored** file is a plain zip member — reading one is instant, and it is
  still checked against its SHA-256, so a selective restore of stored files
  carries the same guarantee a full one does;
* a **pipelined** file lives inside one solid stream. There is no such thing
  as reading one of those cheaply: getting a single byte out replays the
  whole chain. That is a fact about solid compression, not a shortcoming, and
  the honest move is to say the price *before* it is paid — which is what
  `selection_cost()` exists for.

The security-relevant half is the foreign path. `7z x -i!name` matches
**glob patterns**, and 7-Zip has no literal mode, so a requested name
containing `*` or `?` would quietly extract more than was asked for. Every
requested name goes through `safepath.safe_relpath` first, which already
refuses both characters — so by construction no name we accept can be a
wildcard.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.safepath import UnsafePathError
from excmp.stages.base import StageContext
from excmp.tools import find_tools

_SEVENZIP = find_tools().get("7z")
needs_7z = pytest.mark.skipif(_SEVENZIP is None, reason="7z.exe not installed")

PASSWORD = "correct horse battery staple"


def ctx(tmp_path):
    return StageContext(temp_dir=tmp_path / "t")


@pytest.fixture
def ours(tmp_path):
    """An .excmp with both populations: `readme.txt` compresses (pipeline),
    `noise.bin` does not (store)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "readme.txt").write_text("shrink me. " * 3000, encoding="utf-8")
    (src / "notes.txt").write_text("also shrink me. " * 2000, encoding="utf-8")
    (src / "noise.bin").write_bytes(bytes((i * 97 + 3) % 256 for i in range(50_000)))
    out = tmp_path / "ours.excmp"
    engine.compress([src], out, Profile.FAST, ctx(tmp_path))
    return out


@pytest.fixture
def theirs(tmp_path):
    path = tmp_path / "theirs.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 500)
        zf.writestr("docs/data.csv", "a,b,c\n" * 400)
        zf.writestr("bin/tool.exe", b"MZ" + b"\0" * 900)
    return path


def routes(archive) -> dict[str, str]:
    return {e.name: e.route for e in engine.list_archive(archive).entries}


def landed(out_dir: Path) -> set[str]:
    return {p.relative_to(out_dir).as_posix()
            for p in Path(out_dir).rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Our own archives
# ---------------------------------------------------------------------------

def test_one_stored_file_comes_out_alone_and_still_verified(ours, tmp_path):
    """A stored entry is a plain zip member, so this costs a directory read —
    and it is *still* hash-checked. Speed here does not buy itself with a
    weaker guarantee."""
    stored = [n for n, r in routes(ours).items() if r == "store"]
    assert stored, "the corpus produced no stored entry"

    dest = tmp_path / "one"
    result = engine.extract_selected(ours, stored[:1], dest, ctx(tmp_path))

    assert landed(dest) == {stored[0]}
    assert result.files_restored == 1
    assert result.verified == 1
    assert result.ledger_backed is True


def test_one_pipelined_file_comes_out_and_is_verified(ours, tmp_path):
    piped = [n for n, r in routes(ours).items() if r == "pipeline"]
    assert piped

    dest = tmp_path / "one"
    result = engine.extract_selected(ours, piped[:1], dest, ctx(tmp_path))

    assert landed(dest) == {piped[0]}
    assert result.verified == 1


def test_a_mixed_selection_gets_both_populations(ours, tmp_path):
    by_route = routes(ours)
    piped = next(n for n, r in by_route.items() if r == "pipeline")
    stored = next(n for n, r in by_route.items() if r == "store")

    dest = tmp_path / "mixed"
    result = engine.extract_selected(ours, [piped, stored], dest, ctx(tmp_path))
    assert landed(dest) == {piped, stored}
    assert result.verified == 2


def test_the_files_that_were_not_asked_for_stay_in_the_archive(ours, tmp_path):
    piped = [n for n, r in routes(ours).items() if r == "pipeline"]
    dest = tmp_path / "one"
    engine.extract_selected(ours, piped[:1], dest, ctx(tmp_path))
    assert landed(dest) == {piped[0]}, "the whole archive was unpacked"


def test_the_replay_leaves_no_temp_behind(ours, tmp_path):
    """A pipelined selection restores the entire archive in temp to get at one
    file. That is unavoidable; leaving it on the disk afterwards is not."""
    temp = tmp_path / "t"
    piped = [n for n, r in routes(ours).items() if r == "pipeline"]
    engine.extract_selected(ours, piped[:1], tmp_path / "one",
                            StageContext(temp_dir=temp))
    assert list(temp.iterdir()) == [], f"left behind: {list(temp.iterdir())}"


# ---------------------------------------------------------------------------
# The price, quoted before it is paid
# ---------------------------------------------------------------------------

def test_a_stored_selection_is_not_solid(ours, tmp_path):
    stored = [n for n, r in routes(ours).items() if r == "store"]
    cost = engine.selection_cost(ours, stored[:1])
    assert cost.solid is False
    assert cost.bytes_to_replay == 0


def test_a_pipelined_selection_prices_the_whole_stream(ours, tmp_path):
    """Not the size of the file asked for — the size of everything that has
    to be decompressed to reach it. Quoting the former would understate the
    wait by orders of magnitude on a real archive."""
    by_route = routes(ours)
    piped = [n for n, r in by_route.items() if r == "pipeline"]
    listing = engine.list_archive(ours)
    all_piped_bytes = sum(e.size for e in listing.entries if e.route == "pipeline")

    cost = engine.selection_cost(ours, piped[:1])
    assert cost.solid is True
    assert cost.bytes_to_replay == all_piped_bytes


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_an_empty_selection_is_refused_rather_than_treated_as_everything(
        ours, tmp_path):
    """"Extract the files I selected" with nothing selected must not quietly
    become "extract all of them"."""
    with pytest.raises(ValueError):
        engine.extract_selected(ours, [], tmp_path / "out", ctx(tmp_path))


def test_a_name_that_is_not_in_the_archive_is_named_in_the_error(ours, tmp_path):
    with pytest.raises(KeyError, match="ghost.txt"):
        engine.extract_selected(ours, ["ghost.txt"], tmp_path / "out", ctx(tmp_path))


@pytest.mark.parametrize("hostile", ["../evil.txt", "C:/windows/system32/x.dll",
                                     "sub/../../out.txt"])
def test_a_hostile_selection_never_reaches_a_subprocess(theirs, tmp_path, hostile):
    with pytest.raises(UnsafePathError):
        engine.extract_selected(theirs, [hostile], tmp_path / "out", ctx(tmp_path))


@pytest.mark.parametrize("globby", ["docs/*.txt", "docs/data.cs?"])
def test_a_wildcard_selection_cannot_over_extract(theirs, tmp_path, globby):
    """`-i!` takes glob patterns and 7-Zip has no literal mode, so a name
    carrying `*` or `?` would match more than was asked for. safe_relpath
    already refuses both characters in a filename, so validating the request
    before building the filter closes this by construction rather than by
    escaping."""
    with pytest.raises(UnsafePathError):
        engine.extract_selected(theirs, [globby], tmp_path / "out", ctx(tmp_path))


# ---------------------------------------------------------------------------
# Foreign archives
# ---------------------------------------------------------------------------

@needs_7z
def test_exactly_the_requested_members_land(theirs, tmp_path):
    dest = tmp_path / "sel"
    result = engine.extract_selected(theirs, ["docs/guide.txt"], dest, ctx(tmp_path))
    assert landed(dest) == {"docs/guide.txt"}
    assert result.files_restored == 1


@needs_7z
def test_a_foreign_selection_claims_no_verification(theirs, tmp_path):
    result = engine.extract_selected(theirs, ["docs/guide.txt"],
                                     tmp_path / "sel", ctx(tmp_path))
    assert result.ledger_backed is False
    assert result.verified == 0


@needs_7z
def test_two_of_three_members(theirs, tmp_path):
    dest = tmp_path / "sel"
    engine.extract_selected(theirs, ["docs/guide.txt", "bin/tool.exe"],
                            dest, ctx(tmp_path))
    assert landed(dest) == {"docs/guide.txt", "bin/tool.exe"}


@needs_7z
def test_the_staging_directory_does_not_survive(theirs, tmp_path):
    temp = tmp_path / "t"
    engine.extract_selected(theirs, ["docs/guide.txt"], tmp_path / "sel",
                            StageContext(temp_dir=temp))
    assert list(temp.iterdir()) == []


# ---------------------------------------------------------------------------
# Passwords on the extract path
# ---------------------------------------------------------------------------

@needs_7z
def test_an_encrypted_archive_extracts_with_its_password(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "secret.txt").write_text("classified\n" * 100, encoding="utf-8")
    locked = tmp_path / "locked.7z"
    subprocess.run([_SEVENZIP.path, "a", "-t7z", "-mhe=on", f"-p{PASSWORD}",
                    str(locked), str(src / "*")], check=True,
                   stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    dest = tmp_path / "open"
    result = engine.extract_any(locked, dest, ctx(tmp_path), password=PASSWORD)
    assert (dest / "secret.txt").read_text(encoding="utf-8").startswith("classified")
    assert result.ledger_backed is False


@needs_7z
def test_extracting_an_encrypted_archive_without_the_password_fails_fast(tmp_path):
    """It must not hang. Before G2 this call had no `-p` at all and 7-Zip sat
    waiting for a password on a console that does not exist under the GUI."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "secret.txt").write_text("classified", encoding="utf-8")
    locked = tmp_path / "locked.7z"
    subprocess.run([_SEVENZIP.path, "a", "-t7z", "-mhe=on", f"-p{PASSWORD}",
                    str(locked), str(src / "*")], check=True,
                   stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    with pytest.raises(Exception) as caught:
        engine.extract_any(locked, tmp_path / "nope", ctx(tmp_path))
    assert PASSWORD not in str(caught.value)
