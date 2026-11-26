"""One read of a source is only safe if nothing can write to it meanwhile.

The small-files work made the ledger's SHA-256 the hash of the read that
archives the file. An adversarial review (2026-11-26) showed what that lost:
a file rewritten in place, at the same size, *while* that one read ran was
published torn - half the old bytes, half the new - with a digest that
matched, because the digest was of the same torn read. `main` read every
file twice (hash, then copy), so the two reads disagreed and the gate
refused.

The rule now, never less safe than that:

* the single hashed read holds the file open with **writers denied**
  (`FILE_SHARE_READ` only), so the file cannot change under it;
* if that open is refused because somebody already has the file open for
  writing, that one file goes the old way - hashed by one read, archived by a
  second - and a change between them refuses the job;
* a file that cannot be opened for reading at all is still skipped by name.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import threading
from pathlib import Path

import pytest

from excmp import engine, sharedread
from excmp.planner import Profile
from excmp.stages.base import NeedsStaging, StageContext, StageError
from excmp.tools import find_tools
from excmp.verify import VerifyError

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None,
                              reason="7-Zip not installed")
windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="Windows share modes")
PROFILES = [pytest.param(Profile.FAST, id="fast"),
            pytest.param(Profile.NORMAL, id="normal", marks=needs_7z)]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(seed: int, size: int = 6_000) -> bytes:
    return (f"line {seed} of some compressible text\n".encode() * (size // 20 + 1))[:size]


def _tree(root: Path, files: int = 6) -> dict[str, bytes]:
    root.mkdir(parents=True)
    made = {}
    for i in range(files):
        (root / f"f{i}.txt").write_bytes(_text(i))
        made[f"{root.name}/f{i}.txt"] = _text(i)
    return made


def _restore(out: Path, tmp_path: Path) -> dict[str, bytes]:
    dest = tmp_path / "restored"
    engine.extract(out, dest, StageContext(temp_dir=tmp_path / "t2"))
    return {p.relative_to(dest).as_posix(): p.read_bytes()
            for p in dest.rglob("*") if p.is_file()}


def _spy_routes(monkeypatch) -> dict[str, list[str]]:
    """Which way each source was opened for the archive, by file name."""
    seen: dict[str, list[str]] = {}
    real = sharedread.open_for_archive

    def spy(path):
        fh, how = real(path)
        seen.setdefault(Path(path).name, []).append(how)
        return fh, how

    monkeypatch.setattr(sharedread, "open_for_archive", spy)
    return seen


def _count_plain_opens(monkeypatch, under: Path) -> dict[str, int]:
    import builtins
    import tarfile
    counts: dict[str, int] = {}
    prefix = os.path.normcase(str(under.resolve())) + os.sep
    real = io.open

    def counting(file, *a, **k):
        if isinstance(file, (str, os.PathLike)):
            name = os.path.normcase(os.fspath(file))
            if name.startswith(prefix):
                counts[Path(name).name] = counts.get(Path(name).name, 0) + 1
        return real(file, *a, **k)

    monkeypatch.setattr(io, "open", counting)
    monkeypatch.setattr(builtins, "open", counting)
    monkeypatch.setattr(tarfile, "bltn_open", counting)
    return counts


# --------------------------------------------------------------------------
# the helper
# --------------------------------------------------------------------------

@windows_only
def test_the_stable_open_denies_writers_and_only_while_it_is_held(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"0123456789")
    fh, how = sharedread.open_for_archive(f)
    try:
        assert how == sharedread.STABLE
        assert fh.read() == b"0123456789" and os.fstat(fh.fileno()).st_size == 10
        with pytest.raises(PermissionError):
            open(f, "r+b")
        with open(f, "rb") as other:            # readers are not turned away
            assert other.read(4) == b"0123"
    finally:
        fh.close()
    with open(f, "r+b") as writer:
        writer.write(b"X")


@windows_only
def test_a_file_somebody_has_open_for_writing_is_reported_busy_not_unreadable(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"0123456789")
    with open(f, "r+b"):
        fh, how = sharedread.open_for_archive(f)
        with fh:
            assert how == sharedread.BUSY and fh.read() == b"0123456789"


@windows_only
def test_a_file_that_cannot_be_read_at_all_raises_as_a_plain_open_does(tmp_path):
    from tests.test_locked_files import DenyAll
    f = tmp_path / "a.txt"
    f.write_bytes(b"0123456789")
    with DenyAll(f):
        with pytest.raises(PermissionError):
            sharedread.open_for_archive(f)
    with pytest.raises(FileNotFoundError):
        sharedread.open_for_archive(tmp_path / "gone.txt")


def test_the_helper_falls_back_to_a_plain_open_when_the_win32_call_itself_fails(tmp_path, monkeypatch):
    """ctypes missing, a broken prototype, a platform without share modes:
    the job still reads the file, the way it did before the helper existed."""
    f = tmp_path / "a.txt"
    f.write_bytes(b"0123456789")

    def broken(path):
        raise RuntimeError("kernel32 is not what it was")

    monkeypatch.setattr(sharedread, "_open_denying_writers", broken)
    fh, how = sharedread.open_for_archive(f)
    with fh:
        assert how == sharedread.PLAIN and fh.read() == b"0123456789"


def test_off_windows_the_helper_is_a_plain_open(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_bytes(b"abc")
    monkeypatch.setattr(sharedread, "_WINDOWS", False)
    fh, how = sharedread.open_for_archive(f)
    with fh:
        assert how == sharedread.PLAIN and fh.read() == b"abc"


# --------------------------------------------------------------------------
# through the engine
# --------------------------------------------------------------------------

@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_nobody_holds_is_read_once_with_writers_denied(tmp_path, monkeypatch, profile):
    src = tmp_path / "src"
    made = _tree(src)
    routes = _spy_routes(monkeypatch)
    plain = _count_plain_opens(monkeypatch, src)
    out = tmp_path / "out.excmp"
    engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    assert routes == {f"f{i}.txt": [sharedread.STABLE] for i in range(6)}
    assert set(plain.values()) == {1}, plain        # analysis; nothing else
    monkeypatch.undo()
    assert _restore(out, tmp_path) == made


@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_held_open_for_writing_is_read_twice_and_still_archives(tmp_path, monkeypatch, profile):
    """Nobody writes, so the two reads agree and the job is byte-identical."""
    src = tmp_path / "src"
    made = _tree(src)
    routes = _spy_routes(monkeypatch)
    out = tmp_path / "out.excmp"
    with open(src / "f2.txt", "r+b"):
        result = engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    assert not result.skipped
    assert sharedread.BUSY in routes["f2.txt"]
    monkeypatch.undo()
    assert _restore(out, tmp_path) == made
    ledger = {e.name: e.sha256 for e in engine.list_archive(out).entries}
    assert ledger == {rel: _sha(data) for rel, data in made.items()}


@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_a_busy_file_that_changes_between_its_two_reads_refuses_the_job(tmp_path, monkeypatch, profile):
    """The old guarantee, kept for exactly the files that need it."""
    src = tmp_path / "src"
    _tree(src)
    victim = src / "f3.txt"
    holder = open(victim, "r+b")
    real = sharedread.open_for_archive
    state = {"n": 0}

    def rewrite_after_the_first_read(path):
        fh, how = real(path)
        if Path(path).name == "f3.txt" and how == sharedread.BUSY:
            state["n"] += 1
            first = fh

            class Then:
                def __getattr__(self, name):
                    return getattr(first, name)

                def close(self):
                    first.close()
                    holder.seek(0)
                    # Different every time: at Normal the file is met twice
                    # (in place, then staged), and the same bytes twice would
                    # be no change at all.
                    holder.write(b"REWRITTEN BETWEEN THE READS %d" % state["n"])
                    holder.flush()

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    self.close()

            return Then(), how
        return fh, how

    monkeypatch.setattr(sharedread, "open_for_archive", rewrite_after_the_first_read)
    out = tmp_path / "out.excmp"
    try:
        with pytest.raises((StageError, VerifyError), match="changed|hash mismatch"):
            engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    finally:
        holder.close()
    assert state["n"] >= 1
    assert list(tmp_path.glob("out.excmp*")) == []


@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_an_exclusively_locked_file_is_still_skipped_by_name(tmp_path, monkeypatch, profile):
    from tests.test_locked_files import DenyAll
    src = tmp_path / "src"
    made = _tree(src)
    real = engine._plan_that_fits
    held = {}

    def lock_then_plan(*a, **k):
        held["lock"] = DenyAll(src / "f4.txt")
        held["lock"].__enter__()
        return real(*a, **k)

    monkeypatch.setattr(engine, "_plan_that_fits", lock_then_plan)
    out = tmp_path / "out.excmp"
    try:
        result = engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    finally:
        held["lock"].__exit__(None, None, None)
    assert len(result.skipped) == 1
    assert "src/f4.txt: in use by another program" in result.skipped[0]
    del made["src/f4.txt"]
    monkeypatch.undo()
    assert _restore(out, tmp_path) == made


@windows_only
@pytest.mark.parametrize("profile", PROFILES)
def test_a_live_same_size_writer_never_gets_a_torn_file_published(tmp_path, profile):
    """The review's reproduction. A thread rewrites a large file in place,
    all-A then all-B and back, for the whole job. Either the job is refused,
    or what was archived is a state the file really had."""
    src = tmp_path / "src"
    src.mkdir()
    size = 32 << 20
    live = src / "live.txt"
    live.write_bytes(b"A" * size)
    for i in range(3):
        (src / f"pad{i}.txt").write_bytes(_text(i))
    stop = threading.Event()

    def writer():
        flip = 0
        while not stop.is_set():
            flip ^= 1
            block = (b"B" if flip else b"A") * (1 << 20)
            try:
                with open(live, "r+b") as fh:
                    for _ in range(size >> 20):
                        fh.write(block)     # a whole pass per open, always
            except OSError:
                pass

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    out = tmp_path / "out.excmp"
    try:
        engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    except (StageError, VerifyError) as refused:
        assert "changed" in str(refused) or "mismatch" in str(refused), refused
    finally:
        stop.set()
        thread.join()
    if not out.exists():
        assert list(tmp_path.glob("out.excmp*")) == []
        return
    data = _restore(out, tmp_path)["src/live.txt"]
    a, b = data.count(b"A"), data.count(b"B")
    assert a + b == size and 0 in (a, b), f"TORN: {a} A bytes and {b} B bytes"


# --------------------------------------------------------------------------
# the 7-Zip list file
# --------------------------------------------------------------------------

@pytest.mark.parametrize("arc", ["﻿bom.txt", "d/﻿bom.txt", "﻿dir/x.txt",
                                 "d/mid﻿dle.txt"])
def test_a_name_holding_a_byte_order_mark_is_left_to_staging(tmp_path, arc):
    """U+FEFF at the head of a list is a BOM to whoever reads the list, so
    "<BOM>bom.txt" on the first line named its sibling "bom.txt" instead."""
    from excmp.stages.sevenzip import SevenZipStage
    ok = [(tmp_path / "ok.txt", "ok.txt")]
    assert SevenZipStage.source_base(ok) == tmp_path
    assert SevenZipStage.source_base([(tmp_path.joinpath(*arc.split("/")), arc)] + ok) is None


def _stub_seven_zip(monkeypatch, tmp_path):
    from excmp.stages import sevenzip
    ran, lists = [], []
    monkeypatch.setattr(sevenzip.SevenZipStage, "source_base",
                        staticmethod(lambda entries: tmp_path))
    monkeypatch.setattr(sevenzip.SevenZipStage, "_exe", lambda self: "7z.exe")

    def fake_run(cmd, *a, **k):
        ran.append(cmd)
        lists.extend(Path(str(c)[1:]).read_bytes() for c in cmd if str(c).startswith("@"))
        Path(next(c for c in cmd if str(c).endswith(".7z"))).write_bytes(b"7z")

    monkeypatch.setattr(sevenzip, "run_tool", fake_run)
    return sevenzip.SevenZipStage(), ran, lists


def test_the_list_file_starts_with_a_mark_of_its_own(tmp_path, monkeypatch):
    """Written as UTF-8 *with* a signature: the reader strips that one and
    the first name is read as it was written, whatever it starts with."""
    stage, ran, lists = _stub_seven_zip(monkeypatch, tmp_path)
    real = tmp_path / "d" / "real.txt"
    real.parent.mkdir()
    real.write_bytes(b"payload")
    stage.compress_files([(real, "d/real.txt")], tmp_path / "s0.7z",
                         StageContext(temp_dir=tmp_path / "t"),
                         lambda *a: None, lambda *a: None)
    assert len(ran) == 1 and "-scsUTF-8" in ran[0]
    assert lists == [b"\xef\xbb\xbf" + f"d{os.sep}real.txt\n".encode()]


@pytest.mark.parametrize("bad,why", [("d/﻿real.txt", "byte order mark"),
                                     ("d/lone\ud800.txt", "cannot be written")])
def test_a_name_the_list_cannot_carry_is_refused_before_anything_runs(tmp_path, monkeypatch, bad, why):
    """A lone surrogate is a legal Windows name and not legal UTF-8: writing
    it raised UnicodeEncodeError out of the stage. It is a reason to stage."""
    stage, ran, lists = _stub_seven_zip(monkeypatch, tmp_path)
    real = tmp_path / "d" / "real.txt"
    real.parent.mkdir()
    real.write_bytes(b"payload")
    with pytest.raises(NeedsStaging, match=why):
        stage.compress_files([(real, bad)], tmp_path / "s0.7z",
                             StageContext(temp_dir=tmp_path / "t"),
                             lambda *a: None, lambda *a: None)
    assert ran == [] and lists == [] and not list(tmp_path.glob("s0.7z*"))


@windows_only
@needs_7z
@pytest.mark.parametrize("case", ["bom_single", "bom_dir"])
def test_selecting_a_bom_named_input_archives_it_and_not_its_sibling(tmp_path, case):
    """The review's two cases, end to end at Normal."""
    src = tmp_path / "in"
    src.mkdir()
    if case == "bom_single":
        (src / "bom.txt").write_bytes(b"the sibling nobody selected " * 40)
        (src / "﻿bom.txt").write_bytes(b"the selected file " * 40)
        inputs = [src / "﻿bom.txt"]
        want = {"﻿bom.txt": b"the selected file " * 40}
    else:
        a, b = src / "﻿dir", src / "dir"
        a.mkdir()
        b.mkdir()
        (a / "x.txt").write_bytes(b"selected x " * 40)
        (a / "y.txt").write_bytes(b"selected y " * 40)
        (b / "x.txt").write_bytes(b"sibling x, never selected " * 40)
        inputs = [a]
        want = {"﻿dir/x.txt": b"selected x " * 40,
                "﻿dir/y.txt": b"selected y " * 40}
    out = tmp_path / "out.excmp"
    engine.compress(inputs, out, Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    assert _restore(out, tmp_path) == want
