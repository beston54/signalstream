"""Error code catalog with user-facing messages.

Every user-facing error uses a structured ErrorInfo. Error codes are referenced
by routes and middleware — never raise raw HTTP errors with ad-hoc strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class ErrorInfo:
    """Structured error for API and template responses."""

    code: str
    http_status: int
    message: str  # May contain {placeholders} for .format()
    action: str  # Suggested next step for the user


class ErrorCode(Enum):
    """All user-facing error codes.

    Usage:
        err = ErrorCode.PROVIDER_UNREACHABLE
        resp = err.value  # ErrorInfo instance
        msg = resp.message.format(provider="Claude")
    """

    PROVIDER_UNREACHABLE = ErrorInfo(
        code="PROVIDER_UNREACHABLE",
        http_status=502,
        message="Could not reach {provider}. Check your internet connection.",
        action="retry",
    )
    PROVIDER_AUTH_FAILED = ErrorInfo(
        code="PROVIDER_AUTH_FAILED",
        http_status=401,
        message="Your {provider} API key appears to be invalid or expired.",
        action="open_settings",
    )
    PROVIDER_RATE_LIMITED = ErrorInfo(
        code="PROVIDER_RATE_LIMITED",
        http_status=429,
        message="Rate limited by {provider}. Retrying in {seconds} seconds...",
        action="wait",
    )
    PROVIDER_CONTEXT_EXCEEDED = ErrorInfo(
        code="PROVIDER_CONTEXT_EXCEEDED",
        http_status=422,
        message="Post too long for {model}. Skipping.",
        action="skip",
    )
    COLLECTOR_RATE_LIMITED = ErrorInfo(
        code="COLLECTOR_RATE_LIMITED",
        http_status=429,
        message="Reddit is rate-limiting requests. Waiting...",
        action="wait",
    )
    COLLECTOR_EMPTY = ErrorInfo(
        code="COLLECTOR_EMPTY",
        http_status=404,
        message="No posts found for '{topic}'. Try broader search terms.",
        action="edit_topic",
    )
    COLLECTOR_BLOCKED = ErrorInfo(
        code="COLLECTOR_BLOCKED",
        http_status=503,
        message="Reddit is not responding. Try again in a few minutes.",
        action="retry_later",
    )
    ANALYSIS_PARSE_FAILED = ErrorInfo(
        code="ANALYSIS_PARSE_FAILED",
        http_status=422,
        message="Could not parse analysis for {count} posts.",
        action="shown_in_results",
    )
    ANALYSIS_PARTIAL = ErrorInfo(
        code="ANALYSIS_PARTIAL",
        http_status=200,
        message="Analysis complete ({completed} of {total} posts analyzed).",
        action="shown_in_results",
    )
    REPORT_PDF_UNAVAILABLE = ErrorInfo(
        code="REPORT_PDF_UNAVAILABLE",
        http_status=501,
        message="PDF export requires additional setup. Install with: pip install signalstream[pdf]",
        action="show_install",
    )
    DB_LOCKED = ErrorInfo(
        code="DB_LOCKED",
        http_status=503,
        message="Database is busy. Please try again.",
        action="auto_retry",
    )
    JOB_NOT_FOUND = ErrorInfo(
        code="JOB_NOT_FOUND",
        http_status=404,
        message="Job '{job_id}' not found.",
        action="go_home",
    )
    INVALID_INPUT = ErrorInfo(
        code="INVALID_INPUT",
        http_status=400,
        message="{detail}",
        action="fix_input",
    )
    SSRF_BLOCKED = ErrorInfo(
        code="SSRF_BLOCKED",
        http_status=400,
        message="The endpoint URL '{url}' is not allowed. Use a public HTTPS URL or localhost.",
        action="fix_input",
    )


def error_response(error: ErrorCode, **kwargs: str) -> dict:
    """Build a JSON-serializable error response dict.

    Args:
        error: The ErrorCode enum member.
        **kwargs: Values to interpolate into the message template.

    Returns:
        Dict with 'error', 'code', 'message', 'action' keys.
    """
    info = error.value
    return {
        "error": True,
        "code": info.code,
        "message": info.message.format(**kwargs),
        "action": info.action,
    }
