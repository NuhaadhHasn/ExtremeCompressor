"""The queue: one job at a time, engine calls on a worker thread.

Threading contract
------------------
``QueueManager`` lives on the GUI thread and owns every :class:`Job`. Workers
are ``QRunnable``s on a pool capped at **one** concurrent job - this is a
two-core laptop and the stages already saturate it. Because ``QRunnable`` is
not a ``QObject`` it cannot declare signals, so the manager hands each worker
a shared :class:`WorkerSignals` (created on the GUI thread); Qt then queues
every emission back onto the GUI thread automatically, and nothing but the
worker touches engine state.

Pause and cancel
----------------
``cancel`` sets ``StageContext.cancel``, which ``run_tool`` already honors by
killing the child process. ``pause`` sets ``StageContext.pause``, which the
engine checks at stage boundaries, *and* stops the queue handing out new
jobs - so pausing means "finish this stage, then hold", never "abandon ten
minutes of LZMA2".
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from excmp.analyzer import analyze_file, iter_files
from excmp.planner import Profile, plan as make_plan
from excmp.stages.base import StageContext
from excmp.tools import ToolInfo, find_tools

from .models import Job, JobKind, JobState
from .progress import ChainProgress, EtaEstimator, expected_chain
from .suggest import AnalysisSummary, strongest_profile, summarize

# Don't flood the event loop: 7-Zip's -bsp1 emits a line per percent and
# zstd reports once per file.
_MIN_PCT_DELTA = 0.4
_MIN_INTERVAL_S = 0.10

# Precomp and 7-Zip animate progress with carriage returns and spinner
# glyphs, so a single "line" of stdout can hold fifty overwritten updates.
_CONTROL = {ord(c): None for c in "\x00\x08\x0b\x0c\x1b\x07"}


def _clean_log_line(line: str) -> str:
    """Last frame of a CR-animated line, with control characters removed."""
    return line.split("\r")[-1].translate(_CONTROL).strip()


class WorkerSignals(QObject):
    """Signals shared by every worker; the job id says who is talking."""

    started = Signal(str)
    progress = Signal(str, str, float, object)   # id, stage, overall pct, eta|None
    log = Signal(str, str)                       # id, line
    done = Signal(str, object)                   # id, CompressResult|ExtractResult
    failed = Signal(str, str)                    # id, message
    cancelled = Signal(str)


class AnalysisSignals(QObject):
    # The raw FileInfo list rides along so that switching profile can re-plan
    # instantly instead of re-reading every file's entropy.
    ready = Signal(object, object)   # list[FileInfo], AnalysisSummary
    progress = Signal(int, int)      # files read, files found
    failed = Signal(str)


# At most this many progress emissions per scan, however big the tree. On the
# real HDD corpus (42 files, 6.4 GB) a fixed tick of 5 still left a 4.7s
# silence on the big installers, so small trees now report every single file;
# a 10k-file tree still emits only ~200 signals.
_SCAN_UPDATES = 200


def _scan_tick(total: int) -> int:
    return max(1, total // _SCAN_UPDATES)


class AnalysisWorker(QRunnable):
    """Runs the analyzer + planner off the GUI thread.

    Entropy sampling reads up to 3 MiB per file; on the real HDD corpus
    (81 files, 5.76 GB, external drive) that is minutes, and a card that
    never changed read as a hang - hence the per-file tick (W2-8).
    """

    def __init__(self, paths: list[Path], profile: Profile,
                 tools: dict[str, ToolInfo | None], signals: AnalysisSignals) -> None:
        super().__init__()
        self.paths = list(paths)
        self.profile = profile
        self.tools = tools
        self.signals = signals

    def run(self) -> None:  # pragma: no cover - exercised via the GUI tests
        try:
            # Walking the tree is one cheap pass; do it first so the count is
            # known and the bar can be determinate for the expensive part.
            files: list[Path] = []
            for path in self.paths:
                files.extend(iter_files(path))
            total = len(files)
            self.signals.progress.emit(0, total)

            tick = _scan_tick(total)
            infos = []
            for index, file in enumerate(files, start=1):
                infos.append(analyze_file(file))
                if index % tick == 0 or index == total:
                    self.signals.progress.emit(index, total)

            the_plan = make_plan(infos, self.profile, self.tools)
            reference = make_plan(infos, strongest_profile(self.tools), self.tools)
            self.signals.ready.emit(
                infos, summarize(infos, the_plan, self.tools, reference))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ListingSignals(QObject):
    ready = Signal(object)          # ArchiveListing
    failed = Signal(str, bool)      # message, needs_password


class ListingWorker(QRunnable):
    """Read a foreign archive's table of contents off the GUI thread (G2).

    Only foreign archives come through here. Listing one of ours is a
    zip-directory read plus a JSON parse and stays synchronous, because it
    genuinely is instant and a worker would only add latency and a race to
    something that has neither. This one shells out to `7z l -slt`, against a
    file that may be an ISO on an external drive.

    ``needs_password`` rides beside the message so the surface can offer a
    prompt instead of an apology - the two failures look identical in a
    string and lead to completely different next moves.
    """

    def __init__(self, archive: Path, password: str | None, temp_dir: Path,
                 signals: ListingSignals) -> None:
        super().__init__()
        self.archive = archive
        self.password = password
        self.temp_dir = temp_dir
        self.signals = signals

    def run(self) -> None:  # pragma: no cover - exercised via the GUI tests
        from excmp.engine import EncryptedArchiveError, list_any

        try:
            listing = list_any(self.archive,
                               StageContext(temp_dir=self.temp_dir),
                               self.password)
        except EncryptedArchiveError as exc:
            self.signals.failed.emit(str(exc), True)
        except Exception as exc:                            # noqa: BLE001
            self.signals.failed.emit(str(exc), False)
        else:
            self.signals.ready.emit(listing)


class _EngineWorker(QRunnable):
    """Shared plumbing: a StageContext wired to throttled Qt signals."""

    def __init__(self, job: Job, signals: WorkerSignals, temp_dir: Path,
                 threads: int = 0) -> None:
        super().__init__()
        self.job_id = job.id
        self.signals = signals
        self.ctx = StageContext(temp_dir=temp_dir, threads=threads)
        self.ctx.progress_cb = self._on_progress
        self.ctx.log_cb = self._on_log
        chain = job.summary.chain if job.summary else []
        self._chain = ChainProgress(chain or expected_chain(["sevenzip"]))
        self._eta = EtaEstimator()
        self._t0 = 0.0
        self._last_emit = 0.0
        self._last_pct = -1.0

    # -- callbacks, running on the worker thread ---------------------------
    def _on_progress(self, stage: str, pct: float) -> None:
        overall = self._chain.update(stage, pct)
        now = time.monotonic()
        if (overall - self._last_pct < _MIN_PCT_DELTA
                and now - self._last_emit < _MIN_INTERVAL_S
                and overall < 100.0):
            return
        self._last_pct = overall
        self._last_emit = now
        eta = self._eta.update(overall / 100.0, now - self._t0)
        self.signals.progress.emit(self.job_id, stage, overall, eta)

    def _on_log(self, stage: str, line: str) -> None:
        line = _clean_log_line(line)
        if line:
            self.signals.log.emit(self.job_id, f"[{stage}] {line}")

    def _note(self, line: str) -> None:
        self.signals.log.emit(self.job_id, line)

    def _finish(self, result: object) -> None:
        self._chain.finish()
        self.signals.progress.emit(self.job_id, "", 100.0, 0.0)
        self.signals.done.emit(self.job_id, result)

    def _fail(self, exc: BaseException) -> None:
        if self.ctx.cancel.is_set():
            self._note("cancelled by user")
            self.signals.cancelled.emit(self.job_id)
        else:
            self.signals.failed.emit(self.job_id, str(exc))


class CompressWorker(_EngineWorker):
    def __init__(self, job: Job, signals: WorkerSignals, temp_dir: Path,
                 tools: dict[str, ToolInfo | None], threads: int = 0) -> None:
        super().__init__(job, signals, temp_dir, threads)
        self.inputs = list(job.inputs)
        self.out_path = job.out_path
        self.profile = job.profile
        self.tools = tools
        self.sidecar = job.sidecar
        self.options = job.options
        self.password = job.password
        self.recovery = job.recovery
        self.split = job.split
        self.archive_format = job.archive_format

    def run(self) -> None:
        from excmp import engine  # deferred: importing the engine is not free

        self._t0 = time.monotonic()
        self.signals.started.emit(self.job_id)
        self._note(f"profile '{self.profile.value}' → chain: "
                   f"{' → '.join(self._chain.chain)}")
        try:
            if self.archive_format != "excmp":
                # G4: a plain .7z/.zip has no container and no ledger, so it
                # takes a different engine entry point. It is still extracted
                # and hashed before publication.
                # The password goes through so the engine can REFUSE the
                # combination. Omitting it here is how this silently wrote an
                # unencrypted archive to a user who had typed one in.
                std = engine.compress_standard(
                    self.inputs, self.out_path, self.archive_format, self.ctx,
                    self.tools, password=self.password)
                self._note(std.note)
                result = engine.CompressResult(
                    archive=std.archive, orig_bytes=std.orig_bytes,
                    final_bytes=std.final_bytes, routes=[], warnings=[],
                    elapsed_s=std.elapsed_s)
            else:
                result = engine.compress(
                    self.inputs, self.out_path, self.profile, self.ctx,
                    self.tools, sidecar=self.sidecar, options=self.options,
                    password=self.password)
            # Both of the following run only after the archive is published,
            # so they describe the file that shipped rather than its .tmp twin.
            if self.recovery:
                self._add_recovery(result.archive)
            if self.split:
                self._split(result.archive)
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            self._fail(exc)
            return
        for warning in result.warnings:
            self._note(f"warning: {warning}")
        self._finish(result)

    def _add_recovery(self, archive) -> None:
        from excmp.recovery import available, create

        if not available():
            self._note("par2 is not installed - no recovery records written")
            return
        made = create(archive, self.recovery, self.ctx)
        self._note(f"wrote {len(made)} recovery file(s) at {self.recovery}%")

    def _split(self, archive) -> None:
        from excmp.volumes import split_file, write_parts_sidecar

        parts = split_file(archive, self.split)
        write_parts_sidecar(parts)
        self._note(f"split into {len(parts)} volume(s): {parts[0].name} .. "
                   f"{parts[-1].name}")


class ExtractWorker(_EngineWorker):
    def __init__(self, job: Job, signals: WorkerSignals, temp_dir: Path,
                 threads: int = 0) -> None:
        super().__init__(job, signals, temp_dir, threads)
        # Read off the Job here, on the GUI thread, and keep only the values.
        # The base class deliberately stores `job.id` rather than the Job so
        # that a worker never shares a mutable object with the thread that
        # owns it; reaching back through `self.job` would undo that.
        self.archive = job.inputs[0]
        self.out_dir = job.out_path
        self.selected = list(job.selected)
        self.password = job.password

    def run(self) -> None:
        from excmp import engine

        self._t0 = time.monotonic()
        self.signals.started.emit(self.job_id)
        self._note(f"restoring {self.archive.name} → {self.out_dir}")
        try:
            # extract_any, not extract: G1 lets this open zip/7z/rar/iso/... too.
            # The result carries `ledger_backed` so the UI can tell the verified
            # restore from the best-effort one instead of blurring them.
            if self.selected:
                result = engine.extract_selected(
                    self.archive, self.selected, self.out_dir, self.ctx,
                    self.password)
            else:
                result = engine.extract_any(self.archive, self.out_dir,
                                            self.ctx, self.password)
        except BaseException as exc:  # noqa: BLE001
            self._fail(exc)
            return
        if result.ledger_backed:
            self._note(f"verified {result.verified} SHA-256 hash(es)")
        else:
            self._note("no SHA-256 ledger in this archive - nothing to verify "
                       "the restored files against")
        self._finish(result)


class VerifyWorker(_EngineWorker):
    """A verify is a full restore, so it is a job like any other - queued,
    cancellable, logged - never a modal that locks the window for ten minutes
    while it reads 700 MB."""

    def __init__(self, job: Job, signals: WorkerSignals, temp_dir: Path,
                 threads: int = 0) -> None:
        super().__init__(job, signals, temp_dir, threads)
        self.archive = job.inputs[0]

    def run(self) -> None:
        from excmp import engine

        self._t0 = time.monotonic()
        self.signals.started.emit(self.job_id)
        self._note(f"verifying {self.archive.name}: restoring every file to "
                   f"temp and checking it against the manifest’s SHA-256 ledger")
        try:
            result = engine.verify_archive(self.archive, self.ctx)
        except BaseException as exc:  # noqa: BLE001
            self._fail(exc)
            return
        self._note(f"OK: {result.verified} hash(es) matched")
        self._finish(result)


class QueueManager(QObject):
    """Owns the job list and runs them strictly one at a time."""

    jobAdded = Signal(str)
    jobStarted = Signal(str)
    jobProgress = Signal(str, str, float, object)
    jobLog = Signal(str, str)
    jobDone = Signal(str, object)
    jobFailed = Signal(str, str)
    jobStateChanged = Signal(str, object)
    queueIdle = Signal()
    pausedChanged = Signal(bool)

    def __init__(self, temp_dir: Path | None = None,
                 tools: dict[str, ToolInfo | None] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.temp_dir = Path(temp_dir or (Path.home() / ".excmp" / "tmp"))
        self.tools = tools if tools is not None else find_tools(with_versions=True)
        self.threads = 0

        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._active: _EngineWorker | None = None
        self._active_id: str | None = None
        self._paused = False
        self._started_at = 0.0

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)     # one job at a time, by design

        self._signals = WorkerSignals(self)
        self._signals.started.connect(self._on_started)
        self._signals.progress.connect(self._on_progress)
        self._signals.log.connect(self._on_log)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._signals.cancelled.connect(self._on_cancelled)

    # -- inspection --------------------------------------------------------
    @property
    def jobs(self) -> list[Job]:
        return [self._jobs[i] for i in self._order]

    def job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_busy(self) -> bool:
        return self._active_id is not None

    def pending_count(self) -> int:
        return sum(1 for j in self.jobs if not j.state.is_terminal)

    # -- building the queue ------------------------------------------------
    def add_job(self, job: Job) -> Job:
        self._jobs[job.id] = job
        self._order.append(job.id)
        self.jobAdded.emit(job.id)
        self._pump()
        return job

    def add_compress(self, inputs: list[Path], out_path: Path, profile: Profile,
                     summary: AnalysisSummary | None = None,
                     sidecar: bool = False, options: object | None = None,
                     extras: dict | None = None) -> Job:
        job = Job(inputs=list(inputs), out_path=Path(out_path), profile=profile,
                  kind=JobKind.COMPRESS, summary=summary, sidecar=sidecar,
                  options=options, **(extras or {}))
        if summary is not None:
            job.orig_bytes = summary.total_bytes
        return self.add_job(job)

    def add_extract(self, archive: Path, out_dir: Path) -> Job:
        archive = Path(archive)
        job = Job(inputs=[archive], out_path=Path(out_dir), kind=JobKind.EXTRACT)
        job.orig_bytes = archive.stat().st_size if archive.exists() else 0
        return self.add_job(job)

    def add_extract_selected(self, archive: Path, out_dir: Path,
                             names: list, password: str | None = None) -> Job:
        """Restore only ``names`` (G2). Same worker, same queue, same
        progress - a selective restore is an extract with a shorter list, not
        a second code path with its own bugs."""
        archive = Path(archive)
        job = Job(inputs=[archive], out_path=Path(out_dir), kind=JobKind.EXTRACT)
        job.orig_bytes = archive.stat().st_size if archive.exists() else 0
        job.selected = [str(n) for n in names]
        job.password = password
        return self.add_job(job)

    def add_verify(self, archive: Path) -> Job:
        """A verify has no destination. ``out_path`` is the archive itself so
        the row's context menu can still reveal it in Explorer - it is never
        written to."""
        archive = Path(archive)
        job = Job(inputs=[archive], out_path=archive, kind=JobKind.VERIFY)
        job.orig_bytes = archive.stat().st_size if archive.exists() else 0
        return self.add_job(job)

    # -- control -----------------------------------------------------------
    def pause(self) -> None:
        """Hold the queue. The running job finishes its current stage first."""
        if self._paused:
            return
        self._paused = True
        if self._active is not None:
            self._active.ctx.pause.set()
        active = self._jobs.get(self._active_id or "")
        if active is not None and active.state is JobState.RUNNING:
            self._set_state(active, JobState.PAUSED)
        self.pausedChanged.emit(True)

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._active is not None:
            self._active.ctx.pause.clear()
        active = self._jobs.get(self._active_id or "")
        if active is not None and active.state is JobState.PAUSED:
            self._set_state(active, JobState.RUNNING)
        self.pausedChanged.emit(False)
        self._pump()

    def toggle_pause(self) -> None:
        self.resume() if self._paused else self.pause()

    def cancel(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.state.is_terminal:
            return
        if job_id == self._active_id and self._active is not None:
            # Unblock a paused stage boundary first, or the cancel would sit
            # in the pause loop until someone hit resume.
            self._active.ctx.cancel.set()
            self._active.ctx.pause.clear()
        else:
            self._set_state(job, JobState.CANCELLED)
            self._pump()

    def cancel_all(self) -> None:
        for job in list(self.jobs):
            self.cancel(job.id)

    def clear_finished(self) -> None:
        for job_id in [i for i in self._order if self._jobs[i].state.is_terminal]:
            del self._jobs[job_id]
            self._order.remove(job_id)

    def shutdown(self, wait_ms: int = 5000) -> None:
        """Cancel everything and wait for the pool - called on window close so
        we never leave a 7-Zip child process orphaned."""
        self.cancel_all()
        self._pool.waitForDone(wait_ms)

    # -- the pump ----------------------------------------------------------
    def _pump(self) -> None:
        if self._active_id is not None or self._paused:
            return
        nxt = next((j for j in self.jobs if j.state is JobState.QUEUED), None)
        if nxt is None:
            self.queueIdle.emit()
            return
        worker: _EngineWorker
        if nxt.kind is JobKind.VERIFY:
            worker = VerifyWorker(nxt, self._signals, self.temp_dir, self.threads)
        elif nxt.kind is JobKind.EXTRACT:
            worker = ExtractWorker(nxt, self._signals, self.temp_dir, self.threads)
        else:
            worker = CompressWorker(nxt, self._signals, self.temp_dir,
                                    self.tools, self.threads)
        self._active = worker
        self._active_id = nxt.id
        self._started_at = time.monotonic()
        self._pool.start(worker)

    def _set_state(self, job: Job, state: JobState) -> None:
        if job.state is state:
            return
        job.state = state
        self.jobStateChanged.emit(job.id, state)

    def _retire(self, job: Job, state: JobState) -> None:
        """Free the slot and settle the job. Deliberately does *not* pump:
        callers emit their own jobDone/jobFailed first, so listeners see this
        job finish before the next one starts."""
        job.elapsed_s = time.monotonic() - self._started_at
        self._active = None
        self._active_id = None
        self._set_state(job, state)

    # -- worker signal handlers (GUI thread) -------------------------------
    def _on_started(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._set_state(job, JobState.PAUSED if self._paused else JobState.RUNNING)
        self.jobStarted.emit(job_id)

    def _on_progress(self, job_id: str, stage: str, pct: float, eta: object) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.stage = stage
        job.percent = pct
        job.eta_s = eta if isinstance(eta, (int, float)) else None
        self.jobProgress.emit(job_id, stage, pct, eta)

    def _on_log(self, job_id: str, line: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.append_log(line)
        self.jobLog.emit(job_id, line)

    def _on_done(self, job_id: str, result: object) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.result = result
        job.percent = 100.0
        job.eta_s = 0.0
        if job.kind is JobKind.COMPRESS:
            job.orig_bytes = getattr(result, "orig_bytes", job.orig_bytes)
            job.final_bytes = getattr(result, "final_bytes", 0)
        self._retire(job, JobState.DONE)
        self.jobDone.emit(job_id, result)
        self._pump()

    def _on_failed(self, job_id: str, message: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.error = message
        job.append_log(f"FAILED: {message}")
        self._retire(job, JobState.FAILED)
        self.jobFailed.emit(job_id, message)
        self._pump()

    def _on_cancelled(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._retire(job, JobState.CANCELLED)
        self._pump()
