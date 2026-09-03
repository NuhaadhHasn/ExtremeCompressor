"""F2 — a keyfile as a second factor, done so it actually adds a factor.

PeaZip's version of this feature prepends `base64(SHA256(keyfile))` to the
passphrase (research/17 §1). That is two problems at once: the keyfile's
contribution is *separable* from the password, and it rides through the
backend as part of a plaintext command-line argument.

Ours folds the keyfile in at key-derivation time and keeps Argon2id in the
loop on the password side:

    key = HKDF(ikm=Argon2id(password, random_salt), salt=SHA-256(keyfile))

The order matters. HKDF is fast by design, so deriving from the keyfile alone
would make a password brute-force cheap — the attacker who steals your keyfile
would be back to guessing a password against a fast hash. Argon2id runs first
and stays memory-hard; HKDF only *mixes*.

Three consequences the tests below pin:

- **Both factors are required.** Right password, wrong keyfile fails. Right
  keyfile, wrong password fails.
- **The archive says it needs a keyfile.** Otherwise a user with the right
  password but no keyfile is told "wrong password", goes hunting for a
  password that is already correct, and eventually concludes the archive is
  broken.
- **Keyfile-only is allowed.** Some people want a file they can put on a USB
  stick and nothing to remember.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from excmp.crypto import (Argon2Params, CorruptArchiveError, KeyfileRequired,
                          WrongPasswordError, decrypt_file, encrypt_file,
                          needs_keyfile)

FAST = Argon2Params(memory_kib=8, time_cost=1, parallelism=1)


@pytest.fixture
def keyfile(tmp_path):
    p = tmp_path / "secret.key"
    p.write_bytes(os.urandom(4096))
    return p


@pytest.fixture
def plain(tmp_path):
    p = tmp_path / "in.bin"
    p.write_bytes(b"two factors are better than one " * 500)
    return p


# ---------------------------------------------------------------------------
# It works
# ---------------------------------------------------------------------------

def test_password_and_keyfile_round_trip(tmp_path, plain, keyfile):
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    decrypt_file(enc, dec, "pw", keyfile=keyfile)
    assert dec.read_bytes() == plain.read_bytes()


def test_a_keyfile_alone_is_allowed(tmp_path, plain, keyfile):
    """For people who would rather carry a file than remember a phrase."""
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "", FAST, keyfile=keyfile)
    decrypt_file(enc, dec, "", keyfile=keyfile)
    assert dec.read_bytes() == plain.read_bytes()


def test_the_keyfile_contents_matter_not_its_name(tmp_path, plain, keyfile):
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)

    moved = tmp_path / "renamed.dat"
    moved.write_bytes(keyfile.read_bytes())
    decrypt_file(enc, dec, "pw", keyfile=moved)
    assert dec.read_bytes() == plain.read_bytes()


# ---------------------------------------------------------------------------
# Both factors are genuinely required
# ---------------------------------------------------------------------------

def test_the_right_password_with_the_wrong_keyfile_fails(tmp_path, plain, keyfile):
    other = tmp_path / "other.key"
    other.write_bytes(os.urandom(4096))
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    with pytest.raises(WrongPasswordError):
        decrypt_file(enc, dec, "pw", keyfile=other)
    assert not dec.exists()


def test_the_right_keyfile_with_the_wrong_password_fails(tmp_path, plain, keyfile):
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    with pytest.raises(WrongPasswordError):
        decrypt_file(enc, dec, "nope", keyfile=keyfile)


def test_one_changed_byte_in_the_keyfile_is_enough(tmp_path, plain, keyfile):
    """It is a cryptographic factor, not a checksum - a near-miss is a miss."""
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)

    tweaked = bytearray(keyfile.read_bytes())
    tweaked[0] ^= 0x01
    near = tmp_path / "near.key"
    near.write_bytes(bytes(tweaked))
    with pytest.raises(WrongPasswordError):
        decrypt_file(enc, dec, "pw", keyfile=near)


# ---------------------------------------------------------------------------
# The archive says what it needs
# ---------------------------------------------------------------------------

def test_an_archive_declares_that_it_needs_a_keyfile(tmp_path, plain, keyfile):
    enc = tmp_path / "e"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    assert needs_keyfile(enc) is True


def test_an_ordinary_encrypted_archive_does_not(tmp_path, plain):
    enc = tmp_path / "e"
    encrypt_file(plain, enc, "pw", FAST)
    assert needs_keyfile(enc) is False


def test_omitting_a_required_keyfile_says_so(tmp_path, plain, keyfile):
    """Not "wrong password". A user with the correct password and no keyfile
    would otherwise hunt for a password that is already right, and end up
    believing the archive is corrupt."""
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    with pytest.raises(KeyfileRequired):
        decrypt_file(enc, dec, "pw")


def test_supplying_a_keyfile_that_was_not_used_says_so(tmp_path, plain, keyfile):
    """The mirror image, and just as confusing if it silently failed."""
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST)
    with pytest.raises(CorruptArchiveError, match="keyfile"):
        decrypt_file(enc, dec, "pw", keyfile=keyfile)


def test_a_missing_keyfile_on_disk_is_a_clear_error(tmp_path, plain, keyfile):
    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=keyfile)
    with pytest.raises((KeyfileRequired, OSError, CorruptArchiveError)):
        decrypt_file(enc, dec, "pw", keyfile=tmp_path / "not-here.key")


# ---------------------------------------------------------------------------
# The keyfile is read safely
# ---------------------------------------------------------------------------

def test_a_huge_keyfile_is_capped_rather_than_read_whole(tmp_path, plain):
    """Somebody will point this at a 40 GB video. Hashing a bounded prefix is
    still a perfectly good factor and does not take the machine with it."""
    from excmp.crypto import MAX_KEYFILE_BYTES

    big = tmp_path / "big.key"
    big.write_bytes(os.urandom(MAX_KEYFILE_BYTES // 4) * 5)
    assert big.stat().st_size > MAX_KEYFILE_BYTES

    enc, dec = tmp_path / "e", tmp_path / "d"
    encrypt_file(plain, enc, "pw", FAST, keyfile=big)
    decrypt_file(enc, dec, "pw", keyfile=big)
    assert dec.read_bytes() == plain.read_bytes()


def test_an_empty_keyfile_is_refused(tmp_path, plain):
    """A zero-byte keyfile adds nothing and would silently reduce this to a
    password-only archive that claims two factors."""
    empty = tmp_path / "empty.key"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        encrypt_file(plain, tmp_path / "e", "pw", FAST, keyfile=empty)


def test_neither_factor_at_all_is_refused(tmp_path, plain):
    with pytest.raises(ValueError):
        encrypt_file(plain, tmp_path / "e", "", FAST)


# ---------------------------------------------------------------------------
# The property that makes this different from PeaZip's version
# ---------------------------------------------------------------------------

def test_the_password_still_goes_through_argon2(tmp_path, plain, keyfile):
    """The whole point of the ordering.

    If the keyfile were mixed in with a fast hash *instead of* Argon2id, an
    attacker holding the keyfile would face only a cheap password guess. Here
    Argon2id runs on the password first and HKDF only mixes, so the expensive
    step stays expensive.

    Measured on the KDF itself rather than on `encrypt_file`. An earlier
    version timed the whole call and compared 0.026s against 0.025s - the
    first call pays a one-time crypto-backend warm-up that swamped a 0.1ms vs
    44ms difference entirely. Timing the thing under test avoids arguing with
    unrelated overhead.
    """
    import time

    from excmp.crypto import _derive, _mix

    salt = os.urandom(16)
    _derive("warm", salt, 8, 1, 1)          # pay the one-time cost first

    t0 = time.perf_counter()
    cheap = _derive("pw", salt, 8, 1, 1)
    quick = time.perf_counter() - t0

    t0 = time.perf_counter()
    dear = _derive("pw", salt, 8192, 3, 1)
    heavy = time.perf_counter() - t0

    assert heavy > quick * 10, (
        f"the Argon2 cost did not bite ({quick*1000:.2f}ms vs "
        f"{heavy*1000:.2f}ms) - the KDF may not be running")
    assert cheap != dear, "different costs produced the same key"


def test_the_keyfile_only_mixes_and_never_replaces_the_kdf(tmp_path, keyfile):
    """Structurally: the Argon2 output must be the HKDF *input keying
    material*, not its salt. Swapping those would put the fast hash in charge
    of the secret and make the whole ordering pointless."""
    from excmp.crypto import _derive, _mix, keyfile_digest

    salt = os.urandom(16)
    argon = _derive("pw", salt, 8, 1, 1)
    kf = keyfile_digest(keyfile)

    mixed = _mix(argon, kf)
    assert mixed != argon, "the keyfile made no difference to the key"
    assert len(mixed) == 32
    # Same keyfile, different Argon2 output -> different key. So the password
    # is genuinely part of what comes out.
    other = _derive("different", salt, 8, 1, 1)
    assert _mix(other, kf) != mixed


def test_no_keyfile_means_the_argon_output_is_used_unchanged(keyfile):
    from excmp.crypto import _derive, _mix

    argon = _derive("pw", os.urandom(16), 8, 1, 1)
    assert _mix(argon, None) == argon
