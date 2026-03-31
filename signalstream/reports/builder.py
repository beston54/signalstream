"""
Report content assembly.

Computes statistics, generates charts, and structures all data needed by
the renderer. This is the "what goes in the report" layer — decoupled from
"how it is rendered" (PDF, JSON, etc.).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from signalstream.reports.charts import generate_all_charts

logger = logging.getLogger(__name__)


@dataclass
class ReportContent:
    """All data needed to render a report in any format."""

    job_id: str
    topic: str
    phrases: list[str]
    generated_at: str
    total_posts: int
    skipped_count: int
    statistics: dict[str, Any]
    executive_snapshot: dict[str, Any]
    themes: list[dict[str, Any]]
    charts: dict[str, str]  # chart name -> base64 data URI
    analyzed_posts: list[dict[str, Any]]
    branding_footer: bool = True


def _compute_statistics(
    posts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive distribution statistics from analyzed posts."""
    if not posts:
        return {
            "sentiment_distribution": {},
            "emotion_distribution": {},
            "community_breakdown": {},
        }

    sentiment_counter: Counter[str] = Counter()
    emotion_counter: Counter[str] = Counter()
    community_sentiments: dict[str, Counter[str]] = {}

    for post_data in posts:
        analysis = post_data.get("analysis", {})
        post = post_data.get("post", {})

        sentiment = analysis.get("sentiment", "neutral")
        emotion = analysis.get("emotion", "unknown")
        community = post.get("community", "unknown")

        sentiment_counter[sentiment] += 1
        emotion_counter[emotion] += 1

        if community not in community_sentiments:
            community_sentiments[community] = Counter()
        community_sentiments[community][sentiment] += 1

    community_breakdown = {
        comm: dict(counter)
        for comm, counter in community_sentiments.items()
    }

    return {
        "sentiment_distribution": dict(sentiment_counter),
        "emotion_distribution": dict(emotion_counter),
        "community_breakdown": community_breakdown,
    }


def _compute_executive_snapshot(
    posts: list[dict[str, Any]],
    statistics: dict[str, Any],
    themes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute top-level metrics for the executive snapshot."""
    if not posts:
        return {
            "total_posts": 0,
            "dominant_sentiment": "n/a",
            "dominant_emotion": "n/a",
            "avg_confidence": 0.0,
            "top_theme": "n/a",
            "sentiment_ratio": "n/a",
        }

    sent_dist = statistics.get("sentiment_distribution", {})
    emo_dist = statistics.get("emotion_distribution", {})

    dominant_sentiment = (
        max(sent_dist, key=sent_dist.get)
        if sent_dist else "n/a"
    )
    dominant_emotion = (
        max(emo_dist, key=emo_dist.get)
        if emo_dist else "n/a"
    )

    confidences = [
        p.get("analysis", {}).get("confidence", 0.0)
        for p in posts
    ]
    avg_confidence = (
        sum(confidences) / len(confidences)
        if confidences else 0.0
    )

    top_theme = themes[0]["name"] if themes else "n/a"

    positive = sent_dist.get("positive", 0)
    negative = sent_dist.get("negative", 0)
    total_pn = positive + negative
    sentiment_ratio = (
        f"{positive}:{negative}" if total_pn > 0 else "n/a"
    )

    return {
        "total_posts": len(posts),
        "dominant_sentiment": dominant_sentiment,
        "dominant_emotion": dominant_emotion,
        "avg_confidence": round(avg_confidence, 3),
        "top_theme": top_theme,
        "sentiment_ratio": sentiment_ratio,
    }


def build_report_content(
    job_id: str,
    topic: str,
    phrases: list[str],
    analyzed_posts: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    skipped_count: int = 0,
    branding_footer: bool = True,
) -> ReportContent:
    """Assemble all report content from analysis results.

    This is the single entry point for report data preparation.
    """
    statistics = _compute_statistics(analyzed_posts)
    executive_snapshot = _compute_executive_snapshot(
        analyzed_posts, statistics, themes,
    )
    charts = generate_all_charts(statistics, themes)

    return ReportContent(
        job_id=job_id,
        topic=topic,
        phrases=phrases,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=len(analyzed_posts),
        skipped_count=skipped_count,
        statistics=statistics,
        executive_snapshot=executive_snapshot,
        themes=themes,
        charts=charts,
        analyzed_posts=analyzed_posts,
        branding_footer=branding_footer,
    )
