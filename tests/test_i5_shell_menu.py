"""I5: the Explorer right-click menu (Windows 10 path: HKCU registry verbs, no admin).

Three parts, each testable on its own:

* ``excmp.intake`` - the command-line contract the verbs call (``compress``,
  ``extract``, ``extract-here``, ``verify``) and the strict JSON a second
  process hands the running one;
* ``excmp.shellmenu`` - writes and removes the verbs. Every test here writes
  under a throwaway ``HKCU\\Software\\ExtremeCompressorTests\\<uuid>`` root,
  **never** under the real ``Software\\Classes``: a test that edited the
  developer's real shell menu would be a defect of its own;
* ``gui.singleinstance`` / ``MainWindow.handle_intake`` - Explorer starts ONE
  PROCESS PER SELECTED FILE, so the first becomes the window and the rest
  forward their paths to it.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

from excmp import intake as I
from excmp import shellmenu as S

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the registry is Windows-only")


# -- the command-line contract -------------------------------------------------

def test_an_action_then_paths():
    got = I.parse_intake(["compress", r"C:\a b\one.txt", r"C:\two"])
    assert got == I.Intake("compress", (Path(r"C:\a b\one.txt"), Path(r"C:\two")))


@pytest.mark.parametrize("action", ["compress", "extract", "extract-here", "verify"])
def test_every_action_parses(action):
    assert I.parse_intake([action, r"C:\x\y.excmp"]).action == action


def test_a_plain_path_is_inferred_from_what_it_is():
    """Drag a file onto the exe, or "Open with": no verb name arrives."""
    assert I.parse_intake([r"C:\x\a.excmp"]).action == "extract"
    assert I.parse_intake([r"C:\x\A.EXCMP"]).action == "extract"
    assert I.parse_intake([r"C:\x\a.txt"]).action == "compress"
    assert I.parse_intake([r"C:\x\a.txt", r"C:\x\b.excmp"]).action == "compress"


def test_a_plain_launch_is_not_an_intake():
    assert I.parse_intake([]) is None
    assert I.parse_intake(["compress"]) is None             # an action with nothing to act on
    assert I.parse_intake(["", "  "]) is None


def test_qt_flags_are_not_paths():
    got = I.parse_intake(["-platform", "offscreen", "compress", r"C:\a.txt"])
    assert got.action == "compress" and got.paths == (Path(r"C:\a.txt"),)


def test_paths_are_deduplicated_ignoring_case_and_keep_their_order():
    got = I.parse_intake(["compress", r"C:\A.txt", r"C:\b.txt", r"c:\a.TXT"])
    assert got.paths == (Path(r"C:\A.txt"), Path(r"C:\b.txt"))


def test_surrounding_quotes_and_space_are_stripped():
    got = I.parse_intake(["compress", '  "C:\\a b\\c.txt" '])
    assert got.paths == (Path(r"C:\a b\c.txt"),)


@pytest.mark.parametrize("action", ["extract", "extract-here", "verify"])
def test_the_one_archive_actions_take_only_the_first_path(action):
    got = I.parse_intake([action, r"C:\one.excmp", r"C:\two.excmp"])
    assert got.paths == (Path(r"C:\one.excmp"),)


# -- the IPC boundary: any local process can write to the pipe ---------------

def test_an_intake_survives_the_wire():
    original = I.Intake("compress", (Path(r"C:\a b\c.txt"), Path(r"D:\ü.txt")))
    assert I.from_wire(I.to_wire(original)) == original


@pytest.mark.parametrize("bad", [
    b"", b"not json", b"[]", b"null", b'{"action": "format-disk", "paths": ["C:\\\\a"]}',
    b'{"action": "compress"}', b'{"action": "compress", "paths": "C:\\\\a"}',
    b'{"action": "compress", "paths": [1, 2]}', b'{"action": "compress", "paths": []}',
    b'{"action": 7, "paths": ["C:\\\\a"]}', b"\xff\xfe\x00",
])
def test_the_wire_rejects_what_it_does_not_understand(bad):
    assert I.from_wire(bad) is None


def test_the_wire_has_size_limits():
    many = json.dumps({"action": "compress", "paths": [f"C:\\f{i}" for i in range(I.MAX_PATHS + 1)]})
    assert I.from_wire(many.encode()) is None
    huge = json.dumps({"action": "compress", "paths": ["C:\\" + "x" * 40_000]})
    assert I.from_wire(huge.encode()) is None
    assert I.from_wire(b"{" + b" " * (I.MAX_WIRE_BYTES + 1)) is None


def test_a_path_with_a_nul_is_rejected():
    assert I.from_wire(json.dumps({"action": "compress", "paths": ["C:\\a\x00b"]}).encode()) is None


# -- the verbs -------------------------------------------------------------------

@pytest.fixture
def root():
    """A throwaway registry root, removed afterwards (see the module docstring)."""
    if sys.platform != "win32":
        pytest.skip("the registry is Windows-only")
    import winreg
    path = rf"Software\ExtremeCompressorTests\{uuid.uuid4().hex}"
    yield path
    S._delete_tree(winreg.HKEY_CURRENT_USER, path)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\ExtremeCompressorTests")
    except OSError:
        pass


PREFIX = [r"C:\Program Files\Extreme Compressor\ExtremeCompressor.exe"]


def _read(root, sub, name=""):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{sub}") as key:
        return winreg.QueryValueEx(key, name)[0]


def _exists(root, sub):
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{sub}"))
        return True
    except FileNotFoundError:
        return False


def test_the_command_line_quotes_the_program_and_the_argument():
    cmd = S.command_line("compress", PREFIX)
    assert cmd == '"C:\\Program Files\\Extreme Compressor\\ExtremeCompressor.exe" compress "%1"'


def test_a_script_launcher_is_two_quoted_parts():
    cmd = S.command_line("extract", [r"C:\py\pythonw.exe", r"C:\my repo\run_gui.py"])
    assert cmd == '"C:\\py\\pythonw.exe" "C:\\my repo\\run_gui.py" extract "%1"'


@pytest.mark.parametrize("bad", ['C:\\a"b\\x.exe', "", "relative.exe", "C:\\a\x00.exe"])
def test_a_launcher_that_cannot_be_quoted_safely_is_refused(bad):
    with pytest.raises(ValueError):
        S.command_line("compress", [bad])


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError):
        S.command_line("format-disk", PREFIX)


@windows_only
def test_install_writes_the_verbs_and_status_sees_them(root):
    written = S.install(PREFIX, root=root, check_exists=False)
    assert written
    assert _read(root, r"*\shell\ExtremeCompressor.Compress", "MUIVerb") == "Compress with ExtremeCompressor"
    assert _read(root, r"*\shell\ExtremeCompressor.Compress\command") == S.command_line("compress", PREFIX)
    assert _read(root, r"Directory\shell\ExtremeCompressor.Compress\command") == S.command_line("compress", PREFIX)
    assert _read(root, r"ExtremeCompressor.Archive\shell\open\command") == S.command_line("extract", PREFIX)
    assert _read(root, r"ExtremeCompressor.Archive\shell\ExtractHere\command") == S.command_line("extract-here", PREFIX)
    assert _read(root, r"ExtremeCompressor.Archive\shell\Verify\command") == S.command_line("verify", PREFIX)
    assert _read(root, ".excmp") == "ExtremeCompressor.Archive"
    st = S.status(PREFIX, root=root)
    assert st.installed and not st.stale and not st.missing


@windows_only
def test_install_twice_changes_nothing(root):
    S.install(PREFIX, root=root, check_exists=False)
    S.install(PREFIX, root=root, check_exists=False)
    assert S.status(PREFIX, root=root).installed


@windows_only
def test_uninstall_removes_exactly_what_install_wrote_and_nothing_else(root):
    import winreg
    # Somebody else's verbs and association, which must survive.
    for sub, val in ((r"*\shell\SomeoneElse\command", "other.exe"),
                     (r"Directory\shell\ExtremeCompressor.Other\command", "x.exe")):
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{sub}", 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, val)
        winreg.CloseKey(key)
    S.install(PREFIX, root=root, check_exists=False)
    removed = S.uninstall(root=root)
    assert removed
    assert not _exists(root, r"*\shell\ExtremeCompressor.Compress")
    assert not _exists(root, r"Directory\shell\ExtremeCompressor.Compress")
    assert not _exists(root, "ExtremeCompressor.Archive")
    assert not _exists(root, ".excmp")
    assert _read(root, r"*\shell\SomeoneElse\command") == "other.exe"
    assert _read(root, r"Directory\shell\ExtremeCompressor.Other\command") == "x.exe"
    assert not S.status(PREFIX, root=root).installed


@windows_only
def test_a_foreign_excmp_association_is_not_taken_over_or_removed(root):
    import winreg
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\.excmp", 0, winreg.KEY_WRITE)
    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "SomeOther.Progid")
    winreg.CloseKey(key)
    S.install(PREFIX, root=root, check_exists=False)
    assert _read(root, ".excmp") == "SomeOther.Progid"
    S.uninstall(root=root)
    assert _read(root, ".excmp") == "SomeOther.Progid"


@windows_only
def test_uninstall_on_a_clean_machine_is_not_an_error(root):
    assert S.uninstall(root=root) == []


@windows_only
def test_status_notices_a_verb_that_points_somewhere_else(root):
    S.install([r"C:\old\ExtremeCompressor.exe"], root=root, check_exists=False)
    st = S.status(PREFIX, root=root)
    assert st.installed and st.stale          # installed, but from another path


@windows_only
def test_install_refuses_a_launcher_that_does_not_exist(root):
    with pytest.raises(FileNotFoundError):
        S.install([r"C:\definitely\not\here\ExtremeCompressor.exe"], root=root)


@windows_only
def test_the_default_root_is_the_users_classes_not_the_machines():
    assert S.CLASSES_ROOT == r"Software\Classes"


# -- the CLI: ``excmp shell install | uninstall | status`` ----------------------

def _cli(*argv):
    from excmp import cli
    return cli.main(["shell", *argv])


@windows_only
def test_the_cli_installs_reports_and_removes(root, monkeypatch, capsys, tmp_path):
    exe = tmp_path / "ExtremeCompressor.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(S, "default_launcher", lambda: [str(exe)])
    monkeypatch.setattr(S, "CLASSES_ROOT", root)
    # The functions bound their default at definition time, so route through the module attribute.
    for name in ("install", "uninstall", "status"):
        real = getattr(S, name)
        monkeypatch.setattr(S, name, (lambda r: lambda *a, **k: r(*a, **{"root": root, **k}))(real))
    assert _cli("status") == 1                       # not installed: a non-zero answer a script can test
    assert "not installed" in capsys.readouterr().out.lower()
    assert _cli("install") == 0
    assert "installed" in capsys.readouterr().out.lower()
    assert _cli("status") == 0
    assert _cli("uninstall") == 0
    assert _cli("status") == 1


@windows_only
def test_the_cli_refuses_to_install_a_launcher_that_is_not_there(root, monkeypatch, capsys):
    monkeypatch.setattr(S, "default_launcher", lambda: [r"C:\not\there\ExtremeCompressor.exe"])
    real = S.install
    monkeypatch.setattr(S, "install", lambda *a, **k: real(*a, **{"root": root, **k}))
    assert _cli("install") == 1
    assert "not" in capsys.readouterr().err.lower()


def test_the_cli_needs_an_action():
    with pytest.raises(SystemExit):
        _cli()
