"""Discovery of the external CLI tools the engine can orchestrate.

Tools are looked up in well-known install locations first, then in the flat
``tools/bin`` directory, then in E1's nested
``tools/bin/<name>/<version>/`` layout (via `toolfetch.installed_path`, so a
hash-pinned tool is only reported when it still matches its pin), then on
PATH. A missing tool is not an
error at discovery time — profiles degrade gracefully; stages that need a
missing tool raise :class:`ToolMissingError` when actually used.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

APP_BIN = Path(__file__).resolve().parent.parent / "tools" / "bin"

#: Tools we still look for, and will still *run*, but will never choose for a
#: new archive.
#:
#: SREP came out of every compression chain in B11 for two independent
#: reasons — it is not OSI-licensed, so it can never ship with a repo that
#: needs SignPath signing, and `srep64.exe` failed its own decompression
#: checksum on 1 of 3 runs over byte-identical input (2026-08-01). The stage
#: survives only so that archives written before B11 still restore, which is
#: why discovery must stay: `SrepStage.available()` asks `find_tools()`.
#:
#: The label exists because the app was listing it under "Tools found" with no
#: qualifier, naming a tool it would never run. Hiding it instead would be its
#: own small dishonesty — someone restoring a legacy archive needs to see it
#: was located.
LEGACY_ONLY: frozenset[str] = frozenset({"srep"})

#: Minimum version we are willing to see, per tool. Below this the app says so.
#:
#: 7-Zip below **26.02** carries **CVE-2026-14266** (CVSS 7.0): a heap buffer
#: overflow in the XZ decoder (`MixCoder_Code`, `C/XzDec.c`) that a crafted
#: `.xz` can turn into code execution in the process doing the extracting.
#: It was present from 21.07 through 26.01 - a five-year window - and fixed in
#: 26.02 on 2026-06-25.
#:
#: **This one IS an exploit path for us**, unlike the CVE the floor previously
#: named. `excmp.safepath` protects against hostile *names*; it cannot do
#: anything about memory corruption inside 7-Zip while it decompresses, and we
#: hand 7-Zip arbitrary user archives on the Extract tab by design. The floor
#: was 24.09 for CVE-2025-0411, a Mark-of-the-Web bypass that our own
#: propagation and validation already covered - so it was both too low and
#: aimed at the wrong risk.
#:
#: Kept as a tuple so the comparison is numeric: `"9.20" > "24.09"` is True as
#: *strings*, which would wave a 2010 build straight through.
SECURITY_FLOOR: dict[str, tuple[int, int]] = {"7z": (26, 2)}

_FLOOR_REASON: dict[str, str] = {
    "7z": "CVE-2026-14266, a heap overflow in the XZ decoder that a crafted "
          "archive can turn into code execution",
}

# A version sits after the product name, but not always in the next word:
# the reduced console build prints "7-Zip (a) 16.02" and p7zip prints
# "7-Zip [64] 16.02", so the first number on the line is what we want, not
# the second token.
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

_PRODUCT_NAME: dict[str, str] = {"7z": "7-Zip"}

CANDIDATES: dict[str, list[str]] = {
    "7z": [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"],
    "precomp": [r"C:\Program Files\precomp\windows\precomp.exe"],
    "srep": [r"C:\Program Files\srep\srep64.exe", r"C:\Program Files\srep\srep.exe"],
    "zpaqfranz": [],
    "zstd": [],
    "ffmpeg": [],
    "ffprobe": [],
}

_VERSION_ARGS: dict[str, list[str]] = {
    "7z": [],           # 7z prints a banner with no args
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
    "zstd": ["--version"],
    "zpaqfranz": [],
}


class ToolMissingError(RuntimeError):
    """Raised when a stage requires a tool that is not installed."""


@dataclass(frozen=True)
class ToolInfo:
    name: str
    path: str
    version: str = ""


def _probe_version(name: str, path: str) -> str:
    args = _VERSION_ARGS.get(name)
    if args is None:
        return ""
    try:
        proc = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
        first = (proc.stdout or proc.stderr).strip().splitlines()
        return first[0][:120] if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _pinned_tool(name: str) -> str | None:
    """An E1-installed tool's path, if it is present and still verifies.

    Imported lazily: `toolfetch` imports `tempclean` and `safepath`, and
    `tools` is imported by nearly everything, so a module-level import would
    be a cycle waiting to happen.
    """
    try:
        from . import toolfetch
    except ImportError:                      # pragma: no cover
        return None
    spec = toolfetch.TOOL_MANIFEST.get(name)
    if spec is None:
        return None
    found = toolfetch.installed_path(spec)
    return str(found) if found is not None else None


def find_tools(with_versions: bool = False) -> dict[str, ToolInfo | None]:
    """Locate every known tool. Returns a dict with an entry per tool name."""
    found: dict[str, ToolInfo | None] = {}
    # E1-pinned tools are not in CANDIDATES - they have no well-known install
    # location, which is the whole reason they are fetched - so the loop has
    # to consider them too or they can never be discovered. `dict.fromkeys`
    # keeps CANDIDATES' order and appends only the pinned names not already
    # listed there.
    from . import toolfetch
    names = dict.fromkeys([*CANDIDATES, *toolfetch.TOOL_MANIFEST])
    for name in names:
        paths = CANDIDATES.get(name, ())
        located: str | None = None
        for p in paths:
            if Path(p).is_file():
                located = p
                break
        if located is None:
            app_exe = APP_BIN / f"{name}.exe"
            if app_exe.is_file():
                located = str(app_exe)
        if located is None:
            # E1's own layout, which is nested rather than a flat
            # `tools/bin/<name>.exe`: `<root>/<name>/<version>/<exe_relpath>`.
            # An audit pointed out that this docstring promised to look "in
            # the app-managed tools/bin directory" while never looking at the
            # shape E1 actually installs into - so a hash-pinned tool was
            # invisible to normal discovery and only reachable by asking
            # `toolfetch` directly, which is what `flacaudio` happens to do.
            #
            # Routed through `installed_path`, so a fetched tool is only
            # reported when it still hashes to what was pinned.
            located = _pinned_tool(name)
        if located is None:
            located = shutil.which(name)
        if located is None:
            found[name] = None
        else:
            version = _probe_version(name, located) if with_versions else ""
            found[name] = ToolInfo(name=name, path=located, version=version)
    return found


def parse_tool_version(banner: str, product: str = "7-Zip") -> tuple[int, int] | None:
    """``(major, minor)`` out of a tool's banner, or None if it did not say.

    None means *unknown*, never *old*. A fork prints its own name — NanaZip
    says "NanaZip 5.0" — and reporting that as a 7-Zip version would apply a
    floor that means nothing for that binary. Crying wolf on every fork is how
    a security notice gets ignored.

    Scans the first few non-empty lines rather than trusting line 0: ``7z.exe``
    with no arguments prints a blank line *before* its banner.
    """
    if not banner:
        return None
    for line in [ln for ln in banner.splitlines() if ln.strip()][:5]:
        if product.lower() not in line.lower():
            continue
        found = _VERSION_RE.search(line)
        if found:
            return int(found.group(1)), int(found.group(2))
    return None


def below_floor(
    tools: dict[str, ToolInfo | None],
) -> list[tuple[str, str, str]]:
    """Which installed tools are older than :data:`SECURITY_FLOOR`.

    Returns ``(name, found_version, required_version)`` per offender, so the
    caller can name both numbers — "yours is old" without saying which two
    versions it is comparing leaves the user nothing to act on.

    A tool that is missing, or whose banner we could not read, is **not**
    reported. "We could not tell" is a different fact from "it is old", and
    only one of them is worth interrupting somebody about.
    """
    stale: list[tuple[str, str, str]] = []
    for name, floor in SECURITY_FLOOR.items():
        info = tools.get(name)
        if info is None:
            continue
        found = parse_tool_version(info.version, _PRODUCT_NAME.get(name, name))
        if found is not None and found < floor:
            stale.append((name,
                          f"{found[0]}.{found[1]:02d}",
                          f"{floor[0]}.{floor[1]:02d}"))
    return stale


def floor_reason(name: str) -> str:
    """Why the floor is where it is, for a sentence a user can act on."""
    return _FLOOR_REASON.get(name, "")


def require(tools: dict[str, ToolInfo | None], name: str) -> ToolInfo:
    tool = tools.get(name)
    if tool is None:
        raise ToolMissingError(
            f"'{name}' is required for this operation but was not found. "
            f"Install it or pick a profile that does not need it."
        )
    return tool
