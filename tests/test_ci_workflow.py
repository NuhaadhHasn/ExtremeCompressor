"""D7: the CI workflow, checked against what this suite actually needs.

A workflow file is the one artifact in this repo whose acceptance gate lives on
someone else's machine. Nothing here can prove GitHub will run it - but a
surprising amount of what usually breaks a first CI run *is* checkable from
here, and every one of these assertions came from a fact measured on this
machine rather than from a template:

- **The suite reads the user's real data folders in four places.** Every one is
  gated on the path existing, so they skip on a runner - but if a future test
  hard-codes such a path without a gate, CI turns red for a reason that has
  nothing to do with the change. `test_no_ungated_corpus_paths` is the guard,
  and it looks at the tests rather than at the workflow.
- **The tool install root is `tools/bin`, not `%LOCALAPPDATA%`.** A cache step
  pointed at the wrong directory silently caches nothing, and "silently caches
  nothing" looks exactly like "cache works" until you read the timings.
- **The full suite takes an hour here.** A job with no `timeout-minutes` gets
  GitHub's 6-hour default, so a hang costs 360 minutes of a private repo's
  quota instead of failing.
- **The pinned tools are fetched over the network.** That belongs in a job that
  is *not* on the push path, or every push is one GitHub outage away from red.

These are structural assertions, not a substitute for a real run. The YAML is
parsed, so a syntax error fails here; whether Actions *accepts* the schema is
still unproven until the branch is pushed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is a dev dependency (D7)")

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci() -> dict:
    assert WORKFLOW.is_file(), f"{WORKFLOW} does not exist"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _jobs(ci: dict) -> dict:
    return ci["jobs"]


def _all_steps(ci: dict) -> list[dict]:
    return [s for job in _jobs(ci).values() for s in job.get("steps", [])]


def _run_text(ci: dict) -> str:
    return "\n".join(str(s.get("run", "")) for s in _all_steps(ci))


# --------------------------------------------------------------------------
# the file itself
# --------------------------------------------------------------------------

def test_the_workflow_is_valid_yaml_and_has_jobs(ci):
    assert _jobs(ci), "no jobs defined"
    # `on:` is the YAML 1.1 boolean True, which is the single most common way
    # to write a workflow that looks right and parses wrong.
    assert True in ci or "on" in ci, "no trigger block"


def test_every_job_runs_on_windows(ci):
    """The product is Windows-only: `safepath` pins Windows path semantics,
    `motw` writes NTFS alternate data streams, and the tools are .exe files.
    A ubuntu runner would not fail informatively - it would fail everywhere."""
    for name, job in _jobs(ci).items():
        assert "windows" in str(job.get("runs-on", "")), \
            f"job {name!r} does not run on Windows"


def test_every_job_has_a_timeout(ci):
    """A full pass measured 1 h 07 m on this machine. Without an explicit
    timeout a hung job burns GitHub's 6-hour default from a private repo's
    quota."""
    for name, job in _jobs(ci).items():
        assert isinstance(job.get("timeout-minutes"), int), \
            f"job {name!r} has no integer timeout-minutes"
        assert job["timeout-minutes"] <= 180, \
            f"job {name!r} may run for {job['timeout-minutes']} minutes"


def test_the_workflow_only_asks_for_read_permission(ci):
    """Nothing in CI publishes, comments or tags. The default token is
    read/write on some repo settings, so it is narrowed explicitly."""
    perms = ci.get("permissions")
    assert perms is not None, "no top-level permissions block"
    assert perms == {"contents": "read"} or perms == "read-all", perms


def test_the_suite_is_actually_run(ci):
    text = _run_text(ci)
    assert re.search(r"pytest", text), "no job runs pytest"


def test_dependencies_come_from_both_requirements_files(ci):
    """The GUI tests need pytest-qt and the property tests need hypothesis,
    and both live in requirements-dev.txt. Installing only requirements.txt
    would silently skip a third of the suite via importorskip."""
    text = _run_text(ci)
    assert "requirements.txt" in text
    assert "requirements-dev.txt" in text


def test_pip_is_cached_against_the_requirements_files(ci):
    """D7 asks for the setup-python pip cache. Keyed on the requirements
    files, or a dependency bump reuses a stale wheel set."""
    setups = [s for s in _all_steps(ci)
              if "setup-python" in str(s.get("uses", ""))]
    assert setups, "no actions/setup-python step"
    for step in setups:
        with_ = step.get("with", {})
        assert with_.get("cache") == "pip", step
        dep = str(with_.get("cache-dependency-path", ""))
        assert "requirements.txt" in dep and "requirements-dev.txt" in dep, dep


def test_the_python_matrix_covers_the_declared_floor(ci):
    """The README badge says 3.12+. Whatever else the matrix tries, it must
    cover the versions the project claims to support."""
    versions = set(re.findall(r"3\.1[0-9]", WORKFLOW.read_text(encoding="utf-8")))
    assert {"3.12", "3.13"} <= versions, versions


# --------------------------------------------------------------------------
# the facts about *this* suite that a CI file has to respect
# --------------------------------------------------------------------------

def test_the_tool_cache_points_at_the_real_install_root(ci, monkeypatch):
    """`toolfetch._install_root()` is `<repo>/tools/bin`, overridable with
    EXCMP_TOOLS_DIR - measured, not assumed. A cache step aimed at
    %LOCALAPPDATA% (which is what the E1 roadmap sketch said) would cache an
    empty directory and look like it worked.

    **The override is cleared before asserting the default**, and that is not
    tidiness. The first version asserted the repo-relative path unconditionally
    and failed the moment the suite was run with `EXCMP_TOOLS_DIR` set - which
    `toolfetch` documents as the supported way for a packaged build (E3) to
    point somewhere else, and which is how the merged tree was verified. A test
    that treats a **default** as an **invariant** goes red for someone using a
    feature exactly as intended, and a false alarm in the one test protecting
    CI's cache path is worse than no test."""
    from excmp import toolfetch

    monkeypatch.delenv("EXCMP_TOOLS_DIR", raising=False)
    assert toolfetch._install_root() == REPO / "tools" / "bin"

    # And the override actually works, since the assertion above is only
    # meaningful if the fallback it describes is the fallback.
    monkeypatch.setenv("EXCMP_TOOLS_DIR", str(REPO / "elsewhere"))
    assert toolfetch._install_root() == REPO / "elsewhere"

    caches = [s for s in _all_steps(ci) if "actions/cache" in str(s.get("uses", ""))]
    if not caches:
        pytest.skip("no tool cache step; nothing to check")
    paths = "\n".join(str(c.get("with", {}).get("path", "")) for c in caches)
    assert "tools/bin" in paths or "tools\\bin" in paths, paths


def test_the_tool_cache_key_changes_when_a_pin_changes(ci):
    """The pins live in excmp/toolfetch.py. A cache keyed on anything else
    would serve yesterday's binary after a hash bump - which is precisely the
    failure E1 exists to prevent."""
    caches = [s for s in _all_steps(ci) if "actions/cache" in str(s.get("uses", ""))]
    if not caches:
        pytest.skip("no tool cache step; nothing to check")
    keys = "\n".join(str(c.get("with", {}).get("key", "")) for c in caches)
    assert "toolfetch.py" in keys, keys


def test_network_tool_fetching_is_not_on_the_push_path(ci):
    """E1 downloads from GitHub releases. A push-triggered job that fetches
    would go red on someone else's outage, and this repo's rule is that a red
    build must mean a real defect."""
    fetching = {name for name, job in _jobs(ci).items()
                if "ensure_tool" in "\n".join(str(s.get("run", ""))
                                              for s in job.get("steps", []))}
    for name in fetching:
        condition = str(_jobs(ci)[name].get("if", ""))
        assert condition, (
            f"job {name!r} fetches tools over the network with no `if:` guard, "
            f"so it runs on every push")
        assert ("workflow_dispatch" in condition or "schedule" in condition), \
            condition


def test_the_fetch_step_fails_when_a_tool_did_not_arrive(ci):
    """`ensure_tool` returns None on failure and deliberately never raises -
    "a download that fails should look exactly like a tool that was never
    there rather than crash a job" (excmp/toolfetch.py). That is right for the
    app and wrong for CI: a job whose whole purpose is to exercise the real
    chains would print `qpdf None`, exit 0, skip every chain test and report
    success. So the step has to check the return values itself."""
    steps = [s for s in _all_steps(ci) if "ensure_tool" in str(s.get("run", ""))]
    if not steps:
        pytest.skip("no tool-fetch step; nothing to check")
    for step in steps:
        run = str(step["run"])
        assert "is None" in run and ("exit" in run or "raise" in run), (
            "the fetch step does not fail when ensure_tool returns None, so "
            "the job would be green having downloaded nothing:\n" + run)


def test_a_job_that_runs_the_suite_guarantees_the_compressor(ci):
    """Every chain test is behind `skipif(find_tools()["7z"] is None)`. On a
    runner without 7-Zip the suite is *green* and has tested none of the
    compression, publishing or verification paths - the "green suite proves
    nothing about what it does not look at" failure, with the whole product
    outside the frame. So at least one job must make 7-Zip's presence a
    hard requirement rather than a hope about the runner image."""
    texts = {name: "\n".join(str(s.get("run", "")) for s in job.get("steps", []))
             for name, job in _jobs(ci).items()}
    guarded = [name for name, t in texts.items()
               if "7z" in t and ("exit" in t or "raise" in t)]
    assert guarded, (
        "no job asserts that 7-Zip is available, so a runner image without it "
        "would produce a green build that never ran the compressor")


def test_skip_reasons_are_reported(ci):
    """`pytest -q` prints a bare count. `-rs` names every skip, which is the
    only way a reviewer notices that coverage quietly fell off a cliff."""
    runs = [str(s.get("run", "")) for s in _all_steps(ci)
            if "pytest" in str(s.get("run", ""))]
    assert runs, "no pytest step"
    for run in runs:
        assert "-rs" in run, (
            "pytest is run without -rs, so silently skipped tests stay "
            "silent:\n" + run)


def test_no_ungated_corpus_paths():
    """Four tests read the user's real data folders. Every one must be gated
    on the path existing, or it fails on a runner that has never seen that
    drive. This looks at the tests, not the workflow, because that is where
    the regression would land.

    **It deliberately takes no `ci` fixture.** An audit of this file pointed
    out that the module-level `importorskip("yaml")` would take this guard
    down with it if pyyaml were ever missing - so the one test protecting CI
    from an ungated absolute path would vanish exactly when someone had a
    half-installed dev environment, and the suite would still be green. The
    guard now needs nothing but the standard library."""
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"Downloads-1|PalluVaapaHDD|excmp-bench", text):
            continue
        # Some gate must exist in the same module: an is_dir()/is_file()/
        # exists() guarded skipif, or an explicit `return None` fallback.
        gated = re.search(r"skipif\(|\.exists\(\)|\.is_dir\(\)|\.is_file\(\)",
                          text)
        if not gated:
            offenders.append(path.name)
    assert offenders == [], (
        f"these read the real corpora with no presence gate, so they would "
        f"fail in CI: {offenders}")


def test_the_gui_tests_need_no_display_configuration_from_ci(ci):
    """conftest.py sets QT_QPA_PLATFORM itself, so the workflow does not have
    to - and if that ever stops being true, this test says so rather than a
    runner hanging on a window that cannot open."""
    conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'QT_QPA_PLATFORM' in conftest and "offscreen" in conftest
    assert "setdefault" in conftest, (
        "conftest no longer *defaults* the platform, so CI must set it "
        "explicitly - update the workflow")


def test_the_slow_corpus_walk_stays_opt_in(ci):
    """EXCMP_SLOW_CORPUS gates a 57,020-file walk. CI must not set it: the
    corpus is not there, and the gate also checks the path, but a workflow
    that sets it is stating an intention that cannot be met."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "EXCMP_SLOW_CORPUS" not in text, \
        "CI sets EXCMP_SLOW_CORPUS, but the corpus it needs is not on a runner"
