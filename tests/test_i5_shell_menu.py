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


# -- the review of 854a203: each of these failed before the fix -----------------

def _put(root, sub, name, value, kind=None):
    import winreg
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{sub}", 0, winreg.KEY_WRITE)
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ if kind is None else kind, value)
    winreg.CloseKey(key)


def _tree(root):
    """Every key and (name, value) under the throwaway root, for before/after comparison."""
    import winreg
    out = {}

    def walk(path):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            n_sub, n_val, _ = winreg.QueryInfoKey(key)
            out[path[len(root):]] = sorted((winreg.EnumValue(key, i)[0], str(winreg.EnumValue(key, i)[1]))
                                           for i in range(n_val))
            for i in range(n_sub):
                walk(rf"{path}\{winreg.EnumKey(key, i)}")
    try:
        walk(root)
    except FileNotFoundError:
        pass
    return out


@windows_only
@pytest.mark.parametrize("kind_name", ["REG_EXPAND_SZ", "REG_BINARY", "REG_DWORD"])
def test_a_foreign_excmp_default_of_any_type_is_not_taken_over(root, kind_name):
    import winreg
    value = {"REG_EXPAND_SZ": "Foreign.%X%", "REG_BINARY": b"\x01\x02", "REG_DWORD": 7}[kind_name]
    _put(root, ".excmp", "", value, getattr(winreg, kind_name))
    S.install(PREFIX, root=root, check_exists=False)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\.excmp") as key:
        got, kind = winreg.QueryValueEx(key, "")
    assert (got, kind) == (value, getattr(winreg, kind_name))


@windows_only
def test_uninstall_leaves_what_somebody_else_put_inside_our_keys(root):
    """The verb keys are ours, but a subkey or value a user (or another tool) added under them is not."""
    S.install(PREFIX, root=root, check_exists=False)
    _put(root, r"*\shell\ExtremeCompressor.Compress\UserSub", "", "mine")
    _put(root, r"ExtremeCompressor.Archive", "EditFlags", "65536")
    _put(root, r"ExtremeCompressor.Archive\shell\Mine\command", "", "mine.exe")
    S.uninstall(root=root)
    assert _read(root, r"*\shell\ExtremeCompressor.Compress\UserSub") == "mine"
    assert _read(root, r"ExtremeCompressor.Archive", "EditFlags") == "65536"
    assert _read(root, r"ExtremeCompressor.Archive\shell\Mine\command") == "mine.exe"
    # ...while everything it wrote is gone: no value of ours is left behind.
    left = _tree(root)
    assert all(name not in ("MUIVerb", "Icon") for vals in left.values() for name, _ in vals)
    assert not _exists(root, r"*\shell\ExtremeCompressor.Compress\command")
    assert not _exists(root, r"ExtremeCompressor.Archive\shell\open")


@windows_only
def test_install_then_uninstall_restores_the_tree_exactly(root):
    _put(root, r"*\shell\SomeoneElse\command", "", "other.exe")
    _put(root, ".txt", "", "txtfile")
    before = _tree(root)
    S.install(PREFIX, root=root, check_exists=False)
    assert _tree(root) != before
    S.uninstall(root=root)
    assert _tree(root) == before


@windows_only
def test_install_writes_only_where_it_says(root):
    """Nothing outside the three trees and the one association is touched."""
    S.install(PREFIX, root=root, check_exists=False)
    tops = {k.lstrip("\\").split("\\")[0] for k in _tree(root) if k.strip("\\")}
    assert tops == {"*", "Directory", "ExtremeCompressor.Archive", ".excmp"}


@windows_only
def test_the_other_labels_and_icons_are_what_the_menu_shows(root):
    S.install(PREFIX, root=root, check_exists=False)
    icon = f'"{PREFIX[0]}",0'
    assert _read(root, r"ExtremeCompressor.Archive\shell\open", "MUIVerb") == "Extract with ExtremeCompressor"
    assert _read(root, r"ExtremeCompressor.Archive\shell\ExtractHere", "MUIVerb") == "Extract here"
    assert _read(root, r"ExtremeCompressor.Archive\shell\Verify", "MUIVerb") == "Verify archive"
    assert _read(root, r"ExtremeCompressor.Archive\shell") == "open"
    assert _read(root, r"ExtremeCompressor.Archive\DefaultIcon") == icon
    assert _read(root, r"*\shell\ExtremeCompressor.Compress", "Icon") == icon


@windows_only
def test_no_associate_leaves_excmp_alone(root):
    written = S.install(PREFIX, root=root, check_exists=False, associate=False)
    assert ".excmp" not in written and not _exists(root, ".excmp")


@windows_only
def test_uninstall_removes_only_the_value_from_a_shared_excmp_key(root):
    S.install(PREFIX, root=root, check_exists=False)
    _put(root, r".excmp\OpenWithProgids", "Other.Progid", "")
    S.uninstall(root=root)
    assert _exists(root, r".excmp\OpenWithProgids")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\.excmp") as key:
        with pytest.raises(FileNotFoundError):
            winreg.QueryValueEx(key, "")


@windows_only
def test_status_sees_a_half_installed_menu(root):
    import winreg
    S.install(PREFIX, root=root, check_exists=False)
    S._delete_tree(winreg.HKEY_CURRENT_USER, rf"{root}\ExtremeCompressor.Archive\DefaultIcon")
    st = S.status(PREFIX, root=root)
    assert not st.installed and r"ExtremeCompressor.Archive\DefaultIcon" in st.missing


@windows_only
def test_status_reports_stale_even_when_something_is_also_missing(root):
    import winreg
    S.install([r"C:\old\ExtremeCompressor.exe"], root=root, check_exists=False)
    S._delete_tree(winreg.HKEY_CURRENT_USER, rf"{root}\Directory\shell\ExtremeCompressor.Compress")
    st = S.status(PREFIX, root=root)
    assert st.missing and st.stale


@pytest.mark.parametrize("bad", [r"C:\100%1x\ec.exe", "C:\\a\nb\\ec.exe", "C:\\a\tb\\ec.exe",
                                 "\\foo\\x.exe", "/foo/x.exe", "C:\\folder\\", "C:ec.exe",
                                 r"C:\a%PATH%\ec.exe"])
def test_a_launcher_the_shell_would_rewrite_or_mis_split_is_refused(bad):
    """`%1` and friends are substituted anywhere in the template, a trailing backslash eats the
    closing quote, and a rooted path with no drive is not absolute for the shell."""
    with pytest.raises(ValueError):
        S.command_line("compress", [bad])


def test_a_unc_launcher_is_accepted():
    assert S.command_line("compress", [r"\\server\share\ec.exe"]).startswith('"\\\\server\\share')


# -- what Explorer's quoting does to a folder path ------------------------------

@pytest.mark.parametrize("arg,expected", [
    ("D:", "D:\\"),                   # CommandLineToArgvW turns "D:\" into D:" - the drive ROOT
    ('D:"', "D:\\"),
    ('C:\\x y\\"', "C:\\x y"),        # a folder given with its trailing backslash
    ("C:\\x y", "C:\\x y"),
])
def test_a_drive_root_is_not_read_as_the_drives_current_directory(arg, expected):
    got = I.parse_intake(["compress", arg])
    assert got.paths == (Path(expected),)


def test_a_lone_surrogate_is_not_a_path():
    payload = json.dumps({"action": "compress", "paths": ["C:\\a\ud800b"]}).encode("utf-8", "surrogatepass")
    assert I.from_wire(payload) is None
    assert I.parse_intake(["compress", "C:\\a\ud800b"]) is None


def test_deeply_nested_json_is_just_rejected():
    assert I.from_wire(b"[" * 200_000) is None
    assert I.from_wire(b'{"a":' * 50_000) is None


@pytest.mark.parametrize("opt", ["-platform", "-style", "-stylesheet", "-geometry", "-title"])
def test_every_qt_option_with_a_value_is_skipped_with_its_value(opt):
    got = I.parse_intake([opt, "Fusion", "compress", r"C:\a.txt"])
    assert got == I.Intake("compress", (Path(r"C:\a.txt"),))


def test_the_cli_says_it_is_windows_only_elsewhere(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _cli("status") == 1
    assert "windows" in capsys.readouterr().err.lower()


def test_one_unencodable_path_rejects_the_whole_wire_message():
    """Strict at the boundary: a message that carries one bad path is not trusted for the others."""
    payload = json.dumps({"action": "compress", "paths": ["C:\\ok.txt", "C:\\a\ud800b"]}).encode("utf-8")
    assert I.from_wire(payload) is None


@windows_only
def test_the_cli_no_associate_leaves_excmp_alone(root, monkeypatch, tmp_path):
    exe = tmp_path / "ExtremeCompressor.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(S, "default_launcher", lambda: [str(exe)])
    real = S.install
    monkeypatch.setattr(S, "install", lambda *a, **k: real(*a, **{"root": root, **k}))
    assert _cli("install", "--no-associate") == 0
    assert not _exists(root, ".excmp")
    assert _exists(root, r"*\shell\ExtremeCompressor.Compress")


@pytest.mark.parametrize("opt", ["--platform", "--style", "--stylesheet", "--qwindowtitle",
                                 "-qwindowtitle", "--session", "-session", "--geometry"])
def test_qt_options_are_skipped_with_their_value_in_either_dash_form(opt):
    """Review: `--platform offscreen` produced "Not found: offscreen"."""
    got = I.parse_intake([opt, "something", "compress", r"C:\a.txt"])
    assert got == I.Intake("compress", (Path(r"C:\a.txt"),))


# -- a frozen build: the console tool installs the menu, the WINDOW is what it runs ----------

def _frozen(monkeypatch, exe):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_frozen_the_verbs_run_the_window_even_when_the_console_tool_installed_them(monkeypatch, tmp_path):
    """The installer runs `excmp.exe shell install`; sys.executable is then the CONSOLE exe, and a menu
    that launched it would flash a console and never open the window."""
    gui = tmp_path / "ExtremeCompressor.exe"
    cli = tmp_path / "excmp.exe"
    gui.write_bytes(b"MZ")
    cli.write_bytes(b"MZ")
    _frozen(monkeypatch, cli)
    assert S.default_launcher() == [str(gui)]


def test_frozen_from_the_window_itself_it_is_the_same_program(monkeypatch, tmp_path):
    gui = tmp_path / "ExtremeCompressor.exe"
    gui.write_bytes(b"MZ")
    _frozen(monkeypatch, gui)
    assert S.default_launcher() == [str(gui)]


def test_frozen_without_the_window_next_to_it_falls_back_to_what_is_running(monkeypatch, tmp_path):
    cli = tmp_path / "excmp.exe"
    cli.write_bytes(b"MZ")
    _frozen(monkeypatch, cli)
    assert S.default_launcher() == [str(cli)]


def test_from_source_the_launcher_is_the_interpreter_running_run_gui():
    got = S.default_launcher()
    assert got[-1].endswith("run_gui.py") and len(got) == 2
