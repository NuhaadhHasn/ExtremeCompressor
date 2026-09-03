"""J5 — remember which profile was chosen for each kind of content.

Somebody who always picks Fast for video folders should stop having to pick
it. That is the whole feature.

**It suggests; it never overrides.** The analyser's recommendation stays the
recommendation — a remembered choice that silently outranked it would make the
suggestion unpredictable, and unpredictable is worse than occasionally
re-clicking. The remembered profile is offered, and the user is told it is
being offered because of what they did last time.

Keyed on the *dominant* category rather than the exact mix, because "this is a
folder of video" is the judgement a person actually repeats. A key nobody can
predict is a key nobody benefits from remembering.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from excmp.analyzer import Category
from excmp.planner import Profile

#: QSettings group. A parameter so tests do not fight over the real one.
DEFAULT_SCOPE = "profile-memory"


def remember_profile(category: Category, profile: Profile,
                     scope: str = DEFAULT_SCOPE) -> None:
    QSettings().setValue(f"{scope}/{category.value}", profile.value)


def remembered_profile(category: Category,
                       scope: str = DEFAULT_SCOPE) -> Profile | None:
    """The profile last chosen for this kind of content, or None.

    QSettings is a text file somebody can edit, so an unrecognised value is
    discarded rather than trusted - it costs the preference, never the app.
    """
    raw = QSettings().value(f"{scope}/{category.value}")
    if not isinstance(raw, str):
        return None
    try:
        return Profile(raw)
    except ValueError:
        return None
