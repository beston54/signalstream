"""Tests for signalstream.db.migrations."""
from __future__ import annotations

from pathlib import Path

from signalstream.db.engine import DatabaseEngine
from signalstream.db.migrations import MigrationManager


class TestMigrationManager:
    def test_fresh_database_creates_all_tables(self, tmp_path: Path) -> None:
        """A new database gets all tables created from scratch."""
        engine = DatabaseEngine(tmp_path / "test.db")
        manager = MigrationManager(engine)
        manager.migrate()

        with engine.connect() as conn:
            tables = {
                row[0] for row in
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "jobs" in tables
        assert "job_statistics" in tables
        assert "sentiment_results" in tables
        assert "posts" in tables

    def test_schema_version_set_after_migration(self, tmp_path: Path) -> None:
        """After migration, the schema version pragma is set."""
        engine = DatabaseEngine(tmp_path / "test.db")
        manager = MigrationManager(engine)
        manager.migrate()

        with engine.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version >= 1

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Running migrate twice does not error or corrupt data."""
        engine = DatabaseEngine(tmp_path / "test.db")
        manager = MigrationManager(engine)
        manager.migrate()
        # Insert a row to verify data survives re-migration
        with engine.write() as conn:
            conn.execute(
                "INSERT INTO jobs (id, topic, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("j1", "test", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
        manager.migrate()

        with engine.connect() as conn:
            row = conn.execute("SELECT topic FROM jobs WHERE id = ?", ("j1",)).fetchone()
            assert row["topic"] == "test"

    def test_indexes_created(self, tmp_path: Path) -> None:
        """Expected indexes exist after migration."""
        engine = DatabaseEngine(tmp_path / "test.db")
        MigrationManager(engine).migrate()

        with engine.connect() as conn:
            indexes = {
                row[0] for row in
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        assert "idx_jobs_topic" in indexes
        assert "idx_jobs_status" in indexes
        assert "idx_jobs_created" in indexes
        assert "idx_posts_job_id" in indexes

    def test_get_version_on_fresh_db(self, tmp_path: Path) -> None:
        """A fresh database reports version 0."""
        engine = DatabaseEngine(tmp_path / "test.db")
        manager = MigrationManager(engine)
        assert manager.get_version() == 0

    def test_posts_table_has_expected_columns(self, tmp_path: Path) -> None:
        """The posts table includes all columns needed for checkpointing."""
        engine = DatabaseEngine(tmp_path / "test.db")
        MigrationManager(engine).migrate()

        with engine.connect() as conn:
            info = conn.execute("PRAGMA table_info(posts)").fetchall()
            columns = {row[1] for row in info}

        assert "job_id" in columns
        assert "platform" in columns
        assert "post_id" in columns
        assert "title" in columns
        assert "text" in columns
        assert "community" in columns
        assert "engagement" in columns
        assert "url" in columns

    def test_sentiment_results_table_has_expected_columns(self, tmp_path: Path) -> None:
        """The sentiment_results table includes all output fields."""
        engine = DatabaseEngine(tmp_path / "test.db")
        MigrationManager(engine).migrate()

        with engine.connect() as conn:
            info = conn.execute("PRAGMA table_info(sentiment_results)").fetchall()
            columns = {row[1] for row in info}

        assert "post_row_id" in columns
        assert "sentiment" in columns
        assert "emotion" in columns
        assert "confidence" in columns
        assert "key_point" in columns
        assert "sarcasm_detected" in columns
