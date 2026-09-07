"""K3: one locked file must not destroy the whole job.

Reproduced 2026-09-04 with `CreateFileW(dwShareMode=0)` - the way Outlook and
Excel hold a file open. Six files, one locked:

    >>> PermissionError: [Errno 13] Permission denied
    >>> the five readable files were NOT archived

Every other archiver skips it, carries on, and reports it at the end. This
failed the whole job and wrote nothing, which is the worst of the available
outcomes: the user loses the backup of the files that *were* readable because
one of them was not.

Where it actually fails matters for the fix. `analyzer.analyze_file` opens
the file to sniff its category and sample its entropy, and that happens during
collection - *before* the plan exists, before the ledger, before any staging
copy. So the skip has to be taken at collection time and then carried all the
way to the report; catching `PermissionError` around `shutil.copy2` would be
far too late and would leave the file in the ledger, where D9 would refuse to
publish an archive that could not restore it.

The window is not only at collection, though. A file can be locked *between*
being analyzed and being hashed or copied, so those are guarded too and a file
that disappears mid-job is dropped from the ledger rather than failing the run.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

from excmp import engine
from excmp.planner import Profile
from excmp.stages.base import StageContext

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows share-mode locking")

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class DenyAll:
    """Hold a file open with dwShareMode=0, the way a mail client does.

    `msvcrt.locking` is not equivalent - it takes a byte-range lock that does
    not stop another process opening the file - so this has to go through
    CreateFileW to reproduce the real failure.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        CreateFileW.restype = wintypes.HANDLE
        self.handle = CreateFileW(
            str(self.path), GENERIC_READ,
            0,                                  # dwShareMode = 0: deny everyone
            None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if self.handle == INVALID_HANDLE_VALUE or not self.handle:
            raise OSError(f"could not lock {self.path}: "
                          f"{ctypes.get_last_error()}")
        # Prove the lock is real before any test relies on it.
        try:
            with self.path.open("rb"):
                pass
        except PermissionError:
            return self
        self.__exit__(None, None, None)
        raise RuntimeError("the lock did not deny reads - test is invalid")

    def __exit__(self, *_exc):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(self.handle))
            self.handle = None


def _tree(root: Path) -> Path:
    """Six files, mixed routes, so the skip is visible against real work."""
    root.mkdir(parents=True)
    for i in range(3):
        (root / f"text{i}.txt").write_text(f"line {i}\n" * 800, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "more.txt").write_text("lorem ipsum\n" * 800, encoding="utf-8")
    (root / "rand.bin").write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))
    (root / "locked.txt").write_text("held open by another process\n" * 500,
                                     encoding="utf-8")
    return root


def test_a_locked_file_does_not_fail_the_job(tmp_path):
    """The headline: five readable files must still be archived."""
    src = _tree(tmp_path / "src")
    archive = tmp_path / "out.excmp"
    with DenyAll(src / "locked.txt"):
        result = engine.compress([src], archive, Profile.NORMAL,
                                 StageContext(temp_dir=tmp_path / "t"))
    assert archive.is_file(), "the whole job was lost to one locked file"
    listing = engine.list_archive(archive)
    names = sorted(e.name for e in listing.entries)
    assert names == ["src/rand.bin", "src/sub/more.txt", "src/text0.txt",
                     "src/text1.txt", "src/text2.txt"], names


def test_the_locked_file_is_reported_not_silently_dropped(tmp_path):
    """A silent skip is worse than a failure: the user believes the file is
    backed up. It has to come back in the result, by name."""
    src = _tree(tmp_path / "src")
    with DenyAll(src / "locked.txt"):
        result = engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL,
                                 StageContext(temp_dir=tmp_path / "t"))
    assert result.skipped, "a skipped file must be reported"
    assert any("locked.txt" in s for s in result.skipped), result.skipped
    # And in the warnings, which is what the CLI and the GUI actually surface.
    assert any("locked.txt" in w or "1 file" in w for w in result.warnings), \
        result.warnings


def test_the_archive_restores_without_the_locked_file(tmp_path):
    """The skip has to reach the ledger too. If the locked file stayed in it,
    D9's pre-publish restore would compare against a file that is not in the
    archive and refuse to publish - turning a graceful skip back into a total
    failure, just later."""
    src = _tree(tmp_path / "src")
    archive = tmp_path / "out.excmp"
    with DenyAll(src / "locked.txt"):
        engine.compress([src], archive, Profile.NORMAL,
                        StageContext(temp_dir=tmp_path / "t"))
    out = tmp_path / "restored"
    result = engine.extract(archive, out, StageContext(temp_dir=tmp_path / "t2"))
    assert result.verified == 5
    assert not (out / "src" / "locked.txt").exists()
    assert (out / "src" / "text0.txt").is_file()


def test_a_job_that_is_nothing_but_locked_files_says_so(tmp_path):
    """Skipping everything is not success. But the message has to explain
    *why* there is nothing to do, rather than the bare "nothing to compress"
    that a caller would read as "the folder was empty"."""
    src = tmp_path / "src"
    src.mkdir()
    only = src / "locked.txt"
    only.write_text("x" * 5000, encoding="utf-8")
    with DenyAll(only):
        with pytest.raises(ValueError, match="unreadable|locked|skip"):
            engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL,
                            StageContext(temp_dir=tmp_path / "t"))


def test_a_readable_folder_reports_no_skips(tmp_path):
    """The false-positive half: an ordinary job must not mention skipping."""
    src = _tree(tmp_path / "src")
    result = engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL,
                             StageContext(temp_dir=tmp_path / "t"))
    assert result.skipped == []
    assert not any("skip" in w.lower() for w in result.warnings), result.warnings


def test_analyze_tree_skips_what_it_cannot_open(tmp_path):
    """The unit underneath. `analyze_file` opens the file for its category
    sniff and entropy sample, so this is where the PermissionError is really
    raised and where the skip has to start."""
    from excmp.analyzer import analyze_tree_safe

    src = _tree(tmp_path / "src")
    with DenyAll(src / "locked.txt"):
        infos, skipped = analyze_tree_safe(src)
    assert len(infos) == 5
    assert len(skipped) == 1
    path, reason = skipped[0]
    assert path.name == "locked.txt"
    assert reason, "a skip needs a reason a human can read"


# --------------------------------------------------------------------------
# Found by an adversarial audit of the K3 diff, before it was committed.
# Each of these was reproduced by running the code, not by reading it.
# --------------------------------------------------------------------------

def test_the_plain_export_does_not_silently_drop_a_locked_file(tmp_path):
    """A REGRESSION this diff introduced, and the worst kind.

    Before K3, `_collect` called `analyze_tree`, whose `analyze_file` opens
    every file - so a locked file raised `PermissionError` and the `.7z`/`.zip`
    export failed loudly. After K3 the skip is returned instead of raised, and
    `compress_standard` only looked at it in the "nothing readable at all"
    branch. With *some* files locked it published an archive with those files
    absent and said nothing anywhere: no field on `StandardResult`, no
    warning, nothing in the CLI payload.

    D9 cannot catch it either - the plain export compares hashes of the staged
    tree against the extracted tree, and a skipped file is in neither, so
    `verified` counts only what survived.
    """
    src = _tree(tmp_path / "src")
    out = tmp_path / "out.7z"
    with DenyAll(src / "locked.txt"):
        result = engine.compress_standard(
            [src], out, "7z", StageContext(temp_dir=tmp_path / "t"))

    assert result.skipped, "a plain export must report what it left out"
    assert any("locked.txt" in s for s in result.skipped), result.skipped
    assert result.verified == 5


def test_a_locked_store_route_file_does_not_kill_the_job(tmp_path):
    """K3 guarded three reads and missed the one that matters most.

    A store-route file is never staged: its bytes are first read inside
    `write_container`, at `jpeg.pack(read_bytes())` and `zf.write(src, ...)`.
    Neither was guarded, so the exact failure K3 exists to remove was still
    live for stored files - and CLAUDE.md records the analyzer putting **41.9%
    of the real 6.4 GB corpus's bytes** in the store bucket, so this is the
    more likely half of the window, not an edge case.

    The lock is applied after analysis and hashing, which is the real race: a
    file readable when the tree was walked and held open by the time the
    container is written.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "text.txt").write_text("the quick brown fox\n" * 800, encoding="utf-8")
    stored = src / "rand.bin"      # high-entropy -> store route
    stored.write_bytes(bytes((i * 137 + 11) % 256 for i in range(70_000)))

    archive = tmp_path / "out.excmp"
    real_hash = engine.hash_file
    holder = {}

    def hash_then_lock(path):
        digest = real_hash(path)
        if Path(path).name == "rand.bin" and "lock" not in holder:
            holder["lock"] = DenyAll(Path(path))
            holder["lock"].__enter__()
        return digest

    engine.hash_file = hash_then_lock
    try:
        result = engine.compress([src], archive, Profile.NORMAL,
                                 StageContext(temp_dir=tmp_path / "t"))
    finally:
        engine.hash_file = real_hash
        if "lock" in holder:
            holder["lock"].__exit__(None, None, None)

    assert archive.is_file(), "one locked stored file destroyed the whole job"
    assert any("rand.bin" in s for s in result.skipped), result.skipped
    names = [e.name for e in engine.list_archive(archive).entries]
    assert names == ["src/text.txt"], names


def test_an_archive_that_would_contain_nothing_is_not_published(tmp_path):
    """`compress_standard` already refuses this, with the comment "A gate that
    can pass having checked nothing is not a gate". `compress` did not.

    The `if not ledger` guard only ran after the hash loop, but the staging
    copy can empty the ledger too. With every piped file failing there and no
    store route, the job published a container holding only `manifest.json`
    and an empty payload - and because its ledger is empty, `excmp verify`
    passes on it forever, reporting 0 verified files as success.
    """
    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):
        (src / f"t{i}.txt").write_text(f"line {i}\n" * 800, encoding="utf-8")

    archive = tmp_path / "out.excmp"
    import shutil as _sh
    real_copy = _sh.copy2

    def refuse(*a, **kw):
        raise PermissionError(13, "Permission denied")

    _sh.copy2 = refuse
    try:
        with pytest.raises(ValueError, match="could be read"):
            engine.compress([src], archive, Profile.NORMAL,
                            StageContext(temp_dir=tmp_path / "t"))
    finally:
        _sh.copy2 = real_copy
    assert not archive.exists(), "an archive containing nothing was published"


def test_a_skip_names_the_path_not_just_the_basename(tmp_path):
    """A node_modules tree has hundreds of `index.js`. "index.js: in use by
    another program" identifies nothing, and two different skipped files
    produced byte-identical sentences - which is most of the way back to the
    silence this report exists to prevent, because the user cannot go and
    re-archive the file they cannot name."""
    src = tmp_path / "src"
    (src / "a" / "deep").mkdir(parents=True)
    (src / "b").mkdir()
    (src / "keep.txt").write_text("x" * 5000, encoding="utf-8")
    one = src / "a" / "deep" / "index.js"
    two = src / "b" / "index.js"
    for f in (one, two):
        f.write_text("console.log(1)\n" * 400, encoding="utf-8")

    with DenyAll(one), DenyAll(two):
        result = engine.compress([src], tmp_path / "out.excmp", Profile.NORMAL,
                                 StageContext(temp_dir=tmp_path / "t"))

    assert len(result.skipped) == 2, result.skipped
    assert len(set(result.skipped)) == 2,         f"two different files produced the same sentence: {result.skipped}"
    joined = " ".join(result.skipped)
    assert "a/deep/index.js" in joined, joined
    assert "b/index.js" in joined, joined
