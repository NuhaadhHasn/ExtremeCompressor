"""Drag files out of the Restore tab's list.

Pull a file out of the list into Explorer and it is restored there, without going through "Restore selected". The list
unpacks the chosen files into a staging folder first (checked against the archive's SHA-256 for our own archives, as any
restore is) and hands Explorer those files to copy.

Two rules drive the design, and each has a test:
* Unpacking happens while the mouse button is down, on the window's own thread, so it is capped: past the cap the drag
  is refused in plain words and "Restore selected" (which runs in the queue, with progress) is the way.
* Explorer copies from the staging folder after the drop, possibly for a while, so it is never deleted right after a
  drop; it goes at the next drag, when the window closes, and a stale one is swept at start-up.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt                          # noqa: E402

from excmp import engine                              # noqa: E402
from excmp.planner import Profile                     # noqa: E402
from excmp.stages.base import StageContext            # noqa: E402
from excmp.tools import find_tools                    # noqa: E402
from gui.mainwindow import MainWindow                 # noqa: E402
from gui.widgets import extract_tab as et             # noqa: E402

needs_7z = pytest.mark.skipif(find_tools().get("7z") is None, reason="7z.exe not installed")

TEXT = "shrink me. " * 2000
NOISE = bytes((i * 97 + 3) % 256 for i in range(40_000))


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(et, "_DRAG_TEMP_ROOT", tmp_path / "drag-temp")
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.queue.shutdown()


@pytest.fixture
def ours(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "readme.txt").write_text(TEXT, encoding="utf-8")
    (src / "noise.bin").write_bytes(NOISE)
    (src / "sub" / "inner.txt").write_text("inner " * 3000, encoding="utf-8")
    out = tmp_path / "ours.excmp"
    engine.compress([src], out, Profile.FAST, StageContext(temp_dir=tmp_path / "t"))
    return out


def _open(window, qtbot, archive):
    tab = window.extract_tab
    tab.archive_edit.setText(str(archive))
    tab.contents_toggle.setChecked(True)
    qtbot.waitUntil(lambda: tab.contents.topLevelItemCount() > 0, timeout=15000)
    qtbot.wait(50)
    return tab


def _items(tab, *tails):
    """The rows whose name ends with one of ``tails`` (names carry the folder they were archived under)."""
    found = []
    for i in range(tab.contents.topLevelItemCount()):
        item = tab.contents.topLevelItem(i)
        name = item.data(tab.COL_NAME, Qt.ItemDataRole.UserRole)
        if any(name.endswith(t) for t in tails):
            found.append(item)
    assert len(found) == len(tails), (tails, [tab.contents.topLevelItem(i).text(0)
                                              for i in range(tab.contents.topLevelItemCount())])
    return found


def test_a_dragged_file_is_a_real_verified_copy_of_the_original(window, qtbot, ours):
    tab = _open(window, qtbot, ours)
    paths = tab.stage_for_drag([i.data(tab.COL_NAME, Qt.ItemDataRole.UserRole) for i in _items(tab, "readme.txt", "noise.bin")])
    by = {p.name: p for p in paths}
    assert by["readme.txt"].read_text(encoding="utf-8") == TEXT
    assert by["noise.bin"].read_bytes() == NOISE
    assert all(p.is_file() for p in paths)


def test_a_file_inside_a_folder_is_dragged_as_the_file_itself(window, qtbot, ours):
    tab = _open(window, qtbot, ours)
    (item,) = _items(tab, "inner.txt")
    (path,) = tab.stage_for_drag([item.data(tab.COL_NAME, Qt.ItemDataRole.UserRole)])
    assert path.name == "inner.txt" and path.read_text(encoding="utf-8") == "inner " * 3000


def test_the_mime_data_carries_local_file_urls_for_explorer(window, qtbot, ours):
    tab = _open(window, qtbot, ours)
    mime = tab.contents.mimeData(_items(tab, "readme.txt", "noise.bin"))
    assert mime is not None and mime.hasUrls()
    got = sorted(Path(u.toLocalFile()).name for u in mime.urls())
    assert got == ["noise.bin", "readme.txt"]
    assert all(u.isLocalFile() and Path(u.toLocalFile()).is_file() for u in mime.urls())


def test_the_list_can_only_be_copied_from_never_moved(window, qtbot, ours, monkeypatch):
    """Dragging out must never be able to remove or rewrite anything: the only action offered is Copy."""
    from PySide6.QtWidgets import QTreeWidget
    tab = _open(window, qtbot, ours)
    assert tab.contents.dragEnabled()
    assert tab.contents.dragDropMode().name == "DragOnly"          # nothing can be dropped onto the list either
    passed = []
    monkeypatch.setattr(QTreeWidget, "startDrag", lambda self, actions: passed.append(actions))
    tab.contents.startDrag(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)   # even if Qt offers Move
    assert passed == [Qt.DropAction.CopyAction]                     # what is passed on to Qt: Copy only


def test_rows_that_are_only_folders_are_not_draggable(window, qtbot, ours):
    from PySide6.QtWidgets import QTreeWidgetItem
    tab = _open(window, qtbot, ours)
    folder = QTreeWidgetItem(tab.contents)              # how the list makes a folder row: named, and not checkable
    folder.setText(tab.COL_NAME, "sub/")
    folder.setData(tab.COL_NAME, Qt.ItemDataRole.UserRole, "sub")
    folder.setFlags(folder.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
    assert tab.contents.mimeData([folder]) is None
    assert "folders" in tab.drag_note.text()
    # and a folder in a mixed pick is left out, the files still go
    mixed = tab.contents.mimeData([folder, *_items(tab, "noise.bin")])
    assert mixed is not None and [Path(u.toLocalFile()).name for u in mixed.urls()] == ["noise.bin"]


def test_past_the_cap_the_drag_is_refused_in_plain_words(window, qtbot, ours, monkeypatch):
    tab = _open(window, qtbot, ours)
    monkeypatch.setattr(et, "DRAG_LIMIT", 1000)
    mime = tab.contents.mimeData(_items(tab, "readme.txt"))
    assert mime is None
    note = tab.drag_note.text()
    assert not tab.drag_note.isHidden()
    assert "Restore selected" in note               # where to go instead
    assert "Traceback" not in note


def test_a_small_pick_from_a_stored_only_part_is_not_held_to_the_size_of_the_whole_archive(window, qtbot, ours, monkeypatch):
    """A file kept as is is read straight out of the zip, so only ITS size counts; a compressed (solid) one needs the
    whole chain replayed, so the whole archive's size counts."""
    tab = _open(window, qtbot, ours)
    routes = {e.name.rsplit("/", 1)[-1]: e.route for e in tab.current_listing().entries if not e.is_dir}
    assert routes["noise.bin"] == "store" and routes["readme.txt"] == "pipeline"
    monkeypatch.setattr(et, "DRAG_LIMIT", 50_000)               # noise 40,000 < cap < the files together
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is not None
    assert tab.contents.mimeData(_items(tab, "readme.txt")) is None


def _name(tab, tail):
    (item,) = _items(tab, tail)
    return item.data(tab.COL_NAME, Qt.ItemDataRole.UserRole)


def test_the_next_drag_does_not_delete_what_explorer_may_still_be_copying(window, qtbot, ours):
    """A drop returns before Explorer has finished copying. Deleting the previous staging folder at the next drag lost a
    file in review, so a RECENT one stays."""
    tab = _open(window, qtbot, ours)
    (first,) = tab.stage_for_drag([_name(tab, "noise.bin")])
    (second,) = tab.stage_for_drag([_name(tab, "readme.txt")])
    assert first.exists() and second.exists()


def test_an_old_staging_folder_goes_at_the_next_drag_and_few_are_kept(window, qtbot, ours, monkeypatch):
    tab = _open(window, qtbot, ours)
    (first,) = tab.stage_for_drag([_name(tab, "noise.bin")])
    stage, made = tab._drag_stages[0]
    tab._drag_stages[0] = (stage, made - 10_000)                    # long ago
    (second,) = tab.stage_for_drag([_name(tab, "readme.txt")])
    assert not first.exists() and second.exists()
    paths = [second]
    for _ in range(5):
        paths += tab.stage_for_drag([_name(tab, "noise.bin")])
    assert len(tab._drag_stages) <= et._KEEP_STAGES
    assert sum(p.exists() for p in paths) <= et._KEEP_STAGES


def test_closing_removes_every_staging_folder_and_a_failed_unpack_leaves_none(window, qtbot, ours, monkeypatch):
    from PySide6.QtWidgets import QApplication
    tab = _open(window, qtbot, ours)
    a = tab.stage_for_drag([_name(tab, "noise.bin")])
    b = tab.stage_for_drag([_name(tab, "readme.txt")])
    QApplication.instance().aboutToQuit.emit()                       # what closing the app does, not a direct call
    assert not a[0].exists() and not b[0].exists()
    tab.cleanup_drag()                                               # twice is harmless

    before = set(et._DRAG_TEMP_ROOT.iterdir())
    monkeypatch.setattr(et.engine, "extract_selected", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is None
    assert set(et._DRAG_TEMP_ROOT.iterdir()) == before                # nothing half-unpacked is left behind


def test_a_stale_staging_folder_from_an_earlier_run_is_swept(tmp_path):
    root = tmp_path / "drag-temp"
    old, fresh = root / "excmp-drag-old", root / "excmp-drag-new"
    old.mkdir(parents=True), fresh.mkdir(parents=True)
    (old / "f.bin").write_bytes(b"x")
    import os, time
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    (root / "keep-me.txt").write_text("not ours", encoding="utf-8")   # only excmp-drag-* is ever touched
    et.sweep_stale_drag_folders(root, max_age_s=86400)
    assert not old.exists() and fresh.exists() and (root / "keep-me.txt").exists()


def test_opening_the_tab_sweeps_stale_folders(qtbot, tmp_path, monkeypatch):
    """The sweep is called when the tab is made (a test that calls the function directly cannot tell)."""
    import os, time
    root = tmp_path / "drag-temp"
    old = root / "excmp-drag-old"
    old.mkdir(parents=True)
    t = time.time() - 3 * 86400
    os.utime(old, (t, t))
    monkeypatch.setattr(et, "_DRAG_TEMP_ROOT", root)
    qtbot.addWidget(et.ExtractTab())
    assert not old.exists()


def _junction(link: Path, target: Path) -> None:
    import subprocess
    out = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if out.returncode:
        pytest.skip("cannot make a junction here: " + out.stdout + out.stderr)


@pytest.fixture
def someone_elses_folder(tmp_path):
    """A folder that is not ours, with a read-only file in it and a user document."""
    import os, stat
    folder = tmp_path / "someone-elses"
    folder.mkdir()
    ro = folder / "readonly.txt"
    ro.write_text("keep", encoding="utf-8")
    os.chmod(ro, stat.S_IREAD)
    (folder / "user.doc").write_text("precious", encoding="utf-8")
    yield folder
    os.chmod(ro, stat.S_IWRITE)


def test_the_sweep_never_goes_through_a_junction(tmp_path, someone_elses_folder):
    import os, stat, time
    root = tmp_path / "drag-temp"
    root.mkdir()
    link = root / "excmp-drag-evil"
    _junction(link, someone_elses_folder)
    t = time.time() - 3 * 86400
    os.utime(link, (t, t))
    et.sweep_stale_drag_folders(root, max_age_s=86400)
    assert (someone_elses_folder / "user.doc").read_text(encoding="utf-8") == "precious"
    assert not os.stat(someone_elses_folder / "readonly.txt").st_mode & stat.S_IWRITE      # still read-only


def test_a_root_that_is_itself_a_junction_is_left_alone(tmp_path, someone_elses_folder):
    import os, time
    stale = someone_elses_folder / "excmp-drag-notours"
    stale.mkdir()
    (stale / "user.doc").write_text("mine", encoding="utf-8")
    t = time.time() - 3 * 86400
    os.utime(stale, (t, t))
    root = tmp_path / "drag-temp"
    _junction(root, someone_elses_folder)
    et.sweep_stale_drag_folders(root, max_age_s=86400)
    assert (stale / "user.doc").read_text(encoding="utf-8") == "mine"


def test_a_staging_folder_is_refused_when_the_root_is_a_junction(window, qtbot, ours, tmp_path, someone_elses_folder, monkeypatch):
    tab = _open(window, qtbot, ours)
    root = tmp_path / "linked-root"
    _junction(root, someone_elses_folder)
    monkeypatch.setattr(et, "_DRAG_TEMP_ROOT", root)
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is None
    assert "not an ordinary folder" in tab.drag_note.text()
    assert sorted(p.name for p in someone_elses_folder.iterdir()) == ["readonly.txt", "user.doc"]


def test_rmtree_force_does_not_walk_into_or_touch_a_junction(tmp_path, someone_elses_folder):
    """The shared helper's second pass used `rglob`, which went through a junction and stripped the read-only bit."""
    import os
    from excmp import tempclean
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("x", encoding="utf-8")
    _junction(tree / "link", someone_elses_folder)
    listed = tempclean._entries_without_links(str(tree))
    assert str(tree / "a.txt") in listed
    assert not any("link" in Path(p).name or "readonly" in p or "user.doc" in p for p in listed)
    tempclean.rmtree_force(tree)
    assert (someone_elses_folder / "user.doc").exists() and (someone_elses_folder / "readonly.txt").exists()


@needs_7z
def test_a_file_dragged_out_of_somebody_elses_zip_works_too(window, qtbot, tmp_path):
    z = tmp_path / "theirs.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/guide.txt", "hello " * 500)
        zf.writestr("docs/data.csv", "a,b,c\n" * 400)
    tab = _open(window, qtbot, z)
    (item,) = _items(tab, "guide.txt")
    (path,) = tab.stage_for_drag([item.data(tab.COL_NAME, Qt.ItemDataRole.UserRole)])
    assert path.read_text(encoding="utf-8") == "hello " * 500


def test_a_failure_is_said_in_the_note_not_in_a_dialog(window, qtbot, ours, monkeypatch):
    tab = _open(window, qtbot, ours)

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(et.engine, "extract_selected", boom)
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is None
    assert "disk full" in tab.drag_note.text()


# ---------------------------------------------------------------------------
# What the adversarial review found
# ---------------------------------------------------------------------------

def test_the_cap_is_time_as_well_as_bytes(window, qtbot, ours, monkeypatch):
    """A byte count alone let a slow chain (Insane restores at about 0.1 MB/s) freeze the window for many minutes."""
    tab = _open(window, qtbot, ours)
    tab.current_listing().stages = ["precomp", "zpaqfranz"]            # the slow chain (Insane)
    monkeypatch.setattr(et, "DRAG_SECONDS", 0.3)                       # a stored file (io rate) fits; the chain (~0.7 s) does not
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is not None
    assert tab.contents.mimeData(_items(tab, "readme.txt")) is None
    assert "about" in tab.drag_note.text() and "Restore selected" in tab.drag_note.text()


def test_a_slow_chain_is_priced_slow(window, qtbot, ours, monkeypatch):
    tab = _open(window, qtbot, ours)
    entries = [e for e in tab.current_listing().entries if e.route == "pipeline"]
    tab.current_listing().stages = ["precomp", "zpaqfranz"]            # Insane
    work, seconds = tab._drag_cost(entries[:1], ours)
    assert work > 0 and seconds > 100 * (work / 100e6)                # far slower than a plain copy


def test_a_split_archive_is_refused_not_joined_on_the_gui_thread(window, qtbot, ours, tmp_path):
    import shutil
    part = tmp_path / "ours.excmp.001"
    shutil.copy2(ours, part)
    tab = _open(window, qtbot, part)
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is None
    assert "several parts" in tab.drag_note.text()


def test_files_come_from_the_archive_the_list_was_read_from(window, qtbot, ours, tmp_path):
    """List A, retype the Archive field to B: the rows are still A's, so the drag must hand out A's files."""
    other_src = tmp_path / "other"
    (other_src).mkdir()
    (other_src / "readme.txt").write_text("this is B", encoding="utf-8")
    b = tmp_path / "b.excmp"
    engine.compress([other_src], b, Profile.FAST, StageContext(temp_dir=tmp_path / "t2"))
    tab = _open(window, qtbot, ours)
    tab.archive_edit.setText(str(b))
    (p,) = tab.stage_for_drag([_name(tab, "readme.txt")])
    assert p.read_text(encoding="utf-8") == TEXT                       # A's content, not "this is B"


def test_two_picks_with_the_same_file_name_are_refused_together(window, qtbot, tmp_path):
    src = tmp_path / "dup"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    (src / "a" / "x.txt").write_text("one " * 800, encoding="utf-8")
    (src / "b" / "x.txt").write_text("two " * 800, encoding="utf-8")
    arc = tmp_path / "dup.excmp"
    engine.compress([src], arc, Profile.FAST, StageContext(temp_dir=tmp_path / "t3"))
    tab = _open(window, qtbot, arc)
    both = [i for i in (tab.contents.topLevelItem(k) for k in range(tab.contents.topLevelItemCount()))]
    assert tab.contents.mimeData(both) is None
    assert "x.txt" in tab.drag_note.text() and "one at a time" in tab.drag_note.text()


def test_a_successful_drag_clears_an_earlier_refusal(window, qtbot, ours, monkeypatch):
    tab = _open(window, qtbot, ours)
    monkeypatch.setattr(et, "DRAG_LIMIT", 1000)
    assert tab.contents.mimeData(_items(tab, "readme.txt")) is None
    refusal = tab.drag_note.text()
    monkeypatch.setattr(et, "DRAG_LIMIT", 128 * 1024 * 1024)
    assert tab.contents.mimeData(_items(tab, "readme.txt")) is not None
    assert tab.drag_note.text() != refusal and "Drag files out" in tab.drag_note.text()


def test_a_damaged_member_is_not_handed_out(window, qtbot, ours, tmp_path):
    """The stored file is read straight out of the zip; flip a byte in it and the check must stop it."""
    import zipfile
    with zipfile.ZipFile(ours) as zf:
        info = next(i for i in zf.infolist() if i.filename.endswith("noise.bin") or "noise" in i.filename)
        at = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 100
    data = bytearray(ours.read_bytes())
    data[at] ^= 0xFF
    ours.write_bytes(bytes(data))
    tab = _open(window, qtbot, ours)
    assert tab.contents.mimeData(_items(tab, "noise.bin")) is None
    assert "Could not unpack" in tab.drag_note.text()
    assert "\n" not in tab.drag_note.text()                             # one line, not a dump


def test_our_own_drag_released_over_our_own_window_is_not_taken_as_an_archive(window, qtbot, ours):
    tab = _open(window, qtbot, ours)

    class Event:
        def __init__(self, source):
            self._s = source

        def source(self):
            return self._s
    assert tab._is_own_drag(Event(tab.contents)) is True
    assert tab._is_own_drag(Event(None)) is False                       # a drop from Explorer is still welcome


@needs_7z
def test_a_zip_with_names_that_differ_only_by_case_is_refused_not_guessed(window, qtbot, tmp_path):
    """7-Zip matches names case-insensitively: dragging `A.txt` used to hand out `a.txt`'s content."""
    z = tmp_path / "case.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("A.txt", "upper content " * 50)
        zf.writestr("a.txt", "lower content " * 50)
    tab = _open(window, qtbot, z)
    item = next(tab.contents.topLevelItem(i) for i in range(tab.contents.topLevelItemCount())
                if tab.contents.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "A.txt")
    assert tab.contents.mimeData([item]) is None
    assert "same name" in tab.drag_note.text() or "capital" in tab.drag_note.text()


@needs_7z
def test_the_engine_refuses_an_ambiguous_foreign_pick_for_restore_selected_too(tmp_path):
    z = tmp_path / "dup.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("A.txt", "upper " * 50)
        zf.writestr("a.txt", "lower " * 50)
        zf.writestr("only.txt", "unique " * 50)
    ctx = StageContext(temp_dir=tmp_path / "t")
    with pytest.raises(engine.ContainerError, match="capital letters|same name"):
        engine.extract_selected(z, ["A.txt"], tmp_path / "out", ctx)
    engine.extract_selected(z, ["only.txt"], tmp_path / "out2", ctx)       # a unique name still works
    assert (tmp_path / "out2" / "only.txt").read_text(encoding="utf-8") == "unique " * 50


@needs_7z
def test_a_foreign_archive_that_is_not_a_zip_is_not_dragged_even_if_named_zip(window, qtbot, tmp_path):
    """The suffix is not the format: a tar renamed .zip is one solid stream with no honest size."""
    import tarfile
    src = tmp_path / "t.txt"
    src.write_text("hello " * 500, encoding="utf-8")
    z = tmp_path / "really-a-tar.zip"
    with tarfile.open(z, "w") as tf:
        tf.add(src, arcname="t.txt")
    tab = _open(window, qtbot, z)
    assert tab.contents.mimeData(_items(tab, "t.txt")) is None
    assert "Restore selected" in tab.drag_note.text()
