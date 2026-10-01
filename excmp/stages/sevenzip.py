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



def _dict_bytes(text: str) -> int:
    """"256m" -> bytes, the -md= spelling the stage is configured with."""
    text = text.strip().lower()
    unit = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}.get(text[-1:], 1)
    number = text[:-1] if text[-1:] in "kmg" else text
    return int(number or 0) * unit

class SevenZipStage(Stage):
    id = "sevenzip"

    def __init__(self, level: int = 9, dict_size: str | None = None,
                 extra_args: list[str] | None = None, bcj2: bool = False,
                 archive_type: str = "7z"):
        self.level = level
        self.dict_size = dict_size  # e.g. "192m"; None = 7z default for level
        #: Force the BCJ2 x86 branch filter (B7). Off by default and set from
        #: the *measured* file mix rather than always: it is worth 1.3% on
        #: real executable code and costs 0.04% on text
        #: (tests/test_sevenzip_switches.py carries the table).
        self.bcj2 = bool(bcj2)
        #: `7z` normally; `zip` for the G4 standard export. A parameter rather
        #: than an extra_arg because `-t` may appear exactly once - appending
        #: `-tzip` beside the baked-in `-t7z` makes 7-Zip exit 7 with
        #: "Multiple instances for switch".
        self.archive_type = str(archive_type)
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
        # -mqs sorts by file type inside the solid block. 7-Zip leaves it
        # OFF by default (research/19 section 5); measured here it never cost
        # anything on any corpus and was worth 0.13% on source trees, so not
        # passing it was a choice we were making by accident.
        cmd = [exe, "a", f"-t{self.archive_type}", f"-mx{self.level}",
               "-bsp1", "-y"]
        # -mqs and -mf are 7z-format concepts: zip has no solid block to sort
        # within and no method chain to place a filter in. Passing them to a
        # zip is not merely useless, 7-Zip refuses the whole command with
        # "The parameter is incorrect".
        if self.archive_type == "7z":
            cmd.append("-mqs")
        if self.bcj2 and self.archive_type == "7z":
            # Forcing it matters: at mx9 with the MT mixer 7-Zip is documented
            # to auto-select BCJ2, but measured on 23.5 MB of real DLLs it
            # plainly had not - forcing the filter took another 1.296% off.
            cmd.append("-mf=BCJ2")
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
        # "Auto" (0) is one thread per physical core, passed explicitly. Left
        # to itself 7-Zip takes every logical processor - 4 on the 2-core
        # target - and measured on 645 MB of installers (three LZMA2 blocks)
        # that produced a 0.14% larger archive at more than twice the peak RAM
        # (5,549 MiB against 2,702 MiB at 2 threads), though 1.75x faster. On a
        # single-block input the bytes and RAM matched, and 2 threads was the
        # fastest setting.
        # tests/test_default_threads.py has the table.
        threads = self._auto_threads(ctx.threads)
        cmd = self.build_compress_cmd(src, dst, threads, self._exe())
        run_tool(cmd, ctx, self.id, _parse_percent)
        if not dst.exists():
            raise StageError(f"{self.id}: archive was not created")
        return dst

    def _auto_threads(self, requested: int) -> int:
        """The -mmt to pass: the user's count, else one per physical core
        capped at the RAM budget, else nothing at all when the Parameters line
        already carries -mmt or -mmemuse - those are the user's own word on
        threads and memory, and a forced count would override 7-Zip's
        memory fitting behind their back."""
        if requested:
            return requested
        if any(a.lower().startswith(("-mmt", "-mmemuse")) for a in self.extra_args):
            return 0
        from ..ram import lzma2_auto_threads, lzma2_default_dict
        dict_bytes = (_dict_bytes(self.dict_size) if self.dict_size
                      else lzma2_default_dict(self.level))
        return lzma2_auto_threads(dict_bytes, self.level)

    def build_extract_cmd(self, src: Path, dst: Path, exe: str,
                          include: list[str] | None = None,
                          password: str | None = None,
                          threads: int | None = None) -> list[str]:
        """Split out for the same reason ``build_compress_cmd`` is: so the
        switches can be asserted without running 7-Zip.

        ``-p`` is **always** present. Before G2 this command had none at all,
        and an encrypted archive dropped on the Extract tab froze the app on
        an invisible prompt - shipped behaviour on main, not a new risk.

        ``threads`` is G7's whole mechanism. The roadmap asked to "cap
        dict/window" on extraction, which is not available: the dictionary is
        fixed by whoever *created* the archive and the zstd window comes out
        of the frame header. The decoder thread count is the one real lever,
        and it is a large one - measured 2026-09-11 on Silesia at ``-md=64m``:
        **255 MiB with no switch, 71 MiB at ``-mmt=1``**, a 3.6x drop, while
        `-mmt=2` and `-mmt=4` both stayed at 255 MiB.

        It also measured *faster* single-threaded on this 2-core machine
        (2.5-2.7 s against 2.9-3.0 s), because the extra decoder threads cost
        more in contention than they win. That is one corpus on one machine
        and is **not** why this is opt-in - it is opt-in because generalising
        a speed result from a single 2-core sample to every machine is the
        mistake B8 caught in the estimator.

        ``None``, ``0`` and negatives emit no switch at all. ``-mmt=0`` means
        *use every core* to 7-Zip, the exact opposite of what a caller asking
        for a RAM limit wants, so an unusable value is dropped rather than
        forwarded.
        """
        cmd = [exe, "x", "-bsp1", "-y", f"-p{password or HANG_GUARD_PASSWORD}",
               f"-o{dst}"]
        if threads is not None and int(threads) >= 1:
            cmd.append(f"-mmt={int(threads)}")
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
        # G7: `ctx.extract_threads` is 0 for "tool default", which is the
        # shipped behaviour and must stay reachable - `or None` maps it back to
        # "emit no switch" rather than to `-mmt=0`, which means *all cores*.
        cmd = self.build_extract_cmd(src, dst, self._exe(), include, password,
                                     threads=getattr(ctx, "extract_threads", 0)
                                     or None)
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
