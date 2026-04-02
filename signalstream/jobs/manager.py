"""
Job manager — thread pool, submit/cancel/status, graceful shutdown.

Manages the lifecycle of analysis jobs. Each job runs in a thread
from a bounded pool (max 2 by default).
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from signalstream.jobs.pipeline import (
    PipelineConfig,
    PipelineResult,
    run_pipeline,
)
from signalstream.jobs.state import (
    CancellationToken,
    JobProgress,
    JobState,
)

logger = logging.getLogger(__name__)


class _JobEntry:
    """Internal tracking for a submitted job."""

    __slots__ = (
        "job_id", "config", "provider",
        "collector_fn", "analyzer_fn", "thematic_fn",
        "cancellation_token", "progress", "future",
        "result", "state",
    )

    def __init__(
        self,
        job_id: str,
        config: PipelineConfig,
        provider: Any,
        collector_fn: Callable,
        analyzer_fn: Callable,
        thematic_fn: Callable,
    ):
        self.job_id = job_id
        self.config = config
        self.provider = provider
        self.collector_fn = collector_fn
        self.analyzer_fn = analyzer_fn
        self.thematic_fn = thematic_fn
        self.cancellation_token = CancellationToken()
        self.progress = JobProgress()
        self.future: Future | None = None
        self.result: PipelineResult | None = None
        self.state = JobState.PENDING


class JobManager:
    """Manages analysis job lifecycle with a bounded thread pool."""

    def __init__(
        self, db: Any, max_workers: int = 2,
    ) -> None:
        self._db = db
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="signalstream-job",
        )
        self._jobs: dict[str, _JobEntry] = {}
        self._lock = threading.Lock()
        self._shutdown = False

    def submit_job(
        self,
        topic: str,
        phrases: list[str],
        time_range: str,
        max_posts: int,
        provider: Any,
        collector_fn: Callable,
        analyzer_fn: Callable,
        thematic_fn: Callable,
        branding_footer: bool = True,
    ) -> str:
        """Submit a new analysis job to the thread pool."""
        if self._shutdown:
            raise RuntimeError(
                "Job manager is shutdown — cannot accept new jobs",
            )

        job_id = str(uuid.uuid4())
        config = PipelineConfig(
            job_id=job_id,
            topic=topic,
            phrases=phrases,
            time_range=time_range,
            max_posts=max_posts,
            branding_footer=branding_footer,
        )

        entry = _JobEntry(
            job_id=job_id,
            config=config,
            provider=provider,
            collector_fn=collector_fn,
            analyzer_fn=analyzer_fn,
            thematic_fn=thematic_fn,
        )

        with self._lock:
            self._jobs[job_id] = entry

        try:
            self._db.save_job({
                "job_id": job_id,
                "topic": topic,
                "phrases": phrases,
                "status": JobState.PENDING.value,
                "time_range": time_range,
                "max_posts": max_posts,
            })
        except Exception:
            logger.exception(
                "Failed to persist job metadata (non-fatal)",
            )

        future = self._pool.submit(self._run_job, entry)
        entry.future = future
        future.add_done_callback(
            lambda f: self._on_job_done(job_id, f),
        )

        logger.info(
            "Submitted job %s: topic='%s', phrases=%s",
            job_id, topic, phrases,
        )
        return job_id

    def get_status(
        self, job_id: str,
    ) -> dict[str, Any] | None:
        """Get current status of a job."""
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return None

        status = entry.progress.to_dict()
        status["state"] = entry.state.value
        status["job_id"] = job_id

        if entry.result and entry.result.error:
            status["error"] = entry.result.error
            status["error_code"] = entry.result.error_code

        return status

    def get_result(
        self, job_id: str,
    ) -> PipelineResult | None:
        """Get the final result of a completed job."""
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return None
        return entry.result

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running job."""
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return False

        entry.cancellation_token.cancel()
        logger.info(
            "Cancellation requested for job %s", job_id,
        )
        return True

    def shutdown(
        self, wait: bool = True, timeout: int = 30,
    ) -> None:
        """Graceful shutdown."""
        self._shutdown = True
        logger.info("Job manager shutdown initiated")

        with self._lock:
            for entry in self._jobs.values():
                terminal = (
                    JobState.COMPLETED,
                    JobState.FAILED,
                    JobState.CANCELLED,
                )
                if entry.state not in terminal:
                    entry.cancellation_token.cancel()

        self._pool.shutdown(wait=wait)
        logger.info("Job manager shutdown complete")

    def register_signals(self) -> None:
        """Register SIGTERM and SIGINT for graceful shutdown."""
        def _handler(signum: int, frame: Any) -> None:
            signame = signal.Signals(signum).name
            logger.info(
                "Received %s — initiating graceful shutdown",
                signame,
            )
            self.shutdown(wait=True, timeout=30)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    # -- Internal -------------------------------------------------

    def _run_job(self, entry: _JobEntry) -> PipelineResult:
        """Execute a job pipeline in a worker thread."""
        entry.state = JobState.COLLECTING

        def _state_callback(
            job_id: str, new_state: str, **kwargs: Any,
        ) -> None:
            try:
                state = JobState(new_state)
                entry.state = state
                self._db.update_job_status(
                    job_id, new_state, **kwargs,
                )
            except Exception:
                logger.exception(
                    "State callback DB update failed",
                )

        result = run_pipeline(
            config=entry.config,
            provider=entry.provider,
            collector_fn=entry.collector_fn,
            analyzer_fn=entry.analyzer_fn,
            thematic_fn=entry.thematic_fn,
            cancellation_token=entry.cancellation_token,
            progress=entry.progress,
            state_callback=_state_callback,
        )

        entry.result = result
        entry.state = result.final_state
        return result

    def _on_job_done(
        self, job_id: str, future: Future,
    ) -> None:
        """Callback when a job future completes."""
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return

        exc = future.exception()
        if exc is not None:
            logger.error(
                "Job %s raised unexpected exception: %s",
                job_id, exc,
            )
            entry.state = JobState.FAILED
            try:
                self._db.update_job_status(
                    job_id, JobState.FAILED.value,
                    error=str(exc),
                )
            except Exception:
                logger.exception(
                    "Failed to update job status in DB",
                )
        else:
            result = future.result()
            if result:
                logger.info(
                    "Job %s finished: %s",
                    job_id, result.final_state.value,
                )
