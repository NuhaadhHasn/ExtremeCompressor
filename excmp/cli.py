"""Command-line interface: python -m excmp {analyze|compress|extract|list|verify|hash}."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze_tree
from .planner import Profile, plan as make_plan
from .stages.base import StageContext
from .tools import find_tools


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def cmd_analyze(args: argparse.Namespace) -> int:
    tools = find_tools()
    infos: list = []
    for inp in args.inputs:
        infos.extend(analyze_tree(Path(inp)))
    the_plan = make_plan(infos, Profile(args.profile), tools)
    if args.json:
        print(json.dumps({
            "files": [{"path": str(i.path), "size": i.size, "category": i.category.value,
                       "entropy": round(i.entropy_bps, 3)} for i in infos],
            "routes": [{"action": r.action, "stages": r.stages, "reason": r.reason,
                        "files": [str(f) for f in r.files]} for r in the_plan.routes],
            "warnings": the_plan.warnings,
        }, indent=2))
        return 0
    print(f"{'file':<52} {'category':<20} {'entropy':>8}  {'size':>10}")
    for i in infos:
        print(f"{str(i.path)[-52:]:<52} {i.category.value:<20} {i.entropy_bps:>8.2f}  {_fmt_size(i.size):>10}")
    print()
    for r in the_plan.routes:
        print(f"[{r.action}] {len(r.files)} file(s): {r.reason}")
    for w in the_plan.warnings:
        print(f"warning: {w}")
    return 0


def cmd_compress(args: argparse.Namespace) -> int:
    from . import engine  # deferred: keeps analyze fast
    ctx = StageContext(temp_dir=Path(args.temp))

    def show(stage: str, pct: float) -> None:
        if not args.json:
            print(f"\r  [{stage}] {pct:5.1f}%", end="", flush=True)

    ctx.progress_cb = show
    out = Path(args.output)
    from .ram import parse_extra_args
    options = engine.StageOptions(
        level=args.level,
        dict_size=args.dict_size,
        # Raises ValueError with a reason; main() turns that into a clean
        # one-line error rather than a traceback.
        extra_args=tuple(parse_extra_args(args.params or "")),
    )
    result = engine.compress([Path(p) for p in args.inputs], out,
                             Profile(args.profile), ctx, sidecar=args.sha256,
                             options=options)
    if not args.json:
        print()
    payload = {
        "archive": str(result.archive),
        "original": result.orig_bytes,
        "final": result.final_bytes,
        "ratio": round(result.ratio, 4),
        "saved_percent": round((1 - result.ratio) * 100, 2),
        "elapsed_s": round(result.elapsed_s, 1),
        "warnings": result.warnings,
        "sidecar": str(result.sidecar) if result.sidecar else None,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"done: {_fmt_size(result.orig_bytes)} -> {_fmt_size(result.final_bytes)} "
              f"({payload['saved_percent']}% saved) in {payload['elapsed_s']}s")
        for r in result.routes:
            if r["action"] == "store":
                print(f"note: {len(r['files'])} file(s) stored losslessly - {r['reason']}")
        if result.sidecar is not None:
            print(f"wrote {result.sidecar.name} - check it anywhere with "
                  f"`sha256sum -c {result.sidecar.name}`")
        for w in result.warnings:
            print(f"warning: {w}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract ours or somebody else's (G1).

    The two cases report differently on purpose. A foreign zip has no SHA-256
    ledger, so "restored 2 files" is the whole truth about it - borrowing the
    verified-restore wording would sell a guarantee that does not exist here.
    """
    from . import engine
    ctx = StageContext(temp_dir=Path(args.temp))
    password = _ask_password(args)
    if args.only:
        result = engine.extract_selected(Path(args.archive), args.only,
                                         Path(args.output), ctx, password)
    else:
        result = engine.extract_any(Path(args.archive), Path(args.output), ctx,
                                    password)
    msg = {
        "out_dir": str(result.out_dir),
        "files_restored": result.files_restored,
        "verified": result.verified,
        "ledger_backed": result.ledger_backed,
        "elapsed_s": round(result.elapsed_s, 1),
    }
    if args.json:
        print(json.dumps(msg, indent=2))
    elif result.ledger_backed:
        print(f"restored {result.files_restored} file(s), verified {result.verified} "
              f"hash(es) OK in {msg['elapsed_s']}s -> {result.out_dir}")
    else:
        print(f"restored {result.files_restored} file(s) in {msg['elapsed_s']}s "
              f"-> {result.out_dir}")
        print("note: this archive was not created by ExtremeCompressor, so it "
              "carries no SHA-256 ledger - the contents could not be checked "
              "against one")
    return 0


def _ask_password(args: argparse.Namespace) -> str | None:
    """Prompt, never accept a value on the command line.

    ``--password`` deliberately takes no argument. A password given as argv
    is visible in the process table for the life of the command and lands in
    the shell's history file for much longer than that - and this project
    already refuses to echo one back in an error message
    (``excmp.ram.parse_extra_args``).
    """
    if not getattr(args, "password", False):
        return None
    import getpass
    return getpass.getpass("Archive password: ")


def cmd_list(args: argparse.Namespace) -> int:
    """What is inside. Ours comes from the manifest; anyone else's from
    ``7z l -slt`` (G2). Nothing is extracted either way.

    The two are rendered by different branches on purpose. Our `why` column
    is the part no other archiver can print, because no other archiver
    records why a file was stored rather than compressed - and a foreign
    archive has no answer to it, no profile, no stage chain, and a CRC-32
    where our SHA-256 goes. Printing our headings over its numbers would be
    the "0 SHA-256 hashes verified" mistake in a second place.
    """
    from . import engine
    archive = Path(args.archive)
    listing = engine.list_any(archive, StageContext(temp_dir=Path(args.temp)),
                              _ask_password(args))
    if args.json:
        print(json.dumps({
            "archive": str(listing.archive),
            "kind": listing.kind,
            "profile": listing.profile,
            "created_utc": listing.created_utc,
            "stages": listing.stages,
            "total_bytes": listing.total_bytes,
            "ledger_backed": listing.ledger_backed,
            "truncated": listing.truncated,
            "encrypted": listing.encrypted,
            "entries": [{"name": e.name, "size": e.size, "sha256": e.sha256,
                         "route": e.route, "reason": e.reason, "crc": e.crc,
                         "packed_size": e.packed_size, "modified": e.modified,
                         "encrypted": e.encrypted, "is_dir": e.is_dir}
                        for e in listing.entries],
        }, indent=2))
        return 0

    print(f"{listing.archive}")
    if listing.ledger_backed:
        print(f"  profile {listing.profile} · chain "
              f"{' → '.join(listing.stages) or 'none'} "
              f"· created {listing.created_utc}")
        print(f"  {len(listing.entries)} file(s), {_fmt_size(listing.total_bytes)}")
        print()
        print(f"{'file':<48} {'size':>10}  {'route':<9} why")
        for e in listing.entries:
            print(f"{e.name[-48:]:<48} {_fmt_size(e.size):>10}  "
                  f"{e.route:<9} {e.reason}")
        return 0

    # Plain ASCII separators: this branch is new, and the middle dot the
    # .excmp branch uses renders as a replacement character in the Windows
    # console's default code page.
    print(f"  {listing.kind}, {listing.file_count} file(s), "
          f"{_fmt_size(listing.total_bytes)}")
    print("  not an ExtremeCompressor archive: these are the archive's own "
          "numbers, and its")
    print("  CRC-32s are an error check, not the SHA-256 ledger a verified "
          "restore needs")
    if listing.encrypted:
        print("  some entries are encrypted - extracting them will need the "
              "password")
    if listing.truncated:
        print(f"  showing the first {len(listing.entries)} entries only - this "
              f"archive has more")
    print()
    print(f"{'file':<48} {'size':>10}  {'packed':>10}  {'crc-32':<8} modified")
    for e in listing.entries:
        name = e.name + ("/" if e.is_dir else "")
        # A blank, not "0 B". 7-Zip leaves `Packed Size` empty for every
        # member of a solid block after the first, because the block is
        # compressed as one unit - printing zero there would tell the reader
        # these files take up no space.
        packed = _fmt_size(e.packed_size) if e.packed_size is not None else ""
        print(f"{name[-48:]:<48} {_fmt_size(e.size):>10}  "
              f"{packed:>10}  {e.crc:<8} {e.modified[:19]}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Prove an archive still restores byte-for-byte.

    The same full restore + ledger comparison that gates every publish - not a
    container self-test. Produces nothing and touches nothing.
    """
    from . import engine
    ctx = StageContext(temp_dir=Path(args.temp))
    result = engine.verify_archive(Path(args.archive), ctx)
    payload = {
        "archive": str(result.archive),
        "ok": result.ok,
        "files_restored": result.files_restored,
        "verified": result.verified,
        "elapsed_s": round(result.elapsed_s, 1),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"OK: {result.files_restored} file(s) restored and "
              f"{result.verified} SHA-256 hash(es) verified against the "
              f"manifest in {payload['elapsed_s']}s")
        print(f"     {result.archive}")
    return 0


def cmd_hash(args: argparse.Namespace) -> int:
    """SHA-256 for arbitrary files, in ``sha256sum`` layout.

    The engine hashes everything it touches; there was no way to ask it to
    hash something it did not. Two spaces before the path is not a typo - it
    is the format `sha256sum -c` reads, so the output pipes into the tools
    people already have.
    """
    from .verify import hash_file
    rows = []
    for name in args.paths:
        path = Path(name)
        rows.append({"path": str(path), "sha256": hash_file(path),
                     "size": path.stat().st_size})
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['sha256']}  {row['path']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="excmp",
                                description="ExtremeCompressor engine CLI")
    p.add_argument("--version", action="version", version=f"excmp {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    default_tmp = str(Path.home() / ".excmp" / "tmp")

    pa = sub.add_parser("analyze", help="show categories, entropy and planned routing")
    pa.add_argument("inputs", nargs="+")
    pa.add_argument("-p", "--profile", default="normal",
                    choices=[pr.value for pr in Profile])
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_analyze)

    pc = sub.add_parser("compress", help="compress files/folders to an .excmp archive")
    pc.add_argument("inputs", nargs="+")
    pc.add_argument("-o", "--output", required=True)
    pc.add_argument("-p", "--profile", default="normal",
                    choices=[pr.value for pr in Profile])
    pc.add_argument("--temp", default=default_tmp)
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--level", type=int, choices=range(0, 10), default=None,
                    metavar="0-9",
                    help="compression level; omit to let the profile decide")
    pc.add_argument("--dict", dest="dict_size", default=None, metavar="SIZE",
                    help="LZMA2 dictionary, e.g. 64m or 256m. Bigger is "
                         "slower and costs ~13x its size in RAM")
    # Every value this takes starts with "-", which argparse reads as another
    # option, so it must be spelled --params=-mqs. Saying so in the help is
    # cheaper than the "expected one argument" people would otherwise hit on
    # their first try.
    pc.add_argument("--params", default=None, metavar="SWITCHES",
                    help='extra 7-Zip method switches - use an equals sign, '
                         'e.g. --params="-mqs -myx=9". Method switches only; '
                         '-p/-o/-w/@ are refused')
    pc.add_argument("--sha256", action="store_true",
                    help="also write <archive>.sha256 so a recipient can check "
                         "the transfer with sha256sum -c")
    pc.set_defaults(func=cmd_compress)

    px = sub.add_parser("extract", help="extract an .excmp (verified) or any "
                                        "archive 7-Zip can open (unverified)")
    px.add_argument("archive")
    px.add_argument("-o", "--output", required=True)
    px.add_argument("--temp", default=default_tmp)
    px.add_argument("--json", action="store_true")
    px.add_argument("--only", action="append", metavar="NAME", default=[],
                    help="extract just this member (repeatable). For one of "
                         "ours the file is still checked against its SHA-256; "
                         "a solid archive replays the whole chain to reach it")
    px.add_argument("--password", action="store_true",
                    help="prompt for the archive's password. Takes no value "
                         "on purpose - a password in argv is visible in the "
                         "process table and saved in shell history")
    px.set_defaults(func=cmd_extract)

    pl = sub.add_parser("list", help="show what is inside an .excmp (size, "
                                     "SHA-256, route and why) or any archive "
                                     "7-Zip can open, without extracting")
    pl.add_argument("archive")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--temp", default=default_tmp)
    pl.add_argument("--password", action="store_true",
                    help="prompt for the password of an archive whose file "
                         "names are encrypted")
    pl.set_defaults(func=cmd_list)

    pv = sub.add_parser("verify", help="prove an .excmp archive still restores "
                                       "byte-for-byte (produces nothing)")
    pv.add_argument("archive")
    pv.add_argument("--temp", default=default_tmp)
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(func=cmd_verify)

    ph = sub.add_parser("hash", help="SHA-256 of files, in sha256sum layout")
    ph.add_argument("paths", nargs="+")
    ph.add_argument("--json", action="store_true")
    ph.set_defaults(func=cmd_hash)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # surface a clean one-liner, not a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
