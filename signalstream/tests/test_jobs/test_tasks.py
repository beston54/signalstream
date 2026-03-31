"""Tests for pipeline stage task wrappers with error handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from signalstream.jobs.state import (
    CancellationToken,
    CancelledError,
    JobProgress,
)


def test_collect_task_returns_posts():
    """collect_task calls the collector and returns posts."""
    from signalstream.jobs.tasks import collect_task

    mock_collector = MagicMock(
        return_value=[{"id": "1"}, {"id": "2"}],
    )
    progress = JobProgress()
    token = CancellationToken()

    result = collect_task(
        collector_fn=mock_collector,
        phrases=["test"],
        time_range="week",
        max_posts=50,
        progress=progress,
        cancellation_token=token,
    )

    assert len(result) == 2
    mock_collector.assert_called_once()


def test_collect_task_empty_raises():
    """collect_task raises TaskError with COLLECTOR_EMPTY."""
    from signalstream.jobs.tasks import TaskError, collect_task

    mock_collector = MagicMock(return_value=[])
    progress = JobProgress()
    token = CancellationToken()

    with pytest.raises(TaskError) as exc_info:
        collect_task(
            collector_fn=mock_collector,
            phrases=["obscure-topic"],
            time_range="week",
            max_posts=50,
            progress=progress,
            cancellation_token=token,
        )
    assert exc_info.value.error_code == "COLLECTOR_EMPTY"


def test_collect_task_cancelled():
    """collect_task respects cancellation token."""
    from signalstream.jobs.tasks import collect_task

    mock_collector = MagicMock(return_value=[{"id": "1"}])
    progress = JobProgress()
    token = CancellationToken()
    token.cancel()

    with pytest.raises(CancelledError):
        collect_task(
            collector_fn=mock_collector,
            phrases=["test"],
            time_range="week",
            max_posts=50,
            progress=progress,
            cancellation_token=token,
        )


def test_analyze_task_returns_results():
    """analyze_task calls the analyzer and returns results."""
    from signalstream.jobs.tasks import analyze_task

    posts = [MagicMock(), MagicMock(), MagicMock()]
    analyzed = [MagicMock(), MagicMock()]
    mock_analyzer = MagicMock(return_value=(analyzed, 1))

    progress = JobProgress()
    token = CancellationToken()
    mock_provider = MagicMock()

    result_posts, skipped = analyze_task(
        analyzer_fn=mock_analyzer,
        posts=posts,
        provider=mock_provider,
        progress=progress,
        cancellation_token=token,
    )

    assert len(result_posts) == 2
    assert skipped == 1


def test_analyze_task_provider_error():
    """analyze_task wraps provider errors into TaskError."""
    from signalstream.jobs.tasks import TaskError, analyze_task

    mock_analyzer = MagicMock(
        side_effect=ConnectionError("refused"),
    )
    progress = JobProgress()
    token = CancellationToken()

    with pytest.raises(TaskError) as exc_info:
        analyze_task(
            analyzer_fn=mock_analyzer,
            posts=[MagicMock()],
            provider=MagicMock(),
            progress=progress,
            cancellation_token=token,
        )
    assert exc_info.value.error_code == "PROVIDER_UNREACHABLE"


def test_theme_task_returns_themes():
    """theme_task calls the thematic analyzer and returns themes."""
    from signalstream.jobs.tasks import theme_task

    mock_thematic = MagicMock(
        return_value={"themes": [{"name": "Quality"}]},
    )
    progress = JobProgress()
    token = CancellationToken()

    result = theme_task(
        thematic_fn=mock_thematic,
        analyzed_posts=[MagicMock()],
        provider=MagicMock(),
        phrase="test query",
        progress=progress,
        cancellation_token=token,
    )

    assert "themes" in result
    mock_thematic.assert_called_once()


def test_report_task_returns_content():
    """report_task assembles report content via the builder."""
    from signalstream.jobs.tasks import report_task
    from signalstream.reports.builder import ReportContent

    progress = JobProgress()
    token = CancellationToken()

    result = report_task(
        job_id="task-test-001",
        topic="test",
        phrases=["test"],
        analyzed_posts=[
            {
                "post": {
                    "id": "1",
                    "community": "r/test",
                    "engagement": 5,
                },
                "analysis": {
                    "sentiment": "positive",
                    "emotion": "joy",
                    "confidence": 0.9,
                    "key_point": "Good",
                    "sarcasm_detected": False,
                },
            },
        ],
        themes=[],
        skipped_count=0,
        progress=progress,
        cancellation_token=token,
    )

    assert isinstance(result, ReportContent)
    assert result.job_id == "task-test-001"


def test_task_error_has_user_message():
    """TaskError includes both an error_code and a user-facing message."""
    from signalstream.jobs.tasks import TaskError

    err = TaskError(
        error_code="PROVIDER_AUTH_FAILED",
        message="Your API key appears to be invalid or expired.",
    )
    assert err.error_code == "PROVIDER_AUTH_FAILED"
    assert "invalid or expired" in str(err)
