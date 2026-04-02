"""Security headers and CSRF protection middleware.

Addresses BOARD-005 (security headers) and BOARD-013 (CSRF protection).
Registered via init_security(app) in the app factory.
"""

from __future__ import annotations

import hmac
import secrets
from typing import TYPE_CHECKING

from flask import abort, request

if TYPE_CHECKING:
    from flask import Flask, Response

# Security headers applied to every response
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

_CSRF_COOKIE_NAME = "csrf_token"
_CSRF_HEADER_NAME = "X-CSRF-Token"
_CSRF_TOKEN_LENGTH = 32  # 32 bytes = 64 hex chars
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def init_security(app: Flask) -> None:
    """Register security middleware on the Flask app.

    Call this in the app factory after creating the app.
    """
    app.after_request(_add_security_headers)
    app.before_request(_check_csrf_token)


def _add_security_headers(response: Response) -> Response:
    """Set security headers on every response. Also sets CSRF cookie."""
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value

    # Set CSRF cookie if not already present on the request
    if _CSRF_COOKIE_NAME not in request.cookies:
        token = secrets.token_hex(_CSRF_TOKEN_LENGTH)
        response.set_cookie(
            _CSRF_COOKIE_NAME,
            token,
            httponly=False,  # JS must read this for double-submit
            samesite="Strict",
            secure=False,  # localhost — no HTTPS
            path="/",
        )

    return response


def _check_csrf_token() -> None:
    """Validate CSRF double-submit cookie on state-changing requests.

    Exempt:
    - Safe methods (GET, HEAD, OPTIONS)
    - API routes that use X-LLM-* headers (already require custom headers)
    """
    if request.method not in _STATE_CHANGING_METHODS:
        return

    # API endpoints using X-LLM-Provider are implicitly CSRF-protected
    # because custom headers cannot be sent cross-origin without CORS preflight
    if request.headers.get("X-LLM-Provider"):
        return

    cookie_token = request.cookies.get(_CSRF_COOKIE_NAME)
    header_token = request.headers.get(_CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        abort(403, description="Missing CSRF token")

    if not hmac.compare_digest(cookie_token, header_token):
        abort(403, description="Invalid CSRF token")


def get_csrf_token() -> str:
    """Get the current CSRF token from the request cookie.

    For use in Jinja2 templates: {{ csrf_token() }}
    """
    token = request.cookies.get(_CSRF_COOKIE_NAME)
    if not token:
        # Generate a fresh token — will be set in the response cookie
        token = secrets.token_hex(_CSRF_TOKEN_LENGTH)
    return token
