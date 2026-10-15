"""B13: the Ogg specialist wired into the engine and the container.

The three earlier specialists packed inside ``write_container`` with no way to
cancel, no progress and no sense of how long they would take, because lepton
and FLAC run at tens of MB/s. balrogg runs at ~0.1-0.3 MB/s at ``-9``, so the
same loop would sit for an hour on a game's audio folder with a Cancel button
that did nothing. This file pins what had to change, and keeps the contract
every specialist shares: whatever is packed restores byte for byte, and the
ledger records the *original* file.
"""

from __future__ import annotations

import json
import random
import threading
import zipfile
from pathlib import Path

import pytest

from excmp import engine, oggpack
from excmp.manifest import MANIFEST_NAME
from excmp.planner import Profile
from excmp.stages.base import StageContext, StageError

FIXTURES = Path(__file__).parent / "fixtures" / "ogg"
SMALL = FIXTURES / "invalid_keypress.ogg"
BIGGER = FIXTURES / "fallbackring.ogg"

needs_balrogg = pytest.mark.skipif(not oggpack.available(),
                                   reason="the pinned balrogg is not installed")


def _tree(tmp_path: Path, *, text: bool = True) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    (src / "b.ogg").write_bytes(BIGGER.read_bytes())
    if text:
        (src / "notes.txt").write_text("something to pipeline\n" * 300,
                                       encoding="utf-8")
    return src


def _compress(src: Path, tmp_path: Path, profile=Profile.NORMAL, **ctx_kw):
    ctx = StageContext(temp_dir=tmp_path / "t", **ctx_kw)
    out = tmp_path / "out.excmp"
    result = engine.compress([src], out, profile, ctx)
    return out, result


def _ledger(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as zf:
        return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))["inputs"]


# -- it works, and the ledger says so -----------------------------------------------

@needs_balrogg
def test_an_ogg_survives_a_real_compress_and_restore(tmp_path):
    src = _tree(tmp_path)
    before = {p.name: p.read_bytes() for p in src.glob("*")}
    archive, _ = _compress(src, tmp_path)

    out = tmp_path / "restored"
    result = engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))

    assert result.verified == 3
    for name, data in before.items():
        assert (out / "src" / name).read_bytes() == data, name


@needs_balrogg
def test_the_archive_really_holds_balrogg_not_a_raw_ogg(tmp_path):
    """The round-trip above passes whether or not anything was packed, since
    storing raw also restores. This one fails if the codec is not wired in."""
    src = _tree(tmp_path)
    archive, _ = _compress(src, tmp_path)

    ledger = _ledger(archive)
    with zipfile.ZipFile(archive) as zf:
        member = zf.getinfo("stored/src/a.ogg")
    entry = ledger["src/a.ogg"]
    assert entry.get("codec") == "balrogg", entry
    assert entry["size"] == SMALL.stat().st_size, "the ledger records the ORIGINAL size"
    assert member.file_size < SMALL.stat().st_size * 0.7


@needs_balrogg
def test_two_identical_oggs_still_deduplicate(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    (src / "b.ogg").write_bytes(SMALL.read_bytes())
    archive, _ = _compress(src, tmp_path)
    out = tmp_path / "restored"
    result = engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    assert result.verified == 2
    assert (out / "src" / "a.ogg").read_bytes() == SMALL.read_bytes()
    assert (out / "src" / "b.ogg").read_bytes() == SMALL.read_bytes()


@needs_balrogg
def test_a_file_balrogg_refuses_is_stored_and_the_job_still_succeeds(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    junk = b"OggS" + random.Random(5).randbytes(8000)      # claims to be Ogg
    (src / "fake.ogg").write_bytes(junk)
    (src / "real.ogg").write_bytes(SMALL.read_bytes())
    archive, _ = _compress(src, tmp_path)

    ledger = _ledger(archive)
    assert "codec" not in ledger["src/fake.ogg"]
    assert ledger["src/real.ogg"].get("codec") == "balrogg"
    out = tmp_path / "restored"
    engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    assert (out / "src" / "fake.ogg").read_bytes() == junk


def test_without_balrogg_the_ogg_is_stored_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    src = _tree(tmp_path)
    archive, _ = _compress(src, tmp_path)
    assert all("codec" not in e for e in _ledger(archive).values())
    out = tmp_path / "restored"
    engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    assert (out / "src" / "a.ogg").read_bytes() == SMALL.read_bytes()


# -- effort follows the profile ----------------------------------------------------------

@pytest.mark.parametrize("profile, effort", [(Profile.FAST, 1), (Profile.NORMAL, 4)])
def test_the_profile_picks_balrogg_effort(tmp_path, monkeypatch, profile, effort):
    seen: list[int | None] = []

    def fake_pack(raw, ctx=None, effort=None, cancel=None):
        seen.append(effort)
        return None

    monkeypatch.setattr(oggpack, "available", lambda: True)
    monkeypatch.setattr(oggpack, "pack", fake_pack)
    _compress(_tree(tmp_path), tmp_path, profile)
    assert seen == [effort, effort]


# -- cancel, pause and progress --------------------------------------------------------------

@needs_balrogg
def test_cancel_during_the_pack_phase_stops_the_job_and_publishes_nothing(tmp_path):
    src = _tree(tmp_path)
    cancel = threading.Event()
    seen = []

    def on_progress(stage, pct):
        seen.append((stage, pct))
        if stage == "pack":
            cancel.set()

    ctx = StageContext(temp_dir=tmp_path / "t", progress_cb=on_progress)
    ctx.cancel = cancel
    out = tmp_path / "out.excmp"
    with pytest.raises(StageError, match="cancelled"):
        engine.compress([src], out, Profile.NORMAL, ctx)

    assert not out.exists()
    assert not list(tmp_path.glob("out.excmp*")), "a partial archive was left behind"
    assert any(s == "pack" for s, _ in seen)


@needs_balrogg
def test_the_pack_phase_reports_monotonic_progress_ending_at_100(tmp_path):
    seen: list[float] = []
    ctx_progress = lambda stage, pct: seen.append(pct) if stage == "pack" else None  # noqa: E731
    _compress(_tree(tmp_path), tmp_path, progress_cb=ctx_progress)
    assert seen and seen[0] == 0.0 and seen[-1] == 100.0
    assert seen == sorted(seen)


def test_a_job_with_nothing_to_pack_reports_no_pack_phase(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("plain text\n" * 500, encoding="utf-8")
    stages: list[str] = []
    _compress(src, tmp_path, progress_cb=lambda s, p: stages.append(s))
    assert "pack" not in stages


def test_pause_holds_the_pack_phase_between_files(tmp_path, monkeypatch):
    """Pausing means "finish this file, then wait", as it does between stages,
    and cancel always wins."""
    order: list[str] = []
    ctx_holder = {}

    import time
    stamps: list[float] = []

    def fake_pack(raw, ctx=None, effort=None, cancel=None):
        order.append("pack")
        stamps.append(time.monotonic())
        if len(order) == 1:
            ctx_holder["ctx"].pause.set()
            threading.Timer(0.6, ctx_holder["ctx"].pause.clear).start()
        return None

    monkeypatch.setattr(oggpack, "available", lambda: True)
    monkeypatch.setattr(oggpack, "pack", fake_pack)
    ctx = StageContext(temp_dir=tmp_path / "t")
    ctx_holder["ctx"] = ctx
    engine.compress([_tree(tmp_path)], tmp_path / "out.excmp", Profile.NORMAL, ctx)
    assert order == ["pack", "pack"]
    # Measured between the two files, not around the whole job: the job takes
    # longer than the pause anyway, which let the test pass with the pause
    # loop deleted (review, B13).
    assert stamps[1] - stamps[0] >= 0.5, "the pause was ignored"


# -- the safety half --------------------------------------------------------------------------

def test_files_no_specialist_claims_are_not_read_whole(tmp_path, monkeypatch):
    """The packing loop used to ``read_bytes()`` every stored file, whether or
    not any codec would claim it, only to look at its first 16 bytes. On a
    folder of large videos that is the whole folder read into memory one file
    at a time, for nothing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + random.Random(1).randbytes(500_000))
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    read: list[str] = []
    real = Path.read_bytes

    def spy(self):
        read.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    monkeypatch.setattr(oggpack, "available", lambda: True)
    monkeypatch.setattr(oggpack, "pack", lambda raw, **kw: None)
    _compress(src, tmp_path)
    assert "clip.mp4" not in read, read


def test_restoring_hands_the_ledger_size_to_the_decoder_as_its_limit(tmp_path, monkeypatch):
    """The archive is attacker-supplied data and balrogg's output size is not
    bounded by its input size, so the decode is told how big the file is
    allowed to get and killed past it."""
    from excmp import manifest

    seen: list[int | None] = []
    real_unpack = oggpack.unpack

    def spy(packed, ctx=None, limit=None, cancel=None):
        seen.append(limit)
        return real_unpack(packed, ctx=ctx, limit=limit, cancel=cancel)

    if not oggpack.available():
        pytest.skip("the pinned balrogg is not installed")
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    archive, _ = _compress(src, tmp_path)
    monkeypatch.setattr(oggpack, "unpack", spy)
    engine.extract(archive, tmp_path / "restored", StageContext(temp_dir=tmp_path / "t2"))
    assert seen and all(limit == SMALL.stat().st_size for limit in seen), seen
    assert manifest._CODECS["balrogg"] is oggpack


# -- review fixes --------------------------------------------------------------------------

def _slow_unpack_tool(monkeypatch):
    """Make balrogg's decoder a script that never finishes, so only a cancel
    can end a restore."""
    import sys

    monkeypatch.setattr(oggpack, "_argv",
                        lambda exe, effort, mode, src, dst:
                        [sys.executable, "-c", "import time; time.sleep(120)",
                         str(src), str(dst)])


@needs_balrogg
def test_cancel_reaches_the_decoder_during_a_restore(tmp_path, monkeypatch):
    """The restore of a packed entry used to run with no cancel at all, so
    Cancel and window-close waited out every balrogg decode in the archive."""
    import time

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    archive, _ = _compress(src, tmp_path)
    assert _ledger(archive)["src/a.ogg"].get("codec") == "balrogg"

    _slow_unpack_tool(monkeypatch)
    ctx = StageContext(temp_dir=tmp_path / "t2")
    threading.Timer(0.5, ctx.cancel.set).start()
    started = time.monotonic()
    with pytest.raises(StageError, match="cancelled"):
        engine.extract(archive, tmp_path / "restored", ctx)
    assert time.monotonic() - started < 15


def test_packed_members_are_spooled_to_disk_not_held_in_memory(tmp_path, monkeypatch):
    """Every packed member used to be held in a dict until the zip was
    written: on a 12 GB Ogg library that is ~10 GB of RAM on a 16 GB laptop.
    They are spooled to the job's temp dir instead."""
    from excmp import manifest

    held: list[int] = []
    monkeypatch.setattr(oggpack, "available", lambda: True)
    monkeypatch.setattr(oggpack, "pack", lambda raw, **kw: b"P" * (len(raw) // 2))
    monkeypatch.setattr(oggpack, "unpack", lambda packed, **kw: (_ for _ in ()).throw(RuntimeError("x")))

    real_writestr = zipfile.ZipFile.writestr

    def spy(self, name, data, *a, **k):
        if str(getattr(name, "filename", name)).startswith(manifest.STORED_PREFIX):
            held.append(len(data))
        return real_writestr(self, name, data, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", spy)
    src = _tree(tmp_path, text=False)
    out = tmp_path / "out.excmp"
    with pytest.raises(Exception):
        # unpack is broken on purpose, so D9 refuses to publish; what matters
        # is how the container was written on the way.
        engine.compress([src], out, Profile.NORMAL, StageContext(temp_dir=tmp_path / "t"))
    assert held == [], "packed members were written from memory"
    left = [p for p in (tmp_path / "t").rglob("*") if p.is_file()]
    assert left == [], f"spool files left behind: {left}"


def test_files_outside_the_codec_size_window_are_never_read_whole(tmp_path, monkeypatch):
    read: list[str] = []
    real = Path.read_bytes

    def spy(self):
        read.append(self.name)
        return real(self)

    src = tmp_path / "src"
    src.mkdir()
    (src / "tiny.ogg").write_bytes(b"OggS" + b"\x00" * 100)      # < MIN_SIZE
    monkeypatch.setattr(Path, "read_bytes", spy)
    monkeypatch.setattr(oggpack, "available", lambda: True)
    monkeypatch.setattr(oggpack, "pack", lambda raw, **kw: None)
    _compress(src, tmp_path)
    assert "tiny.ogg" not in read


def test_a_missing_or_tampered_codec_says_how_to_recover(tmp_path, monkeypatch):
    if not oggpack.available():
        pytest.skip("the pinned balrogg is not installed")
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ogg").write_bytes(SMALL.read_bytes())
    archive, _ = _compress(src, tmp_path)
    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    with pytest.raises(Exception, match="re-fetch|integrity"):
        engine.extract(archive, tmp_path / "restored", StageContext(temp_dir=tmp_path / "t2"))
