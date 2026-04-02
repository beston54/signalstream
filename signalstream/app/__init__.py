"""Flask app factory.

Usage:
    from signalstream.app import create_app
    app = create_app()
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify


def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application.

    Args:
        testing: If True, enables testing mode and uses an in-memory DB.

    Returns:
        Configured Flask app instance.
    """
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    # Configuration
    app.config["TESTING"] = testing
    app.config["DEBUG"] = os.environ.get("SIGNALSTREAM_DEBUG", "0") == "1"

    # Logging
    _configure_logging(app)

    # Security middleware (BOARD-005, BOARD-009)
    from signalstream.app.middleware.api_keys import init_api_key_middleware
    from signalstream.app.middleware.security import get_csrf_token, init_security

    init_security(app)
    init_api_key_middleware(app)

    # Template globals
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    # Register blueprints
    from signalstream.app.routes.analysis import analysis_bp
    from signalstream.app.routes.api import api_bp
    from signalstream.app.routes.dashboard import dashboard_bp
    from signalstream.app.routes.settings import settings_bp

    app.register_blueprint(settings_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # Error handlers
    _register_error_handlers(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Set up structured logging. Debug level only if SIGNALSTREAM_DEBUG=1."""
    level = logging.DEBUG if app.config["DEBUG"] else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _register_error_handlers(app: Flask) -> None:
    """Register JSON error handlers for common HTTP errors."""

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error=True, code="BAD_REQUEST", message=str(e.description)), 400

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify(error=True, code="FORBIDDEN", message=str(e.description)), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error=True, code="NOT_FOUND", message="Resource not found"), 404

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.exception("Unhandled exception")
        return jsonify(error=True, code="INTERNAL_ERROR", message="An internal error occurred"), 500
