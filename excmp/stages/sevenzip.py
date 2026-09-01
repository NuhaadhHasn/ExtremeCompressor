"""7-Zip LZMA2 stage — the workhorse of the Normal/Extreme profiles.

Since G2 it is also the reader for **every archive we did not create**:
`7z l -slt` lists them and `7z x` opens them. That widened the blast radius
from "our own temp files" to "any file a user drags in", which is why the
password guard and the output-charset switch below are not optional extras.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import slt
from ..tools import find_tools, require
from .base import Stage, StageContext, StageError, run_capture, run_tool

_PCT = re.compile(r"^\s*(\d{1,3})%")

#: Passed as ``-p`` whenever the user has given us no password of their own.
#:
#: **This is a hang guard, not security.** With no ``-p`` at all, 7-Zip asks
#: for a password on the console; under ``CREATE_NO_WINDOW`` there is no
#: console to ask on, so it waits forever and the app looks frozen. Measured
#: on 7-Zip 24.07 with stdin held open: `7z x` on an encrypted-header archive
#: was **still running after 8 seconds**; with a dummy ``-p`` it exited in
#: 0.22 s with a clean "Wrong password?" we can act on.
#:
#: PeaZip passes the literal ``-pdefault`` for this (research/17 §4). Ours is
#: deliberately not a password anyone would choose, so that the one-in-a-
#: million archive whose real password matches does not silently open.
HANG_GUARD_PASSWORD = "excmp-no-password-supplied"

#: A listing that takes longer than this has stopped being useful. Generous
#: because a large ISO on a slow external drive genuinely is slow; finite
#: because a tool that blocks anyway must not take the app with it.
LIST_TIMEOUT_S = 300.0


def _parse_percent(line: str) -> float | None:
    m = _PCT.match(line)
    return float(m.group(1)) if m else None


def redact(cmd: list[str]) -> list[str]:
    """A command line safe to write down.

    ``-p`` is the only switch carrying a secret, and it carries it inline
    (``-phunter2``), so a log line that prints argv verbatim publishes the
    password. The switch itself stays visible: a reader debugging a failure
    needs to know a password *was* passed. Same rule as
    ``excmp.ram.parse_extra_args``, which refuses ``-p`` in the Parameters
    line and never echoes the value back in its error.
    """
    return [("-p***" if a.startswith("-p") and len(a) > 2 else a) for a in cmd]


class SevenZipStage(Stage):
    id = "sevenzip"

    def __init__(self, level: int = 9, dict_size: str | None = None,
                 extra_args: list[str] | None = None):
        self.level = level
        self.dict_size = dict_size  # e.g. "192m"; None = 7z default for level
        # The Parameters line (research/23 section 5). Already allowlisted by
        # excmp.ram.parse_extra_args before it gets here - this class does not
        # re-validate, it just places them where 7-Zip expects switches.
        self.extra_args = list(extra_args or [])

    def _exe(self) -> str:
        return require(find_tools(), "7z").path

    def available(self) -> bool:
        return find_tools()["7z"] is not None

    def build_compress_cmd(self, src: Path, dst: Path, threads: int,
                           exe: str) -> list[str]:
        """The argument list, split out so the knobs are testable without
        running 7-Zip - and so it is obvious that the output path is ours and
        the extra switches cannot displace it."""
        cmd = [exe, "a", "-t7z", f"-mx{self.level}", "-bsp1", "-y"]
        if self.dict_size:
            cmd.append(f"-md={self.dict_size}")
        if threads:
            cmd.append(f"-mmt{threads}")
        cmd += self.extra_args
        # For a directory, archive its *contents* (src\*) so extraction
        # recreates the tree without an extra wrapping folder.
        target = str(src / "*") if src.is_dir() else str(src)
        cmd += [str(dst), target]
        return cmd

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        if dst.exists():
            dst.unlink()
        cmd = self.build_compress_cmd(src, dst, ctx.threads, self._exe())
        run_tool(cmd, ctx, self.id, _parse_percent)
        if not dst.exists():
            raise StageError(f"{self.id}: archive was not created")
        return dst

    def build_extract_cmd(self, src: Path, dst: Path, exe: str,
                          include: list[str] | None = None,
                          password: str | None = None) -> list[str]:
        """Split out for the same reason ``build_compress_cmd`` is: so the
        switches can be asserted without running 7-Zip.

        ``-p`` is **always** present. Before G2 this command had none at all,
        and an encrypted archive dropped on the Extract tab froze the app on
        an invisible prompt - shipped behaviour on main, not a new risk.
        """
        cmd = [exe, "x", "-bsp1", "-y", f"-p{password or HANG_GUARD_PASSWORD}",
               f"-o{dst}"]
        for name in include or []:
            # `-i!` patterns are matched against archive-internal paths. 7-Zip
            # has no "literal" mode, so a member genuinely called `a[1].txt`
            # over-matches - which is why extract_selected() places files from
            # a temp dir by exact name instead of trusting the filter alone.
            cmd.append(f"-i!{name}")
        cmd.append(str(src))
        return cmd

    def extract(self, src: Path, dst: Path, ctx: StageContext,
                password: str | None = None,
                include: list[str] | None = None) -> Path:
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        cmd = self.build_extract_cmd(src, dst, self._exe(), include, password)
        run_tool(cmd, ctx, self.id, _parse_percent)
        return dst

    def test(self, archive: Path, ctx: StageContext) -> None:
        run_tool([self._exe(), "t", "-bsp1", "-y",
                  f"-p{HANG_GUARD_PASSWORD}", str(archive)],
                 ctx, self.id, _parse_percent)

    # -- G2: reading somebody else's archive --------------------------------
    def build_list_cmd(self, archive: Path, password: str | None,
                       exe: str) -> list[str]:
        """`7z l -slt`, with the two switches that are easy to forget.

        ``-sccUTF-8`` pins the console charset: without it 7-Zip writes names
        in the OEM code page, Python decodes them as the locale codec, and
        every non-ASCII filename comes back mangled in a listing whose whole
        job is to show filenames.

        ``-p`` is the hang guard - see :data:`HANG_GUARD_PASSWORD`.
        """
        return [exe, "l", "-slt", "-y", "-sccUTF-8",
                f"-p{password or HANG_GUARD_PASSWORD}", str(archive)]

    def list_entries(self, archive: Path, ctx: StageContext,
                     password: str | None = None) -> tuple[slt.SltDocument, str]:
        """Return the parsed listing and 7-Zip's own output.

        The raw text rides along because failure classification needs it and
        because the caller - not this stage - decides what "Wrong password?"
        should become. Nothing here is logged: the command line holds the
        password, and 7-Zip echoes archive-supplied filenames that have no
        business being pasted into a log unfiltered.
        """
        cmd = self.build_list_cmd(Path(archive), password, self._exe())
        result = run_capture(cmd, ctx, max_lines=slt.MAX_LINES,
                             timeout_s=LIST_TIMEOUT_S)
        text = "\n".join(result.lines)
        doc = slt.parse_slt(result.lines, max_items=slt.MAX_ITEMS)
        if result.truncated:
            doc.truncated = True
        if result.timed_out:
            raise StageError(
                f"7-Zip did not finish listing this archive within "
                f"{LIST_TIMEOUT_S:.0f}s and was stopped")
        return doc, text
