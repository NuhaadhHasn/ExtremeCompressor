r"""Sign a release's checksum file with the owner's update key (E5).

    python tools\release_sign.py keygen             make the key pair once; prints the PUBLIC key to paste
                                                    into excmp/updater.py (PUBLIC_KEY)
    python tools\release_sign.py sums <installer>   write SHA256SUMS next to the installer
    python tools\release_sign.py sign <SHA256SUMS>  write SHA256SUMS.sig (hex) next to it
    python tools\release_sign.py release <installer>  both of the above

The private key is ``%USERPROFILE%\.excmp\update-signing.key`` (64 hex characters). It is never part of the repo.
**Back it up** (a password manager is fine). Running copies of the app accept only updates signed by the key
whose public half is built in: if the private key is lost, the next update has to be installed by hand once,
with a new public key in a new build.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

KEY_PATH = Path(os.environ.get("EXCMP_UPDATE_KEY", Path.home() / ".excmp" / "update-signing.key"))


def public_hex(priv: Ed25519PrivateKey) -> str:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def keygen(path: Path = KEY_PATH) -> str:
    if path.exists():
        raise SystemExit(f"{path} already exists; refusing to overwrite a signing key")
    path.parent.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    path.write_text(raw.hex() + "\n", encoding="ascii")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return public_hex(priv)


def load_key(path: Path = KEY_PATH) -> Ed25519PrivateKey:
    if not path.is_file():
        raise SystemExit(f"no signing key at {path}; run `keygen` first")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(path.read_text(encoding="ascii").strip()))


def write_sums(installer: Path) -> Path:
    h = hashlib.sha256()
    with open(installer, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    out = installer.parent / "SHA256SUMS"
    out.write_bytes(f"{h.hexdigest()}  {installer.name}\n".encode("ascii"))
    return out


def sign_file(sums: Path, key_path: Path = KEY_PATH) -> Path:
    out = sums.parent / (sums.name + ".sig")
    out.write_text(load_key(key_path).sign(sums.read_bytes()).hex() + "\n", encoding="ascii")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"keygen", "sums", "sign", "release"}:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "keygen":
        pub = keygen()
        print(f"private key written to {KEY_PATH} (BACK IT UP)\nPUBLIC_KEY = bytes.fromhex(\"{pub}\")")
        return 0
    target = Path(argv[2]).resolve() if len(argv) > 2 else None
    if target is None or not target.is_file():
        print("give the file to work on")
        return 2
    if cmd == "sums":
        print(write_sums(target))
    elif cmd == "sign":
        print(sign_file(target))
    else:
        sums = write_sums(target)
        print(sums)
        print(sign_file(sums))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
