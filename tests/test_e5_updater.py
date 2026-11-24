"""E5: the update checker (Qt-free core).

What it must do, and refuse to do:

* read the latest GitHub release and say whether it is newer than the running version;
* download the installer only from the hosts it expects, only over https, only up to the declared size;
* accept it only if (1) its SHA-256 is the one in the release's ``SHA256SUMS`` and (2) ``SHA256SUMS`` carries a
  valid Ed25519 signature from the key built into the app. The checksum alone would not stop someone who got
  into the GitHub account from swapping both files; the signature, made with a key that never leaves the
  owner's laptop, does;
* leave nothing half-written behind, and launch nothing it has not just re-hashed.

The tests run a real HTTP server on localhost (a ``Policy`` opts that host in; production allows only
GitHub's hosts over https).
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from excmp import updater
from excmp.updater import (Policy, UpdateError, check_for_update, download_update, due, installer_command,
                           is_newer, parse_sums, parse_version, verify_signature)


# -- the keys ------------------------------------------------------------------------------------

def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, pub


# -- versions ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [("0.1.0", (0, 1, 0)), ("v1.2.3", (1, 2, 3)), ("V10.0.1", (10, 0, 1)),
                                           ("2.0", (2, 0, 0)), ("1.2.3.4", (1, 2, 3, 4))])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "latest", "1.x", "v", "1..2", "1.2.3-beta", "0.1.0 ", "-1.0", None])
def test_parse_version_rejects_anything_that_is_not_plain_numbers(text):
    with pytest.raises(UpdateError):
        parse_version(text)


def test_is_newer_compares_numbers_not_strings():
    assert is_newer("0.10.0", "0.9.0") and is_newer("v1.0", "0.99.99")
    assert not is_newer("0.1.0", "0.1.0") and not is_newer("0.1.0", "0.2.0")
    assert is_newer("0.1.0.1", "0.1.0")                    # a fourth number counts


# -- the checksum file ---------------------------------------------------------------------------

def test_parse_sums_reads_the_sha256sum_format():
    h1, h2 = "a" * 64, "B" * 64
    text = f"{h1}  ExtremeCompressor-0.2.0-setup.exe\n{h2} *other.bin\n\n"
    assert parse_sums(text) == {"ExtremeCompressor-0.2.0-setup.exe": h1, "other.bin": h2.lower()}


@pytest.mark.parametrize("bad", ["nothex  file.exe", "abc  file.exe", f"{'a' * 64}", f"{'a' * 64}  ../evil.exe",
                                 f"{'a' * 64}  dir/evil.exe", f"{'a' * 64}  C:\\evil.exe"])
def test_parse_sums_ignores_lines_that_are_not_a_plain_file_name(bad):
    assert parse_sums(bad) == {}


# -- the signature -------------------------------------------------------------------------------

def test_a_good_signature_verifies_and_any_change_does_not():
    priv, pub = _keypair()
    msg = b"abc  file\n"
    sig = priv.sign(msg).hex()
    verify_signature(msg, sig, pub)
    with pytest.raises(UpdateError):
        verify_signature(msg + b" ", sig, pub)               # the message changed
    with pytest.raises(UpdateError):
        verify_signature(msg, sig[:-2] + ("00" if sig[-2:] != "00" else "11"), pub)   # the signature changed
    _other_priv, other_pub = _keypair()
    with pytest.raises(UpdateError):
        verify_signature(msg, sig, other_pub)                # a different key


@pytest.mark.parametrize("sig", ["", "zz", "ab" * 10, "ab" * 70, None])
def test_a_malformed_signature_is_an_error_not_a_crash(sig):
    _priv, pub = _keypair()
    with pytest.raises(UpdateError):
        verify_signature(b"x", sig, pub)


def test_the_public_key_in_the_app_is_a_real_32_byte_ed25519_key():
    assert isinstance(updater.PUBLIC_KEY, bytes) and len(updater.PUBLIC_KEY) == 32
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(updater.PUBLIC_KEY)    # raises if it is not a point on the curve


# -- a real server -------------------------------------------------------------------------------

class _Server:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.redirects: dict[str, str] = {}
        self.hits: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.hits.append(self.path)
                if self.path in outer.redirects:
                    self.send_response(302)
                    self.send_header("Location", outer.redirects[self.path])
                    self.end_headers()
                    return
                body = outer.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def _policy():
    return Policy(https_only=False, hosts=frozenset({"127.0.0.1"}))


def _release(server, version="0.2.0", payload=b"MZ-installer-bytes" * 100, key=None, tamper_sums=False,
             tamper_payload=False, with_sig=True, **extra):
    """Publish a fake release on the server; returns (priv, pub, payload)."""
    priv, pub = key or _keypair()
    name = f"ExtremeCompressor-{version}-setup.exe"
    sums = f"{hashlib.sha256(payload).hexdigest()}  {name}\n".encode()
    sig = priv.sign(sums).hex().encode()
    if tamper_sums:
        sums = sums.replace(b"  ", b"  ", 1) + b"# changed\n"
    server.files["/dl/" + name] = payload + (b"x" if tamper_payload else b"")
    server.files["/dl/SHA256SUMS"] = sums
    if with_sig:
        server.files["/dl/SHA256SUMS.sig"] = sig
    assets = [{"name": name, "browser_download_url": server.base + "/dl/" + name, "size": len(payload)},
              {"name": "SHA256SUMS", "browser_download_url": server.base + "/dl/SHA256SUMS", "size": len(sums)}]
    if with_sig:
        assets.append({"name": "SHA256SUMS.sig", "browser_download_url": server.base + "/dl/SHA256SUMS.sig",
                       "size": len(sig)})
    body = {"tag_name": "v" + version, "draft": False, "prerelease": False, "assets": assets, "body": "notes"}
    body.update(extra)
    server.files["/api/latest"] = json.dumps(body).encode()
    return priv, pub, payload


# -- checking ------------------------------------------------------------------------------------

def test_a_newer_release_is_reported(server):
    _release(server, "0.2.0")
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    assert info is not None and info.version == "0.2.0"
    assert info.installer_name == "ExtremeCompressor-0.2.0-setup.exe"
    assert info.installer_url.endswith("/dl/ExtremeCompressor-0.2.0-setup.exe")


def test_the_same_or_an_older_release_is_not_an_update(server):
    _release(server, "0.2.0")
    assert check_for_update("0.2.0", api_url=server.base + "/api/latest", policy=_policy()) is None
    assert check_for_update("0.3.0", api_url=server.base + "/api/latest", policy=_policy()) is None


@pytest.mark.parametrize("extra", [{"draft": True}, {"prerelease": True}])
def test_drafts_and_prereleases_are_ignored(server, extra):
    _release(server, "0.2.0", **extra)
    assert check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy()) is None


def test_a_release_missing_its_installer_or_checksums_is_an_error(server):
    _release(server, "0.2.0")
    body = json.loads(server.files["/api/latest"])
    body["assets"] = [a for a in body["assets"] if a["name"] != "SHA256SUMS"]
    server.files["/api/latest"] = json.dumps(body).encode()
    with pytest.raises(UpdateError):
        check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"tag_name": 5}', b'{"tag_name": "v9.9.9"}',
                                  b'{"tag_name": "v9.9.9", "assets": "x"}'])
def test_garbage_from_the_server_is_an_error_not_a_crash(server, body):
    server.files["/api/latest"] = body
    with pytest.raises(UpdateError):
        check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())


def test_no_network_is_an_error_the_caller_can_show():
    with pytest.raises(UpdateError):
        check_for_update("0.1.0", api_url="http://127.0.0.1:9/api/latest", policy=_policy(), timeout=2)


def test_the_installer_url_must_be_on_an_allowed_host(server):
    _release(server, "0.2.0")
    body = json.loads(server.files["/api/latest"])
    body["assets"][0]["browser_download_url"] = "http://evil.example/ExtremeCompressor-0.2.0-setup.exe"
    server.files["/api/latest"] = json.dumps(body).encode()
    with pytest.raises(UpdateError):
        check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())


def test_production_policy_is_https_and_github_only():
    p = updater.DEFAULT_POLICY
    assert p.https_only and p.hosts >= {"api.github.com", "github.com"}
    assert not any("127" in h or "localhost" in h for h in p.hosts)
    with pytest.raises(UpdateError):                      # an http api url is refused outright
        check_for_update("0.1.0", api_url="http://api.github.com/repos/x/y/releases/latest")


def test_the_default_api_url_points_at_this_projects_releases():
    assert updater.API_URL == "https://api.github.com/repos/NuhaadhHasn/ExtremeCompressor/releases/latest"


# -- downloading ---------------------------------------------------------------------------------

def test_a_good_release_downloads_and_verifies(server, tmp_path):
    _priv, pub, payload = _release(server, "0.2.0")
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    path = download_update(info, tmp_path, public_key=pub, policy=_policy())
    assert path.read_bytes() == payload and path.parent.parent == tmp_path
    assert list(path.parent.glob("*.part")) == []


def test_a_wrong_installer_is_refused_and_nothing_is_left(server, tmp_path):
    _priv, pub, _payload = _release(server, "0.2.0", tamper_payload=True)
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError, match="(?i)sha-?256|checksum|size"):
        download_update(info, tmp_path, public_key=pub, policy=_policy())
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_checksums_signed_by_another_key_are_refused(server, tmp_path):
    _release(server, "0.2.0")
    _other_priv, other_pub = _keypair()
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError, match="(?i)signature"):
        download_update(info, tmp_path, public_key=other_pub, policy=_policy())
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_a_release_without_a_signature_is_refused(server, tmp_path):
    """The case that matters: an attacker with the account uploads their own installer and checksums and
    simply leaves the signature out."""
    _priv, pub, _p = _release(server, "0.2.0", with_sig=False)
    with pytest.raises(UpdateError, match="(?i)signature"):
        info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
        download_update(info, tmp_path, public_key=pub, policy=_policy())
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_edited_checksums_break_the_signature(server, tmp_path):
    _priv, pub, _p = _release(server, "0.2.0", tamper_sums=True)
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError, match="(?i)signature"):
        download_update(info, tmp_path, public_key=pub, policy=_policy())


def test_the_installer_must_be_listed_in_the_signed_checksums(server, tmp_path):
    priv, pub = _keypair()
    _release(server, "0.2.0", key=(priv, pub))
    other = b"someone else's installer"
    sums = f"{hashlib.sha256(other).hexdigest()}  something-else.exe\n".encode()
    server.files["/dl/SHA256SUMS"] = sums
    server.files["/dl/SHA256SUMS.sig"] = priv.sign(sums).hex().encode()
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError, match="(?i)not listed|checksum"):
        download_update(info, tmp_path, public_key=pub, policy=_policy())


def test_a_download_larger_than_declared_is_cut_off(server, tmp_path):
    _priv, pub, payload = _release(server, "0.2.0")
    server.files["/dl/ExtremeCompressor-0.2.0-setup.exe"] = payload * 50      # the server lies
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError):
        download_update(info, tmp_path, public_key=pub, policy=_policy())
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_an_absurd_declared_size_is_refused_before_downloading(server, tmp_path):
    _priv, pub, _p = _release(server, "0.2.0")
    body = json.loads(server.files["/api/latest"])
    body["assets"][0]["size"] = 10 * 1024 ** 3
    server.files["/api/latest"] = json.dumps(body).encode()
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    server.hits.clear()
    with pytest.raises(UpdateError, match="(?i)size"):
        download_update(info, tmp_path, public_key=pub, policy=_policy())
    assert not any(h.endswith(".exe") for h in server.hits)


def test_a_redirect_to_a_host_that_is_not_allowed_is_refused(server, tmp_path):
    _priv, pub, _p = _release(server, "0.2.0")
    server.redirects["/dl/ExtremeCompressor-0.2.0-setup.exe"] = "http://localhost.evil.example/x.exe"
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    with pytest.raises(UpdateError):
        download_update(info, tmp_path, public_key=pub, policy=_policy())


def test_progress_is_reported(server, tmp_path):
    _priv, pub, payload = _release(server, "0.2.0")
    info = check_for_update("0.1.0", api_url=server.base + "/api/latest", policy=_policy())
    seen = []
    download_update(info, tmp_path, public_key=pub, policy=_policy(), progress=lambda done, total: seen.append((done, total)))
    assert seen and seen[-1] == (len(payload), len(payload))


# -- launching -----------------------------------------------------------------------------------

def test_the_installer_command_is_silent_and_closes_the_app_itself(tmp_path):
    exe = tmp_path / "ExtremeCompressor-0.2.0-setup.exe"
    cmd = installer_command(exe)
    assert cmd[0] == str(exe)
    assert "/SILENT" in cmd and "/NORESTART" in cmd and "/SUPPRESSMSGBOXES" in cmd and "/CLOSEAPPLICATIONS" in cmd


# -- how often -----------------------------------------------------------------------------------

def test_due_checks_at_most_once_a_day_and_survives_nonsense():
    assert due(None, now=1_000_000.0)
    assert due("", now=1_000_000.0) and due("garbage", now=1_000_000.0)
    assert not due(1_000_000.0 - 3600, now=1_000_000.0)
    assert due(1_000_000.0 - 25 * 3600, now=1_000_000.0)
    assert due(1_000_000.0 + 10 * 3600, now=1_000_000.0)       # a clock that moved back is not "never again"
