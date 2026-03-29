"""Database engine — SQLite connection management with WAL mode and write serialization."""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data") / "signalstream.db"


class DatabaseEngine:
    """SQLite connection manager with WAL mode, write lock, and incremental vacuum."""

    def __init__(self, db_path: Path | str | None = None, *, timeout: int = 10) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._timeout = timeout
        self._write_lock = threading.Lock()
        self._initialized = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _ensure_directory(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_pragmas(self, conn: sqlite3.Connection) -> None:
        if not self._initialized:
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self._initialized = True

    def _make_connection(self) -> sqlite3.Connection:
        self._ensure_directory()
        conn = sqlite3.connect(str(self._db_path), timeout=self._timeout)
        conn.row_factory = sqlite3.Row
        self._init_pragmas(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._make_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Generator[sqlite3.Connection, None, None]:
        with self._write_lock:
            with self.connect() as conn:
                yield conn

    def incremental_vacuum(self, pages: int = 100) -> None:
        with self.connect() as conn:
            conn.execute(f"PRAGMA incremental_vacuum({pages})")
            logger.debug("Incremental vacuum completed (%d pages requested)", pages)
