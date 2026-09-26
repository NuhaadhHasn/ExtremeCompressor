"""zpaqfranz — the Insane profile's final codec, and our long-range dedup.

This stage does two jobs, which is why it replaces two things at once.

**Final codec.** It sits where 7-Zip sits in the Extreme chain, not where
Precomp sits. Unlike 7-Zip it is deliberately **not** registered as
tree-capable, so a tar stage always precedes it and it only ever receives one
file — see :meth:`ZpaqfranzStage.extract` for the path-mangling reason, which
was found by the first real run and not by any unit test. Dedup is unaffected
by the tar: CDC works on the byte stream, so identical fragments inside it are
still matched at unlimited distance.

**Long-range dedup.** Its content-defined chunking hashes fragments (~4 KB
min) and dedups them by SHA-1 against every fragment in the archive, at
*unlimited distance*. That is the capability that left the product when B11
removed SREP — and it costs about 28 bytes of index per fragment, so 200 GB
of input fits in well under 500 MB of RAM (research/20 §5).

**Why this and not SREP.** SREP bought roughly the same 3.5 points. It also
failed its own decompression checksum on 1 of 3 runs over byte-identical
input, and it is an unlicensed freeware binary. zpaqfranz is MIT, actively
maintained, and has not failed a restore here. When two tools buy the same
thing, take the one that does not corrupt.

Three rules encoded below, each from a specific finding in research/20:

- **`-longpath` is not optional.** zpaqfranz only prepends the ``\\\\?\\``
  prefix when it is passed; without it, a deep tree silently fails to add.
  §7's explicit lesson is to make long-path handling default-on, so there is
  no constructor argument to turn it off.
- **Plain ``a`` only.** ``backup`` (multipart), ZETA and W-chunk archives
  cannot be read by vanilla zpaq 7.15 or unzpaq206. An archive only our build
  can open is a lock-in nobody asked for.
- **Never ``t -paranoid -to``.** That path prompts for an interactive captcha
  when the target directory is non-empty (§6, ``getcaptcha``). Under
  ``CREATE_NO_WINDOW`` the prompt has nowhere to appear, so it would hang the
  app the way a missing 7-Zip ``-p`` did before G2.

And the standing rule that outranks all of them: **zpaqfranz's own ``-test``
and ``t`` are supplements, never substitutes.** What decides whether an
archive publishes is our post-restore SHA-256 comparison against the ledger.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..tools import find_tools, require
from ..tempclean import rmtree_force
from .base import Stage, StageContext, StageError, run_tool

#: zpaqfranz reports progress as a running percentage on its status line.
#: Matched loosely because the surrounding columns (sizes, rates, ETA) differ
#: between operations and versions, and a progress bar is not worth coupling
#: to an exact layout.
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")

#: -m58 since B17 (2026-09): method 5 with 256 MiB blocks. It was -m4 on
#: research/20's reading of the source: both use 64 MiB blocks and -m5 only
#: adds CM depth "at ~2-3x the CPU", so -m4 looked like the realistic
#: ceiling on two cores. The owner's instruction was "whatever is best for
#: compression", so this is the smallest setting measured, and the largest
#: block whose two-thread peak still fits the RAM budget on the 16 GB target.
#:
#: Measured with bare zpaqfranz, every archive restored and SHA-256 compared:
#:
#:     237 MB deflate .pcf        archive      vs -m4
#:       -m4  (64 MiB blocks)   46,575,605
#:       -m5  (64 MiB blocks)   43,194,463    -7.26%
#:       -m57 (128 MiB blocks)  42,933,026    -7.82%
#:       -m58 (256 MiB blocks)  42,852,397    -7.99%
#:     62.5 MB installers .pcf
#:       -m4                    46,191,810
#:       -m5                    45,915,367    -0.60%
#:
#: -m5 was already the smallest codec measured on both corpora, LOLZ
#: included (B12). Block size matters only above 64 MiB, which is exactly
#: where Insane's overnight jobs live. A job smaller than one block gets the
#: same archive at -m58 as at -m5.
#:
#: The price, measured: RAM grows with the block, 910 MiB per busy thread at
#: -m5 and 2,761 MiB at -m58 (`excmp/ram.py` models it); an input smaller than
#: 512 MB is at most two blocks and may keep only one thread busy; and the
#: restore, which the D9 gate replays before every publish, is as slow as
#: the compress, because context mixing is symmetric.
#:
#: Archives written at -m4 before B17 restore unchanged: extraction names no
#: method, because every zpaq block carries its own decoder description.
DEFAULT_METHOD = 58


def _parse_percent(line: str) -> float | None:
    m = _PCT.search(line)
    return float(m.group(1)) if m else None


class ZpaqfranzStage(Stage):
    id = "zpaqfranz"
    tool_name = "zpaqfranz"

    def __init__(self, method: int = DEFAULT_METHOD, test_after_add: bool = False):
        #: zpaq's method number: 4 or 5, optionally followed by a block-size
        #: digit (58 = method 5, 2^8 MiB blocks). See :data:`DEFAULT_METHOD`.
        self.method = int(method)
        #: Add ``-test`` so zpaqfranz decompress-checks its own output in the
        #: same command. Off by default because the engine already replays
        #: the whole chain before publishing (D9) and this would be a second
        #: full decompression of the same bytes.
        self.test_after_add = bool(test_after_add)

    def _exe(self) -> str:
        return require(find_tools(), self.tool_name).path

    def available(self) -> bool:
        return find_tools().get(self.tool_name) is not None

    # -- compress -----------------------------------------------------------
    def build_compress_cmd(self, src: Path, dst: Path, threads: int,
                           exe: str) -> list[str]:
        """The argument list, split out so every switch is assertable without
        the binary installed — the same pattern ``SevenZipStage`` uses."""
        cmd = [exe, "a", str(dst), str(src), f"-m{self.method}", "-longpath"]
        if threads:
            cmd.append(f"-t{threads}")
        if self.test_after_add:
            cmd.append("-test")
        return cmd

    def compress(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        src, dst = Path(src), Path(dst)
        # zpaqfranz *appends* to an existing archive rather than replacing it,
        # so a leftover file from a previous run would silently produce a
        # two-version archive whose first version nobody asked for.
        if dst.exists():
            dst.unlink()
        run_tool(self.build_compress_cmd(src, dst, ctx.threads, self._exe()),
                 ctx, self.id, _parse_percent)
        if not dst.exists():
            raise StageError(f"{self.id}: archive was not created")
        return dst

    # -- extract ------------------------------------------------------------
    def build_extract_cmd(self, src: Path, dst: Path, exe: str) -> list[str]:
        """``x ... -to <dir>``. Deliberately not ``t -paranoid -to``: see the
        module docstring — that variant can block on a captcha."""
        return [exe, "x", str(src), "-to", str(dst), "-longpath"]

    def extract(self, src: Path, dst: Path, ctx: StageContext) -> Path:
        """Extract, then put the payload where the chain expects it.

        **zpaqfranz stores the absolute path it was given**, with the drive
        letter mangled (``C:`` becomes ``C_``), and there is no switch on
        ``add`` to store a relative path — the argument is resolved before it
        is recorded. So ``x -to <dir>`` faithfully rebuilds
        ``<dir>/C_/Users/…/payload.pcf``.

        Two things break if that leaks into the chain. The path can exceed
        ``MAX_PATH``, and the next stage down is Precomp, which is not
        long-path aware and — true to form — **exits 0 while producing
        nothing**. And when this is the last stage, the ledger keys would
        never match a name buried under a ``C_`` prefix.

        ``-flat`` is not the fix: it base64-mangles names into
        ``00000001_00152_c2luZ2xl.pcf``. Relocating here is deterministic,
        keeps the real filename, and does not care what got stored — which is
        why the stage only ever accepts **one file** (see
        ``engine._TREE_CAPABLE``, which deliberately excludes it).
        """
        src, dst = Path(src), Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        scratch = Path(ctx.temp_dir) / f"zx-{src.stem}"
        if scratch.exists():
            rmtree_force(scratch)
        scratch.mkdir(parents=True, exist_ok=True)

        run_tool(self.build_extract_cmd(src, scratch, self._exe()),
                 ctx, self.id, _parse_percent)

        found = [p for p in scratch.rglob("*") if p.is_file()]
        if len(found) != 1:
            raise StageError(
                f"{self.id}: expected exactly 1 file in the restore, got "
                f"{len(found)} - this stage is only ever given one file")
        out = dst / found[0].name
        if out.exists():
            out.unlink()
        # The source can be past MAX_PATH even though the destination is
        # short, so address it the way Windows wants for long paths. Python's
        # own APIs honour the prefix; the tool already had -longpath.
        source = found[0]
        if len(str(source)) >= 250 and not str(source).startswith("\\\\?\\"):
            source = Path("\\\\?\\" + str(source.resolve()))
        shutil.move(str(source), str(out))
        rmtree_force(scratch)
        return out

    # -- the tool's own opinion, which is not the deciding one --------------
    def build_test_cmd(self, archive: Path, exe: str) -> list[str]:
        return [exe, "t", str(archive)]

    def test(self, archive: Path, ctx: StageContext) -> None:
        """Ask zpaqfranz whether it can read back what it wrote.

        Worth running, but note what it is *not*: it checks the archive
        against the hashes stored inside that same archive. A stage that
        corrupted data consistently would pass. Only the engine's restore and
        SHA-256 comparison against the ledger catches that, which is why this
        never gates publication on its own.
        """
        run_tool(self.build_test_cmd(Path(archive), self._exe()),
                 ctx, self.id, _parse_percent)
