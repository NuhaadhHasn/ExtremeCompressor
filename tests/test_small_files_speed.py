"""Many small files: fewer opens per file, and nothing given up for them.

Measured 2026-11-25 on the i5-7200U with real-time scanning on: a Fast job
over 1,801 Python source files (43 MB) took 44 s although zstd needs about
2 s of it. A profile put the time in the *opens* - 10,810 of them, six a
file, about 1.7 ms each - and in re-doing per-file work: every file hashed in
one read and copied in another, analysed through two handles, and its
destination canonicalized twice for every path check.

What these tests pin is the other half of that work: each saving, and the
integrity property it must not have cost.

* The ledger's SHA-256 is of **the bytes that went into the archive**. It is
  now taken from the buffers written to the tar or to the staging copy, so
  there is no second read that could see a different file.
* A source whose **size** changed after analysis still fails the publish gate.
* A file that cannot be read is still skipped and named (K3), including when
  it breaks half-way through being archived.
* Every archive-supplied path still passes every `safepath` check; only the
  canonical form of the *destination* is computed once per pass.
* The publish gate still restores every byte and compares every hash.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import os
import random
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from excmp import analyzer, engine
from excmp.analyzer import (Category, _detect_category, analyze_file,
                            sample_stats)
from excmp.planner import Profile
from excmp.safepath import UnsafePathError, Within, resolve_within
from excmp.stages import tarstage
from excmp.stages.base import StageContext, StageError
from excmp.stages.tarstage import TarStage, add_hashed
from excmp.stages.zstdstage import ZstdStage
from excmp.tools import find_tools
from excmp.verify import VerifyError, hash_file, verify_restore

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7-Zip not installed")
windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="Windows junctions and share modes")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(seed: int, size: int = 6_000) -> bytes:
    rnd = random.Random(seed)
    words = [b"alpha", b"beta", b"gamma", b"delta", b"import", b"return"]
    out = bytearray()
    while len(out) < size:
        out += rnd.choice(words) + b" "
    return bytes(out[:size])


def _tree(root: Path, files: int = 12) -> dict[str, bytes]:
    """Compressible text, so every file takes the pipeline route."""
    root.mkdir(parents=True)
    made: dict[str, bytes] = {}
    for i in range(files):
        rel = f"pkg{i % 3}/Mod_{i}.py" if i % 2 else f"pkg{i % 3}/sub/mod_{i}.py"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _text(i)
        path.write_bytes(data)
        made[f"{root.name}/{rel}"] = data
    return made


class _OpenCounter:
    """Counts opens of files under one directory, however they are made."""

    def __init__(self, monkeypatch, under: Path):
        self.under = os.path.normcase(str(under.resolve())) + os.sep
        self.counts: dict[str, int] = {}
        real = io.open

        def counting(file, *a, **k):
            try:
                name = os.path.normcase(os.fspath(file))
            except TypeError:
                name = ""
            if isinstance(name, str) and name.startswith(self.under):
                self.counts[name] = self.counts.get(name, 0) + 1
            return real(file, *a, **k)

        monkeypatch.setattr(io, "open", counting)
        monkeypatch.setattr(builtins, "open", counting)
        monkeypatch.setattr(tarfile, "bltn_open", counting)


# --------------------------------------------------------------------------
# safepath: one canonical destination per pass, every guard kept
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["a.txt", "a/b/c.txt", "deep/er/still/x.bin"])
def test_within_returns_what_resolve_within_returns(tmp_path, name):
    assert Within(tmp_path)(name) == resolve_within(tmp_path, name)


@pytest.mark.parametrize("name", [
    "../x", "a/../../x", "C:/x", "/x", "\\\\server\\share\\x", "a/./b", "",
    "NUL", "a/COM1.txt", "a:b", "a\x00b", "trailing.", "a/\u202egpj.exe", ".",
])
def test_within_refuses_everything_resolve_within_refuses(tmp_path, name):
    with pytest.raises(UnsafePathError):
        resolve_within(tmp_path, name)
    within = Within(tmp_path)
    within("fine.txt")                  # the cached destination is in play
    with pytest.raises(UnsafePathError):
        within(name)


def test_within_canonicalizes_the_destination_once(tmp_path, monkeypatch):
    """The saving: 100 names, one `resolve()` of the destination - and still
    one of every target, which is the check that catches an escape."""
    seen: list[Path] = []
    real = Path.resolve

    def spy(self, *a, **k):
        seen.append(self)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", spy)
    within = Within(tmp_path)
    for i in range(100):
        within(f"d{i % 4}/f{i}.txt")
    assert seen.count(tmp_path) == 1
    assert len(seen) == 101, "every target must still be canonicalized"


def _junction(link: Path, target: Path) -> None:
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True)
    if done.returncode != 0 or not link.exists():
        pytest.skip("could not create a junction on this machine")


@windows_only
def test_within_refuses_a_junction_that_leaves_the_destination(tmp_path):
    dest, outside = tmp_path / "dest", tmp_path / "outside"
    dest.mkdir()
    outside.mkdir()
    _junction(dest / "j", outside)
    within = Within(dest)
    within("ok.txt")
    with pytest.raises(UnsafePathError, match="escapes"):
        within("j/planted.txt")
    with pytest.raises(UnsafePathError, match="escapes"):
        resolve_within(dest, "j/planted.txt")


@windows_only
def test_a_destination_swapped_mid_pass_is_refused(tmp_path):
    """Why remembering the destination is the strict direction. Re-resolved
    per call, a destination replaced by a junction agrees with its equally
    redirected targets and the write goes wherever the junction points."""
    dest, elsewhere = tmp_path / "dest", tmp_path / "elsewhere"
    dest.mkdir()
    elsewhere.mkdir()
    within = Within(dest)
    within("first.txt")
    dest.rename(tmp_path / "dest-moved")
    _junction(dest, elsewhere)
    assert resolve_within(dest, "second.txt") == dest / "second.txt"
    with pytest.raises(UnsafePathError, match="escapes"):
        within("second.txt")


def test_verify_restore_canonicalizes_the_destination_once(tmp_path, monkeypatch):
    files = {f"t/f{i}.txt": _text(i, 300) for i in range(20)}
    ledger = {}
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        ledger[rel] = {"size": len(data), "sha256": _sha(data)}
    seen: list[Path] = []
    real = Path.resolve

    def spy(self, *a, **k):
        seen.append(self)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", spy)
    assert verify_restore(tmp_path, ledger) == 20
    assert len(seen) == 21


def test_verify_restore_still_refuses_each_kind_of_wrong(tmp_path):
    """One `stat` now answers "is it a file" and "how big"; the three
    refusals it feeds are unchanged, and so is a directory in a file's place."""
    good = _text(1, 500)
    (tmp_path / "ok.txt").write_bytes(good)
    (tmp_path / "short.txt").write_bytes(good[:-1])
    (tmp_path / "flipped.txt").write_bytes(b"X" + good[1:])
    (tmp_path / "adir.txt").mkdir()
    entry = {"size": len(good), "sha256": _sha(good)}
    assert verify_restore(tmp_path, {"ok.txt": dict(entry)}) == 1
    for name, word in [("short.txt", "size mismatch"), ("flipped.txt", "hash mismatch"),
                       ("gone.txt", "missing"), ("adir.txt", "missing")]:
        with pytest.raises(VerifyError, match=word):
            verify_restore(tmp_path, {"ok.txt": dict(entry), name: dict(entry)})


# --------------------------------------------------------------------------
# analysis: one open, the same answers
# --------------------------------------------------------------------------

def test_analyze_file_opens_the_file_once(tmp_path, monkeypatch):
    p = tmp_path / "m.py"
    p.write_bytes(_text(3, 20_000))
    opens = _OpenCounter(monkeypatch, tmp_path)
    analyze_file(p)
    assert list(opens.counts.values()) == [1]


@pytest.mark.parametrize("size", [0, 1, 4_096, 65_536, 65_537, 1_048_576,
                                  3 * 1_048_576, 3 * 1_048_576 + 1, 5_000_000])
def test_analysis_through_one_handle_matches_the_sampler(tmp_path, size):
    """`sample_stats` is still the two-step original (stat, then its own
    open); `analyze_file` now reads the head and the samples through one
    handle. Same numbers, including past the three-sample threshold."""
    rnd = random.Random(size)
    body = (_text(size, size // 2) + rnd.randbytes(size - size // 2))[:size]
    p = tmp_path / "f.bin"
    p.write_bytes(body)
    info, stats = analyze_file(p), sample_stats(p)
    assert info.size == size
    assert info.mtime_ns == p.stat().st_mtime_ns
    assert info.entropy_bps == stats.entropy_bps
    assert info.sample_ratio == stats.ratio
    assert info.sample_ratio_max == stats.ratio_max
    assert info.category == _detect_category(p, body[:analyzer._PDF_SCAN_BYTES])


def _old_text_rule(head: bytes) -> bool:
    return bool(head) and sum(32 <= b < 127 or b in (9, 10, 13)
                              for b in head) / len(head) > 0.95


@pytest.mark.parametrize("seed", range(40))
def test_the_text_heuristic_counts_what_the_loop_counted(seed):
    """The printable count moved from a Python loop into `bytes.translate`.
    Checked around the 95% line, where one byte either way changes the
    category."""
    rnd = random.Random(seed)
    n = rnd.choice([1, 19, 20, 21, 100, 1000, 65_536])
    bad = rnd.choice([0, n // 20 - 1, n // 20, n // 20 + 1, n // 2, n])
    bad = max(0, min(n, bad))
    pool_bad = bytes([*range(0, 9), 11, 12, *range(14, 32), *range(127, 256)])
    pool_good = bytes([9, 10, 13, *range(32, 127)])
    head = bytearray(rnd.choice(pool_good) for _ in range(n - bad))
    head += bytes(rnd.choice(pool_bad) for _ in range(bad))
    rnd.shuffle(head)
    got = _detect_category(Path("no-extension-here"), bytes(head))
    if any(bytes(head[o:o + len(m)]) == m for o, m, _ in analyzer._MAGIC) \
            or bytes(head[:4]) == b"RIFF":
        pytest.skip("random head hit a real magic number")
    assert (got == Category.TEXT) == _old_text_rule(bytes(head))


def test_tree_size_counts_what_the_walk_counted(tmp_path):
    root = tmp_path / "t"
    made = _tree(root, 15)
    (root / "empty" / "deeper").mkdir(parents=True)
    (root / "zero.bin").write_bytes(b"")
    want = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    assert want == sum(len(d) for d in made.values())
    assert engine._tree_size(root) == want
    one = root / "zero.bin"
    one.write_bytes(b"12345")
    assert engine._tree_size(one) == 5
    assert engine._tree_size(tmp_path / "not-there") == 0


# --------------------------------------------------------------------------
# compress: each source read once for the archive, and hashed by that read
# --------------------------------------------------------------------------

def _compress(src: Path, tmp_path: Path, profile: Profile, **kw):
    out = tmp_path / f"out-{profile.value}.excmp"
    result = engine.compress([src], out, profile,
                             StageContext(temp_dir=tmp_path / "t"), **kw)
    return out, result


def _restore(out: Path, tmp_path: Path) -> dict[str, bytes]:
    dest = tmp_path / f"restored-{out.stem}"
    engine.extract(out, dest, StageContext(temp_dir=tmp_path / "t2"))
    return {p.relative_to(dest).as_posix(): p.read_bytes()
            for p in dest.rglob("*") if p.is_file()}


PROFILES = [pytest.param(Profile.FAST, id="fast"),
            pytest.param(Profile.NORMAL, id="normal", marks=needs_7z)]


@pytest.fixture
def staged(monkeypatch):
    """Normal as it runs when 7-Zip cannot read the sources in place: the
    files are copied into the staging tree, hashed by that copy."""
    monkeypatch.setattr(engine, "_READS_SOURCES", ("tar", "zstd"))


@pytest.mark.parametrize("profile", PROFILES)
def test_each_source_is_opened_twice_not_four_times(tmp_path, monkeypatch, profile):
    """Once to analyse, once to archive-and-hash (at Normal: once to hash,
    and 7-Zip's own read of it is not ours to count). It was four: two
    handles in analysis, one to hash, one to copy."""
    src = tmp_path / "src"
    made = _tree(src)
    opens = _OpenCounter(monkeypatch, src)
    out, _ = _compress(src, tmp_path, profile)
    assert len(opens.counts) == len(made)
    assert set(opens.counts.values()) == {2}, opens.counts
    monkeypatch.undo()
    assert _restore(out, tmp_path) == made


@needs_7z
def test_a_staged_normal_job_also_opens_each_source_twice(tmp_path, monkeypatch, staged):
    src = tmp_path / "src"
    made = _tree(src)
    opens = _OpenCounter(monkeypatch, src)
    out, _ = _compress(src, tmp_path, Profile.NORMAL)
    assert set(opens.counts.values()) == {2}, opens.counts
    monkeypatch.undo()
    assert _restore(out, tmp_path) == made


# --------------------------------------------------------------------------
# Normal: 7-Zip reads the sources where they are, or the files are staged
# --------------------------------------------------------------------------

def _spy_staging(monkeypatch) -> list[Path]:
    copied: list[Path] = []
    real = engine._copy_hashing

    def spy(src, dst):
        copied.append(Path(src))
        return real(src, dst)

    monkeypatch.setattr(engine, "_copy_hashing", spy)
    return copied


@needs_7z
def test_normal_reads_one_folder_in_place_and_restores_it(tmp_path, monkeypatch):
    """No staging copy, the same names in the archive, every file back."""
    src = tmp_path / "My Folder"
    made = _tree(src)
    (src / "pkg0" / "name with spaces.txt").write_bytes(_text(50))
    (src / "pkg0" / "ünïcödé-名前.txt").write_bytes(_text(51))
    made[f"{src.name}/pkg0/name with spaces.txt"] = _text(50)
    made[f"{src.name}/pkg0/ünïcödé-名前.txt"] = _text(51)
    copied = _spy_staging(monkeypatch)
    out, result = _compress(src, tmp_path, Profile.NORMAL)
    assert copied == [] and not result.skipped
    assert _restore(out, tmp_path) == made
    ledger = {e.name: e.sha256 for e in engine.list_archive(out).entries}
    assert ledger == {rel: _sha(data) for rel, data in made.items()}


@needs_7z
def test_normal_reads_several_inputs_from_one_folder_in_place(tmp_path, monkeypatch):
    a, b, lone = tmp_path / "in" / "a", tmp_path / "in" / "b", tmp_path / "in" / "lone.txt"
    made = {**_tree(a, 5), **_tree(b, 4)}
    lone.write_bytes(_text(77))
    made["lone.txt"] = _text(77)
    copied = _spy_staging(monkeypatch)
    out = tmp_path / "out.excmp"
    engine.compress([a, b, lone], out, Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    assert copied == []
    assert _restore(out, tmp_path) == made


@needs_7z
def test_inputs_from_different_folders_are_staged(tmp_path, monkeypatch):
    """One working directory cannot give both their archive names, so the
    staging tree does, as before."""
    a, b = tmp_path / "one" / "a", tmp_path / "two" / "b"
    made = {**_tree(a, 4), **_tree(b, 4)}
    copied = _spy_staging(monkeypatch)
    out = tmp_path / "out.excmp"
    engine.compress([a, b], out, Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    assert len(copied) == 8
    assert _restore(out, tmp_path) == made


@pytest.mark.parametrize("name", ["@list.txt", "-switch.txt", " lead.txt", "it's \"q\".txt"])
def test_names_a_list_file_might_not_carry_are_left_to_staging(tmp_path, name):
    from excmp.stages.sevenzip import SevenZipStage
    base = tmp_path
    ok = [(base / "d" / "a.txt", "d/a.txt"), (base / "d" / "s" / "b.txt", "d/s/b.txt")]
    assert SevenZipStage.source_base(ok) == base
    assert SevenZipStage.source_base(ok + [(base / "d" / name, f"d/{name}")]) is None
    assert SevenZipStage.source_base(ok + [(tmp_path / "x" / "d" / "c.txt", "d/c.txt")]) is None
    assert SevenZipStage.source_base([(base / "other.txt", "d/a.txt")]) is None


@needs_7z
def test_when_7zip_cannot_finish_in_place_the_files_are_staged(tmp_path, monkeypatch):
    """7-Zip exits 1 when a file it was told to take cannot be opened - one
    locked after we hashed it. The job does not fail and does not publish a
    short archive: the files are staged, which is where a locked file is
    skipped by name."""
    from excmp.stages import sevenzip
    src = tmp_path / "src"
    made = _tree(src)
    copied = _spy_staging(monkeypatch)
    real = sevenzip.run_tool
    failed = []

    def fail_in_place(cmd, *a, **k):
        if any(str(c).startswith("@") for c in cmd):
            failed.append(1)
            raise StageError("sevenzip: exit 1: WARNING: The process cannot access the file")
        return real(cmd, *a, **k)

    monkeypatch.setattr(sevenzip, "run_tool", fail_in_place)
    out, result = _compress(src, tmp_path, Profile.NORMAL)
    assert failed == [1] and len(copied) == len(made)
    assert not result.skipped
    assert _restore(out, tmp_path) == made


@needs_7z
def test_a_source_changed_after_it_was_hashed_fails_the_gate(tmp_path, monkeypatch):
    """At Normal the digest is taken by our read and the bytes are archived
    by 7-Zip's, a moment later. A file that changes in between is in the
    archive with a digest that is not its own - and the gate, which restores
    the archive and hashes what comes out, refuses to publish it."""
    from excmp.stages import sevenzip
    src = tmp_path / "src"
    made = _tree(src)
    victim = tmp_path / sorted(made)[4]
    real = sevenzip.run_tool

    def rewrite_then_run(cmd, *a, **k):
        if any(str(c).startswith("@") for c in cmd):
            victim.write_bytes(_text(4242, len(victim.read_bytes())))
        return real(cmd, *a, **k)

    monkeypatch.setattr(sevenzip, "run_tool", rewrite_then_run)
    out = tmp_path / "out.excmp"
    with pytest.raises(VerifyError, match="hash mismatch"):
        engine.compress([src], out, Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    assert list(tmp_path.glob("out.excmp*")) == []


@needs_7z
def test_a_cancel_during_the_in_place_run_is_a_cancel_not_a_retry(tmp_path, monkeypatch):
    from excmp.stages import sevenzip
    src = tmp_path / "src"
    _tree(src)
    copied = _spy_staging(monkeypatch)
    ctx = StageContext(temp_dir=tmp_path / "t")

    def cancelled(cmd, *a, **k):
        ctx.cancel.set()
        raise StageError("sevenzip: cancelled")

    monkeypatch.setattr(sevenzip, "run_tool", cancelled)
    with pytest.raises(StageError, match="cancelled"):
        engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL, ctx)
    assert copied == [] and list(tmp_path.glob("out.excmp*")) == []


STAGED_PROFILES = [pytest.param(Profile.FAST, id="fast"),
                   pytest.param(Profile.NORMAL, id="normal-staged", marks=needs_7z)]


@pytest.mark.parametrize("profile", STAGED_PROFILES)
def test_the_ledger_digest_is_of_the_bytes_that_were_archived(tmp_path, monkeypatch, profile, staged):
    """A file rewritten (same size) after analysis. There is one read of it
    for the archive, so the digest and the archived bytes cannot disagree:
    the archive holds the file as that read found it, and says so."""
    src = tmp_path / "src"
    made = _tree(src)
    victim_rel = sorted(made)[3]
    victim = tmp_path / victim_rel
    newer = _text(999, len(made[victim_rel]))
    assert newer != made[victim_rel]
    real = engine._plan_that_fits

    def rewrite_then_plan(*a, **k):
        victim.write_bytes(newer)
        return real(*a, **k)

    monkeypatch.setattr(engine, "_plan_that_fits", rewrite_then_plan)
    out, _ = _compress(src, tmp_path, profile)
    ledger = {e.name: e for e in engine.list_archive(out).entries}
    restored = _restore(out, tmp_path)
    assert restored[victim_rel] == newer
    assert restored == {**made, victim_rel: newer}
    for rel, data in restored.items():
        assert ledger[rel].sha256 == _sha(data), rel


@pytest.mark.parametrize("profile", PROFILES)
def test_a_source_that_changed_size_after_analysis_is_not_published(tmp_path, monkeypatch, profile):
    """The ledger keeps the size analysis saw, so a file that grew or shrank
    before it was archived fails the gate's size check and nothing ships."""
    src = tmp_path / "src"
    made = _tree(src)
    victim = tmp_path / sorted(made)[5]
    real = engine._plan_that_fits

    def grow_then_plan(*a, **k):
        with victim.open("ab") as fh:
            fh.write(b"appended after analysis\n")
        return real(*a, **k)

    monkeypatch.setattr(engine, "_plan_that_fits", grow_then_plan)
    out = tmp_path / "out.excmp"
    with pytest.raises(VerifyError, match="size mismatch"):
        engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    assert list(tmp_path.glob("out.excmp*")) == []


def test_reading_the_sources_writes_the_stream_the_staged_tree_gave(tmp_path):
    """Fast used to copy the tree and tar the copy. Reading the sources in the
    order the copy would have been walked gives the same bytes - same member
    order, names, sizes, modes and times - so nothing about the archive
    format moved."""
    src = tmp_path / "Tree"
    made = _tree(src, 14)
    (src / "pkg0" / "UPPER.TXT").write_bytes(b"upper")
    (src / "pkg0" / "lower.txt").write_bytes(b"lower")
    (src / "pkg0" / "Zed.txt").write_bytes(b"zed")
    for name in ("launcher.exe", "run.CMD", "old.bat", "x.com", "notexe"):
        (src / "pkg1" / name).write_bytes(b"MZ" + name.encode())   # stat-by-name marks these +x
    (src / "pkg0" / "ro.txt").write_bytes(b"read-only")
    os.chmod(src / "pkg0" / "ro.txt", 0o444)
    ctx = StageContext(temp_dir=tmp_path / "t")
    files = [p for p in sorted(src.rglob("*")) if p.is_file()]
    shuffled = files[:]
    random.Random(5).shuffle(shuffled)
    relmap = {p: p.relative_to(src).as_posix() for p in shuffled}
    try:
        for stage, ext in [(TarStage(), "tar"), (ZstdStage(level=3), "zst")]:
            staged = stage.compress(src, tmp_path / f"staged.{ext}", ctx)
            ledger = {rel: {"size": p.stat().st_size, "sha256": engine._UNHASHED}
                      for p, rel in relmap.items()}
            direct, consumed = engine._compress_sources(
                stage, shuffled, relmap, ledger, tmp_path / f"direct.{ext}", ctx,
                lambda f, exc: pytest.fail(f"{f}: {exc}"))
            assert direct.read_bytes() == staged.read_bytes(), type(stage).__name__
            assert consumed == sum(p.stat().st_size for p in files)
            for p, rel in relmap.items():
                assert ledger[rel]["sha256"] == hash_file(p)
    finally:
        os.chmod(src / "pkg0" / "ro.txt", 0o666)
    assert len(made) == 14


def test_hard_linked_sources_are_archived_as_two_whole_files(tmp_path):
    """`tarfile` stores a second link to a file it has already seen as a link
    member with no bytes. A staged copy never had links; the sources can."""
    src = tmp_path / "src"
    made = _tree(src, 4)
    first = tmp_path / sorted(made)[0]
    twin = src / "twin.py"
    try:
        os.link(first, twin)
    except OSError:
        pytest.skip("hard links are not available here")
    made[f"{src.name}/twin.py"] = first.read_bytes()
    out, result = _compress(src, tmp_path, Profile.FAST)
    assert not result.skipped
    assert _restore(out, tmp_path) == made


def test_add_hashed_refuses_a_file_shorter_than_its_header(tmp_path, monkeypatch):
    """The file shrank between the `fstat` and the read. `tarfile` will not
    write a short member, and the stage says what happened to which file."""
    p = tmp_path / "a.txt"
    p.write_bytes(b"0123456789")
    real = tarfile.TarFile.gettarinfo

    def longer(self, *a, **k):
        info = real(self, *a, **k)
        info.size += 7
        return info

    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", longer)
    with tarfile.open(tmp_path / "o.tar", "w") as tar:
        with pytest.raises(StageError, match="changed while it was being archived"):
            add_hashed(tar, p, "a.txt")


def test_add_hashed_hashes_only_the_bytes_the_header_declares(tmp_path, monkeypatch):
    """...and one that grew contributes exactly the declared bytes, which are
    the ones hashed: digest, size and archived bytes all agree."""
    p = tmp_path / "a.txt"
    p.write_bytes(b"0123456789" * 10)
    real = tarfile.TarFile.gettarinfo

    def shorter(self, *a, **k):
        info = real(self, *a, **k)
        info.size -= 30
        return info

    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", shorter)
    with tarfile.open(tmp_path / "o.tar", "w") as tar:
        digest, size = add_hashed(tar, p, "a.txt")
    monkeypatch.undo()
    with tarfile.open(tmp_path / "o.tar") as tar:
        archived = tar.extractfile("a.txt").read()
    assert size == 70 and archived == b"0123456789" * 7
    assert digest == _sha(archived)


@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_locked_after_analysis_is_skipped_where_it_is_read(tmp_path, monkeypatch, profile):
    """K3 at the new place a piped file is first read for the archive."""
    from tests.test_locked_files import DenyAll
    src = tmp_path / "src"
    made = _tree(src)
    victim_rel = sorted(made)[2]
    real = engine._plan_that_fits
    held = {}

    def lock_then_plan(*a, **k):
        held["lock"] = DenyAll(tmp_path / victim_rel)
        held["lock"].__enter__()
        return real(*a, **k)

    monkeypatch.setattr(engine, "_plan_that_fits", lock_then_plan)
    try:
        out, result = _compress(src, tmp_path, profile)
    finally:
        held["lock"].__exit__(None, None, None)
    assert len(result.skipped) == 1 and victim_rel in result.skipped[0]
    del made[victim_rel]
    assert _restore(out, tmp_path) == made


def test_a_file_that_breaks_half_way_is_skipped_and_the_stage_redone(tmp_path, monkeypatch):
    """Its header is already in the stream, so the stream is abandoned and the
    stage run again without it. The job survives and the file is named."""
    src = tmp_path / "src"
    made = _tree(src)
    victim_rel = sorted(made)[7]
    victim = (tmp_path / victim_rel).resolve()
    real = tarstage._HashingReader.read
    broke = []

    def breaking(self, size=-1):
        if self._path == victim:
            broke.append(1)
            raise tarstage.SourceReadError(
                self._path, OSError(5, "Input/output error"))
        return real(self, size)

    monkeypatch.setattr(tarstage._HashingReader, "read", breaking)
    out, result = _compress(src, tmp_path, Profile.FAST)
    monkeypatch.undo()
    assert broke == [1], "the second attempt must not touch the broken file"
    assert len(result.skipped) == 1 and victim_rel in result.skipped[0]
    del made[victim_rel]
    restored = _restore(out, tmp_path)
    assert restored == made
    ledger = {e.name: e.sha256 for e in engine.list_archive(out).entries}
    assert ledger == {rel: _sha(data) for rel, data in made.items()}


def test_a_full_disk_under_the_stage_is_not_taken_for_an_unreadable_file(tmp_path, monkeypatch):
    """D4 at the new seam: an error *writing* the stream is the volume's, not
    the file's, and must abort as itself rather than skip file after file."""
    import errno
    src = tmp_path / "src"
    _tree(src)
    real = tarfile.TarFile.addfile

    def full(self, info, fileobj=None):
        if fileobj is not None:
            fileobj.read(10)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tarfile.TarFile, "addfile", full)
    out = tmp_path / "out.excmp"
    with pytest.raises(OSError) as err:
        engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    assert err.value.errno == errno.ENOSPC
    assert list(tmp_path.glob("out.excmp*")) == []
    assert real is not full


def test_no_entry_reaches_a_manifest_without_a_digest(tmp_path, monkeypatch):
    """Piped files get their digest from the stage that reads them. A stage
    that reported none must not leave a placeholder for the gate to compare
    against - the job is refused before a container is written."""
    src = tmp_path / "src"
    _tree(src)
    real = ZstdStage.compress_files

    def silent(self, entries, dst, ctx, on_added, on_unreadable, **k):
        return real(self, entries, dst, ctx, lambda *a: None, on_unreadable, **k)

    monkeypatch.setattr(ZstdStage, "compress_files", silent)
    out = tmp_path / "out.excmp"
    with pytest.raises(StageError, match="without a SHA-256"):
        engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    assert list(tmp_path.glob("out.excmp*")) == []


def test_copy_hashing_copies_hashes_and_keeps_the_metadata(tmp_path):
    src, dst = tmp_path / "a.bin", tmp_path / "b.bin"
    data = random.Random(4).randbytes(2_500_000)       # more than one chunk
    src.write_bytes(data)
    os.utime(src, ns=(1_600_000_000_123_456_700, 1_500_000_000_987_654_300))
    os.chmod(src, 0o444)
    try:
        assert engine._copy_hashing(src, dst) == _sha(data) == hash_file(dst)
        assert dst.stat().st_mtime_ns == src.stat().st_mtime_ns
        assert not os.access(dst, os.W_OK), "read-only did not travel"
    finally:
        os.chmod(src, 0o666)
        os.chmod(dst, 0o666)


# --------------------------------------------------------------------------
# the gate: as strict, minus the one pass nobody reads
# --------------------------------------------------------------------------

def test_the_gate_checks_every_hash_and_stamps_no_timestamps(tmp_path, monkeypatch):
    """The gate's restore is hashed and deleted; setting 1,801 modification
    times on it was work for nobody. An extraction the user keeps still gets
    them, and the gate still runs the real `verify_restore` over everything."""
    src = tmp_path / "src"
    made = _tree(src)
    stamped, verified = [], []
    real_stamp, real_verify = engine._apply_mtimes, engine.verify_restore

    def stamp(out_dir, ledger):
        stamped.append(len(ledger))
        return real_stamp(out_dir, ledger)

    def verify(out_dir, ledger):
        verified.append(len(ledger))
        return real_verify(out_dir, ledger)

    monkeypatch.setattr(engine, "_apply_mtimes", stamp)
    monkeypatch.setattr(engine, "verify_restore", verify)
    out, _ = _compress(src, tmp_path, Profile.FAST)
    assert verified == [len(made)] and stamped == []
    dest = tmp_path / "kept"
    engine.extract(out, dest, StageContext(temp_dir=tmp_path / "t2"))
    assert stamped == [len(made)]
    for rel in made:
        assert (dest / rel).stat().st_mtime_ns == (tmp_path / rel).stat().st_mtime_ns


@needs_7z
@pytest.mark.parametrize("with_stored", [False, True])
def test_every_piped_file_unreadable_in_place_is_still_a_clean_outcome(tmp_path, monkeypatch, with_stored):
    """Nothing could be hashed for 7-Zip, so nothing is staged either. With
    no other file that is "none of the files could be read"; with a stored
    file beside them the job goes on and names what it left out."""
    from excmp.stages.base import NeedsStaging
    from excmp.stages.sevenzip import SevenZipStage
    src = tmp_path / "src"
    made = _tree(src, 4)
    if with_stored:
        blob = random.Random(8).randbytes(70_000)       # high entropy: stored
        (src / "rand.bin").write_bytes(blob)

    def nothing_readable(self, entries, dst, ctx, on_added, on_unreadable, **k):
        for path, _ in entries:
            on_unreadable(Path(path), PermissionError(13, "Permission denied"))
        raise NeedsStaging("no source file could be read")

    monkeypatch.setattr(SevenZipStage, "compress_files", nothing_readable)
    out = tmp_path / "out.excmp"
    ctx = StageContext(temp_dir=tmp_path / "t")
    if not with_stored:
        with pytest.raises(ValueError, match="could be read"):
            engine.compress([src], out, Profile.NORMAL, ctx)
        assert list(tmp_path.glob("out.excmp*")) == []
        return
    result = engine.compress([src], out, Profile.NORMAL, ctx)
    assert len(result.skipped) == len(made)
    assert _restore(out, tmp_path) == {"src/rand.bin": blob}


# A list file is one name per line, so a name that holds a line separator or
# any other control character must never be written into one (review,
# 2026-11-25): "a\nb.txt" would reach 7-Zip as two entries, "a" and "b.txt".

@pytest.mark.parametrize("bad", ["a\nb.txt", "a\rb.txt", "a\r\nb.txt", "a\x00b.txt",
                                 "a\tb.txt", "a\x1fb.txt", "a\x7fb.txt",
                                 "a\x85b.txt", "a\u2028b.txt", "a\u2029b.txt"])
@pytest.mark.parametrize("where", ["file", "folder"])
def test_a_name_with_a_control_character_is_left_to_staging(tmp_path, bad, where):
    from excmp.stages.sevenzip import SevenZipStage
    ok = [(tmp_path / "d" / "a.txt", "d/a.txt")]
    arc = f"d/{bad}" if where == "file" else f"d/{bad}/x.txt"
    # Built with PurePath semantics only: Windows will not create such a name.
    entry = (tmp_path.joinpath(*arc.split("/")), arc)
    assert SevenZipStage.source_base(ok) == tmp_path
    assert SevenZipStage.source_base(ok + [entry]) is None


def test_the_list_file_is_never_written_with_a_split_name(tmp_path, monkeypatch):
    """The second lock on the same door: even if `source_base` were to let
    such a name through, the list is refused before it is written and before
    7-Zip is started, and the files are staged."""
    from excmp.stages import sevenzip
    from excmp.stages.base import NeedsStaging
    real = tmp_path / "d" / "real.txt"
    real.parent.mkdir()
    real.write_bytes(b"payload")
    ran, written = [], []
    monkeypatch.setattr(sevenzip.SevenZipStage, "source_base",
                        staticmethod(lambda entries: tmp_path))
    monkeypatch.setattr(sevenzip.SevenZipStage, "_exe", lambda self: "7z.exe")
    monkeypatch.setattr(sevenzip, "run_tool", lambda *a, **k: ran.append(a))
    real_write = Path.write_text

    def spy(self, *a, **k):
        written.append(self.name)
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy)
    stage = sevenzip.SevenZipStage()
    for bad in ("d/real.txt\nd/other.txt", "d/real.txt\rother", "d/re\u2028al.txt"):
        with pytest.raises(NeedsStaging, match="line"):
            stage.compress_files([(real, bad)], tmp_path / "s0.7z",
                                 StageContext(temp_dir=tmp_path / "t"),
                                 lambda *a: None, lambda *a: None)
    assert ran == [] and written == []
    assert not list(tmp_path.glob("s0.7z*"))


@needs_7z
def test_a_job_whose_names_cannot_be_listed_still_archives_through_staging(tmp_path, monkeypatch):
    """End to end through the fallback: 7-Zip is never given a list, every
    file is staged, and the restore is byte-identical."""
    from excmp.stages import sevenzip
    src = tmp_path / "src"
    made = _tree(src)
    copied = _spy_staging(monkeypatch)
    monkeypatch.setattr(sevenzip.SevenZipStage, "source_base",
                        staticmethod(lambda entries: None))
    lists = []
    real = sevenzip.run_tool

    def watch(cmd, *a, **k):
        lists.extend(c for c in cmd if str(c).startswith("@"))
        return real(cmd, *a, **k)

    monkeypatch.setattr(sevenzip, "run_tool", watch)
    out, result = _compress(src, tmp_path, Profile.NORMAL)
    assert lists == [] and len(copied) == len(made) and not result.skipped
    assert _restore(out, tmp_path) == made
