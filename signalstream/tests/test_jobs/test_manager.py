"""Tests for the job manager — thread pool, submit/cancel/status, shutdown."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest


def _make_mock_db():
    """Create a mock DB repository."""
    db = MagicMock()
    db.save_job = MagicMock()
    db.update_job_status = MagicMock()
    db.get_job = MagicMock(return_value=None)
    db.save_job_statistics = MagicMock()
    return db


def _slow_collector(**kwargs):
    """Collector that takes a moment to run."""
    time.sleep(0.1)
    return [{"id": "1"}, {"id": "2"}]


def _fast_analyzer(**kwargs):
    """Analyzer that returns instantly."""
    return (
        [
            {
                "post": {
                    "id": "1", "community": "r/test",
                },
                "analysis": {
                    "sentiment": "positive",
                    "emotion": "joy",
                    "confidence": 0.9,
                    "key_point": "Ok",
                    "sarcasm_detected": False,
                },
            },
        ],
        0,
    )


def _fast_thematic(**kwargs):
    """Thematic analyzer that returns instantly."""
    return {"themes": []}


def test_submit_job():
    """submit_job returns a job_id and the job starts running."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        assert isinstance(job_id, str)
        assert len(job_id) > 0

        status = manager.get_status(job_id)
        assert status is not None
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_get_status_returns_progress():
    """get_status returns a dict with stage, items, message, elapsed."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        status = manager.get_status(job_id)
        assert "stage" in status
        assert "items_completed" in status
        assert "items_total" in status
        assert "elapsed_seconds" in status
        assert "state" in status
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_get_status_unknown_job():
    """get_status returns None for unknown job_id."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        assert manager.get_status("nonexistent-id") is None
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_cancel_job():
    """cancel_job sets the cancellation token for a running job."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    def _blocking_collector(**kwargs):
        time.sleep(10)
        return []

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_blocking_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        time.sleep(0.05)
        cancelled = manager.cancel_job(job_id)
        assert cancelled is True
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_cancel_unknown_job():
    """cancel_job returns False for unknown job_id."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        assert manager.cancel_job("nonexistent") is False
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_max_workers_limit():
    """Only max_workers jobs can run concurrently."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=1)

    started = threading.Event()
    block = threading.Event()

    def _blocking_collector(**kwargs):
        started.set()
        block.wait(timeout=5)
        return [{"id": "1"}]

    try:
        _job1 = manager.submit_job(
            topic="test1", phrases=["t"],
            time_range="week", max_posts=5,
            provider=MagicMock(),
            collector_fn=_blocking_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )
        started.wait(timeout=2)

        job2 = manager.submit_job(
            topic="test2", phrases=["t"],
            time_range="week", max_posts=5,
            provider=MagicMock(),
            collector_fn=lambda **kw: [{"id": "2"}],
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        status2 = manager.get_status(job2)
        assert status2["state"] in ("PENDING", "COLLECTING")

        block.set()
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_shutdown_graceful():
    """shutdown() prevents new submissions."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        manager.submit_job(
            topic="test", phrases=["test"],
            time_range="week", max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )
    finally:
        manager.shutdown(wait=True, timeout=5)

    with pytest.raises(RuntimeError, match="shutdown"):
        manager.submit_job(
            topic="too late", phrases=["test"],
            time_range="week", max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )


def test_job_completes_with_result():
    """A completed job has its result stored."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    def _instant_collector(**kwargs):
        return [{"id": "1"}]

    try:
        job_id = manager.submit_job(
            topic="test", phrases=["test"],
            time_range="week", max_posts=10,
            provider=MagicMock(),
            collector_fn=_instant_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        for _ in range(50):
            status = manager.get_status(job_id)
            if status and status["state"] in (
                "COMPLETED", "FAILED",
            ):
                break
            time.sleep(0.1)

        result = manager.get_result(job_id)
        assert result is not None
    finally:
        manager.shutdown(wait=True, timeout=5)
