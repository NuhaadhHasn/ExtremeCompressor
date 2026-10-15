"""B13: balrogg ships as one bare ``.exe``, not a zip.

Every tool E1 pinned before it came in a zip, and `fetch_tool` unpacked it
through `safepath`. A bare executable has no archive to unpack, so it needs its
own spelling of the same trust model: the download is hashed against the pin
**before** it is placed, it lands at `exe_relpath` and nowhere else, and
`verify_installed` re-hashes it before every use and refuses a planted sibling.
"""

from __future__ import annotations

import hashlib
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from excmp import toolfetch
from excmp.toolfetch import FetchError, ToolSpec, installed_path, verify_installed

FAKE_EXE = b"MZ this is not really balrogg"


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", root
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def _isolate_install_root(tmp_path, monkeypatch):
    monkeypatch.setattr(toolfetch, "_install_root", lambda: tmp_path / "tools-root")


def _spec(base: str, payload: bytes, **kw) -> ToolSpec:
    digest = hashlib.sha256(payload).hexdigest()
    return ToolSpec(
        name="balrogg", version="1.4", url=f"{base}/balrogg.exe",
        sha256=kw.pop("sha256", digest), size=kw.pop("size", len(payload)),
        exe_relpath=kw.pop("exe_relpath", "balrogg.exe"), license="GPL-3.0",
        raw=True, exe_dir_sha256=kw.pop("exe_dir_sha256", (("balrogg.exe", digest),)),
        **kw)


def _fetch(spec, **kw):
    kw.setdefault("allow_insecure", True)      # the localhost server only
    return toolfetch.fetch_tool(spec, **kw)


def test_a_bare_executable_installs_where_the_spec_says(server):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE)

    exe = _fetch(spec)

    assert exe.read_bytes() == FAKE_EXE
    assert exe.parts[-3:-1] == ("balrogg", "1.4")
    assert installed_path(spec) == exe


def test_a_bare_executable_in_a_subfolder_installs_there(server):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    digest = hashlib.sha256(FAKE_EXE).hexdigest()
    spec = _spec(base, FAKE_EXE, exe_relpath="bin/balrogg.exe",
                 exe_dir_sha256=(("balrogg.exe", digest),))
    exe = _fetch(spec)
    assert exe.parent.name == "bin" and exe.read_bytes() == FAKE_EXE


def test_a_wrong_hash_is_refused_and_leaves_nothing(server, tmp_path):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE, sha256=hashlib.sha256(b"other").hexdigest())

    with pytest.raises(FetchError, match="sha256"):
        _fetch(spec)

    assert installed_path(spec) is None
    leftovers = [p for p in (tmp_path / "tools-root").rglob("*") if p.is_file()]
    assert leftovers == [], leftovers


def test_a_wrong_size_is_refused(server):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE, size=len(FAKE_EXE) + 1)
    with pytest.raises(FetchError):
        _fetch(spec)
    assert installed_path(spec) is None


def test_an_exe_path_that_escapes_the_install_is_refused(server):
    """`exe_relpath` is ours, not the server's, but it is still joined into a
    path, and `resolve_within` is how this project refuses to do that naively."""
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    with pytest.raises(Exception, match="escape|outside|unsafe|path"):
        _fetch(_spec(base, FAKE_EXE, exe_relpath="../../evil.exe"))


def test_tampering_after_install_is_detected(server):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE)
    exe = _fetch(spec)
    assert verify_installed(spec)

    exe.write_bytes(FAKE_EXE + b" patched")

    assert verify_installed(spec) is False
    assert installed_path(spec) is None


def test_a_planted_sibling_is_detected(server):
    """Windows searches the application directory first for a DLL, so a file
    dropped beside the executable is code execution without modifying any
    pinned byte."""
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE)
    exe = _fetch(spec)

    (exe.parent / "version.dll").write_bytes(b"MZ planted")

    assert verify_installed(spec) is False


def test_a_second_fetch_with_a_good_install_downloads_nothing(server):
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    spec = _spec(base, FAKE_EXE)
    first = _fetch(spec)
    (root / "balrogg.exe").unlink()          # the server is now gone
    assert _fetch(spec) == first


def test_a_zip_pin_still_refuses_a_bare_executable(server):
    """The default is unchanged: without ``raw`` the download is a zip, and a
    bare .exe is not one."""
    base, root = server
    (root / "balrogg.exe").write_bytes(FAKE_EXE)
    digest = hashlib.sha256(FAKE_EXE).hexdigest()
    spec = ToolSpec(name="balrogg", version="1.4", url=f"{base}/balrogg.exe",
                    sha256=digest, size=len(FAKE_EXE), exe_relpath="balrogg.exe",
                    license="GPL-3.0", exe_dir_sha256=(("balrogg.exe", digest),))
    with pytest.raises(Exception):
        _fetch(spec)
    assert installed_path(spec) is None


# -- the shipped pin ---------------------------------------------------------

def test_balrogg_is_pinned_as_a_bare_executable_with_published_digests():
    spec = toolfetch.TOOL_MANIFEST["balrogg"]
    assert spec.raw is True
    assert spec.version == "1.4"
    assert spec.url == ("https://github.com/iczelia/balrogg/releases/download/"
                        "1.4/balrogg-x86_64.exe")
    # GitHub's own per-asset digest for the release, confirmed against the
    # downloaded bytes on this machine (2026-10-01 and again 2026-10-06).
    assert spec.sha256 == ("b3a52670bf37eaf941933bf67fbfdcd1"
                           "40638240fa3d20bb9e9bd6c923097db2")
    assert spec.size == 247_315
    assert spec.exe_relpath == "balrogg-x86_64.exe"
    assert spec.exe_dir_sha256 == (("balrogg-x86_64.exe", spec.sha256),)
    assert spec.license.startswith("GPL-3.0")
    assert spec.min_version == "1.4"
