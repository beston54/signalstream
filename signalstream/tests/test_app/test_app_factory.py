"""Tests for the Flask app factory."""

from signalstream.app import create_app


class TestAppFactory:
    """Verify app factory configuration."""

    def test_create_app_returns_flask_instance(self):
        app = create_app(testing=True)
        assert app is not None
        assert app.config["TESTING"] is True

    def test_debug_off_by_default(self):
        app = create_app(testing=True)
        assert app.config["DEBUG"] is False

    def test_security_headers_on_response(self):
        app = create_app(testing=True)
        client = app.test_client()
        resp = client.get("/")
        # Even a 404 should have security headers
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_404_returns_json(self):
        app = create_app(testing=True)
        client = app.test_client()
        resp = client.get("/nonexistent-route")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    def test_csrf_token_in_jinja_globals(self):
        app = create_app(testing=True)
        assert "csrf_token" in app.jinja_env.globals
