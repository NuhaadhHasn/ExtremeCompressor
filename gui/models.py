"""The Job record the queue table renders and the workers mutate."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from excmp.planner import Profile

from .suggest import AnalysisSummary

_ids = itertools.count(1)


class JobKind(StrEnum):
    COMPRESS = "compress"
    EXTRACT = "extract"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)

    @property
    def label(self) -> str:
        return {
            JobState.QUEUED: "Queued",
            JobState.RUNNING: "Running",
            JobState.PAUSED: "Paused",
            JobState.DONE: "Done",
            JobState.FAILED: "Failed",
            JobState.CANCELLED: "Cancelled",
        }[self]


@dataclass
class Job:
    """One unit of work in the queue. Owned by the GUI thread; workers only
    report *about* it via signals, they never mutate it from off-thread."""

    inputs: list[Path]
    out_path: Path
    profile: Profile = Profile.NORMAL
    kind: JobKind = JobKind.COMPRESS
    id: str = field(default_factory=lambda: f"job{next(_ids)}")

    state: JobState = JobState.QUEUED
    stage: str = ""
    percent: float = 0.0
    eta_s: float | None = None

    orig_bytes: int = 0
    final_bytes: int = 0
    elapsed_s: float = 0.0

    summary: AnalysisSummary | None = None
    result: object | None = None      # CompressResult | ExtractResult
    error: str = ""
    log: list[str] = field(default_factory=list)

    LOG_LIMIT = 400

    @property
    def display_name(self) -> str:
        if not self.inputs:
            return self.id
        first = self.inputs[0].name or str(self.inputs[0])
        extra = len(self.inputs) - 1
        return f"{first} +{extra} more" if extra else first

    @property
    def saved_bytes(self) -> int:
        return max(0, self.orig_bytes - self.final_bytes)

    @property
    def saved_fraction(self) -> float:
        return self.saved_bytes / self.orig_bytes if self.orig_bytes else 0.0

    def append_log(self, line: str) -> None:
        """Keep a bounded tail - a long 7-Zip run emits thousands of lines
        and the expander only ever shows the end of it."""
        self.log.append(line)
        if len(self.log) > self.LOG_LIMIT:
            del self.log[: len(self.log) - self.LOG_LIMIT]
