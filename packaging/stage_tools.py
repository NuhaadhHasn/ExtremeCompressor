"""Assemble the external tools the installer carries: ``build/bundled-tools/<name>/<version>/...``.

    python packaging/stage_tools.py            # offline first: uses tools/bin, downloads only what is missing

The layout is the one ``excmp.toolfetch`` already reads (``<root>/<name>/<version>/<exe_relpath>``), so the
installed app finds and verifies them exactly as a source checkout does: PyInstaller puts this folder at
``_internal/tools/bin`` and ``toolfetch._install_root()`` points there.

Nothing is trusted on the way in. Every tool is checked against the pins in ``toolfetch.TOOL_MANIFEST``
(every file in the executable's folder, and nothing extra) before it is copied and again where it was
copied to, so a modified or half-downloaded copy in the developer's tools folder can never reach an
installer. The build machine needs no network when ``tools/bin`` is complete: the data was paid for once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from excmp import toolfetch  # noqa: E402

DEFAULT_SOURCE = ROOT / "tools" / "bin"
DEFAULT_DEST = ROOT / "build" / "bundled-tools"


class StageError(RuntimeError):
    """A tool is missing, or does not match its pin, so no installer may be built."""


@contextmanager
def _tools_root(root: Path):
    """``toolfetch`` reads its root from the environment at call time; point it at ``root`` for a while."""
    old = os.environ.get("EXCMP_TOOLS_DIR")
    os.environ["EXCMP_TOOLS_DIR"] = str(root)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("EXCMP_TOOLS_DIR", None)
        else:
            os.environ["EXCMP_TOOLS_DIR"] = old


def _exe_dir(spec: toolfetch.ToolSpec, root: Path) -> Path:
    return (root / spec.name / spec.version / Path(spec.exe_relpath)).parent


def stage(names, *, source_root: Path = DEFAULT_SOURCE, dest: Path = DEFAULT_DEST) -> list[str]:
    """Copy each named tool from ``source_root`` to ``dest`` after checking it against its pin.

    Returns the names staged, in order. Raises :class:`StageError` (leaving nothing half-staged for that
    tool) when one is missing, differs from its pin, or carries a file the pin does not list.
    """
    source_root, dest = Path(source_root), Path(dest)
    staged: list[str] = []
    for name in names:
        spec = toolfetch.TOOL_MANIFEST[name]
        src_exe_dir = _exe_dir(spec, source_root)
        if not (src_exe_dir / Path(spec.exe_relpath).name).is_file():
            raise StageError(
                f"{name} {spec.version}: not found under {source_root} - run "
                f"`python packaging/stage_tools.py` without --offline to fetch it")
        with _tools_root(source_root):
            ok = toolfetch.verify_installed(spec)
        if not ok:
            raise StageError(
                f"{name} {spec.version}: the copy under {source_root} does not match its pin "
                f"(a changed file, or one the pin does not list) - refusing to ship it")

        final = dest / name / spec.version
        part = dest / f".{name}.part"
        shutil.rmtree(part, ignore_errors=True)
        try:
            target = part / Path(spec.exe_relpath).parent
            target.mkdir(parents=True)
            for f in src_exe_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, target / f.name)
            shutil.rmtree(final, ignore_errors=True)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(part, final)
        finally:
            shutil.rmtree(part, ignore_errors=True)
        with _tools_root(dest):
            if not toolfetch.verify_installed(spec):                 # the copy itself, not the source
                shutil.rmtree(final, ignore_errors=True)
                raise StageError(f"{name} {spec.version}: the staged copy does not verify")
        staged.append(name)
    return staged


def _system_7z() -> str:
    for c in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if Path(c).is_file():
            return c
    found = shutil.which("7z")
    if found:
        return found
    raise StageError("unpacking the 7-Zip Extra package needs a 7-Zip on the build machine (winget install 7zip.7zip)")


def provision(names, *, source_root: Path = DEFAULT_SOURCE) -> list[str]:
    """Make sure each tool is under ``source_root``, fetching only what is missing. Returns what it fetched."""
    fetched: list[str] = []
    for name in names:
        spec = toolfetch.TOOL_MANIFEST[name]
        with _tools_root(source_root):
            if toolfetch.verify_installed(spec):
                continue
            if _adopt_flat_copy(spec, source_root):                  # offline: a file we already hold
                continue
            if not spec.bundled_only:
                toolfetch.fetch_tool(spec)
            else:
                _provision_extra(spec, source_root)
        fetched.append(name)
    return fetched


def _sha256(path: Path) -> str:
    return toolfetch._sha256_of(path)


def _adopt_flat_copy(spec: toolfetch.ToolSpec, source_root: Path) -> bool:
    """A raw tool that already sits as ``<source_root>/<exe>`` (zpaqfranz has lived at ``tools/bin/zpaqfranz.exe``
    since B1) moves into the nested layout without a download, if - and only if - it hashes to the pin."""
    if not spec.raw:
        return False
    flat = source_root / Path(spec.exe_relpath).name
    if not flat.is_file() or _sha256(flat) != spec.sha256:
        return False
    target = source_root / spec.name / spec.version / spec.exe_relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(flat, target)                                       # a copy: the original is left alone
    return toolfetch.verify_installed(spec)


def _provision_extra(spec: toolfetch.ToolSpec, source_root: Path) -> None:
    """7-Zip Extra: download (size and SHA-256 checked by toolfetch), unpack with the build machine's 7-Zip,
    take ``x64/7za.exe``, and let ``verify_installed`` decide whether it is the pinned file."""
    work = Path(tempfile.mkdtemp(prefix="7zextra-"))
    try:
        pkg = work / "extra.7z"
        base = spec.url.rsplit("/", 1)[-1]
        have = next((c for c in (source_root / base, source_root / ".downloads" / base)
                     if c.is_file() and c.stat().st_size == spec.size and _sha256(c) == spec.sha256), None)
        if have is not None:
            shutil.copy2(have, pkg)                                  # already paid for
        else:
            toolfetch._download_to(spec, pkg, False)
        out = work / "x"
        subprocess.run([_system_7z(), "x", "-y", f"-o{out}", str(pkg), "x64/7za.exe"],
                       check=True, capture_output=True, timeout=120)
        final = source_root / spec.name / spec.version
        shutil.rmtree(final, ignore_errors=True)
        final.mkdir(parents=True)
        shutil.copy2(out / "x64" / "7za.exe", final / "7za.exe")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not toolfetch.verify_installed(spec):
        shutil.rmtree(source_root / spec.name / spec.version, ignore_errors=True)
        raise StageError("7z: the 7za.exe in the downloaded package does not match its pin")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="the tools folder to take tools from")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--offline", action="store_true", help="never download: fail if a tool is missing")
    args = ap.parse_args(argv)
    names = list(toolfetch.BUNDLED)
    try:
        if not args.offline:
            for n in provision(names, source_root=args.source):
                print(f"fetched {n} (it was missing or did not match its pin)")
        if args.dest.name == "bundled-tools":                       # a folder this script owns; regenerated
            shutil.rmtree(args.dest, ignore_errors=True)
        staged = stage(names, source_root=args.source, dest=args.dest)
    except (StageError, toolfetch.FetchError, subprocess.SubprocessError, OSError) as exc:
        print(f"stage_tools: {exc}", file=sys.stderr)
        return 1
    total = sum(f.stat().st_size for f in args.dest.rglob("*") if f.is_file())
    print(f"staged {len(staged)} tools ({total / 1e6:.1f} MB) in {args.dest}: {', '.join(staged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
