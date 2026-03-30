"""Tests for signalstream.db.models."""
from __future__ import annotations

from datetime import datetime, timezone

from signalstream.db.models import (
    Comment,
    Job,
    JobStatistics,
    Post,
    SentimentResult,
    Theme,
)


class TestComment:
    def test_comment_creation(self) -> None:
        comment = Comment(
            id="abc123", body="Great post!", author="user1", score=42,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
        )
        assert comment.id == "abc123"
        assert comment.replies == []

    def test_comment_nested_replies(self) -> None:
        reply = Comment(
            id="r1", body="Thanks!", author="user2", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=2,
        )
        parent = Comment(
            id="c1", body="Interesting", author="user1", score=10,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
            replies=[reply],
        )
        assert len(parent.replies) == 1
        assert parent.replies[0].id == "r1"


class TestPost:
    def test_post_creation_with_defaults(self) -> None:
        post = Post(
            platform="reddit", id="post1", author="author1", text="Hello world",
            title="My Post", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://reddit.com/r/test/post1", community="test", engagement=100,
        )
        assert post.comments == []
        assert post.phrase_matches == []
        assert post.detected_language == ""
        assert post.detected_region == ""
        assert post.upvote_ratio is None
        assert post.flair is None
        assert post.is_crosspost is False
        assert post.crosspost_source is None

    def test_post_dedup_key(self) -> None:
        post = Post(
            platform="reddit", id="abc", author="u", text="t", title="T",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://example.com", community="r", engagement=0,
        )
        assert post.dedup_key == "reddit:abc"

    def test_post_with_comments(self) -> None:
        comment = Comment(
            id="c1", body="Nice", author="u2", score=3,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
        )
        post = Post(
            platform="reddit", id="p1", author="u1", text="content",
            title="Title", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://example.com", community="sub", engagement=10,
            comments=[comment],
        )
        assert len(post.comments) == 1


class TestSentimentResult:
    def test_sentiment_result_creation(self) -> None:
        result = SentimentResult(
            sentiment="positive", emotion="enthusiastic", confidence=0.95,
            key_point="Users love this feature", sarcasm_detected=False,
        )
        assert result.sentiment == "positive"
        assert result.secondary_emotion == "none"
        assert result.emotion_intensity == "moderate"
        assert result.emotional_driver == ""


class TestTheme:
    def test_theme_creation(self) -> None:
        theme = Theme(
            name="Battery Life", description="Users report rapid drain",
            percentage=45.0, post_count=18, sentiment_skew="negative",
            representative_quotes=["Battery dies in 2 hours"],
        )
        assert theme.percentage == 45.0
        assert len(theme.representative_quotes) == 1


class TestJob:
    def test_job_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        job = Job(id="job1", topic="Python", created_at=now, updated_at=now)
        assert job.status == "queued"
        assert job.phase == ""
        assert job.progress_pct == 0.0
        assert job.max_posts == 100
        assert job.time_range == "week"


class TestJobStatistics:
    def test_job_statistics_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        stats = JobStatistics(job_id="job1", created_at=now)
        assert stats.total_posts == 0
        assert stats.sentiment_positive == 0
        assert stats.dominant_emotion == ""
        assert stats.themes_json == "[]"
