"""K6 — Cancel has to reach a tool that prints nothing.

`run_tool` used to check `ctx.cancel` only when the tool emitted a line. B17's
capture showed what that means for zpaqfranz: during a `-m58` restore it
writes its header by 0.3 s and then **nothing at all** until its summary,
151 s later on a 16 MiB archive, `-verbose` included (the capture is
recorded under K6 in docs/ROADMAP.md). On a Silesia-sized Insane job the
D9 restore is about 25 minutes of that silence, and Cancel and window-close
waited for all of it.

The stand-in here is a child Python that sleeps without printing, which is
exactly the shape that defeated the per-line check.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from excmp.stages.base import StageContext, StageError, run_tool

SILENT = [sys.executable, "-c", "import time; time.sleep(60)"]


def _cancel_after(ctx: StageContext, seconds: float) -> threading.Timer:
    timer = threading.Timer(seconds, ctx.cancel.set)
    timer.daemon = True
    timer.start()
    return timer


def test_cancel_reaches_a_tool_that_prints_nothing(tmp_path):
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    _cancel_after(ctx, 0.5)
    t0 = time.monotonic()
    with pytest.raises(StageError, match="cancelled"):
        run_tool(SILENT, ctx, "silent")
    assert time.monotonic() - t0 < 10, "Cancel waited for the tool to finish"


def test_cancel_set_before_the_tool_starts_stops_it_at_once(tmp_path):
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    ctx.cancel.set()
    t0 = time.monotonic()
    with pytest.raises(StageError, match="cancelled"):
        run_tool(SILENT, ctx, "silent")
    assert time.monotonic() - t0 < 10


def test_a_killed_tool_says_cancelled_not_exit_code(tmp_path):
    """Killing the child makes it exit non-zero. Reporting that as
    "exited with code 1" would tell the user the tool failed, when the user
    stopped it."""
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    _cancel_after(ctx, 0.5)
    with pytest.raises(StageError) as err:
        run_tool(SILENT, ctx, "silent")
    assert "cancelled" in str(err.value)
    assert "exited with code" not in str(err.value)


def test_a_tool_that_finishes_is_untouched(tmp_path):
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    lines = []
    ctx.log_cb = lambda stage, line: lines.append(line)
    run_tool([sys.executable, "-c", "print('done')"], ctx, "quick")
    assert lines == ["done"]


def test_a_failing_tool_still_reports_its_exit_code(tmp_path):
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    with pytest.raises(StageError, match="exited with code 3"):
        run_tool([sys.executable, "-c", "import sys; sys.exit(3)"], ctx, "fails")
