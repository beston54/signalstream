"""API key extraction and redaction middleware.

Addresses BOARD-009 (API key logging). Extracts X-LLM-* headers into a
ProviderConfig, strips keys from request.environ before any logging can
occur, and installs a logging.Filter that redacts key patterns from all
log messages.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from flask import g, request

if TYPE_CHECKING:
    from flask import Flask

from signalstream.llm.config import ProviderConfig

# Headers used for LLM provider configuration
_HEADER_PROVIDER = "X-LLM-Provider"
_HEADER_API_KEY = "X-LLM-API-Key"
_HEADER_MODEL = "X-LLM-Model"
_HEADER_ENDPOINT = "X-LLM-Endpoint"

# Patterns to redact from log messages
_REDACT_PATTERNS = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{20,})"
)
_REDACT_REPLACEMENT = "[REDACTED]"

# HTTP_* keys in environ that correspond to our sensitive headers
_SENSITIVE_ENVIRON_KEYS = (
    "HTTP_X_LLM_API_KEY",
)


class KeyRedactionFilter(logging.Filter):
    """Logging filter that redacts API key patterns from log messages.

    Catches sk-ant-* (Anthropic) and sk-* (OpenAI) patterns in any
    log record message, args, or string representation.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Always returns True (never drops records), but mutates the message."""
        if record.msg and isinstance(record.msg, str):
            record.msg = _REDACT_PATTERNS.sub(_REDACT_REPLACEMENT, record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (
                        _REDACT_PATTERNS.sub(_REDACT_REPLACEMENT, v)
                        if isinstance(v, str)
                        else v
                    )
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _REDACT_PATTERNS.sub(_REDACT_REPLACEMENT, a)
                    if isinstance(a, str)
                    else a
                    for a in record.args
                )
        return True


def init_api_key_middleware(app: Flask) -> None:
    """Register API key middleware on the Flask app.

    - Installs the KeyRedactionFilter on all loggers.
    - Registers a before_request handler that extracts and strips keys.
    """
    # Install redaction filter on the root logger so ALL log output is filtered
    redaction_filter = KeyRedactionFilter()
    logging.getLogger().addFilter(redaction_filter)

    # Also install on Flask's logger and werkzeug's logger
    app.logger.addFilter(redaction_filter)
    logging.getLogger("werkzeug").addFilter(redaction_filter)

    app.before_request(_extract_and_strip_keys)


def _extract_and_strip_keys() -> None:
    """Extract X-LLM-* headers into g.provider_config, strip from environ.

    After this runs, the API key is no longer accessible via request.environ
    or request.headers for any downstream logging.
    """
    provider = request.headers.get(_HEADER_PROVIDER)
    api_key = request.headers.get(_HEADER_API_KEY)
    model = request.headers.get(_HEADER_MODEL)
    endpoint = request.headers.get(_HEADER_ENDPOINT)

    # Build ProviderConfig if a provider was specified
    if provider:
        g.provider_config = ProviderConfig(
            provider=provider,
            api_key=api_key,
            model=model or "",
            endpoint=endpoint,
        )
    else:
        g.provider_config = None

    # Strip sensitive headers from environ BEFORE any logging can access them
    for key in _SENSITIVE_ENVIRON_KEYS:
        request.environ.pop(key, None)
