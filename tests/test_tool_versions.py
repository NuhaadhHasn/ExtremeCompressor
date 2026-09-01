"""Version floors, and the legacy tools we find but will never run.

Two unrelated-looking facts share this file because both are about the gap
between *what is installed* and *what we will actually do with it*.

**The floor.** E1 wants a minimum version per tool, not just a pinned hash:
7-Zip below **24.09** carries CVE-2025-0411, a Mark-of-the-Web bypass. We do
not depend on 7-Zip's own sanitizer — `excmp/safepath.py` validates every
archive-supplied name ourselves — so this is not an exploit path *for us*.
It is still the wrong binary to be feeding untrusted archives to, and a user
running it deserves to be told rather than to find out from a CVE feed.

**The legacy tool.** B11 removed SREP from every compression chain (not
OSI-licensed, and `srep64.exe` once failed its own decompression checksum on
1 of 3 runs over byte-identical input). The stage survives *only* so archives
written before B11 still restore. So the app genuinely does find a tool it
will never choose — and the honest answer is to say which, not to hide it.
Hiding a tool that can still run would leave someone debugging a legacy
archive with no way to see it was found.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from excmp.tools import (LEGACY_ONLY, SECURITY_FLOOR, below_floor,
                         find_tools, parse_tool_version)


# ---------------------------------------------------------------------------
# Parsing a version out of a banner
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("banner, expected", [
    # What this machine prints today, and what it printed before the upgrade.
    ("7-Zip 26.02 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-06-25", (26, 2)),
    ("7-Zip 24.07 (x64) : Copyright (c) 1999-2024 Igor Pavlov : 2024-06-19", (24, 7)),
    # The reduced console build puts a bracketed tag where the version goes.
    ("7-Zip (a) 16.02 : Copyright (c) 1999-2016 Igor Pavlov : 2016-05-21", (16, 2)),
    # p7zip does the same with a different bracket.
    ("7-Zip [64] 16.02 : Copyright (c) 1999-2016 Igor Pavlov", (16, 2)),
    # Old builds had no colon at all.
    ("7-Zip 9.20  Copyright (c) 1999-2010 Igor Pavlov  2010-11-18", (9, 20)),
])
def test_the_version_is_read_from_the_banner(banner, expected):
    """`split()[1]` is the obvious implementation and it is wrong twice over:
    on the reduced build it returns "(a)" and on p7zip "[64]"."""
    assert parse_tool_version(banner) == expected


def test_a_banner_from_something_that_is_not_7_zip_is_not_guessed_at():
    """NanaZip and other forks print their own name. Reporting a fork's
    version number as a 7-Zip version would apply a floor that means nothing
    for that binary — better to say "unknown" than to say something false."""
    assert parse_tool_version("NanaZip 5.0 : Copyright (c) 2023 M2-Team") is None
    assert parse_tool_version("") is None
    assert parse_tool_version("some tool with no version at all") is None


def test_the_leading_blank_line_does_not_defeat_it():
    """`7z.exe` with no arguments prints an empty line *before* its banner.
    A reader that trusts line 0 gets nothing."""
    assert parse_tool_version("\n\n7-Zip 26.02 (x64) : Copyright") == (26, 2)


# ---------------------------------------------------------------------------
# Comparing against the floor
# ---------------------------------------------------------------------------

def test_versions_compare_as_numbers_not_as_text():
    """The bug this test exists to prevent: `"9.20" > "24.09"` is True as
    strings, so a lexical comparison clears the floor for a 2010 binary —
    exactly the one the floor is meant to catch."""
    assert parse_tool_version("7-Zip 9.20 Copyright") < SECURITY_FLOOR["7z"]
    assert parse_tool_version("7-Zip 24.09 Copyright") >= SECURITY_FLOOR["7z"]
    assert parse_tool_version("7-Zip 24.07 Copyright") < SECURITY_FLOOR["7z"]


def test_a_zero_padded_minor_is_not_octal_or_a_string():
    assert parse_tool_version("7-Zip 24.09 x") == (24, 9)
    assert parse_tool_version("7-Zip 24.09 x") > parse_tool_version("7-Zip 24.7 x")


def test_below_floor_names_what_was_found_and_what_is_needed():
    from excmp.tools import ToolInfo

    old = {"7z": ToolInfo("7z", "C:/7z.exe", "7-Zip 24.07 (x64) : Copyright")}
    (name, found, needed), = below_floor(old)
    assert name == "7z"
    assert "24.07" in found
    assert "24.09" in needed


def test_a_current_tool_is_not_reported():
    from excmp.tools import ToolInfo

    ok = {"7z": ToolInfo("7z", "C:/7z.exe", "7-Zip 26.02 (x64) : Copyright")}
    assert below_floor(ok) == []


def test_an_unreadable_version_is_not_reported_as_vulnerable():
    """"We could not tell" is not "it is old". Reporting an unknown version as
    below the floor would cry wolf on every fork and every build whose banner
    we do not recognise."""
    from excmp.tools import ToolInfo

    assert below_floor({"7z": ToolInfo("7z", "C:/7z.exe", "")}) == []
    assert below_floor({"7z": None}) == []


def test_this_machine_is_current():
    """A live check, not a fixture. It is the one that would have caught the
    24.07 install, and it is the one that will fail if the floor is raised
    past what is installed here."""
    stale = below_floor(find_tools(with_versions=True))
    assert stale == [], f"install a newer build: {stale}"


# ---------------------------------------------------------------------------
# Tools we find but will never choose
# ---------------------------------------------------------------------------

def test_srep_is_marked_legacy():
    assert "srep" in LEGACY_ONLY


def test_a_legacy_tool_is_still_discovered():
    """It has to be. `SrepStage.available()` goes through `find_tools()`, and
    a pre-B11 archive cannot be restored without it — there is a test that
    builds one and restores it."""
    assert "srep" in find_tools()


def test_no_compression_chain_can_reach_a_legacy_tool():
    """The invariant that makes the label true. If a future edit put SREP back
    into a chain, this fails rather than the app quietly resuming use of a
    tool that is neither OSI-clean nor trustworthy on restore."""
    from excmp.planner import _CHAINS

    for profile, chain in _CHAINS.items():
        # Entries are (stage_id, tool_name | None); the tool is what gets run.
        tools = {tool for _stage, tool in chain if tool}
        assert not (tools & LEGACY_ONLY), \
            f"{profile} would run a legacy-only tool: {sorted(tools & LEGACY_ONLY)}"


def test_every_legacy_name_is_a_tool_we_actually_look_for():
    """Guards against the label drifting onto a tool that no longer exists."""
    from excmp.tools import CANDIDATES

    assert LEGACY_ONLY <= set(CANDIDATES)


# ---------------------------------------------------------------------------
# The three surfaces that show the inventory
# ---------------------------------------------------------------------------

pytest.importorskip("pytestqt")


@pytest.fixture
def window(qtbot):
    from gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_the_status_strip_no_longer_advertises_a_tool_it_will_never_run(window):
    """The wart from docs/NEXT-SESSION-START-HERE.md section 8. The strip said
    "Tools found: 7z, precomp, srep" with no qualifier, naming a tool B11
    removed from every chain."""
    text = window._tools_text.lower()
    if "srep" in text:
        assert "srep (legacy)" in text, text


def test_settings_explains_what_legacy_means(window):
    """A bare "(legacy)" is a label, not an explanation. The full inventory
    page is where there is room to say what it means."""
    from excmp.tools import find_tools

    if find_tools().get("srep") is None:
        pytest.skip("srep not installed on this machine")
    text = window.settings_tab.tools_text().lower()
    assert "legacy" in text
    assert "never used to compress" in text


def test_a_stale_tool_is_named_with_its_two_versions_and_the_reason(qtbot):
    """"Your 7-Zip is old" is not actionable. Which version, which version is
    needed, and what it fixes — all three, or the user cannot decide."""
    from excmp.tools import ToolInfo
    from gui.widgets.settings_tab import SettingsTab

    tab = SettingsTab({"7z": ToolInfo("7z", "C:/7z.exe",
                                      "7-Zip 24.07 (x64) : Copyright")},
                      Path(tempfile.gettempdir()))
    qtbot.addWidget(tab)
    text = tab.tools_text()
    assert "24.07" in text and "24.09" in text
    assert "CVE-2025-0411" in text


def test_a_current_tool_gets_no_scolding(qtbot):
    from excmp.tools import ToolInfo
    from gui.widgets.settings_tab import SettingsTab

    tab = SettingsTab({"7z": ToolInfo("7z", "C:/7z.exe",
                                      "7-Zip 26.02 (x64) : Copyright")},
                      Path(tempfile.gettempdir()))
    qtbot.addWidget(tab)
    assert "update it" not in tab.tools_text().lower()
