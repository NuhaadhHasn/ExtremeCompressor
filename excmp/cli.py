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
    result = engine.compress([Path(p) for p in args.inputs], out,
                             Profile(args.profile), ctx)
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
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"done: {_fmt_size(result.orig_bytes)} -> {_fmt_size(result.final_bytes)} "
              f"({payload['saved_percent']}% saved) in {payload['elapsed_s']}s")
        for r in result.routes:
            if r["action"] == "store":
                print(f"note: {len(r['files'])} file(s) stored losslessly - {r['reason']}")
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
    result = engine.extract_any(Path(args.archive), Path(args.output), ctx)
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


def cmd_list(args: argparse.Namespace) -> int:
    """What is inside, straight from the manifest - nothing is extracted.

    The `why` column is the part no other archiver can print, because no other
    archiver records why a file was stored rather than compressed.
    """
    from . import engine
    listing = engine.list_archive(Path(args.archive))
    if args.json:
        print(json.dumps({
            "archive": str(listing.archive),
            "kind": listing.kind,
            "profile": listing.profile,
            "created_utc": listing.created_utc,
            "stages": listing.stages,
            "total_bytes": listing.total_bytes,
            "entries": [{"name": e.name, "size": e.size, "sha256": e.sha256,
                         "route": e.route, "reason": e.reason}
                        for e in listing.entries],
        }, indent=2))
        return 0

    print(f"{listing.archive}")
    print(f"  profile {listing.profile} · chain {' → '.join(listing.stages) or 'none'} "
          f"· created {listing.created_utc}")
    print(f"  {len(listing.entries)} file(s), {_fmt_size(listing.total_bytes)}")
    print()
    print(f"{'file':<48} {'size':>10}  {'route':<9} why")
    for e in listing.entries:
        print(f"{e.name[-48:]:<48} {_fmt_size(e.size):>10}  {e.route:<9} {e.reason}")
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
    pc.set_defaults(func=cmd_compress)

    px = sub.add_parser("extract", help="extract an .excmp (verified) or any "
                                        "archive 7-Zip can open (unverified)")
    px.add_argument("archive")
    px.add_argument("-o", "--output", required=True)
    px.add_argument("--temp", default=default_tmp)
    px.add_argument("--json", action="store_true")
    px.set_defaults(func=cmd_extract)

    pl = sub.add_parser("list", help="show what is inside an .excmp - size, "
                                     "SHA-256, route and why, without extracting")
    pl.add_argument("archive")
    pl.add_argument("--json", action="store_true")
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
