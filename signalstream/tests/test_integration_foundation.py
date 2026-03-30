"""Integration test — full foundation stack with mock LLM provider.

Verifies: DB setup -> Post storage -> Sentiment analysis -> Thematic analysis
-> Result persistence -> Checkpoint recovery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from signalstream.analyzers.sentiment import SentimentAnalyzer
from signalstream.analyzers.thematic import ThematicAnalyzer
from signalstream.db.engine import DatabaseEngine
from signalstream.db.migrations import MigrationManager
from signalstream.db.models import Job, Post, SentimentResult, Theme
from signalstream.db.repositories import (
    JobRepository,
    PostRepository,
    SentimentResultRepository,
)

_SENTIMENT_RESPONSE = """PRIMARY_EMOTION: enthusiastic
SECONDARY_EMOTION: hopeful
EMOTION_INTENSITY: strong
SENTIMENT: positive
CONFIDENCE: certain
KEY_POINT: Users love the performance improvements
EMOTIONAL_DRIVER: Faster build times improve productivity
SARCASM_DETECTED: false"""


_THEME_RESPONSE = """MAJOR_THEMES:
1. Performance Gains | Users report 2-3x speed improvements
2. API Design | Clean new API praised by developers

POST_THEME_ASSIGNMENTS:
1: 1
2: 1,2
3: 2

NOVEL_IDEAS:
- Using new async primitives for pipeline patterns

KEY_CRITIQUES:
- Migration path unclear for large codebases (frequency: frequent)

REGIONAL_PATTERNS:
- US: Focus on enterprise adoption

SENTIMENT_SUMMARY:
Overall sentiment is positive with high confidence.
Developers are enthusiastic about performance gains."""


@pytest.fixture
def engine(tmp_path: Path) -> DatabaseEngine:
    e = DatabaseEngine(tmp_path / "integration.db")
    MigrationManager(e).migrate()
    return e


class TestFoundationIntegration:
    def test_full_pipeline_with_mock_llm(self, engine: DatabaseEngine) -> None:
        """End-to-end: create job -> store posts -> analyze -> store results."""
        # 1. Create a job
        job_repo = JobRepository(engine)
        post_repo = PostRepository(engine)
        sentiment_repo = SentimentResultRepository(engine)

        now = datetime.now(timezone.utc)
        job = Job(id="integration-1", topic="Python 4.0", created_at=now, updated_at=now)
        job_repo.save(job)

        # 2. Store posts
        posts = []
        for i in range(3):
            post = Post(
                platform="reddit", id=f"post{i}", author=f"user{i}",
                text=f"Python 4.0 is {'great' if i % 2 == 0 else 'concerning'}",
                title=f"Post {i} about Python",
                timestamp=now, url=f"https://reddit.com/r/python/{i}",
                community="python", engagement=50 + i * 10,
            )
            post_repo.save("integration-1", post)
            posts.append(post)

        # 3. Verify posts stored
        stored_posts = post_repo.get_by_job("integration-1")
        assert len(stored_posts) == 3

        # 4. Run sentiment analysis with mock LLM
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _SENTIMENT_RESPONSE

        analyzer = SentimentAnalyzer(provider=mock_provider, model="test")
        results = analyzer.analyze(posts=posts, topic="Python 4.0")

        assert len(results) == 3

        # 5. Persist results (simulating checkpointing)
        row_ids = [
            post_repo.save("integration-1", p) for p in posts
        ]
        for row_id, (_, result) in zip(row_ids, results, strict=False):
            sentiment_repo.save(row_id, result)

        # 6. Verify checkpointing — all posts now analyzed
        unanalyzed = post_repo.get_unanalyzed_row_ids("integration-1")
        assert len(unanalyzed) == 0

        # 7. Run thematic analysis
        mock_provider.complete.return_value = _THEME_RESPONSE
        thematic = ThematicAnalyzer(provider=mock_provider, model="test")
        themes = thematic.analyze(analyzed_posts=results, phrase="Python 4.0")

        assert len(themes) >= 1
        assert all(isinstance(t, Theme) for t in themes)

    def test_checkpoint_recovery(self, engine: DatabaseEngine) -> None:
        """Simulate job failure at post 2/3 and verify recovery."""
        job_repo = JobRepository(engine)
        post_repo = PostRepository(engine)
        sentiment_repo = SentimentResultRepository(engine)

        now = datetime.now(timezone.utc)
        job = Job(id="recovery-1", topic="Recovery Test", created_at=now, updated_at=now)
        job_repo.save(job)

        # Store 3 posts
        posts = []
        for i in range(3):
            post = Post(
                platform="reddit", id=f"rp{i}", author=f"user{i}",
                text=f"Post content {i}", title=f"Title {i}",
                timestamp=now, url=f"https://reddit.com/{i}",
                community="test", engagement=10,
            )
            row_id = post_repo.save("recovery-1", post)
            posts.append((post, row_id))

        # Analyze only the first 2 (simulating failure before 3rd)
        result = SentimentResult(
            sentiment="positive", emotion="enthusiastic",
            confidence=0.9, key_point="Test point",
            sarcasm_detected=False,
        )
        for _, row_id in posts[:2]:
            sentiment_repo.save(row_id, result)

        # Verify: only post 3 is unanalyzed
        unanalyzed = post_repo.get_unanalyzed_row_ids("recovery-1")
        assert len(unanalyzed) == 1
        assert unanalyzed[0] == posts[2][1]  # row_id of third post

        # "Resume": analyze the remaining post
        sentiment_repo.save(posts[2][1], result)

        # Now all analyzed
        unanalyzed = post_repo.get_unanalyzed_row_ids("recovery-1")
        assert len(unanalyzed) == 0
