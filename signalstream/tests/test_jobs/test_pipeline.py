"""Tests for pipeline orchestration — stage sequencing, error handling."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from signalstream.jobs.state import (
    CancellationToken,
    CancelledError,
    JobProgress,
    JobState,
)


@dataclass
class _FakePost:
    id: str
    community: str = "r/test"


def _make_pipeline_config():
    """Build a minimal PipelineConfig for testing."""
    from signalstream.jobs.pipeline import PipelineConfig

    return PipelineConfig(
        job_id="pipe-001",
        topic="test topic",
        phrases=["test"],
        time_range="week",
        max_posts=50,
    )


def _mock_stages():
    """Create mocked stage functions with realistic data."""
    collected = [
        _FakePost(id="1"),
        _FakePost(id="2"),
        _FakePost(id="3"),
    ]
    analyzed = [
        {
            "post": {"id": "1", "community": "r/test"},
            "analysis": {
                "sentiment": "positive", "emotion": "joy",
                "confidence": 0.9, "key_point": "Good",
                "sarcasm_detected": False,
            },
        },
        {
            "post": {"id": "2", "community": "r/test"},
            "analysis": {
                "sentiment": "negative", "emotion": "anger",
                "confidence": 0.8, "key_point": "Bad",
                "sarcasm_detected": False,
            },
        },
    ]
    themes = [
        {
            "name": "Quality", "description": "Desc",
            "percentage": 50.0, "post_count": 1,
            "sentiment_skew": "positive",
            "representative_quotes": [],
        },
    ]

    collector_fn = MagicMock(return_value=collected)
    analyzer_fn = MagicMock(return_value=(analyzed, 1))
    thematic_fn = MagicMock(
        return_value={"themes": themes},
    )

    return (
        collector_fn, analyzer_fn, thematic_fn,
        analyzed, themes,
    )


def test_pipeline_happy_path():
    """Full pipeline runs all 4 stages and returns COMPLETED."""
    from signalstream.jobs.pipeline import (
        PipelineResult,
        run_pipeline,
    )

    config = _make_pipeline_config()
    collector_fn, analyzer_fn, thematic_fn, _, _ = _mock_stages()
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=thematic_fn,
        cancellation_token=token,
        progress=progress,
    )

    assert isinstance(result, PipelineResult)
    assert result.final_state == JobState.COMPLETED
    assert result.report_content is not None
    assert result.error is None
    collector_fn.assert_called_once()
    analyzer_fn.assert_called_once()
    thematic_fn.assert_called_once()


def test_pipeline_collection_failure():
    """Pipeline fails at collection with structured error."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn = MagicMock(return_value=[])
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=MagicMock(),
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.FAILED
    assert result.error_code == "COLLECTOR_EMPTY"
    assert result.report_content is None


def test_pipeline_analysis_failure():
    """Pipeline fails at analysis stage."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn = MagicMock(
        return_value=[_FakePost(id="1")],
    )
    analyzer_fn = MagicMock(
        side_effect=ConnectionError("refused"),
    )
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.FAILED
    assert result.failed_stage == "ANALYZING"


def test_pipeline_cancellation_mid_analysis():
    """Pipeline cancellation preserves partial results."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn = MagicMock(
        return_value=[_FakePost(id="1")],
    )

    def _cancel_analyzer(**kwargs):
        raise CancelledError("Job cancelled")

    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=_cancel_analyzer,
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.CANCELLED


def test_pipeline_state_callback():
    """Pipeline calls state_callback on each transition."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn, analyzer_fn, thematic_fn, _, _ = _mock_stages()
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()
    state_changes: list[str] = []

    def on_state_change(
        job_id: str, new_state: str, **kwargs,
    ):
        state_changes.append(new_state)

    run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=thematic_fn,
        cancellation_token=token,
        progress=progress,
        state_callback=on_state_change,
    )

    assert "COLLECTING" in state_changes
    assert "ANALYZING" in state_changes
    assert "THEMING" in state_changes
    assert "REPORTING" in state_changes
    assert "COMPLETED" in state_changes
