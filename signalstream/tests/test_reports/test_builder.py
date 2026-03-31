"""Tests for report content assembly."""

from __future__ import annotations

from datetime import datetime, timezone


def _make_analyzed_post(
    post_id: str,
    sentiment: str = "positive",
    emotion: str = "joy",
    confidence: float = 0.85,
    community: str = "r/python",
    key_point: str = "Great discussion.",
    sarcasm_detected: bool = False,
) -> dict:
    """Helper to build a minimal analyzed post dict for testing."""
    return {
        "post": {
            "platform": "reddit",
            "id": post_id,
            "author": "test_user",
            "text": "Sample post text.",
            "title": "Sample Title",
            "timestamp": datetime(
                2026, 3, 15, tzinfo=timezone.utc,
            ).isoformat(),
            "url": f"https://reddit.com/r/python/comments/{post_id}",
            "community": community,
            "engagement": 42,
            "comments": [],
            "phrase_matches": ["python"],
        },
        "analysis": {
            "sentiment": sentiment,
            "emotion": emotion,
            "confidence": confidence,
            "key_point": key_point,
            "sarcasm_detected": sarcasm_detected,
        },
    }


def test_build_report_content_basic():
    """Builder produces a ReportContent with correct top-level fields."""
    from signalstream.reports.builder import (
        ReportContent,
        build_report_content,
    )

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "negative", "anger", community="r/python"),
        _make_analyzed_post("3", "positive", "surprise", community="r/programming"),
        _make_analyzed_post("4", "neutral", "trust", community="r/programming"),
    ]
    themes = [
        {
            "name": "Code Quality",
            "description": "Focus on code standards",
            "percentage": 50.0,
            "post_count": 2,
            "sentiment_skew": "positive",
            "representative_quotes": ["quote1"],
        },
        {
            "name": "Tooling",
            "description": "IDE and tool discussions",
            "percentage": 25.0,
            "post_count": 1,
            "sentiment_skew": "neutral",
            "representative_quotes": ["quote2"],
        },
    ]

    content = build_report_content(
        job_id="job-001",
        topic="Python sentiment",
        phrases=["python", "coding"],
        analyzed_posts=posts,
        themes=themes,
        skipped_count=1,
    )

    assert isinstance(content, ReportContent)
    assert content.job_id == "job-001"
    assert content.topic == "Python sentiment"
    assert content.total_posts == 4
    assert content.skipped_count == 1


def test_statistics_computation():
    """Statistics dict has correct sentiment and emotion distributions."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "positive", "joy", community="r/python"),
        _make_analyzed_post("3", "negative", "anger", community="r/python"),
        _make_analyzed_post(
            "4", "neutral", "trust", community="r/learnpython",
        ),
    ]

    content = build_report_content(
        job_id="job-002",
        topic="test",
        phrases=["test"],
        analyzed_posts=posts,
        themes=[],
    )

    stats = content.statistics
    assert stats["sentiment_distribution"]["positive"] == 2
    assert stats["sentiment_distribution"]["negative"] == 1
    assert stats["sentiment_distribution"]["neutral"] == 1
    assert stats["emotion_distribution"]["joy"] == 2
    assert stats["emotion_distribution"]["anger"] == 1
    assert stats["emotion_distribution"]["trust"] == 1
    assert "r/python" in stats["community_breakdown"]
    assert "r/learnpython" in stats["community_breakdown"]


def test_community_breakdown_sentiment_split():
    """Community breakdown includes per-community sentiment counts."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "negative", "anger", community="r/python"),
        _make_analyzed_post("3", "positive", "joy", community="r/rust"),
    ]

    content = build_report_content(
        job_id="job-003", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[],
    )

    python_breakdown = content.statistics["community_breakdown"]["r/python"]
    assert python_breakdown["positive"] == 1
    assert python_breakdown["negative"] == 1


def test_charts_are_generated():
    """ReportContent includes chart data URIs when data is present."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy"),
        _make_analyzed_post("2", "negative", "anger"),
    ]

    content = build_report_content(
        job_id="job-004", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[
            {
                "name": "Theme A",
                "description": "Desc",
                "percentage": 60.0,
                "post_count": 1,
                "sentiment_skew": "positive",
                "representative_quotes": [],
            },
        ],
    )

    assert content.charts.get("sentiment", "").startswith(
        "data:image/png;base64,",
    )
    assert content.charts.get("emotion", "").startswith(
        "data:image/png;base64,",
    )


def test_executive_snapshot():
    """Executive snapshot card data is computed correctly."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", confidence=0.9),
        _make_analyzed_post("2", "positive", "joy", confidence=0.8),
        _make_analyzed_post("3", "negative", "anger", confidence=0.7),
    ]

    content = build_report_content(
        job_id="job-005", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[],
    )

    snap = content.executive_snapshot
    assert snap["dominant_sentiment"] == "positive"
    assert snap["dominant_emotion"] == "joy"
    assert snap["total_posts"] == 3
    assert 0.0 <= snap["avg_confidence"] <= 1.0


def test_empty_posts_produces_empty_report():
    """Zero posts produces valid but empty ReportContent."""
    from signalstream.reports.builder import build_report_content

    content = build_report_content(
        job_id="job-006", topic="empty", phrases=["nothing"],
        analyzed_posts=[], themes=[],
    )

    assert content.total_posts == 0
    assert content.statistics["sentiment_distribution"] == {}
