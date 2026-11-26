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

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from excmp.analyzer import analyze_file, describe_unreadable, iter_files
from excmp.planner import Profile, plan as make_plan
from excmp.stages.base import StageContext
from excmp.tools import ToolInfo, find_tools

from .models import Job, JobKind, JobState
from .progress import (FINISHING, PACK_STAGE, PACKING, VERIFY_GAP_LIMIT_S,
                       VERIFY_STAGE, VERIFYING,
                       VERIFYING_LATE, ChainProgress, EtaEstimator,
                       expected_chain)
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
    # K3: one line per file the analysis could not read. A *note*, not a
    # failure - losing the estimate for a whole folder because one
    # spreadsheet is open is exactly what this replaced.
    note = Signal(str)


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
            # Each file keeps the root it was found under, so the analysis
            # can record its archive name for the overhead estimate (B19d).
            files: list[tuple[Path, Path]] = []
            for path in self.paths:
                files.extend((path, f) for f in iter_files(path))
            total = len(files)
            self.signals.progress.emit(0, total)

            tick = _scan_tick(total)
            infos = []
            for index, (root, file) in enumerate(files, start=1):
                try:
                    infos.append(analyze_file(file, root))
                except OSError as exc:
                    # K3: `analyze_file` opens the file, so one open Excel or
                    # Outlook document raised here, the bare `except` below
                    # emitted `failed`, and the user lost the size estimate,
                    # the route breakdown, the store reasons and the profile
                    # recommendation for the *entire* selection - shown as the
                    # raw stdlib "[Errno 13] Permission denied", the very
                    # wording `describe_unreadable` exists to replace.
                    #
                    # The analysis pass must never be able to fail for a
                    # reason the compress it precedes can survive.
                    self.signals.note.emit(describe_unreadable(file, exc))
                if index % tick == 0 or index == total:
                    self.signals.progress.emit(index, total)
            if not infos:
                raise ValueError(
                    "none of the selected files could be read - they may be "
                    "open in another program")

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


def _time_split(summary: AnalysisSummary | None) -> tuple[float | None, float | None]:
    """(compress, verify) expected seconds for a job's bar, if it has an analysis.

    The same rates the comparison table quotes, this machine's calibration
    included, so the bar's self-test share agrees with the promised time.
    """
    if summary is None:
        return None, None
    from excmp.calibrate import blended_rates
    from excmp.estimate import PackCost, RecodeCost, time_split

    try:
        pack = PackCost(bytes=summary.pack_bytes, seconds=summary.pack_seconds,
                        verify_seconds=summary.pack_verify_seconds)
        recode = RecodeCost(compress_seconds=summary.recode_seconds,
                            verify_seconds=summary.recode_verify_seconds,
                            own_bytes=summary.recode_own_bytes)
        return time_split(summary.store_bytes, summary.pipeline_bytes,
                          summary.chain, blended_rates(), pack=pack,
                          recode=recode, files=summary.per_file_count)
    except Exception:                                   # noqa: BLE001
        # An estimate is a nicety for the bar; a job never fails for want
        # of one.
        return None, None


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
        compress_s, verify_s = _time_split(job.summary)
        self._chain = ChainProgress(
            chain or expected_chain(["sevenzip"]), compress_s=compress_s,
            verify_s=verify_s,
            pack_s=job.summary.pack_seconds if job.summary else None)
        self._eta = EtaEstimator()
        self._clock = time.monotonic
        self._t0 = 0.0
        self._last_emit = 0.0
        self._last_pct = -1.0
        self._last_stage = ""
        # I11: when the D9 self-test began, the seconds it has actually run
        # (beat to beat, so a pause is not counted) and, once done, how long it
        # occupied the job's clock, pauses included. The first is what the bar
        # and countdown use; the second is what calibration must subtract from
        # a job time that also contains the pause.
        self._verify_t0: float | None = None
        # B19: what Precomp's recoders were expected to add, which calibration
        # must not learn as the chain's own speed either.
        self._recode_s = job.summary.recode_seconds if job.summary else 0.0
        self._per_file_count = job.summary.per_file_count if job.summary else 0
        self._recode_bytes = job.summary.recode_bytes if job.summary else 0
        # B23: and media piped only because the probe flagged it, which Precomp
        # passes straight through.
        self._probe_piped_bytes = job.summary.probe_piped_bytes if job.summary else 0
        # B13: the pack phase's span, which calibration must also leave out.
        self._pack_t0: float | None = None
        self._pack_end = 0.0
        self._verify_last = 0.0
        self._verify_run = 0.0
        self._verify_elapsed = 0.0
        # B23: the stage the heartbeat is creeping the bar through, and when it
        # started (a stage that prints nothing sends no event at its start).
        self._silent_stage: str | None = None
        self._silent_t0 = 0.0
        self._beat_last: float | None = None
        self._heartbeat_stopped = False
        # The engine thread reports and the heartbeat thread creeps: one lock
        # around both, so the bar never goes back and a beat cannot land after
        # the job has ended.
        self._emit_lock = threading.RLock()

    # -- callbacks, running on the worker thread ---------------------------
    def _on_progress(self, stage: str, pct: float) -> None:
        with self._emit_lock:
            self._on_progress_locked(stage, pct)

    def _on_progress_locked(self, stage: str, pct: float) -> None:
        now = self._clock()
        if stage == VERIFY_STAGE:
            self._on_verify(pct, now)
            return
        overall = self._chain.update(stage, pct)
        if stage == PACK_STAGE:
            if self._pack_t0 is None:
                self._pack_t0 = now
            self._pack_end = now
            stage = PACKING
        # A change of stage is always drawn. The chain's last report and the
        # pack phase's first land on the same bar value a moment apart, and
        # throttling the second left the job naming the previous stage for
        # the whole first file - minutes, for a large Vorbis file.
        if (stage == self._last_stage
                and overall - self._last_pct < _MIN_PCT_DELTA
                and now - self._last_emit < _MIN_INTERVAL_S
                and overall < 100.0):
            return
        self._last_stage = stage
        self._last_pct = overall
        self._last_emit = now
        eta = self._eta.update(overall / 100.0, now - self._t0)
        self.signals.progress.emit(self.job_id, stage, overall, eta)

    def _heartbeat_once(self) -> None:
        """B23: while a stage that prints nothing runs (zpaqfranz: one scan
        line, then silence for the whole compress), move the bar through that
        stage's band by elapsed time against the estimate. The stage reports
        nothing at its start, so its clock starts when the one before it is
        seen to finish. The stage's own 100% closes the band and ends this."""
        with self._emit_lock:
            if self._heartbeat_stopped:
                return
            now = self._clock()
            last, self._beat_last = self._beat_last, now
            stage = self._chain.silent_stage()
            if stage is None:
                self._silent_stage = None
                return
            if stage != self._silent_stage:
                self._silent_stage, self._silent_t0 = stage, now
            if self.ctx.pause.is_set():
                # Pause holds the engine between stages, so the stage that is
                # "silent" next may not have started: its clock does not run,
                # and on resume it goes on from where it was, not from the
                # pause's length.
                if last is not None:
                    self._silent_t0 += now - last
                return
            overall = self._chain.creep(now - self._silent_t0)
            if overall <= self._last_pct:
                return
            self._last_stage, self._last_pct, self._last_emit = stage, overall, now
            eta = self._eta.update(overall / 100.0, now - self._t0)
            self.signals.progress.emit(self.job_id, stage, overall, eta)

    def _stop_heartbeat(self, stop: threading.Event) -> None:
        """End the beat for good: a beat already in flight, or one that wakes
        after the job is over, draws nothing (it would overwrite the finished
        job's bar)."""
        with self._emit_lock:
            self._heartbeat_stopped = True
        stop.set()

    def _start_heartbeat(self) -> threading.Event:
        """Beat once a second until the returned event is set."""
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(1.0):
                try:
                    self._heartbeat_once()
                except Exception:           # noqa: BLE001 - a bar is never worth a job
                    pass

        threading.Thread(target=beat, daemon=True).start()
        return stop

    def _on_verify(self, pct: float, now: float) -> None:
        """The D9 self-test: timed against the estimate, never parsed.

        The engine sends a heartbeat about once a second, already slower than
        the throttle, so every report is drawn. The remaining time is the
        estimate's, not the EMA's: the bar's position here comes from that
        same estimate, and feeding it back into the EMA would only echo it.
        """
        if self._verify_t0 is None:
            self._verify_t0 = now
        elif now - self._verify_last <= VERIFY_GAP_LIMIT_S:
            # A longer gap means the beats stopped: the job was paused and the
            # restore held. Those seconds are not the self-test's, and
            # counting them would flip a resumed job to "past estimate".
            self._verify_run += now - self._verify_last
        self._verify_last = now
        elapsed = self._verify_run
        if pct >= 100.0:
            self._verify_elapsed = now - self._verify_t0
            overall = self._chain.verify_done()
            eta: float | None = None
            # The gate passed. What follows (publish, encrypt, recovery
            # records, split) reports nothing, and "verifying" would be a lie.
            label = FINISHING
        else:
            overall = self._chain.verify(elapsed)
            eta = self._chain.verify_remaining(elapsed)
            spent = self._chain.verify_s is not None and eta is None
            label = VERIFYING_LATE if spent else VERIFYING
        self._last_pct = overall
        self._last_emit = now
        self.signals.progress.emit(self.job_id, label, overall, eta)

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
        if self.archive_format != "excmp":
            # A plain .7z/.zip is one 7-Zip stage, checked by a different gate
            # that reports no "verify" events. Keeping the profile's chain and
            # its self-test share would leave the bar parked at 51-82%.
            self._chain = ChainProgress(expected_chain(["sevenzip"]))

    def run(self) -> None:
        from excmp import engine  # deferred: importing the engine is not free

        self._t0 = time.monotonic()
        self.signals.started.emit(self.job_id)
        self._note(f"profile '{self.profile.value}' → chain: "
                   f"{' → '.join(self._chain.chain)}")
        heartbeat = self._start_heartbeat()
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
                # K3: a plain export carries no ledger, so `skipped` is the
                # only record that a file was left out. Rebuilding the
                # CompressResult with `warnings=[]` discarded it, which is how
                # the GUI came to publish a partial archive silently.
                for line in std.skipped:
                    self._note(line)
                result = engine.CompressResult(
                    archive=std.archive, orig_bytes=std.orig_bytes,
                    final_bytes=std.final_bytes, routes=[],
                    warnings=list(std.skipped), elapsed_s=std.elapsed_s,
                    skipped=list(std.skipped))
            else:
                result = engine.compress(
                    self.inputs, self.out_path, self.profile, self.ctx,
                    self.tools, sidecar=self.sidecar, options=self.options,
                    password=self.password)
            # Both of the following run only after the archive is published,
            # so they describe the file that shipped rather than its .tmp twin.
            #
            # And both are caught: at this point the archive is written AND
            # verified. A split that runs out of disk is a failed *extra*, not
            # a failed job, and reporting it as one would send somebody to
            # re-run work that already succeeded - possibly over the archive
            # they were about to keep.
            for step, run in (("recovery records", self._add_recovery),
                              ("split", self._split)):
                if step == "recovery records" and not self.recovery:
                    continue
                if step == "split" and not self.split:
                    continue
                try:
                    run(result.archive)
                except Exception as exc:      # noqa: BLE001 - reported below
                    self._note(f"warning: the archive is written and verified "
                               f"at {result.archive}, but {step} failed: {exc}")
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            self._stop_heartbeat(heartbeat)
            self._fail(exc)
            return
        self._stop_heartbeat(heartbeat)
        for warning in result.warnings:
            self._note(f"warning: {warning}")
        self._calibrate(result)
        self._finish(result)

    def _calibrate(self, result) -> None:
        """J7: fold this job's real throughput back into the estimator.

        Only the *piped* bytes count. A store-only job is disk-bound and says
        nothing about how fast a codec runs, and averaging the two together is
        precisely the "11.6 MB/s" blend that mispredicted every other mix.
        """
        from excmp.calibrate import record

        # The engine reports this from the ledger, exactly. It used to be
        # reconstructed here by stat-ing `routes[].files`, which holds
        # archive-**relative** paths, so `Path("data/text.txt").is_file()`
        # resolved against the process CWD, came back false for every entry,
        # and `piped` was always 0 - which made this return early and J7
        # record nothing at all. A byte count that depends on where the app
        # happens to be running was never a byte count.
        piped = result.piped_bytes
        stages = next((r.get("stages", []) for r in result.routes
                       if r.get("action") == "pipeline"), [])
        if not stages or not piped:
            return
        # B19: a job made mostly of media Precomp recodes itself (MP3, the
        # JPEGs lepton refuses) ran at that recoder's pace (~1 MB/s each way
        # quiet, 2026-10-17; down to 0.3 MB/s contended), which says little
        # about the chain: one such job moved the learned Extreme
        # rate by -23% (review). Those are timed by `recode_cost` instead.
        # Below a quarter of the piped bytes, their modelled share of the time
        # is taken out and the rest is learned.
        # B23: and media piped only because the probe flagged it (MKV, MP4,
        # ...): Precomp finds nothing in it and streams it through, the chain's
        # no-op regime, which taught Extreme 3.1 MB/s against its 1.41 prior
        # from one MKV job. The next job with streams Precomp can open then ran
        # 2-3x over its estimate. Not modelled, so not learned; the two kinds
        # count together (they are disjoint: the probe set has no recoded type).
        if (self._recode_bytes + self._probe_piped_bytes) * 4 >= piped:
            return
        # I11: the self-test is estimated separately (`_VERIFY_RATE`), so it
        # must not also be learned as part of the codec's rate. Counting it in
        # both put the whole restore into an Insane estimate twice.
        #
        # B13: the same for the pack phase. Packing Ogg audio runs at
        # ~0.1 MB/s on bytes that are not piped, so counting it as codec time
        # taught the estimator a rate several times too slow for the chain.
        pack_s = (self._pack_end - self._pack_t0
                  if self._pack_t0 is not None else 0.0)
        # B22: nor the job's setup second, which the estimate bills on its own
        # (`estimate.job_fixed_seconds`); folded into the rate it was counted
        # twice, and it is a large share of a small job.
        # Nor the per-file cost (`estimate.per_file_seconds`), for the same
        # reason: a tree of small files would otherwise teach the chain a
        # byte rate several times too slow for the next large file.
        from excmp.estimate import job_fixed_seconds, per_file_seconds
        per_file_s = per_file_seconds(self._per_file_count)[0]
        codec_s = (result.elapsed_s - self._verify_elapsed - pack_s - self._recode_s
                   - job_fixed_seconds(stages) - per_file_s)
        # A job paced by how many files it holds says little about the chain's
        # byte rate, and what is left after taking a modelled per-file cost
        # off it is mostly that model's error: on a machine that opens files
        # faster than the prior, the remainder is a few tenths of a second and
        # would be learned as hundreds of MB/s. Not modelled well enough to
        # subtract, so not learned (as with the recoded media above).
        if per_file_s > 0 and per_file_s >= codec_s:      # only when a per-file cost was really taken off
            return
        # No `achieved_factor` (B19): a whole-job ratio is not the slope the
        # estimator's factor became in B8 (see `calibrate.record`).
        record(stages, piped_bytes=piped, elapsed_s=codec_s)

    def _add_recovery(self, archive) -> None:
        from excmp.recovery import available, create

        if not available():
            self._note("par2 is not installed - no recovery records written")
            return
        made = create(archive, self.recovery, self.ctx)
        self._note(f"wrote {len(made)} recovery file(s) at {self.recovery}%")

    def _split(self, archive) -> None:
        from excmp.volumes import split_file, write_parts_sidecar

        # D8: digests measured during the split, so the sidecar does not
        # re-read the whole archive to learn them.
        digests: dict[str, str] = {}
        parts = split_file(archive, self.split, digests)
        write_parts_sidecar(parts, digests)
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
        self.password = job.password

    def run(self) -> None:
        from excmp import engine

        self._t0 = time.monotonic()
        self.signals.started.emit(self.job_id)
        self._note(f"verifying {self.archive.name}: restoring every file to "
                   f"temp and checking it against the manifest’s SHA-256 ledger")
        try:
            result = engine.verify_archive(self.archive, self.ctx, self.password)
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

    def add_extract(self, archive: Path, out_dir: Path, password: str | None = None) -> Job:
        archive = Path(archive)
        job = Job(inputs=[archive], out_path=Path(out_dir), kind=JobKind.EXTRACT)
        job.orig_bytes = archive.stat().st_size if archive.exists() else 0
        job.password = password
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

    def add_verify(self, archive: Path, password: str | None = None) -> Job:
        """A verify has no destination. ``out_path`` is the archive itself so
        the row's context menu can still reveal it in Explorer - it is never
        written to."""
        archive = Path(archive)
        job = Job(inputs=[archive], out_path=archive, kind=JobKind.VERIFY)
        job.orig_bytes = archive.stat().st_size if archive.exists() else 0
        job.password = password
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

    def order(self) -> list[str]:
        """Job ids in run order. A list copy - callers reorder through
        `move_job`, so the queue stays the only thing that mutates it."""
        return list(self._order)

    def move_job(self, job_id: str, delta: int) -> None:
        """Nudge a queued job up or down. Out-of-range and unknown ids are
        no-ops: a queue control that raises is a queue control nobody uses."""
        if job_id not in self._jobs or job_id not in self._order:
            return
        index = self._order.index(job_id)
        target = max(0, min(len(self._order) - 1, index + delta))
        if target == index:
            return
        self._order.insert(target, self._order.pop(index))

    def run_next(self, job_id: str) -> None:
        """Put this job at the head of the *waiting* jobs.

        Never ahead of one already running - that would mean stopping work
        already paid for, which is not what "run next" means to anybody.
        """
        if job_id not in self._jobs or job_id not in self._order:
            return
        first_waiting = 0
        for i, other in enumerate(self._order):
            if self._jobs[other].state.is_terminal or other == self._active_id:
                first_waiting = i + 1
        self._order.remove(job_id)
        self._order.insert(min(first_waiting, len(self._order)), job_id)

    def clear_finished(self) -> None:
        """Tidy the queue - and keep the record (I3).

        This used to delete the job outright, so the only trace of what was
        compressed, how well and with which settings went with it.
        """
        from . import history

        for job_id in [i for i in self._order if self._jobs[i].state.is_terminal]:
            job = self._jobs[job_id]
            # ...except an I6 measurement, whose archive was deleted as soon as
            # its size was read. A history row is a record of something you
            # still have.
            if not getattr(job, "measurement", False):
                history.append(self._history_entry(job))
            del self._jobs[job_id]
            self._order.remove(job_id)

    @staticmethod
    def _history_entry(job):
        from datetime import datetime

        from . import history

        return history.HistoryEntry(
            archive=str(job.out_path),
            inputs=[str(p) for p in job.inputs],
            profile=job.profile.value,
            chain=" + ".join(getattr(job, "chain", []) or []),
            orig_bytes=int(job.orig_bytes or 0),
            final_bytes=int(job.final_bytes or 0),
            elapsed_s=float(getattr(job, "elapsed_s", 0.0) or 0.0),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            state=job.state.value,
            error=str(getattr(job, "error", "") or ""),
            archive_format=getattr(job, "archive_format", "excmp"),
            recovery=getattr(job, "recovery", None),
            split=getattr(job, "split", None),
            # The fact, never the password: history outlives the session and a
            # secret written here would outlive it too.
            encrypted=bool(getattr(job, "password", None)),
        )

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
