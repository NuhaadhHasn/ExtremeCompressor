"""G2: listing archives we did not create, and the password that unlocks them.

Three things are being pinned here, and only the first is a feature:

**1. The listing is honest about what it does not know.** 7-Zip reports
CRC-32. This project sells SHA-256. A foreign entry therefore carries an
*empty* ``sha256`` and its checksum in ``crc``, and the listing carries
``ledger_backed=False`` — the same companion flag ``ExtractResult`` already
uses, for the same reason: "we have no hashes" and "we checked and found
none" are different facts and must not render alike.

**2. An encrypted archive must fail, not hang.** Measured on 7-Zip 24.07:
with stdin held open and no ``-p``, ``7z x`` on an encrypted-header archive
was **still running after 8 seconds**, waiting for a password to be typed
into a console the GUI does not have. With a dummy ``-p`` it exits in 0.22 s.
This is PeaZip's ``-pdefault`` trick (research/17 §4) and it is the highest
-value line in the phase, because the failure mode it removes is an app that
looks frozen with no way out but Task Manager.

**3. The password never leaks.** Not into the job log, not into an exception
message, not into an accessible string. ``excmp/ram.py:parse_extra_args``
already refuses ``-p`` in the Parameters line for exactly this reason.
"""

from __future__ import annotations

import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from excmp import engine, slt
from excmp.manifest import ContainerError
from excmp.planner import Profile
from excmp.stages import sevenzip
from excmp.stages.base import StageContext
from excmp.tools import find_tools

_SEVENZIP = find_tools().get("7z")
needs_7z = pytest.mark.skipif(_SEVENZIP is None, reason="7z.exe not installed")

PASSWORD = "correct horse battery staple"


def _7z(*args: str) -> None:
    subprocess.run([_SEVENZIP.path, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   stdin=subprocess.DEVNULL)


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "plain.txt").write_text("hello world\n" * 200, encoding="utf-8")
    (src / "sub" / "nested.bin").write_bytes(b"x" * 500)
    return src


@pytest.fixture
def plain_zip(tmp_path, tree):
    path = tmp_path / "theirs.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 500)
        zf.writestr("docs/data.csv", "a,b,c\n" * 400)
    return path


@pytest.fixture
def ours(tmp_path, tree):
    out = tmp_path / "ours.excmp"
    engine.compress([tree], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


@pytest.fixture
def hidden_names(tmp_path, tree):
    """7z -mhe=on: even the file names are encrypted, so listing needs the
    password. This is the archive that hangs an unguarded 7z."""
    path = tmp_path / "hidden.7z"
    _7z("a", "-t7z", "-mhe=on", f"-p{PASSWORD}", str(path), str(tree / "*"))
    return path


@pytest.fixture
def aes_zip(tmp_path, tree):
    """AES *data*, plaintext *names*. Lists without a password; every entry
    is flagged encrypted. A different case from `hidden_names` entirely."""
    path = tmp_path / "aes.zip"
    _7z("a", "-tzip", f"-p{PASSWORD}", "-mem=AES256", str(path), str(tree / "*"))
    return path


def ctx(tmp_path, log=None):
    return StageContext(temp_dir=tmp_path / "t",
                        log_cb=log or (lambda stage, line: None))


# ---------------------------------------------------------------------------
# The listing itself
# ---------------------------------------------------------------------------

@needs_7z
def test_a_foreign_zip_finally_lists(plain_zip, tmp_path):
    listing = engine.list_any(plain_zip, ctx(tmp_path))
    assert listing.kind == "zip"
    assert {e.name for e in listing.entries} == {"docs/guide.txt", "docs/data.csv"}


@needs_7z
def test_a_foreign_listing_never_claims_a_sha256(plain_zip, tmp_path):
    """The whole honesty boundary in one assertion. 7-Zip gives a CRC-32;
    putting it in the `sha256` field would let every surface above render a
    32-bit error check under the name of this project's integrity guarantee.
    """
    listing = engine.list_any(plain_zip, ctx(tmp_path))
    assert listing.ledger_backed is False
    for entry in listing.entries:
        assert entry.sha256 == "", "a CRC-32 was filed as a SHA-256"
        assert entry.crc, "the checksum 7-Zip did give went missing"
        assert entry.route == "" and entry.reason == "", \
            "route/reason are our concepts and cannot be known about a foreign archive"


@needs_7z
def test_our_own_archive_is_untouched_by_any_of_this(ours, tmp_path):
    listing = engine.list_any(ours, ctx(tmp_path))
    assert listing.kind == "excmp"
    assert listing.ledger_backed is True
    assert listing.profile == "fast"
    for entry in listing.entries:
        assert len(entry.sha256) == 64
        assert entry.crc == ""


def test_list_archive_stays_excmp_only(plain_zip):
    """`list_archive` is the free path: a zip-directory read plus one JSON
    parse, with no subprocess anywhere. `ExtractTab._suggest_destination`
    calls it synchronously on every dropped file, so if it ever grew a
    foreign fallback the GUI thread would shell out to 7-Zip on every drop.
    The split mirrors `extract` / `extract_any`, which exists for the same
    kind of reason."""
    with pytest.raises(ContainerError):
        engine.list_archive(plain_zip)


@needs_7z
def test_directories_are_marked_not_listed_as_empty_files(tmp_path, tree):
    path = tmp_path / "withdirs.7z"
    _7z("a", "-t7z", str(path), str(tree / "*"))
    listing = engine.list_any(path, ctx(tmp_path))
    by_name = {e.name: e for e in listing.entries}
    assert by_name["sub"].is_dir is True
    assert by_name["plain.txt"].is_dir is False


# ---------------------------------------------------------------------------
# The hang guard
# ---------------------------------------------------------------------------

def test_every_seven_zip_command_carries_a_password():
    """Measured, not assumed: without `-p`, `7z x` on an encrypted archive
    was still running after 8 seconds with stdin held open. The guard is on
    *extract* as well as list - the extract path is the one already shipped
    on main, and it is the one that freezes a running app."""
    stage = sevenzip.SevenZipStage()
    for cmd in (stage.build_list_cmd(Path("a.7z"), None, exe="7z.exe"),
                stage.build_extract_cmd(Path("a.7z"), Path("out"), exe="7z.exe")):
        assert any(a.startswith("-p") for a in cmd), cmd


def test_the_guard_password_is_not_a_password_anyone_would_use():
    assert len(sevenzip.HANG_GUARD_PASSWORD) > 8


@needs_7z
def test_an_encrypted_archive_errors_promptly_instead_of_hanging(
        hidden_names, tmp_path, monkeypatch):
    """The regression this phase exists to prevent. The timeout is lowered so
    that a lost guard fails the test in seconds rather than wedging the run:
    with the guard this takes ~0.2 s, without it the archive never answers."""
    monkeypatch.setattr(sevenzip, "LIST_TIMEOUT_S", 15)
    t0 = time.monotonic()
    with pytest.raises(engine.EncryptedArchiveError):
        engine.list_any(hidden_names, ctx(tmp_path))
    assert time.monotonic() - t0 < 10, "7-Zip sat waiting for a password"


@needs_7z
def test_the_right_password_opens_it(hidden_names, tmp_path):
    listing = engine.list_any(hidden_names, ctx(tmp_path), password=PASSWORD)
    assert {e.name for e in listing.entries} >= {"plain.txt", "sub/nested.bin"}
    assert listing.encrypted is True


@needs_7z
def test_the_wrong_password_is_still_reported_as_encrypted(hidden_names, tmp_path):
    """Not as corruption. "You typed the wrong password" and "this file is
    damaged" send the user to completely different places."""
    with pytest.raises(engine.EncryptedArchiveError):
        engine.list_any(hidden_names, ctx(tmp_path), password="not it")


@needs_7z
def test_an_aes_zip_lists_without_a_password_and_says_it_is_encrypted(
        aes_zip, tmp_path):
    """Encrypted *data*, plaintext *names*: 7-Zip lists it happily. Flagging
    the entries is the only way the UI can warn that extraction will need a
    password even though listing did not."""
    listing = engine.list_any(aes_zip, ctx(tmp_path))
    assert listing.encrypted is True
    assert any(e.encrypted for e in listing.entries)


@needs_7z
def test_a_corrupt_file_is_not_reported_as_encrypted(tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ContainerError) as caught:
        engine.list_any(junk, ctx(tmp_path))
    assert not isinstance(caught.value, engine.EncryptedArchiveError)
    assert "password" not in str(caught.value).lower()


# ---------------------------------------------------------------------------
# The password never leaks
# ---------------------------------------------------------------------------

@needs_7z
def test_the_password_never_reaches_the_job_log(hidden_names, tmp_path):
    lines: list[str] = []
    engine.list_any(hidden_names, ctx(tmp_path, log=lambda s, line: lines.append(line)),
                    password=PASSWORD)
    blob = "\n".join(lines)
    assert PASSWORD not in blob
    assert "battery" not in blob, "a fragment of the password got through"


@needs_7z
def test_the_password_never_reaches_an_error_message(hidden_names, tmp_path):
    with pytest.raises(ContainerError) as caught:
        engine.list_any(hidden_names, ctx(tmp_path), password="hunter2 wrong")
    assert "hunter2" not in str(caught.value)


def test_redaction_replaces_the_value_not_just_the_switch():
    redacted = " ".join(sevenzip.redact(["7z.exe", "l", "-phunter2", "a.7z"]))
    assert "hunter2" not in redacted
    assert "-p" in redacted, "the reader should still see that a password was passed"


def test_redaction_leaves_ordinary_switches_alone():
    assert sevenzip.redact(["7z.exe", "a", "-mx9", "-mqs"]) == \
        ["7z.exe", "a", "-mx9", "-mqs"]


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

@needs_7z
def test_a_capped_listing_says_it_was_capped(plain_zip, tmp_path, monkeypatch):
    """A truncated list renders exactly like a complete one, which is why the
    cap has to be visible rather than merely present."""
    monkeypatch.setattr(slt, "MAX_ITEMS", 1)
    listing = engine.list_any(plain_zip, ctx(tmp_path))
    assert listing.truncated is True
    assert len(listing.entries) == 1


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

@needs_7z
def test_the_list_verb_opens_foreign_archives(plain_zip, tmp_path, capsys):
    from excmp.cli import main as cli_main
    assert cli_main(["list", str(plain_zip), "--temp", str(tmp_path / "t")]) == 0
    out = capsys.readouterr().out
    assert "guide.txt" in out and "data.csv" in out


@needs_7z
def test_the_foreign_listing_does_not_print_our_own_vocabulary(plain_zip, tmp_path,
                                                               capsys):
    """A foreign archive has no profile, no stage chain and no SHA-256
    ledger. Printing `profile  . chain none . created ` would be four blanks
    dressed as facts, and a SHA-256 heading over a CRC-32 column would be
    worse than blank."""
    from excmp.cli import main as cli_main
    cli_main(["list", str(plain_zip), "--temp", str(tmp_path / "t")])
    out = capsys.readouterr().out.lower()
    assert "profile" not in out
    assert "chain" not in out
    assert "not an extremecompressor archive" in out

    # The heading row is where a claim would be made. Naming SHA-256 in the
    # caveat is the opposite of claiming one - it is saying which guarantee
    # this archive cannot offer - so the assertion is about the columns.
    header = next(ln for ln in out.splitlines() if ln.startswith("file "))
    assert "sha" not in header
    assert "crc-32" in header
    assert "route" not in header and "why" not in header


@needs_7z
def test_the_json_listing_carries_the_honesty_flags(plain_zip, tmp_path, capsys):
    import json as _json
    from excmp.cli import main as cli_main
    cli_main(["list", str(plain_zip), "--json", "--temp", str(tmp_path / "t")])
    payload = _json.loads(capsys.readouterr().out)
    assert payload["ledger_backed"] is False
    assert payload["kind"] == "zip"
    assert all(e["sha256"] == "" for e in payload["entries"])
    assert all(e["crc"] for e in payload["entries"])


def test_our_own_json_listing_is_unchanged(ours, capsys):
    import json as _json
    from excmp.cli import main as cli_main
    cli_main(["list", str(ours), "--json"])
    payload = _json.loads(capsys.readouterr().out)
    assert payload["ledger_backed"] is True
    assert payload["kind"] == "excmp"
    assert all(len(e["sha256"]) == 64 for e in payload["entries"])


@needs_7z
def test_the_extract_verb_can_take_only_named_members(plain_zip, tmp_path, capsys):
    from excmp.cli import main as cli_main
    dest = tmp_path / "sel"
    assert cli_main(["extract", str(plain_zip), "-o", str(dest),
                     "--only", "docs/guide.txt",
                     "--temp", str(tmp_path / "t")]) == 0
    files = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert files == {"docs/guide.txt"}


@needs_7z
def test_a_password_is_never_a_command_line_value(tmp_path):
    """`--password` takes no argument: it prompts. A password passed as argv
    lands in the process table and the shell history, where it outlives the
    command by a long way."""
    from excmp.cli import build_parser
    args = build_parser().parse_args(["list", str(tmp_path / "a.zip"), "--password"])
    assert args.password is True
