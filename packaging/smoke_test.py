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
    # The bundled tools, as the installed app has them: every one under _internal\tools\bin and verified, and Insane
    # (Precomp, then zpaqfranz) round-trips with PATH cut down to Windows' own folders, as on a clean machine.
    listing = run("tools").stdout
    for tool in ("precomp", "zpaqfranz", "flac", "balrogg"):
        line = next((ln for ln in listing.splitlines() if ln.startswith(tool + ":")), "")
        check(f"{tool} is found and comes with the app", "included with the app" in line and "tools\\bin" in line, line)
    seven = next((ln for ln in listing.splitlines() if ln.startswith("7z:")), "")
    check("7-Zip is found", " - " in seven, seven)
    win = os.environ.get("SystemRoot", r"C:\Windows")
    clean = dict(os.environ, PATH=os.pathsep.join([win + r"\System32", win]))
    ins = subprocess.run([exe, "compress", str(src), "-o", str(work / "i.excmp"), "--profile", "insane"],
                         capture_output=True, text=True, timeout=600, env=clean)
    check("insane compresses with only the bundled tools", ins.returncode == 0, ins.stderr[-300:])
    back = subprocess.run([exe, "extract", str(work / "i.excmp"), "-o", str(work / "iout")],
                          capture_output=True, text=True, timeout=600, env=clean)
    check("insane restores", back.returncode == 0, back.stderr[-300:])
    check("insane restored byte-identical",
          all((src / n).read_bytes() == (work / "iout" / "in" / n).read_bytes() for n in ("text.txt", "blob.bin")))


def frozen_gui(work: Path) -> None:
    print("2. the window and a second launch")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", EXCMP_NO_UPDATE_CHECK="1")   # never reach GitHub from a test
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
    if key_exists(VERB):
        # The product writes these keys, and so does this test: never run over somebody's real menu
        # (the uninstall at the end would remove it).
        check("no menu before", False, "the Explorer menu is already installed here; remove it first")
        return
    check("no menu before", True)
    try:
        r = subprocess.run([str(setups[-1]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                            "/CURRENTUSER", f"/DIR={target}", "/TASKS=contextmenu"], timeout=300)
        check("silent per-user install", r.returncode == 0)
        names = {p.name for p in target.iterdir()} if target.exists() else set()
        check("the programs are there", {"ExtremeCompressor.exe", "excmp.exe", "unins000.exe"} <= names)
        check("the licence texts are there (LGPL asks for them)",
              {"LICENSE", "THIRD-PARTY-NOTICES.md"} <= names
              and (target / "licenses" / "LGPL-3.0.txt").is_file() and (target / "licenses" / "GPL-3.0.txt").is_file())
        cmd = value(VERB + r"\command") or ""
        check("the verb runs the window, in the install folder",
              str(target / "ExtremeCompressor.exe") in cmd and "excmp.exe" not in cmd, cmd)
        check("an uninstall entry exists", key_exists(UNINST_KEY))
        par2 = list(target.rglob("par2.exe"))
        check("par2.exe is bundled (recovery records work)", bool(par2))
    finally:
        # Always remove what was installed, even when a check above raised or timed out.
        uninstaller = target / "unins000.exe"
        if uninstaller.exists():
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", EXCMP_NO_UPDATE_CHECK="1")
            running = subprocess.Popen([str(target / "ExtremeCompressor.exe")], env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            time.sleep(8)
            try:
                # With the window open the uninstaller must REFUSE and change nothing: it used to
                # report success, delete the uninstall entry and leave every file behind.
                refused = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                         timeout=300)
                check("the uninstaller refuses while the window is open", refused.returncode != 0,
                      f"exit code {refused.returncode}")
                check("... and leaves the program and its uninstall entry alone",
                      (target / "ExtremeCompressor.exe").exists() and key_exists(UNINST_KEY))
            finally:
                if running.poll() is None:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(running.pid)], capture_output=True)
            time.sleep(3)
            if uninstaller.exists():
                u = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                   timeout=300)
                check("silent uninstall (window closed)", u.returncode == 0)
            for _ in range(30):             # the uninstaller finishes in a helper process
                if not target.exists() or not any(target.iterdir()):
                    break
                time.sleep(1)
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
