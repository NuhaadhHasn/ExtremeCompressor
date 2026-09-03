"""I3 — job history that survives, and a queue you can reorder.

Today `clear_finished()` deletes a finished job outright and closing the window
does the same, so the record of what you compressed, when, how big it got and
which settings produced it is gone the moment you tidy up. That is the one
piece of information the app is uniquely placed to keep: it knows the profile,
the chain, the real elapsed time and the achieved ratio for every job that ever
ran on this machine.

Three things here:

- **History outlives the queue.** Clearing finished jobs moves them to history
  rather than destroying them, and history is written to disk.
- **"Compress again" reproduces the settings**, not just the paths. A job
  remembered without its profile is a job you have to reconstruct by hand.
- **Reordering, and "run next".** A queue you cannot reorder is a queue you
  have to cancel and rebuild.

The history store is deliberately bounded and deliberately dull: a JSON file
with a cap, no secrets in it, and a corrupt one costs the history and nothing
else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from excmp.planner import Profile
from gui.history import MAX_ENTRIES, HistoryEntry, append, load, clear


@pytest.fixture
def store(tmp_path) -> Path:
    return tmp_path / "history.json"


def _entry(name: str = "photos", **kw) -> HistoryEntry:
    base = dict(
        archive=f"C:/out/{name}.excmp",
        inputs=[f"C:/src/{name}"],
        profile=Profile.NORMAL.value,
        chain="precomp+sevenzip",
        orig_bytes=1_000_000,
        final_bytes=400_000,
        elapsed_s=12.5,
        finished_at="2026-09-03T10:00:00",
        state="done",
    )
    base.update(kw)
    return HistoryEntry(**base)


# ---------------------------------------------------------------------------
# It survives
# ---------------------------------------------------------------------------

def test_a_finished_job_can_be_recalled(store):
    append(_entry(), path=store)
    entries = load(store)
    assert len(entries) == 1
    assert entries[0].archive.endswith("photos.excmp")


def test_history_keeps_what_the_queue_forgets(store):
    """The whole point: the queue's own record is transient, this one is not."""
    append(_entry("a"), path=store)
    append(_entry("b"), path=store)
    assert [e.archive.split("/")[-1] for e in load(store)] == \
        ["b.excmp", "a.excmp"], "newest first"


def test_it_remembers_the_settings_not_only_the_paths(store):
    """A job recalled without its profile is a job you rebuild by hand."""
    append(_entry(profile=Profile.EXTREME.value, chain="precomp+zpaqfranz"),
           path=store)
    entry = load(store)[0]
    assert entry.profile == Profile.EXTREME.value
    assert entry.chain == "precomp+zpaqfranz"
    assert entry.inputs == ["C:/src/photos"]


def test_a_failed_job_is_recorded_too(store):
    """Knowing what did *not* work is worth as much as knowing what did."""
    append(_entry(state="failed", error="precomp: restore produced no output"),
           path=store)
    entry = load(store)[0]
    assert entry.state == "failed"
    assert "precomp" in entry.error


# ---------------------------------------------------------------------------
# It stays bounded and safe
# ---------------------------------------------------------------------------

def test_history_does_not_grow_without_limit(store):
    for n in range(MAX_ENTRIES + 25):
        append(_entry(f"job{n}"), path=store)
    entries = load(store)
    assert len(entries) == MAX_ENTRIES
    assert entries[0].archive.endswith(f"job{MAX_ENTRIES + 24}.excmp"), \
        "the newest entry was dropped instead of the oldest"


def test_no_password_is_ever_written_to_history(store):
    """History is a plain file that outlives the session. A secret in it would
    outlive the session too - and the whole point of prompting rather than
    taking one on argv is that it should not be written down."""
    append(_entry(), path=store)
    raw = store.read_text(encoding="utf-8").lower()
    for forbidden in ("password", "passphrase", "keyfile", "secret"):
        assert forbidden not in raw, f"{forbidden!r} appears in the history file"


def test_the_entry_type_has_no_password_field():
    """Belt and braces: it cannot be written if there is nowhere to put it."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(HistoryEntry)}
    assert not (names & {"password", "keyfile", "passphrase"})


def test_a_missing_store_is_empty_not_an_error(tmp_path):
    assert load(tmp_path / "nope.json") == []


def test_a_corrupt_store_costs_the_history_and_nothing_else(store):
    store.write_text("{ not json at all", encoding="utf-8")
    assert load(store) == []
    append(_entry(), path=store)          # and it recovers
    assert len(load(store)) == 1


def test_entries_with_junk_in_them_are_skipped_not_fatal(store):
    store.write_text(json.dumps(
        {"entries": [{"archive": 42}, {"nonsense": True}]}), encoding="utf-8")
    assert load(store) == []


def test_appending_survives_an_unwritable_location(tmp_path):
    """Failing to record history must never fail the job that produced it."""
    append(_entry(), path=tmp_path / "no" / "such" / "dir" / "h.json")


def test_clearing_history_is_explicit(store):
    append(_entry(), path=store)
    clear(store)
    assert load(store) == []


# ---------------------------------------------------------------------------
# Reordering the queue
# ---------------------------------------------------------------------------

def test_a_queued_job_can_be_moved(qtbot, tmp_path):
    from gui.queue_manager import QueueManager

    queue = QueueManager()
    try:
        ids = [queue.add_compress([tmp_path / f"s{n}"], tmp_path / f"o{n}.excmp",
                                  Profile.FAST).id for n in range(3)]
        queue.move_job(ids[2], -1)
        assert queue.order()[1] == ids[2]
        queue.move_job(ids[2], +1)
        assert queue.order()[2] == ids[2]
    finally:
        queue.shutdown()


def test_run_next_puts_a_job_at_the_front_of_the_waiting_ones(qtbot, tmp_path):
    from gui.queue_manager import QueueManager

    queue = QueueManager()
    try:
        ids = [queue.add_compress([tmp_path / f"s{n}"], tmp_path / f"o{n}.excmp",
                                  Profile.FAST).id for n in range(3)]
        queue.run_next(ids[2])
        # Never ahead of a job already running - that would mean stopping it.
        assert queue.order().index(ids[2]) <= 1
    finally:
        queue.shutdown()


def test_moving_past_the_ends_is_harmless(qtbot, tmp_path):
    from gui.queue_manager import QueueManager

    queue = QueueManager()
    try:
        job = queue.add_compress([tmp_path / "s"], tmp_path / "o.excmp",
                                 Profile.FAST)
        queue.move_job(job.id, -5)
        queue.move_job(job.id, +5)
        assert queue.order() == [job.id]
    finally:
        queue.shutdown()


def test_moving_an_unknown_job_does_nothing(qtbot, tmp_path):
    from gui.queue_manager import QueueManager

    queue = QueueManager()
    try:
        queue.move_job("no-such-job", -1)
        queue.run_next("no-such-job")
    finally:
        queue.shutdown()


def test_clearing_finished_moves_them_to_history_rather_than_deleting(
        qtbot, tmp_path, monkeypatch):
    """The behaviour the roadmap called out: `clear_finished()` used to delete
    the record forever."""
    import gui.history as history
    from gui.models import JobState
    from gui.queue_manager import QueueManager

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)

    queue = QueueManager()
    try:
        job = queue.add_compress([tmp_path / "s"], tmp_path / "o.excmp",
                                 Profile.FAST)
        job.state = JobState.DONE
        job.orig_bytes, job.final_bytes = 1000, 400
        queue.clear_finished()
        assert load(store), "the finished job left no trace"
    finally:
        queue.shutdown()


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

def test_the_history_tab_exists_and_starts_empty(qtbot, tmp_path, monkeypatch):
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.json")
    tab = HistoryTab()
    qtbot.addWidget(tab)
    assert tab.table.rowCount() == 0
    assert "nothing here" in tab._caption.text().lower()


def test_a_recorded_job_appears_in_the_tab(qtbot, tmp_path, monkeypatch):
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)
    history.append(_entry("holiday"), path=store)

    tab = HistoryTab()
    qtbot.addWidget(tab)
    assert tab.table.rowCount() == 1
    assert "holiday" in tab.table.item(0, 0).text()


def test_an_encrypted_job_says_so_without_saying_the_password(
        qtbot, tmp_path, monkeypatch):
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)
    history.append(_entry("secret", encrypted=True), path=store)

    tab = HistoryTab()
    qtbot.addWidget(tab)
    shown = " ".join(tab.table.item(0, c).text()
                     for c in range(tab.table.columnCount() - 1)).lower()
    assert "encrypted" in shown
    for forbidden in ("password", "hunter", "passphrase"):
        assert forbidden not in shown


def test_a_failed_job_is_shown_with_its_reason(qtbot, tmp_path, monkeypatch):
    """A history that quietly drops failures is one that flatters the tool."""
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)
    history.append(_entry("bad", state="failed", error="disk full"), path=store)

    tab = HistoryTab()
    qtbot.addWidget(tab)
    assert tab.table.rowCount() == 1
    assert "disk full" in tab.table.item(0, 0).toolTip()


def test_compress_again_emits_the_entry(qtbot, tmp_path, monkeypatch):
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)
    history.append(_entry("again"), path=store)

    tab = HistoryTab()
    qtbot.addWidget(tab)
    button = tab.table.cellWidget(0, tab.table.columnCount() - 1)
    with qtbot.waitSignal(tab.compressAgain, timeout=1000) as caught:
        button.click()
    assert caught.args[0].archive.endswith("again.excmp")


def test_a_failed_job_does_not_claim_it_compressed_to_nothing(
        qtbot, tmp_path, monkeypatch):
    """Rendering caught this: a failed job showed "3.7 GB -> 0 B", which reads
    as a spectacular success rather than as a job that never finished."""
    import gui.history as history
    from gui.widgets.history_tab import HistoryTab

    store = tmp_path / "h.json"
    monkeypatch.setattr(history, "DEFAULT_PATH", store)
    history.append(_entry("nope", state="failed", final_bytes=0,
                          error="not enough free space"), path=store)

    tab = HistoryTab()
    qtbot.addWidget(tab)
    size_cell = tab.table.item(0, 2).text()
    assert "→" not in size_cell and "0 B" not in size_cell, size_cell
