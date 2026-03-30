"""
Job state machine, cancellation tokens, and progress reporting.

State machine:
    PENDING -> COLLECTING -> ANALYZING -> THEMING -> REPORTING -> COMPLETED
                                                     -> FAILED (from any running state)
                                                     -> CANCELLED (from any running state)
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Any


class JobState(str, enum.Enum):
    """Pipeline job states."""

    PENDING = "PENDING"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    THEMING = "THEMING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Valid transitions: from_state -> set of allowed to_states
_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.PENDING: {JobState.COLLECTING, JobState.FAILED},
    JobState.COLLECTING: {
        JobState.ANALYZING, JobState.FAILED, JobState.CANCELLED,
    },
    JobState.ANALYZING: {
        JobState.THEMING, JobState.FAILED, JobState.CANCELLED,
    },
    JobState.THEMING: {
        JobState.REPORTING, JobState.FAILED, JobState.CANCELLED,
    },
    JobState.REPORTING: {
        JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED,
    },
    # Terminal states — no transitions out
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


def is_valid_transition(
    from_state: JobState, to_state: JobState,
) -> bool:
    """Check whether a state transition is allowed."""
    return to_state in _TRANSITIONS.get(from_state, set())


class CancelledError(Exception):
    """Raised by CancellationToken.check() when cancelled."""


class CancellationToken:
    """Cooperative cancellation via threading.Event.

    Pipeline stages check this token between items. When cancelled,
    stages complete their current item and exit cleanly.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        """Check cancellation state without raising."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Signal cancellation. Thread-safe."""
        self._event.set()

    def check(self) -> None:
        """Raise CancelledError if cancelled."""
        if self._event.is_set():
            raise CancelledError("Job cancelled")


class JobProgress:
    """Thread-safe progress tracker for a running job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage: str = ""
        self._items_completed: int = 0
        self._items_total: int = 0
        self._message: str = ""
        self._start_time: float = time.monotonic()

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    @property
    def items_completed(self) -> int:
        with self._lock:
            return self._items_completed

    @property
    def items_total(self) -> int:
        with self._lock:
            return self._items_total

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def update(
        self,
        stage: str | None = None,
        items_completed: int | None = None,
        items_total: int | None = None,
        message: str | None = None,
    ) -> None:
        """Update progress fields. Only provided fields change."""
        with self._lock:
            if stage is not None:
                self._stage = stage
            if items_completed is not None:
                self._items_completed = items_completed
            if items_total is not None:
                self._items_total = items_total
            if message is not None:
                self._message = message

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the status API response."""
        with self._lock:
            return {
                "stage": self._stage,
                "items_completed": self._items_completed,
                "items_total": self._items_total,
                "message": self._message,
                "elapsed_seconds": round(
                    self.elapsed_seconds, 1,
                ),
            }
