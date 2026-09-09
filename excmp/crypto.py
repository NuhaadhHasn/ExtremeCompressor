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

import hashlib
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

#: Format 2 adds a flags byte (F2 keyfiles). Format 1 is still read: it has no
#: flags field and therefore never needs a keyfile.
VERSION = 2
VERSION_NO_FLAGS = 1

#: Bit 0 of the flags byte: this archive was written with a keyfile.
#:
#: Recorded because without it a user holding the right password and no keyfile
#: is told "wrong password", hunts for a password that is already correct, and
#: concludes the archive is broken. It leaks only that a keyfile exists, which
#: an attacker learns anyway the moment their password guesses all fail.
FLAG_KEYFILE = 0x01

#: A keyfile is hashed up to this much. Somebody will eventually point this at
#: a 40 GB video; a bounded prefix is still a perfectly good factor and does
#: not take the machine with it. PeaZip caps at the same 100 MiB.
MAX_KEYFILE_BYTES = 100 << 20

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

_HEADER_V1 = struct.Struct(f"<{len(MAGIC)}sB{SALT_BYTES}sIIBI{CHECK_BYTES}s")
_HEADER = struct.Struct(f"<{len(MAGIC)}sB{SALT_BYTES}sIIBIB{CHECK_BYTES}s")


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


class KeyfileRequired(CryptoError):
    """This archive was written with a keyfile and none was supplied.

    Deliberately *not* WrongPasswordError: the password may be perfectly
    correct, and sending someone to re-check it would waste their time and end
    with them believing the archive is broken.
    """


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


def keyfile_digest(path: Path) -> bytes:
    """SHA-256 over (a bounded prefix of) the keyfile.

    Streamed rather than read whole, and capped at :data:`MAX_KEYFILE_BYTES`.
    An empty file is refused: it would contribute nothing while letting the
    archive claim two factors.
    """
    digest = hashlib.sha256()
    seen = 0
    with Path(path).open("rb") as fh:
        while seen < MAX_KEYFILE_BYTES:
            block = fh.read(min(1 << 20, MAX_KEYFILE_BYTES - seen))
            if not block:
                break
            digest.update(block)
            seen += len(block)
    if not seen:
        raise ValueError(
            f"{Path(path).name} is empty - an empty keyfile adds no second "
            f"factor, so it is refused rather than silently ignored")
    return digest.digest()


def _mix(argon_key: bytes, keyfile_hash: bytes | None) -> bytes:
    """Fold the keyfile into the Argon2id output.

    HKDF *mixes*; it does not slow anything down, and that is exactly why the
    keyfile goes here rather than into the KDF's own inputs. Argon2id has
    already run on the password and is still the expensive step, so an
    attacker who steals the keyfile is not handed a cheap password guess -
    which is the flaw in PeaZip's prepend-the-hash approach (research/17 §1).
    """
    if keyfile_hash is None:
        return argon_key
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=keyfile_hash, info=b"excmp-keyfile-v2").derive(argon_key)


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
                 params: Argon2Params = DEFAULT_PARAMS,
                 keyfile: Path | None = None,
                 expect_src_sha256: str | None = None,
                 digests: dict[str, str] | None = None) -> Path:
    """Encrypt ``src`` to ``dst``. The source is left untouched.

    ``keyfile`` adds a second factor (F2). Either factor may be empty but not
    both — an archive protected by nothing is not an outcome anyone asked for.

    **D8, the two hash arguments.** With a password, what the D9 gate proves
    restorable is the *plaintext* container, and what actually ships is a
    ciphertext produced by a separate pass over that file afterwards. Nothing
    checked the handoff between them. Both bytestreams already pass through
    this loop, so hashing them here is free:

    ``expect_src_sha256`` refuses the job if the plaintext is not the artifact
    the caller measured — the source changed between the gate and the
    encryption. ``digests``, if given a dict, comes back holding ``"src"`` and
    ``"dst"``, so the caller can hand the ciphertext's digest to
    :func:`excmp.atomic.publish` and have the read-back prove the file at the
    destination is the ciphertext this function wrote. An out-dict rather than
    a changed return type: five call sites in the tests expect a ``Path``, and
    a wider return would be a worse trade than one documented parameter.
    """
    src, dst = Path(src), Path(dst)
    keyfile_hash = keyfile_digest(keyfile) if keyfile is not None else None
    if not password and keyfile_hash is None:
        raise ValueError(
            "an encrypted archive needs a password, a keyfile, or both")
    salt = os.urandom(SALT_BYTES)
    key = _mix(_derive(password, salt, params.memory_kib, params.time_cost,
                       params.parallelism), keyfile_hash)
    flags = FLAG_KEYFILE if keyfile_hash is not None else 0
    header = _HEADER.pack(MAGIC, VERSION, salt, params.memory_kib,
                          params.time_cost, params.parallelism, CHUNK_SIZE,
                          flags, _check_value(key))
    aead = AESGCM(key)

    dst.parent.mkdir(parents=True, exist_ok=True)
    src_digest = hashlib.sha256()
    dst_digest = hashlib.sha256()
    try:
        with src.open("rb") as fin, dst.open("wb") as fout:
            fout.write(header)
            dst_digest.update(header)
            index = 0
            chunk = fin.read(CHUNK_SIZE)
            while True:
                src_digest.update(chunk)
                nxt = fin.read(CHUNK_SIZE)
                final = not nxt
                sealed = aead.encrypt(_nonce(index, final), chunk, header)
                fout.write(sealed)
                dst_digest.update(sealed)
                if final:
                    break
                chunk = nxt
                index += 1
        if (expect_src_sha256 is not None
                and src_digest.hexdigest() != expect_src_sha256):
            # Refused *after* writing rather than pre-checked with a separate
            # read: the source is read exactly once either way, and the
            # ciphertext is deleted below, so the only cost of finding out
            # late is time - against a whole extra pass over the archive on
            # every job that is fine.
            raise CryptoError(
                f"{src.name} changed between being verified and being "
                f"encrypted: expected SHA-256 {expect_src_sha256[:16]}..., "
                f"read {src_digest.hexdigest()[:16]}... - refusing to publish "
                f"a ciphertext of bytes nothing has vouched for")
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    if digests is not None:
        digests["src"] = src_digest.hexdigest()
        digests["dst"] = dst_digest.hexdigest()
    return dst


def needs_keyfile(src: Path) -> bool:
    """Does this archive declare a keyfile? False for anything unreadable."""
    try:
        # A bounded read, not read_bytes()[:n] - that pulled a 50 GB archive
        # into memory to look at 55 bytes of header.
        with Path(src).open("rb") as fh:
            raw = fh.read(_HEADER.size)
        if len(raw) < _HEADER.size:
            return False
        magic, version = _HEADER.unpack(raw)[:2]
    except (OSError, struct.error):
        return False
    if magic != MAGIC or version != VERSION:
        return False
    return bool(_HEADER.unpack(raw)[7] & FLAG_KEYFILE)


def decrypt_file(src: Path, dst: Path, password: str,
                 keyfile: Path | None = None) -> Path:
    """Decrypt ``src`` to ``dst``.

    Raises :class:`WrongPasswordError` or :class:`CorruptArchiveError` — never
    both, and never a bare `InvalidTag`, because the caller has to be able to
    tell a person which of those two very different things happened. Nothing
    is left at ``dst`` on failure.
    """
    src, dst = Path(src), Path(dst)
    # Read enough for the larger of the two header layouts, then dispatch on
    # the version byte - format 1 has no flags field and so is shorter.
    with src.open("rb") as fh:
        probe = fh.read(_HEADER.size)
    if len(probe) < _HEADER_V1.size:
        raise CorruptArchiveError(
            f"{src.name} is too short to be an encrypted archive")
    if probe[:len(MAGIC)] != MAGIC:
        raise CorruptArchiveError(
            f"{src.name} is not an encrypted ExtremeCompressor archive")
    version = probe[len(MAGIC)]
    if version == VERSION_NO_FLAGS:
        layout, flags = _HEADER_V1, 0
        (_magic, _v, salt, m_kib, t, p, chunk_size,
         check) = layout.unpack(probe[:layout.size])
    elif version == VERSION:
        layout = _HEADER
        if len(probe) < layout.size:
            raise CorruptArchiveError(
                f"{src.name} is too short to be an encrypted archive")
        (_magic, _v, salt, m_kib, t, p, chunk_size, flags,
         check) = layout.unpack(probe[:layout.size])
    else:
        raise CorruptArchiveError(
            f"{src.name} was written by a newer version (format {version}); "
            f"this build understands formats {VERSION_NO_FLAGS}-{VERSION}")
    raw_header = probe[:layout.size]

    # Say which factor is missing rather than blaming the password for it.
    wants_keyfile = bool(flags & FLAG_KEYFILE)
    if wants_keyfile and keyfile is None:
        raise KeyfileRequired(
            f"{src.name} was created with a keyfile; supply the same file "
            f"as well as the password")
    if keyfile is not None and not wants_keyfile:
        raise CorruptArchiveError(
            f"{src.name} was not created with a keyfile - supplying one would "
            f"derive the wrong key")
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
    if m_kib < 8 * p:
        # argon2 itself requires this, and without the check its HashingError
        # escapes decrypt_file as a bare library exception rather than the
        # "this archive is malformed" answer the caller can act on.
        raise CorruptArchiveError(
            f"{src.name} asks for {m_kib} KiB across {p} lanes, which argon2 "
            f"does not accept (needs at least {8 * p} KiB)")

    keyfile_hash = keyfile_digest(keyfile) if keyfile is not None else None
    key = _mix(_derive(password, salt, m_kib, t, p), keyfile_hash)
    if _check_value(key) != check:
        # Checked before touching the ciphertext, so this answer never depends
        # on whether the body happens to be damaged as well.
        raise WrongPasswordError("wrong password")

    aead = AESGCM(key)
    stride = chunk_size + TAG_BYTES
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with src.open("rb") as fin, dst.open("wb") as fout:
            fin.seek(layout.size)
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
