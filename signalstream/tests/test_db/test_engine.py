"""Tests for signalstream.db.engine."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from signalstream.db.engine import DatabaseEngine


class TestDatabaseEngine:
    def test_creates_db_file_and_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "subdir" / "deep" / "test.db"
        engine = DatabaseEngine(db_path)
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1

    def test_auto_vacuum_incremental(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        engine = DatabaseEngine(db_path)
        with engine.connect() as conn:
            val = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            assert val == 2

    def test_context_manager_commits_on_success(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t VALUES (1)")
        with engine.connect() as conn:
            row = conn.execute("SELECT id FROM t").fetchone()
            assert row[0] == 1

    def test_context_manager_rolls_back_on_error(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        with pytest.raises(ValueError):
            with engine.connect() as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                raise ValueError("simulated failure")
        with engine.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0

    def test_row_factory_returns_row_objects(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (name TEXT)")
            conn.execute("INSERT INTO t VALUES ('alice')")
            row = conn.execute("SELECT name FROM t").fetchone()
            assert row["name"] == "alice"

    def test_write_lock_serializes_writes(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        results = []
        def writer(val: str) -> None:
            with engine.write() as conn:
                conn.execute("INSERT INTO t (val) VALUES (?)", (val,))
                results.append(val)
        threads = [threading.Thread(target=writer, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
        with engine.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 5

    def test_incremental_vacuum(self, tmp_path: Path) -> None:
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, data TEXT)")
            for i in range(100):
                conn.execute("INSERT INTO t VALUES (?, ?)", (i, "x" * 1000))
        with engine.write() as conn:
            conn.execute("DELETE FROM t")
        engine.incremental_vacuum(pages=10)
