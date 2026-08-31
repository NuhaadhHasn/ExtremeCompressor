"""Wave 3c: the transport sidecar, and an app that remembers (G6 + I1).

**G6 — `.sha256` sidecar.** Publishing is a single atomic `replace`, so
hashing the finished container there is a handful of lines. The value is
transport: a recipient who never installs this app can still check the
download arrived intact, with `sha256sum -c` or QuickSFV.

Decided this session: **opt-in, remembered.** Not default-on. A second file
appearing beside every archive is a surprise, and "no surprise outputs" has
been a standing rule since the engine's first commit ("inputs are never
modified; outputs are written to .tmp and atomically renamed"). One checkbox,
and it stays where you put it.

**I1 — Settings.** The app persisted exactly one thing (window geometry) and
forgot everything else on every launch: threads, temp folder, theme. The
roadmap has called that "the loudest daily annoyance" for four phases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from excmp import engine
from excmp.cli import main as cli_main
from excmp.planner import Profile
from excmp.stages.base import StageContext
from excmp.verify import hash_file


def _tiny(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("data " * 500, encoding="utf-8")
    return src


# ---------------------------------------------------------------------------
# G6: the sidecar
# ---------------------------------------------------------------------------

def test_no_sidecar_unless_asked(tmp_path):
    """The standing rule: no output the user did not ask for."""
    out = tmp_path / "a.excmp"
    engine.compress([_tiny(tmp_path)], out, Profile.FAST,
                    StageContext(temp_dir=tmp_path / "t"))
    assert not out.with_suffix(".excmp.sha256").exists()
    assert list(tmp_path.glob("*.sha256")) == []


def test_the_sidecar_matches_the_published_archive(tmp_path):
    out = tmp_path / "a.excmp"
    result = engine.compress([_tiny(tmp_path)], out, Profile.FAST,
                             StageContext(temp_dir=tmp_path / "t"), sidecar=True)
    side = Path(str(out) + ".sha256")
    assert side.is_file()
    assert result.sidecar == side

    # Hashed AFTER the atomic rename, so it describes the file that shipped -
    # not the .tmp twin that existed a moment earlier.
    text = side.read_text(encoding="utf-8")
    assert text.startswith(hash_file(out))
    # sha256sum's own layout, so `sha256sum -c a.excmp.sha256` just works.
    assert text.strip() == f"{hash_file(out)}  {out.name}"
    assert text.endswith("\n")


def test_the_sidecar_names_the_file_not_its_full_path(tmp_path):
    """`sha256sum -c` resolves relative to the working directory, so an
    absolute path here breaks the moment the pair is moved - which is the
    only situation a transport sidecar exists for."""
    out = tmp_path / "deep" / "a.excmp"
    out.parent.mkdir()
    engine.compress([_tiny(tmp_path)], out, Profile.FAST,
                    StageContext(temp_dir=tmp_path / "t"), sidecar=True)
    body = Path(str(out) + ".sha256").read_text(encoding="utf-8")
    assert str(out.parent) not in body


def test_a_failed_compress_leaves_no_sidecar(tmp_path, monkeypatch):
    """A sidecar for an archive that does not exist is worse than none."""
    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(engine, "_verify_before_publish", boom)
    out = tmp_path / "a.excmp"
    with pytest.raises(RuntimeError):
        engine.compress([_tiny(tmp_path)], out, Profile.FAST,
                        StageContext(temp_dir=tmp_path / "t"), sidecar=True)
    assert not Path(str(out) + ".sha256").exists()


def test_the_cli_takes_sha256(tmp_path, capsys):
    out = tmp_path / "a.excmp"
    assert cli_main(["compress", str(_tiny(tmp_path)), "-o", str(out),
                     "-p", "fast", "--temp", str(tmp_path / "t"),
                     "--sha256"]) == 0
    assert Path(str(out) + ".sha256").is_file()
    assert "sha256" in capsys.readouterr().out.lower()


def test_the_cli_writes_none_by_default(tmp_path):
    out = tmp_path / "a.excmp"
    assert cli_main(["compress", str(_tiny(tmp_path)), "-o", str(out),
                     "-p", "fast", "--temp", str(tmp_path / "t")]) == 0
    assert not Path(str(out) + ".sha256").exists()


# ---------------------------------------------------------------------------
# I1: settings that survive a relaunch
# ---------------------------------------------------------------------------

pytest.importorskip("pytestqt")

from gui.mainwindow import MainWindow   # noqa: E402


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


def test_there_is_a_settings_tab(window):
    labels = [window.tabs.tabText(i).split(" (")[0]
              for i in range(window.tabs.count())]
    assert labels == ["Compress", "Extract", "Activity", "Settings"]


def test_settings_lists_the_tools_the_status_strip_has_to_elide(window):
    """The strip elides the tools line at 910px by design. Settings is where
    the full inventory lives, which is what made that eliding acceptable."""
    text = window.settings_tab.tools_text()
    assert "7z" in text.lower()


def test_the_choices_survive_a_relaunch(qtbot):
    """The app persisted exactly one thing - window geometry - and forgot
    threads, temp folder and theme on every launch."""
    first = MainWindow()
    qtbot.addWidget(first)
    first.settings_tab.sidecar_toggle.setChecked(True)
    first.settings_tab.threads.setValue(3)
    first.settings_tab.open_after_extract.setChecked(True)
    first.close()
    first.queue.shutdown()

    second = MainWindow()
    qtbot.addWidget(second)
    try:
        assert second.settings_tab.sidecar_toggle.isChecked() is True
        assert second.settings_tab.threads.value() == 3
        assert second.settings_tab.open_after_extract.isChecked() is True
    finally:
        second.queue.shutdown()


def test_the_sidecar_preference_reaches_the_job(window, qtbot, tmp_path):
    src = _tiny(tmp_path)
    window.queue.pause()
    window.settings_tab.sidecar_toggle.setChecked(True)
    with qtbot.waitSignal(window.analysisFinished, timeout=60_000):
        window.add_paths([src])
    window.start_compression()

    assert window.queue.jobs[0].sidecar is True


def test_the_theme_is_remembered_too(qtbot):
    first = MainWindow(theme="dark")
    qtbot.addWidget(first)
    first.toggle_theme()
    chosen = first.theme_name
    first.close()
    first.queue.shutdown()

    second = MainWindow()
    qtbot.addWidget(second)
    try:
        assert second.theme_name == chosen
    finally:
        second.queue.shutdown()


def test_the_thread_label_does_not_claim_physical_cores(window):
    """os.cpu_count() reports LOGICAL processors - the target machine is a
    2-core i7-3540M that reports 4. "auto (4 cores)" sat directly beside a
    description calling it a two-core laptop."""
    label = window.settings_tab.threads.specialValueText().lower()
    assert "core" not in label, label
    assert "auto" in label
