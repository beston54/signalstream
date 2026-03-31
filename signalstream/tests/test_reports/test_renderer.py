"""Tests for PDF renderer with SSRF protection (BOARD-002)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


def _make_report_content():
    """Build a minimal ReportContent for renderer tests."""
    from signalstream.reports.builder import ReportContent

    return ReportContent(
        job_id="test-001",
        topic="Test Topic",
        phrases=["test"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=5,
        skipped_count=0,
        statistics={
            "sentiment_distribution": {
                "positive": 3, "negative": 2,
            },
            "emotion_distribution": {"joy": 3, "anger": 2},
            "community_breakdown": {
                "r/test": {"positive": 3, "negative": 2},
            },
        },
        executive_snapshot={
            "total_posts": 5,
            "dominant_sentiment": "positive",
            "dominant_emotion": "joy",
            "avg_confidence": 0.85,
            "top_theme": "n/a",
            "sentiment_ratio": "3:2",
        },
        themes=[],
        charts={},
        analyzed_posts=[],
        branding_footer=True,
    )


def test_pdf_available_flag():
    """PDF_AVAILABLE is a boolean reflecting whether weasyprint is importable."""
    from signalstream.reports.renderer import PDF_AVAILABLE

    assert isinstance(PDF_AVAILABLE, bool)


def test_render_html_string():
    """render_html() returns an HTML string regardless of WeasyPrint availability."""
    from signalstream.reports.renderer import render_html

    content = _make_report_content()
    html = render_html(content)

    assert isinstance(html, str)
    assert "Test Topic" in html
    assert "Sentiment Analysis Report" in html
    assert "Powered by Signalstream" in html


def test_render_html_no_branding():
    """Branding footer is omitted when branding_footer=False."""
    from signalstream.reports.renderer import render_html

    content = _make_report_content()
    content.branding_footer = False
    html = render_html(content)

    assert "Powered by Signalstream" not in html


def test_safe_url_fetcher_allows_data_uris():
    """data: URIs are passed through by the safe url_fetcher."""
    from signalstream.reports.renderer import _safe_url_fetcher

    data_uri = "data:image/png;base64,iVBORw0KGgo="
    result = _safe_url_fetcher(data_uri)
    assert isinstance(result, dict)


def test_safe_url_fetcher_blocks_http():
    """HTTP URLs are blocked by the safe url_fetcher."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("http://example.com/evil.css")


def test_safe_url_fetcher_blocks_https():
    """HTTPS URLs are blocked."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("https://cdn.example.com/styles.css")


def test_safe_url_fetcher_blocks_file():
    """file:// URLs are blocked."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("file:///etc/passwd")


def test_safe_url_fetcher_blocks_ftp():
    """ftp:// URLs are blocked."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("ftp://internal.server/data")


def test_render_pdf_when_available():
    """render_pdf() returns bytes when WeasyPrint is installed."""
    from signalstream.reports import renderer

    if not renderer.PDF_AVAILABLE:
        pytest.skip("WeasyPrint not installed")

    content = _make_report_content()
    pdf_bytes = renderer.render_pdf(content)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_pdf_when_unavailable():
    """render_pdf() raises RuntimeError when WeasyPrint missing."""
    from signalstream.reports.renderer import render_pdf

    with (
        patch("signalstream.reports.renderer.PDF_AVAILABLE", False),
        pytest.raises(RuntimeError, match="WeasyPrint"),
    ):
        render_pdf(_make_report_content())
