"""F1 — password protection for the whole container.

**Why not `7z -p`.** It is source-proven weak (research/19 §1,
`7zAes.cpp:232-238`): the salt lines are literally commented out, so identical
passwords produce identical keys — and a global key cache makes that worse. It
is AES-256-**CBC** with CRC32-only integrity, so ciphertext is malleable and
nothing authenticates it. The KDF is SHA-256 iterated 2^19 over UTF-16LE,
which is precisely the shape a GPU is good at. And it would only cover the 7z
payload stage, leaving `manifest.json` — every filename and every hash — plus
the whole `stored/` tree sitting in plaintext. Even `-mhe=on` leaks archive
size, header size and KDF parameters.

So this wraps the *finished container*, which encrypts everything including
the ledger, and is the full `-mhe=on` equivalent **plus** the authentication
7-Zip does not have.

## The format

```
magic "EXCMPENC" (8) | version (1) | salt (16) | m_kib (4) | t (4) | p (1)
                     | chunk_size (4) | check (16)          <- all of this is AAD
then, repeated:      | ciphertext chunk (<= chunk_size) + GCM tag (16)
```

**Nonces are age-style STREAM**: an 11-byte big-endian counter plus one byte
that is 1 only for the final chunk. The counter means a chunk cannot be moved;
the flag means the file cannot be truncated — without it every remaining chunk
after a truncation is still perfectly valid and plain per-chunk AEAD notices
nothing. Chunking also dodges GCM's ~64 GiB single-message ceiling.

**The header is AAD for every chunk**, so the stored Argon2 parameters cannot
be edited down to make a brute-force cheaper.

**The check value** is HKDF output, stored so a wrong password can be told
apart from a damaged file. That distinction is not a nicety: telling somebody
who mistyped that their archive is corrupt is how archives get deleted. It
gives an attacker nothing they did not already have — they could always test a
guess against chunk 0's tag — and Argon2id is what actually makes guessing
expensive. (PeaZip's 16-bit `PW_Ver` was a genuine oracle because it was
*small* enough to collide; 16 bytes of HKDF is not.)
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import NamedTuple

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"EXCMPENC"
VERSION = 1

SALT_BYTES = 16
CHECK_BYTES = 16
TAG_BYTES = 16
NONCE_BYTES = 12
COUNTER_BYTES = NONCE_BYTES - 1

#: 4 MiB. Small enough that a failed chunk costs little to re-read, large
#: enough that the per-chunk tag overhead is negligible (16 bytes in 4 MiB).
CHUNK_SIZE = 4 << 20

#: RFC 9106's *second* recommendation, which is the one meant for memory-
#: constrained settings. 64 MiB is affordable on the 16 GB target and is the
#: number that actually costs a GPU attacker.
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_TIME = 3
ARGON2_PARALLELISM = 4

#: Bounds on the KDF parameters we will honour *from a file*.
#:
#: These are attacker-controlled on a hostile archive: the header carries them,
#: and they are needed to derive the key that would authenticate the header, so
#: "the header is AAD" does not protect this step. Without bounds, one flipped
#: bit in `m_kib` asks Argon2 for 16 GiB (measured: a 19-minute hang) and a
#: crafted one can ask for 4 TiB.
#:
#: The ceiling is generous enough to accept anything a future version might
#: reasonably choose, and far below what would wedge the 16 GB target machine.
_MIN_MEMORY_KIB = 8            # argon2's own floor
_MAX_MEMORY_KIB = 1 << 20      # 1 GiB
_MAX_TIME_COST = 20
_MAX_PARALLELISM = 16

_HEADER = struct.Struct(f"<{len(MAGIC)}sB{SALT_BYTES}sIIBI{CHECK_BYTES}s")


class Argon2Params(NamedTuple):
    """The KDF cost, as a value so it can be dialled down in tests.

    Production uses :data:`DEFAULT_PARAMS`. A test suite that paid the real
    64 MiB cost on every case would take minutes and would get skipped, which
    is a worse outcome for security than fast tests plus one assertion that
    the shipped numbers are the strong ones (`test_the_kdf_is_memory_hard...`).

    Every parameter is written into the header, so an archive encrypted with
    any of them decrypts without being told which were used.
    """

    memory_kib: int = ARGON2_MEMORY_KIB
    time_cost: int = ARGON2_TIME
    parallelism: int = ARGON2_PARALLELISM


DEFAULT_PARAMS = Argon2Params()


class CryptoError(RuntimeError):
    """Base for everything this module refuses to do."""


class WrongPasswordError(CryptoError):
    """The password did not match. The file itself may be perfectly fine."""


class CorruptArchiveError(CryptoError):
    """The password was right (or unreadable) and the bytes are damaged."""


def _derive(password: str, salt: bytes, m_kib: int, t: int, p: int) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=t,
        memory_cost=m_kib,
        parallelism=p,
        hash_len=32,                 # AES-256
        type=Type.ID,                # Argon2id
    )


def _check_value(key: bytes) -> bytes:
    """A value derived from the key but useless for decrypting anything."""
    return HKDF(algorithm=hashes.SHA256(), length=CHECK_BYTES,
                salt=None, info=b"excmp-password-check").derive(key)


def _nonce(index: int, final: bool) -> bytes:
    return index.to_bytes(COUNTER_BYTES, "big") + (b"\x01" if final else b"\x00")


def is_encrypted(path: Path) -> bool:
    """Cheap magic-byte check. Never raises — a missing or tiny file is just
    'no'."""
    try:
        with Path(path).open("rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt_file(src: Path, dst: Path, password: str,
                 params: Argon2Params = DEFAULT_PARAMS) -> Path:
    """Encrypt ``src`` to ``dst``. The source is left untouched."""
    src, dst = Path(src), Path(dst)
    salt = os.urandom(SALT_BYTES)
    key = _derive(password, salt, params.memory_kib, params.time_cost,
                  params.parallelism)
    header = _HEADER.pack(MAGIC, VERSION, salt, params.memory_kib,
                          params.time_cost, params.parallelism, CHUNK_SIZE,
                          _check_value(key))
    aead = AESGCM(key)

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with src.open("rb") as fin, dst.open("wb") as fout:
            fout.write(header)
            index = 0
            chunk = fin.read(CHUNK_SIZE)
            while True:
                nxt = fin.read(CHUNK_SIZE)
                final = not nxt
                fout.write(aead.encrypt(_nonce(index, final), chunk, header))
                if final:
                    break
                chunk = nxt
                index += 1
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return dst


def decrypt_file(src: Path, dst: Path, password: str) -> Path:
    """Decrypt ``src`` to ``dst``.

    Raises :class:`WrongPasswordError` or :class:`CorruptArchiveError` — never
    both, and never a bare `InvalidTag`, because the caller has to be able to
    tell a person which of those two very different things happened. Nothing
    is left at ``dst`` on failure.
    """
    src, dst = Path(src), Path(dst)
    raw_header = src.read_bytes()[:_HEADER.size] if src.exists() else b""
    if len(raw_header) < _HEADER.size:
        raise CorruptArchiveError(
            f"{src.name} is too short to be an encrypted archive")
    magic, version, salt, m_kib, t, p, chunk_size, check = _HEADER.unpack(raw_header)
    if magic != MAGIC:
        raise CorruptArchiveError(
            f"{src.name} is not an encrypted ExtremeCompressor archive")
    if version != VERSION:
        raise CorruptArchiveError(
            f"{src.name} was written by a newer version (format {version}); "
            f"this build understands format {VERSION}")
    if not (0 < chunk_size <= (64 << 20)):
        raise CorruptArchiveError(f"{src.name} declares an implausible chunk size")
    # The KDF parameters come out of the file, so they are attacker-controlled
    # on a hostile archive and must be bounded before they reach Argon2.
    #
    # Found by `test_header_tampering_is_detected`, which flipped one bit that
    # happened to land in the top byte of `m_kib`: 8 KiB became 16 GiB, this
    # function dutifully asked Argon2 for it, and the test took **19 minutes**.
    # A crafted header can ask for 4 TiB just as easily. That is a
    # denial-of-service in a file parser - exactly the class D0 exists to stop -
    # and it is not covered by the header being AAD, because the parameters are
    # needed to derive the key that would check the tag.
    if not (_MIN_MEMORY_KIB <= m_kib <= _MAX_MEMORY_KIB):
        raise CorruptArchiveError(
            f"{src.name} asks for {m_kib} KiB of KDF memory, which is outside "
            f"the accepted range ({_MIN_MEMORY_KIB}-{_MAX_MEMORY_KIB} KiB); "
            f"refusing rather than trying to allocate it")
    if not (1 <= t <= _MAX_TIME_COST):
        raise CorruptArchiveError(
            f"{src.name} asks for {t} KDF passes (limit {_MAX_TIME_COST})")
    if not (1 <= p <= _MAX_PARALLELISM):
        raise CorruptArchiveError(
            f"{src.name} asks for {p} KDF lanes (limit {_MAX_PARALLELISM})")

    key = _derive(password, salt, m_kib, t, p)
    if _check_value(key) != check:
        # Checked before touching the ciphertext, so this answer never depends
        # on whether the body happens to be damaged as well.
        raise WrongPasswordError("wrong password")

    aead = AESGCM(key)
    stride = chunk_size + TAG_BYTES
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with src.open("rb") as fin, dst.open("wb") as fout:
            fin.seek(_HEADER.size)
            index = 0
            block = fin.read(stride)
            if not block:
                raise CorruptArchiveError(f"{src.name} contains no data")
            while True:
                nxt = fin.read(stride)
                final = not nxt
                try:
                    fout.write(aead.decrypt(_nonce(index, final), block,
                                            raw_header))
                except InvalidTag as exc:
                    # The password already matched the check value, so this is
                    # damage or tampering - including the truncation case,
                    # where the last surviving chunk was not written as final.
                    raise CorruptArchiveError(
                        f"{src.name} is damaged or has been tampered with "
                        f"(chunk {index} failed authentication)") from exc
                if final:
                    break
                block = nxt
                index += 1
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return dst
