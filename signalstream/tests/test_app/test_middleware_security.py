"""Tests for security headers and CSRF middleware."""

import pytest
from flask import Flask

from signalstream.app.middleware.security import (
    _CSRF_COOKIE_NAME,
    _CSRF_HEADER_NAME,
    SECURITY_HEADERS,
    init_security,
)


@pytest.fixture
def app():
    """Minimal Flask app with security middleware."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_security(app)

    @app.route("/")
    def index():
        return "ok"

    @app.route("/action", methods=["POST"])
    def action():
        return "done"

    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSecurityHeaders:
    """Verify all security headers are set on every response."""

    def test_all_security_headers_present(self, client):
        resp = client.get("/")
        for header, value in SECURITY_HEADERS.items():
            assert resp.headers.get(header) == value, f"Missing or wrong: {header}"

    def test_csp_header_value(self, client):
        resp = client.get("/")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "img-src 'self' data:" in csp

    def test_x_frame_options_deny(self, client):
        resp = client.get("/")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_nosniff(self, client):
        resp = client.get("/")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"


class TestCSRFProtection:
    """Verify CSRF double-submit cookie."""

    def test_csrf_cookie_set_on_first_get(self, client):
        client.get("/")
        cookie = client.get_cookie(_CSRF_COOKIE_NAME)
        assert cookie is not None
        assert len(cookie.value) == 64  # 32 bytes hex

    def test_post_without_csrf_returns_403(self, client):
        resp = client.post("/action")
        assert resp.status_code == 403

    def test_post_with_valid_csrf_succeeds(self, client):
        # First GET to receive the CSRF cookie
        client.get("/")
        cookie = client.get_cookie(_CSRF_COOKIE_NAME)
        token = cookie.value

        resp = client.post(
            "/action",
            headers={_CSRF_HEADER_NAME: token},
        )
        assert resp.status_code == 200

    def test_post_with_wrong_csrf_returns_403(self, client):
        client.get("/")
        resp = client.post(
            "/action",
            headers={_CSRF_HEADER_NAME: "wrong-token"},
        )
        assert resp.status_code == 403

    def test_post_with_llm_provider_header_bypasses_csrf(self, client):
        """API calls with X-LLM-Provider are CSRF-exempt (custom header = CORS preflight)."""
        resp = client.post(
            "/action",
            headers={"X-LLM-Provider": "claude"},
        )
        assert resp.status_code == 200

    def test_get_request_skips_csrf(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
