"""B4 — the WAV specialist, and the false statement it replaces.

Measured on 4 real WAVs from this machine (335,536,808 B) before any of this
was written:

    store (what shipped)                  0.00%
    7z mx9, default filters               9.45%
    7z mx9 -mf=Delta:4                    3.07%   <- the filter HURTS
    7z mx9 -mf=Delta:2                    1.67%
    flac -8 --keep-foreign-metadata      43.15%   <- 4/4 byte-identical

So this is the first specialist in the project to actually beat the existing
route: B3's `oxipng`, B5's `qpdf` and K4's wide zstd window all lost to
`precomp -> 7z` on real files. The reason B4 is different is structural rather
than lucky - a PDF or a docx is *already deflate output* one layer down, which
is what Precomp reaches, whereas a WAV is **genuinely uncompressed PCM** and
no general-purpose compressor models audio.

Two findings shaped the implementation.

**`.wav` was being stored, and the reason shown to the user was false.**
`Category.AUDIO` is in `planner._MEDIA`, so every WAV got "media file: already
compressed by its codec; stored losslessly so quality is untouched". A WAV has
no codec. 5.07 GiB of WAV on this machine compressed by exactly nothing while
being told it was already optimal.

**Plain `flac -8` is NOT byte-lossless on a WAV *file*.** It is lossless about
*audio*: measured on a real track, the `data` chunk came back identical
(`0x031899f0` both sides) but the file was **458,114 bytes smaller**, because
the original carries non-audio RIFF chunks that `flac -d` silently drops.
`--keep-foreign-metadata` preserves them and restores the file exactly, at a
cost of 458,198 bytes - the chunks plus framing, which is the whole
difference. Without that flag B4 would have been another Phase C item.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from excmp import flacaudio


def _wav(path: Path, *, seconds: float = 0.25, trailing: bytes = b"") -> Path:
    """A real 16-bit stereo 44.1 kHz WAV, optionally with a foreign chunk
    after the audio - which is what the real corpus files have and what plain
    `flac -d` throws away."""
    rate, channels, bits = 44100, 2, 16
    frames = int(rate * seconds)
    samples = bytearray()
    for n in range(frames):
        # A cheap two-tone so it is compressible like audio rather than noise.
        left = int(12000 * ((n % 91) / 91.0 - 0.5))
        right = int(9000 * ((n % 57) / 57.0 - 0.5))
        samples += struct.pack("<hh", left, right)
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * block, block, bits)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(samples)) + bytes(samples)
            + trailing)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


needs_flac = pytest.mark.skipif(
    not flacaudio.available(),
    reason="needs the flac binary (E1: tools/bin/flac/<version>/)")


def test_a_wav_is_recognised_and_a_random_file_is_not(tmp_path):
    wav = _wav(tmp_path / "a.wav")
    assert flacaudio.looks_like_wav(wav.read_bytes()[:64]) is True
    assert flacaudio.looks_like_wav(b"not a wav at all") is False
    # A RIFF container that is not WAVE - an AVI - must not be claimed.
    assert flacaudio.looks_like_wav(b"RIFF\x00\x00\x00\x00AVI LIST") is False


@needs_flac
def test_packing_a_wav_round_trips_byte_for_byte(tmp_path):
    """The contract: `pack` returns bytes it has **already restored once**, or
    None. This is the same guarantee `excmp/jpeg.py` makes for lepton, and for
    the same reason - a file the codec would mishandle has to be caught now,
    while storing it raw is still free."""
    raw = _wav(tmp_path / "a.wav").read_bytes()
    packed = flacaudio.pack(raw)
    assert packed is not None, "a plain 16-bit stereo WAV should pack"
    assert len(packed) < len(raw)
    assert flacaudio.unpack(packed) == raw


@needs_flac
def test_a_wav_with_foreign_chunks_still_round_trips_exactly(tmp_path):
    """The finding that made `--keep-foreign-metadata` mandatory.

    Plain `flac -8` then `flac -d` reproduces the *audio* but not the *file*:
    on a real track it came back 458,114 bytes short because the trailing RIFF
    chunks were dropped. A ledger records the file's SHA-256, so audio-lossless
    is not good enough.
    """
    trailing = b"LIST" + struct.pack("<I", 40) + b"INFO" + b"x" * 36
    raw = _wav(tmp_path / "b.wav", trailing=trailing).read_bytes()
    assert trailing in raw

    packed = flacaudio.pack(raw)
    assert packed is not None
    restored = flacaudio.unpack(packed)
    assert restored == raw
    assert trailing in restored, "the foreign chunk was dropped"


@needs_flac
def test_something_flac_cannot_handle_is_declined_not_raised(tmp_path):
    """B2's lesson, applied here: lepton refused 14 of 37 real photos, so a
    specialist has to *decline* rather than fail. 8-bit and 32-bit-float WAVs,
    exotic channel layouts and truncated files all exist in the wild."""
    broken = b"RIFF" + struct.pack("<I", 32) + b"WAVEfmt " + b"\x00" * 24
    assert flacaudio.pack(broken) is None

    # Truncated mid-audio.
    raw = _wav(tmp_path / "c.wav").read_bytes()
    assert flacaudio.pack(raw[: len(raw) // 3]) is None


@needs_flac
def test_a_tiny_wav_is_not_worth_packing(tmp_path):
    """Below the floor the FLAC container's own header costs more than the
    audio saves, and every packed entry costs a subprocess at restore time."""
    tiny = _wav(tmp_path / "t.wav", seconds=0.001).read_bytes()
    assert len(tiny) < flacaudio.MIN_SIZE
    assert flacaudio.pack(tiny) is None


def test_pack_is_a_no_op_when_flac_is_absent(monkeypatch, tmp_path):
    """Absence of the tool is normal and never an error - the WAV is stored
    raw, exactly as it was before B4. This is the detected-only pattern the
    roadmap specifies for every optional specialist."""
    monkeypatch.setattr(flacaudio, "_flac_exe", lambda: None)
    assert flacaudio.available() is False
    assert flacaudio.pack(_wav(tmp_path / "a.wav").read_bytes()) is None


# --------------------------------------------------------------------------
# the routing change, and the sentence it replaces
# --------------------------------------------------------------------------

def test_a_wav_is_no_longer_told_it_is_already_compressed(tmp_path):
    """The false statement. `Category.AUDIO` is in `_MEDIA`, so a WAV was
    stored and explained as "already compressed by its codec" - a WAV has no
    codec. This is the same exception `_DEFLATE_MEDIA` already makes for PNG,
    whose entropy is deflate output rather than real randomness; a WAV's
    entropy is real (7.7-7.9 bits/byte on real music) but the file is
    uncompressed, which no entropy probe can tell you.
    """
    from excmp.analyzer import analyze_file
    from excmp.planner import store_reason

    info = analyze_file(_wav(tmp_path / "a.wav", seconds=1.0))
    reason = store_reason(info)
    if reason is not None:
        assert "already compressed by its codec" not in reason, reason


@needs_flac
def test_a_wav_survives_a_real_compress_and_restore(tmp_path):
    """End to end through the engine, which is what actually has to hold: the
    ledger records the WAV's own SHA-256, so a restore that reproduced only
    the audio would fail D9 and refuse to publish."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    _wav(src / "one.wav", seconds=0.5,
         trailing=b"LIST" + struct.pack("<I", 20) + b"INFO" + b"y" * 16)
    _wav(src / "two.wav", seconds=0.3)
    (src / "notes.txt").write_text("something to pipeline\n" * 300,
                                   encoding="utf-8")
    before = {p.name: p.read_bytes() for p in src.glob("*")}

    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    out = tmp_path / "restored"
    result = engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))

    assert result.verified == 3
    for name, data in before.items():
        assert (out / "src" / name).read_bytes() == data, name


@needs_flac
def test_the_archive_really_holds_flac_not_a_raw_wav(tmp_path):
    """The end-to-end test above passes whether or not the WAV is packed,
    because storing it raw also round-trips. This is the one that fails if the
    codec is not wired in: the ledger must say `codec: flac` and the member in
    the container must be materially smaller than the WAV it restores to."""
    import json
    import zipfile

    from excmp import engine
    from excmp.manifest import MANIFEST_NAME
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    wav = _wav(src / "song.wav", seconds=1.0)
    raw_size = wav.stat().st_size

    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))

    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        member = zf.getinfo("stored/src/song.wav")
    entry = manifest["inputs"]["src/song.wav"]

    assert entry.get("codec") == "flac", entry
    assert entry["size"] == raw_size, "the ledger records the ORIGINAL size"
    assert member.file_size < raw_size * 0.9, (
        f"the stored member is {member.file_size} for a {raw_size}-byte WAV - "
        f"it does not look packed")


@needs_flac
def test_two_identical_wavs_still_deduplicate(tmp_path):
    """G9 dedup and B4 packing meet on the same entry. The packing loop skips
    anything already carrying a `same_as`, so the duplicate must restore from
    the *packed* bytes of the first - the bug B2 hit when two identical photos
    in one folder failed the whole compress."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    _wav(src / "a.wav", seconds=0.5)
    (src / "b.wav").write_bytes((src / "a.wav").read_bytes())
    before = (src / "a.wav").read_bytes()

    archive = tmp_path / "out.excmp"
    engine.compress([src], archive, Profile.NORMAL,
                    StageContext(temp_dir=tmp_path / "t"))
    out = tmp_path / "restored"
    result = engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))

    assert result.verified == 2
    assert (out / "src" / "a.wav").read_bytes() == before
    assert (out / "src" / "b.wav").read_bytes() == before
