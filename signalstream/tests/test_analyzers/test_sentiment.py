"""Tests for signalstream.analyzers.sentiment — per-post analysis with checkpointing."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from signalstream.analyzers.sentiment import SentimentAnalyzer, parse_sentiment_response
from signalstream.db.models import Post, SentimentResult
from signalstream.llm.providers.base import BaseProvider


_GOOD_RESPONSE = """PRIMARY_EMOTION: enthusiastic
SECONDARY_EMOTION: hopeful
EMOTION_INTENSITY: strong
SENTIMENT: positive
CONFIDENCE: certain
KEY_POINT: Users love the new performance improvements
EMOTIONAL_DRIVER: Faster build times directly improve developer productivity
SARCASM_DETECTED: false"""


_BAD_RESPONSE = """This is a post about Python. It seems generally positive.
I think the sentiment is good."""


def _make_post(post_id: str = "p1") -> Post:
    return Post(
        platform="reddit", id=post_id, author="user1",
        text="Amazing new feature release", title="Python 4.0 is here",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="python", engagement=100,
    )


class TestParseSentimentResponse:
    def test_parses_valid_response(self) -> None:
        result = parse_sentiment_response(_GOOD_RESPONSE)
        assert result is not None
        assert result["sentiment"] == "positive"
        assert result["emotion"] == "enthusiastic"
        assert result["sarcasm_detected"] is False

    def test_returns_none_for_unparseable(self) -> None:
        result = parse_sentiment_response(_BAD_RESPONSE)
        assert result is None or result.get("sentiment") == "unknown"

    def test_handles_empty_response(self) -> None:
        result = parse_sentiment_response("")
        assert result is None

    def test_handles_case_insensitive(self) -> None:
        response = _GOOD_RESPONSE.upper()
        result = parse_sentiment_response(response)
        assert result is not None
        assert result["sentiment"] == "positive"


class TestSentimentAnalyzer:
    def test_analyzes_single_post(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        assert len(results) == 1
        post, result = results[0]
        assert result.sentiment == "positive"
        assert result.emotion == "enthusiastic"

    def test_analyzes_multiple_posts(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(posts=posts, topic="Python")

        assert len(results) == 3

    def test_retries_on_parse_failure_then_succeeds(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.side_effect = [_BAD_RESPONSE, _GOOD_RESPONSE]

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        assert len(results) == 1
        assert mock_provider.complete.call_count == 2

    def test_skips_post_after_two_failures(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _BAD_RESPONSE

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        assert len(results) == 0

    def test_progress_callback_called(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE
        callback = MagicMock()

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        analyzer.analyze(
            posts=posts, topic="Python", progress_callback=callback,
        )

        assert callback.call_count == 3

    def test_partial_failure_returns_successes(self) -> None:
        """If 1 of 3 posts fails, the other 2 results are returned."""
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.side_effect = [
            _GOOD_RESPONSE,         # post 0: success
            _BAD_RESPONSE,           # post 1: retry
            _BAD_RESPONSE,           # post 1: retry again — skip
            _GOOD_RESPONSE,         # post 2: success
        ]

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(posts=posts, topic="Python")

        assert len(results) == 2
