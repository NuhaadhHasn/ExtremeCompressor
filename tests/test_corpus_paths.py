"""The corpus fallback chooses by what a candidate holds, not by whether its folder exists."""

from pathlib import Path

from corpus_paths import first_holding


def _make(root: Path, *names: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).write_bytes(b"x")
    return root


def test_the_original_wins_while_it_is_complete(tmp_path):
    a = _make(tmp_path / "orig", "a.exe", "b.zip")
    b = _make(tmp_path / "copy", "a.exe", "b.zip")
    assert first_holding([a, b], ["a.exe", "b.zip"]) == a


def test_a_partly_deleted_original_falls_back_to_the_copy(tmp_path):
    """The real case: three of six files were deleted, the folder still exists."""
    a = _make(tmp_path / "orig", "a.exe")
    b = _make(tmp_path / "copy", "a.exe", "b.zip")
    assert first_holding([a, b], ["a.exe", "b.zip"]) == b


def test_a_missing_original_falls_back_to_the_copy(tmp_path):
    b = _make(tmp_path / "copy", "a.exe")
    assert first_holding([tmp_path / "gone", b], ["a.exe"]) == b


def test_when_no_candidate_is_complete_the_first_is_returned(tmp_path):
    a = _make(tmp_path / "orig", "a.exe")
    b = _make(tmp_path / "copy", "a.exe")
    assert first_holding([a, b], ["a.exe", "never.zip"]) == a
