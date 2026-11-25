"""The Extract tab opens other people's archives, and shows what is inside.

The honesty boundary is the whole feature. An `.excmp` restore is checked
against a SHA-256 ledger; a foreign zip cannot be, because there is no ledger
in it. If the UI renders both the same way, the guarantee stops meaning
anything — so these tests pin the *wording*, not just the plumbing.
"""

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from gui.mainwindow import MainWindow          # noqa: E402
from gui.models import Job, JobKind, JobState  # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def foreign(tmp_path):
    path = tmp_path / "somebody-elses.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.txt", "hello")
    return path


def test_the_file_dialog_no_longer_says_excmp_only(window):
    """`extract()` has always been able to shell `7z x` at anything. The only
    thing stopping people was a file filter."""
    spec = window.extract_tab.archive_filter()
    lowered = spec.lower()
    for fmt in ("zip", "7z", "rar", "tar", "iso", "cab"):
        assert fmt in lowered, f"{fmt} missing from {spec}"
    assert "excmp" in lowered


def test_choosing_a_foreign_archive_says_what_will_be_missing(window, foreign):
    """Before you press anything: this one has no ledger."""
    window.extract_tab.set_archive(foreign)
    note = window.extract_tab.status.text().lower()
    assert "no sha-256 ledger" in note or "not created by" in note


def test_choosing_one_of_ours_promises_the_verified_restore(window, tmp_path):
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 500, encoding="utf-8")
    ours = tmp_path / "ours.excmp"
    engine.compress([src], ours, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))

    window.extract_tab.set_archive(ours)
    assert "no sha-256 ledger" not in window.extract_tab.status.text().lower()


def test_a_foreign_archive_cannot_be_verified(window, foreign):
    """Verify means "compare against the ledger". With no ledger the button is
    not merely disabled - it says why, because a greyed control that never
    explains itself is the thing this UI keeps refusing to ship."""
    window.extract_tab.set_archive(foreign)
    assert not window.extract_tab.verify_button.isEnabled()
    assert "fingerprint" in window.extract_tab.verify_button.toolTip().lower()


def test_a_foreign_extract_result_never_borrows_the_verified_wording(window,
                                                                     tmp_path):
    from excmp.engine import ExtractResult

    job = Job(kind=JobKind.EXTRACT, inputs=[tmp_path / "x.zip"],
              out_path=tmp_path / "out", state=JobState.DONE, elapsed_s=2.0)
    job.result = ExtractResult(out_dir=tmp_path / "out", files_restored=2,
                               verified=0, elapsed_s=2.0, ledger_backed=False)
    window.results.show_job(job)

    hero = window.results.hero.text()
    sub = window.results.subline.text().lower()
    assert "2" in hero
    assert "verified" not in sub, sub
    assert "ledger" in sub


def test_our_own_extract_still_says_verified(window, tmp_path):
    from excmp.engine import ExtractResult

    job = Job(kind=JobKind.EXTRACT, inputs=[tmp_path / "x.excmp"],
              out_path=tmp_path / "out", state=JobState.DONE, elapsed_s=2.0)
    job.result = ExtractResult(out_dir=tmp_path / "out", files_restored=6,
                               verified=6, elapsed_s=2.0, ledger_backed=True)
    window.results.show_job(job)
    assert "verified" in window.results.subline.text().lower()


# ---------------------------------------------------------------------------
# I2-lite: the listing
# ---------------------------------------------------------------------------

def test_the_listing_starts_collapsed_and_fills_from_the_manifest(window,
                                                                  tmp_path, qtbot):
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "readme.txt").write_text("shrink me. " * 2000, encoding="utf-8")
    (src / "noise.bin").write_bytes(bytes((i * 97 + 3) % 256 for i in range(40_000)))
    ours = tmp_path / "ours.excmp"
    engine.compress([src], ours, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))

    tab = window.extract_tab
    assert not tab.contents.isVisibleTo(tab)
    tab.set_archive(ours)
    tab.contents_toggle.click()
    qtbot.wait(30)

    assert tab.contents.isVisibleTo(tab)
    assert tab.contents.topLevelItemCount() == 2
    names = {tab.contents.topLevelItem(i).text(0) for i in range(2)}
    assert names == {"src/readme.txt", "src/noise.bin"}


def test_the_listing_shows_why_a_file_was_stored(window, tmp_path, qtbot):
    """The column no other archiver has."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    src = tmp_path / "src"
    src.mkdir()
    (src / "noise.bin").write_bytes(bytes((i * 97 + 3) % 256 for i in range(40_000)))
    ours = tmp_path / "ours.excmp"
    engine.compress([src], ours, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))

    tab = window.extract_tab
    tab.set_archive(ours)
    tab.contents_toggle.click()
    qtbot.wait(30)

    item = tab.contents.topLevelItem(0)
    row = " ".join(item.text(c) for c in range(tab.contents.columnCount()))
    assert "kept as is" in row.lower()          # the plain-words name of the store route
    assert item.text(tab.COL_WHY), "a stored file with no explanation on screen"


def test_a_foreign_archive_can_be_listed_since_g2(window, foreign, qtbot):
    """Was `test_a_foreign_archive_says_it_cannot_be_listed_yet`.

    Wave 3b deliberately refused here, because an empty list reads as "this
    archive is empty" and that is worse than saying no. G2 wired up the
    `7z l -slt` grammar, so the refusal is no longer the honest answer — the
    listing is. The full replacement coverage lives in `test_gui_g2.py`,
    which pins the part that still matters: it must not borrow our columns.
    """
    tab = window.extract_tab
    tab.set_archive(foreign)
    assert tab.contents_toggle.isEnabled()
    assert "not wired up" not in tab.contents_toggle.toolTip().lower()


def test_the_cards_own_promise_changes_with_the_archive(window, foreign, tmp_path):
    """The standing blurb promised a SHA-256 ledger. Above a status line saying
    "this one has none", that is a contradiction the user reads first."""
    from excmp import engine
    from excmp.planner import Profile
    from excmp.stages.base import StageContext

    tab = window.extract_tab
    assert "checked against the fingerprint saved" in tab._blurb.text().lower()

    tab.set_archive(foreign)
    assert "checked against the fingerprint saved" not in tab._blurb.text().lower()
    assert "other tools" in tab._blurb.text().lower()

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 300, encoding="utf-8")
    ours = tmp_path / "ours.excmp"
    engine.compress([src], ours, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    tab.set_archive(ours)
    assert "checked against the fingerprint saved" in tab._blurb.text().lower()
