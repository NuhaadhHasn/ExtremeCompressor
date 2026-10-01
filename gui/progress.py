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

I11 gave the D9 self-test a band of its own. At ``-m58`` the pre-publish
restore is ~40% of an Insane job (1,556 s of 3,810 on Silesia), and zpaqfranz
prints nothing while it runs, so a bar that kept its peak sat at 95% for 26
minutes. When the job carries an estimate, the self-test gets its estimated
share of the bar and moves through it by *elapsed time against that
estimate*: never all the way, because time is not a measurement of the
restore, and never with a made-up remaining time once the estimate is spent.
"""

from __future__ import annotations

# Relative cost of each stage. Rough by nature - they only have to be right
# about each other's *order of magnitude*.
STAGE_WEIGHTS: dict[str, float] = {
    "tar": 5.0,
    "precomp": 35.0,
    "srep": 20.0,
    "sevenzip": 40.0,
    # B17: -m58 context mixing is 90-93% of an Insane job's compress time on
    # every corpus measured (vs Precomp: 1,264 s to 141 s on the deflate zip,
    # ~360 s to 9 s on the installer sample, ~2,050 s to 3 s on Silesia). At
    # the old 50 the bar crossed half way while zpaqfranz had barely started.
    "zpaqfranz": 400.0,
    "zstd": 100.0,   # the whole fast profile is this one stage
}
DEFAULT_WEIGHT = 25.0

# Mirrors engine._TREE_CAPABLE. Duplicated rather than imported so the GUI
# doesn't drag the engine in just to draw a bar; test_gui_progress.py asserts
# the two stay identical.
TREE_CAPABLE = {"sevenzip", "zstd"}

PIPELINE_CEILING = 95.0

#: The id the engine reports the D9 self-test under (``engine._verify_before_publish``).
VERIFY_STAGE = "verify"
#: What the job shows while it runs, and once it has outlasted its estimate.
VERIFYING = "verifying"
VERIFYING_LATE = "verifying, past estimate"
#: How far elapsed time alone may carry the bar through the self-test's band.
#: The rest is closed only by the engine saying the restore matched.
VERIFY_TIME_CAP = 0.9


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

    def __init__(self, chain: list[str], ceiling: float = PIPELINE_CEILING,
                 compress_s: float | None = None,
                 verify_s: float | None = None) -> None:
        self.chain: list[str] = list(chain) or ["zstd"]
        self.ceiling = ceiling
        self._weights = [STAGE_WEIGHTS.get(s, DEFAULT_WEIGHT) for s in self.chain]
        self._index = 0
        self._peak = 0.0
        # Without both halves of an estimate the self-test has no share to
        # move through, and the bar keeps its pre-I11 behaviour: the chain
        # fills to the ceiling and the self-test waits there.
        if compress_s and verify_s and compress_s > 0 and verify_s > 0:
            self.verify_s: float | None = float(verify_s)
            self._chain_top = ceiling * compress_s / (compress_s + verify_s)
        else:
            self.verify_s = None
            self._chain_top = ceiling

    @property
    def stage_count(self) -> int:
        return len(self.chain)

    def update(self, stage_id: str, pct: float) -> float:
        """Feed one ``progress_cb`` call; get the overall percentage back."""
        if stage_id == VERIFY_STAGE:
            # Not a stage of the chain: appending it would rescale every
            # weight. The self-test is timed through `verify()` instead.
            return self._peak
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
        overall = (done + within) / total * self._chain_top
        self._peak = max(self._peak, overall)
        return self._peak

    def verify(self, elapsed_s: float) -> float:
        """The bar ``elapsed_s`` into the self-test.

        Reaching the self-test means every stage of the chain finished, so
        the chain's band is banked whatever its last report said.
        """
        self._peak = max(self._peak, self._chain_top)
        if self.verify_s is not None:
            fraction = min(max(0.0, elapsed_s) / self.verify_s, VERIFY_TIME_CAP)
            band = self.ceiling - self._chain_top
            self._peak = max(self._peak, self._chain_top + band * fraction)
        return self._peak

    def verify_done(self) -> float:
        """The engine says the restore matched: the self-test's band is full."""
        self._peak = max(self._peak, self.ceiling)
        return self._peak

    def verify_remaining(self, elapsed_s: float) -> float | None:
        """Seconds left by the estimate, or ``None`` once it is spent."""
        if self.verify_s is None:
            return None
        left = self.verify_s - elapsed_s
        return left if left > 0 else None

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
