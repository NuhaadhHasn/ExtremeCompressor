"""Command-line interface: python -m excmp {analyze|compress|extract|list|verify|hash}."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze_tree_safe
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
    unreadable: list[str] = []
    for inp in args.inputs:
        # K3: the analysis pass must never fail for a reason the compress it
        # precedes can survive. `analyze_file` opens every file, so one open
        # spreadsheet used to abort the whole analysis.
        got, skipped = analyze_tree_safe(Path(inp))
        infos.extend(got)
        unreadable.extend(reason for _p, reason in skipped)
    the_plan = make_plan(infos, Profile(args.profile), tools)
    if not args.json:
        for line in unreadable:
            print(f"warning: {line}")
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


def _post_publish(args, archive, payload: dict, ctx: StageContext) -> None:
    """Recovery records and volume splitting, for any output format.

    Both act on the finished file, so they are format-agnostic and belong in
    one place. They run only after publication - which means only after the
    archive has been verified - because protecting or splitting an unverified
    archive just produces several unverified files.
    """
    try:
        _post_publish_steps(args, archive, payload, ctx)
    except Exception as exc:      # noqa: BLE001 - reported, never swallowed
        # The archive is written and verified by now. A failed extra must not
        # be reported as a failed job.
        payload["post_publish_error"] = (
            f"the archive is written and verified at {archive}, but a "
            f"post-publication step failed: {exc}")


def _post_publish_steps(args, archive, payload: dict, ctx: StageContext) -> None:
    if getattr(args, "recovery", None) is not None:
        from .recovery import available as par2_available, create, default_percent
        if not par2_available():
            payload["recovery_warning"] = ("par2 is not installed, so no "
                                           "recovery records were written")
        else:
            pct = (default_percent(archive.stat().st_size)
                   if args.recovery == -1 else args.recovery)
            made = create(archive, pct, ctx)
            payload["recovery"] = [str(m) for m in made]
            payload["recovery_percent"] = pct
            payload["recovery_bytes"] = sum(m.stat().st_size for m in made)

    if getattr(args, "split", None):
        from .volumes import parse_size, split_file, write_parts_sidecar
        parts = split_file(archive, parse_size(args.split))
        write_parts_sidecar(parts)
        payload["volumes"] = [str(p) for p in parts]


def _report_post_publish(args, payload: dict) -> None:
    if payload.get("post_publish_error"):
        print("warning: " + payload["post_publish_error"])
    if payload.get("recovery_warning"):
        print("warning: " + payload["recovery_warning"])
    if payload.get("recovery"):
        print("wrote %d recovery file(s) at %d%% (+%s); repair with "
              "`excmp repair %s`"
              % (len(payload["recovery"]), payload["recovery_percent"],
                 _fmt_size(payload["recovery_bytes"]),
                 Path(payload["archive"]).name))
    if payload.get("volumes"):
        names = [Path(v).name for v in payload["volumes"]]
        print(f"split into {len(names)} volumes: {names[0]} .. {names[-1]}")
        print(f"extract with: excmp extract {names[0]}")


def cmd_compress(args: argparse.Namespace) -> int:
    from . import engine  # deferred: keeps analyze fast
    ctx = StageContext(temp_dir=Path(args.temp))

    if getattr(args, "format", "excmp") != "excmp":
        # Note this does NOT return - the post-publication steps below
        # (recovery records, splitting) are format-agnostic: they operate on
        # the finished file. Returning here silently ignored --recovery and
        # --split for every plain archive.
        return _compress_standard(args, engine, ctx)

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
                             options=options, password=_new_password(args),
                             keyfile=_keyfile(args))
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
        # K3: the names, structured, for anything driving this from a script.
        # The human-readable summary is in `warnings` and prints below.
        "skipped": result.skipped,
        "sidecar": str(result.sidecar) if result.sidecar else None,
    }
    # G3: split only after compress() has published, which means only after
    # the D9 gate has restored and hashed the whole archive. Splitting an
    # unverified archive would just produce several unverified files.
    _post_publish(args, result.archive, payload, ctx)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _report_post_publish(args, payload)
        print(f"done: {_fmt_size(result.orig_bytes)} -> {_fmt_size(result.final_bytes)} "
              f"({payload['saved_percent']}% saved) in {payload['elapsed_s']}s")
        for r in result.routes:
            if r["action"] == "store":
                # `count`, not `len(files)`: the manifest stopped listing every
                # relative path a second time in schema v2 (K1). Fall back for
                # a v1 archive, which is the only thing that still has `files`.
                n = r.get("count", len(r.get("files", [])))
                print(f"note: {n} file(s) stored losslessly - {r['reason']}")
        if result.sidecar is not None:
            print(f"wrote {result.sidecar.name} - check it anywhere with "
                  f"`sha256sum -c {result.sidecar.name}`")
        for w in result.warnings:
            print(f"warning: {w}")
    return 0


def _compress_standard(args, engine, ctx: StageContext) -> int:
    """G4: a plain .7z/.zip. Reports what it can and cannot promise."""
    def show(stage: str, pct: float) -> None:
        if not args.json:
            print(f"\r  [{stage}] {pct:5.1f}%", end="", flush=True)

    ctx.progress_cb = show
    # The password is passed so the engine can REFUSE the combination. Not
    # passing it is how `--format zip --password` used to write a plain,
    # unencrypted archive and exit 0 without even prompting.
    result = engine.compress_standard(
        [Path(p) for p in args.inputs], Path(args.output), args.format, ctx,
        password=_new_password(args))
    if not args.json:
        print()
    payload = {
        "archive": str(result.archive),
        "format": args.format,
        "original": result.orig_bytes,
        "final": result.final_bytes,
        "saved_percent": round((1 - result.final_bytes / result.orig_bytes) * 100, 2)
        if result.orig_bytes else 0.0,
        "elapsed_s": round(result.elapsed_s, 1),
        "verified": result.verified,
        "has_ledger": result.has_ledger,
        "note": result.note,
        # K3: a plain export has no ledger, so this list is the only record
        # that a file was left out of it.
        "skipped": result.skipped,
    }
    # Format-agnostic post-publication steps. These act on the finished file,
    # so a plain .7z/.zip gets them exactly as an .excmp does; an earlier
    # version returned before this point and silently ignored both flags.
    _post_publish(args, result.archive, payload, ctx)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"done: {_fmt_size(result.orig_bytes)} -> "
              f"{_fmt_size(result.final_bytes)} "
              f"({payload['saved_percent']}% saved) in {payload['elapsed_s']}s")
        print(f"verified {result.verified} file(s) by extracting and hashing")
        print(f"note: {result.note}")
        for line in result.skipped:
            print(f"warning: {line}")
        _report_post_publish(args, payload)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract ours or somebody else's (G1), joining volumes first (G3).

    The two cases report differently on purpose. A foreign zip has no SHA-256
    ledger, so "restored 2 files" is the whole truth about it - borrowing the
    verified-restore wording would sell a guarantee that does not exist here.
    """
    from . import engine
    ctx = StageContext(temp_dir=Path(args.temp))

    # G3: handed a `.001`, rejoin the set first. The join is a plain
    # concatenation into temp and nothing about the container changes, so
    # everything below - including the verified restore - is the ordinary
    # path. A split archive is not a second format to reason about.
    # G3 volumes and F1 encryption are both handled by the engine now
    # (engine.opened_for_reading), which every reading entry point routes
    # through. The CLI used to join here into a file under --temp that was
    # never deleted - a 50 GB archive joined and left behind.
    from .volumes import is_first_part, part_paths
    if is_first_part(Path(args.archive)):
        parts = part_paths(Path(args.archive))
        print(f"joining {len(parts)} volumes ({parts[0].name} .. "
              f"{parts[-1].name})...")

    password = _ask_password(args)
    if args.only:
        result = engine.extract_selected(Path(args.archive), args.only,
                                         Path(args.output), ctx, password,
                                         keyfile=_keyfile(args))
    else:
        result = engine.extract_any(Path(args.archive), Path(args.output), ctx,
                                    password, keyfile=_keyfile(args))
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


def _keyfile(args: argparse.Namespace) -> Path | None:
    """The second factor as a path, or None.

    Checked for existence here rather than deep in `crypto`, because the
    failure a user actually hits is a typo in a path - and finding that out
    after Argon2id has spent 64 MiB and three seconds deriving a key from it
    is a worse experience than finding out immediately.
    """
    raw = getattr(args, "keyfile", None)
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        raise ValueError(
            f"keyfile {path} does not exist - nothing was written. The file "
            f"has to be the same one the archive was created with, byte for "
            f"byte")
    return path


def _stdin_is_interactive() -> bool:
    """Is there a human at the other end of stdin?

    Wrapped, because `isatty()` is not guaranteed to exist or to succeed on
    every object that can become `sys.stdin` - a closed stream and some
    embedding hosts both raise - and an exception here would turn "work out
    how to ask for a password" into a crash.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def _read_secret(prompt: str) -> str:
    """One password, from a console if there is one and from stdin if not.

    ``--password`` still takes no argument, for the reason it never did: a
    password given as argv is visible in the process table for the life of the
    command and lands in the shell's history file for much longer than that.

    **The stdin branch is not a convenience, it is a bug fix.** Measured
    2026-09-10: `echo pw | excmp verify --password ... archive.excmp` hung
    indefinitely. `getpass.getpass` is `getpass.win_getpass` on Windows, which
    reads with `msvcrt.getwch()` - from the *console*, not from stdin - and
    falls back to a stdin read only when `sys.stdin is not sys.__stdin__`.
    Piping does not change that identity, so the pipe was ignored and the
    process blocked on a console nobody was typing at.

    That made `verify --password` usable only by a human at a terminal, which
    defeats the point of having it: the callers who most want to prove an
    encrypted archive still restores are a scheduled sweep, a CI job and a
    batch script over a folder of them, and all three would hang with no
    output.

    A piped password appears in neither the process table nor shell history,
    so this keeps the property that argv would have broken. It is the same
    escape hatch `gpg --passphrase-fd` and `ssh-add` offer.
    """
    import getpass

    if _stdin_is_interactive():
        return getpass.getpass(prompt)
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        # "not a terminal" is not the same claim as "has a password on it".
        # A captured, closed or detached stdin can be read by nobody, and the
        # honest response is to ask rather than to fail. That is what a pytest
        # run looks like - `sys.stdin` becomes a `DontReadFromInput` whose
        # read raises - and also a subprocess spawned by the GUI with no
        # console attached.
        return getpass.getpass(prompt)
    if not line:
        # "" is not a password. Accepting it produces "wrong password" for a
        # caller whose actual problem is that they piped nothing, and that
        # message sends people hunting for a password they already have.
        raise ValueError(
            "no password on stdin - `--password` reads one line from stdin "
            "when stdin is not a terminal, so pipe it in (`echo pw | ...`) "
            "or run the command interactively")
    # Only the line ending. A passphrase legitimately contains spaces, and
    # `echo pw |` appends the newline that would otherwise become part of it.
    return line.rstrip("\r\n")


def _ask_password(args: argparse.Namespace) -> str | None:
    """The archive's existing password, or None when it was not asked for."""
    if not getattr(args, "password", False):
        return None
    return _read_secret("Archive password: ")


def _new_password(args: argparse.Namespace) -> str | None:
    """Prompt twice when *setting* a password.

    Reading one asks once — a typo just fails. Setting one asks twice, because
    a typo here is not recoverable by anybody: there is no backdoor, no
    recovery key and no reset. That is the honest consequence of Argon2id plus
    AES-GCM, and confirming is the only protection we can offer against it.
    """
    if not getattr(args, "password", False):
        return None
    # F5. The paragraph above used to be the whole of it: the clearest
    # statement of the consequence anywhere in this codebase, in a docstring,
    # printed to nobody, while the prompt below said only "Password for the
    # new archive: ". This is the keystroke at which the data becomes
    # unrecoverable, and the CLI has no tooltip or inline note to fall back
    # on.
    #
    # stderr, not stdout: `--json` output is meant to be piped, and putting a
    # human-readable warning in front of it would make the honest thing a bug.
    print("This encrypts the whole archive - filenames and hashes included.",
          file=sys.stderr)
    print("There is no backdoor, no reset and no recovery: if you lose this "
          "password, the data is gone.", file=sys.stderr)
    print("Keep it somewhere you will still have it next year.",
          file=sys.stderr)
    if getattr(args, "keyfile", None):
        print(f"The keyfile {args.keyfile} is a second factor, and losing it "
              f"is exactly as final.", file=sys.stderr)
        print("Keep that file itself, not a re-saved or re-downloaded copy - "
              "it has to match byte for byte.", file=sys.stderr)
    first = _read_secret("Password for the new archive: ")
    if not first:
        raise ValueError("empty password - nothing was written")
    # The confirmation is for a human's typo, and it is impossible for a pipe:
    # a second read gets EOF, which would compare unequal and refuse every
    # scripted compress. One line in, one password - the caller of a script
    # already has the value written down somewhere it can be re-read.
    if _stdin_is_interactive():
        if _read_secret("Type it again: ") != first:
            raise ValueError(
                "the two passwords did not match - nothing was written")
    return first


def cmd_convert(args: argparse.Namespace) -> int:
    """G5: take somebody else's archive and make it smaller, honestly."""
    from .convert import convert_archive

    ctx = StageContext(temp_dir=Path(args.temp))

    def show(stage: str, pct: float) -> None:
        if not args.json:
            print("\r  [%s] %5.1f%%" % (stage, pct), end="", flush=True)

    ctx.progress_cb = show
    result = convert_archive(Path(args.archive), Path(args.output),
                             Profile(args.profile), ctx,
                             password=_ask_password(args))
    if not args.json:
        print()
    payload = {
        "source": str(result.source),
        "archive": str(result.archive),
        "source_bytes": result.source_bytes,
        "archive_bytes": result.archive_bytes,
        "files": result.files,
        "improved": result.improved,
        "verdict": result.verdict,
        "reasons": result.reasons,
        "elapsed_s": round(result.elapsed_s, 1),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(result.verdict)
        for reason in result.reasons:
            print(f"  {reason}")
        if not result.improved:
            print("the original is still there - nothing was deleted")
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    """F3: put a damaged archive back together from its recovery records."""
    from .recovery import RecoveryStatus, available, repair, verify

    ctx = StageContext(temp_dir=Path(args.temp))
    archive = Path(args.archive)
    if not available():
        print("par2 is not installed, so recovery records cannot be read")
        return 2

    status = verify(archive, ctx)
    if status is RecoveryStatus.OK:
        print(f"{archive.name} is intact - nothing to repair")
        return 0
    if status is RecoveryStatus.NO_RECORDS:
        print(f"no recovery records found beside {archive.name}")
        print("they have to be created up front: excmp compress ... --recovery")
        return 2
    if status is RecoveryStatus.UNREPAIRABLE:
        print(f"{archive.name} is damaged beyond what its recovery records "
              f"can rebuild")
        return 2

    print(f"{archive.name} is damaged but repairable - rebuilding...")
    if repair(archive, ctx):
        print("repaired; the archive now matches its recovery records")
        print(f"confirm the contents too with: excmp verify {archive.name}")
        return 0
    print("repair failed")
    return 2


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
                              _ask_password(args), keyfile=_keyfile(args))
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
    source = Path(args.source) if getattr(args, "source", None) else None
    result = engine.verify_archive(Path(args.archive), ctx,
                                   _ask_password(args),
                                   keyfile=_keyfile(args),
                                   deep=bool(getattr(args, "deep", False)),
                                   source=source)
    payload = {
        "archive": str(result.archive),
        "ok": result.ok,
        "files_restored": result.files_restored,
        "verified": result.verified,
        "elapsed_s": round(result.elapsed_s, 1),
    }
    if result.tree_sha256:
        payload["tree_sha256"] = result.tree_sha256
    if source is not None:
        payload["source"] = str(source)
        payload["source_checked"] = result.source_checked
        payload["source_changed"] = result.source_changed
        payload["source_missing"] = result.source_missing
        payload["source_extra"] = result.source_extra
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"OK: {result.files_restored} file(s) restored and "
              f"{result.verified} SHA-256 hash(es) verified against the "
              f"manifest in {payload['elapsed_s']}s")
        print(f"     {result.archive}")
        if result.tree_sha256:
            print(f"     tree SHA-256 {result.tree_sha256}")
            print(f"     (order-independent; record it and this archive can "
                  f"be compared with one number)")
        if source is not None:
            print()
            print(f"Source re-read: {result.source_checked} original(s) "
                  f"compared against the archive")
            # Printed to stdout, not stderr: these are findings about the
            # user's files, which is a result, not a diagnostic.
            for rel in result.source_changed:
                print(f"  CHANGED  {rel}")
            for rel in result.source_missing:
                print(f"  missing  {rel}")
            for rel in result.source_extra:
                print(f"  new      {rel}")
            if not (result.source_changed or result.source_missing
                    or result.source_extra):
                print("  every original still matches what the archive "
                      "recorded")
    # A changed original is the finding worth an exit code: something that was
    # supposed to be stable is not. A *missing* original is not - deleting the
    # source after archiving it is the point of having an archive - and a new
    # file is news rather than a fault.
    return 1 if result.source_changed else 0


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
    pc.add_argument("--password", action="store_true",
                    help="encrypt the archive (Argon2id + AES-256-GCM over the "
                         "whole container, filenames and hashes included). You "
                         "are prompted twice; the password is never taken on "
                         "the command line. There is no recovery if you lose it")
    pc.add_argument("--keyfile", metavar="FILE",
                    help="a second factor, in addition to the password: this exact "
                         "file must be supplied again to open the archive. "
                         "Only the first 100 MiB is hashed. Losing it is "
                         "exactly as final as losing the password")
    pc.add_argument("--recovery", nargs="?", type=int, const=-1, default=None,
                    metavar="PCT",
                    help="write PAR2 recovery records beside the archive so a "
                         "bad sector or a truncated download can be repaired "
                         "rather than merely detected. Omit the number for a "
                         "size-appropriate default (5%% small, 3%% medium, "
                         "1%% large)")
    pc.add_argument("--format", default="excmp", choices=["excmp", "7z", "zip"],
                    help="'excmp' (default) is our container: per-file SHA-256 "
                         "and a restore we can re-verify any time. '7z' or "
                         "'zip' write a plain archive any tool can open - "
                         "still checked by extracting and hashing before it is "
                         "published, but with no ledger to re-check later")
    pc.add_argument("--split", default=None, metavar="SIZE",
                    help="split the finished archive into volumes of this "
                         "size, e.g. 100m or 4g. Parts are named .001, .002 "
                         "and a .sha256 lists them so a bad transfer can name "
                         "the part to re-fetch. The whole archive is written "
                         "and verified first, then split")
    pc.add_argument("--params", default=None, metavar="SWITCHES",
                    help='extra 7-Zip method switches - use an equals sign, '
                         'e.g. --params="-mqs -myx=9". Method switches only; '
                         '-p/-o/-w/@ are refused')
    pc.add_argument("--sha256", action="store_true",
                    help="also write <archive>.sha256 so a recipient can check "
                         "the transfer with sha256sum -c")
    pc.set_defaults(func=cmd_compress)

    pv = sub.add_parser("convert", help="repack any archive 7-Zip can open as "
                                       "an .excmp, and say whether it helped")
    pv.add_argument("archive")
    pv.add_argument("-o", "--output", required=True)
    pv.add_argument("-p", "--profile", default="normal",
                    choices=[pr_.value for pr_ in Profile])
    pv.add_argument("--temp", default=default_tmp)
    pv.add_argument("--json", action="store_true")
    pv.add_argument("--password", action="store_true",
                    help="prompt for the SOURCE archive's password")
    pv.add_argument("--keyfile", metavar="FILE",
                    help="the same file the SOURCE archive was created with")
    pv.set_defaults(func=cmd_convert)

    pr = sub.add_parser("repair", help="rebuild a damaged archive from its "
                                      "PAR2 recovery records (F3)")
    pr.add_argument("archive")
    pr.add_argument("--temp", default=default_tmp)
    pr.set_defaults(func=cmd_repair)

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
    px.add_argument("--keyfile", metavar="FILE",
                    help="the same file the archive was created with")
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
    pl.add_argument("--keyfile", metavar="FILE",
                    help="the same file the archive was created with")
    pl.set_defaults(func=cmd_list)

    pv = sub.add_parser("verify", help="prove an .excmp archive still restores "
                                       "byte-for-byte (produces nothing)")
    pv.add_argument("archive")
    pv.add_argument("--temp", default=default_tmp)
    pv.add_argument("--json", action="store_true")
    pv.add_argument("--password", action="store_true",
                    help="prompt for the archive's password. Verify had no "
                         "way to take one until 2026-09-09, which left the "
                         "product's central promise - proving an archive "
                         "still restores - unavailable for every encrypted "
                         "archive")
    pv.add_argument("--keyfile", metavar="FILE",
                    help="the same file the archive was created with")
    pv.add_argument("--deep", action="store_true",
                    help="also report an order-independent SHA-256 for the "
                         "whole restored tree, and refuse an archive that "
                         "returns files its ledger does not account for (D5)")
    pv.add_argument("--source", metavar="DIR",
                    help="re-read the ORIGINALS under DIR and compare them "
                         "against the archive - the one check that can find "
                         "bit-rot in your source. DIR is the parent of what "
                         "was archived. Implies nothing about the archive "
                         "itself; requires --deep")
    pv.set_defaults(func=cmd_verify)

    ph = sub.add_parser("hash", help="SHA-256 of files, in sha256sum layout")
    ph.add_argument("paths", nargs="+")
    ph.add_argument("--json", action="store_true")
    ph.set_defaults(func=cmd_hash)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (getattr(args, "keyfile", None) and args.func is cmd_compress
            and not getattr(args, "password", False)):
        # A keyfile alone is a legitimate single factor as far as `crypto` is
        # concerned, but the CLI only ever collects a password interactively -
        # so `--keyfile` without `--password` would hand `engine.compress` a
        # keyfile and no password and write an archive with no encryption at
        # all. Silently producing an unprotected archive for someone who
        # asked for two factors is the worst available outcome.
        parser.error("--keyfile needs --password: the CLI collects the "
                     "password interactively, so without it nothing would "
                     "encrypt the archive at all")
    if getattr(args, "source", None) and not getattr(args, "deep", False):
        # Refused rather than silently ignored, and refused rather than
        # quietly implying --deep: "verify --source" reads as a request about
        # the originals, and honouring half of it without saying so is how a
        # user comes to believe a check ran that did not.
        parser.error("--source needs --deep: re-reading the originals is a "
                     "comparison against the ledger, which a shallow verify "
                     "does not read")
    try:
        return args.func(args)
    except Exception as exc:  # surface a clean one-liner, not a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
