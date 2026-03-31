"""
Per-stage task wrappers with error handling and progress reporting.

Each task wraps a pipeline stage with:
- Cancellation token checks
- Error translation to user-facing messages
- Progress updates
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from signalstream.jobs.state import (
    CancellationToken,
    CancelledError,
    JobProgress,
)
from signalstream.reports.builder import (
    ReportContent,
    build_report_content,
)

logger = logging.getLogger(__name__)


class TaskError(Exception):
    """Structured error from a pipeline stage."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


# -- Error classification helpers -------------------------------------

_CONNECTION_ERRORS = (
    ConnectionError, ConnectionRefusedError,
    ConnectionResetError, TimeoutError, OSError,
)


def _classify_provider_error(
    exc: Exception,
) -> tuple[str, str]:
    """Map a provider exception to (error_code, user_message)."""
    msg = str(exc).lower()

    if isinstance(exc, _CONNECTION_ERRORS) or "refused" in msg:
        return (
            "PROVIDER_UNREACHABLE",
            "Could not reach the LLM provider. "
            "Check your internet connection.",
        )

    if any(k in msg for k in ("401", "403", "auth", "invalid", "expired")):
        return (
            "PROVIDER_AUTH_FAILED",
            "Your API key appears to be invalid or expired.",
        )

    if "429" in msg or "rate" in msg:
        return (
            "PROVIDER_RATE_LIMITED",
            "Rate limited by the LLM provider. Retrying...",
        )

    if "context" in msg or ("token" in msg and "too" in msg):
        return (
            "PROVIDER_CONTEXT_EXCEEDED",
            "Content too large for the model. Try fewer posts.",
        )

    return ("PROVIDER_UNREACHABLE", f"LLM provider error: {exc}")


def _classify_collector_error(
    exc: Exception,
) -> tuple[str, str]:
    """Map a collector exception to (error_code, user_message)."""
    msg = str(exc).lower()

    if "429" in msg or "rate" in msg:
        return (
            "COLLECTOR_RATE_LIMITED",
            "Reddit is rate-limiting requests. Waiting...",
        )

    if "403" in msg or "blocked" in msg:
        return (
            "COLLECTOR_BLOCKED",
            "Reddit is not responding. Try again in a few minutes.",
        )

    return ("COLLECTOR_BLOCKED", f"Collection error: {exc}")


# -- Stage tasks ------------------------------------------------------


def collect_task(
    collector_fn: Callable[..., list],
    phrases: list[str],
    time_range: str,
    max_posts: int,
    progress: JobProgress,
    cancellation_token: CancellationToken,
    **collector_kwargs: Any,
) -> list:
    """Run the collection stage."""
    cancellation_token.check()
    progress.update(
        stage="COLLECTING", items_completed=0,
        items_total=0, message="Starting collection...",
    )

    try:
        posts = collector_fn(
            phrases=phrases,
            time_range=time_range,
            max_posts=max_posts,
            **collector_kwargs,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_collector_error(exc)
        raise TaskError(code, msg) from exc

    if not posts:
        raise TaskError(
            "COLLECTOR_EMPTY",
            f"No posts found for '{', '.join(phrases)}'. "
            "Try broader search terms or a longer time range.",
        )

    progress.update(
        items_completed=len(posts),
        items_total=len(posts),
        message=f"Collected {len(posts)} posts",
    )
    logger.info("Collection complete: %d posts", len(posts))
    return posts


def analyze_task(
    analyzer_fn: Callable[..., tuple[list, int]],
    posts: list,
    provider: Any,
    progress: JobProgress,
    cancellation_token: CancellationToken,
) -> tuple[list, int]:
    """Run the sentiment analysis stage."""
    cancellation_token.check()
    progress.update(
        stage="ANALYZING", items_completed=0,
        items_total=len(posts),
        message="Starting analysis...",
    )

    def _progress_callback(
        completed: int, total: int, current_id: str = "",
    ) -> None:
        progress.update(
            items_completed=completed,
            items_total=total,
            message=f"Analyzing post {completed}/{total}",
        )

    try:
        analyzed_posts, skipped = analyzer_fn(
            posts=posts,
            provider=provider,
            progress_callback=_progress_callback,
            cancellation_token=cancellation_token,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_provider_error(exc)
        raise TaskError(code, msg) from exc

    if skipped > 0:
        logger.warning(
            "Analysis partial: %d of %d posts skipped",
            skipped, len(posts),
        )

    progress.update(
        items_completed=len(analyzed_posts),
        message=(
            f"Analysis complete "
            f"({len(analyzed_posts)} of {len(posts)} posts)"
        ),
    )
    return analyzed_posts, skipped


def theme_task(
    thematic_fn: Callable[..., Any],
    analyzed_posts: list,
    provider: Any,
    phrase: str,
    progress: JobProgress,
    cancellation_token: CancellationToken,
) -> Any:
    """Run the thematic analysis stage."""
    cancellation_token.check()
    progress.update(
        stage="THEMING", items_completed=0,
        items_total=1, message="Extracting themes...",
    )

    try:
        result = thematic_fn(
            posts=analyzed_posts,
            provider=provider,
            phrase=phrase,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_provider_error(exc)
        raise TaskError(code, msg) from exc

    progress.update(
        items_completed=1,
        message="Theme extraction complete",
    )
    return result


def report_task(
    job_id: str,
    topic: str,
    phrases: list[str],
    analyzed_posts: list[dict],
    themes: list[dict],
    skipped_count: int,
    progress: JobProgress,
    cancellation_token: CancellationToken,
    branding_footer: bool = True,
) -> ReportContent:
    """Run the report generation stage."""
    cancellation_token.check()
    progress.update(
        stage="REPORTING", items_completed=0,
        items_total=1, message="Generating report...",
    )

    try:
        content = build_report_content(
            job_id=job_id,
            topic=topic,
            phrases=phrases,
            analyzed_posts=analyzed_posts,
            themes=themes,
            skipped_count=skipped_count,
            branding_footer=branding_footer,
        )
    except Exception as exc:
        raise TaskError(
            "REPORT_GENERATION_FAILED",
            f"Failed to generate report: {exc}",
        ) from exc

    progress.update(
        items_completed=1, message="Report ready",
    )
    return content
