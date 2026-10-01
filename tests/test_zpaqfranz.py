"""B1 — the zpaqfranz stage, and what makes Insane real.

zpaqfranz does two jobs at once here, which is why it replaces *two* things.
It is the Insane profile's final codec (in place of 7-Zip), and its
content-defined-chunking dedup is the long-range deduplication that left the
product when B11 removed SREP. CDC matches identical fragments at unlimited
distance, so it is the honest answer to the 3.5 points B11 cost us — and
unlike SREP it is MIT, maintained, and has never failed a restore here.

Everything that can be asserted without the binary is asserted without it:
the command builders are separate methods precisely so the switches are
testable on a machine that has never seen zpaqfranz. The handful of tests
that genuinely need the tool skip cleanly when it is absent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from excmp.planner import Profile, _CHAINS, _resolve_chain
from excmp.stages.base import StageContext
from excmp.stages.zpaqfranz import ZpaqfranzStage
from excmp.tools import ToolInfo, find_tools

HAVE = find_tools().get("zpaqfranz") is not None
needs_tool = pytest.mark.skipif(not HAVE, reason="zpaqfranz not installed")

EXE = "C:/zpaqfranz.exe"


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------

def test_insane_uses_m58_by_default():
    """B17: -m58, not -m4. The owner's instruction was "whatever is best for
    compression". Measured on the 237 MB deflate .pcf, every archive restored
    and SHA-256 compared:

        -m4  46,575,605    -m5 (64 MiB blocks)  43,194,463
        -m57 (128 MiB) 42,933,026    -m58 (256 MiB)  42,852,397

    -m5 was already the smallest codec measured on both B12 corpora, LOLZ
    included, and bigger blocks took another 0.79% off. -m58 is the largest
    block whose two-thread peak fits the RAM budget on the 16 GB target.
    """
    cmd = ZpaqfranzStage().build_compress_cmd(Path("in"), Path("out.zpaq"), 2, EXE)
    assert "-m58" in cmd
    assert not [a for a in cmd if a in ("-m4", "-m5", "-m57")], cmd


def test_m4_stays_reachable():
    """The faster setting is still one argument away, for anyone who wants
    Insane's dedup without -m58's wait and RAM."""
    cmd = ZpaqfranzStage(method=4).build_compress_cmd(Path("in"), Path("o.zpaq"), 2, EXE)
    assert "-m4" in cmd and "-m5" not in cmd


def test_the_engine_runs_insane_at_the_default_method():
    """The engine builds this stage with no arguments, so the default *is* what
    Insane runs. A default changed here but shadowed by an explicit method in
    `_stage_factory` would pass the test above and ship -m4 anyway."""
    from excmp.engine import _stage_factory
    from excmp.stages.zpaqfranz import DEFAULT_METHOD
    stage = _stage_factory()["zpaqfranz"]
    assert stage.method == DEFAULT_METHOD == 58


def test_extract_names_no_method():
    """Restoring must not depend on how the archive was written: a zpaq block
    carries its own decoder description. Archives made at -m4 before B17 are
    restored by the same command as those made at -m58 after it."""
    for method in (4, 5, 57, 58):
        cmd = ZpaqfranzStage(method=method).build_extract_cmd(
            Path("a.zpaq"), Path("out"), EXE)
        assert not [a for a in cmd if a.startswith("-m")], cmd


def test_longpath_is_always_on():
    r"""zpaqfranz only prepends the \\?\ prefix when -longpath is passed;
    without it a deep tree silently fails to add. research/20 §7 says make
    this default-on rather than a flag, so there is no way to switch it off.
    """
    for method in (4, 5):
        cmd = ZpaqfranzStage(method=method).build_compress_cmd(
            Path("in"), Path("o.zpaq"), 2, EXE)
        assert "-longpath" in cmd


def test_the_archive_stays_readable_by_vanilla_zpaq():
    """Plain `a` only. `backup` (multipart), ZETA and W-chunk archives cannot
    be opened by zpaq 7.15 or unzpaq206, and an archive only our build can
    read is a lock-in we did not agree to. research/20 §6."""
    cmd = ZpaqfranzStage().build_compress_cmd(Path("in"), Path("o.zpaq"), 2, EXE)
    assert cmd[1] == "a"
    for forbidden in ("backup", "-zeta", "-chunk"):
        assert forbidden not in cmd


def test_threads_are_passed_and_zero_means_tool_default():
    assert "-t2" in ZpaqfranzStage().build_compress_cmd(
        Path("i"), Path("o.zpaq"), 2, EXE)
    assert not [a for a in ZpaqfranzStage().build_compress_cmd(
        Path("i"), Path("o.zpaq"), 0, EXE) if a.startswith("-t")]


def test_extract_never_uses_the_captcha_path():
    """`t -paranoid -to <dir>` prompts for an interactive captcha when the
    target is non-empty (research/20 §6, `getcaptcha`). Under
    CREATE_NO_WINDOW that prompt has nowhere to appear, so it would hang the
    app exactly the way the missing 7-Zip -p did before G2."""
    cmd = ZpaqfranzStage().build_extract_cmd(Path("a.zpaq"), Path("out"), EXE)
    assert "-paranoid" not in cmd
    assert cmd[1] == "x"


def test_extract_targets_the_destination_we_chose():
    cmd = ZpaqfranzStage().build_extract_cmd(Path("a.zpaq"), Path("out"), EXE)
    assert "-to" in cmd and str(Path("out")) in cmd


def test_test_command_is_the_non_interactive_one():
    """`t` alone re-reads and re-hashes without a target directory, so it
    cannot reach the captcha. It is a supplement to our own SHA-256 gate,
    never a replacement for it."""
    cmd = ZpaqfranzStage().build_test_cmd(Path("a.zpaq"), EXE)
    assert cmd[1] == "t"
    assert "-to" not in cmd and "-paranoid" not in cmd


# ---------------------------------------------------------------------------
# Wiring into the planner - where the regressions would be
# ---------------------------------------------------------------------------

def test_insane_now_actually_uses_zpaqfranz():
    assert any(t == "zpaqfranz" for _s, t in _CHAINS["insane"])


def test_insane_no_longer_claims_it_is_not_integrated():
    """The warning string was asserted by a test for months. Leaving it in
    place after wiring the stage would be a lie printed in the UI."""
    tools = {"precomp": ToolInfo("precomp", "p", ""),
             "zpaqfranz": ToolInfo("zpaqfranz", "z", ""),
             "7z": ToolInfo("7z", "7", "")}
    _stages, warnings = _resolve_chain(Profile.INSANE, tools)
    assert not any("not integrated" in w for w in warnings)


def test_insane_without_zpaqfranz_falls_back_to_a_real_final_codec():
    """The regression this change could easily introduce.

    `_resolve_chain` drops a stage whose tool is missing. Applied naively to
    the new Insane chain that leaves `["precomp"]` — a chain whose *final*
    output is a .pcf, i.e. an intermediate precomp stream published as if it
    were the archive. Insane must degrade to the Extreme chain, not to half
    of itself.
    """
    tools = {"precomp": ToolInfo("precomp", "p", ""),
             "zpaqfranz": None,
             "7z": ToolInfo("7z", "7", "")}
    stages, warnings = _resolve_chain(Profile.INSANE, tools)
    assert stages[-1] == "sevenzip", stages
    assert any("zpaqfranz" in w for w in warnings)


def test_insane_with_neither_final_codec_still_terminates_sanely():
    tools = {"precomp": ToolInfo("precomp", "p", ""), "zpaqfranz": None, "7z": None}
    stages, _w = _resolve_chain(Profile.INSANE, tools)
    assert stages[-1] in ("zstd", "sevenzip"), stages


def test_a_chain_never_ends_on_an_intermediate_stage():
    """Generalises the case above: precomp and tar both emit something that
    is not an archive, so neither may ever be the last stage of any profile
    under any combination of installed tools."""
    intermediate = {"precomp", "tar", "srep"}
    every_combination = [
        {"precomp": None, "zpaqfranz": None, "7z": None},
        {"precomp": ToolInfo("precomp", "p", ""), "zpaqfranz": None, "7z": None},
        {"precomp": ToolInfo("precomp", "p", ""), "zpaqfranz": None,
         "7z": ToolInfo("7z", "7", "")},
        {"precomp": None, "zpaqfranz": ToolInfo("zpaqfranz", "z", ""), "7z": None},
    ]
    for tools in every_combination:
        for profile in Profile:
            stages, _w = _resolve_chain(profile, tools)
            assert stages, f"{profile} produced an empty chain for {tools}"
            assert stages[-1] not in intermediate, (
                f"{profile.value} ends on '{stages[-1]}' with {tools}")


def test_the_payload_extension_is_registered():
    """A stage the engine cannot name a file for produces an archive it
    cannot find again."""
    from excmp.engine import _PAYLOAD_EXT

    assert _PAYLOAD_EXT["zpaqfranz"] == ".zpaq"


def test_zpaqfranz_is_deliberately_not_tree_capable():
    """It *is* a real archiver, so listing it as tree-capable looks right —
    and it was, until the first real run. zpaqfranz stores the **absolute**
    path it was handed (drive letter mangled to `C_`) and `add` has no switch
    to store a relative one, so extracting a tree rebuilds
    `out/C_/Users/.../file` and no ledger key ever matches.

    Forcing a tar in front means it only ever sees one file, which is also
    what makes the relocation in `extract` unambiguous. Dedup is unaffected:
    CDC works on the byte stream, so identical fragments inside the tar are
    still matched at unlimited distance.
    """
    from excmp.engine import _TREE_CAPABLE

    assert "zpaqfranz" not in _TREE_CAPABLE


# ---------------------------------------------------------------------------
# Live round-trip - the only thing that actually proves it works
# ---------------------------------------------------------------------------

@needs_tool
def test_a_real_roundtrip_is_byte_identical(tmp_path):
    """One file in, the same bytes out, at a sane path.

    The single-file shape is the contract now: the engine puts a tar in front
    of this stage precisely so the absolute-path mangling has nowhere to go.
    """
    payload = tmp_path / "payload.tar"
    payload.write_bytes(b"hello world\n" * 500 + bytes(range(256)) * 200)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()

    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = ZpaqfranzStage()
    archive = stage.compress(payload, tmp_path / "out.zpaq", ctx)
    assert archive.exists() and archive.stat().st_size > 0

    out = stage.extract(archive, tmp_path / "restored", ctx)
    assert out.is_file(), f"expected a file, got {out}"
    assert out.name == "payload.tar", (
        f"the real filename must survive; got {out.name}")
    assert "C_" not in str(out), (
        f"the stored absolute path leaked into the restore: {out}")
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest


@needs_tool
def test_an_archive_written_before_b17_still_restores(tmp_path):
    """Every Insane archive made before B17 was written at -m4. The stage as
    it now stands - defaulting to -m58 - must restore one byte for byte, or
    changing the default would have orphaned the user's existing archives.
    """
    payload = tmp_path / "old.tar"
    payload.write_bytes(b"written at -m4 before B17\n" * 4000 + bytes(range(256)) * 64)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()

    ctx = StageContext(temp_dir=tmp_path / "tmp")
    archive = ZpaqfranzStage(method=4).compress(payload, tmp_path / "old.zpaq", ctx)
    out = ZpaqfranzStage().extract(archive, tmp_path / "restored", ctx)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest


@needs_tool
def test_dedup_actually_finds_distant_duplicates(tmp_path):
    """The whole reason this stage exists.

    The same multi-MB blob twice inside one stream, far apart, must not cost
    twice the space — that is the unlimited-distance CDC dedup SREP used to
    provide, and it is what B11 took away. One file rather than two because
    that is the shape the stage now receives (a tar), which is also the shape
    that proves CDC works *within* a stream rather than only across files.
    """
    blob = (b"a repeating quantum of data. " * 64 + bytes(range(256))) * 512
    filler = bytes((i * 7 + 3) % 251 for i in range(len(blob) // 4))
    payload = tmp_path / "twice.tar"
    payload.write_bytes(blob + filler + blob)

    ctx = StageContext(temp_dir=tmp_path / "tmp")
    archive = ZpaqfranzStage().compress(payload, tmp_path / "d.zpaq", ctx)
    # Two copies of the blob plus filler; a deduplicating archiver stores ~one.
    assert archive.stat().st_size < len(blob) * 0.75, (
        f"{archive.stat().st_size:,} bytes for 2x{len(blob):,} - dedup did not fire")


@needs_tool
def test_the_tools_own_check_passes_on_what_we_wrote(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_bytes(b"content\n" * 1000)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = ZpaqfranzStage()
    archive = stage.compress(src, tmp_path / "t.zpaq", ctx)
    stage.test(archive, ctx)  # raises StageError if zpaqfranz disagrees
