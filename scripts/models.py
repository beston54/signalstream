from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Post:
    post_id: str = ""
    phrase_match: str = ""
    title: str = ""
    text: str = ""
    subreddit: str = ""
    community_name: str = ""
    community_kind: str = ""
    source_platform: str = "reddit"
    author: str = ""
    upvotes: int = 0
    comments: int = 0
    url: str = ""
    timestamp: str = ""
    detected_language: str = ""
    detected_region: str = ""
    poster_region: str = ""
    topic_region: str = ""
    top_comments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SentimentAnalysis:
    sentiment: str = "unknown"
    emotion: str = "neutral"
    confidence: str = "unknown"
    key_point: str = ""
    sarcasm_detected: bool = False
    provider_used: str = ""


@dataclass
class AnalyzedPost(Post):
    sentiment_analysis: SentimentAnalysis = field(default_factory=SentimentAnalysis)


@dataclass
class ThemeResult:
    theme: str = ""
    percentage: int = 0
    post_count: int = 0
    representative_quotes: List[Dict[str, Any]] = field(default_factory=list)
