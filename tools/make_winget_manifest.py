r"""Make the winget manifest for a published release (E8).

    python tools\make_winget_manifest.py --version 0.2.0 --sums dist\SHA256SUMS
    python tools\make_winget_manifest.py --version 0.2.0 --sha256 <64 hex> --out C:\somewhere

It writes the three-file manifest winget wants, under ``<out>\manifests\n\NuhaadhHasn\ExtremeCompressor\<version>\``.
The installer URL is derived from the version (the release's asset), so the manifest can only point at this
project's own GitHub release. ``winget validate --manifest <that folder>`` checks it; submitting it is a pull
request to microsoft/winget-pkgs (see packaging/RELEASING.md): the files in the pull request are exactly these.

No dependency: the YAML is written from templates (the values are checked first, so nothing needs escaping).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

PACKAGE_ID = "NuhaadhHasn.ExtremeCompressor"
REPO = "NuhaadhHasn/ExtremeCompressor"
MANIFEST_VERSION = "1.9.0"
_VERSION = re.compile(r"\d+(\.\d+){1,3}")
_SHA = re.compile(r"[0-9a-fA-F]{64}")


class ManifestError(ValueError):
    pass


def installer_name(version: str) -> str:
    return f"ExtremeCompressor-{version}-setup.exe"


def installer_url(version: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/{installer_name(version)}"


def sha_from_sums(sums_text: str, version: str) -> str:
    for line in sums_text.splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](\S+)", line.strip())
        if m and m.group(2) == installer_name(version):
            return m.group(1)
    raise ManifestError(f"{installer_name(version)} is not listed in the checksum file")


def render(version: str, sha256: str, release_date: str) -> dict[str, str]:
    """The three manifest files, as ``{file name: text}``. Raises :class:`ManifestError` on a bad value."""
    if not _VERSION.fullmatch(version):
        raise ManifestError(f"not a plain version number: {version!r}")
    if not _SHA.fullmatch(sha256):
        raise ManifestError("the SHA-256 must be 64 hex characters")
    try:
        _dt.date.fromisoformat(release_date)
    except ValueError:
        raise ManifestError(f"not a date (YYYY-MM-DD): {release_date!r}") from None
    sha = sha256.upper()
    head = f"PackageIdentifier: {PACKAGE_ID}\nPackageVersion: {version}\n"
    tail = f"ManifestVersion: {MANIFEST_VERSION}\n"
    base = f"{PACKAGE_ID}"

    def hdr(kind: str) -> str:               # winget wants the schema line first (it warns without it)
        return f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{MANIFEST_VERSION}.schema.json\n\n"
    return {
        f"{base}.yaml": hdr("version") + head + "DefaultLocale: en-US\nManifestType: version\n" + tail,
        f"{base}.installer.yaml": (
            hdr("installer") + head
            + "InstallerType: inno\nScope: user\nInstallModes:\n- interactive\n- silent\n- silentWithProgress\n"
            + "UpgradeBehavior: install\nMinimumOSVersion: 10.0.17763.0\n"
            + f"ReleaseDate: {release_date}\n"
            + f"Installers:\n- Architecture: x64\n  InstallerUrl: {installer_url(version)}\n  InstallerSha256: {sha}\n"
            + "ManifestType: installer\n" + tail),
        f"{base}.locale.en-US.yaml": (
            hdr("defaultLocale") + head
            + "PackageLocale: en-US\nPublisher: NuhaadhHasn\n"
            + f"PublisherUrl: https://github.com/NuhaadhHasn\nPackageName: ExtremeCompressor\n"
            + f"PackageUrl: https://github.com/{REPO}\nLicense: MIT\n"
            + f"LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE\n"
            + "ShortDescription: Compression for Windows that checks every restore, byte for byte.\n"
            + "Description: Analyzes every file, routes it to the compression pipeline that suits its data, and "
              "restores it byte-identically before it calls an archive finished. Never modifies the originals.\n"
            + "Moniker: extremecompressor\nTags:\n- compression\n- archive\n- lossless\n- 7zip\n- zstd\n"
            + "ManifestType: defaultLocale\n" + tail),
    }


def write(out: Path, version: str, sha256: str, release_date: str) -> Path:
    files = render(version, sha256, release_date)
    folder = Path(out) / "manifests" / "n" / "NuhaadhHasn" / "ExtremeCompressor" / version
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\r\n")
    return folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--sha256")
    group.add_argument("--sums", type=Path, help="the release's SHA256SUMS file")
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--out", type=Path, default=Path("dist") / "winget")
    args = ap.parse_args(argv)
    try:
        sha = args.sha256 or sha_from_sums(args.sums.read_text(encoding="ascii"), args.version)
        folder = write(args.out, args.version, sha, args.date)
    except (ManifestError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(folder)
    print(f"check it:  winget validate --manifest \"{folder}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
