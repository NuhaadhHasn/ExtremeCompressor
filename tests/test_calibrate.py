"""J7 — the estimator learns this machine instead of a benchmark laptop's.

The shipped rates were measured on one machine against two corpora, and those
two corpora **disagreed by 2.5× on 7-Zip's throughput alone** — purely because
one lived on an external HDD (benchmarks/2026-08-01). No constant can be right
for both, so the constant should stop being the answer: every finished job
already knows exactly how many bytes it piped and how long that took.

The design constraints are all about not making the estimate *worse*:

- **Keyed on the resolved chain, not the profile.** A degraded Extreme and a
  Fast run the same stages and should share calibration; two profiles that
  resolve differently should not.
- **The shipped defaults are the cold-start prior**, blended by an exponential
  moving average. One weird job must not throw the estimate away, and a fresh
  install must not have no answer at all.
- **Absurd and tiny samples are dropped.** A 3 KB job measures process startup,
  not throughput, and a rate a thousand times the prior is a clock artefact or
  a cached read - learning either would poison the number for every later job.
- **Qt-free.** `excmp/` never imports Qt, so this is a plain JSON file rather
  than QSettings, and both the CLI and the GUI feed the same store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from excmp.calibrate import (MIN_SAMPLE_BYTES, Calibration, blended_rates,
                             load, record)
from excmp.estimate import Rates


@pytest.fixture
def store(tmp_path) -> Path:
    return tmp_path / "calibration.json"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_a_finished_job_is_remembered(store):
    record(["precomp", "sevenzip"], piped_bytes=200 << 20, elapsed_s=100.0,
           path=store)
    cal = load(store)
    assert "precomp+sevenzip" in cal.chains


def test_the_key_ignores_the_tar_stage(store):
    """The engine prepends `tar` for multi-stage chains; it is pure I/O and
    carries no codec calibration, exactly as `Rates.chain_key` already says."""
    record(["tar", "precomp", "sevenzip"], piped_bytes=200 << 20,
           elapsed_s=100.0, path=store)
    assert "precomp+sevenzip" in load(store).chains


def test_two_profiles_that_resolve_alike_share_calibration(store):
    """A degraded Extreme runs the same stages as Normal. Keying on the
    profile name would keep two half-learned numbers where one belongs."""
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=25.0, path=store)
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=25.0, path=store)
    cal = load(store)
    assert list(cal.chains) == ["sevenzip"]
    assert cal.chains["sevenzip"].samples == 2


def test_a_tiny_job_is_not_learned_from(store):
    """A 3 KB job measures process startup, not throughput."""
    record(["sevenzip"], piped_bytes=MIN_SAMPLE_BYTES - 1, elapsed_s=0.5,
           path=store)
    assert not load(store).chains


def test_a_zero_or_negative_duration_is_dropped(store):
    for bad in (0.0, -1.0):
        record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=bad, path=store)
    assert not load(store).chains


def test_an_absurd_rate_is_dropped(store):
    """1000x the prior is a clock artefact or a fully cached read, and
    learning it would poison every later estimate for that chain."""
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=0.0001, path=store)
    assert not load(store).chains


# ---------------------------------------------------------------------------
# Blending
# ---------------------------------------------------------------------------

def test_with_no_history_the_shipped_defaults_are_used(store):
    shipped = Rates()
    learned = blended_rates(path=store)
    assert learned.rate_for(["sevenzip"]) == shipped.rate_for(["sevenzip"])


def test_one_observation_moves_the_rate_towards_it(store):
    shipped = Rates()
    before = shipped.rate_for(["sevenzip"])
    # Deliberately much slower than the prior - an external drive, say.
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=200.0, path=store)
    after = blended_rates(path=store).rate_for(["sevenzip"])
    assert after < before, f"{after} did not move below {before}"


def test_it_does_not_jump_all_the_way_on_one_sample(store):
    """An EMA, not a replacement. One odd job must not throw away everything
    the defaults encode."""
    shipped_rate = Rates().rate_for(["sevenzip"])
    observed = (100 << 20) / 200.0        # bytes/s, matching the shipped units
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=200.0, path=store)
    after = blended_rates(path=store).rate_for(["sevenzip"])
    assert min(shipped_rate, observed) < after < max(shipped_rate, observed)


def test_repeated_agreement_converges_on_the_truth(store):
    """The property that makes this worth having: a machine that is
    consistently slower ends up with a rate that says so."""
    observed_rate = (50 << 20) / 100.0        # bytes/s
    for _ in range(25):
        record(["sevenzip"], piped_bytes=50 << 20, elapsed_s=100.0, path=store)
    after = blended_rates(path=store).rate_for(["sevenzip"])
    assert abs(after - observed_rate) / observed_rate < 0.15, (
        f"{after} never converged on {observed_rate}")


def test_learning_one_chain_leaves_the_others_alone(store):
    shipped = Rates()
    record(["zstd"], piped_bytes=100 << 20, elapsed_s=200.0, path=store)
    learned = blended_rates(path=store)
    assert learned.rate_for(["sevenzip"]) == shipped.rate_for(["sevenzip"])
    assert learned.rate_for(["zstd"]) != shipped.rate_for(["zstd"])


# ---------------------------------------------------------------------------
# The ratio, which is the part no probe can predict
# ---------------------------------------------------------------------------

def test_the_achieved_ratio_is_learned_too(store):
    """J1 note 3: sampling cannot predict what Precomp will find, and no cheap
    probe can. Watching what it actually achieved is the only real fix."""
    shipped = Rates().factor_for(["precomp", "sevenzip"])
    for _ in range(25):
        record(["precomp", "sevenzip"], piped_bytes=100 << 20, elapsed_s=50.0,
               achieved_factor=0.20, path=store)
    after = blended_rates(path=store).factor_for(["precomp", "sevenzip"])
    assert after != shipped
    assert abs(after - 0.20) < 0.08, f"{after} never approached 0.20"


def test_a_nonsense_factor_is_ignored(store):
    """A factor is output/input. Above 1 means it grew, below 0 is impossible;
    neither is a compression ratio worth learning."""
    for bad in (-0.5, 0.0, 1.9, 50.0):
        record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=50.0,
               achieved_factor=bad, path=store)
    cal = load(store)
    entry = cal.chains.get("sevenzip")
    assert entry is None or entry.factor is None


# ---------------------------------------------------------------------------
# The store itself
# ---------------------------------------------------------------------------

def test_a_missing_store_is_empty_not_an_error(tmp_path):
    assert load(tmp_path / "nope.json").chains == {}


def test_a_corrupt_store_is_ignored_rather_than_fatal(store):
    """Calibration is an optimisation. A damaged file must cost the user their
    learned rates, never their ability to compress anything."""
    store.write_text("{ this is not json", encoding="utf-8")
    assert load(store).chains == {}
    assert blended_rates(path=store).rate_for(["sevenzip"]) == \
        Rates().rate_for(["sevenzip"])


def test_a_store_with_hostile_values_is_ignored(store):
    store.write_text(json.dumps(
        {"chains": {"sevenzip": {"rate": "fast", "samples": "many"}}}),
        encoding="utf-8")
    assert blended_rates(path=store).rate_for(["sevenzip"]) == \
        Rates().rate_for(["sevenzip"])


def test_recording_survives_an_unwritable_location(tmp_path):
    """Failing to learn is not a reason to fail a job that already finished."""
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=50.0,
           path=tmp_path / "no-such-dir" / "deep" / "c.json")
    # No exception is the assertion.


def test_the_store_is_human_readable(store):
    record(["sevenzip"], piped_bytes=100 << 20, elapsed_s=50.0, path=store)
    data = json.loads(store.read_text(encoding="utf-8"))
    assert "chains" in data and "sevenzip" in data["chains"]
    assert "rate" in data["chains"]["sevenzip"]
