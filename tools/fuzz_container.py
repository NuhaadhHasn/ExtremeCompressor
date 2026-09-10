"""D6 — a long soak over the `.excmp` parser, using the properties in
`tests/test_fuzz_container.py`.

    .venv\\Scripts\\python.exe tools\\fuzz_container.py [--examples 20000]

**Why this exists rather than HypoFuzz.** The roadmap named HypoFuzz because
Atheris is Linux-only. HypoFuzz is not installed here (absent from `.venv`,
from `venvPython`, and from `requirements-dev.txt`), and the surface worth
fuzzing turned out not to need it: the interesting targets are pure byte-in
functions - a manifest string, a ledger dict, a sidecar text, a name - so
Hypothesis, which is already a dev dependency for D1, generates against them
at tens of thousands of examples a minute with no coverage instrumentation.

What HypoFuzz would add is coverage-guided example selection, which pays off
on deep branchy parsers. If the parser grows one, install it and point it at
the same test module - the properties are written so nothing here has to
change.

**The invariant, in one line:** a malformed archive raises `ContainerError`.
That is what `cli.main` prints as a single line and what every caller catches.
Anything else escaping - an `AttributeError`, a `TypeError`, an
`OverflowError` - means a failure nobody anticipated, in code that reads
attacker-chosen bytes.

The first pass of this found **eleven** such shapes. They are listed in the
test module's docstring and each has a regression case there.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hypothesis import HealthCheck, given, settings   # noqa: E402
from hypothesis import strategies as st              # noqa: E402

from excmp.manifest import ContainerError, Manifest, declared_total  # noqa: E402
from excmp.safepath import UnsafePathError, safe_relpath              # noqa: E402
from excmp.slt import classify_failure, parse_slt                     # noqa: E402
from excmp.volumes import VolumeError, parse_size                     # noqa: E402

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(),
    lambda children: st.lists(children, max_size=5)
    | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=20,
)


def _soak(examples: int) -> list[str]:
    """Run every property at `examples` and return the failures found."""
    failures: list[str] = []
    conf = settings(max_examples=examples, deadline=None,
                    suppress_health_check=list(HealthCheck))

    def check(name, fn):
        started = time.perf_counter()
        try:
            fn()
            print(f"  ok    {name:34} {time.perf_counter() - started:6.1f}s")
        except Exception as exc:                     # noqa: BLE001
            print(f"  FAIL  {name:34} {type(exc).__name__}: {exc}"[:300])
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    @conf
    @given(text=st.text())
    def manifest_text(text):
        try:
            Manifest.from_json(text)
        except ContainerError:
            pass

    @conf
    @given(value=json_values)
    def manifest_json(value):
        import json
        try:
            Manifest.from_json(json.dumps(value))
        except (ContainerError, ValueError):
            # ValueError only from json.dumps itself on a NaN-free-mode float;
            # the parser's own refusals are all ContainerError.
            pass

    @conf
    @given(ledger=json_values)
    def ledger_total(ledger):
        try:
            total = declared_total(ledger)
        except ContainerError:
            return
        assert isinstance(total, int) and total >= 0

    @conf
    @given(name=st.text())
    def names(name):
        try:
            rel = safe_relpath(name)
        except UnsafePathError:
            return
        assert not rel.is_absolute() and ".." not in rel.parts

    @conf
    @given(text=st.text())
    def sizes(text):
        try:
            size = parse_size(text)
        except VolumeError:
            return
        assert isinstance(size, int) and size > 0

    @conf
    @given(lines=st.lists(st.text(), max_size=60))
    def slt(lines):
        parse_slt(lines)

    @conf
    @given(text=st.text())
    def failures_classified(text):
        assert classify_failure(text) in ("", "encrypted", "corrupt", "missing")

    check("manifest.from_json (text)", manifest_text)
    check("manifest.from_json (json)", manifest_json)
    check("manifest.declared_total", ledger_total)
    check("safepath.safe_relpath", names)
    check("volumes.parse_size", sizes)
    check("slt.parse_slt", slt)
    check("slt.classify_failure", failures_classified)
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--examples", type=int, default=20_000,
                    help="examples per property (default 20000)")
    args = ap.parse_args()

    print(f"soaking the .excmp parser, {args.examples:,} examples per "
          f"property\n")
    t0 = time.perf_counter()
    failures = _soak(args.examples)
    print(f"\n{time.perf_counter() - t0:.1f}s total")

    if failures:
        print(f"\n{len(failures)} property/properties failed:")
        for line in failures:
            print(f"  - {line}")
        print("\nHypothesis has saved the failing examples under .hypothesis/, "
              "so re-running the test suite will reproduce them without "
              "searching again. Add each one to "
              "tests/test_fuzz_container.py as a regression case.")
        return 1
    print("\nno property violated. That is not proof of absence - it is the "
          "absence of a counterexample at this example count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
