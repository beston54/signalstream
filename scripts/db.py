"""
Database Module

SQLite-based persistence for jobs, analysis results, profiles, and
historical trend data. Replaces the in-memory job dict + JSON file approach.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signalstream.db"


def _ensure_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection():
    """Thread-safe database connection context manager."""
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                time_range TEXT DEFAULT 'week',
                languages TEXT DEFAULT '',
                regions TEXT DEFAULT '',
                max_posts INTEGER DEFAULT 100,
                status TEXT DEFAULT 'queued',
                phase TEXT DEFAULT '',
                progress_pct REAL DEFAULT 0,
                message TEXT DEFAULT '',
                post_count INTEGER DEFAULT 0,
                community_count INTEGER DEFAULT 0,
                pdf_path TEXT DEFAULT '',
                analyzed_path TEXT DEFAULT '',
                themes_path TEXT DEFAULT '',
                error TEXT DEFAULT '',
                email_submitted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT DEFAULT '',
                preview_json TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS job_statistics (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                total_posts INTEGER DEFAULT 0,
                sentiment_positive INTEGER DEFAULT 0,
                sentiment_negative INTEGER DEFAULT 0,
                sentiment_neutral INTEGER DEFAULT 0,
                sentiment_mixed INTEGER DEFAULT 0,
                dominant_emotion TEXT DEFAULT '',
                dominant_emotion_pct REAL DEFAULT 0,
                themes_json TEXT DEFAULT '[]',
                statistics_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                time_range TEXT DEFAULT 'week',
                languages TEXT DEFAULT '',
                regions TEXT DEFAULT '',
                max_posts INTEGER DEFAULT 100,
                schedule_cron TEXT DEFAULT '',
                notify_email TEXT DEFAULT '',
                branding_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_topic ON jobs(topic);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
        """)
    # Add notify_email column if missing (migration for existing databases)
    with get_connection() as conn:
        try:
            conn.execute("SELECT notify_email FROM profiles LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE profiles ADD COLUMN notify_email TEXT DEFAULT ''")
            logger.info("Added notify_email column to profiles table")

    logger.info("Database initialized")


# --- Job CRUD ---

def save_job(job: Dict[str, Any]):
    """Insert or update a job record."""
    now = datetime.now().isoformat()
    preview = json.dumps(job.get('preview', {}), default=str)
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs (id, topic, time_range, languages, regions, max_posts,
                            status, phase, progress_pct, message, post_count,
                            community_count, pdf_path, analyzed_path, themes_path,
                            error, email_submitted, created_at, updated_at,
                            completed_at, preview_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status, phase=excluded.phase,
                progress_pct=excluded.progress_pct, message=excluded.message,
                post_count=excluded.post_count, community_count=excluded.community_count,
                pdf_path=excluded.pdf_path, analyzed_path=excluded.analyzed_path,
                themes_path=excluded.themes_path, error=excluded.error,
                email_submitted=excluded.email_submitted,
                updated_at=excluded.updated_at, completed_at=excluded.completed_at,
                preview_json=excluded.preview_json
        """, (
            job.get('id', ''),
            job.get('topic', ''),
            job.get('time_range', 'week'),
            job.get('languages', ''),
            job.get('regions', ''),
            job.get('max_posts', 100),
            job.get('status', 'queued'),
            job.get('phase', ''),
            job.get('progress_pct', 0),
            job.get('message', ''),
            job.get('post_count', 0),
            job.get('community_count', 0),
            job.get('pdf_path', ''),
            job.get('analyzed_path', ''),
            job.get('themes_path', ''),
            job.get('error', ''),
            1 if job.get('email_submitted') else 0,
            job.get('created_at', now),
            now,
            job.get('completed_at', ''),
            preview,
        ))


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a job by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            return _row_to_job(row)
    return None


def get_all_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent jobs, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_job(r) for r in rows]


def delete_job(job_id: str):
    """Delete a job and its statistics."""
    with get_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def _row_to_job(row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a job dict matching the legacy format."""
    d = dict(row)
    d['email_submitted'] = bool(d.get('email_submitted', 0))
    try:
        d['preview'] = json.loads(d.get('preview_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        d['preview'] = {}
    d.pop('preview_json', None)
    return d


# --- Statistics persistence for trend tracking ---

def save_job_statistics(job_id: str, statistics: Dict[str, Any]):
    """Save analysis statistics for historical trend tracking."""
    now = datetime.now().isoformat()
    sentiment = statistics.get('sentiment_distribution', {})
    emotion_dist = statistics.get('emotion_distribution', {})
    dominant_emotion = max(emotion_dist, key=emotion_dist.get) if emotion_dist else ''
    total = max(statistics.get('total_posts', 1), 1)
    dominant_pct = round(emotion_dist.get(dominant_emotion, 0) / total * 100, 1) if dominant_emotion else 0

    themes_summary = []
    for phrase, tdata in (statistics.get('themes_by_phrase', {}) or {}).items():
        for t in (tdata.get('major_themes', []) or [])[:3]:
            themes_summary.append({
                "theme": t.get('theme', ''),
                "pct": t.get('percentage', 0),
                "count": t.get('post_count', 0),
            })

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO job_statistics (job_id, total_posts,
                sentiment_positive, sentiment_negative, sentiment_neutral, sentiment_mixed,
                dominant_emotion, dominant_emotion_pct, themes_json, statistics_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            job_id,
            statistics.get('total_posts', 0),
            sentiment.get('positive', 0),
            sentiment.get('negative', 0),
            sentiment.get('neutral', 0),
            sentiment.get('mixed', 0),
            dominant_emotion,
            dominant_pct,
            json.dumps(themes_summary, default=str),
            json.dumps(statistics, default=str),
            now,
        ))


def get_trend_data(topic: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get historical statistics for a topic to compute trends.

    Uses LIKE matching on the topic field to find related prior analyses.
    Returns newest first.
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT j.id, j.topic, j.created_at, j.completed_at, j.post_count,
                   s.total_posts, s.sentiment_positive, s.sentiment_negative,
                   s.sentiment_neutral, s.sentiment_mixed,
                   s.dominant_emotion, s.dominant_emotion_pct, s.themes_json
            FROM jobs j
            JOIN job_statistics s ON j.id = s.job_id
            WHERE j.topic LIKE ? AND j.status = 'complete'
            ORDER BY j.created_at DESC
            LIMIT ?
        """, (f"%{topic}%", limit)).fetchall()
        return [dict(r) for r in rows]


# --- Profile CRUD ---

def save_profile(profile: Dict[str, Any]) -> int:
    """Insert or update a profile. Returns profile ID."""
    now = datetime.now().isoformat()
    branding = json.dumps(profile.get('branding', {}), default=str)
    with get_connection() as conn:
        if profile.get('id'):
            conn.execute("""
                UPDATE profiles SET name=?, topic=?, time_range=?, languages=?,
                    regions=?, max_posts=?, schedule_cron=?, notify_email=?,
                    branding_json=?, updated_at=?
                WHERE id=?
            """, (
                profile['name'], profile['topic'], profile.get('time_range', 'week'),
                profile.get('languages', ''), profile.get('regions', ''),
                profile.get('max_posts', 100), profile.get('schedule_cron', ''),
                profile.get('notify_email', ''),
                branding, now, profile['id'],
            ))
            return profile['id']
        else:
            cursor = conn.execute("""
                INSERT INTO profiles (name, topic, time_range, languages, regions,
                    max_posts, schedule_cron, notify_email, branding_json,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile['name'], profile['topic'], profile.get('time_range', 'week'),
                profile.get('languages', ''), profile.get('regions', ''),
                profile.get('max_posts', 100), profile.get('schedule_cron', ''),
                profile.get('notify_email', ''),
                branding, now, now,
            ))
            return cursor.lastrowid


def get_all_profiles() -> List[Dict[str, Any]]:
    """Get all saved profiles."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM profiles ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['branding'] = json.loads(d.get('branding_json', '{}'))
            except (json.JSONDecodeError, TypeError):
                d['branding'] = {}
            d.pop('branding_json', None)
            result.append(d)
        return result


def get_profile(profile_id: int) -> Optional[Dict[str, Any]]:
    """Get a single profile by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row:
            d = dict(row)
            try:
                d['branding'] = json.loads(d.get('branding_json', '{}'))
            except (json.JSONDecodeError, TypeError):
                d['branding'] = {}
            d.pop('branding_json', None)
            return d
    return None


def delete_profile(profile_id: int):
    """Delete a profile."""
    with get_connection() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


def migrate_job_history(history_path: str):
    """One-time migration of existing job_history.json into SQLite."""
    path = Path(history_path)
    if not path.exists():
        return
    try:
        with open(path, 'r') as f:
            history = json.load(f)
        if isinstance(history, list):
            for job in history:
                save_job(job)
            logger.info(f"Migrated {len(history)} jobs from {path}")
        elif isinstance(history, dict):
            for job_id, job in history.items():
                if 'id' not in job:
                    job['id'] = job_id
                save_job(job)
            logger.info(f"Migrated {len(history)} jobs from {path}")
    except Exception as e:
        logger.warning(f"Failed to migrate job history: {e}")
