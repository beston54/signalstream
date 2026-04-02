"""Tests for JSON API routes."""

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


class TestListJobs:
    """GET /api/jobs"""

    def test_returns_job_list(self, client):
        jobs = [{"job_id": "j1", "topic": "bitcoin", "status": "completed"}]
        with patch(f"{_DB}.get_all_jobs", return_value=jobs, create=True):
            resp = client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["job_id"] == "j1"

    def test_returns_empty_list(self, client):
        with patch(f"{_DB}.get_all_jobs", return_value=[], create=True):
            resp = client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.get_json()["jobs"] == []


class TestJobStatus:
    """GET /api/jobs/<job_id>/status"""

    def test_returns_status_for_existing_job(self, client):
        mock_status = MagicMock()
        mock_status.job_id = "j1"
        mock_status.stage = "analyzing"
        mock_status.items_completed = 15
        mock_status.items_total = 37
        mock_status.message = "Analyzing post 15/37..."
        mock_status.elapsed_seconds = 42.5
        mock_status.status = "analyzing"
        mock_status.error = None

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = mock_status

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.get("/api/jobs/j1/status")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stage"] == "analyzing"
        assert data["items_completed"] == 15
        assert data["items_total"] == 37
        assert data["elapsed_seconds"] == 42.5

    def test_nonexistent_job_returns_404(self, client):
        mock_manager = MagicMock()
        mock_manager.get_status.return_value = None

        with patch(_JM_PATH, return_value=mock_manager, create=True):
            resp = client.get("/api/jobs/nope/status")

        assert resp.status_code == 404
        assert resp.get_json()["code"] == "JOB_NOT_FOUND"


class TestJobResults:
    """GET /api/jobs/<job_id>/results"""

    def test_returns_results_for_completed_job(self, client):
        job = {"job_id": "j1", "topic": "bitcoin"}
        stats = {"sentiment_counts": {"positive": 20}}
        with patch(f"{_DB}.get_job", return_value=job, create=True), \
             patch(f"{_DB}.get_job_statistics", return_value=stats, create=True):
            resp = client.get("/api/jobs/j1/results")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job"]["topic"] == "bitcoin"
        assert data["statistics"]["sentiment_counts"]["positive"] == 20

    def test_nonexistent_job_returns_404(self, client):
        with patch(f"{_DB}.get_job", return_value=None, create=True), \
             patch(f"{_DB}.get_job_statistics", create=True):
            resp = client.get("/api/jobs/nope/results")
        assert resp.status_code == 404


class TestExportJson:
    """GET /api/jobs/<job_id>/export/json"""

    def test_returns_json_download(self, client):
        with patch(f"{_DB}.get_job", return_value={"job_id": "j1"}, create=True), \
             patch("signalstream.reports.exports.export_json", return_value={"data": "test"}):
            resp = client.get("/api/jobs/j1/export/json")

        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")


class TestDeleteAllData:
    """DELETE /api/data"""

    def test_delete_all_data(self, client):
        # Need CSRF bypass — use X-LLM-Provider header
        with patch(f"{_DB}.delete_all_data", create=True):
            resp = client.delete(
                "/api/data",
                headers={"X-LLM-Provider": "claude"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True
