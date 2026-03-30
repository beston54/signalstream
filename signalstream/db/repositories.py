"""Repositories — all SQL for Signalstream lives here.

Every query is parameterized. No f-strings or string formatting with user input.
Each repository takes a DatabaseEngine instance for testability.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from signalstream.db.engine import DatabaseEngine
from signalstream.db.models import (
    Comment,
    Job,
    JobStatistics,
    Post,
    SentimentResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_comments(comments: list[Comment]) -> str:
    """Recursively serialize Comment objects to JSON."""
    def _to_dict(c: Comment) -> dict[str, Any]:
        return {
            "id": c.id,
            "body": c.body,
            "author": c.author,
            "score": c.score,
            "timestamp": c.timestamp.isoformat(),
            "depth": c.depth,
            "replies": [_to_dict(r) for r in c.replies],
        }
    return json.dumps([_to_dict(c) for c in comments])


def _deserialize_comments(raw: str) -> list[Comment]:
    """Recursively deserialize JSON back to Comment objects."""
    def _from_dict(d: dict[str, Any]) -> Comment:
        return Comment(
            id=d["id"],
            body=d["body"],
            author=d.get("author", ""),
            score=d.get("score", 0),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            depth=d.get("depth", 0),
            replies=[_from_dict(r) for r in d.get("replies", [])],
        )
    try:
        items = json.loads(raw) if raw else []
        return [_from_dict(d) for d in items]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Failed to deserialize comments JSON")
        return []


# ---------------------------------------------------------------------------
# JobRepository
# ---------------------------------------------------------------------------

class JobRepository:
    """CRUD operations for the jobs table."""

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine

    def save(self, job: Job) -> None:
        """Insert or update a job record."""
        with self._engine.write() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    id, topic, time_range, languages, regions, max_posts,
                    status, phase, progress_pct, message, post_count,
                    community_count, pdf_path, analyzed_path, themes_path,
                    error, created_at, updated_at, completed_at, preview_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    topic=excluded.topic,
                    time_range=excluded.time_range,
                    languages=excluded.languages,
                    regions=excluded.regions,
                    max_posts=excluded.max_posts,
                    status=excluded.status,
                    phase=excluded.phase,
                    progress_pct=excluded.progress_pct,
                    message=excluded.message,
                    post_count=excluded.post_count,
                    community_count=excluded.community_count,
                    pdf_path=excluded.pdf_path,
                    analyzed_path=excluded.analyzed_path,
                    themes_path=excluded.themes_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at,
                    preview_json=excluded.preview_json
            """, (
                job.id, job.topic, job.time_range, job.languages, job.regions,
                job.max_posts, job.status, job.phase, job.progress_pct,
                job.message, job.post_count, job.community_count,
                job.pdf_path, job.analyzed_path, job.themes_path,
                job.error,
                job.created_at.isoformat() if isinstance(job.created_at, datetime) else job.created_at,
                job.updated_at.isoformat() if isinstance(job.updated_at, datetime) else job.updated_at,
                job.completed_at,
                job.preview_json,
            ))

    def get(self, job_id: str) -> Job | None:
        """Retrieve a job by ID. Returns None if not found."""
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_job(row)

    def get_all(self, limit: int = 50) -> list[Job]:
        """Get recent jobs, newest first."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> None:
        """Delete a job and cascade to related tables."""
        with self._engine.write() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        d = dict(row)
        return Job(
            id=d["id"],
            topic=d["topic"],
            time_range=d.get("time_range", "week"),
            languages=d.get("languages", ""),
            regions=d.get("regions", ""),
            max_posts=d.get("max_posts", 100),
            status=d.get("status", "queued"),
            phase=d.get("phase", ""),
            progress_pct=d.get("progress_pct", 0.0),
            message=d.get("message", ""),
            post_count=d.get("post_count", 0),
            community_count=d.get("community_count", 0),
            pdf_path=d.get("pdf_path", ""),
            analyzed_path=d.get("analyzed_path", ""),
            themes_path=d.get("themes_path", ""),
            error=d.get("error", ""),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            completed_at=d.get("completed_at", ""),
            preview_json=d.get("preview_json", "{}"),
        )


# ---------------------------------------------------------------------------
# PostRepository
# ---------------------------------------------------------------------------

class PostRepository:
    """CRUD operations for the posts table — supports analysis checkpointing."""

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine

    def save(self, job_id: str, post: Post) -> int:
        """Insert a post or return the existing row_id if already present.

        Deduplication is by (platform, post_id) within the same job.

        Returns:
            The row_id of the inserted or existing post.
        """
        with self._engine.write() as conn:
            # Check for existing
            existing = conn.execute(
                "SELECT row_id FROM posts WHERE job_id = ? AND platform = ? AND post_id = ?",
                (job_id, post.platform, post.id),
            ).fetchone()
            if existing:
                return existing[0]

            cursor = conn.execute("""
                INSERT INTO posts (
                    job_id, platform, post_id, author, title, text, url,
                    community, engagement, comments_json, phrase_matches_json,
                    detected_language, detected_region, poster_region,
                    topic_region, upvote_ratio, flair, is_crosspost,
                    crosspost_source, timestamp, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, post.platform, post.id, post.author,
                post.title or "", post.text, post.url,
                post.community, post.engagement,
                _serialize_comments(post.comments),
                json.dumps(post.phrase_matches),
                post.detected_language, post.detected_region,
                post.poster_region, post.topic_region,
                post.upvote_ratio, post.flair,
                1 if post.is_crosspost else 0,
                post.crosspost_source,
                post.timestamp.isoformat() if isinstance(post.timestamp, datetime) else post.timestamp,
                datetime.now(timezone.utc).isoformat(),
            ))
            return cursor.lastrowid  # type: ignore[return-value]

    def get_by_job(self, job_id: str) -> list[Post]:
        """Retrieve all posts for a job."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE job_id = ? ORDER BY row_id",
                (job_id,),
            ).fetchall()
            return [self._row_to_post(r) for r in rows]

    def get_unanalyzed_row_ids(self, job_id: str) -> list[int]:
        """Return row_ids of posts that have no sentiment result yet.

        Used for checkpointing — resume analysis from where it left off (BOARD-008).
        """
        with self._engine.connect() as conn:
            rows = conn.execute("""
                SELECT p.row_id FROM posts p
                LEFT JOIN sentiment_results sr ON p.row_id = sr.post_row_id
                WHERE p.job_id = ? AND sr.id IS NULL
                ORDER BY p.row_id
            """, (job_id,)).fetchall()
            return [row[0] for row in rows]

    def get_by_row_id(self, row_id: int) -> Post | None:
        """Retrieve a single post by its row_id."""
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM posts WHERE row_id = ?", (row_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_post(row)

    @staticmethod
    def _row_to_post(row: sqlite3.Row) -> Post:
        d = dict(row)
        phrase_matches: list[str] = []
        try:
            phrase_matches = json.loads(d.get("phrase_matches_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass

        return Post(
            platform=d["platform"],
            id=d["post_id"],
            author=d.get("author", ""),
            text=d.get("text", ""),
            title=d.get("title") or None,
            timestamp=datetime.fromisoformat(d["timestamp"]),
            url=d.get("url", ""),
            community=d.get("community", ""),
            engagement=d.get("engagement", 0),
            comments=_deserialize_comments(d.get("comments_json", "[]")),
            phrase_matches=phrase_matches,
            detected_language=d.get("detected_language", ""),
            detected_region=d.get("detected_region", ""),
            poster_region=d.get("poster_region", ""),
            topic_region=d.get("topic_region", ""),
            upvote_ratio=d.get("upvote_ratio"),
            flair=d.get("flair"),
            is_crosspost=bool(d.get("is_crosspost", 0)),
            crosspost_source=d.get("crosspost_source"),
        )


# ---------------------------------------------------------------------------
# SentimentResultRepository
# ---------------------------------------------------------------------------

class SentimentResultRepository:
    """CRUD for sentiment analysis results — supports per-post checkpointing."""

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine

    def save(self, post_row_id: int, result: SentimentResult, raw_response: str = "") -> int:
        """Save a sentiment result for a post.

        Called after each successful analysis for checkpointing (BOARD-008).

        Returns:
            The id of the inserted sentiment_results row.
        """
        with self._engine.write() as conn:
            cursor = conn.execute("""
                INSERT INTO sentiment_results (
                    post_row_id, sentiment, emotion, secondary_emotion,
                    emotion_intensity, confidence, key_point, emotional_driver,
                    sarcasm_detected, raw_response, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                post_row_id, result.sentiment, result.emotion,
                result.secondary_emotion, result.emotion_intensity,
                result.confidence, result.key_point, result.emotional_driver,
                1 if result.sarcasm_detected else 0,
                raw_response,
                datetime.now(timezone.utc).isoformat(),
            ))
            return cursor.lastrowid  # type: ignore[return-value]

    def get_by_post(self, post_row_id: int) -> SentimentResult | None:
        """Retrieve the sentiment result for a post, or None."""
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sentiment_results WHERE post_row_id = ?",
                (post_row_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_result(row)

    def get_by_job(self, job_id: str) -> list[tuple[int, SentimentResult]]:
        """Retrieve all sentiment results for a job as (post_row_id, result) pairs."""
        with self._engine.connect() as conn:
            rows = conn.execute("""
                SELECT sr.* FROM sentiment_results sr
                JOIN posts p ON sr.post_row_id = p.row_id
                WHERE p.job_id = ?
                ORDER BY sr.post_row_id
            """, (job_id,)).fetchall()
            return [(dict(r)["post_row_id"], self._row_to_result(r)) for r in rows]

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> SentimentResult:
        d = dict(row)
        return SentimentResult(
            sentiment=d["sentiment"],
            emotion=d["emotion"],
            secondary_emotion=d.get("secondary_emotion", "none"),
            emotion_intensity=d.get("emotion_intensity", "moderate"),
            confidence=d["confidence"],
            key_point=d.get("key_point", ""),
            emotional_driver=d.get("emotional_driver", ""),
            sarcasm_detected=bool(d.get("sarcasm_detected", 0)),
        )


# ---------------------------------------------------------------------------
# StatisticsRepository
# ---------------------------------------------------------------------------

class StatisticsRepository:
    """CRUD for aggregated job statistics."""

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine

    def save(self, stats: JobStatistics) -> None:
        """Insert or update statistics for a job."""
        with self._engine.write() as conn:
            conn.execute("""
                INSERT INTO job_statistics (
                    job_id, total_posts, sentiment_positive, sentiment_negative,
                    sentiment_neutral, sentiment_mixed, dominant_emotion,
                    dominant_emotion_pct, themes_json, statistics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    total_posts=excluded.total_posts,
                    sentiment_positive=excluded.sentiment_positive,
                    sentiment_negative=excluded.sentiment_negative,
                    sentiment_neutral=excluded.sentiment_neutral,
                    sentiment_mixed=excluded.sentiment_mixed,
                    dominant_emotion=excluded.dominant_emotion,
                    dominant_emotion_pct=excluded.dominant_emotion_pct,
                    themes_json=excluded.themes_json,
                    statistics_json=excluded.statistics_json
            """, (
                stats.job_id, stats.total_posts,
                stats.sentiment_positive, stats.sentiment_negative,
                stats.sentiment_neutral, stats.sentiment_mixed,
                stats.dominant_emotion, stats.dominant_emotion_pct,
                stats.themes_json, stats.statistics_json,
                stats.created_at.isoformat() if isinstance(stats.created_at, datetime) else stats.created_at,
            ))

    def get(self, job_id: str) -> JobStatistics | None:
        """Retrieve statistics for a job, or None."""
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_statistics WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            return JobStatistics(
                job_id=d["job_id"],
                total_posts=d.get("total_posts", 0),
                sentiment_positive=d.get("sentiment_positive", 0),
                sentiment_negative=d.get("sentiment_negative", 0),
                sentiment_neutral=d.get("sentiment_neutral", 0),
                sentiment_mixed=d.get("sentiment_mixed", 0),
                dominant_emotion=d.get("dominant_emotion", ""),
                dominant_emotion_pct=d.get("dominant_emotion_pct", 0.0),
                themes_json=d.get("themes_json", "[]"),
                statistics_json=d.get("statistics_json", "{}"),
                created_at=datetime.fromisoformat(d["created_at"]),
            )
