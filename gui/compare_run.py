"""I6: run every profile on a sample of the input, for real, and report what
each one actually achieved.

Estimates are the honest thing to show before any work has been done, and J1/J8
went to some trouble to make them ranges rather than promises. This is the next
step up: for the price of a few minutes, the profile chooser can stop
predicting and start reporting.

Three decisions shape the whole module.

**They are real queue jobs.** Not a private code path, not a shortcut through
``engine.compress`` with the verification skipped. They go through the same
``QueueManager``, appear in Activity, show progress, cancel the same way, and
are verified before publication like every other archive - because a number
produced by a path the product does not otherwise run is a number about that
path, not about the product.

**One job per resolved chain, not per profile.** With Precomp missing, Extreme
resolves to exactly Normal's stages; measuring both would spend twice the time
to print the same figure twice and invite the reader to believe they were two
independent results.

**Each profile lands the moment it finishes.** Cancelling after two of four
leaves two measured cards and two estimated ones, which is the honest state.
Holding everything back until the end would throw away work the machine has
already done.

What this module does *not* do is decide anything. It measures, and the
measurement never moves the recommendation - see
:func:`gui.suggest.profile_comparison`. A ratio from 56 MB of a 5 GB folder
ranks the profiles; it does not forecast the job.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from excmp.analyzer import FileInfo
from excmp.planner import Profile, resolved_chain
from excmp.sample import DEFAULT_SAMPLE_BYTES, MeasuredRun, Sample, pick_sample
from excmp.tools import ToolInfo

from .models import JobState

#: Every profile, in the order the chooser lists them.
ALL_PROFILES: tuple[Profile, ...] = (Profile.FAST, Profile.NORMAL,
                                     Profile.EXTREME, Profile.INSANE)


class ComparisonRun(QObject):
    """One "compare the presets on this input" operation."""

    #: A profile finished and its measured saving is now in :attr:`results`.
    measured = Signal(object)          # Profile
    #: A profile's job failed. The card keeps its estimate; nothing is invented.
    failed = Signal(object, str)       # Profile, message
    #: No jobs of ours are left, whether they finished or were cancelled.
    finished = Signal()

    def __init__(self, queue, tools: dict[str, ToolInfo | None],
                 infos: list[FileInfo], work_dir: Path,
                 profiles: tuple[Profile, ...] = ALL_PROFILES,
                 cap_bytes: int = DEFAULT_SAMPLE_BYTES,
                 options: object | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.tools = dict(tools or {})
        self.work_dir = Path(work_dir)
        self.options = options
        self.sample: Sample = pick_sample(infos, cap_bytes=cap_bytes)
        self.results: dict[Profile, MeasuredRun] = {}

        # Group the profiles by what they will really run. The first profile
        # of each group is the one that gets a job; the rest read its result.
        self._groups: list[tuple[tuple[str, ...], list[Profile]]] = []
        by_chain: dict[tuple[str, ...], list[Profile]] = {}
        for profile in profiles:
            key = tuple(resolved_chain(profile, self.tools))
            by_chain.setdefault(key, []).append(profile)
        for profile in profiles:
            key = tuple(resolved_chain(profile, self.tools))
            entry = (key, by_chain[key])
            if entry not in self._groups:
                self._groups.append(entry)

        self._owned: dict[str, tuple[Profile, ...]] = {}
        self._started = False
        self._cleaned = False

    # -- the shape of the work, before committing to it --------------------

    @property
    def job_count(self) -> int:
        """How many compressions this will really run. Fewer than the number
        of profiles whenever two of them resolve to the same chain."""
        return len(self._groups)

    def chains(self) -> list[tuple[str, ...]]:
        return [key for key, _profiles in self._groups]

    def is_running(self) -> bool:
        return bool(self._owned)

    # -- running it ---------------------------------------------------------

    def start(self) -> None:
        """Enqueue one job per distinct chain. Idempotent."""
        if self._started or not self.sample.files:
            return
        self._started = True
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.queue.jobDone.connect(self._on_done)
        self.queue.jobFailed.connect(self._on_failed)
        # A cancelled job emits NEITHER of those. QueueManager retires it
        # through `_retire`, which only emits `jobStateChanged`, so a run that
        # listened to done and failed alone would wait forever for a job the
        # queue had already finished with — and every one of these jobs has a
        # visible x in Activity, by design. Closing the window does it too:
        # `closeEvent -> shutdown() -> cancel_all()`.
        self.queue.jobStateChanged.connect(self._on_state)
        inputs = [f.path for f in self.sample.files]
        for key, profiles in self._groups:
            lead = profiles[0]
            out = self.work_dir / f"compare-{lead.value}.excmp"
            job = self.queue.add_compress(inputs, out, lead,
                                          options=self.options,
                                          # Throwaway archives: the number is
                                          # the product and the file is deleted
                                          # below, so this must not become a
                                          # history row pointing at nothing.
                                          extras={"measurement": True})
            self._owned[job.id] = tuple(profiles)

    def cancel(self) -> None:
        """Stop what has not run and keep what has.

        The archives are throwaway either way: their only product is the
        number already recorded in :attr:`results`.
        """
        if not self._owned:
            return                     # nothing in flight; already settled
        for job_id in list(self._owned):
            self.queue.cancel(job_id)
        if not self._owned:
            return                     # the queue settled us on the way round
        self._owned.clear()
        self._cleanup()
        self.finished.emit()

    # -- the queue talking back --------------------------------------------

    def _on_done(self, job_id: str, result: object) -> None:
        profiles = self._owned.pop(job_id, None)
        if profiles is None:
            return                     # somebody else's job
        orig = int(getattr(result, "orig_bytes", 0) or 0)
        final = int(getattr(result, "final_bytes", 0) or 0)
        elapsed = float(getattr(result, "elapsed_s", 0.0) or 0.0)
        archive = getattr(result, "archive", None)
        if orig > 0 and final > 0:
            for profile in profiles:
                self.results[profile] = MeasuredRun(
                    profile=profile, orig_bytes=orig, final_bytes=final,
                    elapsed_s=elapsed, verified=True)
                self.measured.emit(profile)
        else:
            # An archive with no bytes on either side is not a 100% saving,
            # it is a job that did nothing. Report it rather than printing it.
            for profile in profiles:
                self.failed.emit(profile, "the run produced no measurable bytes")
        if archive is not None:
            try:
                Path(archive).unlink(missing_ok=True)
            except OSError:
                pass                   # a leftover in our own temp dir
        self._settle()

    def _on_state(self, job_id: str, state: object) -> None:
        """Only cancellation: done and failed have their own signals, and
        reacting to those here would race them for the result.

        No ``failed`` is emitted. A cancellation is something somebody chose,
        not something that went wrong, and the card keeping its estimate is
        already the right answer — a banner saying "insane could not be
        measured" for each remaining profile would be four apologies for one
        deliberate click.
        """
        if state is not JobState.CANCELLED:
            return
        if self._owned.pop(job_id, None) is None:
            return
        self._settle()

    def _on_failed(self, job_id: str, message: str) -> None:
        profiles = self._owned.pop(job_id, None)
        if profiles is None:
            return
        for profile in profiles:
            self.failed.emit(profile, message)
        self._settle()

    def _settle(self) -> None:
        if not self._owned:
            self._cleanup()
            self.finished.emit()

    def _cleanup(self) -> None:
        # Idempotent: cancelling a queued job makes the real queue emit its
        # state change synchronously, so `cancel()` can find the run already
        # settled by the time it gets to its own cleanup.
        if self._cleaned:
            return
        self._cleaned = True
        for signal, slot in ((self.queue.jobDone, self._on_done),
                             (self.queue.jobFailed, self._on_failed),
                             (self.queue.jobStateChanged, self._on_state)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass                   # already disconnected, or queue gone
        # Only ever our own directory, and only the archives we asked for.
        if self.work_dir.name == "compare" and self.work_dir.is_dir():
            shutil.rmtree(self.work_dir, ignore_errors=True)
