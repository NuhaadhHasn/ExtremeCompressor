"""F1 — password protection, and why not `7z -p`.

`7z -p` looks like the obvious answer and is source-proven to be a bad one
(research/19 §1, `7zAes.cpp:232-238`): the salt lines are **commented out**, so
identical passwords produce identical keys and a global key cache makes that
worse; it is AES-256-**CBC** with CRC32-only integrity, so the ciphertext is
malleable and nothing authenticates it; and the KDF is SHA-256 iterated 2^19
over UTF-16LE, which is exactly the shape a GPU likes. On top of all that it
would only cover the 7z payload stage, leaving `manifest.json` — every filename
and every hash — and the whole `stored/` tree in plaintext.

So we wrap the finished container instead:

- **Argon2id** (RFC 9106's second recommendation: m=64 MiB, t=3, p=4) — memory-
  hard, which is what actually costs an attacker with a GPU farm.
- **AES-256-GCM in 4 MiB chunks** with age-style STREAM nonces: an 11-byte
  counter plus a final-chunk flag. The counter stops chunk reordering, the flag
  stops truncation, and chunking dodges GCM's ~64 GiB single-message limit.
- **The header is AAD for every chunk**, so the parameters cannot be swapped.
- **An HKDF check value** in the header, so "wrong password" and "this file is
  damaged" are different sentences. A user who mistypes needs to know that;
  telling them their archive is corrupt would be a lie that costs them the
  archive.

Every test below is about one of those properties failing loudly rather than
quietly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from excmp.crypto import (CHUNK_SIZE, MAGIC, Argon2Params,
                          CorruptArchiveError, WrongPasswordError,
                          decrypt_file, encrypt_file, is_encrypted)

#: Deliberately feeble, and only here. Argon2id at the shipped 64 MiB takes
#: most of a second per derivation by design; paying that on every case below
#: would make this file slow enough to get skipped, which would cost more
#: security than it buys. `test_the_kdf_is_memory_hard_at_the_documented_setting`
#: is what pins the real numbers.
FAST = Argon2Params(memory_kib=8, time_cost=1, parallelism=1)


def _plain(tmp_path: Path, size: int, name: str = "a.excmp") -> Path:
    p = tmp_path / name
    p.write_bytes(os.urandom(size) if size else b"")
    return p


def _roundtrip(tmp_path: Path, data: bytes, password: str = "correct horse") -> bytes:
    src = tmp_path / "in.bin"
    src.write_bytes(data)
    enc = tmp_path / "in.bin.enc"
    dec = tmp_path / "out.bin"
    encrypt_file(src, enc, password, FAST)
    decrypt_file(enc, dec, password)
    return dec.read_bytes()


# ---------------------------------------------------------------------------
# It round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size", [
    pytest.param(0, id="empty"),
    pytest.param(1, id="one-byte"),
    pytest.param(1000, id="small"),
    pytest.param(CHUNK_SIZE - 1, id="just-under-one-chunk"),
    pytest.param(CHUNK_SIZE, id="exactly-one-chunk"),
    pytest.param(CHUNK_SIZE + 1, id="just-over-one-chunk"),
    pytest.param(CHUNK_SIZE * 2 + 12345, id="several-chunks"),
])
def test_data_survives_a_roundtrip(tmp_path, size):
    """The chunk boundaries are where a streaming cipher goes wrong, so they
    are what the parametrisation targets."""
    data = os.urandom(size)
    assert _roundtrip(tmp_path, data) == data


def test_a_unicode_password_works(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"secret stuff")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "пароль-日本語-🎉", FAST)
    decrypt_file(enc, dec, "пароль-日本語-🎉")
    assert dec.read_bytes() == b"secret stuff"


# ---------------------------------------------------------------------------
# The same input twice must not look the same
# ---------------------------------------------------------------------------

def test_encrypting_twice_gives_different_bytes(tmp_path):
    """The bug 7-Zip actually has: with the salt commented out, identical
    passwords give identical keys, so identical plaintext gives identical
    ciphertext and an attacker learns that two archives match."""
    src = tmp_path / "in.bin"
    src.write_bytes(b"identical content")
    a, b = tmp_path / "a", tmp_path / "b"
    encrypt_file(src, a, "same password", FAST)
    encrypt_file(src, b, "same password", FAST)
    assert a.read_bytes() != b.read_bytes()


def test_the_plaintext_does_not_appear_in_the_output(tmp_path):
    src = tmp_path / "in.bin"
    marker = b"TOP-SECRET-MARKER-STRING"
    src.write_bytes(b"x" * 1000 + marker + b"y" * 1000)
    enc = tmp_path / "e"
    encrypt_file(src, enc, "pw", FAST)
    assert marker not in enc.read_bytes()


# ---------------------------------------------------------------------------
# Wrong password is not the same thing as damage
# ---------------------------------------------------------------------------

def test_a_wrong_password_says_so(tmp_path):
    """The distinction that matters most to a real person. Telling someone who
    mistyped that their archive is corrupt would make them delete it."""
    src = tmp_path / "in.bin"
    src.write_bytes(b"content")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "the right one", FAST)
    with pytest.raises(WrongPasswordError):
        decrypt_file(enc, dec, "the wrong one")


def test_a_wrong_password_writes_no_output(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"content")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "right", FAST)
    with pytest.raises(WrongPasswordError):
        decrypt_file(enc, dec, "wrong")
    assert not dec.exists(), "a failed decrypt left a partial file behind"


def test_damaged_ciphertext_is_reported_as_damage(tmp_path):
    """The other half of the same distinction: the password was right, the
    file is broken, and saying "wrong password" would send the user hunting
    for a password that works fine."""
    src = tmp_path / "in.bin"
    src.write_bytes(os.urandom(50_000))
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)

    raw = bytearray(enc.read_bytes())
    raw[-100] ^= 0xFF               # flip a bit well inside the ciphertext
    enc.write_bytes(bytes(raw))

    with pytest.raises(CorruptArchiveError):
        decrypt_file(enc, dec, "pw")


# ---------------------------------------------------------------------------
# Tampering, in each of the shapes GCM+STREAM is supposed to stop
# ---------------------------------------------------------------------------

def test_truncation_is_detected(tmp_path):
    """Plain per-chunk AEAD does not catch this: every remaining chunk is
    perfectly valid. The final-chunk flag in the nonce is what makes a
    truncated file fail."""
    src = tmp_path / "in.bin"
    src.write_bytes(os.urandom(CHUNK_SIZE * 2 + 5000))
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)

    raw = enc.read_bytes()
    enc.write_bytes(raw[:len(raw) - CHUNK_SIZE])     # drop the last chunk

    with pytest.raises(CorruptArchiveError):
        decrypt_file(enc, dec, "pw")


def test_header_tampering_is_detected(tmp_path):
    """The header is AAD, so editing the stored Argon2 parameters - to make a
    brute-force cheaper, say - breaks every chunk's tag."""
    src = tmp_path / "in.bin"
    src.write_bytes(b"content" * 100)
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)

    raw = bytearray(enc.read_bytes())
    raw[len(MAGIC) + 20] ^= 0x01     # somewhere inside the parameter block
    enc.write_bytes(bytes(raw))

    with pytest.raises((CorruptArchiveError, WrongPasswordError)):
        decrypt_file(enc, dec, "pw")


def test_a_swapped_chunk_is_detected(tmp_path):
    """The counter in the nonce is what makes chunk N fail to decrypt in
    position M."""
    src = tmp_path / "in.bin"
    src.write_bytes(os.urandom(CHUNK_SIZE * 3))
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)

    raw = bytearray(enc.read_bytes())
    header_len = len(raw) - (CHUNK_SIZE + 16) * 3
    stride = CHUNK_SIZE + 16
    first = raw[header_len:header_len + stride]
    second = raw[header_len + stride:header_len + stride * 2]
    raw[header_len:header_len + stride] = second
    raw[header_len + stride:header_len + stride * 2] = first
    enc.write_bytes(bytes(raw))

    with pytest.raises(CorruptArchiveError):
        decrypt_file(enc, dec, "pw")


def test_a_file_that_is_not_ours_is_refused_clearly(tmp_path):
    junk = tmp_path / "junk.enc"
    junk.write_bytes(b"this is not an encrypted archive at all")
    with pytest.raises(CorruptArchiveError):
        decrypt_file(junk, tmp_path / "out", "pw")


# ---------------------------------------------------------------------------
# Recognising one
# ---------------------------------------------------------------------------

def test_is_encrypted_recognises_our_own(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"x" * 100)
    enc = tmp_path / "e"
    encrypt_file(src, enc, "pw", FAST)
    assert is_encrypted(enc)
    assert not is_encrypted(src)


def test_is_encrypted_on_a_tiny_file_does_not_explode(tmp_path):
    tiny = tmp_path / "t"
    tiny.write_bytes(b"ab")
    assert not is_encrypted(tiny)


def test_is_encrypted_on_a_missing_file_is_false(tmp_path):
    assert not is_encrypted(tmp_path / "nope")


# ---------------------------------------------------------------------------
# The parameters we actually chose
# ---------------------------------------------------------------------------

def test_the_kdf_is_memory_hard_at_the_documented_setting(tmp_path):
    """m=64 MiB is the point of the whole exercise: it is what makes a GPU
    farm expensive, and it is the number an attacker would most like us to
    have quietly lowered."""
    from excmp.crypto import ARGON2_MEMORY_KIB, ARGON2_PARALLELISM, ARGON2_TIME

    assert ARGON2_MEMORY_KIB >= 64 * 1024
    assert ARGON2_TIME >= 3
    assert ARGON2_PARALLELISM >= 1


def test_the_salt_is_long_enough_and_actually_random(tmp_path):
    from excmp.crypto import SALT_BYTES

    assert SALT_BYTES >= 16
    src = tmp_path / "in.bin"
    src.write_bytes(b"x")
    salts = set()
    for i in range(5):
        target = tmp_path / f"e{i}"
        encrypt_file(src, target, "pw", FAST)
        salts.add(bytes(target.read_bytes()[len(MAGIC) + 1:
                                            len(MAGIC) + 1 + SALT_BYTES]))
    assert len(salts) == 5, "salts repeated across encryptions"


# ---------------------------------------------------------------------------
# A hostile header must not be able to make us do work
# ---------------------------------------------------------------------------

def _rewrite_kdf(enc: Path, *, m_kib: int | None = None,
                 t: int | None = None, p: int | None = None) -> None:
    """Rewrite the KDF parameters in place, as an attacker would."""
    import struct as _s

    from excmp.crypto import _HEADER
    raw = bytearray(enc.read_bytes())
    fields = list(_HEADER.unpack(bytes(raw[:_HEADER.size])))
    if m_kib is not None:
        fields[3] = m_kib
    if t is not None:
        fields[4] = t
    if p is not None:
        fields[5] = p
    raw[:_HEADER.size] = _HEADER.pack(*fields)
    enc.write_bytes(bytes(raw))


def test_an_absurd_memory_cost_is_refused_not_attempted(tmp_path):
    """A denial-of-service found by accident, then pinned deliberately.

    `test_header_tampering_is_detected` flipped one bit that happened to land
    in the top byte of `m_kib`. 8 KiB became 16 GiB, `decrypt_file` dutifully
    asked Argon2 for it, and that single test took **19 minutes**. A crafted
    header can ask for 4 TiB just as cheaply.

    "The header is AAD" does not help here: the parameters are needed to derive
    the key that would check the tag, so they are consumed *before* anything is
    authenticated. Bounds are the only defence, and this asserts we refuse
    instead of allocating.
    """
    src = tmp_path / "in.bin"
    src.write_bytes(b"content")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)

    # The largest the 4-byte field can hold: 4,294,967,295 KiB = 4 TiB.
    _rewrite_kdf(enc, m_kib=0xFFFFFFFF)
    import time
    t0 = time.perf_counter()
    with pytest.raises(CorruptArchiveError, match="memory"):
        decrypt_file(enc, dec, "pw")
    assert time.perf_counter() - t0 < 5, "it tried to honour the request"
    assert not dec.exists()


def test_an_absurd_pass_count_is_refused(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"content")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)
    _rewrite_kdf(enc, t=2_000_000)
    with pytest.raises(CorruptArchiveError, match="passes"):
        decrypt_file(enc, dec, "pw")


def test_an_absurd_lane_count_is_refused(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"content")
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(src, enc, "pw", FAST)
    _rewrite_kdf(enc, p=250)
    with pytest.raises(CorruptArchiveError, match="lanes"):
        decrypt_file(enc, dec, "pw")


def test_the_real_parameters_are_still_inside_the_bounds(tmp_path):
    """The bounds must not have been drawn so tight that our own shipped
    settings would be rejected by a future reader."""
    from excmp.crypto import (_MAX_MEMORY_KIB, _MAX_PARALLELISM, _MAX_TIME_COST,
                              _MIN_MEMORY_KIB, DEFAULT_PARAMS)

    assert _MIN_MEMORY_KIB <= DEFAULT_PARAMS.memory_kib <= _MAX_MEMORY_KIB
    assert 1 <= DEFAULT_PARAMS.time_cost <= _MAX_TIME_COST
    assert 1 <= DEFAULT_PARAMS.parallelism <= _MAX_PARALLELISM
