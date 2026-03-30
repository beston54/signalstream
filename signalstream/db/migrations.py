"""Schema versioning and auto-migration for the Signalstream database.

New databases are created fresh with the latest schema. Existing databases
are upgraded incrementally through numbered migration functions.

Usage:
    engine = DatabaseEngine(path)
    MigrationManager(engine).migrate()
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from signalstream.db.engine import DatabaseEngine

logger = logging.getLogger(__name__)

# Type alias for migration functions
MigrationFn = Callable[[sqlite3.Connection], None]


def _migration_001(conn: sqlite3.Connection) -> None:
    """Initial schema — jobs, job_statistics, posts, sentiment_results."""
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

        CREATE TABLE IF NOT EXISTS posts (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            post_id TEXT NOT NULL,
            author TEXT DEFAULT '',
            title TEXT DEFAULT '',
            text TEXT DEFAULT '',
            url TEXT DEFAULT '',
            community TEXT DEFAULT '',
            engagement INTEGER DEFAULT 0,
            comments_json TEXT DEFAULT '[]',
            phrase_matches_json TEXT DEFAULT '[]',
            detected_language TEXT DEFAULT '',
            detected_region TEXT DEFAULT '',
            poster_region TEXT DEFAULT '',
            topic_region TEXT DEFAULT '',
            upvote_ratio REAL,
            flair TEXT,
            is_crosspost INTEGER DEFAULT 0,
            crosspost_source TEXT,
            timestamp TEXT NOT NULL,
            collected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sentiment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_row_id INTEGER NOT NULL REFERENCES posts(row_id) ON DELETE CASCADE,
            sentiment TEXT NOT NULL,
            emotion TEXT NOT NULL,
            secondary_emotion TEXT DEFAULT 'none',
            emotion_intensity TEXT DEFAULT 'moderate',
            confidence REAL NOT NULL,
            key_point TEXT DEFAULT '',
            emotional_driver TEXT DEFAULT '',
            sarcasm_detected INTEGER DEFAULT 0,
            raw_response TEXT DEFAULT '',
            analyzed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_topic ON jobs(topic);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
        CREATE INDEX IF NOT EXISTS idx_posts_job_id ON posts(job_id);
        CREATE INDEX IF NOT EXISTS idx_posts_dedup ON posts(platform, post_id);
        CREATE INDEX IF NOT EXISTS idx_sentiment_post ON sentiment_results(post_row_id);
    """)


# Ordered list of all migrations. Index 0 = migration 1.
_MIGRATIONS: list[MigrationFn] = [
    _migration_001,
]

LATEST_VERSION = len(_MIGRATIONS)


class MigrationManager:
    """Manages schema versioning and migration for a DatabaseEngine.

    Uses SQLite's ``user_version`` pragma to track the current schema version.
    Each migration function advances the version by 1.

    Args:
        engine: The DatabaseEngine instance to migrate.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine

    def get_version(self) -> int:
        """Return the current schema version (0 = uninitialized)."""
        with self._engine.connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        """Apply all pending migrations.

        Safe to call on every startup. If the database is already at the latest
        version, this is a no-op.
        """
        current = self.get_version()

        if current >= LATEST_VERSION:
            logger.debug(
                "Database schema is up to date (version %d)", current
            )
            return

        logger.info(
            "Migrating database from version %d to %d",
            current, LATEST_VERSION,
        )

        with self._engine.write() as conn:
            for i in range(current, LATEST_VERSION):
                version = i + 1
                logger.info("Applying migration %d...", version)
                _MIGRATIONS[i](conn)
                conn.execute(f"PRAGMA user_version = {version}")

        logger.info("Database migration complete (now at version %d)", LATEST_VERSION)
