"""Smoke test of a REAL build: the frozen programs and the installer round trip (E3).

Not part of the pytest suite: it needs ``packaging\\build.cmd`` to have run, it installs into a
scratch folder, and it briefly writes the Explorer-menu keys under the real
``HKCU\\Software\\Classes`` (that is what the product does) and removes them again.

    python packaging\\smoke_test.py            # after packaging\\build.cmd

It checks, in this order:
  1. ``excmp.exe`` compresses and restores a folder byte-identically (the bundled libraries work);
  2. ``ExtremeCompressor.exe`` starts, and a second launch hands its file to it and exits;
  3. the installer installs per user with the menu task, the registered verb runs the WINDOW in the
     install folder (not the console tool that ran ``shell install``), the uninstaller removes every
     file and every key.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = DIST / "ExtremeCompressor"
APP_ID = "{7D57A03D-876B-4BF2-9569-D11D4F586D01}"
UNINST_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
VERB = r"Software\Classes\*\shell\ExtremeCompressor.Compress"
ok = True


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok
    ok &= bool(condition)
    print(f"  [{'ok' if condition else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def key_exists(path: str) -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, path))
        return True
    except FileNotFoundError:
        return False


def value(path: str, name: str = ""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except FileNotFoundError:
        return None


def frozen_cli(work: Path) -> None:
    print("1. the console tool")
    src = work / "in"
    src.mkdir()
    (src / "text.txt").write_text("smoke test. " * 20000)
    (src / "blob.bin").write_bytes(os.urandom(50_000))
    exe = str(APP / "excmp.exe")
    run = lambda *a: subprocess.run([exe, *a], capture_output=True, text=True, timeout=180)  # noqa: E731
    check("compress", run("compress", str(src), "-o", str(work / "t.excmp"), "--profile", "fast").returncode == 0)
    check("extract", run("extract", str(work / "t.excmp"), "-o", str(work / "out")).returncode == 0)
    same = all((src / n).read_bytes() == (work / "out" / "in" / n).read_bytes()
               for n in ("text.txt", "blob.bin"))
    check("restored byte-identical", same)


def frozen_gui(work: Path) -> None:
    print("2. the window and a second launch")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    quiet = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    exe = str(APP / "ExtremeCompressor.exe")
    first = subprocess.Popen([exe, "compress", str(work / "in" / "text.txt")], **quiet)
    time.sleep(12)
    check("the window is still running after 12 s", first.poll() is None)
    second = subprocess.Popen([exe, "compress", str(work / "in" / "blob.bin")], **quiet)
    try:
        code = second.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("a second launch hands its file over and exits", code == 0)
    check("the first is still the only window", first.poll() is None)
    for p in (first, second):
        if p.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)


def installer_round_trip(work: Path) -> None:
    print("3. the installer")
    setups = sorted(DIST.glob("ExtremeCompressor-*-setup.exe"))
    if not setups:
        check("a setup program exists", False, "run packaging\\build.cmd first")
        return
    target = work / "installed"
    check("no menu before", not key_exists(VERB))
    r = subprocess.run([str(setups[-1]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/CURRENTUSER", f"/DIR={target}", "/TASKS=contextmenu"], timeout=300)
    check("silent per-user install", r.returncode == 0)
    names = {p.name for p in target.iterdir()} if target.exists() else set()
    check("the programs are there", {"ExtremeCompressor.exe", "excmp.exe", "unins000.exe"} <= names)
    cmd = value(VERB + r"\command") or ""
    check("the verb runs the window, in the install folder",
          str(target / "ExtremeCompressor.exe") in cmd and "excmp.exe" not in cmd, cmd)
    check("an uninstall entry exists", key_exists(UNINST_KEY))
    u = subprocess.run([str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       timeout=300)
    time.sleep(3)
    check("silent uninstall", u.returncode == 0)
    check("no file left", not target.exists() or not any(target.iterdir()))
    check("no menu or association key left",
          not any(key_exists(k) for k in (VERB, r"Software\Classes\Directory\shell\ExtremeCompressor.Compress",
                                          r"Software\Classes\ExtremeCompressor.Archive",
                                          r"Software\Classes\.excmp")))
    check("no uninstall entry left", not key_exists(UNINST_KEY))


def main() -> int:
    if not (APP / "ExtremeCompressor.exe").is_file():
        print("no build found: run packaging\\build.cmd first")
        return 2
    with tempfile.TemporaryDirectory(prefix="excmp-smoke-") as tmp:
        work = Path(tmp)
        frozen_cli(work)
        frozen_gui(work)
        installer_round_trip(work)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
