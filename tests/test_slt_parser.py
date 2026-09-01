"""The `7z l -slt` grammar (G2), pinned against real 7-Zip output.

Every fixture below is **captured**, not invented: it came out of
`7z.exe l -slt` 24.07 on archives built for the purpose, and the awkward
cases are awkward because 7-Zip really emits them, not because a parser
author imagined they might.

Deliberately subprocess-free. The parser is the half of foreign listing that
can be wrong in silence — a dropped record, a name truncated at the wrong
`=`, a directory counted as a file — and it is the half that would otherwise
go untested on any machine without `7z.exe`. Feeding it recorded text means
the grammar is covered whether or not the tool is installed, and it means a
future 7-Zip whose output drifts fails *here*, naming the field, instead of
in a GUI that quietly lists nothing.

Source: research/19 section 6 (List.cpp line references) and research/17
section 4 (PeaZip's `list_slt`).
"""

from __future__ import annotations

import pytest

from excmp.slt import classify_failure, parse_slt

# ---------------------------------------------------------------------------
# Captured fixtures
# ---------------------------------------------------------------------------

# `7z l -slt plain.7z` — a solid 7z holding a directory, a file whose *name
# contains " = "*, and two ordinary files. CRLF as emitted.
SEVENZIP_LISTING = "\r\n".join([
    "",
    "7-Zip 24.07 (x64) : Copyright (c) 1999-2024 Igor Pavlov : 2024-06-19",
    "",
    "Scanning the drive for archives:",
    "1 file, 262 bytes (1 KiB)",
    "",
    "Listing archive: plain.7z",
    "",
    "--",
    "Path = plain.7z",
    "Type = 7z",
    "Physical Size = 262",
    "Headers Size = 216",
    "Method = LZMA2:12",
    "Solid = +",
    "Blocks = 1",
    "",
    "----------",
    "Path = sub",
    "Size = 0",
    "Packed Size = 0",
    "Modified = 2026-09-01 14:31:14.6660464",
    "Attributes = D",
    "CRC = ",
    "Encrypted = -",
    "Method = ",
    "Block = ",
    "",
    "Path = a = b.txt",
    "Size = 3",
    "Packed Size = 46",
    "Modified = 2026-09-01 14:31:14.9356278",
    "Attributes = A",
    "CRC = 67AC7170",
    "Encrypted = -",
    "Method = LZMA2:12",
    "Block = 0",
    "",
    "Path = plain.txt",
    "Size = 2400",
    "Packed Size = ",
    "Modified = 2026-09-01 14:31:14.8039228",
    "Attributes = A",
    "CRC = AD121804",
    "Encrypted = -",
    "Method = LZMA2:12",
    "Block = 0",
    "",
    "Path = sub\\nested.bin",
    "Size = 500",
    "Packed Size = ",
    "Modified = 2026-09-01 14:31:14.9336272",
    "Attributes = A",
    "CRC = 0AB2CE51",
    "Encrypted = -",
    "Method = LZMA2:12",
    "Block = 0",
    "",
])

# `7z l -slt aes.zip` with the WRONG password. A zip with AES *data* and
# plaintext *names* lists fine and exits 0 — the encryption shows up per
# entry, not as a failure.
AES_ZIP_LISTING = "\r\n".join([
    "Listing archive: aes.zip",
    "",
    "--",
    "Path = aes.zip",
    "Type = zip",
    "Physical Size = 748",
    "",
    "----------",
    "Path = sub",
    "Folder = +",
    "Size = 0",
    "Packed Size = 0",
    "Modified = 2026-09-01 14:31:14.9326266",
    "Created = ",
    "Accessed = ",
    "Attributes = D",
    "Encrypted = -",
    "CRC = ",
    "Method = ",
    "",
    "Path = plain.txt",
    "Folder = -",
    "Size = 2400",
    "Packed Size = 65",
    "Modified = 2026-09-01 14:31:14.8039228",
    "Created = ",
    "Accessed = ",
    "Attributes = A",
    "Encrypted = +",
    "Comment = ",
    "CRC = ",
    "Method = AES-256 Store",
    "Characteristics = NTFS WzAES : Encrypt",
    "Host OS = FAT",
    "Version = 51",
    "Volume Index = 0",
    "Offset = 0",
    "",
])

ENCRYPTED_HEADERS = "\n".join([
    "7-Zip 24.07 (x64) : Copyright (c) 1999-2024 Igor Pavlov : 2024-06-19",
    "Scanning the drive for archives:",
    "1 file, 334 bytes (1 KiB)",
    "Listing archive: hidden.7z",
    "Errors: 1",
    "ERROR: hidden.7z : Cannot open encrypted archive. Wrong password?",
])

NOT_AN_ARCHIVE = "\n".join([
    "Scanning the drive for archives:",
    "1 file, 300 bytes (1 KiB)",
    "Listing archive: junk.bin",
    "Errors: 1",
    "ERROR: junk.bin : Cannot open the file as archive",
])

NO_SUCH_FILE = "\n".join([
    "Scanning the drive for archives:",
    "ERROR: The system cannot find the file specified.",
    "nope.zip",
])


def names(doc):
    return [e.name for e in doc.entries]


# ---------------------------------------------------------------------------
# The separator
# ---------------------------------------------------------------------------

def test_only_the_first_separator_splits_a_line():
    """`Path = a = b.txt` is a real filename, not a malformed record.

    Splitting on every " = " would name this file "a", and splitting on the
    last would name it "b.txt". Both are wrong, and both are silent: the
    listing still renders, it just lies about what is in the archive.
    """
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert "a = b.txt" in names(doc)


def test_an_empty_value_is_a_value_and_does_not_end_the_record():
    """7-Zip prints `CRC = ` with nothing after it for a directory, and
    `Packed Size = ` for every solid-block member after the first
    (List.cpp:572-578 — a VT_EMPTY property still prints its name). A parser
    that treats an empty right-hand side as the end of a record loses every
    field below it."""
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    by_name = {e.name: e for e in doc.entries}

    # `plain.txt` has `Packed Size = ` and four more fields after it.
    plain = by_name["plain.txt"]
    assert plain.crc == "AD121804", "fields below the empty one were dropped"
    assert plain.size == 2400

    # And the empty value is carried as *unknown*, not as zero. Every member
    # of a solid block after the first has no individual packed size, so a 0
    # here would render as "this file takes up no space".
    assert plain.packed_size is None
    assert by_name["a = b.txt"].packed_size == 46


def test_a_blank_line_ends_one_record():
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert len(doc.entries) == 4


# ---------------------------------------------------------------------------
# Where the items start
# ---------------------------------------------------------------------------

def test_the_banner_and_scan_lines_never_become_entries():
    """Everything before `----------` is chatter. `find_7z_titles` scans for
    the separator rather than skipping a fixed line count (research/17 §4)
    because the banner's height depends on the build and the archive."""
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert "plain.7z" not in names(doc), "the archive-properties block leaked"
    assert all("7-Zip" not in n for n in names(doc))


def test_the_archive_block_is_kept_separately():
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert doc.archive["Type"] == "7z"
    assert doc.archive["Physical Size"] == "262"
    assert doc.kind == "7z"


def test_a_nested_layer_separator_does_not_open_a_new_item():
    """`----` separates nested archive layers (a .tar inside a .gz); only
    `----------` opens the item section."""
    text = SEVENZIP_LISTING + "\r\n".join([
        "----",
        "Path = inner.tar",
        "Type = tar",
        "",
    ])
    doc = parse_slt(text.splitlines())
    assert "inner.tar" not in names(doc)
    assert len(doc.entries) == 4


# ---------------------------------------------------------------------------
# Reading the fields
# ---------------------------------------------------------------------------

def test_backslash_names_are_normalised_to_forward_slashes():
    """Our ledger, our safepath validator and our UI all speak posix-style
    relative paths. 7-Zip speaks Windows."""
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert "sub/nested.bin" in names(doc)
    assert "sub\\nested.bin" not in names(doc)


def test_a_directory_is_recognised_by_either_dialect():
    """7z marks a directory with `Attributes = D`; zip marks it
    `Folder = +`. Both appear in the wild and neither is always present."""
    sevenz = {e.name: e for e in parse_slt(SEVENZIP_LISTING.splitlines()).entries}
    assert sevenz["sub"].is_dir is True
    assert sevenz["plain.txt"].is_dir is False

    zipped = {e.name: e for e in parse_slt(AES_ZIP_LISTING.splitlines()).entries}
    assert zipped["sub"].is_dir is True
    assert zipped["plain.txt"].is_dir is False


def test_an_encrypted_entry_is_flagged_from_the_flag():
    doc = parse_slt(AES_ZIP_LISTING.splitlines())
    by_name = {e.name: e for e in doc.entries}
    assert by_name["plain.txt"].encrypted is True
    assert by_name["sub"].encrypted is False
    assert doc.encrypted is True, "the listing as a whole holds encrypted data"


def test_an_aes_method_flags_encryption_even_without_the_flag():
    """`Encrypted` is handler-driven and not every handler emits it, so
    `Method` containing AES is the second signal (research/17 §4)."""
    text = "\n".join([
        "----------",
        "Path = secret.bin",
        "Size = 10",
        "Method = AES-256 Deflate",
        "",
    ])
    doc = parse_slt(text.splitlines())
    assert doc.entries[0].encrypted is True


def test_nothing_is_encrypted_in_a_plain_archive():
    doc = parse_slt(SEVENZIP_LISTING.splitlines())
    assert doc.encrypted is False
    assert all(not e.encrypted for e in doc.entries)


def test_sizes_parse_and_a_missing_one_is_zero_not_a_crash():
    doc = parse_slt("\n".join([
        "----------",
        "Path = sizeless.bin",
        "Modified = 2026-09-01 14:31:14",
        "",
    ]).splitlines())
    assert doc.entries[0].size == 0


def test_a_record_without_a_path_is_dropped():
    """A property block with no name cannot be listed, extracted or spoken.
    Better absent than rendered as a blank row the user cannot act on."""
    doc = parse_slt("\n".join([
        "----------",
        "Size = 10",
        "CRC = DEADBEEF",
        "",
        "Path = real.txt",
        "Size = 5",
        "",
    ]).splitlines())
    assert names(doc) == ["real.txt"]


def test_crlf_survives_the_split():
    doc = parse_slt(SEVENZIP_LISTING.split("\n"))   # keeps the trailing \r
    assert "plain.txt" in names(doc), "a stray \\r attached itself to the value"
    assert all(not n.endswith("\r") for n in names(doc))


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------

def test_the_row_cap_stops_early_and_admits_it():
    """PeaZip caps at 0.5 M rows because a huge archive's listing is slow and
    unbounded. A cap is fine; a cap the user cannot see is not — a truncated
    list reads exactly like a complete one."""
    body = ["----------"]
    for i in range(50):
        body += [f"Path = file{i:03d}.bin", "Size = 1", ""]
    doc = parse_slt(body, max_items=10)
    assert len(doc.entries) == 10
    assert doc.truncated is True


def test_an_uncapped_listing_is_not_marked_truncated():
    doc = parse_slt(SEVENZIP_LISTING.splitlines(), max_items=1000)
    assert doc.truncated is False


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    (ENCRYPTED_HEADERS, "encrypted"),
    (NOT_AN_ARCHIVE, "corrupt"),
    (NO_SUCH_FILE, "missing"),
    (SEVENZIP_LISTING, ""),
])
def test_failures_are_told_apart(text, expected):
    """"This archive needs a password" and "this file is not an archive" lead
    to completely different next moves — one is a prompt, the other is a dead
    end. Collapsing them into "could not read it" would make the prompt
    impossible."""
    assert classify_failure(text) == expected


def test_an_unrecognised_failure_is_not_guessed_at():
    assert classify_failure("ERROR: something nobody has seen before") == ""
