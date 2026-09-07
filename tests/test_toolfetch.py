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
from excmp.toolfetch import (FetchError, ToolSpec, installed_path,
                             verify_installed)


def fetch_tool(spec, **kw):
    """`toolfetch.fetch_tool` with the localhost-HTTP waiver.

    Production defaults ``allow_insecure`` to **False** - that is this
    module's first stated rule, and an audit found it defaulting to True,
    which made "HTTPS only" opt-in on the function that does the work. These
    tests serve from a localhost `http.server` deliberately - hermetic,
    offline, and able to send corrupt bytes on purpose - so the waiver lives
    here and nowhere else. Tests that assert on the https rule itself call the
    real function directly.
    """
    kw.setdefault("allow_insecure", True)
    return toolfetch.fetch_tool(spec, **kw)


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

    # The real function, not the waiver helper above - this is the rule.
    with pytest.raises(FetchError, match="https"):
        toolfetch.fetch_tool(spec, allow_insecure=False)


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
    spec = _pinned(spec)
    assert verify_installed(spec) is True

    exe.write_bytes(b"MZ trojan")
    assert verify_installed(spec) is False
    assert installed_path(spec) is None, \
        "a tampered binary must not be handed back as installed"


def test_an_unpinned_spec_is_never_reported_as_installed(server):
    """With no `exe_dir_sha256` there is nothing in source to compare against,
    so a good install and a tampered one are indistinguishable. Answering
    "installed" there would be a guess, which is the thing this function
    exists to avoid - so it refuses, and the tool is re-fetched instead."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
    digest, size = _publish(root, "qpdf.zip", payload)
    spec = _spec(base, "qpdf.zip", digest, size)

    fetch_tool(spec)
    assert spec.exe_dir_sha256 == ()
    assert verify_installed(spec) is False
    assert installed_path(spec) is None


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


# --------------------------------------------------------------------------
# The hole an audit found in the first version of this module: "re-hash before
# use" hashed the launcher and nothing else.
# --------------------------------------------------------------------------

def _pinned(spec):
    """Re-create ``spec`` carrying the digests of the install now on disk.

    This mirrors the real workflow exactly: `fetch_tool` has verified the
    *archive* against a source-pinned hash, so the tree it just unpacked is
    trustworthy at that moment, and `pin_exe_dir` records what it found for a
    human to commit. Tests that skip this step are asserting `verify_installed`
    on an unpinned spec, which now correctly answers False.
    """
    import dataclasses

    return dataclasses.replace(spec, exe_dir_sha256=toolfetch.pin_exe_dir(spec))


def _tool_with_dll(server, tmp_path, **kw):
    """Install a tool shaped like the real ones: a small exe beside a DLL that
    holds the actual code. qpdf.exe is 19 KB next to a 7.4 MB qpdf30.dll, and
    flac.exe is 339 KB next to a 522 KB libFLAC.dll."""
    base, root = server
    payload = _zip_bytes({
        "bin/qpdf.exe": b"MZ small launcher",
        "bin/qpdf30.dll": b"MZ this is where the code actually lives",
        "bin/msvcp140.dll": b"MZ runtime",
    })
    digest, size = _publish(root, "tool.zip", payload)
    spec = _spec(base, "tool.zip", digest, size, **kw)
    exe = fetch_tool(spec)
    return _pinned(spec), exe


def test_replacing_a_sibling_dll_is_detected(server, tmp_path):
    """The critical finding. `verify_installed` hashed `exe_relpath` alone, so
    on the real qpdf install it guarded 19,456 of 87,686,094 bytes - 0.02% -
    and the 7.4 MB DLL holding the code was unchecked.

    Windows searches the application directory first for a non-KnownDLL, so
    replacing a sibling DLL is code execution inside the process the engine
    spawns. `flac` has exactly this shape and **is** spawned, by
    `flacaudio._run` through `installed_path`, so this was live rather than
    hypothetical.
    """
    spec, exe = _tool_with_dll(server, tmp_path)
    assert verify_installed(spec) is True

    (exe.parent / "qpdf30.dll").write_bytes(b"MZ ATTACKER PAYLOAD")

    assert verify_installed(spec) is False, \
        "a replaced sibling DLL was not detected"
    assert installed_path(spec) is None


def test_adding_a_dll_that_was_never_in_the_archive_is_detected(server, tmp_path):
    """The variant the reporter missed and the verifier found: there was no
    "nothing extra" check either, so *planting* a DLL was undetected even
    without touching a pinned file. `version.dll` is a classic hijack target."""
    spec, exe = _tool_with_dll(server, tmp_path)
    (exe.parent / "version.dll").write_bytes(b"MZ PLANTED")

    assert verify_installed(spec) is False, \
        "a planted DLL in the executable's own directory was not detected"


def test_the_trust_anchor_is_not_a_file_in_the_directory_it_protects(server, tmp_path):
    """The first version wrote the expected hash to `.pinned-sha256` **next to
    the binary**, so anyone able to overwrite the binary could rewrite the
    marker too. Verified: tampering with both left `verify_installed` returning
    True. Hashing the whole tree into that marker would not have fixed it - the
    same single write closes the loop.

    So the expected digests live in the source-pinned `ToolSpec`, where the
    archive hash already lives. An attacker who can edit the source can do
    anything anyway; that is outside the threat model and always was.
    """
    spec, exe = _tool_with_dll(server, tmp_path)
    exe.write_bytes(b"MZ TROJAN LAUNCHER")

    # Re-write every on-disk marker to agree with the tampered tree.
    import hashlib as _h
    for marker in exe.parent.parent.rglob(".pinned-sha256"):
        marker.write_text(_h.sha256(exe.read_bytes()).hexdigest(),
                          encoding="ascii")

    assert verify_installed(spec) is False, \
        "the on-disk marker is still being trusted"


def test_every_pinned_tool_declares_its_directory_digests():
    """Without `exe_dir_sha256` there is nothing in source to compare against,
    so `verify_installed` cannot answer and the tool would be re-fetched on
    every run. Pinning it is therefore not optional for a shipped entry, and
    this is what stops an unpinned one being committed."""
    for name, spec in toolfetch.TOOL_MANIFEST.items():
        assert spec.exe_dir_sha256, f"{name}: no exe_dir_sha256 pinned"
        for filename, digest in spec.exe_dir_sha256:
            assert "/" not in filename and "\\" not in filename, filename
            assert len(digest) == 64, f"{name}/{filename}: not a sha256"


# --------------------------------------------------------------------------
# The rest of the audit, verified by hand after the workflow that found them
# ran out of session. 10 of 12 reproduced; the two that did not are recorded
# in docs/benchmarks/2026-09-07-e1-audit.md so nobody re-derives them.
# --------------------------------------------------------------------------

def test_an_archive_that_expands_hugely_is_refused(server):
    """The worst of the batch. `MAX_DOWNLOAD_BYTES` caps the *download* and
    nothing capped the *expansion*: measured, a 204,060-byte download
    installed 209,715,202 bytes - **1028x** - with no refusal at all.

    A ceiling on the compressed side is not a ceiling. This is the same
    asymmetry the `.excmp` reader was hardened against in D0, where extraction
    is bounded by the manifest's own ledger rather than by a ratio.
    """
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ",
                          "payload.bin": b"\0" * (300 << 20)})
    digest, size = _publish(root, "bomb.zip", payload)
    # The point of the test is the asymmetry: tiny on the wire, huge on disk.
    assert size < (2 << 20), f"the bomb should be small in transit: {size}"

    with pytest.raises(FetchError, match="expand|unpacked|limit"):
        fetch_tool(_spec(base, "bomb.zip", digest, size))


def test_a_server_sending_more_than_the_pin_is_cut_off_early(server):
    """`spec.size` was checked *after* the whole transfer, so a server that
    sends 41,943,160 bytes for a 120-byte pin had all 41 MB written to disk
    before the refusal. The pin is a known-good number available up front;
    reading one byte past it is enough to know.
    """
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
    digest = hashlib.sha256(payload).hexdigest()
    (root / "over.zip").write_bytes(payload + b"\0" * (8 << 20))

    with pytest.raises(FetchError, match="size|bytes"):
        fetch_tool(_spec(base, "over.zip", digest, len(payload)))


def test_a_refused_download_leaves_no_staging_behind(server):
    """Measured after the bomb above: 209,715,200 bytes of a *refused*
    download were still sitting under the install root, because the staging
    directory is created with `dir=root` and the failure path did not sweep
    what the unpack had already written."""
    base, root = server
    payload = _zip_bytes({"bin/qpdf.exe": b"MZ",
                          "payload.bin": b"\0" * (300 << 20)})
    digest, size = _publish(root, "bomb.zip", payload)

    with pytest.raises(FetchError):
        fetch_tool(_spec(base, "bomb.zip", digest, size))

    install_root = toolfetch._install_root()
    strays = ([p for p in install_root.rglob("*") if p.is_file()]
              if install_root.exists() else [])
    assert strays == [], f"a refused fetch left {len(strays)} file(s): {strays[:3]}"


def test_ensure_tool_never_raises(server):
    """Its docstring promises this, and the promise is load-bearing: every
    stage that shells a tool degrades when the tool is missing, so a download
    that fails must look like a tool that was never there. Measured, a non-zip
    download raised `BadZipFile` and a traversing entry raised
    `UnsafePathError` straight out of it, crashing the job instead."""
    base, root = server
    (root / "junk.zip").write_bytes(b"this is not a zip file at all")
    junk = (root / "junk.zip").read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        info = zipfile.ZipInfo("placeholder")
        info.filename = "../../escaped.exe"
        zf.writestr(info, b"pwned")
    hostile = buf.getvalue()
    (root / "hostile.zip").write_bytes(hostile)

    for label, filename, blob in (("non-zip", "junk.zip", junk),
                                  ("traversal", "hostile.zip", hostile)):
        spec = _spec(base, filename, hashlib.sha256(blob).hexdigest(),
                     len(blob), name=f"et-{label}")
        toolfetch.TOOL_MANIFEST[spec.name] = spec
        try:
            assert toolfetch.ensure_tool(spec.name, allow_insecure=True) is None, \
                f"{label}: expected None"
        finally:
            toolfetch.TOOL_MANIFEST.pop(spec.name, None)


def test_https_is_required_unless_explicitly_waived():
    """`fetch_tool`'s `allow_insecure` defaulted to **True**, so the module's
    first stated rule - "HTTPS only" - was opt-in on the function that does
    the work. Only the tests want the waiver, so only the tests should ask."""
    import inspect

    assert inspect.signature(toolfetch.fetch_tool).parameters[
        "allow_insecure"].default is False
    assert inspect.signature(toolfetch.ensure_tool).parameters[
        "allow_insecure"].default is False


def test_a_prerelease_cannot_jump_the_version_floor():
    """`_version_tuple` strips non-digits per chunk, so `1.5.0-rc9` became
    `(1, 5, 0, 9)` - which sorts **above** `1.5.0`'s `(1, 5, 0)`. A floor of
    "1.5.0" would therefore accept a release candidate of itself, and the
    floor exists to keep known-vulnerable builds out."""
    assert toolfetch._version_tuple("1.5.0-rc9") < toolfetch._version_tuple("1.5.0")
    assert toolfetch._version_tuple("24.09") > toolfetch._version_tuple("22.00")
    assert toolfetch._version_tuple("1.5.1") > toolfetch._version_tuple("1.5.0")


def test_a_legitimate_redirect_with_a_port_is_allowed():
    """`_redirect_ok` compared `netloc`, which carries the port and the case,
    so `github.com -> release-assets.githubusercontent.com:443` was refused
    and `GitHub.com -> GitHub.com` was refused. That is an availability bug in
    a security check, which is how security checks get switched off."""
    ok = toolfetch._redirect_ok
    assert ok("github.com", "release-assets.githubusercontent.com:443")
    assert ok("github.com", "GitHub.com")
    assert ok("github.com", "github.com:443")
    # ...and the refusals still refuse.
    assert not ok("github.com", "githubusercontent.com.evil.com")
    assert not ok("github.com", "evil.com:443")


def test_a_duplicate_entry_name_is_refused(server):
    """A zip may carry two entries with one name, and `_unpack` wrote both in
    order, so the archive chose which bytes ended up at `exe_relpath` -
    measured, the second won. `manifest.extract_stored` has refused this since
    D0 for exactly this reason; the tool reader had not caught up."""
    base, root = server
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("bin/qpdf.exe", b"MZ FIRST")
        zf.writestr("bin/qpdf.exe", b"MZ SECOND WINS")
    payload = buf.getvalue()
    digest, size = _publish(root, "dup.zip", payload)

    with pytest.raises(FetchError, match="two entries|duplicate"):
        fetch_tool(_spec(base, "dup.zip", digest, size))


def test_every_shipped_tool_declares_a_version_floor():
    """The floor is listed as a guarantee of this module and was unset on both
    shipped entries, so it protected nothing in production. A pin says "these
    are the bytes I meant"; the floor says "and that version is not the one
    with the CVE"."""
    for name, spec in toolfetch.TOOL_MANIFEST.items():
        assert spec.min_version, f"{name}: no min_version"
        assert (toolfetch._version_tuple(spec.version)
                >= toolfetch._version_tuple(spec.min_version)), name


def test_every_redirect_hop_is_validated(server, tmp_path):
    """`urlopen` follows a redirect chain internally and `geturl()` reports
    only where it ended, so checking that checked one hop out of however many
    were contacted. An intermediate `Location` could name any host, and the
    request to it was already sent by the time we looked.

    The pinned hash still catches substituted *content*; this is about not
    issuing the request at all, which a hash cannot help with because it is
    checked afterwards.
    """
    from http.server import BaseHTTPRequestHandler

    hops: list[str] = []

    class Chain(BaseHTTPRequestHandler):
        def do_GET(self):
            hops.append(self.path)
            self.send_response(302)
            # An unrelated host, mid-chain, that nothing has allowlisted.
            self.send_header("Location", "https://evil.example.net/final.zip")
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Chain)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        payload = _zip_bytes({"bin/qpdf.exe": b"MZ"})
        spec = _spec(base, "start.zip", hashlib.sha256(payload).hexdigest(),
                     len(payload))
        with pytest.raises(FetchError, match="host|redirect"):
            fetch_tool(spec)
        assert hops, "the first hop should have been attempted"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_an_e1_installed_tool_is_found_by_normal_discovery():
    """`excmp/tools.py` promised to look "in the app-managed tools/bin
    directory" and only ever checked a flat `tools/bin/<name>.exe`, never
    E1's nested `<name>/<version>/<exe_relpath>`. So a hash-pinned tool was
    invisible to `find_tools` and reachable only by asking `toolfetch`
    directly - which `flacaudio` happens to do, so nothing was visibly broken
    while the discovery layer quietly did not know the tool existed.

    Skipped when nothing is installed, so the suite still runs on a machine
    that has never fetched a tool.
    """
    from excmp.tools import find_tools

    installed = {name for name, spec in toolfetch.TOOL_MANIFEST.items()
                 if toolfetch.installed_path(spec) is not None}
    if not installed:
        pytest.skip("no E1-pinned tool is installed on this machine")

    found = find_tools()
    for name in installed:
        assert found.get(name) is not None, \
            f"{name} is installed and verified but find_tools missed it"
        assert Path(found[name].path).is_file()
