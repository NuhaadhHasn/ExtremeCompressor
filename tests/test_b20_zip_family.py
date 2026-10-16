"""B20: zip-structured containers that Extreme stored by mistake.

B5 built a structural probe (`analyzer.probe_expandable`) that knows when a
file is a zip with deflated members Precomp can expand, but used it only for
the estimate; the planner kept piping by a suffix list (`_PRECOMP_EXPANDABLE`:
.zip .gz .jar .apk .docx .xlsx .pptx .pdf). So a real EPUB or ODT, whose
deflated bytes look random, was stored at Extreme as "already compressed
... ~0%", and zip-structured files under other names (Android AAR/AAB, NuGet,
APPX, VSIX...) were never probed at all.

Measured 2026-10-16 (docs/benchmarks/2026-10-16-b20-zip-family.md), file by
file, `precomp -cn -intense` then 7-Zip, every output restored and SHA-256
compared:

    type    files   saved    per-file ratio   main at Extreme
    NuGet     3     57.10%     0.36-0.60       all stored
    APPX      2     47.35%     0.49-0.71       all stored
    AAR       7     38.71%     0.47-0.70       5 of 7 stored
    ODT/ODS   4     34.72%     0.60-0.67       1 of 4 stored
    EPUB      6     18.95%     0.67-0.89       all stored
"""

from __future__ import annotations

import random
import zipfile
from pathlib import Path

import pytest

from excmp.analyzer import Category, FileInfo
from excmp.planner import Profile, plan, store_reason
from excmp.tools import ToolInfo

TOOLS = {n: ToolInfo(name=n, path=f"C:/{n}.exe", version="t")
         for n in ("7z", "precomp", "zpaqfranz")}


def _words(n=60_000, seed=1) -> bytes:
    """Text whose deflated form looks random, as a real book's does."""
    rng = random.Random(seed)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz")
                     for _ in range(rng.randint(3, 10))) for _ in range(20_000)]
    return " ".join(rng.choice(vocab) for _ in range(n)).encode()


def _zip(path: Path, deflate=True, encrypt_flag=False) -> Path:
    method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", method) as zf:
        zf.writestr("OEBPS/chapter1.xhtml", _words())
        zf.writestr("OEBPS/chapter2.xhtml", _words(seed=2))
    if encrypt_flag:
        # Set bit 0 (encrypted) on every member, local and central headers,
        # as an encrypted zip carries it: the probe reads flags only.
        data = bytearray(path.read_bytes())
        for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            i = data.find(sig)
            while i != -1:
                data[i + off] |= 0x01
                i = data.find(sig, i + 4)
        path.write_bytes(bytes(data))
    return path


# -- the probe, by content -----------------------------------------------------

@pytest.mark.parametrize("name", ["lib.aar", "pkg.nupkg", "app.appx", "ext.vsix",
                                  "mod.whl", "book.epub", "doc.odt", "plain.bin"])
def test_any_zip_is_probed_whatever_it_is_called(tmp_path, name):
    from excmp.analyzer import analyze_file
    info = analyze_file(_zip(tmp_path / name))
    assert info.category is Category.COMPRESSED_ARCHIVE
    assert info.entropy_bps >= 7.9          # looks incompressible, as real ones do
    assert info.expandable is True


@pytest.mark.parametrize("kwargs", [{"deflate": False}, {"encrypt_flag": True}],
                         ids=["stored-members", "encrypted"])
def test_a_zip_precomp_cannot_open_is_not_expandable(tmp_path, kwargs):
    """B5's rule, kept: nothing deflated, or encrypted (the 263 MB
    `pass=123.zip` that expands to nothing)."""
    from excmp.analyzer import analyze_file
    assert analyze_file(_zip(tmp_path / "x.nupkg", **kwargs)).expandable is False


def test_a_file_merely_named_like_a_zip_is_not_expandable(tmp_path):
    from excmp.analyzer import analyze_file
    p = tmp_path / "book.epub"
    p.write_bytes(random.Random(3).randbytes(200_000))
    assert analyze_file(p).expandable is False


# -- routing -------------------------------------------------------------------

def _container(name, expandable=True):
    return FileInfo(path=Path(name), size=2_000_000, category=Category.COMPRESSED_ARCHIVE,
                    entropy_bps=7.99, sample_ratio=1.0, sample_ratio_max=1.0,
                    expandable=expandable)


@pytest.mark.parametrize("name", ["book.epub", "doc.odt", "sheet.ods", "talk.odp",
                                  "lib.aar", "app.aab", "pkg.nupkg", "app.appx"])
@pytest.mark.parametrize("profile", [Profile.EXTREME, Profile.INSANE])
def test_an_expandable_container_is_piped_where_precomp_runs(name, profile):
    routes = plan([_container(name)], profile, TOOLS).routes
    assert [r.action for r in routes] == ["pipeline"], routes
    assert "precomp" in routes[0].stages


@pytest.mark.parametrize("profile", [Profile.FAST, Profile.NORMAL])
def test_without_precomp_it_stays_stored_and_says_what_would_shrink_it(profile):
    info = _container("book.epub")
    assert [r.action for r in plan([info], profile, TOOLS).routes] == ["store"]
    reason = store_reason(info)
    assert "Extreme" in reason and "~0%" not in reason


def test_a_container_precomp_cannot_open_stays_stored_on_extreme():
    info = _container("pkg.nupkg", expandable=False)
    assert [r.action for r in plan([info], Profile.EXTREME, TOOLS).routes] == ["store"]
    assert "~0%" in store_reason(info)


def test_the_suffix_list_still_pipes_what_it_did():
    """`.gz` is a single deflate stream, not a zip, so the probe says False;
    the suffix list is why it is piped, and that stays."""
    gz = FileInfo(path=Path("data.gz"), size=2_000_000, category=Category.COMPRESSED_ARCHIVE,
                  entropy_bps=7.99, expandable=False)
    assert [r.action for r in plan([gz], Profile.EXTREME, TOOLS).routes] == ["pipeline"]


# -- the estimate --------------------------------------------------------------

@pytest.mark.parametrize("name", ["book.epub", "lib.aar", "pkg.nupkg"])
def test_a_newly_routed_container_is_priced_at_its_worst_file(name):
    """Under the Precomp ceiling ("≤ X"), B18's rule: the worst file of the
    20 measured, an EPUB at 0.888. B5's 0.55 (PDF/Office) would have put the
    ceiling under every EPUB measured."""
    from excmp.estimate import estimate_size
    info = _container(name)
    est = estimate_size([info], plan([info], Profile.EXTREME, TOOLS))
    payload = (est.expected - est.overhead_bytes) / info.size
    assert est.upper_bound and 0.888 <= payload <= 0.90
    assert (est.low - est.overhead_bytes) / info.size <= 0.37
    assert est.high - est.overhead_bytes == info.size


def test_b5_s_types_keep_their_measured_ratio():
    from excmp.estimate import _EXPANDABLE_EXPECTED, estimate_size
    info = _container("report.docx")
    est = estimate_size([info], plan([info], Profile.EXTREME, TOOLS))
    assert (est.expected - est.overhead_bytes) / info.size == pytest.approx(
        _EXPANDABLE_EXPECTED, abs=0.001)


#: Per-file `precomp -cn -intense` -> 7-Zip ratios measured on the B20
#: samples (perfile-*.jsonl), every one restored. The ceiling covers them all.
MEASURED = {"epub": (0.6684, 0.8882, 0.7620, 0.8018, 0.7448, 0.8801),
            "aar": (0.5091, 0.5192, 0.5214, 0.4720, 0.6912, 0.6904, 0.6963),
            "appx": (0.7092, 0.4946), "nupkg": (0.5959, 0.4550, 0.3614),
            "odf": (0.6372, 0.6027, 0.6490, 0.6685)}


def test_the_ceiling_covers_every_measured_file():
    from excmp.estimate import _ZIP_CONTAINER_RATIO
    every = [r for rs in MEASURED.values() for r in rs]
    assert max(every) <= _ZIP_CONTAINER_RATIO[1]
    assert min(every) >= _ZIP_CONTAINER_RATIO[0]


# -- end to end ----------------------------------------------------------------

def test_an_epub_goes_through_precomp_and_comes_back(tmp_path):
    """Through the engine at Extreme: piped, smaller than storing it, and
    byte-identical on the way out. Needs Precomp (not on CI)."""
    import hashlib
    from excmp import engine
    from excmp.stages.base import StageContext
    from excmp.tools import find_tools
    if find_tools().get("precomp") is None:
        pytest.skip("Precomp not installed (it isn't on CI)")
    src = _zip(tmp_path / "book.epub")
    ctx = StageContext(temp_dir=tmp_path / "t")
    out = tmp_path / "m.excmp"
    result = engine.compress([src], out, Profile.EXTREME, ctx)
    assert result.piped_bytes == src.stat().st_size
    assert result.final_bytes < src.stat().st_size * 0.9
    x = engine.extract(out, tmp_path / "x", ctx)
    back = next((tmp_path / "x").rglob(src.name))
    assert x.verified == 1
    assert hashlib.sha256(back.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()
