"""The gate that decides whether a pixel budget is measuring the layout.

D7's first real CI run failed three layout tests on `windows-latest` - the
populated Compress page at 464px against a 447px ceiling, a profile row at
50px against 36px, and the empty page scrolling at 910x512. None was a
regression. `windows-latest` has a real `C:\\Windows\\Fonts`, so
`QT_QPA_FONTDIR` is satisfied and the glyphs are real, but it is a Windows
Server font set with larger metrics than the ones the budgets were measured
against.

The budgets are gated rather than loosened, because raising a ceiling to
accommodate an unknown font destroys what the ceiling protects: these gates
caught a window 132px taller than the target screen and a 55px progress slab
that no other test saw.

**This file tests the gate itself**, which is worth doing for one reason: the
rule has a quiet failure direction. If a font update shifts the metrics on the
development machine and the gate *skips*, every layout budget in the suite
switches off and the run still reports green - the precise failure the gates
exist to prevent, reintroduced by their own guard.
"""

from __future__ import annotations

import pytest

from tests.conftest import (REFERENCE_FONT_PROBE, font_gate_verdict,
                            measure_font_probe)

REFERENCE = (13, 129)
FOREIGN = (15, 148)          # roughly what windows-latest reported


def test_matching_metrics_run_the_budget_anywhere():
    assert font_gate_verdict(REFERENCE, REFERENCE, on_ci=True) == "run"
    assert font_gate_verdict(REFERENCE, REFERENCE, on_ci=False) == "run"


def test_a_foreign_font_stack_is_skipped_on_a_runner():
    """The budgets were never measured there, so an absolute px assertion
    would measure the runner's fonts."""
    assert font_gate_verdict(FOREIGN, REFERENCE, on_ci=True) == "skip"


def test_a_foreign_font_stack_fails_on_the_reference_machine():
    """The half that matters. Here a mismatch means the recorded reference is
    stale, and skipping would silently disable every layout gate while still
    reporting green."""
    assert font_gate_verdict(FOREIGN, REFERENCE, on_ci=False) == "fail"


def test_the_recorded_reference_is_this_machines_reality(qapp):
    """The canary. If this fails, `REFERENCE_FONT_PROBE` is stale - re-measure
    it and re-derive the ceilings in the same commit, rather than editing this
    number to make the failure go away."""
    if REFERENCE_FONT_PROBE != measure_font_probe():
        pytest.skip("not the reference font environment; "
                    "`reference_fonts` reports on that, loudly, by design")
    assert REFERENCE_FONT_PROBE == measure_font_probe()


def test_the_probe_is_two_independent_numbers():
    """Height alone is too coarse: two font stacks can share a line height
    and still lay text out at different widths, which is what moves a page's
    height once anything wraps."""
    assert len(REFERENCE_FONT_PROBE) == 2
    assert all(isinstance(n, int) and n > 0 for n in REFERENCE_FONT_PROBE)
