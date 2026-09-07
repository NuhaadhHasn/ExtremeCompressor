"""E1: fetching a tool binary is the most dangerous thing this app does.

Every other component reads untrusted *data*. This one downloads an
**executable** and then runs it, so the pinned hash is not a nicety - it is the
only trust anchor there is. 7-Zip's binaries are unsigned by policy, so there
is no signature to fall back on.

The tests run against a `http.server` on localhost rather than the real
internet: hermetic, offline, and able to serve deliberately corrupt bytes,
which is the half that matters.

Threat model, and every line below maps to one of these:

* **Wrong bytes.** A mirror, an interception, a truncated transfer, a silently
  updated release. Size and SHA-256 are both checked, and a mismatch must
  leave nothing behind - a half-verified binary on disk is worse than none,
  because the next run might use it.
* **Hostile archive.** The download is a zip, so it is exactly as untrusted as
  an `.excmp` and gets the same D0 treatment: `safepath`, no traversal, no
  absolute paths, no links.
* **Tampering after install.** A binary that verified on Tuesday can be
  replaced on Wednesday. It is re-hashed before use.
* **Downgrade.** A pinned hash alone would happily install 7-Zip 22.00 and its
  CVE-2025-0411. There is a per-tool minimum-version floor as well.
* **PATH poisoning.** The download directory is never added to PATH, in either
  direction: we do not put it there, and we do not resolve tools *from* there
  by name.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import zipfile
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from excmp import toolfetch
from excmp.safepath import UnsafePathError
from excmp.toolfetch import (FetchError, ToolSpec, fetch_tool, installed_path,
                             verify_installed)


@pytest.fixture
def server(tmp_path):
    """Serve ``tmp_path/www`` over localhost. Yields the base URL."""
    root = tmp_path / "www"
    root.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", root
    finally:
        httpd.shutdown()
        httpd.server_close()


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _hostile_zip_bytes(name: str) -> bytes:
    """A zip whose entry name escapes the destination. ZipInfo rewrites
    backslashes in its constructor, so the name is assigned afterwards."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        info = zipfile.ZipInfo("placeholder")
        info.filename = name
        zf.writestr(info, b"pwned")
    return buf.getvalue()


def _publish(root: Path, filename: str, payload: bytes) -> tuple[str, int]:
    (root / filename).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _spec(base: str, filename: str, digest: str, size: int, **kw) -> ToolSpec:
    return ToolSpec(
        name=kw.pop("name", "qpdf"),
        version=kw.pop("version", "12.3.0"),
        url=f"{base}/{filename}",
        sha256=digest,
        size=size,
        exe_relpath=kw.pop("exe_relpath", "bin/qpdf.exe"),
        license=kw.pop("license", "Apache-2.0"),
        **kw,
    )


@pytest.fixture(autouse=True)
def _isolate_install_root(tmp_path, monkeypatch):
    """Never touch the real %LOCALAPPDATA% during tests."""
    monkeypatch.setattr(toolfetch, "_install_root",
                        lambda: tmp_path / "tools-root")


# --------------------------------------------------------------------------
# the happy path, and where it lands
# --------------------------------------------------------------------------

def test_a_pinned_tool_installs_and_verifies(server):
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ fake binary", "README": b"hi"})
    digest, size = _publish(root, "qpdf.zip", payload)

    exe = fetch_tool(_spec(base, "qpdf.zip", digest, size))

    assert exe.is_file()
    assert exe.name == "qpdf.exe"
    # ...under <root>/<name>/<version>/, so two versions can coexist and a
    # bump is not an in-place overwrite of a binary something may be running.
    assert exe.parts[-4:-1] == ("qpdf", "12.3.0", "bin")
    assert exe.read_bytes() == b"MZ fake binary"


def test_the_download_directory_is_never_put_on_path(server, monkeypatch):
    """A tool directory on PATH turns "we fetched qpdf" into "every
    subprocess in this process tree now resolves qpdf, and anything else
    sitting in that folder, by name". Tools are invoked by absolute path."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
    digest, size = _publish(root, "qpdf.zip", payload)
    before = os.environ.get("PATH", "")

    exe = fetch_tool(_spec(base, "qpdf.zip", digest, size))

    assert os.environ.get("PATH", "") == before
    assert str(exe.parent) not in os.environ.get("PATH", "")


# --------------------------------------------------------------------------
# wrong bytes
# --------------------------------------------------------------------------

def test_a_hash_mismatch_is_refused_and_leaves_nothing(server):
    """The whole point. A binary that failed verification must not be on disk
    at all - if it is, some later run re-hashes it, or worse does not."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ real"})
    _publish(root, "qpdf.zip", payload)
    wrong = hashlib.sha256(b"something else").hexdigest()

    spec = _spec(base, "qpdf.zip", wrong, len(payload))
    with pytest.raises(FetchError, match="sha256|hash"):
        fetch_tool(spec)

    assert installed_path(spec) is None
    root_dir = toolfetch._install_root()
    strays = [p for p in root_dir.rglob("*") if p.is_file()] if root_dir.exists() else []
    assert strays == [], f"a refused download left {strays}"


def test_a_size_mismatch_is_refused(server):
    """Checked as well as the hash, and cheaply, because it is the signal that
    catches a truncated transfer before megabytes have been hashed."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
    digest, size = _publish(root, "qpdf.zip", payload)

    with pytest.raises(FetchError, match="size|bytes"):
        fetch_tool(_spec(base, "qpdf.zip", digest, size + 99))


def test_a_truncated_download_is_refused(server):
    """Serve fewer bytes than the manifest declares.

    The pin describes the **whole** file, so the hash and size come from the
    full payload while the server hands back half of it. Getting this wrong
    once was instructive: publishing the truncated bytes *and* pinning their
    hash made the download verify perfectly and then fail inside `zipfile`,
    which tests nothing about verification.
    """
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ padding padding padding"})
    digest = hashlib.sha256(payload).hexdigest()
    (root / "qpdf.zip").write_bytes(payload[: len(payload) // 2])

    with pytest.raises(FetchError, match="size|bytes|sha256"):
        fetch_tool(_spec(base, "qpdf.zip", digest, len(payload)))


def test_an_insecure_url_is_refused_without_being_fetched(server):
    """`http://` for a real tool is refused. The localhost fixture is http, so
    the check has to be explicit about what it allows - and the refusal must
    happen before any request is made."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
    digest, size = _publish(root, "qpdf.zip", payload)
    spec = _spec(base, "qpdf.zip", digest, size)

    with pytest.raises(FetchError, match="https"):
        fetch_tool(spec, allow_insecure=False)


# --------------------------------------------------------------------------
# hostile archive - the download is untrusted input, exactly like an .excmp
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", [
    "../../escaped.exe",
    r"..\..\escaped.exe",
    "bin/../../../escaped.exe",
    "C:/Windows/Temp/escaped.exe",
])
def test_a_traversing_archive_entry_is_refused(server, hostile, tmp_path):
    base, root = server
    payload = _hostile_zip_bytes(hostile)
    digest, size = _publish(root, "evil.zip", payload)

    with pytest.raises((UnsafePathError, FetchError)):
        fetch_tool(_spec(base, "evil.zip", digest, size))

    strays = [p for p in tmp_path.rglob("escaped.exe")]
    assert strays == [], f"hostile entry escaped to {strays}"


def test_an_archive_missing_its_declared_executable_is_refused(server):
    """The manifest promises `exe_relpath`. An archive that does not contain it
    is not the tool we pinned, whatever its hash says."""
    base, root = server
    payload = _zip_bytes({"bin/something-else.exe": b"MZ"})
    digest, size = _publish(root, "qpdf.zip", payload)

    with pytest.raises(FetchError, match="qpdf.exe|exe_relpath|not contain"):
        fetch_tool(_spec(base, "qpdf.zip", digest, size))


# --------------------------------------------------------------------------
# tampering after install, and the downgrade floor
# --------------------------------------------------------------------------

def test_an_installed_binary_is_rehashed_before_use(server):
    """A binary that verified at install can be replaced afterwards. The hash
    is re-checked, so `installed_path` answers "is the pinned tool here",
    not "is something here"."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ genuine"})
    digest, size = _publish(root, "qpdf.zip", payload)
    spec = _spec(base, "qpdf.zip", digest, size)

    exe = fetch_tool(spec)
    assert verify_installed(spec) is True

    exe.write_bytes(b"MZ trojan")
    assert verify_installed(spec) is False
    assert installed_path(spec) is None, \
        "a tampered binary must not be handed back as installed"


def test_a_version_below_the_security_floor_is_refused(server):
    """A pinned hash alone happily installs 7-Zip 22.00 and CVE-2025-0411.
    The floor is a separate assertion from the hash and has to be, because a
    hash only says "these are the bytes I meant", not "those bytes are safe"."""
    base, root = server
    payload = _zip_bytes({"bin/7z.exe": b"MZ"})
    digest, size = _publish(root, "7z.zip", payload)

    with pytest.raises(FetchError, match="minimum|floor|older"):
        fetch_tool(_spec(base, "7z.zip", digest, size, name="7z",
                         version="22.00", exe_relpath="bin/7z.exe",
                         min_version="24.09", license="LGPL-2.1"))


def test_the_shipped_manifest_is_internally_consistent():
    """Every pinned entry needs the fields the fetcher relies on, an https
    URL, and a full-length hash. A manifest typo is a download that fails at
    the worst moment - when a profile first needs the tool.

    Deliberately does not require the manifest to be *non-empty*: a hash may
    only be pinned after the bytes have been downloaded and checked on this
    machine, so an entry appearing here is a record of that having happened.
    An empty manifest means the fetcher works and nothing is pinned yet, which
    is a true statement about the code rather than a failing test.
    """
    for name, spec in toolfetch.TOOL_MANIFEST.items():
        assert spec.name == name
        assert spec.url.startswith("https://"), f"{name}: {spec.url}"
        assert len(spec.sha256) == 64, f"{name}: hash is not sha256"
        assert int(spec.sha256, 16) >= 0, f"{name}: hash is not hex"
        assert spec.size > 0, f"{name}: no declared size"
        assert spec.exe_relpath, f"{name}: no executable path"
        assert spec.license, f"{name}: no licence recorded"


# --------------------------------------------------------------------------
# redirects: the guard that was right to exist and wrong as first written
# --------------------------------------------------------------------------

def test_github_is_allowed_to_redirect_to_its_asset_host():
    """A same-host-only rule refused the primary source for every tool this
    project fetches: GitHub serves every release asset by redirecting
    `github.com` to `release-assets.githubusercontent.com`. Found by the guard
    firing on the very first real download."""
    from excmp.toolfetch import _redirect_ok

    assert _redirect_ok("github.com", "release-assets.githubusercontent.com")
    assert _redirect_ok("github.com", "objects.githubusercontent.com")
    assert _redirect_ok("github.com", "github.com")


@pytest.mark.parametrize("final", [
    "evil.com",
    "githubusercontent.com.evil.com",      # suffix-match bait
    "release-assets.githubusercontent.com.attacker.net",
    "raw.example.org",
])
def test_a_redirect_to_an_unexpected_host_is_still_refused(final):
    """The relaxation has to stay narrow. `endswith('.githubusercontent.com')`
    is why the bait entries here matter - a bare `in` or a substring test
    would pass them."""
    from excmp.toolfetch import _redirect_ok

    assert not _redirect_ok("github.com", final)


def test_an_unlisted_origin_gets_no_redirect_latitude():
    """Only hosts we have a reason to trust get a redirect allowance."""
    from excmp.toolfetch import _redirect_ok

    assert _redirect_ok("example.org", "example.org")
    assert not _redirect_ok("example.org", "cdn.example.org")
