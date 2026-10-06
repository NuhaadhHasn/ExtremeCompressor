"""B13: the Ogg specialist, balrogg driven as a subprocess.

Same contract as :mod:`excmp.flacaudio` and :mod:`excmp.jpeg`: ``pack`` returns
bytes that have **already been restored once and compared**, or ``None``, and
``None`` is always a correct answer. Nothing balrogg says counts on its own -
its exit codes are documented (0 ok, 1 refused, 4 internal error) and are not
the gate. The byte comparison is.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from excmp import oggpack
from excmp.stages.base import StageError

FIXTURES = Path(__file__).parent / "fixtures" / "ogg"
SMALL = FIXTURES / "invalid_keypress.ogg"        # 5,353 B -> 2,642 B at -5
BIGGER = FIXTURES / "fallbackring.ogg"           # 14,611 B -> 12,085 B at -5

needs_balrogg = pytest.mark.skipif(not oggpack.available(),
                                   reason="the pinned balrogg is not installed")


def _py(code: str):
    """An ``_argv`` that runs a Python one-liner instead of balrogg, so the
    runner's cancel, timeout and verification behaviour can be tested without
    waiting on a real multi-minute encode."""
    def argv(exe, effort, mode, src, dst):
        return [sys.executable, "-c", code, str(src), str(dst)]
    return argv


COPY = ("import sys, shutil; shutil.copyfile(sys.argv[1], sys.argv[2])")
SLEEP = "import time; time.sleep(120)"


@pytest.fixture
def fake_tool(monkeypatch):
    """Pretend balrogg is installed, whatever this machine has."""
    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: Path(sys.executable))


# -- recognising the format ---------------------------------------------------

@pytest.mark.parametrize("head, expected", [
    (b"OggS\x00\x02" + b"\x00" * 10, True),
    (b"OggS", True),
    (b"RIFF\x00\x00\x00\x00WAVE", False),
    (b"", False),
    (b"Ogg", False),
    (b"\xff\xd8\xff\xe0" + b"\x00" * 12, False),
])
def test_looks_like_claims_only_ogg(head, expected):
    assert oggpack.looks_like(head) is expected


# -- the real tool --------------------------------------------------------------

@needs_balrogg
@pytest.mark.parametrize("path", [SMALL, BIGGER], ids=lambda p: p.name)
def test_a_real_ogg_packs_smaller_and_restores_byte_for_byte(path):
    raw = path.read_bytes()
    packed = oggpack.pack(raw)
    assert packed is not None and len(packed) < len(raw)
    assert oggpack.unpack(packed) == raw


@needs_balrogg
@pytest.mark.parametrize("effort", [1, 5, 9])
def test_every_effort_level_restores_byte_for_byte(effort):
    raw = SMALL.read_bytes()
    packed = oggpack.pack(raw, effort=effort)
    assert packed is not None
    assert oggpack.unpack(packed) == raw


@needs_balrogg
def test_the_effort_is_not_needed_to_restore():
    """The archive records the codec, not the effort, so a restore with
    nothing but the packed bytes must work."""
    raw = SMALL.read_bytes()
    packed = oggpack.pack(raw, effort=1)
    assert oggpack.unpack(packed) == raw


@needs_balrogg
def test_input_that_is_not_ogg_is_declined_not_guessed_at():
    assert oggpack.pack(b"OggS" + os.urandom(6000)) is None
    assert oggpack.pack(b"not an ogg file at all " * 400) is None


@needs_balrogg
def test_a_damaged_ogg_never_comes_back_different():
    """Whatever balrogg does with a corrupted stream, the contract is the
    same: ``None``, or bytes that restore the corrupted input exactly."""
    raw = bytearray(BIGGER.read_bytes())
    for offset in (40, 700, 4000, len(raw) - 9):
        damaged = bytearray(raw)
        damaged[offset] ^= 0xFF
        packed = oggpack.pack(bytes(damaged))
        if packed is not None:
            assert oggpack.unpack(packed) == bytes(damaged)
    truncated = bytes(raw[: len(raw) // 2])
    packed = oggpack.pack(truncated)
    if packed is not None:
        assert oggpack.unpack(packed) == truncated


@needs_balrogg
def test_unpacking_garbage_is_a_loud_error():
    with pytest.raises(RuntimeError):
        oggpack.unpack(b"this was never balrogg output" * 50)


@needs_balrogg
def test_the_size_gates_decline_without_running_anything(monkeypatch):
    called = []
    monkeypatch.setattr(oggpack, "_run", lambda *a, **k: called.append(a) or 0)
    assert oggpack.pack(b"OggS" + b"\x00" * 10) is None          # too small
    monkeypatch.setattr(oggpack, "MAX_SIZE", 100)
    assert oggpack.pack(SMALL.read_bytes()) is None              # too large
    assert called == []


# -- the verification gate: nothing the tool says is trusted --------------------

def test_a_tool_that_lies_about_the_round_trip_is_caught(fake_tool, monkeypatch):
    """Encode produces something smaller; decode produces something else. The
    exit codes are all 0. Only the comparison can tell, and it must."""
    def argv(exe, effort, mode, src, dst):
        if mode == "e":
            code = "import sys; open(sys.argv[2], 'wb').write(b'tiny')"
        else:
            code = "import sys; open(sys.argv[2], 'wb').write(b'NOT THE ORIGINAL')"
        return [sys.executable, "-c", code, str(src), str(dst)]

    monkeypatch.setattr(oggpack, "_argv", argv)
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None


def test_a_win_that_is_not_smaller_is_not_taken(fake_tool, monkeypatch):
    monkeypatch.setattr(oggpack, "_argv", _py(COPY))
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None


def test_an_exit_code_of_zero_with_no_output_is_not_a_success(fake_tool, monkeypatch):
    monkeypatch.setattr(oggpack, "_argv", _py("pass"))
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None


def test_a_crashing_tool_is_a_decline_not_an_exception(fake_tool, monkeypatch):
    monkeypatch.setattr(oggpack, "_argv", _py("import sys; sys.exit(4)"))
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None


# -- cancel and timeout ---------------------------------------------------------

def test_cancel_stops_a_long_encode_promptly_and_says_so(fake_tool, monkeypatch):
    """balrogg prints nothing while it works, so a cancel check that only runs
    when it prints (as `run_capture`'s does) would wait out the whole encode.
    This is the K6 lesson, applied to the first tool that needs it."""
    monkeypatch.setattr(oggpack, "_argv", _py(SLEEP))
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(StageError, match="cancelled"):
        oggpack.pack(b"OggS" + b"\x01" * 5000, cancel=cancel)
    assert time.monotonic() - started < 10


def test_a_cancel_already_set_never_starts_the_tool(fake_tool, monkeypatch):
    started = []
    monkeypatch.setattr(oggpack, "_argv",
                        lambda *a: started.append(a) or [sys.executable, "-c", "pass"])
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(StageError, match="cancelled"):
        oggpack.pack(b"OggS" + b"\x01" * 5000, cancel=cancel)
    assert started == []


def test_a_tool_that_outlives_its_budget_is_killed_and_declined(fake_tool, monkeypatch):
    monkeypatch.setattr(oggpack, "_argv", _py(SLEEP))
    monkeypatch.setattr(oggpack, "_encode_budget", lambda size, effort: 1.0)
    started = time.monotonic()
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None
    assert time.monotonic() - started < 15


def test_the_budget_scales_with_the_file_and_the_effort():
    small = oggpack._encode_budget(1_000_000, 5)
    assert oggpack._encode_budget(10_000_000, 5) > small
    assert oggpack._encode_budget(1_000_000, 9) > small
    # Measured: 36.3 MB at -9 took 306 s with the machine contended. The
    # budget has to clear that with room, or the biggest file is always
    # declined after a full wait.
    assert oggpack._encode_budget(36_290_277, 9) > 2 * 306


def test_no_temp_files_are_left_behind(fake_tool, monkeypatch, tmp_path):
    monkeypatch.setattr(oggpack.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(oggpack, "_argv", _py("import sys; sys.exit(1)"))
    oggpack.pack(b"OggS" + b"\x01" * 5000)
    assert list(tmp_path.iterdir()) == []


# -- availability ----------------------------------------------------------------

def test_without_the_tool_pack_declines_and_unpack_says_why(monkeypatch):
    monkeypatch.setattr(oggpack, "_balrogg_exe", lambda: None)
    assert oggpack.available() is False
    assert oggpack.pack(SMALL.read_bytes()) is None
    with pytest.raises(RuntimeError, match="balrogg"):
        oggpack.unpack(b"anything")


# -- effort by profile -------------------------------------------------------------

def test_effort_follows_the_profile():
    # Measured on three real files (19.3 MB), saving at each effort: -1 9.45%,
    # -4 11.24%, -5 11.55%, -9 11.59%, with -9 taking 3.3-4.7x as long as -5
    # in every batch. -5 buys all but 0.04 points of what -9 does, so only
    # Insane (the owner's "best for compression") pays for -9.
    assert oggpack.effort_for("fast") == 1
    assert oggpack.effort_for("normal") == 4
    assert oggpack.effort_for("extreme") == 5
    assert oggpack.effort_for("insane") == 9
    assert oggpack.effort_for("anything else") == oggpack.DEFAULT_EFFORT
    assert oggpack.effort_for(None) == oggpack.DEFAULT_EFFORT


# -- a decode is bounded by what the ledger declares ------------------------------

_GROW = ("import sys, time\n"
         "f = open(sys.argv[2], 'wb')\n"
         "for _ in range(4000):\n"
         "    f.write(b'x' * 1_000_000); f.flush(); time.sleep(0.02)\n")


def test_a_decode_that_outgrows_the_ledger_size_is_killed(fake_tool, monkeypatch):
    """The archive is attacker-supplied and balrogg's output size is not
    bounded by its input size. Without the limit a few hundred bytes of
    "packed" data could decode to however much disk there is."""
    monkeypatch.setattr(oggpack, "_argv", _py(_GROW))
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="limit"):
        oggpack.unpack(b"a few hundred bytes", limit=100_000)
    assert time.monotonic() - started < 15


def test_an_encode_whose_round_trip_grows_past_the_original_is_declined(fake_tool, monkeypatch):
    def argv(exe, effort, mode, src, dst):
        code = ("import sys; open(sys.argv[2], 'wb').write(b'tiny')" if mode == "e"
                else _GROW)
        return [sys.executable, "-c", code, str(src), str(dst)]

    monkeypatch.setattr(oggpack, "_argv", argv)
    assert oggpack.pack(b"OggS" + b"\x01" * 5000) is None
