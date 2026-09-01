"""The `7z l -slt` output grammar, and nothing else (G2).

Text in, structure out. No subprocess, no filesystem, no knowledge of what an
archive is for — which is deliberate: this is the half of foreign listing that
can be wrong *in silence*. A record split at the wrong `=` still renders a
tidy-looking list, it just names files that are not in the archive. Keeping
the grammar in a pure function means it is covered by recorded output on any
machine, including one where `7z.exe` is not installed at all.

The grammar is source-pinned rather than reverse-engineered
(research/19 section 6, quoting 7-Zip's own ``List.cpp``; research/17
section 4, quoting PeaZip's ``list_slt``):

* Everything up to a line of exactly ``----------`` is chatter — a banner
  whose height depends on the build, then the archive's own property block.
  PeaZip scans for the separator instead of skipping a line count, and so do
  we.
* Each item is a run of ``Name = value`` lines terminated by a blank line.
* The separator is the **first** ``" = "`` on the line. A file may legally be
  called ``a = b.txt``, and 7-Zip really does emit ``Path = a = b.txt``.
* **An empty right-hand side is a value, not a terminator.** A VT_EMPTY
  property still prints its name (``List.cpp:572-578``), so directories carry
  ``CRC = `` and every solid-block member after the first carries
  ``Packed Size = ``.
* ``--`` opens the archive-properties block; ``----`` separates nested
  archive layers (a tar inside a gz). Neither opens an item.

Field *vocabulary* is handler-driven — 7z emits ``Attributes``, zip emits
``Folder``, and the full ``kPropIdToName[]`` table runs to a hundred names —
so every reader below treats its field as optional and has a defined answer
when it is missing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

#: Where the item records begin. Exactly ten dashes, on a line of its own.
_ITEMS_MARK = "----------"

#: The key/value separator. Spaces included: splitting on a bare ``=`` would
#: cut ``a = b.txt`` in the wrong place.
_SEP = " = "

#: Above this many entries a listing stops being something a person reads and
#: starts being something that eats the UI thread. PeaZip caps at 0.5 M rows;
#: this is a two-core laptop with a 1366x768 screen, and nobody scrolls fifty
#: thousand rows. The cap is honest rather than silent: :attr:`SltDocument.truncated`
#: exists so the surface above can say the list is partial, because a
#: truncated listing reads exactly like a complete one.
MAX_ITEMS = 50_000

#: Line budget for the *reader* feeding this parser. Roughly ten lines per
#: record at :data:`MAX_ITEMS`, plus slack for chatty handlers.
MAX_LINES = 600_000


@dataclass
class SltEntry:
    """One member of a foreign archive, as 7-Zip described it.

    Note what is *not* here: a SHA-256. 7-Zip reports CRC-32, and the two are
    not interchangeable — one is a 32-bit error check, the other is this
    project's integrity guarantee. They get different fields all the way up
    so that no surface can accidentally print one under the other's name.
    """

    name: str
    size: int = 0
    #: ``None`` means 7-Zip printed nothing here, which is **not** zero bytes.
    #: Every member of a solid block after the first gets an empty
    #: ``Packed Size =`` because the block is compressed as one unit and no
    #: per-file figure exists. Rendering that as "0 B" would put a number on
    #: screen that says these files cost nothing to store.
    packed_size: int | None = None
    modified: str = ""
    crc: str = ""
    method: str = ""
    encrypted: bool = False
    is_dir: bool = False


@dataclass
class SltDocument:
    archive: dict[str, str] = field(default_factory=dict)
    entries: list[SltEntry] = field(default_factory=list)
    #: True when the cap stopped us before the archive did. The listing is a
    #: prefix, and every surface that shows it has to say so.
    truncated: bool = False

    @property
    def kind(self) -> str:
        """7-Zip's own name for the format, lower-cased: ``zip``, ``7z``,
        ``rar5``, ``iso``. Empty when the handler did not say."""
        return self.archive.get("Type", "").strip().lower()

    @property
    def encrypted(self) -> bool:
        return any(e.encrypted for e in self.entries)

    @property
    def solid(self) -> bool:
        """7-Zip's own answer to "can one member be read on its own?".

        A solid archive is compressed as one stream, so pulling one file out
        of it decodes everything up to that file. Worth saying before a user
        ticks one row in a 4 GB archive and waits.
        """
        return self.archive.get("Solid", "").strip() == "+"


def _split(line: str) -> tuple[str, str] | None:
    """``"Path = a = b.txt"`` -> ``("Path", "a = b.txt")``.

    Returns None for a line with no separator at all, which is how the
    section markers and stray chatter are recognised.
    """
    head, sep, tail = line.partition(_SEP)
    if not sep:
        # `Key =` with nothing after it, not even the trailing space, is how
        # some handlers render an empty value at end of line.
        if line.endswith(" =") and len(line) > 2:
            return line[:-2], ""
        return None
    return head, tail


def _as_int(value: str) -> int:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return 0


def _as_opt_int(value: str) -> int | None:
    """``None`` for a field the handler left blank.

    The distinction matters exactly once and it matters a lot: a solid
    block's members carry no individual packed size, and collapsing "not
    stated" into 0 produces a column of confident zeroes. Same shape as
    ``ExtractResult.ledger_backed`` - where a number could mean two things,
    carry which one it is.
    """
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _entry_from(props: dict[str, str]) -> SltEntry | None:
    name = props.get("Path", "").strip()
    if not name:
        # No name means nothing can be listed, selected, extracted or spoken
        # about it. Better dropped than rendered as a blank row.
        return None

    attributes = props.get("Attributes", "")
    method = props.get("Method", "").strip()
    return SltEntry(
        # Our ledger, safepath and UI all speak posix-style relative paths;
        # 7-Zip speaks Windows.
        name=name.replace("\\", "/"),
        size=_as_int(props.get("Size", "")),
        packed_size=_as_opt_int(props.get("Packed Size", "")),
        modified=props.get("Modified", "").strip(),
        crc=props.get("CRC", "").strip(),
        method=method,
        # Two signals, because `Encrypted` is handler-driven and not every
        # handler emits it (research/17 §4 flags AES in `Method` for exactly
        # this reason).
        encrypted=props.get("Encrypted", "").strip() == "+" or "AES" in method,
        # Two dialects: 7z says `Attributes = D`, zip says `Folder = +`.
        is_dir=props.get("Folder", "").strip() == "+" or "D" in attributes,
    )


def parse_slt(lines: Iterable[str], max_items: int = MAX_ITEMS) -> SltDocument:
    """Parse `7z l -slt` output into an archive block and a list of members.

    Consumes ``lines`` lazily and **returns as soon as the cap is reached**,
    so a caller streaming a subprocess can stop the tool rather than read a
    million rows it will not show.
    """
    doc = SltDocument()
    in_items = False
    props: dict[str, str] = {}

    def flush() -> bool:
        """Close the record in hand. Returns False when the cap is hit."""
        nonlocal props
        if not props:
            return True
        entry = _entry_from(props)
        props = {}
        if entry is None:
            return True
        if len(doc.entries) >= max_items:
            doc.truncated = True
            return False
        doc.entries.append(entry)
        return True

    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped == _ITEMS_MARK:
            # The archive block ends here even if it had no blank line after
            # it, and anything already collected belongs to the archive.
            if not in_items and not doc.archive:
                doc.archive.update({k: v.strip() for k, v in props.items()})
            props = {}
            in_items = True
            continue
        if stripped and set(stripped) == {"-"}:
            # `--` opens an archive-properties block and `----` opens a
            # *nested layer's* (a tar inside a gz). Either way what follows
            # describes an archive, not a member - without this, a nested
            # layer's `Path = inner.tar` is listed as a file that is not in
            # the archive. Only the outermost block sets `Type`, because that
            # is the format the user is actually holding.
            if not flush():
                return doc
            in_items = False
            continue
        if not stripped:
            if not flush():
                return doc
            continue

        pair = _split(line)
        if pair is None:
            # `--`, `----`, `Listing archive: x`, `Errors: 1`. None of them
            # opens a record; `----` in particular marks a *nested layer*,
            # whose properties would otherwise be listed as a member.
            if not flush():
                return doc
            continue

        key, value = pair
        if in_items:
            props[key.strip()] = value
        else:
            doc.archive[key.strip()] = value.strip()

    flush()
    return doc


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

# Captured from 7-Zip 24.07 rather than recalled. Each maps to a different
# next move for the user, which is the entire reason to tell them apart:
# "encrypted" leads to a password prompt, "corrupt" is a dead end, and
# "missing" is a typo in a path.
_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("encrypted", "cannot open encrypted archive"),
    ("encrypted", "wrong password"),
    ("corrupt", "cannot open the file as archive"),
    ("corrupt", "is not archive"),
    ("corrupt", "unsupported method"),
    ("corrupt", "unexpected end of archive"),
    ("corrupt", "headers error"),
    ("missing", "the system cannot find the file"),
    ("missing", "cannot find archive"),
)


def classify_failure(text: str) -> str:
    """``"encrypted"``, ``"corrupt"``, ``"missing"`` or ``""``.

    An empty string means *this output does not look like a failure* — never
    "some unknown failure". A caller that guessed "corrupt" for output it did
    not recognise would tell somebody their archive was broken on the
    strength of a string 7-Zip changed between releases.
    """
    lowered = text.lower()
    for verdict, needle in _SIGNATURES:
        if needle in lowered:
            return verdict
    return ""
