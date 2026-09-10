"""D5: `excmp verify --deep` — the source-side half, and one number for a tree.

`verify_archive` already did the expensive half, and it is worth being precise
about which half. Modelled on zpaqfranz's two separate verbs
(research/20 §6):

- **`t`** decompresses everything and re-hashes it, needing no source. That is
  exactly what `verify_archive` has always done, and it answers *"can this
  archive still produce the bytes it claims?"*
- **`v -ssd`** re-reads the *source* from disk and compares it against the
  stored hashes. Nothing here did that, and it answers a different question:
  *"are the originals still what they were when I archived them?"* An archive
  is the only reference copy of that answer, which makes it the one tool that
  can detect bit-rot in the source.

Running only the first and calling it "deep" would be the same category error
as `7z t` — a check that passes while the thing you cared about is broken.

The third piece is the **order-independent tree hash**: one value for a whole
tree, so "these two trees are equal" is a single comparison a user can write
down and check a year later. `zpaqfranz sum` is the model.

**Why it is sort-then-hash and not XOR.** Combining digests with XOR or
addition is order-free without sorting, and it is worthless here: XOR is
self-cancelling, so a tree containing the same file twice hashes *identically*
to a tree containing neither copy. This project deduplicates identical files
on purpose, so that is not a theoretical attack, it is Tuesday. Sorting the
`digest  path` lines and hashing the result is order-independent by
canonicalisation instead, and binds each digest to its path.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools
from excmp.verify import VerifyError, hash_file, tree_hash

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None,
                              reason="7z not installed")


# --------------------------------------------------------------------------
# the tree hash, as a function
# --------------------------------------------------------------------------

def test_the_tree_hash_ignores_the_order_it_was_given():
    entries = {f"dir/f{i}.txt": f"{i:064x}" for i in range(25)}
    shuffled = list(entries.items())
    random.Random(4).shuffle(shuffled)

    assert tree_hash(entries) == tree_hash(dict(shuffled))


def test_the_tree_hash_binds_each_digest_to_its_path():
    """Two files swapping names is a different tree, and a hash that says
    otherwise would call a scrambled restore correct."""
    a = {"one.txt": "aa" * 32, "two.txt": "bb" * 32}
    b = {"one.txt": "bb" * 32, "two.txt": "aa" * 32}

    assert tree_hash(a) != tree_hash(b)


def test_the_tree_hash_is_not_self_cancelling():
    """The XOR trap, pinned. With XOR-combining, a tree holding the same
    content at two paths collapses to the same value as a tree holding
    neither - and this program deduplicates identical files as a feature, so
    duplicate content is the normal case, not an edge one."""
    digest = "cc" * 32
    twice = {"a.bin": digest, "b.bin": digest}
    neither = {}
    one = {"a.bin": digest}

    assert tree_hash(twice) != tree_hash(neither)
    assert tree_hash(twice) != tree_hash(one)


def test_the_empty_tree_has_a_value_and_it_is_not_a_files_value():
    empty_file_sha = ("e3b0c44298fc1c149afbf4c8996fb924"
                      "27ae41e4649b934ca495991b7852b855")
    assert tree_hash({}) != tree_hash({"empty.txt": empty_file_sha})
    assert len(tree_hash({})) == 64


def test_the_tree_hash_is_stable_across_calls_and_processes():
    """It is a value users are invited to write down, so it must not depend on
    anything but the input - no salt, no iteration order, no locale."""
    entries = {"a/b.txt": "11" * 32, "a/c.txt": "22" * 32}
    assert tree_hash(entries) == tree_hash(entries)
    assert tree_hash(entries) == (
        tree_hash({"a/c.txt": "22" * 32, "a/b.txt": "11" * 32}))


def test_the_tree_hash_normalises_separators_not_case():
    """Archive-relative keys are always posix in the ledger, but a caller may
    hand over a Windows path. Case is NOT folded: two names differing only in
    case are two files on the volumes this program is tested against, and
    silently merging them would hide a real difference."""
    assert tree_hash({"a/b.txt": "33" * 32}) == tree_hash({"a\\b.txt": "33" * 32})
    assert tree_hash({"a/b.txt": "33" * 32}) != tree_hash({"A/B.TXT": "33" * 32})


# --------------------------------------------------------------------------
# the archive-side half, end to end
# --------------------------------------------------------------------------

def _tree(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "doc.txt").write_text("deep verify reads both sides. " * 3_000)
    (root / "blob.bin").write_bytes(bytes(random.Random(11).getrandbits(8)
                                          for _ in range(30_000)))
    (root / "nested").mkdir()
    (root / "nested" / "same.txt").write_text("shared body " * 500)
    return root


@needs_7z
def test_a_deep_verify_reports_the_tree_hash_of_the_ledger(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    result = engine.verify_archive(arc, ctx, deep=True)

    assert result.ok
    assert len(result.tree_sha256) == 64
    # Independently reproducible from the archive's own ledger.
    listing = engine.list_archive(arc)
    assert not listing.truncated
    assert result.tree_sha256 == tree_hash(
        {e.name: e.sha256 for e in listing.entries})


@needs_7z
def test_the_tree_hash_is_the_same_on_a_second_verify(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    first = engine.verify_archive(arc, ctx, deep=True)
    second = engine.verify_archive(arc, ctx, deep=True)
    assert first.tree_sha256 == second.tree_sha256


@needs_7z
def test_a_shallow_verify_does_not_pretend_to_have_a_tree_hash(tmp_path):
    """An empty string, not a plausible-looking one. A caller comparing a
    field that was never computed is the failure this avoids."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    assert engine.verify_archive(arc, ctx).tree_sha256 == ""


# --------------------------------------------------------------------------
# the source-side half: the question nothing could answer before
# --------------------------------------------------------------------------

@needs_7z
def test_the_source_side_pass_finds_a_source_file_that_rotted(tmp_path):
    """The archive is the reference copy. One byte changes in the original
    after archiving, and this is the only check in the program that notices."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    victim = src / "nested" / "same.txt"
    raw = bytearray(victim.read_bytes())
    raw[7] ^= 0xFF
    victim.write_bytes(bytes(raw))

    result = engine.verify_archive(arc, ctx, deep=True, source=src.parent)

    assert result.ok, "the archive itself is fine - only the source changed"
    assert result.source_checked > 0
    assert any("same.txt" in line for line in result.source_changed), \
        result.source_changed


@needs_7z
def test_the_source_side_pass_reports_a_missing_original(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    (src / "doc.txt").unlink()
    result = engine.verify_archive(arc, ctx, deep=True, source=src.parent)

    assert any("doc.txt" in line for line in result.source_missing), \
        result.source_missing
    assert result.source_changed == []


@needs_7z
def test_a_new_file_beside_the_source_is_reported_and_is_not_a_failure(tmp_path):
    """A file the archive has never seen is news, not corruption - it usually
    means the source has moved on. Reported separately so the two cannot be
    confused, and it does not make the verdict false."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    (src / "added-later.txt").write_text("written after the archive")
    result = engine.verify_archive(arc, ctx, deep=True, source=src.parent)

    assert result.ok
    assert result.source_changed == [] and result.source_missing == []
    assert any("added-later.txt" in line for line in result.source_extra), \
        result.source_extra


@needs_7z
def test_an_untouched_source_passes_both_halves_cleanly(tmp_path):
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    result = engine.verify_archive(arc, ctx, deep=True, source=src.parent)

    assert result.ok
    assert result.source_checked == result.verified
    assert result.source_changed == []
    assert result.source_missing == []
    assert result.source_extra == []


@needs_7z
def test_the_source_pass_never_writes_to_the_source(tmp_path):
    """It re-reads originals. Reading must not touch them - not the bytes and
    not the mtimes, which are the thing a backup tool must never disturb."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    before = {p: (p.stat().st_size, p.stat().st_mtime_ns)
              for p in sorted(src.rglob("*")) if p.is_file()}
    engine.verify_archive(arc, ctx, deep=True, source=src.parent)
    after = {p: (p.stat().st_size, p.stat().st_mtime_ns)
             for p in sorted(src.rglob("*")) if p.is_file()}

    assert before == after


@needs_7z
def test_a_broken_archive_still_fails_loudly_in_deep_mode(tmp_path):
    """Deep mode adds checks; it must not soften the one that already
    existed."""
    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    data = bytearray(arc.read_bytes())
    for off in range(len(data) // 2, len(data) // 2 + 64):
        data[off] ^= 0xFF
    arc.write_bytes(bytes(data))

    with pytest.raises((VerifyError, Exception)):
        engine.verify_archive(arc, ctx, deep=True, source=src.parent)


# --------------------------------------------------------------------------
# the CLI surface
# --------------------------------------------------------------------------

@needs_7z
def test_the_cli_prints_the_tree_hash_as_json(tmp_path, capsys):
    from excmp import cli

    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    code = cli.main(["verify", str(arc), "--deep", "--json",
                     "--temp", str(tmp_path / "tmp")])
    out = capsys.readouterr().out

    import json
    payload = json.loads(out)
    assert code == 0
    assert len(payload["tree_sha256"]) == 64
    assert payload["ok"] is True


@needs_7z
def test_the_cli_exits_nonzero_when_the_source_disagrees(tmp_path, capsys):
    """A changed original is a finding the shell has to be able to act on."""
    from excmp import cli

    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    victim = src / "doc.txt"
    victim.write_text("rewritten after archiving")

    code = cli.main(["verify", str(arc), "--deep", "--source", str(src.parent),
                     "--temp", str(tmp_path / "tmp")])
    out = capsys.readouterr().out
    assert code != 0, out
    assert "doc.txt" in out


@needs_7z
def test_source_is_only_meaningful_with_deep(tmp_path):
    """--source without --deep is a request the shallow path cannot honour.
    Refused with a message, rather than silently ignored."""
    from excmp import cli

    src = _tree(tmp_path / "src")
    arc = tmp_path / "a.excmp"
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    engine.compress([src], arc, Profile.NORMAL, ctx)

    with pytest.raises(SystemExit) as exc:
        cli.main(["verify", str(arc), "--source", str(src.parent),
                  "--temp", str(tmp_path / "tmp")])
    assert exc.value.code != 0
