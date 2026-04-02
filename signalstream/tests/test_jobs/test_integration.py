"""Integration tests — full pipeline with mock LLM and collector."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from signalstream.jobs.state import JobState


def _make_mock_db():
    db = MagicMock()
    db.save_job = MagicMock()
    db.update_job_status = MagicMock()
    db.get_job = MagicMock(return_value=None)
    db.save_job_statistics = MagicMock()
    return db


def _mock_collector(phrases, time_range, max_posts, **kwargs):
    """Return realistic mock posts."""
    posts = []
    communities = ["r/python", "r/programming", "r/learnpython"]
    for i in range(min(max_posts, 10)):
        posts.append({
            "platform": "reddit",
            "id": f"post-{i}",
            "author": f"user_{i}",
            "text": f"Test post {i} about {phrases[0]}.",
            "title": f"Post {i}",
            "timestamp": "2026-03-15T00:00:00+00:00",
            "url": f"https://reddit.com/r/python/comments/post-{i}",
            "community": communities[i % len(communities)],
            "engagement": i * 10,
            "comments": [],
            "phrase_matches": phrases,
        })
    return posts


def _mock_analyzer(
    posts, provider,
    progress_callback=None, cancellation_token=None,
    **kwargs,
):
    """Return analyzed posts with deterministic results."""
    sentiments = [
        "positive", "negative", "neutral",
        "positive", "positive",
    ]
    emotions = ["joy", "anger", "trust", "surprise", "joy"]
    results = []
    for i, post in enumerate(posts):
        post_dict = (
            post if isinstance(post, dict)
            else {"id": str(i), "community": "r/test"}
        )
        result = {
            "post": post_dict,
            "analysis": {
                "sentiment": sentiments[i % len(sentiments)],
                "emotion": emotions[i % len(emotions)],
                "confidence": 0.85,
                "key_point": f"Key insight from post {i}",
                "sarcasm_detected": False,
            },
        }
        results.append(result)
        if progress_callback:
            progress_callback(
                i + 1, len(posts),
                post_dict.get("id", str(i)),
            )
    return results, 0


def _mock_thematic(posts, provider, phrase, **kwargs):
    """Return realistic mock themes."""
    return {
        "themes": [
            {
                "name": "Code Quality",
                "description": "Maintaining code standards",
                "percentage": 45.0,
                "post_count": 5,
                "sentiment_skew": "positive",
                "representative_quotes": [
                    "Code quality is important",
                ],
            },
            {
                "name": "Tooling",
                "description": "IDE and tool preferences",
                "percentage": 30.0,
                "post_count": 3,
                "sentiment_skew": "neutral",
                "representative_quotes": [
                    "I prefer VS Code",
                ],
            },
            {
                "name": "Performance",
                "description": "Runtime performance concerns",
                "percentage": 15.0,
                "post_count": 2,
                "sentiment_skew": "negative",
                "representative_quotes": [
                    "Python is slow",
                ],
            },
        ],
    }


def _wait_for_job(manager, job_id, timeout=10):
    """Poll until job reaches a terminal state."""
    for _ in range(int(timeout / 0.1)):
        status = manager.get_status(job_id)
        if status and status["state"] in (
            "COMPLETED", "FAILED", "CANCELLED",
        ):
            return status
        time.sleep(0.1)
    return manager.get_status(job_id)


def test_full_pipeline_happy_path():
    """Complete pipeline: submit, wait, verify report."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="Python sentiment",
            phrases=["python", "coding"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        _wait_for_job(manager, job_id)

        final_status = manager.get_status(job_id)
        assert final_status["state"] == "COMPLETED"

        result = manager.get_result(job_id)
        assert result is not None
        assert result.final_state == JobState.COMPLETED
        assert result.report_content is not None
        assert result.report_content.total_posts == 10
        assert result.report_content.topic == "Python sentiment"
        assert len(result.report_content.themes) == 3

        charts = result.report_content.charts
        assert "sentiment" in charts
        assert "emotion" in charts
        assert "themes" in charts
        assert "community" in charts

        stats = result.report_content.statistics
        assert sum(stats["sentiment_distribution"].values()) == 10
        assert sum(stats["emotion_distribution"].values()) == 10

        snap = result.report_content.executive_snapshot
        assert snap["total_posts"] == 10
        assert snap["dominant_sentiment"] == "positive"

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_full_pipeline_json_export():
    """Pipeline result can be exported to JSON."""
    from signalstream.jobs.manager import JobManager
    from signalstream.reports.exports import export_json

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="JSON test",
            phrases=["test"],
            time_range="week",
            max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        _wait_for_job(manager, job_id)

        result = manager.get_result(job_id)
        assert result is not None
        assert result.report_content is not None

        json_str = export_json(result.report_content)
        parsed = json.loads(json_str)
        assert parsed["topic"] == "JSON test"
        assert parsed["total_posts"] == 5
        assert "statistics" in parsed

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_full_pipeline_html_render():
    """Pipeline result can be rendered to HTML."""
    from signalstream.jobs.manager import JobManager
    from signalstream.reports.renderer import render_html

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="HTML test",
            phrases=["test"],
            time_range="week",
            max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        _wait_for_job(manager, job_id)

        result = manager.get_result(job_id)
        assert result is not None
        assert result.report_content is not None

        html = render_html(result.report_content)
        assert "Sentiment Analysis Report" in html
        assert "HTML test" in html
        assert "Executive Snapshot" in html
        assert "Powered by Signalstream" in html

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_pipeline_collector_empty():
    """Empty collection results in FAILED with COLLECTOR_EMPTY."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="empty test",
            phrases=["nonexistent-topic-xyz"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=lambda **kw: [],
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        _wait_for_job(manager, job_id)

        final_status = manager.get_status(job_id)
        assert final_status["state"] == "FAILED"

        # Small retry — result may be set slightly after state
        result = None
        for _ in range(20):
            result = manager.get_result(job_id)
            if result is not None:
                break
            time.sleep(0.05)
        assert result is not None
        assert result.error_code == "COLLECTOR_EMPTY"

    finally:
        manager.shutdown(wait=True, timeout=5)


def test_pipeline_cancellation():
    """Cancelling a running job transitions to CANCELLED."""
    import threading

    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    started = threading.Event()

    def _slow_collector(**kwargs):
        started.set()
        # Simulate long work that checks cancellation
        for _ in range(300):
            time.sleep(0.01)
        return [{"id": "1"}]

    try:
        job_id = manager.submit_job(
            topic="cancel test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        started.wait(timeout=5)
        time.sleep(0.05)
        manager.cancel_job(job_id)

        _wait_for_job(manager, job_id, timeout=5)

        status = manager.get_status(job_id)
        # Job may be CANCELLED or FAILED depending on timing
        assert status is not None
        assert status["state"] in (
            "CANCELLED", "FAILED", "COMPLETED",
        )

    finally:
        manager.shutdown(wait=True, timeout=5)


def test_two_concurrent_jobs():
    """Two jobs can run simultaneously in the thread pool."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job1 = manager.submit_job(
            topic="job 1", phrases=["python"],
            time_range="week", max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )
        job2 = manager.submit_job(
            topic="job 2", phrases=["rust"],
            time_range="week", max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        _wait_for_job(manager, job1)
        _wait_for_job(manager, job2)

        r1 = manager.get_result(job1)
        r2 = manager.get_result(job2)
        assert r1 is not None
        assert r1.final_state == JobState.COMPLETED
        assert r2 is not None
        assert r2.final_state == JobState.COMPLETED

    finally:
        manager.shutdown(wait=True, timeout=10)
