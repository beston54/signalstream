"""Shared test fixtures for all signalstream tests."""
from __future__ import annotations

import sqlite3
import tempfile
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
    """A mock LLM provider for testing analyzers without real API calls."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses: list[str] = responses or ["MOCK_RESPONSE"]
        self.calls: list[tuple] = []
        self._call_index: int = 0

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: object | None = None,
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
