"""Tests for settings routes — provider detection and validation."""

from unittest.mock import patch

import pytest

from signalstream.app import create_app


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestDetectProviders:
    """GET /api/providers/detect"""

    def test_returns_ollama_info_when_running(self, client):
        mock_result = {"models": ["llama3.1:8b", "mistral:7b"]}
        with patch("signalstream.llm.router.detect_ollama", return_value=mock_result, create=True):
            resp = client.get("/api/providers/detect")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ollama"]["models"] == ["llama3.1:8b", "mistral:7b"]

    def test_returns_null_when_ollama_not_running(self, client):
        with patch("signalstream.llm.router.detect_ollama", return_value=None, create=True):
            resp = client.get("/api/providers/detect")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ollama"] is None


class TestValidateProvider:
    """POST /api/providers/validate"""

    def test_missing_provider_returns_400(self, client):
        client.get("/")
        cookie = client.get_cookie("csrf_token")
        resp = client.post(
            "/api/providers/validate",
            headers={"X-CSRF-Token": cookie.value},
        )
        assert resp.status_code == 400

    def test_invalid_provider_returns_400(self, client):
        resp = client.post(
            "/api/providers/validate",
            headers={"X-LLM-Provider": "invalid"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Unknown provider" in data["message"]

    def test_valid_claude_provider(self, client):
        with patch("signalstream.llm.router.create_provider", create=True), \
             patch("signalstream.llm.router.preflight_check", create=True):
            resp = client.post(
                "/api/providers/validate",
                headers={
                    "X-LLM-Provider": "claude",
                    "X-LLM-API-Key": "sk-ant-test",
                    "X-LLM-Model": "claude-sonnet-4-20250514",
                },
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is True
        assert data["provider"] == "claude"

    def test_unreachable_provider_returns_502(self, client):
        with patch("signalstream.llm.router.create_provider", create=True), \
             patch(
                 "signalstream.llm.router.preflight_check",
                 side_effect=ConnectionError("timeout"),
                 create=True,
             ):
            resp = client.post(
                "/api/providers/validate",
                headers={
                    "X-LLM-Provider": "claude",
                    "X-LLM-API-Key": "sk-ant-test",
                    "X-LLM-Model": "claude-sonnet-4-20250514",
                },
            )
        assert resp.status_code == 502
        data = resp.get_json()
        assert data["code"] == "PROVIDER_UNREACHABLE"

    def test_auth_failure_returns_401(self, client):
        with patch("signalstream.llm.router.create_provider", create=True), \
             patch(
                 "signalstream.llm.router.preflight_check",
                 side_effect=PermissionError("bad key"),
                 create=True,
             ):
            resp = client.post(
                "/api/providers/validate",
                headers={
                    "X-LLM-Provider": "claude",
                    "X-LLM-API-Key": "sk-ant-bad",
                    "X-LLM-Model": "claude-sonnet-4-20250514",
                },
            )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["code"] == "PROVIDER_AUTH_FAILED"

    def test_ssrf_blocked_endpoint(self, client):
        with patch(
            "signalstream.llm.safety.validate_endpoint",
            side_effect=ValueError("blocked"),
        ):
            resp = client.post(
                "/api/providers/validate",
                headers={
                    "X-LLM-Provider": "openai-compat",
                    "X-LLM-API-Key": "sk-test",
                    "X-LLM-Model": "gpt-4o",
                    "X-LLM-Endpoint": "http://169.254.169.254/latest",
                },
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["code"] == "SSRF_BLOCKED"
