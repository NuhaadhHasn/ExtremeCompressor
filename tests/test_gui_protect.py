"""The GUI half of F1/F3/G3/G4 — features that existed only on the CLI.

Everything shipped in the last stretch was reachable by typing `excmp
compress --password --recovery --split 100m --format zip` and by no other
means. This is a desktop app; a feature the window cannot reach is a feature
most of its users do not have.

Four controls, all in the Advanced panel, which is the right place because
each has a sane default and none is needed for the common job:

- **Password** — two fields, because a mistyped password here is unrecoverable
  and there is no reset. Inline, never a modal: the no-modal rule is a design
  rule of this app, and a password dialog is exactly the kind of thing that
  usually breaks it.
- **Recovery records** — off, or a percentage.
- **Split into volumes** — blank, or a size.
- **Format** — our container, or a plain `.7z`/`.zip`.

The tests below care about two things: that the controls exist and are
reachable, and that what they *say* is honest — particularly the password
warning, because "there is no backdoor" is a promise the user has to
understand before they rely on it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from excmp.crypto import DEFAULT_PARAMS


@pytest.fixture
def panel(qtbot, tmp_path):
    from gui.widgets.preset_cards import AdvancedPanel

    p = AdvancedPanel(tmp_path)
    qtbot.addWidget(p)
    return p


# ---------------------------------------------------------------------------
# The controls exist
# ---------------------------------------------------------------------------

def test_there_is_a_password_field(panel):
    assert panel.password is not None
    assert panel.password_confirm is not None


def test_the_password_is_not_echoed_on_screen(panel):
    from PySide6.QtWidgets import QLineEdit

    assert panel.password.echoMode() == QLineEdit.EchoMode.Password
    assert panel.password_confirm.echoMode() == QLineEdit.EchoMode.Password


def test_there_is_a_recovery_control(panel):
    assert panel.recovery is not None
    assert panel.recovery_percent() is None, "recovery must default to off"


def test_there_is_a_split_control(panel):
    assert panel.split is not None
    assert panel.split_size() is None, "splitting must default to off"


def test_there_is_a_format_control(panel):
    assert panel.archive_format() == "excmp", "our container is the default"


# ---------------------------------------------------------------------------
# They read back correctly
# ---------------------------------------------------------------------------

def test_a_matching_password_is_returned(panel):
    panel.password.setText("hunter2")
    panel.password_confirm.setText("hunter2")
    assert panel.password_value() == "hunter2"


def test_a_mismatched_password_is_refused_with_a_reason(panel):
    panel.password.setText("hunter2")
    panel.password_confirm.setText("hunter3")
    with pytest.raises(ValueError, match="match"):
        panel.password_value()


def test_no_password_means_no_password(panel):
    assert panel.password_value() is None


def test_a_password_typed_only_once_is_refused(panel):
    """Silently accepting the first field would defeat the point of having a
    second one."""
    panel.password.setText("hunter2")
    with pytest.raises(ValueError, match="match|again|confirm"):
        panel.password_value()


def test_the_recovery_percentage_reads_back(panel):
    for index in range(panel.recovery.count()):
        panel.recovery.setCurrentIndex(index)
        value = panel.recovery_percent()
        assert value is None or 1 <= value <= 20


def test_the_split_size_is_parsed(panel):
    panel.split.setText("100m")
    assert panel.split_size() == 100 * (1 << 20)


def test_a_nonsense_split_size_is_refused_with_a_reason(panel):
    panel.split.setText("banana")
    with pytest.raises(ValueError):
        panel.split_size()


def test_a_blank_split_size_is_simply_off(panel):
    panel.split.setText("   ")
    assert panel.split_size() is None


@pytest.mark.parametrize("fmt", ["excmp", "7z", "zip"])
def test_each_format_is_offered(panel, fmt):
    found = [panel.format_box.itemData(i) for i in range(panel.format_box.count())]
    assert fmt in found


# ---------------------------------------------------------------------------
# What it tells the user
# ---------------------------------------------------------------------------

def test_the_password_warning_says_there_is_no_recovery(panel):
    """The one thing a user must understand before relying on this. Argon2id
    plus AES-GCM means a forgotten password is a lost archive, and saying so
    up front is the only protection we can offer."""
    text = (panel.password.toolTip() + " " + panel.protect_note.text()).lower()
    assert "no" in text
    assert any(w in text for w in ("recover", "backdoor", "lost", "cannot"))


def test_the_recovery_control_explains_what_it_buys(panel):
    text = panel.recovery.toolTip().lower()
    assert any(w in text for w in ("repair", "damage", "corrupt", "sector"))


def test_the_format_control_admits_what_a_plain_archive_gives_up(panel):
    """Choosing `.zip` costs the re-verifiable ledger. The control has to say
    so, or the app implies a guarantee it cannot keep for that file."""
    text = panel.format_box.toolTip().lower()
    assert any(w in text for w in ("ledger", "verif", "re-check", "recheck"))


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_the_panel_hands_the_queue_everything_it_needs(panel):
    """One accessor rather than four scattered reads, so a caller cannot
    quietly forget the password."""
    panel.password.setText("pw")
    panel.password_confirm.setText("pw")
    panel.split.setText("50m")
    spec = panel.job_extras()
    assert spec["password"] == "pw"
    assert spec["split"] == 50 * (1 << 20)
    assert spec["archive_format"] == "excmp"
    assert "recovery" in spec


def test_job_extras_propagates_a_bad_value_rather_than_hiding_it(panel):
    panel.split.setText("nope")
    with pytest.raises(ValueError):
        panel.job_extras()


def test_the_shipped_kdf_cost_is_the_strong_one(panel):
    """Guards against a future "make the GUI feel faster" change quietly
    lowering it."""
    assert DEFAULT_PARAMS.memory_kib >= 64 * 1024


# ---------------------------------------------------------------------------
# The wiring, end to end through the queue
# ---------------------------------------------------------------------------

def test_the_queue_actually_encrypts_splits_and_protects(qtbot, tmp_path):
    """The controls being present proves nothing on its own - inert UI is the
    usual way a feature 'ships'. This runs a real job through the real queue
    and checks the file on disk.
    """
    import time

    from excmp.crypto import is_encrypted
    from excmp.recovery import available as par2_available
    from gui.queue_manager import QueueManager

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"protect me " * 50_000)

    queue = QueueManager()
    queue.temp_dir = tmp_path / "t"
    queue.threads = 2
    try:
        out = tmp_path / "job.excmp"
        queue.add_compress(
            [src], out, __import__("excmp.planner", fromlist=["Profile"]).Profile.FAST,
            extras={"password": "hunter2", "recovery": 5,
                    "split": 200_000, "archive_format": "excmp"})

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if any(j.state.is_terminal for j in queue.jobs):
                break
            qtbot.wait(100)
        job = queue.jobs[0]
        assert job.state.value == "done", f"job {job.state.value}: {job.error}"

        volumes = sorted(tmp_path.glob("job.excmp.0*"))
        assert volumes, "G3: no volumes were written"
        rejoined = tmp_path / "rejoined.excmp"
        from excmp.volumes import join_parts
        join_parts(volumes[0], rejoined)
        assert is_encrypted(rejoined), "F1: the archive was not encrypted"
        if par2_available():
            assert list(tmp_path.glob("job.excmp*.par2")), "F3: no recovery records"
    finally:
        queue.shutdown()
