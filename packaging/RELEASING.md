# Releasing a new version (E5)

An installed copy updates itself from this project's GitHub **releases**, and only to a release that carries the
owner's signature (`excmp/updater.py`). To publish one, from the laptop that holds the signing key
(`%USERPROFILE%\.excmp\update-signing.key`, **back it up**):

1. Bump `__version__` in `excmp/__init__.py` (plain numbers: `0.2.0`), commit, merge to `main`, CI green.
2. `packaging\build.cmd` builds `dist\ExtremeCompressor-<version>-setup.exe`. It first runs `packaging\stage_tools.py`, which
   checks the bundled tools against their pins (offline when `tools\bin` is complete; it downloads only what is missing and
   needs a 7-Zip on the machine to unpack the 7-Zip Extra package once).
3. `python packaging\smoke_test.py` (real install and uninstall, per user).
4. `python tools\release_sign.py release dist\ExtremeCompressor-<version>-setup.exe` writes `dist\SHA256SUMS`
   and `dist\SHA256SUMS.sig`.
5. `gh release create v<version> dist\ExtremeCompressor-<version>-setup.exe dist\SHA256SUMS dist\SHA256SUMS.sig
   --title "v<version>" --notes "..."`  (publishing is public and cannot be fully taken back: look first).

The release must be a normal release (not a draft or pre-release), its tag must be `v<version>`, and the three
files must carry exactly those names. A copy that finds anything missing refuses the update and says why.

**The key.** Running copies accept only updates signed by the key whose public half is `PUBLIC_KEY` in
`excmp/updater.py`. If the private key is lost or leaks: make a new pair (`python tools\release_sign.py keygen`),
put the new public key in `updater.py`, build, and install that build **by hand** once; every copy updates by
itself after that. The repository must be public for unauthenticated copies to read its releases.

## winget (`winget install NuhaadhHasn.ExtremeCompressor`)

After a release is public (step 5), make and check the manifest:

    python tools\make_winget_manifest.py --version <version> --sums dist\SHA256SUMS
    winget validate --manifest dist\winget\manifests\n\NuhaadhHasn\ExtremeCompressor\<version>

It points only at this project's own release asset and uses its SHA-256. To publish it, fork
`microsoft/winget-pkgs`, copy the `manifests\n\NuhaadhHasn\ExtremeCompressor\<version>` folder into the same place in
the fork, and open a pull request; Microsoft's checks run on it. (The installer is not code-signed yet, so its
checks may take a manual review. Each later release is the same three steps; the app's own updater and winget
upgrade the same per-user install in place.)
