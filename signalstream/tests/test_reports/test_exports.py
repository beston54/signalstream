"""Tests for JSON export."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _make_report_content():
    from signalstream.reports.builder import ReportContent

    return ReportContent(
        job_id="export-001",
        topic="Export Test",
        phrases=["test"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=3,
        skipped_count=0,
        statistics={
            "sentiment_distribution": {
                "positive": 2, "negative": 1,
            },
            "emotion_distribution": {"joy": 2, "anger": 1},
            "community_breakdown": {
                "r/test": {"positive": 2, "negative": 1},
            },
        },
        executive_snapshot={
            "total_posts": 3,
            "dominant_sentiment": "positive",
            "dominant_emotion": "joy",
            "avg_confidence": 0.82,
            "top_theme": "n/a",
            "sentiment_ratio": "2:1",
        },
        themes=[
            {
                "name": "Theme A",
                "description": "Desc A",
                "percentage": 60.0,
                "post_count": 2,
                "sentiment_skew": "positive",
                "representative_quotes": ["quote 1"],
            },
        ],
        charts={
            "sentiment": "data:image/png;base64,fakedata",
        },
        analyzed_posts=[
            {
                "post": {
                    "id": "p1",
                    "text": "Great stuff",
                    "community": "r/test",
                },
                "analysis": {
                    "sentiment": "positive",
                    "emotion": "joy",
                },
            },
        ],
        branding_footer=True,
    )


def test_export_json_string():
    """export_json() returns a valid JSON string."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed["job_id"] == "export-001"
    assert parsed["topic"] == "Export Test"


def test_export_json_excludes_charts_by_default():
    """Charts are excluded from JSON export by default."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content)
    parsed = json.loads(result)

    assert "charts" not in parsed


def test_export_json_includes_charts_when_requested():
    """Charts are included when include_charts=True."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content, include_charts=True)
    parsed = json.loads(result)

    assert "charts" in parsed
    assert "sentiment" in parsed["charts"]


def test_export_json_includes_statistics():
    """Statistics and themes are always present."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    parsed = json.loads(export_json(content))

    assert "statistics" in parsed
    assert "themes" in parsed
    assert "executive_snapshot" in parsed
    assert parsed["statistics"]["sentiment_distribution"]["positive"] == 2


def test_export_dict():
    """export_dict() returns a plain Python dict."""
    from signalstream.reports.exports import export_dict

    content = _make_report_content()
    result = export_dict(content)

    assert isinstance(result, dict)
    assert result["job_id"] == "export-001"
    assert "charts" not in result


def test_export_json_post_text_truncated():
    """Post text is truncated in export to limit file size."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    content.analyzed_posts = [
        {
            "post": {
                "id": "p1",
                "text": "x" * 5000,
                "community": "r/test",
            },
            "analysis": {"sentiment": "positive"},
        },
    ]

    parsed = json.loads(export_json(content))
    exported_text = parsed["analyzed_posts"][0]["post"]["text"]
    assert len(exported_text) <= 500
