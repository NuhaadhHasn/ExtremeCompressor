"""F2's second factor, through the engine rather than through `crypto` alone.

**The defect this file exists for, reproduced on 2026-09-09.** `engine.compress`
has accepted `keyfile=` since F2 shipped, and `crypto.decrypt_file` has always
accepted one — but nothing on the read side ever passed it. Measured:

    engine.compress([src], arc, NORMAL, ctx, password="pw", keyfile=kf)
    # -> writes an 855-byte archive, reports success

    engine.extract(arc, out, ctx, password="pw")
    # -> KeyfileRequired: sealed.excmp was created with a keyfile;
    #    supply the same file as well as the password

    engine.extract(arc, out, ctx, password="pw", keyfile=kf)
    # -> TypeError: extract() got an unexpected keyword argument 'keyfile'

So the engine could **write an archive that no code path in the engine could
read**, while the error message instructed the user to do something the API did
not permit. F2 was marked DONE in the roadmap.

**Why every existing test missed it.** `tests/test_keyfile.py` exercises
`crypto.encrypt_file` / `decrypt_file` directly, where the parameter has always
worked. And the D9 publish gate — the thing that would otherwise have caught an
unopenable archive — verifies the *plaintext* container before encryption, by
design (F1: "encrypt after the D9 gate and before the rename"). Nothing on
either side of that seam tried to decrypt what was published.

The property below is the one that was never stated: **whatever factors an
archive was created with, the same factors must open it — through the same
public API a caller uses.** Everything else here is a corollary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp import engine
from excmp.crypto import CryptoError, KeyfileRequired
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None,
                              reason="7z not installed")

PASSWORD = "correct horse battery staple"


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, StageContext]:
    src = tmp_path / "src"
    src.mkdir()
    (src / "secret.txt").write_text("two factors in, two factors out. " * 300)
    (src / "blob.bin").write_bytes(bytes(range(256)) * 40)
    keyfile = tmp_path / "my.key"
    keyfile.write_bytes(b"a second factor, on a USB stick somewhere" * 32)
    return src, keyfile, tmp_path / "sealed.excmp", StageContext(
        temp_dir=tmp_path / "tmp")


@needs_7z
def test_an_archive_made_with_a_keyfile_can_be_extracted_with_it(tmp_path):
    """The whole point, and what did not work."""
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    out = tmp_path / "out"
    result = engine.extract(arc, out, ctx, password=PASSWORD, keyfile=keyfile)

    assert result.verified == 2
    assert (out / "src" / "secret.txt").read_bytes() == \
        (src / "secret.txt").read_bytes()
    assert (out / "src" / "blob.bin").read_bytes() == \
        (src / "blob.bin").read_bytes()


@needs_7z
def test_the_password_alone_is_refused_and_says_why(tmp_path):
    """Refusing is correct; the message must name the *keyfile* so the user
    knows which of the two factors is missing. Telling somebody their password
    is wrong when it is not is how archives get deleted."""
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    with pytest.raises(KeyfileRequired, match="keyfile"):
        engine.extract(arc, tmp_path / "out", ctx, password=PASSWORD)


@needs_7z
def test_the_wrong_keyfile_is_refused(tmp_path):
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    impostor = tmp_path / "other.key"
    impostor.write_bytes(b"not the same file at all")

    with pytest.raises(CryptoError):
        engine.extract(arc, tmp_path / "out", ctx,
                       password=PASSWORD, keyfile=impostor)


@needs_7z
def test_a_keyfile_offered_to_an_archive_that_used_none_is_refused(tmp_path):
    """The inverse. Mixing the factor in would derive the wrong key, so this
    has to be an error and not a silent 'wrong password'."""
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx, password=PASSWORD)

    with pytest.raises(CryptoError):
        engine.extract(arc, tmp_path / "out", ctx,
                       password=PASSWORD, keyfile=keyfile)


@needs_7z
def test_verify_can_verify_a_keyfile_archive(tmp_path):
    """`excmp verify` is the product's central promise. An archive it cannot
    open is an archive whose promise has quietly lapsed."""
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    result = engine.verify_archive(arc, ctx, password=PASSWORD,
                                   keyfile=keyfile, deep=True)
    assert result.ok
    assert result.verified == 2
    assert len(result.tree_sha256) == 64


@needs_7z
def test_listing_a_keyfile_archive_works_with_both_factors(tmp_path):
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    listing = engine.list_any(arc, ctx, password=PASSWORD, keyfile=keyfile)
    assert {e.name for e in listing.entries} == {"src/secret.txt",
                                                "src/blob.bin"}


@needs_7z
def test_selective_extract_takes_a_keyfile_too(tmp_path):
    """Every read entry point, not just the one that was easy to reach - a
    partially-plumbed factor is how this defect happened in the first place."""
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    out = tmp_path / "one"
    result = engine.extract_selected(arc, ["src/secret.txt"], out, ctx,
                                     password=PASSWORD, keyfile=keyfile)
    assert result.files_restored == 1
    assert (out / "src" / "secret.txt").is_file()


@needs_7z
def test_extract_any_takes_a_keyfile_too(tmp_path):
    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)

    result = engine.extract_any(arc, tmp_path / "any", ctx,
                                password=PASSWORD, keyfile=keyfile)
    assert result.verified == 2


# --------------------------------------------------------------------------
# the CLI, which had no way to say the word at all
# --------------------------------------------------------------------------

@needs_7z
def test_the_cli_can_create_and_open_a_keyfile_archive(tmp_path, monkeypatch):
    """`crypto.py` tells users to "supply the same file as well as the
    password" - through a CLI that had zero occurrences of the word
    'keyfile'. An instruction the tool cannot obey is worse than none."""
    from excmp import cli

    src, keyfile, arc, ctx = _fixture(tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: PASSWORD)

    code = cli.main(["compress", str(src), "-o", str(arc), "--password",
                     "--keyfile", str(keyfile),
                     "--temp", str(tmp_path / "tmp")])
    assert code == 0 and arc.is_file()

    out = tmp_path / "back"
    code = cli.main(["extract", str(arc), "-o", str(out), "--password",
                     "--keyfile", str(keyfile),
                     "--temp", str(tmp_path / "tmp")])
    assert code == 0
    assert (out / "src" / "secret.txt").read_bytes() == \
        (src / "secret.txt").read_bytes()


@needs_7z
def test_the_cli_refuses_a_keyfile_without_a_password_flag(tmp_path):
    """A keyfile alone is a legitimate single factor for `crypto`, but the CLI
    only ever collects a password interactively - so `--keyfile` with no
    `--password` would silently produce an *unencrypted* archive. Refused."""
    from excmp import cli

    src, keyfile, arc, _ = _fixture(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["compress", str(src), "-o", str(arc),
                  "--keyfile", str(keyfile)])
    assert exc.value.code != 0


# --------------------------------------------------------------------------
# what the real CLI run on 2026-09-09 exposed
# --------------------------------------------------------------------------

@needs_7z
def test_verify_can_be_given_a_password_on_the_command_line(tmp_path,
                                                            monkeypatch):
    """`excmp verify` had no `--password` at all, so the product's central
    promise - "prove this archive still restores" - was simply unavailable for
    every encrypted archive. Found by running the command, not by a test."""
    from excmp import cli

    src, keyfile, arc, ctx = _fixture(tmp_path)
    engine.compress([src], arc, Profile.NORMAL, ctx,
                    password=PASSWORD, keyfile=keyfile)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: PASSWORD)

    code = cli.main(["verify", str(arc), "--password", "--keyfile",
                     str(keyfile), "--deep", "--temp", str(tmp_path / "tmp")])
    assert code == 0


@needs_7z
def test_a_wrong_keyfile_does_not_blame_the_password(tmp_path, monkeypatch):
    """Measured on the real CLI: supplying the right password with the wrong
    keyfile printed `error: wrong password`.

    That is not a wording quibble. The password was correct; the message sends
    the user hunting for a password they already have, and the next conclusion
    after "my password is right and it still says wrong password" is "the
    archive is broken" - which is how archives get deleted. `decrypt_file`
    knows whether a keyfile was in play, so it can say which factors it
    tried."""
    from excmp.crypto import decrypt_file, encrypt_file

    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"two factors" * 500)
    sealed = tmp_path / "sealed.bin"
    good = tmp_path / "good.key"
    good.write_bytes(b"the real second factor" * 40)
    bad = tmp_path / "bad.key"
    bad.write_bytes(b"not that file at all" * 40)
    encrypt_file(plain, sealed, PASSWORD, keyfile=good)

    with pytest.raises(CryptoError) as exc:
        decrypt_file(sealed, tmp_path / "out.bin", PASSWORD, keyfile=bad)
    message = str(exc.value).lower()
    assert "keyfile" in message, message
    assert message != "wrong password", message


@needs_7z
def test_a_wrong_password_with_no_keyfile_still_says_wrong_password(tmp_path):
    """The single-factor message must not get vaguer to accommodate the
    two-factor one - "check both" would be nonsense where there is only one."""
    from excmp.crypto import decrypt_file, encrypt_file

    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"one factor" * 500)
    sealed = tmp_path / "sealed.bin"
    encrypt_file(plain, sealed, PASSWORD)

    with pytest.raises(CryptoError) as exc:
        decrypt_file(sealed, tmp_path / "out.bin", "not it")
    assert "keyfile" not in str(exc.value).lower(), str(exc.value)
