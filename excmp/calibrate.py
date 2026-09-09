"""J7 — learn this machine's real speed instead of trusting a constant.

The shipped rates in :mod:`excmp.estimate` were measured once, and the two
corpora they were measured against **disagreed by 2.5× on 7-Zip's throughput
alone** — purely because one lived on an external HDD
(benchmarks/2026-08-01-estimator-backtest.md). No single constant is right for
both, which means the constant should stop being the final answer. Every
finished job already knows exactly how many bytes it piped and how long that
took; this records that and blends it back in.

Four decisions, each of them about not making the estimate *worse*:

**Keyed on the resolved chain, not the profile.** A degraded Extreme runs the
same stages as Normal and should share their calibration; two profiles that
resolve to different chains should not pollute each other. This is the same
key :meth:`excmp.estimate.Rates.chain_key` already uses.

**The shipped defaults are the cold-start prior.** Blending is an exponential
moving average, so one strange job nudges the number instead of replacing it,
and a fresh install still has a real answer on its first estimate.

**Absurd and tiny samples are dropped.** A 3 KB job measures process startup
rather than throughput, and a rate a thousand times the prior is a clock
artefact or a fully cached read. Learning either would poison every later
estimate for that chain, which is worse than not learning at all.

**Qt-free, like the rest of ``excmp/``.** A plain JSON file rather than
QSettings, so the CLI and the GUI feed the same store and the engine keeps its
independence from Qt.

Calibration is an optimisation, never a dependency: a missing, corrupt or
unwritable store costs the learned rates and nothing else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .atomic import PublishError, atomic_write_text
from .estimate import Rates

#: Where the store lives when nobody says otherwise. Beside the temp dir the
#: app already uses, so a user who clears ``~/.excmp`` clears this too.
DEFAULT_PATH = Path.home() / ".excmp" / "calibration.json"

#: Below this a job is measuring process startup, not throughput.
MIN_SAMPLE_BYTES = 8 << 20

#: How far a single observation may sit from the prior before it is treated as
#: an artefact rather than a measurement. Generous, because a genuinely slow
#: external drive is exactly the case this feature exists for; a 100x gap is
#: not that.
MAX_RATE_MULTIPLE = 100.0

#: EMA weight for each new observation. Slow enough that one odd job barely
#: moves the number, fast enough that ~25 consistent jobs get most of the way
#: there - which the tests assert directly rather than leaving to taste.
ALPHA = 0.25


@dataclass
class ChainCalibration:
    """What we have learned about one resolved chain."""

    #: **Bytes** per second of piped input, matching `estimate._CODEC_RATE`.
    #: Not MiB/s: the shipped rates are byte rates (3.38e6 for 7-Zip), and
    #: mixing the two units made every observation look 2^20 times too slow
    #: and fall outside the sanity window.
    rate: float
    samples: int = 0
    #: Achieved output/input ratio, or None if never observed. This is the
    #: J1-note-3 blind spot: no cheap probe can predict what Precomp will
    #: find, so watching what it actually achieved is the only real fix.
    factor: float | None = None


@dataclass
class Calibration:
    chains: dict[str, ChainCalibration] = field(default_factory=dict)


def _coerce(value: object) -> float | None:
    """A number from the store, or None. The file is user-editable and may
    have been hand-mangled, so nothing here trusts its types."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def load(path: Path | None = None) -> Calibration:
    """Read the store. A missing or damaged one is simply empty."""
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Calibration()
    if not isinstance(raw, dict):
        return Calibration()

    chains: dict[str, ChainCalibration] = {}
    for key, entry in (raw.get("chains") or {}).items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        rate = _coerce(entry.get("rate"))
        if rate is None or rate <= 0:
            continue
        samples = _coerce(entry.get("samples")) or 0
        factor = _coerce(entry.get("factor"))
        if factor is not None and not (0 < factor <= 1.5):
            factor = None
        chains[key] = ChainCalibration(rate=rate, samples=int(samples),
                                       factor=factor)
    return Calibration(chains=chains)


def _save(cal: Calibration, target: Path) -> None:
    payload = {"chains": {
        key: {"rate": round(entry.rate, 6), "samples": entry.samples,
              **({"factor": round(entry.factor, 6)}
                 if entry.factor is not None else {})}
        for key, entry in cal.chains.items()}}
    # D8: flushed and read back, and the previous store survives a failed
    # write. This file is the only record of how fast each chain actually runs
    # on this machine; half of it is worse than none, because a truncated
    # rate silently poisons every future estimate.
    atomic_write_text(target, json.dumps(payload, indent=2))


def record(stages: Sequence[str], piped_bytes: int, elapsed_s: float,
           achieved_factor: float | None = None,
           path: Path | None = None) -> None:
    """Fold one finished job into the store.

    Never raises. This runs *after* a job has succeeded, and failing to learn
    from it is not a reason to turn a completed job into a failed one.
    """
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        key = Rates.chain_key(stages)
        if not key or piped_bytes < MIN_SAMPLE_BYTES or elapsed_s <= 0:
            return
        observed = piped_bytes / elapsed_s      # bytes/s, as shipped
        if observed <= 0:
            return

        cal = load(target)
        prior = cal.chains.get(key)
        baseline = prior.rate if prior is not None else Rates().rate_for(stages)
        if not (baseline / MAX_RATE_MULTIPLE <= observed
                <= baseline * MAX_RATE_MULTIPLE):
            # A clock artefact or a fully cached read, not this machine's
            # throughput. Dropped rather than blended: one poisoned sample
            # outlives many good ones under an EMA.
            return

        # Blended from the very first sample, because the shipped default *is*
        # the prior - that is what "cold-start prior" means. Replacing it
        # outright on sample one would throw away everything the defaults
        # encode on the strength of a single job, which is exactly the
        # behaviour the EMA exists to avoid.
        rate = baseline * (1 - ALPHA) + observed * ALPHA

        factor = prior.factor if prior is not None else None
        if achieved_factor is not None and 0 < achieved_factor <= 1.5:
            # Same rule for the ratio: the shipped factor is the prior.
            factor_prior = (factor if factor is not None
                            else Rates().factor_for(stages))
            factor = factor_prior * (1 - ALPHA) + achieved_factor * ALPHA

        cal.chains[key] = ChainCalibration(
            rate=rate,
            samples=(prior.samples + 1) if prior is not None else 1,
            factor=factor)
        _save(cal, target)
    except (OSError, ValueError, TypeError, PublishError):
        # PublishError is a RuntimeError, so it is named explicitly: D8's
        # read-back added a new way for the write to fail, and this function
        # promises never to raise. A finished job must not be reported as a
        # failure because the store it was about to learn from would not
        # write.
        return


def blended_rates(base: Rates | None = None,
                  path: Path | None = None) -> Rates:
    """The shipped rates with whatever this machine has taught us folded in.

    Chains with no history keep their shipped values exactly, so learning
    about one chain never disturbs another.
    """
    base = base or Rates()
    cal = load(path)
    if not cal.chains:
        return base

    codec = dict(base.codec)
    factor = dict(base.codec_factor)
    for key, entry in cal.chains.items():
        codec[key] = entry.rate
        if entry.factor is not None:
            factor[key] = entry.factor
    return Rates(io_rate=base.io_rate, codec=codec, codec_factor=factor,
                 rate_spread=base.rate_spread, verify=base.verify)
