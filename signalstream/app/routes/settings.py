"""Settings routes — provider detection and key validation.

Provides:
- GET /settings — Settings page
- GET /api/providers/detect — Auto-detect Ollama
- POST /api/providers/validate — Test provider connection
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, render_template, request

from signalstream.app.errors import ErrorCode, error_response
from signalstream.llm.config import VALID_PROVIDERS, ProviderConfig

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings")
def settings_page():
    """Render the settings page."""
    return render_template("pages/settings.html")


@settings_bp.route("/api/providers/detect")
def detect_providers():
    """Auto-detect available LLM providers.

    Pings Ollama at localhost:11434/api/tags. Returns available models
    if Ollama is running, or null if not.
    """
    from signalstream.llm.router import detect_ollama

    ollama_info = detect_ollama()

    return jsonify({
        "ollama": ollama_info,  # {models: [...]} or None
    })


@settings_bp.route("/api/providers/validate", methods=["POST"])
def validate_provider():
    """Test a provider connection with the given credentials.

    Expects X-LLM-* headers (extracted by middleware into g.provider_config).
    Makes a minimal test call to verify the provider is reachable and the
    key is valid.
    """
    config: ProviderConfig | None = g.get("provider_config")

    # Check for invalid provider name (middleware sets None on ValueError)
    raw_provider = request.headers.get("X-LLM-Provider")
    if raw_provider and not config:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT,
            detail=(
                f"Unknown provider '{raw_provider}'. "
                f"Must be one of: {', '.join(sorted(VALID_PROVIDERS))}"
            ),
        )), 400

    if not config:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT, detail="No provider specified. Set X-LLM-Provider header."
        )), 400

    # SSRF check for custom endpoints
    if config.endpoint:
        from signalstream.llm.safety import validate_endpoint
        try:
            validate_endpoint(config.endpoint)
        except ValueError:
            return jsonify(error_response(
                ErrorCode.SSRF_BLOCKED, url=config.endpoint,
            )), 400

    # Pre-flight test call
    from signalstream.llm.router import create_provider, preflight_check

    try:
        provider = create_provider(config)
        preflight_check(provider, config.model)
    except ConnectionError:
        return jsonify(error_response(
            ErrorCode.PROVIDER_UNREACHABLE, provider=config.provider,
        )), 502
    except PermissionError:
        return jsonify(error_response(
            ErrorCode.PROVIDER_AUTH_FAILED, provider=config.provider,
        )), 401
    except Exception as e:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT, detail=str(e),
        )), 400

    return jsonify({
        "valid": True,
        "provider": config.provider,
        "model": config.model,
    })
