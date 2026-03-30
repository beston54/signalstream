"""Tests for signalstream.analyzers.thematic — batch theme extraction with chunking."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from signalstream.analyzers.thematic import (
    ThematicAnalyzer,
    create_aggregation_summary,
    parse_theme_response,
)
from signalstream.db.models import Post, SentimentResult, Theme

_GOOD_THEME_RESPONSE = """MAJOR_THEMES:
1. Performance Improvements | Users praise significant speed gains in the new release
2. Pricing Concerns | Enterprise users worry about cost increases
3. Documentation Quality | Community requests better API documentation

POST_THEME_ASSIGNMENTS:
1: 1
2: 2
3: 3
4: 1,3
5: 2

NOVEL_IDEAS:
- Using the new async API for real-time data processing pipelines
- Community-maintained documentation as alternative to official docs

KEY_CRITIQUES:
- Backward compatibility issues with plugin ecosystem (frequency: frequent)
- Steep learning curve for new configuration system (frequency: occasional)

REGIONAL_PATTERNS:
- US: Focus on enterprise features and pricing
- EU: Emphasis on data privacy compliance in new features

SENTIMENT_SUMMARY:
Overall sentiment is mixed with medium confidence.
The community is excited about performance but worried about migration costs."""


def _make_analyzed_post(
    post_id: str, sentiment: str = "positive", key_point: str = "Good stuff",
    region: str = "global",
) -> tuple[Post, SentimentResult]:
    post = Post(
        platform="reddit", id=post_id, author="user1",
        text="Content", title="Title",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="test",
        engagement=10, detected_region=region,
    )
    result = SentimentResult(
        sentiment=sentiment, emotion="enthusiastic",
        confidence=0.8, key_point=key_point,
        sarcasm_detected=False,
    )
    return post, result


class TestCreateAggregationSummary:
    def test_creates_numbered_summaries(self) -> None:
        analyzed = [
            _make_analyzed_post("p1", "positive", "Users love it", "US"),
            _make_analyzed_post("p2", "negative", "Too expensive", "EU"),
        ]
        summaries = create_aggregation_summary(analyzed)
        assert len(summaries) == 2
        assert "[positive]" in summaries[0]
        assert "[US]" in summaries[0]
        assert "Users love it" in summaries[0]

    def test_samples_50_for_large_collections(self) -> None:
        analyzed = [
            _make_analyzed_post(f"p{i}", "neutral", f"Point {i}")
            for i in range(100)
        ]
        summaries = create_aggregation_summary(analyzed)
        assert len(summaries) == 50

    def test_deterministic_sampling(self) -> None:
        analyzed = [
            _make_analyzed_post(f"p{i}", "neutral", f"Point {i}")
            for i in range(100)
        ]
        summaries1 = create_aggregation_summary(analyzed)
        summaries2 = create_aggregation_summary(analyzed)
        assert summaries1 == summaries2


class TestParseThemeResponse:
    def test_parses_major_themes(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["major_themes"]) == 3
        assert themes["major_themes"][0]["theme"] == "Performance Improvements"

    def test_parses_novel_ideas(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["novel_ideas"]) >= 1

    def test_parses_key_critiques(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["key_critiques"]) >= 1

    def test_parses_sentiment_summary(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert themes["sentiment_summary"]["overall"] == "mixed"

    def test_handles_empty_response(self) -> None:
        themes = parse_theme_response("")
        assert themes["major_themes"] == []


class TestThematicAnalyzer:
    def test_analyzes_small_batch(self) -> None:
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [
            _make_analyzed_post(f"p{i}", "positive", f"Point {i}")
            for i in range(10)
        ]

        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="Python 4.0",
        )

        assert len(themes) >= 1
        assert mock_provider.complete.call_count == 1

    def test_chunks_large_collections(self) -> None:
        """Collections > 50 posts are chunked and consolidated (BOARD-011)."""
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [
            _make_analyzed_post(f"p{i}", "positive", f"Point {i}")
            for i in range(120)
        ]

        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="Python 4.0",
        )

        assert mock_provider.complete.call_count >= 2
        assert len(themes) >= 1

    def test_returns_theme_objects(self) -> None:
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [_make_analyzed_post("p1", "positive", "Good stuff")]
        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="test",
        )

        for theme in themes:
            assert isinstance(theme, Theme)
