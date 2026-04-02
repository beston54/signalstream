"""Tests for analysis routes — job creation and cancellation."""

from unittest.mock import MagicMock, patch

import pytest

from signalstream.app import create_app


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def _llm_headers(provider="claude", key="sk-ant-test", model="claude-sonnet-4-20250514"):
    """Build X-LLM-* headers."""
    h = {"X-LLM-Provider": provider, "X-LLM-Model": model}
    if key:
        h["X-LLM-API-Key"] = key
    return h


_JM_PATH = "signalstream.jobs.manager.JobManager.get_instance"


def _csrf_headers(client):
    """Get a valid CSRF token by making a GET request first."""
    client.get("/")
    cookie = client.get_cookie("csrf_token")
    return {"X-CSRF-Token": cookie.value}


class TestStartJob:
    """POST /api/jobs"""

    def test_missing_provider_returns_400(self, client):
        headers = _csrf_headers(client)
        resp = client.post(
            "/api/jobs",
            json={"topic": "bitcoin"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_missing_topic_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400
        assert "Topic is required" in resp.get_json()["message"]

    def test_empty_topic_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={"topic": "   "},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400

    def test_topic_too_long_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={"topic": "x" * 201},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400
        assert "200 characters" in resp.get_json()["message"]

    def test_invalid_time_range_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={"topic": "bitcoin", "time_range": "century"},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400

    def test_max_posts_too_high_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={"topic": "bitcoin", "max_posts": 501},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400

    def test_max_posts_zero_returns_400(self, client):
        resp = client.post(
            "/api/jobs",
            json={"topic": "bitcoin", "max_posts": 0},
            headers=_llm_headers(),
        )
        assert resp.status_code == 400

    def test_successful_job_submission(self, client):
        mock_manager = MagicMock()
        mock_manager.submit_job.return_value = "job-abc-123"

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.post(
                "/api/jobs",
                json={"topic": "bitcoin", "time_range": "week", "max_posts": 50},
                headers=_llm_headers(),
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["job_id"] == "job-abc-123"
        assert data["status"] == "pending"

    def test_defaults_applied(self, client):
        mock_manager = MagicMock()
        mock_manager.submit_job.return_value = "job-xyz"

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.post(
                "/api/jobs",
                json={"topic": "bitcoin"},
                headers=_llm_headers(),
            )

        assert resp.status_code == 201
        call_kwargs = mock_manager.submit_job.call_args[1]
        assert call_kwargs["time_range"] == "month"
        assert call_kwargs["max_posts"] == 100


class TestCancelJob:
    """POST /api/jobs/<job_id>/cancel"""

    def test_cancel_running_job(self, client):
        mock_manager = MagicMock()
        mock_manager.cancel_job.return_value = True

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.post(
                "/api/jobs/job-123/cancel",
                headers={"X-LLM-Provider": "claude"},  # bypass CSRF
            )

        assert resp.status_code == 200
        assert resp.get_json()["cancelled"] is True

    def test_cancel_nonexistent_job_returns_404(self, client):
        mock_manager = MagicMock()
        mock_manager.cancel_job.return_value = False

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.post(
                "/api/jobs/no-such-job/cancel",
                headers={"X-LLM-Provider": "claude"},
            )

        assert resp.status_code == 404
