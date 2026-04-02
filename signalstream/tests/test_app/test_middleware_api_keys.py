"""Tests for API key extraction and log redaction."""

import logging

import pytest
from flask import Flask, g

from signalstream.app.middleware.api_keys import (
    _SENSITIVE_ENVIRON_KEYS,
    KeyRedactionFilter,
    init_api_key_middleware,
)


@pytest.fixture
def app():
    """Minimal Flask app with API key middleware."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_api_key_middleware(app)

    @app.route("/check")
    def check():
        config = g.get("provider_config")
        if config:
            return {
                "provider": config.provider,
                "has_key": config.api_key is not None,
                "model": config.model,
            }
        return {"provider": None}

    @app.route("/environ")
    def environ_check():
        """Check that sensitive keys were stripped from environ."""
        found = {
            key: key in g.get("_request_environ", {})
            for key in _SENSITIVE_ENVIRON_KEYS
        }
        return found

    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestKeyExtraction:
    """Verify X-LLM-* headers are extracted into ProviderConfig."""

    def test_extracts_provider_config(self, client):
        resp = client.get(
            "/check",
            headers={
                "X-LLM-Provider": "claude",
                "X-LLM-API-Key": "sk-ant-test123",
                "X-LLM-Model": "claude-sonnet-4-20250514",
            },
        )
        data = resp.get_json()
        assert data["provider"] == "claude"
        assert data["has_key"] is True
        assert data["model"] == "claude-sonnet-4-20250514"

    def test_no_headers_yields_none(self, client):
        resp = client.get("/check")
        data = resp.get_json()
        assert data["provider"] is None

    def test_provider_without_key(self, client):
        resp = client.get(
            "/check",
            headers={"X-LLM-Provider": "ollama", "X-LLM-Model": "llama3.1:8b"},
        )
        data = resp.get_json()
        assert data["provider"] == "ollama"
        assert data["has_key"] is False


class TestKeyRedactionFilter:
    """Verify log redaction of API key patterns."""

    def test_redacts_anthropic_key(self):
        f = KeyRedactionFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Key is sk-ant-api03-abcdef1234567890abcdef", args=(), exc_info=None,
        )
        f.filter(record)
        assert "sk-ant-" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_redacts_openai_key(self):
        f = KeyRedactionFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Key is sk-proj-abcdef1234567890abcdef1234", args=(), exc_info=None,
        )
        f.filter(record)
        assert "sk-proj-" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_preserves_normal_messages(self):
        f = KeyRedactionFilter()
        original = "Job abc-123 completed successfully"
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=original, args=(), exc_info=None,
        )
        f.filter(record)
        assert record.msg == original

    def test_redacts_key_in_args_tuple(self):
        f = KeyRedactionFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Provider used key %s", args=("sk-ant-api03-abcdef1234567890",), exc_info=None,
        )
        f.filter(record)
        assert "[REDACTED]" in record.args[0]

    def test_redacts_key_in_args_dict(self):
        f = KeyRedactionFilter()
        # Wrap dict in tuple so LogRecord.__init__ can unpack it
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Config: %(key)s",
            args=({"key": "sk-ant-api03-abcdef1234567890"},),
            exc_info=None,
        )
        f.filter(record)
        assert "[REDACTED]" in record.args["key"]
