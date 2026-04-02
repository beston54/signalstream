"""Integration tests for the full web flow."""

from unittest.mock import MagicMock, patch

import pytest

from signalstream.app import create_app

_JM_PATH = "signalstream.jobs.manager.JobManager.get_instance"
_DB = "signalstream.db.repositories"


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestFullWebFlow:
    """Test the complete analysis flow through the web interface."""

    def test_home_page_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Signalstream" in resp.data

    def test_settings_page_loads(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_results_page_loads(self, client):
        resp = client.get("/results/test-job")
        assert resp.status_code == 200

    def test_create_and_poll_job(self, client):
        """Full flow: create job, poll status, get results."""
        # 1. Create job
        mock_manager = MagicMock()
        mock_manager.submit_job.return_value = "job-integration-test"

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.post(
                "/api/jobs",
                json={"topic": "bitcoin", "time_range": "week", "max_posts": 25},
                headers={
                    "X-LLM-Provider": "claude",
                    "X-LLM-API-Key": "sk-ant-test",
                    "X-LLM-Model": "claude-sonnet-4-20250514",
                },
            )

        assert resp.status_code == 201
        job_id = resp.get_json()["job_id"]
        assert job_id == "job-integration-test"

        # 2. Poll status
        mock_status = MagicMock()
        mock_status.job_id = job_id
        mock_status.stage = "analyzing"
        mock_status.items_completed = 10
        mock_status.items_total = 25
        mock_status.message = "Analyzing post 10/25..."
        mock_status.elapsed_seconds = 15.0
        mock_status.status = "analyzing"
        mock_status.error = None

        mock_manager.get_status.return_value = mock_status

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.get(f"/api/jobs/{job_id}/status")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stage"] == "analyzing"
        assert data["items_completed"] == 10

        # 3. Get results
        job = {"job_id": job_id, "topic": "bitcoin", "status": "completed"}
        stats = {
            "total_posts": 25,
            "sentiment_counts": {"positive": 12, "negative": 8, "neutral": 5},
            "dominant_sentiment": "positive",
        }
        with patch(f"{_DB}.get_job", return_value=job, create=True), \
             patch(f"{_DB}.get_job_statistics", return_value=stats, create=True):
            resp = client.get(f"/api/jobs/{job_id}/results")

        assert resp.status_code == 200
        results = resp.get_json()
        assert results["job"]["topic"] == "bitcoin"
        assert results["statistics"]["total_posts"] == 25

    def test_security_headers_on_all_responses(self, client):
        """Every response must include security headers."""
        for path in ["/", "/settings", "/results/x", "/api/jobs", "/nonexistent"]:
            with patch(f"{_DB}.get_all_jobs", return_value=[], create=True):
                resp = client.get(path)
            assert resp.headers.get("X-Frame-Options") == "DENY", \
                f"Missing X-Frame-Options on {path}"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff", \
                f"Missing nosniff on {path}"
            assert "Content-Security-Policy" in resp.headers, \
                f"Missing CSP on {path}"

    def test_api_key_not_leaked_in_error_responses(self, client):
        """API keys must never appear in error responses."""
        resp = client.post(
            "/api/jobs",
            json={"topic": "test"},
            headers={
                "X-LLM-Provider": "invalid-provider",
                "X-LLM-API-Key": "sk-ant-super-secret-key-12345",
            },
        )
        # The response body should not contain the API key
        assert b"sk-ant-super-secret" not in resp.data
