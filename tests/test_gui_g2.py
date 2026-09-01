"""G2 on screen: listing somebody else's archive without borrowing our words.

Wave 3b shipped a listing that worked only on `.excmp` and said so. The
temptation now that foreign listing works is to point the same four columns
at it — and three of those four columns would be lies. A foreign archive has
no route, no reason a file was stored, and no SHA-256; it has a CRC-32, which
is a different thing wearing a similar shape.

That is not a hypothetical. The QA sweep already caught this exact substitution
once, when a foreign *extract* reused the verified-restore wording and produced
"0 SHA-256 hashes verified - byte-identical to the originals" about an archive
that had never been checked against anything.

The password tests pin absence rather than presence: a secret that reaches the
accessible name, the status line or the log has leaked, and the widget that
holds it is a `QLineEdit` that would otherwise keep it for the session.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from excmp import engine                              # noqa: E402
from excmp.planner import Profile                     # noqa: E402
from excmp.stages.base import StageContext            # noqa: E402
from excmp.tools import find_tools                    # noqa: E402
from gui.mainwindow import MainWindow                 # noqa: E402

_SEVENZIP = find_tools().get("7z")
needs_7z = pytest.mark.skipif(_SEVENZIP is None, reason="7z.exe not installed")

PASSWORD = "correct horse battery staple"


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def foreign(tmp_path):
    path = tmp_path / "somebody-elses.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 500)
        zf.writestr("docs/data.csv", "a,b,c\n" * 400)
    return path


@pytest.fixture
def ours(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "readme.txt").write_text("shrink me. " * 2000, encoding="utf-8")
    (src / "noise.bin").write_bytes(bytes((i * 97 + 3) % 256 for i in range(40_000)))
    out = tmp_path / "ours.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


@pytest.fixture
def locked(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    (src / "secret.txt").write_text("classified\n" * 50, encoding="utf-8")
    path = tmp_path / "locked.7z"
    subprocess.run([_SEVENZIP.path, "a", "-t7z", "-mhe=on", f"-p{PASSWORD}",
                    str(path), str(src / "*")], check=True,
                   stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return path


def open_contents(tab, qtbot, timeout=15000):
    """Open the panel and wait for the listing to *settle*.

    Not merely for the status line to say something: the foreign path sets
    "Reading the archive's contents…" before it launches 7-Zip, so waiting on
    a non-empty status returns before any row exists.
    """
    window = tab.window()
    tab.contents_toggle.setChecked(True)
    qtbot.waitUntil(
        lambda: tab.contents.topLevelItemCount() > 0
        or "could not" in tab.status.text().lower()
        or window.banner.has_secret_field(),
        timeout=timeout)
    qtbot.wait(50)


def headers(tab):
    head = tab.contents.headerItem()
    return [head.text(i).lower() for i in range(tab.contents.columnCount())]


# ---------------------------------------------------------------------------
# The toggle that used to refuse
# ---------------------------------------------------------------------------

@needs_7z
def test_a_foreign_archive_can_now_be_opened(window, foreign):
    """Replaces wave 3b's `test_a_foreign_archive_says_it_cannot_be_listed_yet`.
    That test pinned an honest refusal; this phase is what makes the refusal
    unnecessary, so the assertion inverts rather than disappears."""
    tab = window.extract_tab
    tab.set_archive(foreign)
    assert tab.contents_toggle.isEnabled()
    assert "not wired up" not in tab.contents_toggle.toolTip().lower()


@needs_7z
def test_the_rows_are_the_archives_real_contents(window, foreign, qtbot):
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    names = {tab.contents.topLevelItem(i).text(tab.COL_NAME)
             for i in range(tab.contents.topLevelItemCount())}
    assert names == {"docs/guide.txt", "docs/data.csv"}


# ---------------------------------------------------------------------------
# Not borrowing our vocabulary
# ---------------------------------------------------------------------------

def test_our_own_archive_keeps_the_columns_only_we_can_fill(window, ours, qtbot):
    tab = window.extract_tab
    tab.set_archive(ours)
    open_contents(tab, qtbot)
    assert "route" in headers(tab)
    assert any("why" in h for h in headers(tab))


@needs_7z
def test_a_foreign_archive_gets_columns_it_can_actually_fill(window, foreign,
                                                             qtbot):
    """No `Route`, because we did not route it. No `Why it was stored`,
    because we did not decide that either — and an empty column under that
    heading reads as "no reason", not "unknowable"."""
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    head = headers(tab)
    assert "route" not in head
    assert not any("why" in h for h in head)
    # Four columns is the width budget at 1366x768, so the two it can fill
    # take the slots. The CRC-32 goes one hover away, the same place ours
    # puts the SHA-256 — see the tooltip test below.
    assert head == ["file", "size", "packed", "modified"]


@needs_7z
def test_no_row_offers_a_sha256_it_does_not_have(window, foreign, qtbot):
    """Ours puts the SHA-256 one hover away. A foreign row must not offer the
    same affordance filled with a CRC-32, and must not offer an empty one
    either — "SHA-256 " with nothing after it reads as a failed check."""
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    import re
    for i in range(tab.contents.topLevelItemCount()):
        tip = tab.contents.topLevelItem(i).toolTip(tab.COL_NAME).lower()
        # No 64-hex value anywhere: that is what a SHA-256 *claim* looks like.
        # Naming SHA-256 in the disclaimer is the opposite of claiming one.
        assert not re.search(r"[0-9a-f]{64}", tip), tip
        assert "crc-32" in tip


def test_our_own_rows_still_show_the_sha256(window, ours, qtbot):
    tab = window.extract_tab
    tab.set_archive(ours)
    open_contents(tab, qtbot)
    tip = tab.contents.topLevelItem(0).toolTip(tab.COL_NAME).lower()
    assert "sha-256" in tip


@needs_7z
def test_the_panel_says_these_numbers_are_the_archives_own(window, foreign, qtbot):
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    caption = tab.contents_caption.text().lower()
    assert caption
    assert "crc-32" in caption and "sha-256" in caption

    # And it must not simply restate the status line sitting five rows above
    # it. One warning printed twice in one panel is the defect Phase J
    # recorded after printing one three times.
    assert "not created by extremecompressor" in tab.status.text().lower()
    assert "not created by extremecompressor" not in caption


def test_the_caption_is_absent_for_our_own(window, ours, qtbot):
    """A standing caveat above a listing that *is* ledger-backed would be the
    wave-3b blurb bug again, one widget down."""
    tab = window.extract_tab
    tab.set_archive(ours)
    open_contents(tab, qtbot)
    assert not tab.contents_caption.isVisibleTo(tab)


# ---------------------------------------------------------------------------
# The password
# ---------------------------------------------------------------------------

@needs_7z
def test_an_encrypted_archive_asks_rather_than_failing_silently(window, locked,
                                                                qtbot):
    tab = window.extract_tab
    tab.set_archive(locked)
    open_contents(tab, qtbot)
    qtbot.waitUntil(lambda: window.banner.isVisibleTo(window), timeout=15000)
    assert "password" in window.banner.text().lower()
    assert window.banner.has_secret_field()


@needs_7z
def test_the_typed_password_opens_the_listing(window, locked, qtbot):
    tab = window.extract_tab
    tab.set_archive(locked)
    open_contents(tab, qtbot)
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=15000)

    window.banner.submit_secret(PASSWORD)
    qtbot.waitUntil(lambda: tab.contents.topLevelItemCount() > 0, timeout=20000)
    names = {tab.contents.topLevelItem(i).text(tab.COL_NAME)
             for i in range(tab.contents.topLevelItemCount())}
    assert "secret.txt" in names


@needs_7z
def test_the_password_is_not_left_sitting_in_the_widget(window, locked, qtbot):
    """The field would otherwise hold the secret in plain text for the rest of
    the session, one screen-reader query or screenshot away."""
    tab = window.extract_tab
    tab.set_archive(locked)
    open_contents(tab, qtbot)
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=15000)
    window.banner.submit_secret(PASSWORD)
    qtbot.wait(100)
    assert window.banner.secret_text() == ""


@needs_7z
def test_the_password_never_reaches_a_spoken_or_visible_string(window, locked,
                                                               qtbot):
    tab = window.extract_tab
    tab.set_archive(locked)
    open_contents(tab, qtbot)
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=15000)
    window.banner.submit_secret(PASSWORD)
    qtbot.waitUntil(lambda: tab.contents.topLevelItemCount() > 0, timeout=20000)

    for surface in (window.banner.accessibleName(), window.banner.text(),
                    tab.status.text(), tab.contents_caption.text()):
        assert PASSWORD not in surface
        assert "battery" not in surface


@needs_7z
def test_the_password_is_forgotten_when_the_archive_changes(window, locked,
                                                            foreign, qtbot):
    """It was given for one archive. Carrying it to the next one silently
    tries a user's password against a file they did not offer it for."""
    tab = window.extract_tab
    tab.set_archive(locked)
    open_contents(tab, qtbot)
    qtbot.waitUntil(lambda: window.banner.has_secret_field(), timeout=15000)
    window.banner.submit_secret(PASSWORD)
    qtbot.waitUntil(lambda: tab.contents.topLevelItemCount() > 0, timeout=20000)

    tab.set_archive(foreign)
    assert tab.current_password() is None


# ---------------------------------------------------------------------------
# Selective extract
# ---------------------------------------------------------------------------

@needs_7z
def test_nothing_is_selected_to_begin_with(window, foreign, qtbot):
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    assert tab.selected_names() == []
    assert not tab.extract_selected_button.isEnabled()


@needs_7z
def test_ticking_a_row_offers_to_extract_just_that(window, foreign, qtbot):
    tab = window.extract_tab
    tab.set_archive(foreign)
    open_contents(tab, qtbot)
    tab.check_row(0)
    assert len(tab.selected_names()) == 1
    assert tab.extract_selected_button.isEnabled()


@needs_7z
def test_a_directory_row_cannot_be_selected(window, tmp_path, qtbot):
    """A directory is archive bookkeeping. Offering it as a selectable file
    invites a request 7-Zip will answer with nothing."""
    src = tmp_path / "s"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("x" * 100, encoding="utf-8")
    path = tmp_path / "dirs.7z"
    subprocess.run([_SEVENZIP.path, "a", "-t7z", str(path), str(src / "*")],
                   check=True, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    tab = window.extract_tab
    tab.set_archive(path)
    open_contents(tab, qtbot)
    for i in range(tab.contents.topLevelItemCount()):
        item = tab.contents.topLevelItem(i)
        if item.text(tab.COL_NAME).endswith("/"):
            assert item.flags() & __import__("PySide6.QtCore", fromlist=["Qt"]) \
                .Qt.ItemFlag.ItemIsUserCheckable == \
                __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemFlag(0)


def test_a_solid_selection_is_priced_before_it_is_paid_for(window, ours, qtbot):
    """One 3 KB file out of a solid archive replays the whole stream. Saying
    so afterwards is an excuse; saying so first is a choice."""
    tab = window.extract_tab
    tab.set_archive(ours)
    open_contents(tab, qtbot)

    piped = [n for n, r in ((e.name, e.route)
                            for e in engine.list_archive(ours).entries)
             if r == "pipeline"]
    assert piped
    tab.check_named(piped[0])
    tab.extract_selected_button.click()

    assert window.banner.isVisibleTo(window)
    text = window.banner.text().lower()
    assert "solid" in text or "whole" in text
    # A number, not an adjective.
    assert any(ch.isdigit() for ch in window.banner.text())


# ---------------------------------------------------------------------------
# Through the queue, not just the engine
# ---------------------------------------------------------------------------

def test_a_selective_restore_runs_as_a_real_job(window, ours, tmp_path, qtbot):
    """The engine-level tests all call `extract_selected` directly, so none of
    them exercised the Job -> ExtractWorker handoff. The first full-suite run
    of this phase failed here and nowhere else: the worker reached back
    through a `self.job` the base class deliberately does not keep, because a
    worker on another thread must not share a mutable object with the thread
    that owns it.
    """
    from gui.models import JobState

    names = [e.name for e in engine.list_archive(ours).entries][:1]
    dest = tmp_path / "queued"
    job = window.queue.add_extract_selected(ours, dest, names)
    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=120_000)

    assert job.state is JobState.DONE, job.error
    landed = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert landed == set(names)
    assert job.result.verified == 1


def test_a_whole_archive_restore_still_runs_unchanged(window, ours, tmp_path,
                                                      qtbot):
    """The same worker with an empty selection must still mean "everything" —
    the branch that reads `selected` is the one that broke."""
    from gui.models import JobState

    dest = tmp_path / "all"
    job = window.queue.add_extract(ours, dest)
    qtbot.waitUntil(lambda: job.state.is_terminal, timeout=120_000)

    assert job.state is JobState.DONE, job.error
    assert job.result.files_restored == 2
    assert job.result.verified == 2
