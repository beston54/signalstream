"""End-to-end tests for the complete web layer.

Verifies the assembled application works as a coherent unit:
- App factory produces a functional app
- All routes respond with correct status codes
- Security middleware is active
- CSRF protection enforces on state-changing routes
- Error handlers produce JSON responses
"""

from unittest.mock import patch

import pytest

from signalstream.app import create_app


@pytest.fixture
def client():
    app = create_app(testing=True)
    return app.test_client()


class TestRouteAccessibility:
    """All page routes must return 200."""

    @pytest.mark.parametrize("path", [
        "/",
        "/settings",
        "/analyze",
        "/results/any-job-id",
    ])
    def test_page_routes_return_200(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"

    def test_api_detect_providers(self, client):
        with patch("signalstream.llm.router.detect_ollama", return_value=None, create=True):
            resp = client.get("/api/providers/detect")
        assert resp.status_code == 200


class TestSecurityEnforcement:
    """Security headers must be on EVERY response, including errors."""

    def test_security_headers_on_200(self, client):
        resp = client.get("/")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_security_headers_on_404(self, client):
        resp = client.get("/nonexistent-page-12345")
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_csp_blocks_inline_scripts(self, client):
        resp = client.get("/")
        csp = resp.headers["Content-Security-Policy"]
        script_src = csp.split("script-src")[1].split(";")[0]
        assert "'unsafe-inline'" not in script_src

    def test_csrf_blocks_unprotected_post(self, client):
        resp = client.post("/api/providers/validate")
        assert resp.status_code in (400, 403)


class TestErrorHandling:
    """Error responses must be JSON with structured codes."""

    def test_404_is_json(self, client):
        resp = client.get("/no-such-page")
        data = resp.get_json()
        assert data is not None
        assert data["error"] is True

    def test_missing_provider_on_job_create(self, client):
        resp = client.post("/api/jobs", json={"topic": "test"})
        # 403 from CSRF or 400 from missing provider — both are correct rejections
        assert resp.status_code in (400, 403)
        data = resp.get_json()
        assert data["error"] is True


class TestDemoDataFlow:
    """Demo data path must work without any LLM provider."""

    def test_demo_fixture_loads(self):
        from signalstream.fixtures.demo_data import load_demo_data
        job, stats = load_demo_data()
        assert job["job_id"] == "demo-remote-work-2026"
        assert job["status"] == "completed"
        assert stats["total_posts"] == 47
        assert len(stats["themes"]) == 5
        assert stats["sentiment_counts"]["positive"] > 0
