"""
Pipeline orchestration — stage sequencing with state transitions.

Sequences: COLLECTING -> ANALYZING -> THEMING -> REPORTING -> COMPLETED
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from signalstream.jobs.state import (
    CancellationToken,
    CancelledError,
    JobProgress,
    JobState,
)
from signalstream.jobs.tasks import (
    TaskError,
    analyze_task,
    collect_task,
    report_task,
    theme_task,
)
from signalstream.reports.builder import ReportContent

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    job_id: str
    topic: str
    phrases: list[str]
    time_range: str = "week"
    max_posts: int = 100
    branding_footer: bool = True


@dataclass
class PipelineResult:
    """Result of a pipeline run — success or failure."""

    final_state: JobState
    report_content: ReportContent | None = None
    error: str | None = None
    error_code: str | None = None
    failed_stage: str | None = None
    collected_posts: list | None = None
    analyzed_posts: list | None = None
    skipped_count: int = 0


def run_pipeline(
    config: PipelineConfig,
    provider: Any,
    collector_fn: Callable,
    analyzer_fn: Callable,
    thematic_fn: Callable,
    cancellation_token: CancellationToken,
    progress: JobProgress,
    state_callback: Callable[..., None] | None = None,
) -> PipelineResult:
    """Execute the full analysis pipeline.

    Sequences four stages:
    1. COLLECTING — fetch posts
    2. ANALYZING — per-post sentiment analysis
    3. THEMING — cross-post thematic extraction
    4. REPORTING — assemble report content with charts
    """
    collected_posts: list = []
    analyzed_posts: list = []
    skipped_count: int = 0
    themes: list = []

    def _transition(
        new_state: JobState, **kwargs: Any,
    ) -> None:
        if state_callback:
            try:
                state_callback(
                    config.job_id, new_state.value,
                    **kwargs,
                )
            except Exception:
                logger.exception(
                    "State callback error (non-fatal)",
                )

    try:
        # Stage 1: Collection
        _transition(JobState.COLLECTING)
        collected_posts = collect_task(
            collector_fn=collector_fn,
            phrases=config.phrases,
            time_range=config.time_range,
            max_posts=config.max_posts,
            progress=progress,
            cancellation_token=cancellation_token,
        )

        # Stage 2: Analysis
        _transition(JobState.ANALYZING)
        analyzed_posts, skipped_count = analyze_task(
            analyzer_fn=analyzer_fn,
            posts=collected_posts,
            provider=provider,
            progress=progress,
            cancellation_token=cancellation_token,
        )

        # Stage 3: Thematic extraction
        _transition(JobState.THEMING)
        thematic_result = theme_task(
            thematic_fn=thematic_fn,
            analyzed_posts=analyzed_posts,
            provider=provider,
            phrase=(
                config.phrases[0]
                if config.phrases else config.topic
            ),
            progress=progress,
            cancellation_token=cancellation_token,
        )

        if isinstance(thematic_result, dict):
            themes = thematic_result.get("themes", [])
        elif hasattr(thematic_result, "themes"):
            themes = thematic_result.themes
        else:
            themes = []

        # Stage 4: Report generation
        _transition(JobState.REPORTING)
        report_content = report_task(
            job_id=config.job_id,
            topic=config.topic,
            phrases=config.phrases,
            analyzed_posts=analyzed_posts,
            themes=themes,
            skipped_count=skipped_count,
            progress=progress,
            cancellation_token=cancellation_token,
            branding_footer=config.branding_footer,
        )

        _transition(JobState.COMPLETED)
        return PipelineResult(
            final_state=JobState.COMPLETED,
            report_content=report_content,
            collected_posts=collected_posts,
            analyzed_posts=analyzed_posts,
            skipped_count=skipped_count,
        )

    except CancelledError:
        _transition(JobState.CANCELLED)
        logger.info(
            "Pipeline cancelled for job %s", config.job_id,
        )
        return PipelineResult(
            final_state=JobState.CANCELLED,
            collected_posts=(
                collected_posts if collected_posts else None
            ),
            analyzed_posts=(
                analyzed_posts if analyzed_posts else None
            ),
            skipped_count=skipped_count,
        )

    except TaskError as exc:
        failed_stage = progress.stage or "UNKNOWN"
        _transition(
            JobState.FAILED,
            error_code=exc.error_code, error=str(exc),
        )
        logger.error(
            "Pipeline failed at %s: [%s] %s",
            failed_stage, exc.error_code, exc,
        )
        return PipelineResult(
            final_state=JobState.FAILED,
            error=str(exc),
            error_code=exc.error_code,
            failed_stage=failed_stage,
            collected_posts=(
                collected_posts if collected_posts else None
            ),
            analyzed_posts=(
                analyzed_posts if analyzed_posts else None
            ),
            skipped_count=skipped_count,
        )

    except Exception as exc:
        failed_stage = progress.stage or "UNKNOWN"
        _transition(
            JobState.FAILED,
            error_code="INTERNAL_ERROR", error=str(exc),
        )
        logger.exception(
            "Unexpected pipeline error at %s", failed_stage,
        )
        return PipelineResult(
            final_state=JobState.FAILED,
            error=f"Unexpected error: {exc}",
            error_code="INTERNAL_ERROR",
            failed_stage=failed_stage,
            collected_posts=(
                collected_posts if collected_posts else None
            ),
            analyzed_posts=(
                analyzed_posts if analyzed_posts else None
            ),
            skipped_count=skipped_count,
        )
