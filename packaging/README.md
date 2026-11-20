# Packaging (E3): a frozen build and a per-user installer

**Status, 2026-11-21: built and smoke-tested, not signed.** PyInstaller 6.22.3 and Inno Setup 6.7.3.
The first build was 110 MB / 33.8 MB; after a review dropped the DLLs of the excluded Qt modules,
`dist\ExtremeCompressor\` is **92 MB** on disk and `ExtremeCompressor-0.1.0-setup.exe` is **27.7 MB**.
`python packaging\smoke_test.py` repeats the checks (it writes the real Explorer-menu keys, so it refuses to
run when they exist, and always uninstalls). It proves, among others, that the frozen `excmp.exe` writes and
uses PAR2 recovery records, and that **an uninstall with the window open is refused and changes nothing**
(the window holds a mutex the installer's `AppMutex` watches; it used to return 0 and leave every file).

| File | What it is |
|---|---|
| `ExtremeCompressor.spec` | PyInstaller, `--onedir`: `ExtremeCompressor.exe` (window) and `excmp.exe` (console tool) in one folder |
| `entry_cli.py` | the console tool's entry point |
| `installer.iss` | Inno Setup: per user, no administrator, optional Explorer menu task, clean uninstall |
| `build.cmd` | PyInstaller, then `iscc` |
| `smoke_test.py` | runs the frozen programs and an install / uninstall round trip on a real build |
| `../tests/test_e3_packaging_files.py` | keeps the inputs honest without needing a build (the part that fails silently) |

## What the smoke test showed (2026-11-21)

1. `excmp.exe` compressed and restored a folder byte-identically: the bundled `zstandard`, `cryptography`,
   `lepton` and friends are all there.
2. `ExtremeCompressor.exe` starts (offscreen Qt), and a **second launch handed its file to it in 0.6 s and
   exited**, leaving one window: the single-instance mutex and pipe work frozen too.
3. The installer installed silently per user in 9 s. The registered verb was
   `"<install folder>\ExtremeCompressor.exe" compress "%1"` - the WINDOW, although the console tool is what
   ran `shell install` (a first version of I5 would have registered `excmp.exe`; a test pins the fix). The
   uninstaller left no file and no registry key, including the `.excmp` association and the uninstall entry.

## What was decided, and why

* **Two executables.** The window has no console; the installer needs something that prints and takes
  `shell install`.
* **The roadmap's exclude list was wrong for the code as it is now.** It names `QtSvg` and `QtNetwork`;
  the icons need `QtSvg` and I5's single-instance pipe needs `QtNetwork`. Following it would build an app
  that dies at start-up. The spec keeps both, and a test reads the real imports so the list cannot drift
  into that again. (92 MB, not the roadmap's 71 MB: it kept those two modules and the toast and crypto
  libraries the app has gained since.)
* **Never UPX** (it raises antivirus detections), **never `--onefile`** (re-extracts every launch).
* **Per-user install** because the menu is per user (HKCU); nothing here needs administrator rights.

## To build

1. `pip install pyinstaller` (in `requirements-dev.txt`) and Inno Setup 6 (`winget install JRSoftware.InnoSetup
   --scope user`, hash-checked by winget; `build.cmd` finds a per-user install).
2. `packaging\build.cmd`, then `python packaging\smoke_test.py`.

## Not done

* **Code signing (E4)** needs an account with a signing service, and **auto-update (E5)** a release channel
  to poll. Until then an installer is unsigned and **Windows SmartScreen will warn**.
* **The external tools are not bundled.** 7-Zip, Precomp, zpaqfranz and the rest are found on the machine or
  fetched by the app (E1); the frozen app finds them the same way the source one does. Fast works with
  nothing else installed.
* An application icon: `assets\` holds SVG icons only, no `.ico`.
* The Windows 11 top-level menu (a signed sparse package, after E4).

## Licences

Shipping this folder ships PySide6, which is LGPL-3.0. The one-folder build keeps the Qt libraries as
separate DLLs under `_internal\PySide6`, which can be replaced - what the LGPL asks of a dynamically
linked use. The Qt notices belong in the installer's licence page before anything is distributed
(`THIRD-PARTY-NOTICES.md`). The repo is private and nothing is distributed today.
