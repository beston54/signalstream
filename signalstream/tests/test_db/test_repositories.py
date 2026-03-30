"""Tests for signalstream.db.repositories."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from signalstream.db.engine import DatabaseEngine
from signalstream.db.migrations import MigrationManager
from signalstream.db.models import Job, JobStatistics, Post, Comment, SentimentResult
from signalstream.db.repositories import (
    JobRepository,
    PostRepository,
    SentimentResultRepository,
    StatisticsRepository,
)


@pytest.fixture
def engine(tmp_path: Path) -> DatabaseEngine:
    e = DatabaseEngine(tmp_path / "test.db")
    MigrationManager(e).migrate()
    return e


@pytest.fixture
def job_repo(engine: DatabaseEngine) -> JobRepository:
    return JobRepository(engine)


@pytest.fixture
def post_repo(engine: DatabaseEngine) -> PostRepository:
    return PostRepository(engine)


@pytest.fixture
def sentiment_repo(engine: DatabaseEngine) -> SentimentResultRepository:
    return SentimentResultRepository(engine)


@pytest.fixture
def stats_repo(engine: DatabaseEngine) -> StatisticsRepository:
    return StatisticsRepository(engine)


def _make_job(job_id: str = "j1", topic: str = "Python") -> Job:
    now = datetime.now(timezone.utc)
    return Job(id=job_id, topic=topic, created_at=now, updated_at=now)


def _make_post(
    job_id: str = "j1", post_id: str = "p1", platform: str = "reddit"
) -> Post:
    return Post(
        platform=platform, id=post_id, author="user1", text="content",
        title="Title", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="test", engagement=10,
    )


class TestJobRepository:
    def test_save_and_get(self, job_repo: JobRepository) -> None:
        job = _make_job()
        job_repo.save(job)
        retrieved = job_repo.get("j1")
        assert retrieved is not None
        assert retrieved.topic == "Python"

    def test_get_nonexistent_returns_none(self, job_repo: JobRepository) -> None:
        assert job_repo.get("nonexistent") is None

    def test_save_updates_existing(self, job_repo: JobRepository) -> None:
        job = _make_job()
        job_repo.save(job)
        job.status = "running"
        job.phase = "collecting"
        job_repo.save(job)
        retrieved = job_repo.get("j1")
        assert retrieved is not None
        assert retrieved.status == "running"
        assert retrieved.phase == "collecting"

    def test_get_all_ordered_by_created_desc(self, job_repo: JobRepository) -> None:
        for i in range(3):
            j = _make_job(f"j{i}", f"topic{i}")
            j.created_at = datetime(2026, 1, i + 1, tzinfo=timezone.utc)
            job_repo.save(j)
        jobs = job_repo.get_all(limit=10)
        assert len(jobs) == 3
        assert jobs[0].id == "j2"  # newest first

    def test_delete(self, job_repo: JobRepository) -> None:
        job_repo.save(_make_job())
        job_repo.delete("j1")
        assert job_repo.get("j1") is None


class TestPostRepository:
    def test_save_and_get_by_job(
        self, job_repo: JobRepository, post_repo: PostRepository
    ) -> None:
        job_repo.save(_make_job())
        post = _make_post()
        row_id = post_repo.save("j1", post)
        assert row_id > 0

        posts = post_repo.get_by_job("j1")
        assert len(posts) == 1
        assert posts[0].id == "p1"

    def test_dedup_by_platform_and_post_id(
        self, job_repo: JobRepository, post_repo: PostRepository
    ) -> None:
        """Saving the same post twice for the same job does not create duplicates."""
        job_repo.save(_make_job())
        post = _make_post()
        post_repo.save("j1", post)
        post_repo.save("j1", post)

        posts = post_repo.get_by_job("j1")
        assert len(posts) == 1

    def test_comments_round_trip(
        self, job_repo: JobRepository, post_repo: PostRepository
    ) -> None:
        """Comments are serialized to JSON and deserialized back."""
        job_repo.save(_make_job())
        reply = Comment(
            id="r1", body="Reply", author="u2", score=2,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=2,
        )
        comment = Comment(
            id="c1", body="Top comment", author="u1", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
            replies=[reply],
        )
        post = _make_post()
        post.comments = [comment]
        post_repo.save("j1", post)

        posts = post_repo.get_by_job("j1")
        assert len(posts[0].comments) == 1
        assert posts[0].comments[0].id == "c1"
        assert len(posts[0].comments[0].replies) == 1
        assert posts[0].comments[0].replies[0].id == "r1"

    def test_get_unanalyzed_post_ids(
        self, job_repo: JobRepository, post_repo: PostRepository
    ) -> None:
        """Returns row_ids of posts without sentiment results."""
        job_repo.save(_make_job())
        post_repo.save("j1", _make_post(post_id="p1"))
        post_repo.save("j1", _make_post(post_id="p2"))

        unanalyzed = post_repo.get_unanalyzed_row_ids("j1")
        assert len(unanalyzed) == 2


class TestSentimentResultRepository:
    def test_save_and_get(
        self, job_repo: JobRepository, post_repo: PostRepository,
        sentiment_repo: SentimentResultRepository,
    ) -> None:
        job_repo.save(_make_job())
        row_id = post_repo.save("j1", _make_post())

        result = SentimentResult(
            sentiment="positive", emotion="enthusiastic", confidence=0.9,
            key_point="Great feature", sarcasm_detected=False,
        )
        sentiment_repo.save(row_id, result)

        retrieved = sentiment_repo.get_by_post(row_id)
        assert retrieved is not None
        assert retrieved.sentiment == "positive"
        assert retrieved.confidence == 0.9

    def test_checkpointing_preserves_partial_results(
        self, job_repo: JobRepository, post_repo: PostRepository,
        sentiment_repo: SentimentResultRepository,
    ) -> None:
        """Saving results one at a time preserves each independently (BOARD-008)."""
        job_repo.save(_make_job())
        ids = []
        for i in range(3):
            row_id = post_repo.save("j1", _make_post(post_id=f"p{i}"))
            ids.append(row_id)

        # Analyze only the first two
        for row_id in ids[:2]:
            result = SentimentResult(
                sentiment="neutral", emotion="curious", confidence=0.7,
                key_point=f"Point for {row_id}", sarcasm_detected=False,
            )
            sentiment_repo.save(row_id, result)

        # Third post should still be unanalyzed
        unanalyzed = post_repo.get_unanalyzed_row_ids("j1")
        assert len(unanalyzed) == 1
        assert unanalyzed[0] == ids[2]


class TestStatisticsRepository:
    def test_save_and_get(
        self, job_repo: JobRepository, stats_repo: StatisticsRepository,
    ) -> None:
        job_repo.save(_make_job())
        stats = JobStatistics(
            job_id="j1",
            created_at=datetime.now(timezone.utc),
            total_posts=50,
            sentiment_positive=20,
            sentiment_negative=10,
            sentiment_neutral=15,
            sentiment_mixed=5,
            dominant_emotion="enthusiastic",
            dominant_emotion_pct=40.0,
        )
        stats_repo.save(stats)

        retrieved = stats_repo.get("j1")
        assert retrieved is not None
        assert retrieved.total_posts == 50
        assert retrieved.dominant_emotion == "enthusiastic"
