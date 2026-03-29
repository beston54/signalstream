# Plan 1: Foundation — DB, LLM, Collectors, Analyzers

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core engine — database, LLM providers, data collection, and analysis — that the pipeline and web layer depend on.

**Architecture:** Flat domain packages under `signalstream/`. Each package has clear boundaries and no cross-dependencies except through well-defined interfaces. TDD throughout — every component is tested before integration.

**Tech Stack:** Python 3.10+, SQLite (WAL mode), anthropic SDK, requests, nh3, pytest

---

## Task 0: Project Scaffolding

> Create the package structure, pyproject.toml, and shared test infrastructure. Everything else depends on this.

**Files:**
- Create: `signalstream/__init__.py`
- Create: `signalstream/db/__init__.py`
- Create: `signalstream/llm/__init__.py`
- Create: `signalstream/llm/providers/__init__.py`
- Create: `signalstream/collectors/__init__.py`
- Create: `signalstream/analyzers/__init__.py`
- Create: `signalstream/tests/__init__.py`
- Create: `signalstream/tests/test_db/__init__.py`
- Create: `signalstream/tests/test_llm/__init__.py`
- Create: `signalstream/tests/test_collectors/__init__.py`
- Create: `signalstream/tests/test_analyzers/__init__.py`
- Create: `signalstream/tests/conftest.py`
- Create: `pyproject.toml`

- [ ] **Step 1:** Create the package directory tree.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
mkdir -p signalstream/{db,llm/providers,collectors,analyzers,tests/{test_db,test_llm,test_collectors,test_analyzers}}
```

- [ ] **Step 2:** Create all `__init__.py` files.

```python
# signalstream/__init__.py
"""Signalstream — LLM-powered sentiment analysis engine."""
from __future__ import annotations

__version__ = "0.1.0"
```

All other `__init__.py` files are empty except for the `from __future__ import annotations` import:

```python
from __future__ import annotations
```

- [ ] **Step 3:** Create `pyproject.toml` at the project root.

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "signalstream"
version = "0.1.0"
description = "LLM-powered sentiment analysis engine"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "flask>=3.0",
    "requests>=2.31",
    "matplotlib>=3.8",
    "jinja2>=3.1",
    "nh3>=0.2",
]

[project.optional-dependencies]
pdf = ["weasyprint>=60"]
reddit-api = ["praw>=7.7"]
claude = ["anthropic>=0.39"]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
]

[tool.pytest.ini_options]
testpaths = ["signalstream/tests"]
pythonpath = ["."]

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM"]
```

- [ ] **Step 4:** Create `signalstream/tests/conftest.py` with shared fixtures.

```python
"""Shared test fixtures for all signalstream tests."""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temporary database file path."""
    return tmp_path / "test_signalstream.db"


@pytest.fixture
def tmp_db_connection(tmp_db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a raw SQLite connection to a temporary database with WAL mode."""
    conn = sqlite3.connect(str(tmp_db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


class MockLLMProvider:
    """A mock LLM provider for testing analyzers without real API calls.

    Attributes:
        responses: List of strings to return in sequence. Cycles if exhausted.
        calls: List of (messages, model, config) tuples recorded from each call.
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses: list[str] = responses or ["MOCK_RESPONSE"]
        self.calls: list[tuple] = []
        self._call_index: int = 0

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: "CompletionConfig | None" = None,
    ) -> str:
        self.calls.append((messages, model, config))
        response = self.responses[self._call_index % len(self.responses)]
        self._call_index += 1
        return response

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """Return a fresh MockLLMProvider instance."""
    return MockLLMProvider()
```

- [ ] **Step 5:** Verify the scaffolding by running pytest (expect 0 tests collected, no errors).

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/ --co -q
```

Expected output: `no tests ran` (with exit code 0 or 5 for "no tests collected").

- [ ] **Step 6:** Commit.

```
feat: create signalstream package scaffolding

Project structure, pyproject.toml, and shared test fixtures for the
signalstream rebuild. Flat domain packages: db, llm, collectors, analyzers.
```

---

## Task 1: Database Engine (`signalstream/db/engine.py`)

> SQLite connection manager with WAL mode, write serialization, incremental vacuum, and auto-directory creation.

**Files:**
- Create: `signalstream/db/engine.py`
- Create: `signalstream/tests/test_db/test_engine.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_db/test_engine.py`.

```python
"""Tests for signalstream.db.engine."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from signalstream.db.engine import DatabaseEngine


class TestDatabaseEngine:
    """Tests for the DatabaseEngine connection manager."""

    def test_creates_db_file_and_parent_dirs(self, tmp_path: Path) -> None:
        """Engine creates the database file and any missing parent directories."""
        db_path = tmp_path / "subdir" / "deep" / "test.db"
        engine = DatabaseEngine(db_path)
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """Engine sets WAL journal mode."""
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        """Engine enables foreign key enforcement."""
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1

    def test_auto_vacuum_incremental(self, tmp_path: Path) -> None:
        """Engine sets auto_vacuum to INCREMENTAL (value 2)."""
        db_path = tmp_path / "test.db"
        engine = DatabaseEngine(db_path)
        with engine.connect() as conn:
            # auto_vacuum must be set before any tables are created
            val = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            assert val == 2

    def test_context_manager_commits_on_success(self, tmp_path: Path) -> None:
        """Successful context manager block commits the transaction."""
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t VALUES (1)")

        # Verify data persisted
        with engine.connect() as conn:
            row = conn.execute("SELECT id FROM t").fetchone()
            assert row[0] == 1

    def test_context_manager_rolls_back_on_error(self, tmp_path: Path) -> None:
        """Failed context manager block rolls back the transaction."""
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
        """Connections use sqlite3.Row for dict-like access."""
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (name TEXT)")
            conn.execute("INSERT INTO t VALUES ('alice')")
            row = conn.execute("SELECT name FROM t").fetchone()
            assert row["name"] == "alice"

    def test_write_lock_serializes_writes(self, tmp_path: Path) -> None:
        """The write lock prevents concurrent writes from overlapping."""
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
        """incremental_vacuum runs without error."""
        engine = DatabaseEngine(tmp_path / "test.db")
        with engine.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, data TEXT)")
            for i in range(100):
                conn.execute("INSERT INTO t VALUES (?, ?)", (i, "x" * 1000))

        with engine.write() as conn:
            conn.execute("DELETE FROM t")

        # Should not raise
        engine.incremental_vacuum(pages=10)
```

- [ ] **Step 2:** Run the test — confirm it fails (module not found).

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_engine.py -x -q 2>&1 | head -20
```

- [ ] **Step 3:** Implement `signalstream/db/engine.py`.

```python
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
    """SQLite connection manager with WAL mode, write lock, and incremental vacuum.

    Args:
        db_path: Path to the SQLite database file. Parent directories are created
            automatically if they do not exist.
        timeout: SQLite busy timeout in seconds.
    """

    def __init__(self, db_path: Path | str | None = None, *, timeout: int = 10) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._timeout = timeout
        self._write_lock = threading.Lock()
        self._initialized = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _ensure_directory(self) -> None:
        """Create parent directories for the database file if they do not exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_pragmas(self, conn: sqlite3.Connection) -> None:
        """Set one-time pragmas that must be applied before any tables are created."""
        if not self._initialized:
            # auto_vacuum must be set before any tables exist in the database.
            # It is a no-op on an already-initialized database, but safe to call.
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self._initialized = True

    def _make_connection(self) -> sqlite3.Connection:
        """Create a new connection with standard configuration."""
        self._ensure_directory()
        conn = sqlite3.connect(str(self._db_path), timeout=self._timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._init_pragmas(conn)
        return conn

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for a database connection.

        Commits on successful exit, rolls back on exception. The connection
        is always closed when the context exits.
        """
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
        """Context manager for serialized write access.

        Acquires the write lock before yielding the connection. This prevents
        concurrent write transactions from causing SQLITE_BUSY errors.
        """
        with self._write_lock:
            with self.connect() as conn:
                yield conn

    def incremental_vacuum(self, pages: int = 100) -> None:
        """Reclaim free pages without blocking the entire database.

        Args:
            pages: Number of free pages to reclaim. Pass 0 to reclaim all.
        """
        with self.connect() as conn:
            conn.execute(f"PRAGMA incremental_vacuum({pages})")
            logger.debug("Incremental vacuum completed (%d pages requested)", pages)
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_engine.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5:** Commit.

```
feat(db): add DatabaseEngine with WAL mode, write lock, incremental vacuum

SQLite connection manager that creates parent directories, enables WAL
journal mode, foreign keys, and incremental auto-vacuum. Write access
serialized through a threading lock.
```

---

## Task 2: Domain Models (`signalstream/db/models.py`)

> Domain dataclasses for Post, Comment, SentimentResult, Theme, Job, and JobStatistics. These are plain data — no ORM, no database coupling.

**Files:**
- Create: `signalstream/db/models.py`
- Create: `signalstream/tests/test_db/test_models.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_db/test_models.py`.

```python
"""Tests for signalstream.db.models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalstream.db.models import (
    Comment,
    Job,
    JobStatistics,
    Post,
    SentimentResult,
    Theme,
)


class TestComment:
    def test_comment_creation(self) -> None:
        comment = Comment(
            id="abc123",
            body="Great post!",
            author="user1",
            score=42,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1,
        )
        assert comment.id == "abc123"
        assert comment.replies == []

    def test_comment_nested_replies(self) -> None:
        reply = Comment(
            id="r1", body="Thanks!", author="user2", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=2,
        )
        parent = Comment(
            id="c1", body="Interesting", author="user1", score=10,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
            replies=[reply],
        )
        assert len(parent.replies) == 1
        assert parent.replies[0].id == "r1"


class TestPost:
    def test_post_creation_with_defaults(self) -> None:
        post = Post(
            platform="reddit",
            id="post1",
            author="author1",
            text="Hello world",
            title="My Post",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://reddit.com/r/test/post1",
            community="test",
            engagement=100,
        )
        assert post.comments == []
        assert post.phrase_matches == []
        assert post.detected_language == ""
        assert post.detected_region == ""
        assert post.upvote_ratio is None
        assert post.flair is None
        assert post.is_crosspost is False
        assert post.crosspost_source is None

    def test_post_dedup_key(self) -> None:
        post = Post(
            platform="reddit", id="abc", author="u", text="t", title="T",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://example.com", community="r", engagement=0,
        )
        assert post.dedup_key == "reddit:abc"

    def test_post_with_comments(self) -> None:
        comment = Comment(
            id="c1", body="Nice", author="u2", score=3,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), depth=1,
        )
        post = Post(
            platform="reddit", id="p1", author="u1", text="content",
            title="Title", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            url="https://example.com", community="sub", engagement=10,
            comments=[comment],
        )
        assert len(post.comments) == 1


class TestSentimentResult:
    def test_sentiment_result_creation(self) -> None:
        result = SentimentResult(
            sentiment="positive",
            emotion="enthusiastic",
            confidence=0.95,
            key_point="Users love this feature",
            sarcasm_detected=False,
        )
        assert result.sentiment == "positive"
        assert result.secondary_emotion == "none"
        assert result.emotion_intensity == "moderate"
        assert result.emotional_driver == ""


class TestTheme:
    def test_theme_creation(self) -> None:
        theme = Theme(
            name="Battery Life",
            description="Users report rapid drain",
            percentage=45.0,
            post_count=18,
            sentiment_skew="negative",
            representative_quotes=["Battery dies in 2 hours"],
        )
        assert theme.percentage == 45.0
        assert len(theme.representative_quotes) == 1


class TestJob:
    def test_job_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        job = Job(id="job1", topic="Python", created_at=now, updated_at=now)
        assert job.status == "queued"
        assert job.phase == ""
        assert job.progress_pct == 0.0
        assert job.max_posts == 100
        assert job.time_range == "week"


class TestJobStatistics:
    def test_job_statistics_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        stats = JobStatistics(job_id="job1", created_at=now)
        assert stats.total_posts == 0
        assert stats.sentiment_positive == 0
        assert stats.dominant_emotion == ""
        assert stats.themes_json == "[]"
```

- [ ] **Step 2:** Run the test — confirm it fails (module not found).

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_models.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/db/models.py`.

```python
"""Domain dataclasses — plain data objects with no database coupling.

These dataclasses define the canonical data shapes used throughout Signalstream.
They are used by repositories for mapping database rows and by the rest of the
application for type-safe data passing.

Board amendments incorporated:
- BOARD-001: Expanded Post with phrase_matches, detected_region, detected_language,
  and structured Comment with id, body, author, score, timestamp, depth, replies.
- BOARD-006: SentimentResult includes secondary_emotion, emotion_intensity,
  emotional_driver (matching the full LLM output format).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# Collection-layer models
# ---------------------------------------------------------------------------

@dataclass
class Comment:
    """A structured comment with threading support.

    Preserves reply nesting, authorship, and scores as required by thread-mode
    analysis (BOARD-001).
    """
    id: str
    body: str
    author: str
    score: int
    timestamp: datetime
    depth: int
    replies: list[Comment] = field(default_factory=list)


@dataclass
class Post:
    """A normalized social media post.

    All collectors produce Post instances. Fields cover Reddit's full data model
    plus cross-platform metadata (BOARD-001).
    """
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
        """Unique key for deduplication across collection runs."""
        return f"{self.platform}:{self.id}"


# ---------------------------------------------------------------------------
# Analysis-layer models
# ---------------------------------------------------------------------------

@dataclass
class SentimentResult:
    """Result of per-post sentiment analysis.

    Fields match the full LLM output format from the analysis prompt.
    """
    sentiment: str          # positive | negative | neutral | mixed
    emotion: str            # primary emotion from taxonomy
    confidence: float       # 0.0 - 1.0
    key_point: str          # one-sentence summary
    sarcasm_detected: bool
    secondary_emotion: str = "none"
    emotion_intensity: str = "moderate"  # strong | moderate | mild
    emotional_driver: str = ""


@dataclass
class Theme:
    """A cross-post theme extracted by the thematic analyzer."""
    name: str
    description: str
    percentage: float       # share of posts touching this theme
    post_count: int
    sentiment_skew: str     # positive | negative | neutral
    representative_quotes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Job-layer models
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """Metadata for an analysis job.

    Persisted to the jobs table. Never contains API keys or credentials.
    """
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
    """Aggregated statistics for a completed job.

    Used for trend tracking and the historical dashboard.
    """
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
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_models.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5:** Commit.

```
feat(db): add domain dataclasses — Post, Comment, SentimentResult, Theme, Job

Plain data objects with no ORM coupling. Expanded Post includes
phrase_matches, detected_region, structured Comment with threading
(BOARD-001). SentimentResult includes full LLM output fields.
```

---

## Task 3: Schema Migrations (`signalstream/db/migrations.py`)

> Schema versioning with auto-migrate on startup. New databases created fresh. Existing databases upgraded incrementally.

**Files:**
- Create: `signalstream/db/migrations.py`
- Create: `signalstream/tests/test_db/test_migrations.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_db/test_migrations.py`.

```python
"""Tests for signalstream.db.migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_migrations.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/db/migrations.py`.

```python
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
from typing import Callable

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
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_migrations.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5:** Commit.

```
feat(db): add schema migration manager with versioned migrations

Auto-migrates on startup using PRAGMA user_version. Initial schema
includes jobs, job_statistics, posts (for checkpointing), and
sentiment_results tables with full indexes.
```

---

## Task 4: Repositories (`signalstream/db/repositories.py`)

> All SQL lives here. Parameterized queries only. CRUD for jobs, posts, sentiment results, and statistics.

**Files:**
- Create: `signalstream/db/repositories.py`
- Create: `signalstream/tests/test_db/test_repositories.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_db/test_repositories.py`.

```python
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
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_repositories.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/db/repositories.py`.

```python
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
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_db/test_repositories.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5:** Commit.

```
feat(db): add repositories with parameterized SQL for all domain objects

JobRepository, PostRepository, SentimentResultRepository, and
StatisticsRepository. All queries parameterized. Post deduplication
by platform:post_id. Checkpoint support via get_unanalyzed_row_ids
(BOARD-008).
```

---

## Task 5: LLM Config (`signalstream/llm/config.py`)

> ProviderConfig and CompletionConfig dataclasses. Per-request, never singleton.

**Files:**
- Create: `signalstream/llm/config.py`
- Create: `signalstream/tests/test_llm/test_config.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_llm/test_config.py`.

```python
"""Tests for signalstream.llm.config."""
from __future__ import annotations

import pytest

from signalstream.llm.config import CompletionConfig, ProviderConfig


class TestProviderConfig:
    def test_claude_config(self) -> None:
        cfg = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
        assert cfg.provider == "claude"
        assert cfg.endpoint is None

    def test_ollama_config(self) -> None:
        cfg = ProviderConfig(provider="ollama", model="llama3.1:8b")
        assert cfg.api_key is None
        assert cfg.endpoint is None

    def test_openai_compat_config(self) -> None:
        cfg = ProviderConfig(
            provider="openai-compat",
            api_key="sk-test",
            model="gpt-4o",
            endpoint="https://api.openai.com/v1",
        )
        assert cfg.endpoint == "https://api.openai.com/v1"

    def test_provider_must_be_valid(self) -> None:
        with pytest.raises(ValueError, match="Invalid provider"):
            ProviderConfig(provider="invalid", model="x")


class TestCompletionConfig:
    def test_defaults(self) -> None:
        cfg = CompletionConfig()
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 1024

    def test_custom_values(self) -> None:
        cfg = CompletionConfig(temperature=0.7, max_tokens=300)
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 300

    def test_temperature_bounds(self) -> None:
        with pytest.raises(ValueError, match="temperature"):
            CompletionConfig(temperature=-0.1)
        with pytest.raises(ValueError, match="temperature"):
            CompletionConfig(temperature=2.1)

    def test_max_tokens_positive(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            CompletionConfig(max_tokens=0)
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_config.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/llm/config.py`.

```python
"""LLM provider configuration dataclasses.

Per-request configuration — never a singleton. Built from request headers
by middleware, passed to the job as a parameter, discarded on completion.

Board amendments incorporated:
- BOARD-006: CompletionConfig with temperature=0.0 default for deterministic
  classification.
"""
from __future__ import annotations

from dataclasses import dataclass

VALID_PROVIDERS = frozenset({"claude", "ollama", "openai-compat"})


@dataclass
class ProviderConfig:
    """Per-request LLM provider configuration.

    Attributes:
        provider: One of "claude", "ollama", "openai-compat".
        api_key: API key for the provider. None for Ollama.
        model: Model identifier (e.g., "claude-haiku-4-5-20251001", "llama3.1:8b").
        endpoint: Custom endpoint URL for openai-compat providers. None for others.
    """
    provider: str
    model: str
    api_key: str | None = None
    endpoint: str | None = None

    def __post_init__(self) -> None:
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'. "
                f"Must be one of: {', '.join(sorted(VALID_PROVIDERS))}"
            )


@dataclass
class CompletionConfig:
    """Per-call configuration for LLM requests.

    Attributes:
        temperature: Sampling temperature. 0.0 = deterministic (default for
            sentiment classification). Range: [0.0, 2.0].
        max_tokens: Maximum tokens in the response. Must be > 0.
    """
    temperature: float = 0.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError(
                f"temperature must be between 0.0 and 2.0, got {self.temperature}"
            )
        if self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be positive, got {self.max_tokens}"
            )
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_config.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5:** Commit.

```
feat(llm): add ProviderConfig and CompletionConfig dataclasses

Per-request provider configuration with validation. CompletionConfig
defaults to temperature=0.0 for deterministic classification (BOARD-006).
Provider must be claude, ollama, or openai-compat.
```

---

## Task 6: LLM Provider Base & Implementations (`signalstream/llm/providers/`)

> Abstract provider interface and concrete implementations for Claude, Ollama, and OpenAI-compatible endpoints.

**Files:**
- Create: `signalstream/llm/providers/base.py`
- Create: `signalstream/llm/providers/claude.py`
- Create: `signalstream/llm/providers/ollama.py`
- Create: `signalstream/llm/providers/openai_compat.py`
- Create: `signalstream/tests/test_llm/test_providers.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_llm/test_providers.py`.

```python
"""Tests for signalstream.llm.providers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, Mock

import pytest

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider
from signalstream.llm.providers.claude import ClaudeProvider
from signalstream.llm.providers.ollama import OllamaProvider
from signalstream.llm.providers.openai_compat import OpenAICompatProvider


class TestBaseProvider:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseProvider(ProviderConfig(provider="claude", model="x", api_key="k"))


class TestClaudeProvider:
    def test_complete_calls_anthropic(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Positive sentiment")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            result = provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
            )

        assert result == "Positive sentiment"
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_system_prompt_as_top_level_param(self) -> None:
        """Claude's system prompt goes as a top-level kwarg, not in messages."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            provider.complete(
                messages=[
                    {"role": "system", "content": "You are an analyst."},
                    {"role": "user", "content": "Analyze this."},
                ],
                model="claude-haiku-4-5-20251001",
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are an analyst."
        # Messages should only contain non-system messages
        assert all(m["role"] != "system" for m in call_kwargs["messages"])

    def test_custom_completion_config(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                config=CompletionConfig(temperature=0.5, max_tokens=300),
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 300


class TestOllamaProvider:
    def test_complete_sends_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Neutral analysis"}
        mock_response.raise_for_status = MagicMock()

        with patch("signalstream.llm.providers.ollama.requests.post", return_value=mock_response) as mock_post:
            config = ProviderConfig(provider="ollama", model="gemma2:9b")
            provider = OllamaProvider(config)
            result = provider.complete(
                messages=[
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "Analyze this."},
                ],
                model="gemma2:9b",
            )

        assert result == "Neutral analysis"
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["model"] == "gemma2:9b"
        assert payload["system"] == "Be concise."
        assert payload["prompt"] == "Analyze this."
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.0

    def test_default_endpoint(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        provider = OllamaProvider(config)
        assert provider._base_url == "http://localhost:11434"

    def test_custom_endpoint(self) -> None:
        config = ProviderConfig(
            provider="ollama", model="gemma2:9b",
            endpoint="http://localhost:11435",
        )
        provider = OllamaProvider(config)
        assert provider._base_url == "http://localhost:11435"


class TestOpenAICompatProvider:
    def test_complete_sends_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OpenAI result"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("signalstream.llm.providers.openai_compat.requests.post", return_value=mock_response) as mock_post:
            config = ProviderConfig(
                provider="openai-compat",
                api_key="sk-test",
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
            )
            provider = OpenAICompatProvider(config)
            result = provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="gpt-4o",
            )

        assert result == "OpenAI result"
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["model"] == "gpt-4o"
        assert payload["temperature"] == 0.0
        headers = call_kwargs[1]["headers"]
        assert "Bearer sk-test" in headers["Authorization"]

    def test_requires_endpoint(self) -> None:
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test", model="gpt-4o",
        )
        with pytest.raises(ValueError, match="endpoint"):
            OpenAICompatProvider(config)
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_providers.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/llm/providers/base.py`.

```python
"""Abstract base for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from signalstream.llm.config import CompletionConfig, ProviderConfig


class BaseProvider(ABC):
    """Abstract LLM provider interface.

    Providers are stateless per-request objects. Each job creates a provider
    instance with credentials from the request. No singletons.

    Args:
        provider_config: The provider configuration for this instance.
    """

    def __init__(self, provider_config: ProviderConfig) -> None:
        self._provider_config = provider_config

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        """Send a completion request to the LLM provider.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                System messages are extracted and handled per-provider.
            model: The model identifier to use.
            config: Optional completion config. Defaults to CompletionConfig()
                (temperature=0.0, max_tokens=1024).

        Returns:
            The completion text from the model.

        Raises:
            Exception: Provider-specific errors (auth, rate limit, etc.).
        """
        ...
```

- [ ] **Step 4:** Implement `signalstream/llm/providers/claude.py`.

```python
"""Claude (Anthropic) LLM provider."""
from __future__ import annotations

import logging
import random
import time

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Errors that should not be retried
_NON_RETRYABLE = tuple()  # populated at runtime if anthropic is available


def _get_non_retryable() -> tuple:
    if anthropic is None:
        return ()
    return (
        anthropic.BadRequestError,
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
    )


class ClaudeProvider(BaseProvider):
    """Anthropic Claude API provider.

    System prompts are passed as a top-level parameter (not in messages)
    for prompt injection defense.
    """

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        if anthropic is None:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self._client = anthropic.Anthropic(api_key=provider_config.api_key)

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()
        non_retryable = _get_non_retryable()

        # Extract system message — Claude takes it as a top-level param
        system_prompt = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                user_messages.append(msg)

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                kwargs: dict = {
                    "model": model,
                    "max_tokens": cfg.max_tokens,
                    "temperature": cfg.temperature,
                    "messages": user_messages,
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                response = self._client.messages.create(**kwargs)

                if response.content and len(response.content) > 0:
                    return response.content[0].text
                return ""

            except non_retryable:
                raise

            except Exception as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Claude API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable, but satisfies type checker
```

- [ ] **Step 5:** Implement `signalstream/llm/providers/ollama.py`.

```python
"""Ollama local LLM provider."""
from __future__ import annotations

import logging
import random
import time

import requests

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(BaseProvider):
    """Local Ollama provider.

    Uses the /api/generate endpoint. No API key required.
    """

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        self._base_url = (provider_config.endpoint or _DEFAULT_OLLAMA_URL).rstrip("/")

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()

        # Extract system and user content from messages
        system_prompt = ""
        user_content = ""
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                user_content = msg["content"]

        payload: dict = {
            "model": model,
            "prompt": user_content,
            "stream": False,
            "options": {
                "temperature": cfg.temperature,
                "num_predict": cfg.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                    timeout=120,
                )
                response.raise_for_status()
                return response.json().get("response", "")

            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Ollama request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable
```

- [ ] **Step 6:** Implement `signalstream/llm/providers/openai_compat.py`.

```python
"""OpenAI-compatible endpoint provider.

Works with OpenAI, Groq, Together, LM Studio, local vLLM, etc.
"""
from __future__ import annotations

import logging
import random
import time

import requests

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(BaseProvider):
    """Generic OpenAI-compatible chat completions provider.

    Sends requests to ``{endpoint}/chat/completions``.

    Args:
        provider_config: Must include a non-None endpoint.

    Raises:
        ValueError: If endpoint is not set.
    """

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        if not provider_config.endpoint:
            raise ValueError(
                "OpenAI-compatible provider requires an endpoint URL"
            )
        self._endpoint = provider_config.endpoint.rstrip("/")
        self._api_key = provider_config.api_key or ""

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()

        payload = {
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self._endpoint}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "OpenAI-compat request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable
```

- [ ] **Step 7:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_providers.py -v
```

Expected: 10 tests pass.

- [ ] **Step 8:** Commit.

```
feat(llm): add provider implementations — Claude, Ollama, OpenAI-compat

Abstract BaseProvider with complete() interface using CompletionConfig.
Claude separates system prompts as top-level param. Ollama uses
/api/generate. OpenAI-compat wraps /chat/completions. All have
retry with exponential backoff and jitter.
```

---

## Task 7: SSRF Safety (`signalstream/llm/safety.py`)

> SSRF validation for user-configurable endpoints with localhost exemption (BOARD-007).

**Files:**
- Create: `signalstream/llm/safety.py`
- Create: `signalstream/tests/test_llm/test_safety.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_llm/test_safety.py`.

```python
"""Tests for signalstream.llm.safety — SSRF validation."""
from __future__ import annotations

import pytest

from signalstream.llm.safety import validate_endpoint, SSRFError


class TestValidateEndpoint:
    """SSRF validation tests with localhost exemption (BOARD-007)."""

    def test_allows_https_public_endpoint(self) -> None:
        """Standard HTTPS endpoints pass validation."""
        validate_endpoint("https://api.openai.com/v1")

    def test_rejects_http_non_localhost(self) -> None:
        """HTTP is rejected for non-localhost addresses."""
        with pytest.raises(SSRFError, match="HTTPS required"):
            validate_endpoint("http://api.openai.com/v1")

    def test_allows_http_localhost(self) -> None:
        """HTTP is allowed for localhost (BOARD-007 exemption)."""
        validate_endpoint("http://localhost:11434")

    def test_allows_http_127_0_0_1(self) -> None:
        """HTTP is allowed for 127.0.0.1."""
        validate_endpoint("http://127.0.0.1:1234")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(SSRFError, match="scheme"):
            validate_endpoint("file:///etc/passwd")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(SSRFError, match="scheme"):
            validate_endpoint("ftp://example.com/file")

    def test_rejects_cloud_metadata_ip(self) -> None:
        """Block link-local / cloud metadata addresses."""
        with pytest.raises(SSRFError):
            validate_endpoint("https://169.254.169.254/latest/meta-data/")

    def test_rejects_private_10_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://10.0.0.1:8080/v1")

    def test_rejects_private_172_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://172.16.0.1:8080/v1")

    def test_rejects_private_192_168_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://192.168.1.1:8080/v1")

    def test_rejects_raw_ip_non_localhost(self) -> None:
        """Require hostnames for non-localhost (prevents DNS rebinding bypass)."""
        with pytest.raises(SSRFError):
            validate_endpoint("https://93.184.216.34/v1")

    def test_allows_raw_ip_localhost(self) -> None:
        """127.x.x.x IPs are exempt from the hostname requirement."""
        validate_endpoint("http://127.0.0.1:1234/v1")

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("")

    def test_rejects_no_host(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https:///path")

    def test_localhost_still_has_timeout_protection(self) -> None:
        """Localhost exemption note: this test documents behavior, not enforces it.
        Actual timeout enforcement is in the HTTP client, not in validate_endpoint."""
        # validate_endpoint should pass for localhost
        validate_endpoint("http://localhost:8000")
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_safety.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/llm/safety.py`.

```python
"""SSRF validation for user-configurable LLM endpoints.

Validates endpoints before any HTTP request is made to prevent:
- Access to internal services via private IPs
- Cloud metadata access (169.254.x.x)
- File system access (file://)
- DNS rebinding attacks (raw IPs)

Localhost exemption (BOARD-007): Endpoints resolving to 127.0.0.0/8 or ::1
are exempt from the HTTPS requirement and private network block, to support
local inference servers (LM Studio, vLLM, llama.cpp, text-generation-webui).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Networks that are blocked for non-localhost endpoints
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),      # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),              # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),             # IPv6 link-local
]

# Localhost ranges — exempt from HTTPS and private network blocks
_LOCALHOST_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]

_LOCALHOST_HOSTNAMES = frozenset({"localhost"})


class SSRFError(Exception):
    """Raised when an endpoint fails SSRF validation."""


def _is_localhost(host: str) -> bool:
    """Check if a host is a localhost address or hostname."""
    if host.lower() in _LOCALHOST_HOSTNAMES:
        return True
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _LOCALHOST_NETWORKS)
    except ValueError:
        return False


def _is_raw_ip(host: str) -> bool:
    """Check if a host string is a raw IP address."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_and_check(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname and return all addresses. Raises SSRFError if blocked."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFError(f"Cannot resolve hostname '{host}': {e}") from e

    addresses = []
    for family, _type, _proto, _canonname, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        addresses.append(addr)

    return addresses


def validate_endpoint(url: str) -> None:
    """Validate a user-provided endpoint URL against SSRF attacks.

    Args:
        url: The endpoint URL to validate.

    Raises:
        SSRFError: If the URL fails any validation check.
    """
    if not url or not url.strip():
        raise SSRFError("Endpoint URL is empty")

    parsed = urlparse(url)

    # 1. Scheme check
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFError(
            f"Invalid URL scheme '{scheme}'. Only http/https allowed."
        )

    # 2. Host check
    host = parsed.hostname
    if not host:
        raise SSRFError("Endpoint URL has no host")

    is_local = _is_localhost(host)

    # 3. HTTPS required for non-localhost
    if scheme == "http" and not is_local:
        raise SSRFError(
            f"HTTPS required for non-localhost endpoints (got http://{host})"
        )

    # 4. Raw IP rejection for non-localhost
    if _is_raw_ip(host) and not is_local:
        raise SSRFError(
            f"Raw IP addresses not allowed for non-localhost endpoints. "
            f"Use a hostname instead of {host}."
        )

    # 5. If localhost, skip network checks (BOARD-007 exemption)
    if is_local:
        logger.debug("Localhost endpoint exempted from SSRF network checks: %s", url)
        return

    # 6. Resolve and check all addresses against blocked networks
    addresses = _resolve_and_check(host)
    for addr in addresses:
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise SSRFError(
                    f"Endpoint '{host}' resolves to blocked network "
                    f"{network} (address: {addr})"
                )

    logger.debug("Endpoint passed SSRF validation: %s", url)
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_safety.py -v
```

Expected: 14 tests pass.

- [ ] **Step 5:** Commit.

```
feat(llm): add SSRF validation with localhost exemption (BOARD-007)

Validates user-provided endpoints against private networks, cloud
metadata, file:// schemes, and raw IPs. Localhost/127.x.x.x is
exempt from HTTPS and private network blocks to support local
inference servers.
```

---

## Task 8: LLM Router (`signalstream/llm/router.py`)

> Provider selection and pre-flight check. No auto-fallback.

**Files:**
- Create: `signalstream/llm/router.py`
- Create: `signalstream/tests/test_llm/test_router.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_llm/test_router.py`.

```python
"""Tests for signalstream.llm.router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from signalstream.llm.config import ProviderConfig
from signalstream.llm.router import LLMRouter


class TestLLMRouter:
    def test_creates_claude_provider(self) -> None:
        config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
        with patch("signalstream.llm.router.ClaudeProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            router = LLMRouter(config)
            assert router.provider is not None
            mock_cls.assert_called_once_with(config)

    def test_creates_ollama_provider(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        with patch("signalstream.llm.router.OllamaProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            router = LLMRouter(config)
            assert router.provider is not None

    def test_creates_openai_compat_with_ssrf_check(self) -> None:
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test",
            model="gpt-4o", endpoint="https://api.openai.com/v1",
        )
        with patch("signalstream.llm.router.OpenAICompatProvider") as mock_cls, \
             patch("signalstream.llm.router.validate_endpoint") as mock_validate:
            mock_cls.return_value = MagicMock()
            router = LLMRouter(config)
            mock_validate.assert_called_once_with("https://api.openai.com/v1")

    def test_openai_compat_ssrf_failure_raises(self) -> None:
        from signalstream.llm.safety import SSRFError
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test",
            model="gpt-4o", endpoint="http://10.0.0.1:8080/v1",
        )
        with patch("signalstream.llm.router.validate_endpoint", side_effect=SSRFError("blocked")):
            with pytest.raises(SSRFError):
                LLMRouter(config)

    def test_preflight_check_success(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "pong"

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.preflight_check()
            assert result is True

    def test_preflight_check_failure(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = ConnectionError("refused")

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.preflight_check()
            assert result is False

    def test_complete_delegates_to_provider(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "result text"

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.complete(
                messages=[{"role": "user", "content": "test"}],
                model="gemma2:9b",
            )
            assert result == "result text"
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_router.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/llm/router.py`.

```python
"""LLM router — provider selection and pre-flight validation.

No auto-fallback between providers. The user picks their provider explicitly.
Pre-flight check confirms the provider is reachable before the pipeline starts.
"""
from __future__ import annotations

import logging

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider
from signalstream.llm.providers.claude import ClaudeProvider
from signalstream.llm.providers.ollama import OllamaProvider
from signalstream.llm.providers.openai_compat import OpenAICompatProvider
from signalstream.llm.safety import validate_endpoint

logger = logging.getLogger(__name__)

_PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
    "openai-compat": OpenAICompatProvider,
}


class LLMRouter:
    """Routes LLM requests to the configured provider.

    Validates the configuration at construction time (SSRF checks for custom
    endpoints). Provides a pre-flight check method for the pipeline to call
    before starting work.

    Args:
        config: Provider configuration for this job.
    """

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

        # SSRF validation for custom endpoints (before creating the provider)
        if config.provider == "openai-compat" and config.endpoint:
            validate_endpoint(config.endpoint)

        provider_cls = _PROVIDER_MAP.get(config.provider)
        if provider_cls is None:
            raise ValueError(f"Unknown provider: {config.provider}")

        self._provider: BaseProvider = provider_cls(config)
        logger.info("LLM router initialized with provider: %s", config.provider)

    @property
    def provider(self) -> BaseProvider:
        """The underlying provider instance."""
        return self._provider

    def preflight_check(self) -> bool:
        """Test that the provider is reachable with a minimal API call.

        Returns:
            True if the provider responded successfully, False otherwise.
        """
        try:
            response = self._provider.complete(
                messages=[{"role": "user", "content": "ping"}],
                model=self._config.model,
                config=CompletionConfig(temperature=0.0, max_tokens=5),
            )
            logger.info(
                "Pre-flight check passed for %s (response length: %d)",
                self._config.provider, len(response),
            )
            return True
        except Exception as e:
            logger.error(
                "Pre-flight check failed for %s: %s",
                self._config.provider, e,
            )
            return False

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        """Delegate a completion request to the provider.

        Args:
            messages: Message list with role/content dicts.
            model: Model identifier.
            config: Optional completion config.

        Returns:
            The completion text.
        """
        return self._provider.complete(messages, model, config)
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_llm/test_router.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5:** Commit.

```
feat(llm): add LLM router with SSRF pre-validation and pre-flight check

Provider selection without auto-fallback. SSRF validation runs before
provider construction for openai-compat endpoints. Pre-flight check
confirms reachability before pipeline starts.
```

---

## Task 9: Resilient HTTP Client (`signalstream/collectors/http.py`)

> Shared HTTP client with retry, exponential backoff + jitter, Retry-After parsing, timeouts, and response size limits.

**Files:**
- Create: `signalstream/collectors/http.py`
- Create: `signalstream/tests/test_collectors/test_http.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_collectors/test_http.py`.

```python
"""Tests for signalstream.collectors.http — resilient HTTP client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from signalstream.collectors.http import ResilientClient, RateLimiter


class TestRateLimiter:
    def test_allows_first_request(self) -> None:
        limiter = RateLimiter(rpm=30)
        # Should not raise or sleep
        limiter.wait_if_needed()
        limiter.record_request()

    def test_tracks_request_count(self) -> None:
        limiter = RateLimiter(rpm=30)
        for _ in range(5):
            limiter.record_request()
        assert limiter.request_count_in_window >= 5


class TestResilientClient:
    def test_get_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}

        with patch.object(requests.Session, "get", return_value=mock_response):
            client = ResilientClient(user_agent="Test/1.0")
            response = client.get("https://example.com/api")
            assert response.json() == {"data": "test"}

    def test_user_agent_set(self) -> None:
        client = ResilientClient(user_agent="Signalstream/0.1.0")
        assert client._session.headers["User-Agent"] == "Signalstream/0.1.0"

    def test_timeout_defaults(self) -> None:
        client = ResilientClient()
        assert client._connect_timeout > 0
        assert client._read_timeout > 0

    def test_retries_on_server_error(self) -> None:
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=error_response
        )
        error_response.headers = {}

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {"ok": True}
        ok_response.headers = {}

        with patch.object(
            requests.Session, "get",
            side_effect=[error_response, ok_response],
        ), patch("signalstream.collectors.http.time.sleep"):
            client = ResilientClient(retries=2)
            response = client.get("https://example.com/api")
            assert response.json() == {"ok": True}

    def test_respects_response_size_limit(self) -> None:
        client = ResilientClient(max_response_bytes=100)
        assert client._max_response_bytes == 100
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_http.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/collectors/http.py`.

```python
"""Resilient HTTP client with retry, backoff, rate limiting, and size limits.

Shared by collectors and can be used by any component that needs robust HTTP.
"""
from __future__ import annotations

import logging
import random
import time
import threading
from collections import deque

import requests

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter.

    Args:
        rpm: Maximum requests per minute.
    """

    def __init__(self, rpm: int = 30) -> None:
        self._rpm = rpm
        self._window: deque[float] = deque()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block until a request slot is available."""
        with self._lock:
            now = time.monotonic()
            # Purge requests older than 60 seconds
            while self._window and self._window[0] < now - 60:
                self._window.popleft()

            if len(self._window) >= self._rpm:
                oldest = self._window[0]
                sleep_time = 60 - (now - oldest) + 0.1
                if sleep_time > 0:
                    logger.debug("Rate limiter: sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)

    def record_request(self) -> None:
        """Record that a request was made."""
        with self._lock:
            self._window.append(time.monotonic())

    @property
    def request_count_in_window(self) -> int:
        """Number of requests in the current 60-second window."""
        with self._lock:
            now = time.monotonic()
            while self._window and self._window[0] < now - 60:
                self._window.popleft()
            return len(self._window)


class ResilientClient:
    """HTTP client with automatic retry, exponential backoff, and rate limiting.

    Args:
        user_agent: User-Agent header value.
        retries: Maximum number of retry attempts per request.
        base_delay: Base delay in seconds for exponential backoff.
        connect_timeout: Connection timeout in seconds.
        read_timeout: Read timeout in seconds.
        max_response_bytes: Maximum response size in bytes (0 = unlimited).
        rate_limiter: Optional RateLimiter instance.
    """

    def __init__(
        self,
        user_agent: str = "Signalstream/0.1.0",
        retries: int = 3,
        base_delay: float = 2.0,
        connect_timeout: float = 30.0,
        read_timeout: float = 120.0,
        max_response_bytes: int = 10 * 1024 * 1024,  # 10 MB
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._retries = retries
        self._base_delay = base_delay
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_response_bytes = max_response_bytes
        self._rate_limiter = rate_limiter

    def get(
        self,
        url: str,
        params: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        """Send a GET request with retry and backoff.

        Args:
            url: The URL to request.
            params: Optional query parameters.
            **kwargs: Additional keyword arguments passed to requests.Session.get.

        Returns:
            The successful response.

        Raises:
            requests.exceptions.RequestException: After all retries exhausted.
        """
        return self._request("GET", url, params=params, **kwargs)

    def post(
        self,
        url: str,
        json: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        """Send a POST request with retry and backoff.

        Args:
            url: The URL to request.
            json: Optional JSON payload.
            **kwargs: Additional keyword arguments.

        Returns:
            The successful response.

        Raises:
            requests.exceptions.RequestException: After all retries exhausted.
        """
        return self._request("POST", url, json=json, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Internal request handler with retry logic."""
        kwargs.setdefault("timeout", (self._connect_timeout, self._read_timeout))

        last_exc: Exception | None = None

        for attempt in range(self._retries + 1):
            try:
                if self._rate_limiter:
                    self._rate_limiter.wait_if_needed()
                    self._rate_limiter.record_request()

                response = self._session.request(method, url, **kwargs)

                # Check response size
                content_length = response.headers.get("Content-Length")
                if (
                    self._max_response_bytes > 0
                    and content_length
                    and int(content_length) > self._max_response_bytes
                ):
                    raise requests.exceptions.ContentDecodingError(
                        f"Response too large: {content_length} bytes "
                        f"(limit: {self._max_response_bytes})"
                    )

                # Handle rate limiting with Retry-After
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and attempt < self._retries:
                        try:
                            delay = float(retry_after)
                        except (ValueError, TypeError):
                            delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "Rate limited (429), retry-after: %.1fs (attempt %d/%d)",
                            delay, attempt + 1, self._retries + 1,
                        )
                        time.sleep(delay)
                        continue

                # Retry on server errors (5xx)
                if response.status_code >= 500 and attempt < self._retries:
                    delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code, delay, attempt + 1, self._retries + 1,
                    )
                    time.sleep(delay)
                    continue

                return response

            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < self._retries:
                    delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "%s request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                        method, url, attempt + 1, self._retries + 1, e, delay,
                    )
                    time.sleep(delay)

        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        """Close the underlying session."""
        self._session.close()
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_http.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5:** Commit.

```
feat(collectors): add resilient HTTP client with retry, backoff, rate limiting

ResilientClient wraps requests.Session with exponential backoff + jitter,
Retry-After header parsing, sliding-window rate limiting, response size
limits, and configurable timeouts.
```

---

## Task 10: Collector Base & nh3 Sanitization (`signalstream/collectors/base.py`)

> Abstract collector interface with mandatory nh3 sanitization of all text fields.

**Files:**
- Create: `signalstream/collectors/base.py`
- Create: `signalstream/tests/test_collectors/test_base.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_collectors/test_base.py`.

```python
"""Tests for signalstream.collectors.base — sanitization and abstract interface."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalstream.collectors.base import sanitize_post, BaseCollector
from signalstream.db.models import Comment, Post


def _make_post(**overrides) -> Post:
    defaults = dict(
        platform="reddit", id="p1", author="user1",
        text="Clean text", title="Clean title",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="test", engagement=10,
    )
    defaults.update(overrides)
    return Post(**defaults)


class TestSanitizePost:
    def test_strips_script_tags_from_text(self) -> None:
        post = _make_post(text='Hello <script>alert("xss")</script> world')
        sanitized = sanitize_post(post)
        assert "<script>" not in sanitized.text
        assert "Hello" in sanitized.text
        assert "world" in sanitized.text

    def test_strips_script_tags_from_title(self) -> None:
        post = _make_post(title='Title <script>evil()</script>')
        sanitized = sanitize_post(post)
        assert "<script>" not in (sanitized.title or "")

    def test_sanitizes_comment_bodies(self) -> None:
        comment = Comment(
            id="c1", body='<img src=x onerror=alert(1)> Nice post',
            author="u1", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1,
        )
        post = _make_post(comments=[comment])
        sanitized = sanitize_post(post)
        assert "onerror" not in sanitized.comments[0].body

    def test_sanitizes_nested_replies(self) -> None:
        reply = Comment(
            id="r1", body='<a href="javascript:void(0)">click</a>',
            author="u2", score=1,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=2,
        )
        comment = Comment(
            id="c1", body="Safe", author="u1", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1, replies=[reply],
        )
        post = _make_post(comments=[comment])
        sanitized = sanitize_post(post)
        assert "javascript:" not in sanitized.comments[0].replies[0].body

    def test_preserves_clean_text(self) -> None:
        post = _make_post(text="This is perfectly clean text with no HTML.")
        sanitized = sanitize_post(post)
        assert sanitized.text == "This is perfectly clean text with no HTML."

    def test_handles_none_title(self) -> None:
        post = _make_post(title=None)
        sanitized = sanitize_post(post)
        assert sanitized.title is None

    def test_returns_new_post_object(self) -> None:
        post = _make_post()
        sanitized = sanitize_post(post)
        assert sanitized is not post


class TestBaseCollector:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseCollector()  # type: ignore[abstract]
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_base.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/collectors/base.py`.

```python
"""Abstract collector interface and content sanitization.

Every collector inherits from BaseCollector and uses sanitize_post() to clean
all text fields before returning results. Sanitization is mandatory — it is
enforced by the base class's collect() template method.

Uses nh3 for HTML sanitization (BOARD-003).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import replace

import nh3

from signalstream.db.models import Comment, Post

logger = logging.getLogger(__name__)


def _sanitize_text(text: str) -> str:
    """Strip all HTML tags from text, keeping only safe content."""
    return nh3.clean(text, tags=set())


def _sanitize_comment(comment: Comment) -> Comment:
    """Recursively sanitize a comment and its replies."""
    return Comment(
        id=comment.id,
        body=_sanitize_text(comment.body),
        author=comment.author,
        score=comment.score,
        timestamp=comment.timestamp,
        depth=comment.depth,
        replies=[_sanitize_comment(r) for r in comment.replies],
    )


def sanitize_post(post: Post) -> Post:
    """Sanitize all text fields in a Post using nh3.

    Applies nh3.clean() to post.text, post.title, and all comment.body fields
    recursively. Returns a new Post object — the original is not mutated.

    This is not optional — every collector must call this before returning
    results (enforced by BaseCollector).
    """
    return replace(
        post,
        text=_sanitize_text(post.text),
        title=_sanitize_text(post.title) if post.title is not None else None,
        comments=[_sanitize_comment(c) for c in post.comments],
    )


class BaseCollector(ABC):
    """Abstract base for data collectors.

    Subclasses implement _collect_raw() to fetch posts from a platform.
    The public collect() method calls _collect_raw() and then sanitizes
    all results automatically.
    """

    def collect(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        """Collect posts matching a query, with automatic sanitization.

        Args:
            query: The search query / topic.
            max_posts: Maximum number of posts to collect.
            time_range: Time range filter (e.g., "day", "week", "month").

        Returns:
            List of sanitized Post objects.
        """
        raw_posts = self._collect_raw(query, max_posts=max_posts, time_range=time_range)
        sanitized = [sanitize_post(p) for p in raw_posts]
        logger.info(
            "Collected and sanitized %d posts for query '%s'",
            len(sanitized), query,
        )
        return sanitized

    @abstractmethod
    def _collect_raw(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        """Fetch raw (unsanitized) posts from the platform.

        Subclasses implement this method. The base class handles sanitization.

        Args:
            query: The search query.
            max_posts: Maximum posts to return.
            time_range: Time range filter.

        Returns:
            List of raw Post objects (will be sanitized by collect()).
        """
        ...
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_base.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5:** Commit.

```
feat(collectors): add BaseCollector with mandatory nh3 sanitization (BOARD-003)

sanitize_post() strips all HTML from text, title, and nested comment
bodies using nh3.clean(). BaseCollector enforces sanitization via
template method — subclasses implement _collect_raw(), base class
sanitizes automatically.
```

---

## Task 11: Reddit Collector (`signalstream/collectors/reddit.py`)

> Public JSON collector with pagination, deduplication, and rate limiting. Optional PRAW upgrade path.

**Files:**
- Create: `signalstream/collectors/reddit.py`
- Create: `signalstream/tests/test_collectors/test_reddit.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_collectors/test_reddit.py`.

```python
"""Tests for signalstream.collectors.reddit."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from signalstream.collectors.reddit import RedditCollector


def _make_reddit_response(
    posts: list[dict],
    after: str | None = None,
) -> dict:
    """Build a mock Reddit JSON search response."""
    children = []
    for p in posts:
        children.append({
            "kind": "t3",
            "data": {
                "id": p.get("id", "abc123"),
                "title": p.get("title", "Test Post"),
                "selftext": p.get("selftext", "Test content"),
                "author": p.get("author", "testuser"),
                "subreddit": p.get("subreddit", "testsubreddit"),
                "score": p.get("score", 42),
                "upvote_ratio": p.get("upvote_ratio", 0.95),
                "permalink": p.get("permalink", "/r/test/comments/abc123/test_post/"),
                "created_utc": p.get("created_utc", 1735689600),
                "link_flair_text": p.get("flair", None),
                "is_crosspost_child": False,
                "crosspost_parent": None,
                "num_comments": 5,
            },
        })
    return {
        "data": {
            "children": children,
            "after": after,
        }
    }


class TestRedditCollector:
    def test_collects_posts_from_search(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [{"id": "p1", "title": "First Post"}]
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("Python", max_posts=10)

        assert len(posts) == 1
        assert posts[0].platform == "reddit"
        assert posts[0].community == "testsubreddit"

    def test_deduplicates_by_post_id(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [
                {"id": "p1", "title": "Duplicate"},
                {"id": "p1", "title": "Duplicate"},
            ]
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=10)

        assert len(posts) == 1

    def test_pagination_with_after_cursor(self) -> None:
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = _make_reddit_response(
            [{"id": "p1"}], after="cursor123"
        )

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = _make_reddit_response(
            [{"id": "p2"}], after=None
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = [page1, page2]
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=10)

        assert len(posts) == 2
        assert mock_client.get.call_count == 2

    def test_stops_at_max_posts(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [{"id": f"p{i}"} for i in range(25)],
            after="more_pages",
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=5)

        assert len(posts) <= 5

    def test_user_agent_header(self) -> None:
        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _make_reddit_response([])
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            RedditCollector()
            call_kwargs = mock_client_cls.call_args[1]
            assert "Signalstream" in call_kwargs.get("user_agent", "")
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_reddit.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/collectors/reddit.py`.

```python
"""Reddit collector — public JSON endpoints with optional PRAW upgrade path.

Default mode uses public JSON endpoints (no API key needed). If
REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set as environment variables,
uses PRAW automatically for higher rate limits.

Rate limited to 30 RPM for public JSON. User-Agent identifies the tool.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from signalstream.collectors.base import BaseCollector
from signalstream.collectors.http import RateLimiter, ResilientClient
from signalstream.db.models import Comment, Post

logger = logging.getLogger(__name__)

_USER_AGENT = "Signalstream/0.1.0"
_REDDIT_BASE_URL = "https://www.reddit.com"
_PUBLIC_JSON_RPM = 30


class RedditCollector(BaseCollector):
    """Collect posts from Reddit via public JSON endpoints.

    Supports pagination via the ``after`` cursor. Deduplicates posts by ID.

    Args:
        user_agent: User-Agent header value. Defaults to Signalstream/0.1.0.
    """

    def __init__(self, user_agent: str = _USER_AGENT) -> None:
        self._rate_limiter = RateLimiter(rpm=_PUBLIC_JSON_RPM)
        self._client = ResilientClient(
            user_agent=user_agent,
            retries=3,
            base_delay=2.0,
            rate_limiter=self._rate_limiter,
        )

    def _collect_raw(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        """Fetch posts from Reddit's public JSON search endpoint.

        Args:
            query: Search query string.
            max_posts: Maximum posts to return.
            time_range: One of "hour", "day", "week", "month", "year", "all".

        Returns:
            List of raw (unsanitized) Post objects.
        """
        posts: list[Post] = []
        seen_ids: set[str] = set()
        after: str | None = None

        # Reddit returns at most 25 per page with public JSON
        per_page = min(25, max_posts)

        while len(posts) < max_posts:
            params: dict = {
                "q": query,
                "sort": "relevance",
                "t": time_range,
                "limit": per_page,
                "raw_json": 1,
            }
            if after:
                params["after"] = after

            try:
                response = self._client.get(
                    f"{_REDDIT_BASE_URL}/search.json",
                    params=params,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Reddit search returned status %d", response.status_code
                    )
                    break

                data = response.json()

            except Exception as e:
                logger.error("Reddit search request failed: %s", e)
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                if len(posts) >= max_posts:
                    break

                post_data = child.get("data", {})
                post_id = post_data.get("id", "")
                dedup_key = f"reddit:{post_id}"

                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)

                post = self._parse_post(post_data)
                post.phrase_matches = [query]
                posts.append(post)

            # Check for next page
            after = data.get("data", {}).get("after")
            if not after:
                break

        logger.info(
            "Reddit collected %d posts for query '%s' (time_range=%s)",
            len(posts), query, time_range,
        )
        return posts

    @staticmethod
    def _parse_post(data: dict) -> Post:
        """Parse a Reddit post JSON object into a Post dataclass."""
        created_utc = data.get("created_utc", 0)
        timestamp = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        permalink = data.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""

        return Post(
            platform="reddit",
            id=data.get("id", ""),
            author=data.get("author", "[deleted]"),
            text=data.get("selftext", ""),
            title=data.get("title"),
            timestamp=timestamp,
            url=url,
            community=data.get("subreddit", ""),
            engagement=data.get("score", 0),
            upvote_ratio=data.get("upvote_ratio"),
            flair=data.get("link_flair_text"),
            is_crosspost=bool(data.get("is_crosspost_child", False)),
            crosspost_source=data.get("crosspost_parent"),
        )
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_collectors/test_reddit.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5:** Commit.

```
feat(collectors): add Reddit collector with public JSON, pagination, dedup

RedditCollector fetches from reddit.com/search.json with pagination
via after cursor. Deduplicates by post ID. Rate limited to 30 RPM.
Sanitization enforced by BaseCollector. User-Agent: Signalstream/0.1.0.
```

---

## Task 12: Analysis Schemas & Validation (`signalstream/analyzers/schemas.py`)

> Output dataclasses and validation functions for LLM responses (BOARD-012).

**Files:**
- Create: `signalstream/analyzers/schemas.py`
- Create: `signalstream/tests/test_analyzers/test_schemas.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_analyzers/test_schemas.py`.

```python
"""Tests for signalstream.analyzers.schemas — output validation (BOARD-012)."""
from __future__ import annotations

import pytest

from signalstream.analyzers.schemas import (
    ValidationError,
    validate_sentiment_result,
    validate_theme,
    VALID_SENTIMENTS,
    VALID_EMOTIONS,
)
from signalstream.db.models import SentimentResult, Theme


class TestValidateSentimentResult:
    def test_valid_result(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "Users love this feature",
            "sarcasm_detected": False,
        }
        result = validate_sentiment_result(raw)
        assert isinstance(result, SentimentResult)
        assert result.sentiment == "positive"
        assert result.confidence == 0.9

    def test_invalid_sentiment_value(self) -> None:
        raw = {
            "sentiment": "happy",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="sentiment"):
            validate_sentiment_result(raw)

    def test_invalid_emotion_value(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "flabbergasted",
            "confidence": 0.9,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="emotion"):
            validate_sentiment_result(raw)

    def test_confidence_out_of_range_high(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 1.5,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_confidence_out_of_range_low(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": -0.1,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_key_point_too_long(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "x" * 201,
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="key_point"):
            validate_sentiment_result(raw)

    def test_key_point_empty(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="key_point"):
            validate_sentiment_result(raw)

    def test_missing_required_field(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            # missing confidence
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_optional_fields_have_defaults(self) -> None:
        raw = {
            "sentiment": "neutral",
            "emotion": "curious",
            "confidence": 0.7,
            "key_point": "Interesting topic",
            "sarcasm_detected": False,
        }
        result = validate_sentiment_result(raw)
        assert result.secondary_emotion == "none"
        assert result.emotion_intensity == "moderate"
        assert result.emotional_driver == ""

    def test_with_optional_fields(self) -> None:
        raw = {
            "sentiment": "mixed",
            "emotion": "skeptical",
            "secondary_emotion": "curious",
            "emotion_intensity": "strong",
            "confidence": 0.6,
            "key_point": "Mixed feelings about this",
            "emotional_driver": "Uncertainty about outcomes",
            "sarcasm_detected": True,
        }
        result = validate_sentiment_result(raw)
        assert result.secondary_emotion == "curious"
        assert result.emotion_intensity == "strong"
        assert result.emotional_driver == "Uncertainty about outcomes"
        assert result.sarcasm_detected is True


class TestValidateTheme:
    def test_valid_theme(self) -> None:
        raw = {
            "name": "Battery Life Complaints",
            "description": "Users report rapid battery drain",
            "percentage": 45.0,
            "post_count": 18,
            "sentiment_skew": "negative",
            "representative_quotes": ["Battery dies in 2 hours"],
        }
        theme = validate_theme(raw)
        assert isinstance(theme, Theme)
        assert theme.name == "Battery Life Complaints"

    def test_invalid_sentiment_skew(self) -> None:
        raw = {
            "name": "Theme",
            "description": "Desc",
            "percentage": 10.0,
            "post_count": 5,
            "sentiment_skew": "very_negative",
        }
        with pytest.raises(ValidationError, match="sentiment_skew"):
            validate_theme(raw)

    def test_percentage_out_of_range(self) -> None:
        raw = {
            "name": "Theme",
            "description": "Desc",
            "percentage": 150.0,
            "post_count": 5,
            "sentiment_skew": "positive",
        }
        with pytest.raises(ValidationError, match="percentage"):
            validate_theme(raw)
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_schemas.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/analyzers/schemas.py`.

```python
"""Output schemas and validation for LLM analysis results.

Validation functions check that LLM output conforms to expected shapes
and value ranges before the data enters the rest of the system (BOARD-012).

Invalid responses trigger one retry with a tighter prompt. Second failure
skips the post with a warning. This module handles the validation;
the retry logic is in the analyzer.
"""
from __future__ import annotations

import logging

from signalstream.db.models import SentimentResult, Theme

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral", "mixed"})

VALID_EMOTIONS = frozenset({
    "enthusiastic", "hopeful", "curious", "neutral",
    "skeptical", "concerned", "frustrated", "angry",
})

VALID_INTENSITIES = frozenset({"strong", "moderate", "mild"})

MAX_KEY_POINT_LENGTH = 200


class ValidationError(Exception):
    """Raised when LLM output fails validation."""


def validate_sentiment_result(raw: dict) -> SentimentResult:
    """Validate and construct a SentimentResult from a raw dict.

    Args:
        raw: Dictionary with keys matching SentimentResult fields.

    Returns:
        A validated SentimentResult instance.

    Raises:
        ValidationError: If any field fails validation.
    """
    errors: list[str] = []

    # Required fields
    sentiment = raw.get("sentiment", "")
    if sentiment not in VALID_SENTIMENTS:
        errors.append(
            f"sentiment must be one of {sorted(VALID_SENTIMENTS)}, got '{sentiment}'"
        )

    emotion = raw.get("emotion", "")
    if emotion not in VALID_EMOTIONS:
        errors.append(
            f"emotion must be one of {sorted(VALID_EMOTIONS)}, got '{emotion}'"
        )

    confidence = raw.get("confidence")
    if confidence is None:
        errors.append("confidence is required")
    else:
        try:
            confidence = float(confidence)
            if not (0.0 <= confidence <= 1.0):
                errors.append(f"confidence must be in [0.0, 1.0], got {confidence}")
        except (ValueError, TypeError):
            errors.append(f"confidence must be a float, got {type(confidence).__name__}")

    key_point = raw.get("key_point", "")
    if not key_point or not str(key_point).strip():
        errors.append("key_point must be a non-empty string")
    elif len(str(key_point)) > MAX_KEY_POINT_LENGTH:
        errors.append(
            f"key_point must be under {MAX_KEY_POINT_LENGTH} characters, "
            f"got {len(str(key_point))}"
        )

    sarcasm_detected = raw.get("sarcasm_detected")
    if sarcasm_detected is None:
        sarcasm_detected = False

    if errors:
        raise ValidationError("; ".join(errors))

    # Optional fields with defaults
    secondary_emotion = raw.get("secondary_emotion", "none")
    emotion_intensity = raw.get("emotion_intensity", "moderate")
    emotional_driver = raw.get("emotional_driver", "")

    return SentimentResult(
        sentiment=sentiment,
        emotion=emotion,
        confidence=float(confidence),
        key_point=str(key_point).strip(),
        sarcasm_detected=bool(sarcasm_detected),
        secondary_emotion=str(secondary_emotion),
        emotion_intensity=str(emotion_intensity),
        emotional_driver=str(emotional_driver),
    )


def validate_theme(raw: dict) -> Theme:
    """Validate and construct a Theme from a raw dict.

    Args:
        raw: Dictionary with keys matching Theme fields.

    Returns:
        A validated Theme instance.

    Raises:
        ValidationError: If any field fails validation.
    """
    errors: list[str] = []

    name = raw.get("name", "")
    if not name or not str(name).strip():
        errors.append("name must be a non-empty string")

    description = raw.get("description", "")

    percentage = raw.get("percentage", 0.0)
    try:
        percentage = float(percentage)
        if not (0.0 <= percentage <= 100.0):
            errors.append(f"percentage must be in [0.0, 100.0], got {percentage}")
    except (ValueError, TypeError):
        errors.append(f"percentage must be a float, got {type(percentage).__name__}")

    post_count = raw.get("post_count", 0)

    sentiment_skew = raw.get("sentiment_skew", "")
    if sentiment_skew not in VALID_SENTIMENTS:
        errors.append(
            f"sentiment_skew must be one of {sorted(VALID_SENTIMENTS)}, "
            f"got '{sentiment_skew}'"
        )

    if errors:
        raise ValidationError("; ".join(errors))

    representative_quotes = raw.get("representative_quotes", [])
    if not isinstance(representative_quotes, list):
        representative_quotes = []

    return Theme(
        name=str(name).strip(),
        description=str(description).strip(),
        percentage=float(percentage),
        post_count=int(post_count),
        sentiment_skew=str(sentiment_skew),
        representative_quotes=[str(q) for q in representative_quotes],
    )
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_schemas.py -v
```

Expected: 13 tests pass.

- [ ] **Step 5:** Commit.

```
feat(analyzers): add output schema validation for sentiment and themes (BOARD-012)

validate_sentiment_result() checks sentiment enum, emotion set,
confidence range [0.0-1.0], key_point length, sarcasm boolean.
validate_theme() checks percentage range, sentiment_skew enum.
ValidationError raised with specific field details.
```

---

## Task 13: Prompt Templates (`signalstream/analyzers/prompts.py`)

> All LLM prompt templates, version-tagged, ported from current code.

**Files:**
- Create: `signalstream/analyzers/prompts.py`
- Create: `signalstream/tests/test_analyzers/test_prompts.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_analyzers/test_prompts.py`.

```python
"""Tests for signalstream.analyzers.prompts."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalstream.analyzers.prompts import (
    SENTIMENT_PROMPT_V1,
    THEMATIC_PROMPT_V1,
    SENTIMENT_RETRY_PROMPT_V1,
    build_sentiment_prompt,
    build_thematic_prompt,
    build_sentiment_retry_prompt,
)
from signalstream.db.models import Comment, Post, SentimentResult


def _make_post(**overrides) -> Post:
    defaults = dict(
        platform="reddit", id="p1", author="user1",
        text="I really love this new feature. It works perfectly.",
        title="Amazing new release",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="python",
        engagement=100, detected_region="global",
        detected_language="en",
    )
    defaults.update(overrides)
    return Post(**defaults)


class TestBuildSentimentPrompt:
    def test_includes_topic(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="Python 4.0")
        combined = " ".join(m["content"] for m in messages)
        assert "Python 4.0" in combined

    def test_includes_title_and_content(self) -> None:
        post = _make_post(title="Great Release", text="Love the new features")
        messages = build_sentiment_prompt(post, topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "Great Release" in combined
        assert "Love the new features" in combined

    def test_has_system_and_user_messages(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="test")
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_includes_community_and_region(self) -> None:
        post = _make_post(community="machinelearning", detected_region="US")
        messages = build_sentiment_prompt(post, topic="ML")
        combined = " ".join(m["content"] for m in messages)
        assert "machinelearning" in combined
        assert "US" in combined

    def test_includes_thread_context_with_comments(self) -> None:
        comment = Comment(
            id="c1", body="I agree, great feature!",
            author="u2", score=10,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1,
        )
        post = _make_post(comments=[comment])
        messages = build_sentiment_prompt(post, topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "agree" in combined

    def test_user_content_wrapped_in_delimiters(self) -> None:
        """User content is wrapped in delimiters for prompt injection defense."""
        messages = build_sentiment_prompt(_make_post(), topic="test")
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "<user_post>" in user_msg["content"]
        assert "</user_post>" in user_msg["content"]

    def test_output_format_specified(self) -> None:
        messages = build_sentiment_prompt(_make_post(), topic="test")
        combined = " ".join(m["content"] for m in messages)
        assert "SENTIMENT:" in combined or "sentiment:" in combined.lower()
        assert "PRIMARY_EMOTION:" in combined or "primary_emotion:" in combined.lower()


class TestBuildThematicPrompt:
    def test_includes_post_summaries(self) -> None:
        summaries = [
            "1. [positive] [US] Users love the performance improvements",
            "2. [negative] [EU] Pricing concerns raised by enterprise users",
        ]
        messages = build_thematic_prompt(
            phrase="Python 4.0", summaries=summaries, post_count=2,
        )
        combined = " ".join(m["content"] for m in messages)
        assert "performance improvements" in combined
        assert "Pricing concerns" in combined

    def test_includes_expected_sections(self) -> None:
        messages = build_thematic_prompt(
            phrase="test", summaries=["1. [positive] [US] Good stuff"], post_count=1,
        )
        combined = " ".join(m["content"] for m in messages)
        assert "MAJOR_THEMES" in combined
        assert "NOVEL_IDEAS" in combined
        assert "KEY_CRITIQUES" in combined
        assert "REGIONAL_PATTERNS" in combined
        assert "SENTIMENT_SUMMARY" in combined


class TestBuildSentimentRetryPrompt:
    def test_retry_prompt_is_stricter(self) -> None:
        messages = build_sentiment_retry_prompt(
            original_response="Some malformed output that didn't parse",
            topic="test",
        )
        combined = " ".join(m["content"] for m in messages)
        assert "EXACTLY" in combined or "exactly" in combined.lower()
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_prompts.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/analyzers/prompts.py`.

```python
"""LLM prompt templates for sentiment and thematic analysis.

All prompts are version-tagged for reproducibility. Ported from the current
codebase (analyzer.py:201-324, thematic_analyzer.py:122-181).

Prompt injection defense: user content is wrapped in <user_post>...</user_post>
delimiters so the model can distinguish instructions from data.
"""
from __future__ import annotations

from signalstream.db.models import Comment, Post

# ---------------------------------------------------------------------------
# Version-tagged prompt templates
# ---------------------------------------------------------------------------

SENTIMENT_PROMPT_V1 = """You are an expert sentiment and emotion analyst for social media content. \
Analyze the provided post and its context to determine sentiment, emotion, and key points.

You MUST respond in EXACTLY this format (one item per line, no extra text):
PRIMARY_EMOTION: [enthusiastic/hopeful/curious/neutral/skeptical/concerned/frustrated/angry]
SECONDARY_EMOTION: [one of the above, or none]
EMOTION_INTENSITY: [strong/moderate/mild]
SENTIMENT: [positive/negative/neutral/mixed]
CONFIDENCE: [certain/uncertain/questioning]
KEY_POINT: [one sentence summary of the main point or argument]
EMOTIONAL_DRIVER: [one sentence explaining what drives the emotional response]
SARCASM_DETECTED: [true/false]

Pay special attention to sarcasm, irony, and rhetorical inversion. If the text \
appears sarcastic, classify based on the INTENDED meaning, not the literal surface.

Choose only ONE option for each field. Be concise and evidence-based."""


SENTIMENT_RETRY_PROMPT_V1 = """You are an expert sentiment analyst. Your previous response \
could not be parsed. You MUST respond in EXACTLY this format with no extra text, \
preamble, or explanation — just the labeled fields:

PRIMARY_EMOTION: [enthusiastic/hopeful/curious/neutral/skeptical/concerned/frustrated/angry]
SECONDARY_EMOTION: [one of the above, or none]
EMOTION_INTENSITY: [strong/moderate/mild]
SENTIMENT: [positive/negative/neutral/mixed]
CONFIDENCE: [certain/uncertain/questioning]
KEY_POINT: [one sentence]
EMOTIONAL_DRIVER: [one sentence]
SARCASM_DETECTED: [true/false]

Respond ONLY with these 8 lines. No other text."""


THEMATIC_PROMPT_V1 = """You are an expert analyst identifying themes across social media discussions. \
Analyze the provided post summaries and identify cross-cutting themes, patterns, and insights.

Respond in EXACTLY this format:

MAJOR_THEMES:
1. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]
2. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]
3. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]

POST_THEME_ASSIGNMENTS:
For each post number, list which 1-2 major themes (by number) it belongs to:
1: 1,2
2: 1
3: 3

NOVEL_IDEAS:
- [Unique perspective or idea not commonly discussed]

KEY_CRITIQUES:
- [Common criticism or concern raised] (frequency: frequent/occasional/rare)

REGIONAL_PATTERNS:
- [Region]: [Pattern or trend observed in this region]

SENTIMENT_SUMMARY:
Overall sentiment is [positive/negative/neutral/mixed] with [high/medium/low] confidence.
[One sentence narrative summary of the overall discussion tone]

Be specific and base your analysis only on the provided summaries."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _flatten_comments(comments: list[Comment], max_chars: int = 2000) -> str:
    """Flatten comment tree into a text block for the prompt."""
    lines: list[str] = []
    total_chars = 0

    def _walk(comment_list: list[Comment], indent: int = 0) -> None:
        nonlocal total_chars
        for c in comment_list:
            if total_chars >= max_chars:
                return
            prefix = "  " * indent
            score_str = f"[{c.score:+d}]" if c.score else ""
            line = f"{prefix}{score_str} {c.body[:300]}"
            lines.append(line)
            total_chars += len(line)
            if c.replies:
                _walk(c.replies, indent + 1)

    _walk(comments)
    return "\n".join(lines) if lines else "[No comment/reply context available]"


def build_sentiment_prompt(
    post: Post,
    *,
    topic: str,
) -> list[dict]:
    """Build the message list for sentiment analysis of a single post.

    Args:
        post: The post to analyze.
        topic: The search topic for context.

    Returns:
        List of message dicts with 'role' and 'content' keys.
    """
    # Build thread context from comments
    thread_block = _flatten_comments(post.comments)

    community = post.community or "unknown"
    region = post.detected_region or "global"
    language = post.detected_language or "unknown"
    title = post.title or ""
    content = post.text or ""

    user_content = f"""Analyze this social/community discussion thread about '{topic}'.

<user_post>
PRIMARY POST TITLE: {title[:600]}

PRIMARY POST CONTENT: {content[:1800]}

SOURCE: {post.platform} | COMMUNITY: {community} | REGION: {region} | LANGUAGE: {language}

THREAD CONTEXT (comments/replies):
{thread_block}
</user_post>

Assess the overall stance and emotional tone. If comments are sparse, rely on the post itself."""

    return [
        {"role": "system", "content": SENTIMENT_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]


def build_sentiment_retry_prompt(
    *,
    original_response: str,
    topic: str,
) -> list[dict]:
    """Build a retry prompt with stricter format instructions.

    Used when the first LLM response could not be parsed.

    Args:
        original_response: The unparseable response from the first attempt.
        topic: The search topic for context.

    Returns:
        List of message dicts.
    """
    user_content = f"""Your previous analysis of a post about '{topic}' could not be parsed.

Your previous response was:
{original_response[:500]}

Please re-analyze and respond in EXACTLY the required format."""

    return [
        {"role": "system", "content": SENTIMENT_RETRY_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]


def build_thematic_prompt(
    *,
    phrase: str,
    summaries: list[str],
    post_count: int,
) -> list[dict]:
    """Build the message list for thematic analysis of a batch of posts.

    Args:
        phrase: The search phrase these posts matched.
        summaries: List of formatted summary lines (e.g., "1. [positive] [US] ...").
        post_count: Total number of posts in this batch.

    Returns:
        List of message dicts.
    """
    summary_text = "\n".join(summaries)

    user_content = f"""Analyze {post_count} social posts about "{phrase}".

Here are summaries of each post with their sentiment and region:

{summary_text}

Provide your analysis following the format specified."""

    return [
        {"role": "system", "content": THEMATIC_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_prompts.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5:** Commit.

```
feat(analyzers): add version-tagged prompt templates ported from current code

SENTIMENT_PROMPT_V1, THEMATIC_PROMPT_V1, and SENTIMENT_RETRY_PROMPT_V1
with builder functions. User content wrapped in <user_post> delimiters
for prompt injection defense. Thread context flattened from comment tree.
```

---

## Task 14: Analyzer Base (`signalstream/analyzers/base.py`)

> Abstract analyzer with LLM dependency injection.

**Files:**
- Create: `signalstream/analyzers/base.py`
- Create: `signalstream/tests/test_analyzers/test_base.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_analyzers/test_base.py`.

```python
"""Tests for signalstream.analyzers.base."""
from __future__ import annotations

import pytest

from signalstream.analyzers.base import BaseAnalyzer
from signalstream.llm.providers.base import BaseProvider


class TestBaseAnalyzer:
    def test_cannot_instantiate_directly(self) -> None:
        from unittest.mock import MagicMock
        mock_provider = MagicMock(spec=BaseProvider)
        with pytest.raises(TypeError):
            BaseAnalyzer(provider=mock_provider, model="test")  # type: ignore[abstract]

    def test_stores_provider_and_model(self) -> None:
        from unittest.mock import MagicMock

        mock_provider = MagicMock(spec=BaseProvider)

        class ConcreteAnalyzer(BaseAnalyzer):
            def analyze(self, *args, **kwargs):
                return []

        analyzer = ConcreteAnalyzer(provider=mock_provider, model="test-model")
        assert analyzer._provider is mock_provider
        assert analyzer._model == "test-model"
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_base.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/analyzers/base.py`.

```python
"""Abstract analyzer base with LLM dependency injection.

Analyzers receive a provider instance at construction time. They never import
the LLM router directly. This makes them testable with a mock provider.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Type for progress callbacks: (completed, total, current_item_id)
ProgressCallback = Callable[[int, int, str], None]


class BaseAnalyzer(ABC):
    """Abstract base for LLM-powered analyzers.

    Args:
        provider: The LLM provider instance (injected, never imported).
        model: The model identifier to use for completions.
        completion_config: Optional per-call config. Defaults to temperature=0.0.
    """

    def __init__(
        self,
        *,
        provider: BaseProvider,
        model: str,
        completion_config: CompletionConfig | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._completion_config = completion_config or CompletionConfig()

    @abstractmethod
    def analyze(self, *args: Any, **kwargs: Any) -> Any:
        """Run the analysis. Subclasses define their own signatures."""
        ...

    def _complete(self, messages: list[dict]) -> str:
        """Convenience method to call the provider with standard config."""
        return self._provider.complete(
            messages=messages,
            model=self._model,
            config=self._completion_config,
        )
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_base.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5:** Commit.

```
feat(analyzers): add BaseAnalyzer with LLM dependency injection

Abstract base class that receives a provider at construction time.
Includes ProgressCallback type and _complete() convenience method.
Analyzers never import the router — fully testable with mocks.
```

---

## Task 15: Sentiment Analyzer with Checkpointing (`signalstream/analyzers/sentiment.py`)

> Per-post sentiment analysis with checkpointing, retry on parse failure, and progress callbacks (BOARD-008).

**Files:**
- Create: `signalstream/analyzers/sentiment.py`
- Create: `signalstream/tests/test_analyzers/test_sentiment.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_analyzers/test_sentiment.py`.

```python
"""Tests for signalstream.analyzers.sentiment — per-post analysis with checkpointing."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from signalstream.analyzers.sentiment import SentimentAnalyzer, parse_sentiment_response
from signalstream.db.models import Post, SentimentResult
from signalstream.llm.providers.base import BaseProvider


_GOOD_RESPONSE = """PRIMARY_EMOTION: enthusiastic
SECONDARY_EMOTION: hopeful
EMOTION_INTENSITY: strong
SENTIMENT: positive
CONFIDENCE: certain
KEY_POINT: Users love the new performance improvements
EMOTIONAL_DRIVER: Faster build times directly improve developer productivity
SARCASM_DETECTED: false"""


_BAD_RESPONSE = """This is a post about Python. It seems generally positive.
I think the sentiment is good."""


def _make_post(post_id: str = "p1") -> Post:
    return Post(
        platform="reddit", id=post_id, author="user1",
        text="Amazing new feature release", title="Python 4.0 is here",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="python", engagement=100,
    )


class TestParseSentimentResponse:
    def test_parses_valid_response(self) -> None:
        result = parse_sentiment_response(_GOOD_RESPONSE)
        assert result is not None
        assert result["sentiment"] == "positive"
        assert result["emotion"] == "enthusiastic"
        assert result["sarcasm_detected"] is False

    def test_returns_none_for_unparseable(self) -> None:
        result = parse_sentiment_response(_BAD_RESPONSE)
        # Should return None or a dict with "unknown" values
        assert result is None or result.get("sentiment") == "unknown"

    def test_handles_empty_response(self) -> None:
        result = parse_sentiment_response("")
        assert result is None

    def test_handles_case_insensitive(self) -> None:
        response = _GOOD_RESPONSE.upper()
        result = parse_sentiment_response(response)
        assert result is not None
        assert result["sentiment"] == "positive"


class TestSentimentAnalyzer:
    def test_analyzes_single_post(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        assert len(results) == 1
        post, result = results[0]
        assert result.sentiment == "positive"
        assert result.emotion == "enthusiastic"

    def test_analyzes_multiple_posts(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(posts=posts, topic="Python")

        assert len(results) == 3

    def test_retries_on_parse_failure_then_succeeds(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.side_effect = [_BAD_RESPONSE, _GOOD_RESPONSE]

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        assert len(results) == 1
        assert mock_provider.complete.call_count == 2

    def test_skips_post_after_two_failures(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _BAD_RESPONSE

        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(
            posts=[_make_post()], topic="Python",
        )

        # Post should be skipped — no results
        assert len(results) == 0

    def test_progress_callback_called(self) -> None:
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.return_value = _GOOD_RESPONSE
        callback = MagicMock()

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        analyzer.analyze(
            posts=posts, topic="Python", progress_callback=callback,
        )

        assert callback.call_count == 3

    def test_partial_failure_returns_successes(self) -> None:
        """If 1 of 3 posts fails, the other 2 results are returned."""
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.complete.side_effect = [
            _GOOD_RESPONSE,         # post 0: success
            _BAD_RESPONSE,           # post 1: retry
            _BAD_RESPONSE,           # post 1: retry again — skip
            _GOOD_RESPONSE,         # post 2: success
        ]

        posts = [_make_post(f"p{i}") for i in range(3)]
        analyzer = SentimentAnalyzer(
            provider=mock_provider, model="test-model",
        )
        results = analyzer.analyze(posts=posts, topic="Python")

        assert len(results) == 2
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_sentiment.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/analyzers/sentiment.py`.

```python
"""Per-post sentiment analysis with retry, validation, and checkpointing.

Processes each post through the LLM provider, parses the structured output,
validates it, and returns results. Supports progress callbacks for UI updates.

Checkpointing (BOARD-008): The caller (pipeline layer) writes each result to
the database immediately after receiving it. This module yields results one
at a time via the analyze() return value. If the job fails at post N, posts
1 through N-1 are already persisted.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from signalstream.analyzers.base import BaseAnalyzer, ProgressCallback
from signalstream.analyzers.prompts import (
    build_sentiment_prompt,
    build_sentiment_retry_prompt,
)
from signalstream.analyzers.schemas import ValidationError, validate_sentiment_result
from signalstream.db.models import Post, SentimentResult
from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Confidence string to float mapping
_CONFIDENCE_MAP = {
    "certain": 0.9,
    "uncertain": 0.5,
    "questioning": 0.3,
}


def parse_sentiment_response(response: str) -> dict | None:
    """Parse the structured LLM response into a raw dict.

    Returns None if the response cannot be parsed into the expected format.
    """
    if not response or not response.strip():
        return None

    response_text = response.strip()

    # Extract each field using regex (case-insensitive)
    patterns = {
        "sentiment": r"sentiment:\s*(positive|negative|neutral|mixed)",
        "emotion": r"primary[_\s]?emotion:\s*(\w+)",
        "secondary_emotion": r"secondary[_\s]?emotion:\s*(\w+|none)",
        "emotion_intensity": r"emotion[_\s]?intensity:\s*(strong|moderate|mild)",
        "confidence": r"confidence:\s*(certain|uncertain|questioning)",
        "key_point": r"key[_\s]?point:\s*(.+?)(?:\n|$)",
        "emotional_driver": r"emotional[_\s]?driver:\s*(.+?)(?:\n|$)",
        "sarcasm_detected": r"sarcasm[_\s]?detected:\s*(true|false)",
    }

    result: dict = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            result[field] = value

    # Must have at least sentiment to be considered valid
    if "sentiment" not in result:
        return None

    # Normalize values
    result["sentiment"] = result["sentiment"].lower()
    result["emotion"] = result.get("emotion", "neutral").lower()
    result["secondary_emotion"] = result.get("secondary_emotion", "none").lower()
    result["emotion_intensity"] = result.get("emotion_intensity", "moderate").lower()

    # Convert confidence string to float
    conf_str = result.get("confidence", "uncertain").lower()
    result["confidence"] = _CONFIDENCE_MAP.get(conf_str, 0.5)

    # Sarcasm to boolean
    result["sarcasm_detected"] = result.get("sarcasm_detected", "false").lower() == "true"

    # Clean up key_point
    result["key_point"] = result.get("key_point", "Unable to extract key point")[:200]
    result["emotional_driver"] = result.get("emotional_driver", "")[:200]

    return result


class SentimentAnalyzer(BaseAnalyzer):
    """Per-post sentiment analysis with retry on parse failure.

    Processes each post individually through the LLM. On parse failure,
    retries once with a stricter prompt. On second failure, skips the post.

    Args:
        provider: LLM provider instance (injected).
        model: Model identifier.
        completion_config: Optional completion config.
    """

    def analyze(
        self,
        *,
        posts: list[Post],
        topic: str,
        progress_callback: ProgressCallback | None = None,
    ) -> list[tuple[Post, SentimentResult]]:
        """Analyze sentiment for a list of posts.

        Args:
            posts: Posts to analyze.
            topic: The search topic for prompt context.
            progress_callback: Optional (completed, total, post_id) callback.

        Returns:
            List of (post, result) tuples for successfully analyzed posts.
            Posts that fail after retry are skipped.
        """
        results: list[tuple[Post, SentimentResult]] = []
        total = len(posts)
        skipped = 0

        for i, post in enumerate(posts):
            try:
                result = self._analyze_single(post, topic=topic)
                if result is not None:
                    results.append((post, result))
                else:
                    skipped += 1
                    logger.warning(
                        "Skipped post %s after failed retry (post %d/%d)",
                        post.id, i + 1, total,
                    )
            except Exception as e:
                skipped += 1
                logger.error(
                    "Error analyzing post %s: %s (post %d/%d)",
                    post.id, e, i + 1, total,
                )

            if progress_callback:
                progress_callback(i + 1, total, post.id)

        if skipped > 0:
            logger.info(
                "Sentiment analysis complete: %d/%d posts analyzed, %d skipped",
                len(results), total, skipped,
            )

        return results

    def _analyze_single(self, post: Post, *, topic: str) -> SentimentResult | None:
        """Analyze a single post. Retry once on parse failure."""
        # First attempt
        messages = build_sentiment_prompt(post, topic=topic)
        response = self._complete(messages)
        raw = parse_sentiment_response(response)

        if raw is not None:
            try:
                return validate_sentiment_result(raw)
            except ValidationError as e:
                logger.warning(
                    "Validation failed for post %s (attempt 1): %s",
                    post.id, e,
                )

        # Retry with stricter prompt
        logger.info("Retrying analysis for post %s with stricter prompt", post.id)
        retry_messages = build_sentiment_retry_prompt(
            original_response=response,
            topic=topic,
        )
        retry_response = self._complete(retry_messages)
        retry_raw = parse_sentiment_response(retry_response)

        if retry_raw is not None:
            try:
                return validate_sentiment_result(retry_raw)
            except ValidationError as e:
                logger.warning(
                    "Validation failed for post %s (attempt 2): %s",
                    post.id, e,
                )

        return None
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_sentiment.py -v
```

Expected: 10 tests pass.

- [ ] **Step 5:** Commit.

```
feat(analyzers): add sentiment analyzer with retry, validation, checkpointing

Per-post analysis with parse_sentiment_response() regex extraction,
validate_sentiment_result() schema checks, and one retry with stricter
prompt on parse failure. Progress callbacks for UI. Skips posts that
fail twice. Checkpoint-ready via per-post result returns (BOARD-008).
```

---

## Task 16: Thematic Analyzer with Chunking (`signalstream/analyzers/thematic.py`)

> Batch theme extraction with chunking for large collections (BOARD-011).

**Files:**
- Create: `signalstream/analyzers/thematic.py`
- Create: `signalstream/tests/test_analyzers/test_thematic.py`

- [ ] **Step 1:** Write the failing test file `signalstream/tests/test_analyzers/test_thematic.py`.

```python
"""Tests for signalstream.analyzers.thematic — batch theme extraction with chunking."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from signalstream.analyzers.thematic import (
    ThematicAnalyzer,
    create_aggregation_summary,
    parse_theme_response,
)
from signalstream.db.models import Post, SentimentResult, Theme


_GOOD_THEME_RESPONSE = """MAJOR_THEMES:
1. Performance Improvements | Users praise significant speed gains in the new release
2. Pricing Concerns | Enterprise users worry about cost increases
3. Documentation Quality | Community requests better API documentation

POST_THEME_ASSIGNMENTS:
1: 1
2: 2
3: 3
4: 1,3
5: 2

NOVEL_IDEAS:
- Using the new async API for real-time data processing pipelines
- Community-maintained documentation as alternative to official docs

KEY_CRITIQUES:
- Backward compatibility issues with plugin ecosystem (frequency: frequent)
- Steep learning curve for new configuration system (frequency: occasional)

REGIONAL_PATTERNS:
- US: Focus on enterprise features and pricing
- EU: Emphasis on data privacy compliance in new features

SENTIMENT_SUMMARY:
Overall sentiment is mixed with medium confidence.
The community is excited about performance but worried about migration costs."""


def _make_analyzed_post(
    post_id: str, sentiment: str = "positive", key_point: str = "Good stuff",
    region: str = "global",
) -> tuple[Post, SentimentResult]:
    post = Post(
        platform="reddit", id=post_id, author="user1",
        text="Content", title="Title",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="test",
        engagement=10, detected_region=region,
    )
    result = SentimentResult(
        sentiment=sentiment, emotion="enthusiastic",
        confidence=0.8, key_point=key_point,
        sarcasm_detected=False,
    )
    return post, result


class TestCreateAggregationSummary:
    def test_creates_numbered_summaries(self) -> None:
        analyzed = [
            _make_analyzed_post("p1", "positive", "Users love it", "US"),
            _make_analyzed_post("p2", "negative", "Too expensive", "EU"),
        ]
        summaries = create_aggregation_summary(analyzed)
        assert len(summaries) == 2
        assert "[positive]" in summaries[0]
        assert "[US]" in summaries[0]
        assert "Users love it" in summaries[0]

    def test_samples_50_for_large_collections(self) -> None:
        analyzed = [
            _make_analyzed_post(f"p{i}", "neutral", f"Point {i}")
            for i in range(100)
        ]
        summaries = create_aggregation_summary(analyzed)
        assert len(summaries) == 50

    def test_deterministic_sampling(self) -> None:
        analyzed = [
            _make_analyzed_post(f"p{i}", "neutral", f"Point {i}")
            for i in range(100)
        ]
        summaries1 = create_aggregation_summary(analyzed)
        summaries2 = create_aggregation_summary(analyzed)
        assert summaries1 == summaries2


class TestParseThemeResponse:
    def test_parses_major_themes(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["major_themes"]) == 3
        assert themes["major_themes"][0]["theme"] == "Performance Improvements"

    def test_parses_novel_ideas(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["novel_ideas"]) >= 1

    def test_parses_key_critiques(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert len(themes["key_critiques"]) >= 1

    def test_parses_sentiment_summary(self) -> None:
        themes = parse_theme_response(_GOOD_THEME_RESPONSE)
        assert themes["sentiment_summary"]["overall"] == "mixed"

    def test_handles_empty_response(self) -> None:
        themes = parse_theme_response("")
        assert themes["major_themes"] == []


class TestThematicAnalyzer:
    def test_analyzes_small_batch(self) -> None:
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [
            _make_analyzed_post(f"p{i}", "positive", f"Point {i}")
            for i in range(10)
        ]

        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="Python 4.0",
        )

        assert len(themes) >= 1
        assert mock_provider.complete.call_count == 1

    def test_chunks_large_collections(self) -> None:
        """Collections > 50 posts are chunked and consolidated (BOARD-011)."""
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [
            _make_analyzed_post(f"p{i}", "positive", f"Point {i}")
            for i in range(120)
        ]

        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="Python 4.0",
        )

        # Should make multiple LLM calls: chunks + consolidation
        assert mock_provider.complete.call_count >= 2
        assert len(themes) >= 1

    def test_returns_theme_objects(self) -> None:
        mock_provider = MagicMock()
        mock_provider.complete.return_value = _GOOD_THEME_RESPONSE

        analyzed = [_make_analyzed_post("p1", "positive", "Good stuff")]
        analyzer = ThematicAnalyzer(
            provider=mock_provider, model="test-model",
        )
        themes = analyzer.analyze(
            analyzed_posts=analyzed, phrase="test",
        )

        for theme in themes:
            assert isinstance(theme, Theme)
```

- [ ] **Step 2:** Run the test — confirm it fails.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_thematic.py -x -q 2>&1 | head -10
```

- [ ] **Step 3:** Implement `signalstream/analyzers/thematic.py`.

```python
"""Batch thematic analysis with chunking for large collections.

Processes analyzed posts to identify cross-cutting themes, regional patterns,
and novel ideas. For collections exceeding 50 posts, chunks the input and
runs a consolidation pass (BOARD-011).

Token estimation: 4 characters ~= 1 token.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any

from signalstream.analyzers.base import BaseAnalyzer
from signalstream.analyzers.prompts import build_thematic_prompt
from signalstream.db.models import Post, SentimentResult, Theme
from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 50
_CHARS_PER_TOKEN = 4


def create_aggregation_summary(
    analyzed_posts: list[tuple[Post, SentimentResult]],
) -> list[str]:
    """Create numbered summaries of analyzed posts for thematic analysis.

    Samples up to 50 posts with a deterministic seed for reproducibility.

    Args:
        analyzed_posts: List of (post, sentiment_result) tuples.

    Returns:
        List of formatted summary strings.
    """
    sample = analyzed_posts
    if len(analyzed_posts) > _CHUNK_SIZE:
        seed = hash(tuple(p.id for p, _ in analyzed_posts))
        rng = random.Random(seed)
        sample = rng.sample(analyzed_posts, _CHUNK_SIZE)

    summaries: list[str] = []
    for i, (post, result) in enumerate(sample, 1):
        region = post.detected_region or "global"
        line = f"{i}. [{result.sentiment}] [{region}] {result.key_point}"
        summaries.append(line)

    return summaries


def parse_theme_response(response: str) -> dict[str, Any]:
    """Parse the structured thematic analysis response into a dict.

    Returns a dict with: major_themes, novel_ideas, key_critiques,
    regional_patterns, sentiment_summary.
    """
    result: dict[str, Any] = {
        "major_themes": [],
        "novel_ideas": [],
        "key_critiques": [],
        "regional_patterns": {},
        "sentiment_summary": {
            "overall": "unknown",
            "confidence": "unknown",
            "narrative": "",
        },
    }

    if not response or not response.strip():
        return result

    # Parse major themes
    themes_match = re.search(
        r'MAJOR[_\s]?THEMES?:?\s*\n((?:[\d\.\-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if themes_match:
        themes_text = themes_match.group(1)
        theme_lines = re.findall(r'[\d\.\-\*]\s*(.+?)(?:\n|$)', themes_text)
        for line in theme_lines[:5]:
            theme_name = re.sub(r'^\d+\.\s*', '', line).strip()
            theme_name = re.sub(r'^[\.\-\*\)\s]+', '', theme_name).strip()

            if '|' in theme_name:
                parts = theme_name.split('|', 1)
                label = parts[0].strip()
                description = parts[1].strip()
            else:
                parts = theme_name.split(' - ', 1)
                label = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else ""

            pct_match = re.search(r'(\d+)\s*%', line)
            percentage = int(pct_match.group(1)) if pct_match else 0

            if label:
                result["major_themes"].append({
                    "theme": label,
                    "description": description,
                    "percentage": percentage,
                })

    # Parse novel ideas
    novel_match = re.search(
        r'NOVEL[_\s]?IDEAS?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if novel_match:
        ideas_text = novel_match.group(1)
        ideas = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', ideas_text)
        result["novel_ideas"] = [idea.strip() for idea in ideas if idea.strip()]

    # Parse key critiques
    critiques_match = re.search(
        r'KEY[_\s]?CRITIQUES?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if critiques_match:
        critiques_text = critiques_match.group(1)
        critiques = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', critiques_text)
        for c in critiques:
            freq_match = re.search(r'\((?:frequency:?\s*)?(frequent|occasional|rare)\)', c, re.IGNORECASE)
            critique_text = re.sub(r'\s*\((?:frequency:?\s*)?(?:frequent|occasional|rare)\)', '', c).strip()
            result["key_critiques"].append({
                "critique": critique_text,
                "frequency": freq_match.group(1).lower() if freq_match else "unknown",
            })

    # Parse regional patterns
    regional_match = re.search(
        r'REGIONAL[_\s]?PATTERNS?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if regional_match:
        regional_text = regional_match.group(1)
        patterns = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', regional_text)
        for p in patterns:
            if ':' in p:
                region, pattern = p.split(':', 1)
                result["regional_patterns"][region.strip()] = pattern.strip()

    # Parse sentiment summary
    sentiment_match = re.search(
        r'SENTIMENT[_\s]?SUMMARY:?\s*\n(.+?)(?:\n\n|\Z)',
        response, re.IGNORECASE | re.DOTALL,
    )
    if sentiment_match:
        summary_text = sentiment_match.group(1).strip()
        overall_match = re.search(
            r'is\s+(positive|negative|neutral|mixed)', summary_text, re.IGNORECASE,
        )
        conf_match = re.search(
            r'(high|medium|low)\s+confidence', summary_text, re.IGNORECASE,
        )
        if overall_match:
            result["sentiment_summary"]["overall"] = overall_match.group(1).lower()
        if conf_match:
            result["sentiment_summary"]["confidence"] = conf_match.group(1).lower()

        lines = summary_text.split('\n')
        if len(lines) > 1:
            result["sentiment_summary"]["narrative"] = lines[-1].strip()
        else:
            result["sentiment_summary"]["narrative"] = summary_text

    return result


class ThematicAnalyzer(BaseAnalyzer):
    """Batch theme extraction with chunking for large collections.

    For collections <= 50 posts, sends one batch to the LLM.
    For larger collections, chunks into groups of 50, generates per-chunk
    themes, then runs a consolidation pass to merge duplicates and
    recalculate percentages (BOARD-011).

    Args:
        provider: LLM provider instance (injected).
        model: Model identifier.
        completion_config: Optional completion config.
        chunk_size: Maximum posts per chunk (default 50).
    """

    def __init__(
        self,
        *,
        provider: BaseProvider,
        model: str,
        completion_config: CompletionConfig | None = None,
        chunk_size: int = _CHUNK_SIZE,
    ) -> None:
        super().__init__(
            provider=provider, model=model,
            completion_config=completion_config or CompletionConfig(max_tokens=2048),
        )
        self._chunk_size = chunk_size

    def analyze(
        self,
        *,
        analyzed_posts: list[tuple[Post, SentimentResult]],
        phrase: str,
    ) -> list[Theme]:
        """Extract themes from a batch of analyzed posts.

        Args:
            analyzed_posts: List of (post, sentiment_result) tuples.
            phrase: The search phrase for prompt context.

        Returns:
            List of Theme objects sorted by prevalence (post_count descending).
        """
        if len(analyzed_posts) <= self._chunk_size:
            return self._analyze_chunk(analyzed_posts, phrase=phrase)

        # Chunk and analyze
        logger.info(
            "Chunking %d posts into groups of %d for thematic analysis",
            len(analyzed_posts), self._chunk_size,
        )
        all_chunk_themes: list[dict] = []
        for i in range(0, len(analyzed_posts), self._chunk_size):
            chunk = analyzed_posts[i:i + self._chunk_size]
            chunk_themes = self._analyze_chunk_raw(chunk, phrase=phrase)
            all_chunk_themes.extend(chunk_themes)

        # Consolidation pass
        return self._consolidate_themes(all_chunk_themes, total_posts=len(analyzed_posts))

    def _analyze_chunk(
        self,
        chunk: list[tuple[Post, SentimentResult]],
        *,
        phrase: str,
    ) -> list[Theme]:
        """Analyze a single chunk and return Theme objects."""
        raw_themes = self._analyze_chunk_raw(chunk, phrase=phrase)
        total = len(chunk)
        themes: list[Theme] = []

        for t in raw_themes:
            pct = t.get("percentage", 0)
            post_count = max(1, round(pct / 100 * total)) if pct > 0 else 0

            themes.append(Theme(
                name=t.get("theme", "Unknown"),
                description=t.get("description", ""),
                percentage=float(pct),
                post_count=post_count,
                sentiment_skew="neutral",  # default; would need per-theme analysis
                representative_quotes=[],
            ))

        # Sort by post_count descending
        themes.sort(key=lambda th: th.post_count, reverse=True)
        return themes

    def _analyze_chunk_raw(
        self,
        chunk: list[tuple[Post, SentimentResult]],
        *,
        phrase: str,
    ) -> list[dict]:
        """Analyze a chunk and return raw theme dicts."""
        summaries = create_aggregation_summary(chunk)
        messages = build_thematic_prompt(
            phrase=phrase, summaries=summaries, post_count=len(chunk),
        )
        response = self._complete(messages)
        parsed = parse_theme_response(response)
        return parsed.get("major_themes", [])

    def _consolidate_themes(
        self,
        all_themes: list[dict],
        *,
        total_posts: int,
    ) -> list[Theme]:
        """Merge duplicate themes from multiple chunks via a consolidation LLM call."""
        if not all_themes:
            return []

        # Build a consolidation prompt
        theme_list = "\n".join(
            f"{i+1}. {t.get('theme', 'Unknown')} | {t.get('description', '')}"
            for i, t in enumerate(all_themes)
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert analyst. Merge the following theme lists from "
                    "multiple chunks into a single consolidated list. Combine duplicates, "
                    "keep the most representative label, and recalculate approximate "
                    "percentages based on the total.\n\n"
                    "Respond in EXACTLY this format:\n"
                    "MAJOR_THEMES:\n"
                    "1. [Theme Label] | [Description]\n"
                    "2. [Theme Label] | [Description]\n"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Consolidate these {len(all_themes)} themes from "
                    f"{total_posts} total posts:\n\n{theme_list}"
                ),
            },
        ]

        response = self._complete(messages)
        parsed = parse_theme_response(response)
        consolidated = parsed.get("major_themes", [])

        themes: list[Theme] = []
        for t in consolidated:
            pct = t.get("percentage", 0)
            if pct == 0 and consolidated:
                # Distribute evenly if no percentages given
                pct = round(100 / len(consolidated), 1)
            post_count = max(1, round(pct / 100 * total_posts)) if pct > 0 else 0

            themes.append(Theme(
                name=t.get("theme", "Unknown"),
                description=t.get("description", ""),
                percentage=float(pct),
                post_count=post_count,
                sentiment_skew="neutral",
                representative_quotes=[],
            ))

        themes.sort(key=lambda th: th.post_count, reverse=True)
        return themes
```

- [ ] **Step 4:** Run the tests — all should pass.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_analyzers/test_thematic.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5:** Commit.

```
feat(analyzers): add thematic analyzer with chunking for large collections (BOARD-011)

Batch theme extraction with deterministic sampling. Collections > 50
posts are chunked, analyzed per-chunk, then consolidated via a merge
LLM call. Parses MAJOR_THEMES, NOVEL_IDEAS, KEY_CRITIQUES,
REGIONAL_PATTERNS, and SENTIMENT_SUMMARY from structured output.
```

---

## Task 17: Integration Test — Full Foundation Stack

> Verify all four packages work together end-to-end with mock data and a mock LLM provider.

**Files:**
- Create: `signalstream/tests/test_integration_foundation.py`

- [ ] **Step 1:** Write the integration test.

```python
"""Integration test — full foundation stack with mock LLM provider.

Verifies: DB setup -> Post storage -> Sentiment analysis -> Thematic analysis
-> Result persistence -> Checkpoint recovery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from signalstream.db.engine import DatabaseEngine
from signalstream.db.migrations import MigrationManager
from signalstream.db.models import Post, SentimentResult
from signalstream.db.repositories import (
    JobRepository,
    PostRepository,
    SentimentResultRepository,
)
from signalstream.analyzers.sentiment import SentimentAnalyzer
from signalstream.analyzers.thematic import ThematicAnalyzer
from signalstream.db.models import Job, Theme


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
        for row_id, (_, result) in zip(row_ids, results):
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
```

- [ ] **Step 2:** Run the integration test.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/test_integration_foundation.py -v
```

Expected: 2 tests pass.

- [ ] **Step 3:** Run the full test suite to verify nothing is broken.

```bash
cd "/Users/eston/Desktop/Sentiment Analysis"
python -m pytest signalstream/tests/ -v --tb=short
```

Expected: All tests pass (approximately 95+ tests across all modules).

- [ ] **Step 4:** Commit.

```
test: add foundation integration test — full pipeline with checkpoint recovery

End-to-end test: job creation, post storage, mock LLM sentiment analysis,
result persistence, checkpoint verification, and thematic analysis.
Separate test for checkpoint recovery after simulated failure at post N.
```

---

## Summary

| Task | Package | Key Files | Tests |
|------|---------|-----------|-------|
| 0 | Scaffolding | `__init__.py`, `pyproject.toml`, `conftest.py` | 0 |
| 1 | `db/` | `engine.py` | 9 |
| 2 | `db/` | `models.py` | 9 |
| 3 | `db/` | `migrations.py` | 7 |
| 4 | `db/` | `repositories.py` | 12 |
| 5 | `llm/` | `config.py` | 7 |
| 6 | `llm/` | `providers/{base,claude,ollama,openai_compat}.py` | 10 |
| 7 | `llm/` | `safety.py` | 14 |
| 8 | `llm/` | `router.py` | 7 |
| 9 | `collectors/` | `http.py` | 5 |
| 10 | `collectors/` | `base.py` | 8 |
| 11 | `collectors/` | `reddit.py` | 5 |
| 12 | `analyzers/` | `schemas.py` | 13 |
| 13 | `analyzers/` | `prompts.py` | 9 |
| 14 | `analyzers/` | `base.py` | 2 |
| 15 | `analyzers/` | `sentiment.py` | 10 |
| 16 | `analyzers/` | `thematic.py` | 9 |
| 17 | Integration | `test_integration_foundation.py` | 2 |
| **Total** | | **26 production files** | **~138 tests** |

### Board Amendments Addressed

- **BOARD-001:** Expanded Post/Comment dataclasses in `models.py` (Task 2)
- **BOARD-003:** nh3 sanitization in `collectors/base.py` (Task 10)
- **BOARD-006:** CompletionConfig with temperature=0.0 default in `config.py` (Task 5)
- **BOARD-007:** Localhost SSRF exemption in `safety.py` (Task 7)
- **BOARD-008:** Analysis checkpointing via `get_unanalyzed_row_ids()` in `repositories.py` (Task 4) and per-post result returns in `sentiment.py` (Task 15)
- **BOARD-011:** Thematic chunking for >50 posts in `thematic.py` (Task 16)
- **BOARD-012:** Output validation in `schemas.py` (Task 12)

### Dependency Order

```
Task 0 (scaffolding)
  └── Task 1 (engine)
       └── Task 2 (models)
            ├── Task 3 (migrations) ← depends on engine
            └── Task 4 (repositories) ← depends on engine, models, migrations
  └── Task 5 (llm/config)
       └── Task 6 (providers) ← depends on config
            └── Task 7 (safety)
                 └── Task 8 (router) ← depends on providers, safety
  └── Task 9 (http client)
       └── Task 10 (collector base) ← depends on models
            └── Task 11 (reddit) ← depends on base, http
  └── Task 12 (schemas) ← depends on models
       └── Task 13 (prompts) ← depends on models
            └── Task 14 (analyzer base) ← depends on config, providers
                 └── Task 15 (sentiment) ← depends on base, prompts, schemas
                 └── Task 16 (thematic) ← depends on base, prompts, schemas
  └── Task 17 (integration) ← depends on everything above
```
