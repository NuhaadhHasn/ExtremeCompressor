"""An installed app has only what the installer carried. This runs real jobs the way it will: the five bundled
tools staged into an empty folder, every other copy of them hidden (no system 7-Zip, no PATH, no tools/bin),
then compress -> restore -> byte-compare at the profiles that need them. If any bundled tool misbehaves or a
profile silently degrades (the first release lost Extreme and Insane that way), this is where it shows.

Slow (Extreme and Insane run Precomp, zpaqfranz runs at -m58), so one small corpus and three profiles."""

from __future__ import annotations

import hashlib
import io
import random
import sys
import zipfile
from pathlib import Path

import pytest

from excmp import engine, toolfetch, tools
from excmp.planner import Profile
from excmp.stages.base import StageContext

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

pytestmark = pytest.mark.skipif(
    not all((ROOT / "tools" / "bin" / n).is_dir() for n in toolfetch.BUNDLED),
    reason="needs the developer tool folder (tools/bin) to stage from")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    import stage_tools
    dest = tmp_path_factory.mktemp("bundled")
    stage_tools.stage(list(toolfetch.BUNDLED), source_root=ROOT / "tools" / "bin", dest=dest)
    return dest


@pytest.fixture
def only_the_bundle(bundle, monkeypatch):
    """Hide every copy of the tools except the staged one."""
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(bundle))
    monkeypatch.setattr(tools, "APP_BIN", bundle / "does-not-exist")
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    for name in list(tools.CANDIDATES):
        monkeypatch.setitem(tools.CANDIDATES, name, [])
    found = tools.find_tools()
    for name in toolfetch.BUNDLED:
        assert found[name] is not None and Path(found[name].path).is_relative_to(bundle), name
    assert Path(found["7z"].path).name == "7za.exe"          # the Extra build, not the system 7-Zip
    return found


def _corpus(folder: Path) -> dict[str, str]:
    """Text, random bytes, and a zip full of deflate streams (what Precomp exists for)."""
    rng = random.Random(7)
    folder.mkdir()
    (folder / "notes.txt").write_text("".join(f"line {i} of the notes, repeated words repeated words\n"
                                              for i in range(4000)), encoding="utf-8")
    (folder / "noise.bin").write_bytes(rng.randbytes(120_000))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(6):
            z.writestr(f"part{i}.txt", ("chapter %d " % i + "the quick brown fox " * 3000).encode())
    (folder / "bundle.zip").write_bytes(buf.getvalue())
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


@pytest.mark.parametrize("profile", [Profile.NORMAL, Profile.EXTREME, Profile.INSANE])
def test_a_job_with_only_the_bundled_tools_restores_byte_identically(only_the_bundle, tmp_path, profile):
    src = tmp_path / "in"
    want = _corpus(src)
    out = tmp_path / "a.excmp"
    result = engine.compress([src], out, profile, StageContext(temp_dir=tmp_path / "t"))
    assert out.is_file() and out.stat().st_size > 0
    stages = {st for route in result.routes for st in route.get("stages", [])}
    # No silent degrade: each profile must really have run its own chain.
    assert "sevenzip" in stages or "zpaqfranz" in stages, result.routes
    if profile is not Profile.NORMAL:
        assert "precomp" in stages, result.routes
    if profile is Profile.INSANE:
        assert "zpaqfranz" in stages, result.routes
    assert not [w for w in result.warnings if "missing" in w or "not installed" in w], result.warnings
    back = tmp_path / "back"
    engine.extract_any(out, back, StageContext(temp_dir=tmp_path / "t2"))
    got = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in back.rglob("*") if p.is_file()}
    assert got == want
