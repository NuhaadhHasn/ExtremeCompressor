"""E1: fetch a specialist tool binary, pinned by hash.

The lightweight strategy: keep the core app small and pull a specialist down
the first time a profile actually needs it. The whole fleet minus FFmpeg is
about 15 MB.

**This is the most dangerous thing in the codebase, and it is worth being
explicit about why.** Everywhere else here parses untrusted *data* and the
worst case is a refused archive. This module downloads an **executable** and
the engine then runs it. 7-Zip ships unsigned binaries by policy, so there is
no signature to check and **the pinned SHA-256 is the entire trust anchor.**

Five rules follow from that, and each is enforced rather than documented:

1. **HTTPS, and the URL is fixed in this file.** Nothing user-supplied or
   server-supplied picks the address; a redirect cannot move it to another
   host (``_open`` refuses a cross-host redirect).
2. **Size *and* hash, verified on the bytes we actually received**, before
   anything is unpacked and before anything reaches the install root.
3. **A failed verification leaves nothing behind.** A half-verified binary on
   disk is worse than no binary, because the next run may find it.
4. **The archive is untrusted input**, exactly like an `.excmp`, so it goes
   through `safepath` - a tool zip has no more right to write outside its
   directory than a hostile archive does.
5. **Never touch PATH.** Tools are invoked by absolute path. Putting the
   download directory on PATH would let anything that lands in it be resolved
   by name for the whole process tree.

Plus a **minimum-version floor** per tool, because a hash only says "these are
the bytes I meant" - it says nothing about whether those bytes are safe. A pin
alone would happily install 7-Zip 22.00 and CVE-2025-0411.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .safepath import UnsafePathError, resolve_within
from .tempclean import rmtree_force

#: Read size for the download and the hash. One buffer, streamed - a tool is
#: only ~15 MB but there is no reason to hold it in memory.
_CHUNK = 1 << 20

#: Hard ceiling on a download, so a manifest typo or a hostile mirror cannot
#: fill the disk. The largest thing E1 would ever fetch is an FFmpeg build at
#: ~90 MB; 512 MiB leaves room without leaving it unbounded.
MAX_DOWNLOAD_BYTES = 512 << 20


class FetchError(RuntimeError):
    """A tool could not be fetched, or could not be trusted once fetched."""


@dataclass(frozen=True)
class ToolSpec:
    """One pinned tool. Everything needed to fetch it and to distrust it."""

    name: str
    version: str
    url: str
    sha256: str
    size: int
    #: Path of the executable *inside* the archive, forward slashes.
    exe_relpath: str
    license: str
    #: Refuse to install anything older than this, whatever its hash says.
    #: Compared as a dotted release tuple, so "24.09" > "22.00".
    min_version: str = ""
    #: Where the pin came from, for the human who bumps it next.
    source: str = ""
    #: ``(filename, sha256)`` for **every** file in the directory holding
    #: `exe_relpath`, pinned here in source.
    #:
    #: An audit found the first version of this module hashing `exe_relpath`
    #: and nothing else, which on the real qpdf install guarded 19,456 of
    #: 87,686,094 bytes - 0.02%. `qpdf.exe` is a launcher; the 7.4 MB
    #: `qpdf30.dll` beside it holds the code. Windows searches the
    #: application directory first for a non-KnownDLL, so replacing a sibling
    #: is code execution inside the process the engine spawns, and
    #: `verify_installed` returned True throughout. It was live rather than
    #: theoretical: `flac.exe` is 339 KB next to a 522 KB `libFLAC.dll`, and
    #: `flacaudio` spawns it.
    #:
    #: **Why in source and not in a file on disk.** The first version wrote
    #: the expected digest to `.pinned-sha256` next to the binary, so the same
    #: write that replaces a DLL can rewrite the marker - verified, it left
    #: `verify_installed` returning True. Hashing the whole tree into that
    #: marker fixes nothing for the same reason. The anchor has to live
    #: somewhere the attack cannot reach, which is here, beside the archive
    #: hash that is already trusted this way.
    #:
    #: Scoped to the executable's own directory rather than the whole tree
    #: because that is the DLL search path that grants execution, and it keeps
    #: the check cheap enough to run before every spawn: measured 0.66 s for
    #: qpdf's 12-file bin directory against 1.66 s for all 87 MB.
    exe_dir_sha256: tuple[tuple[str, str], ...] = ()

    def version_tuple(self) -> tuple[int, ...]:
        return _version_tuple(self.version)


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in text.replace("-", ".").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


# --------------------------------------------------------------------------
# the pinned manifest
# --------------------------------------------------------------------------
#
# Hashes here are seeded from GitHub's per-asset `digest` field and then
# confirmed against the downloaded bytes by a human before being committed.
# Bumping an entry means re-pinning both `sha256` and `size`; cross-check
# against the winget manifest for the same version, because 7-Zip and friends
# publish unsigned binaries and a single source of truth for a hash is a
# single point of failure.
TOOL_MANIFEST: dict[str, ToolSpec] = {
    # Fetched and verified on this machine 2026-09-07. Pinned even though the
    # lossless engine will never call it: qpdf is a **Phase C** tool, because
    # measuring it settled B5 - `--recompress-flate` rewrites the file, so 0
    # of 10 real PDFs came back byte-identical, and it saved 7.14% where the
    # existing lossless `precomp -> 7z` route saved 49.5% on the same files.
    # See docs/benchmarks/2026-09-07-b5-pdf-office.md.
    #
    # The hash came from GitHub's per-asset `digest` field and was then
    # confirmed against the downloaded bytes by `fetch_tool` itself.
    "qpdf": ToolSpec(
        name="qpdf",
        version="12.4.1",
        url=("https://github.com/qpdf/qpdf/releases/download/v12.4.1/"
             "qpdf-12.4.1-msvc64.zip"),
        sha256="3cd016cd433ef7232e42f4c13348a49cc14907a3c7278ef4f99120593126f7a6",
        size=28165367,
        exe_relpath="qpdf-12.4.1-msvc64/bin/qpdf.exe",
        license="Apache-2.0",
        source="github.com/qpdf/qpdf release asset digest, confirmed on fetch",
        exe_dir_sha256=(
            ("concrt140.dll", "54716f0738af891f283d213b5c8d11b25896bb8ee3097d301eae718560cf974e"),
            ("fix-qdf.exe", "2872497dad0af0fcfd2e92b650067042519ee0108922b9b36eaa1a1b511b43fc"),
            ("msvcp140.dll", "7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca"),
            ("msvcp140_1.dll", "206c931bf90fdad8816de3b5e2ef80b2bcaa9406c89ecc05fe6fddffe251e982"),
            ("msvcp140_2.dll", "d50d7883f20d1dc6191768d3746f52dd9cac89c346ffaed5be1f110c2f34a838"),
            ("msvcp140_atomic_wait.dll", "3d0cbfaa1bf3eecf5a3f4491d2960ee803cb994f30292c6adc4a07c498f60e2b"),
            ("msvcp140_codecvt_ids.dll", "8a65c7596ef2e6938731f5a1058e7e40145b6d97967cc649231a076b9a608d78"),
            ("qpdf.exe", "57c003e868fb66cd343fd5afb91be8c2277f56434eea8635762499731bf9f60d"),
            ("qpdf30.dll", "36fe5b2023f244e5785d96b8372dba26b75ea51b63adf4d4f1e66ad0aa1c8a61"),
            ("vcruntime140.dll", "d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7"),
            ("vcruntime140_1.dll", "a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e"),
            ("zlib-flate.exe", "6898b9fd9e253c410efd28742d4f78919855f4eb0fc2261361f188bf67aa1602"),
        ),
    ),
    # B4's WAV specialist, and the one specialist in this project that beats
    # the existing route: 43.15% on 4 real WAVs against 7-Zip's 9.45% and the
    # 0.00% that shipped, all four byte-identical.
    #
    # The hash did NOT come from GitHub: this release predates the per-asset
    # `digest` field and the API returns null for it. Pinning a hash computed
    # from our own download would be circular - it would only prove we hashed
    # what we downloaded - so it is taken from Microsoft's winget-pkgs
    # manifest for the identical URL, and `fetch_tool` then confirmed the
    # downloaded bytes against it. Two independent parties, which is the
    # standard this item asks for when a release offers no digest of its own.
    #
    # Licence note: libFLAC is BSD-3-Clause but the `flac` CLI is GPL-2.0. We
    # drive it as a subprocess and never link it, and this repo is private
    # with no distribution - but if it is ever made public, CLAUDE.md's OSI
    # rule comes back and this needs revisiting first.
    "flac": ToolSpec(
        name="flac",
        version="1.5.0",
        url=("https://github.com/xiph/flac/releases/download/1.5.0/"
             "flac-1.5.0-win.zip"),
        sha256="53f1500f0d6e7c61379d7fee50d4a9f7f504c650009506d9ba015530d76c0dde",
        size=1318000,
        exe_relpath="flac-1.5.0-win/Win64/flac.exe",
        license="GPL-2.0 (flac CLI; libFLAC itself is BSD-3-Clause)",
        source=("microsoft/winget-pkgs Xiph.FLAC 1.5.0 manifest - the GitHub "
                "asset digest is null for this release"),
        exe_dir_sha256=(
            ("flac.exe", "ff23d9cbc11d18c02f262c3ee455830ea13fbe8d9876249f0bdf101e3ad66709"),
            ("libFLAC++.dll", "3d0a7c31f6326370bd1abec5fe247a4ebdf9e76bad743a73afd7576151ddc163"),
            ("libFLAC.dll", "f93499172875fc2c0df80b57086f32e3f39e835283952ee2a59a3d4ffb097644"),
            ("metaflac.exe", "4f1653fbfc88a2328f92eb9f856dcf0feb3b303b216d1b573a6d57b21a6e296f"),
        ),
    ),
}


def _install_root() -> Path:
    """Where fetched tools live: ``<repo>/tools/bin`` by default.

    The roadmap's E1 sketch said ``%LOCALAPPDATA%\\ExtremeCompressor\\tools``.
    ``tools/bin`` is used instead because **that is already where this
    project's tool binaries are**: `zpaqfranz.exe` has lived there since B1,
    `find_tools` already looks there, and it is already in `.gitignore` - so a
    downloaded binary cannot be committed by accident, and everything is in
    one directory the user can inspect and clear.

    Splitting the fleet across two roots would have been the worse outcome:
    "which tools do I have, and where?" is a question that should have one
    answer.

    ``EXCMP_TOOLS_DIR`` overrides it, so a packaged build (E3, which will not
    have a source tree) has somewhere to point without touching this logic.
    """
    override = os.environ.get("EXCMP_TOOLS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "tools" / "bin"


def install_dir(spec: ToolSpec) -> Path:
    """``<root>/<name>/<version>/``.

    Versioned, so two versions coexist and a bump is never an in-place
    overwrite of a binary something may currently be executing.
    """
    return _install_root() / spec.name / spec.version


def _exe_in(directory: Path, spec: ToolSpec) -> Path:
    """The declared executable inside ``directory``, validated.

    `exe_relpath` comes from this file rather than from the archive, but it is
    still joined into a path, and `resolve_within` is how this project refuses
    to do that naively.
    """
    return resolve_within(directory, spec.exe_relpath)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def verify_installed(spec: ToolSpec) -> bool:
    """Is the pinned tool present, unmodified, and free of planted siblings?

    Re-checked on every call rather than trusted from install time: a binary
    that verified on Tuesday can be replaced on Wednesday, and this is the only
    thing standing between that and executing it.

    Three questions, and the first version of this function only asked a
    weaker form of the first:

    1. does every pinned file still hash to its pinned digest;
    2. is there **nothing extra** in the executable's directory - planting
       `version.dll` needs no modification of any pinned file, and Windows
       will load it;
    3. compared **case-insensitively**, because Windows resolves DLL names
       that way and `LIBFLAC.DLL` would otherwise read as an extra file while
       satisfying the loader.

    An unpinned spec answers ``False``: with nothing in source to compare
    against there is no way to tell a good install from a tampered one, and
    guessing is what this function exists to avoid.
    `test_every_pinned_tool_declares_its_directory_digests` keeps that from
    being the normal case.
    """
    if not spec.exe_dir_sha256:
        return False
    try:
        exe = _exe_in(install_dir(spec), spec)
    except UnsafePathError:
        return False
    if not exe.is_file():
        return False

    pinned = {name.lower(): digest for name, digest in spec.exe_dir_sha256}
    try:
        present = {p.name.lower(): p for p in exe.parent.iterdir() if p.is_file()}
    except OSError:
        return False
    if set(present) != set(pinned):
        return False
    for lowered, path in present.items():
        try:
            if _sha256_of(path) != pinned[lowered]:
                return False
        except OSError:
            return False
    return True


def pin_exe_dir(spec: ToolSpec) -> tuple[tuple[str, str], ...]:
    """Compute the `exe_dir_sha256` tuple for an install already on disk.

    Used once by a human when pinning or bumping a tool: fetch it, run this,
    paste the result into `TOOL_MANIFEST`, commit. The bootstrap is sound
    because `fetch_tool` has already verified the *archive* against a
    source-pinned hash, so the tree it just unpacked is trustworthy at that
    moment - this only records what it found.
    """
    exe = _exe_in(install_dir(spec), spec)
    return tuple(sorted(
        (p.name, _sha256_of(p)) for p in exe.parent.iterdir() if p.is_file()))


def installed_path(spec: ToolSpec) -> Path | None:
    """The executable, or ``None`` if it is absent or no longer trustworthy."""
    if not verify_installed(spec):
        return None
    return install_dir(spec) / Path(spec.exe_relpath)


#: Hosts a download may be redirected *to*, keyed by the host it started at.
#:
#: A same-host-only rule is what this started as, and it was wrong in a way
#: worth recording: GitHub serves every release asset by redirecting
#: `github.com` to `release-assets.githubusercontent.com`, so the strict
#: version refused the primary source for every tool this project fetches.
#:
#: The relaxation is deliberately narrow rather than "follow anything". The
#: pinned hash is what makes substituted *content* detectable; this list is
#: about not issuing a request to a host we never meant to talk to, which the
#: hash cannot help with because it is checked afterwards.
_REDIRECT_ALLOW: dict[str, tuple[str, ...]] = {
    "github.com": (".githubusercontent.com",),
    "www.github.com": (".githubusercontent.com",),
}


def _redirect_ok(origin: str, final: str) -> bool:
    if final == origin:
        return True
    for suffix in _REDIRECT_ALLOW.get(origin, ()):
        if final.endswith(suffix):
            return True
    return False


def _open(url: str, allow_insecure: bool):
    """Open ``url``, refusing anything but https and refusing to be redirected
    somewhere we did not agree to go.

    A pinned hash already means substituted *content* is caught, but a
    redirect to an arbitrary host is still a request we never intended to
    make, and it happens before any hashing. Both hops must be https: a
    redirect that downgrades to http is refused even when the first hop was
    fine.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" and not allow_insecure:
        raise FetchError(
            f"refusing to fetch over {parts.scheme!r}: tool downloads must use "
            f"https ({url})")
    request = urllib.request.Request(
        url, headers={"User-Agent": "ExtremeCompressor/E1"})
    response = urllib.request.urlopen(request, timeout=60)  # noqa: S310 - scheme checked above
    final = urlsplit(response.geturl())
    if final.scheme != parts.scheme and not allow_insecure:
        response.close()
        raise FetchError(
            f"refusing a redirect that changed scheme: {parts.scheme} -> "
            f"{final.scheme}")
    if not _redirect_ok(parts.netloc, final.netloc):
        response.close()
        raise FetchError(
            f"refusing a redirect to an unexpected host: {parts.netloc} -> "
            f"{final.netloc}")
    return response


def _download_to(spec: ToolSpec, target: Path, allow_insecure: bool) -> None:
    """Stream the download into ``target``, then verify size and hash.

    Verification happens on the bytes that arrived, not on a header: a
    `Content-Length` is just more remote input.
    """
    h = hashlib.sha256()
    written = 0
    with _open(spec.url, allow_insecure) as response, target.open("wb") as out:
        while chunk := response.read(_CHUNK):
            written += len(chunk)
            if written > MAX_DOWNLOAD_BYTES:
                raise FetchError(
                    f"{spec.name}: download passed {MAX_DOWNLOAD_BYTES} bytes")
            h.update(chunk)
            out.write(chunk)

    if written != spec.size:
        raise FetchError(
            f"{spec.name} {spec.version}: downloaded {written} bytes, the "
            f"manifest pins {spec.size}")
    digest = h.hexdigest()
    if digest != spec.sha256:
        raise FetchError(
            f"{spec.name} {spec.version}: sha256 {digest} does not match the "
            f"pinned {spec.sha256} - refusing to install it")


def _unpack(archive: Path, into: Path, spec: ToolSpec) -> None:
    """Unpack a tool zip. Untrusted input, so `safepath` decides every name.

    A tool archive has no more right to write outside its own directory than a
    hostile `.excmp` does, and it arrives from the network, so it gets the
    same D0 treatment: reject rather than mangle, and never follow a link.
    """
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = resolve_within(into, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
    if not _exe_in(into, spec).is_file():
        raise FetchError(
            f"{spec.name} {spec.version}: the archive does not contain "
            f"{spec.exe_relpath!r} - this is not the tool the manifest pins")


def fetch_tool(spec: ToolSpec, *, allow_insecure: bool = True,
               force: bool = False) -> Path:
    """Fetch, verify and install ``spec``. Returns the executable's path.

    ``allow_insecure`` exists for the localhost HTTP server the tests run
    against; every shipped manifest entry is https and
    `test_the_shipped_manifest_is_internally_consistent` pins that.

    Nothing reaches the install root until it has been verified, and a failure
    at any point leaves the install root as it was.
    """
    if spec.min_version and spec.version_tuple() < _version_tuple(spec.min_version):
        raise FetchError(
            f"{spec.name} {spec.version} is older than the {spec.min_version} "
            f"minimum this project requires - refusing to install it")

    if not force and spec.exe_dir_sha256:
        # Only skip the download when there is something in source to verify
        # the existing install against.
        existing = installed_path(spec)
        if existing is not None:
            return existing

    root = _install_root()
    root.mkdir(parents=True, exist_ok=True)
    # Staged beside the install root, so the final move is a rename on one
    # volume rather than a copy that could be interrupted half-way.
    staging = Path(
        __import__("tempfile").mkdtemp(prefix=f"{spec.name}-", dir=root))
    final = install_dir(spec)
    try:
        archive = staging / "download.bin"
        _download_to(spec, archive, allow_insecure)
        unpacked = staging / "tree"
        unpacked.mkdir()
        _unpack(archive, unpacked, spec)
        archive.unlink(missing_ok=True)

        # Deliberately no marker file written. The first version recorded the
        # expected digest beside the binary, which made it self-certifying:
        # whoever can overwrite the binary can rewrite the marker. The anchor
        # is `spec.exe_dir_sha256`, in source. See `verify_installed`.

        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            rmtree_force(final)
        os.replace(unpacked, final)
    finally:
        rmtree_force(staging)

    exe = final / Path(spec.exe_relpath)
    if not exe.is_file():          # pragma: no cover - _unpack already checked
        raise FetchError(f"{spec.name}: {exe} is missing after install")
    return exe


def ensure_tool(name: str, *, allow_insecure: bool = False) -> Path | None:
    """The engine-facing entry point: return the tool's path, fetching it if
    it is pinned and absent. ``None`` when it is not pinned at all.

    Deliberately does **not** raise on a fetch failure. Every stage that
    shells a tool already degrades when the tool is missing (the detected-only
    pattern B4 and B6 use), and a download that fails should look exactly like
    a tool that was never there rather than crash a job.
    """
    spec = TOOL_MANIFEST.get(name)
    if spec is None:
        return None
    try:
        return fetch_tool(spec, allow_insecure=allow_insecure)
    except (FetchError, OSError):
        return None
