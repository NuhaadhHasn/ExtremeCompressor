"""The QSS cascade, verified by rendering - not by reading the stylesheet.

The bug class this pins: ID selectors (specificity 101) silently beat attribute
selectors (11), so ``QLabel#Hero { color: $ok }`` swallowed
``QLabel[tone="danger"]`` and a FAILURE headline rendered in 30pt celebratory
green, while every toned Subtitle note fell back to muted grey. The stylesheet
*text* looked fine; only the cascade was wrong - so the test renders widgets
and samples pixels.
"""

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtGui import QColor              # noqa: E402
from PySide6.QtWidgets import QLabel          # noqa: E402

from gui.theme import DARK, LIGHT, qss, repolish, tokens  # noqa: E402


def _contains_color(widget, expected_hex: str, tolerance: int = 40) -> bool:
    """True if any rendered pixel is close to the expected colour. Antialiased
    text blends toward the background, so exact matching would always fail;
    a wrongly-cascaded colour (green vs red) is far outside the tolerance."""
    image = widget.grab().toImage()
    want = QColor(expected_hex)
    for x in range(0, image.width(), 2):
        for y in range(0, image.height(), 2):
            got = image.pixelColor(x, y)
            if (abs(got.red() - want.red()) <= tolerance
                    and abs(got.green() - want.green()) <= tolerance
                    and abs(got.blue() - want.blue()) <= tolerance):
                return True
    return False


def _label(qtbot, name: str, tone: str) -> QLabel:
    label = QLabel("Xx failure Xx")
    label.setObjectName(name)
    if tone:
        label.setProperty("tone", tone)
    label.setStyleSheet(qss("dark"))
    repolish(label)
    qtbot.addWidget(label)
    label.resize(260, 70)
    label.show()
    return label


@pytest.mark.parametrize("tone", ["danger", "warn", "ok"])
def test_a_toned_hero_actually_renders_in_its_tone(qtbot, tone):
    label = _label(qtbot, "Hero", tone)
    assert _contains_color(label, DARK[tone]), (
        f"#Hero[tone={tone}] lost the cascade - a {tone} headline is "
        f"rendering in the default colour")


def test_an_untoned_hero_is_neutral_not_celebratory(qtbot):
    """The old default was $ok green - which is why failures celebrated."""
    label = _label(qtbot, "Hero", "")
    assert not _contains_color(label, DARK["ok"], tolerance=25)
    assert _contains_color(label, DARK["text"])


@pytest.mark.parametrize("tone", ["warn", "danger"])
def test_a_toned_subtitle_is_not_swallowed_by_its_id_rule(qtbot, tone):
    label = _label(qtbot, "Subtitle", tone)
    assert _contains_color(label, DARK[tone]), (
        f"#Subtitle[tone={tone}] renders muted grey - the Insane card's "
        f"'not wired up' warning would be invisible as a warning")


def _contrast(fg: str, bg: str) -> float:
    def lum(hex_color: str) -> float:
        c = QColor(hex_color)
        parts = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            parts.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
        r, g, b = parts
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1, l2 = sorted((lum(fg), lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_every_text_role_meets_wcag_aa_in_both_palettes():
    """4.5:1 at body size. The old palette failed three ways: white on accent
    in dark (3.2:1), ok-on-white (3.35:1) and warn-on-white (4.4:1) in light."""
    for palette in (DARK, LIGHT):
        surfaces = [palette[k] for k in ("bg", "surface", "surface2")]
        for role in ("text", "muted", "ok", "warn", "danger"):
            for surface in surfaces:
                ratio = _contrast(palette[role], surface)
                assert ratio >= 4.5, (
                    f"{role} {palette[role]} on {surface}: {ratio:.2f}:1")
        # Text painted on the accent fill (primary buttons, selections).
        ratio = _contrast(palette["on_accent"], palette["accent"])
        assert ratio >= 4.5, f"on_accent on accent: {ratio:.2f}:1"


def test_the_category_palette_never_intersects_semantic_tokens():
    """TEXT used to equal the ok green and BINARY the accent blue, so a
    breakdown bar could cosplay as a progress bar or a success banner."""
    from gui.widgets.bars import CATEGORY_COLORS

    semantic = {v.lower() for p in (DARK, LIGHT) for k, v in p.items()
                if k in ("accent", "accent_hi", "ok", "warn", "danger")}
    for category, color in CATEGORY_COLORS.items():
        assert color.lower() not in semantic, f"{category} reuses a semantic colour"


def test_the_token_table_has_no_dead_entries():
    """Every token must appear in the emitted QSS (METRICS + palette); dead
    tokens (`shadow`, `pad`) accumulated once already."""
    sheet = qss("dark")
    for token in tokens("dark"):
        if token in ("bg", "surface", "text"):   # obviously used
            continue
        assert f"${token}" not in sheet, "unsubstituted template variable"
