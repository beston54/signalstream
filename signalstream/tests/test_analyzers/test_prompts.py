"""Tests for signalstream.analyzers.prompts."""
from __future__ import annotations

from datetime import datetime, timezone

from signalstream.analyzers.prompts import (
    build_sentiment_prompt,
    build_sentiment_retry_prompt,
    build_thematic_prompt,
)
from signalstream.db.models import Comment, Post


def _make_post(**overrides) -> Post:
    defaults = dict(
        platform="reddit", id="p1", author="user1",
        text="I really love this new feature. It works perfectly.",
        title="Amazing new release",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="python",
        engagement=100, detected_region="global",
        detected_language="en",
    )
    defaults.update(overrides)
    return Post(**defaults)


class TestBuildSentimentPrompt:
    def test_includes_topic(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="Python 4.0")
        combined = " ".join(m["content"] for m in messages)
        assert "Python 4.0" in combined

    def test_includes_title_and_content(self) -> None:
        post = _make_post(title="Great Release", text="Love the new features")
        messages = build_sentiment_prompt(post, topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "Great Release" in combined
        assert "Love the new features" in combined

    def test_has_system_and_user_messages(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="test")
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_includes_community_and_region(self) -> None:
        post = _make_post(community="machinelearning", detected_region="US")
        messages = build_sentiment_prompt(post, topic="ML")
        combined = " ".join(m["content"] for m in messages)
        assert "machinelearning" in combined
        assert "US" in combined

    def test_includes_thread_context_with_comments(self) -> None:
        comment = Comment(
            id="c1", body="I agree, great feature!",
            author="u2", score=10,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1,
        )
        post = _make_post(comments=[comment])
        messages = build_sentiment_prompt(post, topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "agree" in combined

    def test_user_content_wrapped_in_delimiters(self) -> None:
        """User content is wrapped in delimiters for prompt injection defense."""
        messages = build_sentiment_prompt(_make_post(), topic="test")
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "<user_post>" in user_msg["content"]
        assert "</user_post>" in user_msg["content"]

    def test_output_format_specified(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "SENTIMENT:" in combined or "sentiment:" in combined.lower()
        assert "PRIMARY_EMOTION:" in combined or "primary_emotion:" in combined.lower()


class TestBuildThematicPrompt:
    def test_includes_post_summaries(self) -> None:
        summaries = [
            "1. [positive] [US] Users love the performance improvements",
            "2. [negative] [EU] Pricing concerns raised by enterprise users",
        ]
        messages = build_thematic_prompt(
            phrase="Python 4.0", summaries=summaries, post_count=2,
        )
        combined = " ".join(m["content"] for m in messages)
        assert "performance improvements" in combined
        assert "Pricing concerns" in combined

    def test_includes_expected_sections(self) -> None:
        messages = build_thematic_prompt(
            phrase="test", summaries=["1. [positive] [US] Good stuff"], post_count=1,
        )
        combined = " ".join(m["content"] for m in messages)
        assert "MAJOR_THEMES" in combined
        assert "NOVEL_IDEAS" in combined
        assert "KEY_CRITIQUES" in combined
        assert "REGIONAL_PATTERNS" in combined
        assert "SENTIMENT_SUMMARY" in combined


class TestBuildSentimentRetryPrompt:
    def test_retry_prompt_is_stricter(self) -> None:
        messages = build_sentiment_retry_prompt(
            original_response="Some malformed output that didn't parse",
            topic="test",
        )
        combined = " ".join(m["content"] for m in messages)
        assert "EXACTLY" in combined or "exactly" in combined.lower()
