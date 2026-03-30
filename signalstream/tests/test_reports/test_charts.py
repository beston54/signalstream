"""Tests for thread-safe matplotlib chart generation."""

import base64
import threading


def test_emotion_distribution_chart():
    """Emotion bar chart returns a valid base64 PNG data URI."""
    from signalstream.reports.charts import generate_emotion_chart

    emotions = {
        "joy": 15,
        "anger": 8,
        "fear": 5,
        "surprise": 3,
        "sadness": 2,
    }
    result = generate_emotion_chart(emotions)

    assert result.startswith("data:image/png;base64,")
    # Verify the base64 payload is decodable
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    # PNG magic bytes
    assert decoded[:4] == b"\x89PNG"


def test_emotion_chart_empty_input():
    """Empty emotion dict returns empty string, no crash."""
    from signalstream.reports.charts import generate_emotion_chart

    result = generate_emotion_chart({})
    assert result == ""


def test_emotion_chart_filters_zeros():
    """Zero-count emotions are excluded from the chart."""
    from signalstream.reports.charts import generate_emotion_chart

    emotions = {"joy": 10, "anger": 0, "fear": 0}
    result = generate_emotion_chart(emotions)
    assert result.startswith("data:image/png;base64,")


def test_sentiment_split_chart():
    """Sentiment donut chart returns valid PNG data URI."""
    from signalstream.reports.charts import generate_sentiment_chart

    sentiments = {"positive": 20, "negative": 8, "neutral": 12, "mixed": 3}
    result = generate_sentiment_chart(sentiments)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_sentiment_chart_empty():
    """Empty sentiment dict returns empty string."""
    from signalstream.reports.charts import generate_sentiment_chart

    assert generate_sentiment_chart({}) == ""


def test_theme_frequency_chart():
    """Theme frequency horizontal bar returns valid PNG."""
    from signalstream.reports.charts import generate_theme_chart

    themes = [
        {"name": "Product Quality", "percentage": 45.0, "post_count": 18},
        {"name": "Customer Service", "percentage": 30.0, "post_count": 12},
        {"name": "Pricing Concerns", "percentage": 15.0, "post_count": 6},
        {"name": "Feature Requests", "percentage": 10.0, "post_count": 4},
    ]
    result = generate_theme_chart(themes)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_theme_chart_empty():
    """Empty themes list returns empty string."""
    from signalstream.reports.charts import generate_theme_chart

    assert generate_theme_chart([]) == ""


def test_community_breakdown_chart():
    """Community breakdown grouped bar returns valid PNG."""
    from signalstream.reports.charts import generate_community_chart

    communities = {
        "r/python": {"positive": 10, "negative": 3, "neutral": 5},
        "r/programming": {"positive": 8, "negative": 6, "neutral": 4},
        "r/learnpython": {"positive": 12, "negative": 1, "neutral": 7},
    }
    result = generate_community_chart(communities)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_community_chart_empty():
    """Empty community dict returns empty string."""
    from signalstream.reports.charts import generate_community_chart

    assert generate_community_chart({}) == ""


def test_concurrent_chart_generation():
    """Multiple threads generating charts simultaneously must not crash or corrupt."""
    from signalstream.reports.charts import (
        generate_community_chart,
        generate_emotion_chart,
        generate_sentiment_chart,
        generate_theme_chart,
    )

    errors: list[Exception] = []

    def gen_emotion():
        try:
            r = generate_emotion_chart({"joy": 10, "anger": 5, "fear": 3})
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_sentiment():
        try:
            r = generate_sentiment_chart({"positive": 15, "negative": 5, "neutral": 10})
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_themes():
        try:
            r = generate_theme_chart([
                {"name": "Topic A", "percentage": 40.0, "post_count": 8},
                {"name": "Topic B", "percentage": 30.0, "post_count": 6},
            ])
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_community():
        try:
            r = generate_community_chart({
                "r/test": {"positive": 5, "negative": 2, "neutral": 3},
            })
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    threads = []
    # Run 3 rounds of all 4 chart types concurrently (12 threads)
    for _ in range(3):
        for fn in [gen_emotion, gen_sentiment, gen_themes, gen_community]:
            t = threading.Thread(target=fn)
            threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"Thread-safety errors: {errors}"


def test_generate_all_charts():
    """Convenience function returns dict of all chart data URIs."""
    from signalstream.reports.charts import generate_all_charts

    statistics = {
        "sentiment_distribution": {"positive": 20, "negative": 8, "neutral": 12},
        "emotion_distribution": {"joy": 15, "anger": 5, "surprise": 3},
        "community_breakdown": {
            "r/python": {"positive": 10, "negative": 3, "neutral": 5},
        },
    }
    themes = [
        {"name": "Quality", "percentage": 45.0, "post_count": 18},
        {"name": "Support", "percentage": 30.0, "post_count": 12},
    ]

    result = generate_all_charts(statistics, themes)

    assert isinstance(result, dict)
    assert "sentiment" in result
    assert "emotion" in result
    assert "themes" in result
    assert "community" in result
    for key, uri in result.items():
        assert uri.startswith("data:image/png;base64,"), f"{key} is not a valid data URI"


def test_generate_all_charts_partial_data():
    """Missing sections produce partial results, not crashes."""
    from signalstream.reports.charts import generate_all_charts

    statistics = {
        "sentiment_distribution": {"positive": 10, "negative": 5},
        # No emotion or community data
    }
    themes = []

    result = generate_all_charts(statistics, themes)
    assert isinstance(result, dict)
    assert "sentiment" in result
    # Missing sections should be absent, not empty strings
    assert "emotion" not in result or result.get("emotion") == ""
