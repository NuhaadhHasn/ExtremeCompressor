# Releasing a new version (E5)

An installed copy updates itself from this project's GitHub **releases**, and only to a release that carries the
owner's signature (`excmp/updater.py`). To publish one, from the laptop that holds the signing key
(`%USERPROFILE%\.excmp\update-signing.key`, **back it up**):

1. Bump `__version__` in `excmp/__init__.py` (plain numbers: `0.2.0`), commit, merge to `main`, CI green.
2. `packaging\build.cmd` builds `dist\ExtremeCompressor-<version>-setup.exe`.
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
