"""Tests for job state machine, cancellation, and progress reporting."""

from __future__ import annotations

import threading
import time

import pytest


def test_job_state_enum():
    """JobState has all required states."""
    from signalstream.jobs.state import JobState

    assert hasattr(JobState, "PENDING")
    assert hasattr(JobState, "COLLECTING")
    assert hasattr(JobState, "ANALYZING")
    assert hasattr(JobState, "THEMING")
    assert hasattr(JobState, "REPORTING")
    assert hasattr(JobState, "COMPLETED")
    assert hasattr(JobState, "FAILED")
    assert hasattr(JobState, "CANCELLED")


def test_valid_transitions():
    """State transitions follow the defined state machine."""
    from signalstream.jobs.state import JobState, is_valid_transition

    # Happy path
    assert is_valid_transition(JobState.PENDING, JobState.COLLECTING)
    assert is_valid_transition(JobState.COLLECTING, JobState.ANALYZING)
    assert is_valid_transition(JobState.ANALYZING, JobState.THEMING)
    assert is_valid_transition(JobState.THEMING, JobState.REPORTING)
    assert is_valid_transition(JobState.REPORTING, JobState.COMPLETED)

    # Any state can fail
    for state in [JobState.COLLECTING, JobState.ANALYZING, JobState.THEMING, JobState.REPORTING]:
        assert is_valid_transition(state, JobState.FAILED)

    # Any running state can be cancelled
    for state in [JobState.COLLECTING, JobState.ANALYZING, JobState.THEMING, JobState.REPORTING]:
        assert is_valid_transition(state, JobState.CANCELLED)


def test_invalid_transitions():
    """Invalid state transitions are rejected."""
    from signalstream.jobs.state import JobState, is_valid_transition

    # Cannot go backwards
    assert not is_valid_transition(JobState.ANALYZING, JobState.COLLECTING)
    # Cannot transition from terminal states
    assert not is_valid_transition(JobState.COMPLETED, JobState.COLLECTING)
    assert not is_valid_transition(JobState.FAILED, JobState.COLLECTING)
    # Cannot skip states
    assert not is_valid_transition(JobState.PENDING, JobState.ANALYZING)


def test_cancellation_token_starts_unset():
    """CancellationToken starts in non-cancelled state."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    assert not token.is_cancelled


def test_cancellation_token_cancel():
    """Calling cancel() makes is_cancelled return True."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled


def test_cancellation_token_check_raises():
    """check() raises CancelledError when token is cancelled."""
    from signalstream.jobs.state import CancellationToken, CancelledError

    token = CancellationToken()
    token.check()  # Should not raise

    token.cancel()
    with pytest.raises(CancelledError):
        token.check()


def test_cancellation_token_thread_safe():
    """CancellationToken works across threads."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    saw_cancellation = threading.Event()

    def worker():
        while not token.is_cancelled:
            time.sleep(0.01)
        saw_cancellation.set()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    token.cancel()
    t.join(timeout=2)

    assert saw_cancellation.is_set()


def test_job_progress():
    """JobProgress tracks stage, counts, and message."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    assert progress.stage == ""
    assert progress.items_completed == 0
    assert progress.items_total == 0

    progress.update(
        stage="ANALYZING", items_completed=5,
        items_total=20, message="Analyzing post 5/20",
    )
    assert progress.stage == "ANALYZING"
    assert progress.items_completed == 5
    assert progress.items_total == 20
    assert progress.message == "Analyzing post 5/20"


def test_job_progress_elapsed():
    """JobProgress reports elapsed seconds since creation."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    time.sleep(0.05)
    assert progress.elapsed_seconds >= 0.04


def test_job_progress_to_dict():
    """JobProgress serializes to a status dict for API responses."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    progress.update(
        stage="COLLECTING", items_completed=3,
        items_total=10, message="Collecting...",
    )

    d = progress.to_dict()
    assert d["stage"] == "COLLECTING"
    assert d["items_completed"] == 3
    assert d["items_total"] == 10
    assert d["message"] == "Collecting..."
    assert "elapsed_seconds" in d
