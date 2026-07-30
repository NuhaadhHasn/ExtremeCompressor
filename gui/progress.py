"""Turning per-stage progress into one honest job percentage.

The engine only ever says "sevenzip is 40% done" - it has no concept of a
job being four stages long. This module owns that arithmetic, because the
GUI is the only party that knows the whole chain up front (it asked the
planner before starting).

Two deliberate choices:

* stages are weighted by *nominal cost*, not counted equally - 7-Zip LZMA2
  dwarfs the tar that feeds it, and a chain that jumped 0->25%->50% at stage
  boundaries would feel broken;
* the pipeline tops out at 95%. The remaining 5% is the container write,
  the self-test and the atomic publish, which report nothing but are not
  instant. Hitting 100% and then sitting there is the classic progress-bar
  lie; we simply don't claim 100 until the job is genuinely finished.
"""

from __future__ import annotations

# Relative cost of each stage. Rough by nature - they only have to be right
# about each other's *order of magnitude*.
STAGE_WEIGHTS: dict[str, float] = {
    "tar": 5.0,
    "precomp": 35.0,
    "srep": 20.0,
    "sevenzip": 40.0,
    "zstd": 100.0,   # the whole fast profile is this one stage
}
DEFAULT_WEIGHT = 25.0

# Mirrors engine._TREE_CAPABLE. Duplicated rather than imported so the GUI
# doesn't drag the engine in just to draw a bar; test_gui_progress.py asserts
# the two stay identical.
TREE_CAPABLE = {"sevenzip", "zstd"}

PIPELINE_CEILING = 95.0


def expected_chain(stages: list[str]) -> list[str]:
    """The chain the engine will actually run, given a plan's stage list.

    Reproduces ``engine.compress``'s rule: anything that is not a single
    tree-capable stage gets a leading ``tar`` so the byte-oriented stages
    receive one file.
    """
    if not stages:
        return []
    chain = list(stages)
    if len(chain) > 1 or chain[0] not in TREE_CAPABLE:
        chain = ["tar", *[s for s in chain if s != "tar"]]
    return chain


class ChainProgress:
    """Maps ``(stage_id, stage_pct)`` onto a monotonic 0-100 job percentage."""

    def __init__(self, chain: list[str], ceiling: float = PIPELINE_CEILING) -> None:
        self.chain: list[str] = list(chain) or ["zstd"]
        self.ceiling = ceiling
        self._weights = [STAGE_WEIGHTS.get(s, DEFAULT_WEIGHT) for s in self.chain]
        self._index = 0
        self._peak = 0.0

    @property
    def stage_count(self) -> int:
        return len(self.chain)

    def update(self, stage_id: str, pct: float) -> float:
        """Feed one ``progress_cb`` call; get the overall percentage back."""
        if stage_id not in self.chain:
            # The plan and reality disagreed (a stage was added, or a profile
            # degraded differently). Take reality's word for it.
            self.chain.append(stage_id)
            self._weights.append(STAGE_WEIGHTS.get(stage_id, DEFAULT_WEIGHT))

        index = self.chain.index(stage_id)
        if index < self._index:
            return self._peak  # a late report from a stage we already left
        # Jumping forward means the stages in between were skipped
        # (StageSkip) - their weight is simply banked as complete.
        self._index = index

        total = sum(self._weights) or 1.0
        done = sum(self._weights[:index])
        within = self._weights[index] * max(0.0, min(100.0, pct)) / 100.0
        overall = (done + within) / total * self.ceiling
        self._peak = max(self._peak, overall)
        return self._peak

    def finish(self) -> float:
        self._peak = 100.0
        return self._peak

    @property
    def value(self) -> float:
        return self._peak


class EtaEstimator:
    """Remaining-time estimate from elapsed time and fraction complete.

    Smoothed with an EMA because stage transitions make the raw estimate
    lurch, and returns ``None`` until there is enough signal to be worth
    showing at all.
    """

    def __init__(self, alpha: float = 0.25, warmup_s: float = 6.0,
                 min_fraction: float = 0.03) -> None:
        self.alpha = alpha
        self.warmup_s = warmup_s
        self.min_fraction = min_fraction
        self._ema: float | None = None

    def update(self, fraction: float, elapsed_s: float) -> float | None:
        if fraction <= self.min_fraction or elapsed_s < self.warmup_s:
            return None
        if fraction >= 1.0:
            return 0.0
        raw = elapsed_s * (1.0 - fraction) / fraction
        self._ema = raw if self._ema is None else self.alpha * raw + (1 - self.alpha) * self._ema
        return self._ema

    def reset(self) -> None:
        self._ema = None
