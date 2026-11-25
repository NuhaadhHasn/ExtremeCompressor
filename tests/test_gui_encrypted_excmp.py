"""A password-protected .excmp, opened from the Extract tab.

Found by writing the user guide (it ran the app): the tab treated an encrypted ``.excmp`` as somebody else's
archive (it is not a zip until it is decrypted), so Verify was greyed out, the status line said "not created by
ExtremeCompressor", and Restore ran without any password and failed. Only the command line worked.

These tests drive the real tab, the real queue and the real engine.
"""

from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("pytestqt")

from excmp import engine                              # noqa: E402
from excmp.planner import Profile                     # noqa: E402
from excmp.stages.base import StageContext            # noqa: E402
from excmp.tools import find_tools                    # noqa: E402
from gui.mainwindow import MainWindow                 # noqa: E402
from gui.models import JobState                       # noqa: E402

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None, reason="7z.exe not installed")

PASSWORD = "correct horse battery staple"
FILES = {"readme.txt": ("shrink me. " * 2000).encode(), "noise.bin": bytes((i * 97 + 3) % 256 for i in range(40_000))}


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def locked(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name, data in FILES.items():
        (src / name).write_bytes(data)
    out = tmp_path / "locked.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"), password=PASSWORD)
    return out


def _open(window, archive, dest):
    tab = window.extract_tab
    tab.set_archive(archive)
    tab.dest_edit.setText(str(dest))
    return tab


def _wait_job(window, qtbot):
    qtbot.waitUntil(lambda: window.queue.jobs and window.queue.jobs[-1].state.is_terminal, timeout=120_000)
    return window.queue.jobs[-1]


@needs_7z
def test_the_tab_knows_an_encrypted_excmp_is_ours(window, locked, tmp_path):
    tab = _open(window, locked, tmp_path / "out")
    assert tab.verify_button.isEnabled()
    text = tab.status.text().lower()
    assert "password" in text and "not created by" not in text


@needs_7z
def test_restore_without_a_password_asks_for_one_and_runs_nothing(window, locked, tmp_path, qtbot):
    tab = _open(window, locked, tmp_path / "out")
    tab.start_button.click()
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    assert "password" in window.banner.text().lower()
    assert list(window.queue.jobs) == []


@needs_7z
def test_typing_the_password_restores_the_files_byte_for_byte(window, locked, tmp_path, qtbot):
    dest = tmp_path / "out"
    tab = _open(window, locked, dest)
    tab.start_button.click()
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    window.banner.submit_secret(PASSWORD)
    job = _wait_job(window, qtbot)
    assert job.state is JobState.DONE, job.error
    restored = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob("*") if p.is_file()}
    assert restored == {n: hashlib.sha256(d).hexdigest() for n, d in FILES.items()}


@needs_7z
def test_verify_asks_and_then_verifies_against_the_ledger(window, locked, tmp_path, qtbot):
    tab = _open(window, locked, tmp_path / "out")
    tab.verify_button.click()
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    window.banner.submit_secret(PASSWORD)
    job = _wait_job(window, qtbot)
    assert job.state is JobState.DONE, job.error
    assert job.result.verified == len(FILES)


@needs_7z
def test_a_wrong_password_fails_readably_and_asks_again(window, locked, tmp_path, qtbot):
    tab = _open(window, locked, tmp_path / "out")
    tab.start_button.click()
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    window.banner.submit_secret("not the password")
    job = _wait_job(window, qtbot)
    assert job.state is JobState.FAILED and "password" in (job.error or "").lower()
    window.banner.hide_banner()
    tab.start_button.click()                                       # the wrong one is not kept
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)


@needs_7z
def test_the_explorer_verbs_ask_too(window, locked, tmp_path, qtbot):
    tab = _open(window, locked, tmp_path / "out")
    assert tab.request_verify() is True
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    window.banner.hide_banner()
    assert tab.request_extract() is True
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    assert list(window.queue.jobs) == []


@needs_7z
def test_a_plain_excmp_is_unchanged_no_question_asked(window, tmp_path, qtbot):
    src = tmp_path / "s"
    src.mkdir()
    (src / "a.txt").write_text("hello " * 1000)
    plain = tmp_path / "plain.excmp"
    engine.compress([src], plain, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    tab = _open(window, plain, tmp_path / "out")
    assert "password" not in tab.status.text().lower()
    tab.start_button.click()
    assert not window.banner.has_secret_field()
    job = _wait_job(window, qtbot)
    assert job.state is JobState.DONE, job.error


@needs_7z
def test_the_password_is_not_kept_after_the_job_and_not_in_any_visible_text(window, locked, tmp_path, qtbot):
    tab = _open(window, locked, tmp_path / "out")
    tab.start_button.click()
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=5000)
    window.banner.submit_secret(PASSWORD)
    _wait_job(window, qtbot)
    for text in (tab.status.text(), window.banner.text(), window.windowTitle()):
        assert PASSWORD not in text
    assert tab.current_password() is None                          # forgotten once the job has taken it
