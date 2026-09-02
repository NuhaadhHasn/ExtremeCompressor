"""D1 — the one property that is the whole product.

    for every file tree T:  extract(compress(T)) == T, byte for byte.

Everything else this repo does is in service of that sentence, so it is worth
stating once as an executable claim rather than only as a set of examples.
`test_edge_cases.py` covers the awkward cases we *thought of*; this file is
here for the ones we did not.

Hypothesis builds the trees: names drawn from the characters that actually
break archivers (unicode, spaces, dots, digits), contents drawn from the three
regimes a compressor treats differently (compressible, random, empty), nesting
drawn shallow-to-deep. On failure it shrinks to the smallest tree that still
breaks, which is the entire reason for using it over a loop of random cases.

Deliberately modest limits. Every example is a real compress-and-extract
through the engine and takes real seconds, so this runs a small number of
thorough examples rather than a large number of shallow ones. `deadline=None`
because subprocess timings on a 2-core laptop are not a correctness signal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from excmp.engine import compress, extract
from excmp.planner import Profile
from excmp.stages.base import StageContext

# Characters chosen because each has broken a real archiver: spaces and dots
# (Windows strips trailing ones), non-ASCII (code-page mangling), digits and
# dashes (look like switches to a CLI).
NAME_CHARS = st.sampled_from("abcXYZ019 -_.=()#&éüñ日本語")

names = (st.text(NAME_CHARS, min_size=1, max_size=24)
         .map(str.strip)
         .filter(lambda s: s and s not in {".", ".."} and not s.endswith(".")))

# The three regimes: compressible, incompressible, and nothing at all. A
# codec's behaviour differs sharply between them and so does our routing.
contents = st.one_of(
    st.builds(lambda n: b"repeating block " * n, st.integers(1, 400)),
    st.binary(min_size=0, max_size=4096),
    st.just(b""),
)


@st.composite
def file_trees(draw: st.DrawFn) -> dict[str, bytes]:
    """A mapping of relative POSIX path -> content.

    Directory depth is drawn per file rather than per tree, so a single
    example can mix a top-level file with something four levels down - the
    shape that has historically exposed prefix-handling bugs.
    """
    count = draw(st.integers(min_value=1, max_value=6))
    tree: dict[str, bytes] = {}
    for _ in range(count):
        depth = draw(st.integers(min_value=0, max_value=3))
        parts = [draw(names) for _ in range(depth)] + [draw(names)]
        rel = "/".join(parts)
        # A name used as both a file and a directory is not representable on
        # any filesystem; skip rather than pretend we handle it.
        if any(rel.startswith(other + "/") or other.startswith(rel + "/")
               for other in tree):
            continue
        tree[rel] = draw(contents)
    return tree


def _materialise(root: Path, tree: dict[str, bytes]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for rel, data in tree.items():
        target = root / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError:
            continue        # the filesystem refused it; not our claim to test
        digests[rel] = hashlib.sha256(data).hexdigest()
    return digests


@settings(max_examples=12, deadline=None,
          suppress_health_check=[HealthCheck.too_slow,
                                 HealthCheck.function_scoped_fixture])
@given(tree=file_trees())
def test_any_tree_survives_a_roundtrip(tmp_path_factory, tree):
    """The product's whole claim, as a property."""
    tmp_path = tmp_path_factory.mktemp("prop")
    src = tmp_path / "src"
    src.mkdir()
    expected = _materialise(src, tree)
    if not expected:
        pytest.skip("filesystem refused every generated name")

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.FAST,
             StageContext(temp_dir=tmp_path / "t", threads=2))
    out = tmp_path / "out"
    extract(archive, out, StageContext(temp_dir=tmp_path / "xt", threads=2))

    got = {p.relative_to(out).as_posix():
           hashlib.sha256(p.read_bytes()).hexdigest()
           for p in out.rglob("*") if p.is_file()}

    for rel, digest in expected.items():
        match = [v for k, v in got.items() if k.endswith(rel)]
        assert match, f"{rel!r} did not come back. Got {sorted(got)}"
        assert match[0] == digest, f"{rel!r} came back with different bytes"


@settings(max_examples=10, deadline=None,
          suppress_health_check=[HealthCheck.too_slow,
                                 HealthCheck.function_scoped_fixture])
@given(tree=file_trees())
def test_no_tree_is_ever_modified_by_compressing_it(tmp_path_factory, tree):
    """The second promise: reading your files must not change them."""
    tmp_path = tmp_path_factory.mktemp("prop2")
    src = tmp_path / "src"
    src.mkdir()
    if not _materialise(src, tree):
        pytest.skip("filesystem refused every generated name")

    before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in src.rglob("*") if p.is_file()}

    compress([src], tmp_path / "a.excmp", Profile.FAST,
             StageContext(temp_dir=tmp_path / "t", threads=2))

    for path, (data, mtime) in before.items():
        assert path.read_bytes() == data, f"{path.name} was modified"
        assert path.stat().st_mtime_ns == mtime, f"{path.name}'s mtime changed"


@settings(max_examples=8, deadline=None,
          suppress_health_check=[HealthCheck.too_slow,
                                 HealthCheck.function_scoped_fixture])
@given(tree=file_trees())
def test_the_ledger_accounts_for_every_file(tmp_path_factory, tree):
    """The ledger is what `verify_restore` checks against, so a file missing
    from it is a file nobody will ever notice failing to come back."""
    from excmp.manifest import read_container

    tmp_path = tmp_path_factory.mktemp("prop3")
    src = tmp_path / "src"
    src.mkdir()
    expected = _materialise(src, tree)
    if not expected:
        pytest.skip("filesystem refused every generated name")

    archive = tmp_path / "a.excmp"
    compress([src], archive, Profile.FAST,
             StageContext(temp_dir=tmp_path / "t", threads=2))

    manifest, _payload = read_container(archive, tmp_path / "peek")
    assert len(manifest.inputs) == len(expected), (
        f"ledger has {len(manifest.inputs)} entries for {len(expected)} files")
    for meta in manifest.inputs.values():
        assert meta.get("sha256"), "a ledger entry carries no hash"
        assert meta.get("route") in ("pipeline", "store")
