"""Domain dataclasses — plain data objects with no database coupling.

Board amendments: BOARD-001 (expanded Post/Comment), BOARD-006 (full SentimentResult).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Comment:
    """A structured comment with threading support."""
    id: str
    body: str
    author: str
    score: int
    timestamp: datetime
    depth: int
    replies: list[Comment] = field(default_factory=list)


@dataclass
class Post:
    """A normalized social media post."""
    platform: str
    id: str
    author: str
    text: str
    title: str | None
    timestamp: datetime
    url: str
    community: str
    engagement: int
    comments: list[Comment] = field(default_factory=list)
    phrase_matches: list[str] = field(default_factory=list)
    detected_language: str = ""
    detected_region: str = ""
    poster_region: str = ""
    topic_region: str = ""
    upvote_ratio: float | None = None
    flair: str | None = None
    is_crosspost: bool = False
    crosspost_source: str | None = None

    @property
    def dedup_key(self) -> str:
        return f"{self.platform}:{self.id}"


@dataclass
class SentimentResult:
    """Result of per-post sentiment analysis."""
    sentiment: str
    emotion: str
    confidence: float
    key_point: str
    sarcasm_detected: bool
    secondary_emotion: str = "none"
    emotion_intensity: str = "moderate"
    emotional_driver: str = ""


@dataclass
class Theme:
    """A cross-post theme extracted by the thematic analyzer."""
    name: str
    description: str
    percentage: float
    post_count: int
    sentiment_skew: str
    representative_quotes: list[str] = field(default_factory=list)


@dataclass
class Job:
    """Metadata for an analysis job. Never contains API keys."""
    id: str
    topic: str
    created_at: datetime
    updated_at: datetime
    time_range: str = "week"
    languages: str = ""
    regions: str = ""
    max_posts: int = 100
    status: str = "queued"
    phase: str = ""
    progress_pct: float = 0.0
    message: str = ""
    post_count: int = 0
    community_count: int = 0
    pdf_path: str = ""
    analyzed_path: str = ""
    themes_path: str = ""
    error: str = ""
    completed_at: str = ""
    preview_json: str = "{}"


@dataclass
class JobStatistics:
    """Aggregated statistics for a completed job."""
    job_id: str
    created_at: datetime
    total_posts: int = 0
    sentiment_positive: int = 0
    sentiment_negative: int = 0
    sentiment_neutral: int = 0
    sentiment_mixed: int = 0
    dominant_emotion: str = ""
    dominant_emotion_pct: float = 0.0
    themes_json: str = "[]"
    statistics_json: str = "{}"
