"""`--password` has to be usable by something other than a human at a console.

Found by trying it, not by reading it. `echo pw | excmp verify --password
--keyfile k archive.excmp` **hung indefinitely** and had to be killed after
ten minutes.

The cause is a Windows-specific detail of the standard library.
`getpass.getpass` resolves to `getpass.win_getpass`, which reads with
`msvcrt.getwch()` - straight from the *console*, not from stdin - and only
falls back to a stdin read when `sys.stdin is not sys.__stdin__`. Piping into
the process does not change that identity, so the pipe is ignored and the
process blocks on a console nobody is typing at.

Why it matters more here than it would elsewhere: D5 and the F2 fix exist so
that an **encrypted** archive can be verified at all, and the whole promise of
this program is that an archive can be proven to still restore. A scheduled
integrity sweep over a folder of encrypted archives, a CI job, or a batch
script is precisely the caller that wants `verify --password` - and every one
of them would hang forever with no output.

The fix keeps the rule that produced the original design (`_ask_password`:
never accept a password as argv, because argv is visible in the process table
and lands in shell history) and adds the conventional escape hatch: when stdin
is **not a terminal**, read one line from it. That is what `gpg
--passphrase-fd` and `ssh-add` do. A password fed from a pipe or a file appears
in neither the process table nor the shell's history.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pytest

from excmp import cli


def _args(**kw) -> argparse.Namespace:
    kw.setdefault("password", True)
    return argparse.Namespace(**kw)


# --------------------------------------------------------------------------
# reading it
# --------------------------------------------------------------------------

def test_a_piped_password_is_read_instead_of_prompting(monkeypatch):
    """The hang, as a test. If `_ask_password` calls getpass here, this test
    blocks - so getpass is replaced with something that fails loudly instead
    of hanging the suite."""
    def must_not_prompt(prompt=""):
        raise AssertionError(
            "getpass was called with stdin redirected - on Windows that reads "
            "the console and blocks forever")

    monkeypatch.setattr("getpass.getpass", must_not_prompt)
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped-secret\n"))

    assert cli._ask_password(_args()) == "piped-secret"


def test_the_trailing_newline_is_not_part_of_the_password(monkeypatch):
    """`echo pw |` appends a newline, and `pw\\n` is not `pw`. Getting this
    wrong turns every scripted verify into "wrong password" - which is the
    single most misleading error this program can emit, because it sends
    someone hunting for a password they already have."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("secret-with-newline\n"))

    assert cli._ask_password(_args()) == "secret-with-newline"


def test_a_password_may_contain_spaces_and_punctuation(monkeypatch):
    """Only the line ending is stripped. A passphrase legitimately contains
    spaces, and stripping them would silently mangle it."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("  four words with spaces  \r\n"))

    assert cli._ask_password(_args()) == "  four words with spaces  "


def test_an_interactive_run_still_prompts(monkeypatch):
    """The stdin path must not become the default. At a real console the
    password must never be echoed, which is the only thing getpass is for."""
    seen = []

    def fake_prompt(prompt=""):
        seen.append(prompt)
        return "typed-at-the-console"

    monkeypatch.setattr("getpass.getpass", fake_prompt)

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty(""))
    assert cli._ask_password(_args()) == "typed-at-the-console"
    assert seen, "an interactive run did not prompt"


def test_no_password_flag_means_no_password(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("ignored\n"))
    assert cli._ask_password(argparse.Namespace(password=False)) is None


def test_an_empty_pipe_is_refused_rather_than_read_as_an_empty_password(monkeypatch):
    """A closed pipe yields "". Treating that as the password produces
    "wrong password" for a caller whose real problem is that they piped
    nothing - so say what actually happened."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(ValueError, match="stdin"):
        cli._ask_password(_args())


# --------------------------------------------------------------------------
# and the same for setting one, where the confirmation makes no sense
# --------------------------------------------------------------------------

def test_setting_a_password_from_a_pipe_does_not_ask_twice(monkeypatch):
    """`_new_password` prompts twice and compares, which is right for a human
    and impossible for a pipe: the second read gets EOF and the passwords
    "disagree". One line in, one password."""
    monkeypatch.setattr("getpass.getpass",
                        lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("new-archive-secret\n"))

    assert cli._new_password(_args()) == "new-archive-secret"


def test_setting_a_password_interactively_still_confirms(monkeypatch):
    """The typo guard has to survive the change - a mistyped password on a
    *new* archive is unrecoverable data loss, which is exactly what F5's copy
    warns about."""
    answers = iter(["first-try", "second-try-different"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty(""))
    with pytest.raises(ValueError):
        cli._new_password(_args())


# --------------------------------------------------------------------------
# the documented reason the flag takes no argument must stay true
# --------------------------------------------------------------------------

def test_no_subcommand_accepts_a_password_as_an_argument():
    """The stdin path exists so that scripting does not need argv. If a
    `--password VALUE` ever appears, the password lands in the process table
    and in shell history, and this whole file's premise is void."""
    parser = cli.build_parser()
    offenders = []
    for action in parser._subparsers._group_actions[0].choices.items():  # type: ignore[union-attr]
        name, sub = action
        for act in sub._actions:
            if "--password" in getattr(act, "option_strings", []):
                if act.nargs != 0 and not isinstance(act.const, bool) \
                        and act.nargs is not None:
                    offenders.append(f"{name}:{act.nargs}")
    assert offenders == [], offenders


def test_the_password_is_never_echoed_into_help_or_errors():
    """A password must not reach a message. Pinned because the fix reads one
    from stdin now, which makes it available in a new place."""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    for bad in ("print(password", "print(f'{password", 'print(f"{password'):
        assert bad not in src, bad
