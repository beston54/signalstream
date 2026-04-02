"""Tests for dashboard routes."""

import pytest

from signalstream.app import create_app


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


class TestHomePage:
    """GET /"""

    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_has_security_headers(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


class TestResultsPage:
    """GET /results/<job_id>"""

    def test_results_returns_200(self, client):
        resp = client.get("/results/test-job-123")
        assert resp.status_code == 200

    def test_results_has_security_headers(self, client):
        resp = client.get("/results/test-job-123")
        assert resp.headers.get("Content-Security-Policy") is not None
