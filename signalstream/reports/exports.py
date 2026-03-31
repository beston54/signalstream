"""
JSON export for analysis results.

Serializes ReportContent into JSON for API responses, file download,
and downstream analysis tools. Charts (large base64 blobs) are excluded
by default. Post text is truncated for data minimization.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

_MAX_POST_TEXT_LENGTH = 500


def _prepare_export_dict(
    content: Any,
    include_charts: bool = False,
) -> dict[str, Any]:
    """Convert ReportContent to an export-ready dict."""
    data = asdict(content)

    if not include_charts:
        data.pop("charts", None)

    for post_data in data.get("analyzed_posts", []):
        post = post_data.get("post", {})
        text = post.get("text", "")
        if len(text) > _MAX_POST_TEXT_LENGTH:
            post["text"] = text[:_MAX_POST_TEXT_LENGTH]

    return data


def export_dict(
    content: Any, include_charts: bool = False,
) -> dict[str, Any]:
    """Convert ReportContent to a plain dict for API responses."""
    return _prepare_export_dict(
        content, include_charts=include_charts,
    )


def export_json(
    content: Any,
    include_charts: bool = False,
    indent: int = 2,
) -> str:
    """Serialize ReportContent to a formatted JSON string."""
    data = _prepare_export_dict(
        content, include_charts=include_charts,
    )
    return json.dumps(
        data, indent=indent, ensure_ascii=False, default=str,
    )
