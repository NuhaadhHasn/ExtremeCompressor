"""F5: the consequence of losing a password, said where people actually are.

An audit of every user-visible crypto string on 2026-09-09 found the wording
was already honest and the **delivery** was not. Three specific failures, each
verified in the source before it was changed:

1. **The best sentence in the app was hover-only.** `password.setToolTip(...)`
   carried "There is no backdoor and no reset: if you lose this password the
   data is gone" - and a tooltip needs a mouse. A keyboard or screen-reader
   user could set a password having never been shown it.

2. **The visible note was replaced exactly when it mattered.**
   `_show_protect` read:

       if self.password_confirm.text() != first:
           self.protect_note.setText(self.tr("The two entries do not match yet."))
           return

   so for the whole time someone was typing the confirmation - the moment they
   are deciding whether to encrypt at all - the consequence was gone. The
   method's own docstring said "Say the unrecoverable part while they are still
   typing it".

3. **The placeholder framed it as free.** "leave empty for no password" is the
   only text in the field before anybody types, and it named a convenience
   with no cost.

And one hole in the *test* that let this stand: the existing
`test_the_password_warning_says_there_is_no_recovery` builds
`password.toolTip() + " " + protect_note.text()` from a fresh panel where
nothing has been typed - so `protect_note` is `""` and it asserts on the
tooltip alone. The visible note could have been deleted entirely and it would
still have passed. These tests type into the fields.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from gui.widgets.preset_cards import AdvancedPanel  # noqa: E402

RECOVERY_WORDS = ("recover", "backdoor", "reset", "gone", "lost")


@pytest.fixture
def panel(qtbot, tmp_path):
    p = AdvancedPanel(tmp_path)
    qtbot.addWidget(p)
    return p


def _says_it_is_final(text: str) -> bool:
    low = text.lower()
    return "no" in low and any(w in low for w in RECOVERY_WORDS)


def test_the_consequence_appears_from_the_first_keystroke(panel):
    """Before F5 this was the mismatch notice instead."""
    panel.password.setText("s")

    assert _says_it_is_final(panel.protect_note.text()), panel.protect_note.text()


def test_the_consequence_survives_a_mismatch(panel):
    """The exact regression. While the confirmation does not match, both
    pieces of news must be on screen - not one instead of the other."""
    panel.password.setText("a long password")
    panel.password_confirm.setText("a long passw")

    note = panel.protect_note.text()
    assert _says_it_is_final(note), note
    assert "do not match" in note.lower(), note


def test_the_consequence_is_still_there_once_they_match(panel):
    panel.password.setText("a long password")
    panel.password_confirm.setText("a long password")

    note = panel.protect_note.text()
    assert _says_it_is_final(note), note
    assert "do not match" not in note.lower(), note


def test_an_empty_password_says_nothing(panel):
    """No password, no scary text - the warning has to mean something."""
    panel.password.setText("x")
    panel.password.setText("")
    assert panel.protect_note.text() == ""


def test_assistive_technology_is_told_the_consequence(panel):
    """A tooltip needs a hover, and screen readers commonly do not announce
    one. `accessibleDescription` is the channel that is announced after the
    name, which is where this belongs."""
    description = panel.password.accessibleDescription()

    assert _says_it_is_final(description), description
    # And the name stays a name - a label that reads out a paragraph on every
    # focus change is its own accessibility defect.
    assert "password" in panel.password.accessibleName().lower()
    assert len(panel.password.accessibleName()) < 40


def test_the_confirm_field_explains_why_it_exists(panel):
    """"type it again" states the mechanic. The reason is that nobody can
    recover a typo, and that is the part worth saying."""
    description = panel.password_confirm.accessibleDescription().lower()
    assert any(w in description for w in RECOVERY_WORDS), description


def test_the_placeholder_does_not_frame_encryption_as_free(panel):
    """The only string in the field before a user types."""
    placeholder = panel.password.placeholderText().lower()
    assert any(w in placeholder for w in RECOVERY_WORDS), placeholder


def test_the_password_itself_never_reaches_a_visible_or_spoken_string(panel):
    """The new copy must not have interpolated the secret anywhere - the same
    property tests/test_gui_g2.py pins on the extract side."""
    secret = "hunter2-battery-staple"
    panel.password.setText(secret)
    panel.password_confirm.setText(secret)

    for text in (panel.protect_note.text(),
                 panel.password.accessibleName(),
                 panel.password.accessibleDescription(),
                 panel.password.placeholderText(),
                 panel.password.toolTip()):
        assert secret not in text
        assert "hunter" not in text.lower()


def test_forgetting_the_password_clears_the_warning(panel):
    """Unchanged behaviour, re-pinned here because F5 rewrote the method that
    produces the text and this is what tests/test_gui_job_state.py relies on."""
    panel.password.setText("pw")
    panel.password_confirm.setText("pw")
    assert panel.protect_note.text() != ""

    panel.forget_password()
    assert panel.protect_note.text() == ""


# --------------------------------------------------------------------------
# the CLI, where there are no tooltips to fall back on
# --------------------------------------------------------------------------

def test_the_cli_says_the_consequence_before_taking_a_new_password(capsys,
                                                                   monkeypatch):
    """The audit's most important finding. `_new_password` held the clearest
    statement of the consequence anywhere in the codebase - in its
    *docstring*, which is printed to nobody - while the prompt it documents
    said only "Password for the new password: ". That is the exact keystroke
    at which the data becomes unrecoverable, on the one surface with no
    tooltip and no inline note to fall back on."""
    import argparse

    from excmp import cli

    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    cli._new_password(argparse.Namespace(password=True))

    printed = capsys.readouterr()
    said = (printed.out + printed.err).lower()
    assert any(w in said for w in RECOVERY_WORDS), said


def test_the_cli_notice_goes_to_stderr_so_json_stays_parseable(capsys,
                                                              monkeypatch):
    """`--json` output is meant to be piped. A human-readable warning on
    stdout would corrupt it, which would make the honest thing a bug."""
    import argparse

    from excmp import cli

    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    cli._new_password(argparse.Namespace(password=True))

    printed = capsys.readouterr()
    assert printed.out == "", printed.out
    assert printed.err != ""


def test_no_notice_when_no_password_was_asked_for(capsys, monkeypatch):
    import argparse

    from excmp import cli

    assert cli._new_password(argparse.Namespace(password=False)) is None
    printed = capsys.readouterr()
    assert printed.out == "" and printed.err == ""
