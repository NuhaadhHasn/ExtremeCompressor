"""B5: predicting whether Precomp will actually find anything.

`estimate.py` documented this as unknowable - "no cheap signal separates them,
so this is a documented limitation and not a tuning problem" - and on the
evidence available then that was right. The evidence was **entropy sampling**,
which reads raw bytes; two installers with near-identical probe readings had
Precomp find nothing in one and cut the other by 33 points.

Measured 2026-09-07 on 224 real PDF/Office files (136.5 MiB), the claim turns
out to be too strong. There *is* a cheap decisive signal - it is just not in
the bytes, it is in the **container structure**:

    profile   predicted   measured
    normal       9.40%     10.37%    <- fine
    extreme     13.78%     50.36%    <- off by 36.6 points

The comparison table therefore showed Extreme beating Normal by 4 points where
the truth was 40, which steers a user straight past the bigger win on one of
the most ordinary file types there is.

Why the old signal missed it: `zlib_stream` looks for a zlib header at offset
0, and **all 224 files failed that test**. A `.docx` begins `PK\\x03\\x04`; a
PDF's Flate streams are scattered through the body. Their worst-sample ratios
sit at 0.88-0.91, so entropy says "barely compressible" and is not wrong - the
compressible data is one deflate layer down, which is precisely what Precomp
exists to reach.

Why an extension list is not enough either, and this is the part that makes the
probe necessary rather than merely tidier: the estimator backtest corpus holds
`Wondershare ... pass=123.zip`, **263 MB, 37% of that corpus**, on which
Extreme measured 2.97%. It is a `.zip` and Precomp cannot touch it, because its
members are encrypted. Trusting the extension would have predicted a large gain
there and broken a passing backtest.

So the probe reads structure: a ZIP-family container's central directory (no
decompression - just the member flags), and a bounded head scan for a PDF.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from excmp.analyzer import analyze_file


def _docx(path: Path) -> Path:
    """A minimal but genuine OOXML container: deflated members, none
    encrypted."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>" + " " * 4000)
        zf.writestr("word/document.xml",
                    "<document>" + ("lorem ipsum dolor " * 900) + "</document>")
    return path


def _encrypted_zip(path: Path) -> Path:
    """A zip whose members are encrypted. `zipfile` cannot *write* encryption,
    so the general-purpose bit is set by hand - which is exactly the bit the
    probe reads, and the real corpus file that motivated this is checked
    separately below."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("secret.bin", "compressible " * 2000)
    raw = bytearray(path.read_bytes())
    # Set bit 0 of the general purpose flags in both the local header and the
    # central directory entry.
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        at = raw.find(sig)
        assert at >= 0
        off = at + (6 if sig == b"PK\x03\x04" else 8)
        raw[off] |= 0x01
    path.write_bytes(bytes(raw))
    return path


def test_an_ooxml_container_is_seen_as_expandable(tmp_path):
    info = analyze_file(_docx(tmp_path / "doc.docx"))
    assert info.expandable is True


def test_an_encrypted_zip_is_not_expandable(tmp_path):
    """The case that makes this a structural probe rather than an extension
    list. 37% of the estimator's own backtest corpus is an encrypted zip that
    measured 2.97% saved."""
    info = analyze_file(_encrypted_zip(tmp_path / "locked.zip"))
    assert info.expandable is False


def test_a_pdf_with_flate_streams_is_expandable(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 500
                    + b"<< /Filter /FlateDecode /Length 42 >>\nstream\n"
                    + b"y" * 2000 + b"\nendstream\n%%EOF\n")
    assert analyze_file(pdf).expandable is True


def test_a_pdf_without_flate_is_not_claimed(tmp_path):
    """An image-only PDF wrapping DCT data has nothing for Precomp to expand.
    One of the 12 real PDFs sampled looked like this, so it is not a
    hypothetical."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"<< /Filter /DCTDecode >>\n"
                    + bytes((i * 37) % 251 for i in range(4000)) + b"\n%%EOF\n")
    assert analyze_file(pdf).expandable is False


def test_an_ordinary_file_is_not_claimed(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("the quick brown fox\n" * 500, encoding="utf-8")
    assert analyze_file(plain).expandable is False


def test_the_probe_survives_a_truncated_container(tmp_path):
    """A file that merely *starts* like a zip. The probe runs during analysis,
    which K3 just spent a phase making unable to fail the job."""
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    assert analyze_file(broken).expandable is False


# --------------------------------------------------------------------------
# the two real corpora, which disagree with each other on purpose
# --------------------------------------------------------------------------

# 2026-11-21: the owner deletes the originals, so each corpus falls back to a SHA-256-verified
# copy under C:\excmp-bench\temp-copies.
_ENCRYPTED_CANDIDATES = (
    Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check"
         r"\Programs\Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip"),
    Path(r"C:\excmp-bench\temp-copies\Programs"
         r"\Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip"))
_ENCRYPTED = next((p for p in _ENCRYPTED_CANDIDATES if p.is_file()), _ENCRYPTED_CANDIDATES[0])


@pytest.mark.skipif(not _ENCRYPTED.is_file(), reason="needs the Programs corpus")
def test_the_real_encrypted_zip_is_not_claimed():
    """263 MB and 37% of the estimator's backtest corpus, measured at 2.97%
    saved under Extreme. If the probe claimed this one, that backtest would
    break - which is the check that the probe is reading structure and not
    guessing from the extension."""
    assert analyze_file(_ENCRYPTED).expandable is False


_TUTORIALS_CANDIDATES = (
    Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD\0No Need To Check"
         r"\Programming Tutorials, Guides, Course, and Files"),
    # the 51 Office/PDF files this test reads (the first 25 of each type), nothing else
    Path(r"C:\excmp-bench\temp-copies\Programming Tutorials, Guides, Course, and Files"))
def _office_count(root: Path) -> int:
    return sum(1 for ext in ("*.docx", "*.pptx", "*.xlsx", "*.pdf")
               for _ in list(root.rglob(ext))[:25]) if root.is_dir() else 0


# a partly deleted original must not hide the copy: take the first with the 20 files the test needs
_TUTORIALS = next((p for p in _TUTORIALS_CANDIDATES if _office_count(p) >= 20), _TUTORIALS_CANDIDATES[0])


@pytest.mark.skipif(not _TUTORIALS.is_dir(), reason="needs the tutorial corpus")
def test_most_real_office_and_pdf_files_are_claimed():
    """The false-negative half. A probe that claims nothing breaks no test and
    fixes nothing either, so this pins that it fires on real data - measured
    over the same files the 50.36% came from."""
    seen = claimed = 0
    for ext in ("*.docx", "*.pptx", "*.xlsx", "*.pdf"):
        for p in list(_TUTORIALS.rglob(ext))[:25]:
            if p.stat().st_size == 0:
                continue
            seen += 1
            claimed += analyze_file(p).expandable
    assert seen >= 20, f"expected real material, saw {seen}"
    assert claimed / seen >= 0.75, \
        f"only {claimed}/{seen} real Office/PDF files were seen as expandable"
