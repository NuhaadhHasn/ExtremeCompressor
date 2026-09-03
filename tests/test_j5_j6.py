"""J5 and J6 — remembering the last choice, and warning before a long wait.

**J6 is the one that matters.** The measurement that justified the whole Smart
Advisor was that Extreme cost 2.7× the time of Normal for 0.17 extra
percentage points on a real corpus, and nothing told the user until after they
had waited. A comparison table makes that visible; this makes the *absolute*
cost visible too, because "3 hours" means something to a person in a way that
"0.842 MB/s" does not.

Inline, never a modal. The app has one design rule about this and I9 exists
because it was broken once; a confirmation dialogue is exactly the shape that
breaks it again.

**J5** is smaller: remember which profile was chosen for each kind of content,
so somebody who always picks Fast for video folders stops re-picking it. It
suggests, it never overrides - a remembered choice that silently outranks the
analyser would make the recommendation unpredictable.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from excmp.analyzer import Category
from excmp.planner import Profile


# ---------------------------------------------------------------------------
# J6 - the long-job warning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seconds, expected", [
    pytest.param(30, False, id="half-a-minute"),
    pytest.param(60 * 20, False, id="twenty-minutes"),
    pytest.param(60 * 44, False, id="just-under-the-line"),
    pytest.param(60 * 46, True, id="just-over-the-line"),
    pytest.param(60 * 60 * 3, True, id="three-hours"),
])
def test_only_a_genuinely_long_job_is_flagged(seconds, expected):
    from gui.suggest import long_job_warning

    assert (long_job_warning(seconds) is not None) is expected


def test_the_warning_says_how_long_in_words_a_person_uses():
    from gui.suggest import long_job_warning

    text = long_job_warning(60 * 60 * 3).lower()
    assert "hour" in text
    assert "3" in text or "three" in text


def test_it_suggests_the_thing_the_user_would_actually_do():
    """"~9 hours on this machine - run overnight?" was the shape agreed in
    C4. The number alone is a fact; the suggestion is the help."""
    text = long_job_warning_text = None
    from gui.suggest import long_job_warning

    text = long_job_warning(60 * 60 * 9).lower()
    assert "overnight" in text or "leave it" in text or "walk away" in text


def test_a_minutes_long_job_is_phrased_in_minutes():
    from gui.suggest import long_job_warning

    text = long_job_warning(60 * 50)
    assert "minute" in text.lower()


def test_the_warning_is_a_banner_not_a_dialog(qtbot, tmp_path):
    """The app's no-modal rule. I9 exists because it was broken once, and a
    confirmation dialogue is the classic way to break it again."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("gui/mainwindow.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            assert "QMessageBox" not in name, (
                f"a modal appeared in mainwindow.py: {name}")


# ---------------------------------------------------------------------------
# J5 - remembering the last choice per content type
# ---------------------------------------------------------------------------

def test_a_choice_is_remembered_for_that_content_type(qtbot):
    from gui.prefs import remembered_profile, remember_profile

    remember_profile(Category.VIDEO, Profile.FAST, scope="test-j5")
    assert remembered_profile(Category.VIDEO, scope="test-j5") is Profile.FAST


def test_different_content_types_remember_separately(qtbot):
    from gui.prefs import remembered_profile, remember_profile

    remember_profile(Category.VIDEO, Profile.FAST, scope="test-j5b")
    remember_profile(Category.TEXT, Profile.EXTREME, scope="test-j5b")
    assert remembered_profile(Category.VIDEO, scope="test-j5b") is Profile.FAST
    assert remembered_profile(Category.TEXT, scope="test-j5b") is Profile.EXTREME


def test_nothing_remembered_is_simply_none(qtbot):
    from gui.prefs import remembered_profile

    assert remembered_profile(Category.AUDIO, scope="test-j5-empty") is None


def test_a_corrupt_remembered_value_is_ignored(qtbot):
    """QSettings is a text file a user can edit. A junk value must cost the
    preference, not the app."""
    from PySide6.QtCore import QSettings

    from gui.prefs import remembered_profile

    QSettings().setValue("test-j5-bad/video", "not-a-profile")
    assert remembered_profile(Category.VIDEO, scope="test-j5-bad") is None
