"""D6: fuzzing the `.excmp` parser — and what it found on the first pass.

D0 hardened the parser *by hand* against the attacks somebody thought of:
traversal, absolute paths, reserved names, symlink members, bombs. Nothing had
ever generated input at it. The difference showed up immediately.

**HypoFuzz is not installed** (checked: absent from both `.venv` and
`venvPython`, and absent from `requirements-dev.txt`), and it is not needed to
get the value here. Hypothesis is already a dev dependency for D1's property
tests, and the interesting surface is *pure byte-in* — a manifest string, a
ledger dict, a sidecar text — so a few hundred examples per property run in
seconds. `tools/fuzz_container.py` is the same properties with the example
count turned up for a long soak.

**The invariant these tests state**, and it is the one this codebase already
lives by everywhere else: *a malformed archive raises `ContainerError`.* That
is what `cli.main` turns into a one-line error and what every caller catches.
An `AttributeError` or a `TypeError` escaping the parser means the failure was
never anticipated, and "unanticipated" in a parser that reads attacker-chosen
bytes is the whole reason D6 exists.

**Eleven unhandled exception shapes were reproduced before this file was
written**, all from crafted input, all on the path taken by `excmp list` on
any file a user points at:

    declared_total({"a": "not a dict"})       -> AttributeError
    declared_total({"a": {"size": "abc"}})    -> ValueError
    declared_total({"a": {"size": [1, 2]}})   -> TypeError
    declared_total({"a": {"size": None}})     -> TypeError
    declared_total({"a": {"size": nan}})      -> ValueError
    declared_total(["a"])                     -> AttributeError
    Manifest.from_json('[1,2,3]')             -> AttributeError
    parse_size("1e400m")                      -> OverflowError

`declared_total` is not a cosmetic corner: its result *is* the payload budget
and the decompression-bomb budget (D0.3). A ledger it cannot read is a ledger
whose bounds cannot be trusted, so the fix refuses the archive rather than
guessing a number.
"""

from __future__ import annotations

import json
import math

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from excmp.manifest import ContainerError, Manifest, declared_total
from excmp.safepath import UnsafePathError, safe_relpath
from excmp.slt import classify_failure, parse_slt
from excmp.verify import VerifyError, verify_restore
from excmp.volumes import VolumeError, parse_size

FAST = settings(max_examples=300, deadline=None,
                suppress_health_check=[HealthCheck.too_slow])

#: Anything json.loads can produce, nested a couple of levels.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False,
                                                          allow_infinity=False)
    | st.text(),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=8), children, max_size=4),
    max_leaves=12,
)


# --------------------------------------------------------------------------
# the ledger, whose numbers become every bound the extractor trusts
# --------------------------------------------------------------------------

@FAST
@given(ledger=json_values)
def test_declared_total_never_raises_an_unexpected_type(ledger):
    """It either returns a non-negative int or refuses the archive."""
    try:
        total = declared_total(ledger)
    except ContainerError:
        return
    assert isinstance(total, int) and total >= 0


@pytest.mark.parametrize("ledger", [
    {"a": "not a dict"},
    {"a": ["not", "a", "dict"]},
    {"a": None},
    {"a": {"size": "abc"}},
    {"a": {"size": [1, 2]}},
    {"a": {"size": None}},
    {"a": {"size": {}}},
    {"a": {"size": True}},
    {"a": {"size": -1}},
    {"a": {"size": float("nan")}},
    {"a": {"size": float("inf")}},
    ["a", "b"],
    "a string",
    42,
    None,
])
def test_every_shape_that_used_to_crash_now_refuses(ledger):
    """The regression list, verbatim from the reproduction run."""
    with pytest.raises(ContainerError):
        declared_total(ledger)


def test_a_well_formed_ledger_still_totals_correctly():
    """The guard must not have changed the answer for real archives."""
    assert declared_total({"a": {"size": 10}, "b": {"size": 32}}) == 42
    assert declared_total({}) == 0
    # A float that is exactly an integer is what json.loads gives for `10.0`,
    # and refusing that would refuse archives nothing is wrong with.
    assert declared_total({"a": {"size": 10.0}}) == 10


def test_a_size_beyond_any_real_disk_is_refused():
    """`10**400` used to sail through and become a budget. There is no volume
    that size, so a ledger claiming one is either corrupt or hostile - and a
    budget derived from it would be no budget at all."""
    with pytest.raises(ContainerError):
        declared_total({"a": {"size": 10 ** 400}})


# --------------------------------------------------------------------------
# the manifest text itself
# --------------------------------------------------------------------------

@FAST
@given(text=st.text(max_size=200))
def test_from_json_only_ever_raises_container_error(text):
    try:
        Manifest.from_json(text)
    except ContainerError:
        pass
    except Exception as exc:                     # noqa: BLE001 - the point
        raise AssertionError(
            f"{type(exc).__name__} escaped the manifest parser: {exc}") from exc


@FAST
@given(value=json_values)
def test_from_json_only_ever_raises_container_error_on_valid_json(value):
    try:
        Manifest.from_json(json.dumps(value))
    except ContainerError:
        pass
    except Exception as exc:                     # noqa: BLE001
        raise AssertionError(
            f"{type(exc).__name__} escaped the manifest parser: {exc}") from exc


@pytest.mark.parametrize("payload", [
    "[1, 2, 3]",
    '"a string"',
    "42",
    "null",
    "true",
    '{"schema": 2, "nope": 1}',
    '{"schema": 2, "inputs": [1, 2]}',
    "",
    "{",
    '{"schema": "two"}',
])
def test_manifest_shapes_that_used_to_escape(payload):
    with pytest.raises(ContainerError):
        Manifest.from_json(payload)


# --------------------------------------------------------------------------
# verify_restore reads the same untrusted ledger
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ledger", [
    {"a.txt": {}},
    {"a.txt": {"size": 1}},
    {"a.txt": {"sha256": "00"}},
    {"a.txt": "not a dict"},
])
def test_the_acceptance_gate_refuses_a_ledger_it_cannot_read(tmp_path, ledger):
    """`meta["size"]` and `meta["sha256"]` were direct subscripts. The gate the
    entire product rests on must not raise KeyError at a hostile archive - it
    must say the archive is not verifiable."""
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises((VerifyError, ContainerError)):
        verify_restore(tmp_path, ledger)


# --------------------------------------------------------------------------
# the size parser, which is user text rather than archive bytes
# --------------------------------------------------------------------------

@FAST
@given(text=st.text(max_size=40))
def test_parse_size_only_ever_raises_volume_error(text):
    try:
        size = parse_size(text)
    except VolumeError:
        return
    assert isinstance(size, int) and size > 0


@pytest.mark.parametrize("text", ["1e400m", "inf m", "nanm", "1e308t",
                                  "9" * 400 + "g", "-inf", "1e999"])
def test_size_strings_that_used_to_raise_overflow(text):
    with pytest.raises(VolumeError):
        parse_size(text)


def test_ordinary_sizes_still_parse():
    assert parse_size("100m") == 100 << 20
    assert parse_size("4g") == 4 << 30
    assert parse_size("512") == 512


# --------------------------------------------------------------------------
# the surfaces the audit found already total - pinned so they stay that way
# --------------------------------------------------------------------------

@FAST
@given(name=st.text(max_size=60))
def test_safe_relpath_is_total(name):
    """Either it refuses, or it returns something provably contained. This is
    the single chokepoint every archive-supplied name passes through."""
    try:
        rel = safe_relpath(name)
    except UnsafePathError:
        return
    assert not rel.is_absolute()
    assert ".." not in rel.parts
    assert all(part not in ("", ".") for part in rel.parts)


@FAST
@given(lines=st.lists(st.text(max_size=40), max_size=30))
def test_the_slt_parser_never_raises(lines):
    """7-Zip's `-slt` output contains filenames chosen by whoever made the
    foreign archive."""
    doc = parse_slt(lines)
    assert isinstance(doc.entries, list)


@FAST
@given(text=st.text(max_size=80))
def test_classify_failure_returns_one_of_four_answers(text):
    assert classify_failure(text) in ("", "encrypted", "corrupt", "missing")


# --------------------------------------------------------------------------
# and the property that a generated ledger cannot move a bound the wrong way
# --------------------------------------------------------------------------

@FAST
@given(sizes=st.lists(st.integers(min_value=0, max_value=1 << 40), max_size=8))
def test_the_declared_total_is_the_sum_it_says_it_is(sizes):
    """The bomb budget is derived from this number, so an off-by-anything here
    is a bound that does not bound."""
    ledger = {f"f{i}": {"size": n} for i, n in enumerate(sizes)}
    assert declared_total(ledger) == sum(sizes)


@FAST
@given(size=st.floats(allow_nan=True, allow_infinity=True))
def test_no_float_reaches_a_budget_as_a_surprise(size):
    """json.loads produces floats. A NaN or an infinity in a size field must
    not become a budget, and must not crash - it must refuse."""
    assume(not (math.isfinite(size) and size >= 0 and size == int(size)
                if math.isfinite(size) else False))
    with pytest.raises(ContainerError):
        declared_total({"a": {"size": size}})
