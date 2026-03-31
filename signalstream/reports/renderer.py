"""
PDF and HTML rendering for reports.

WeasyPrint is an optional dependency (BOARD-002). If not installed,
render_html() still works and render_pdf() raises RuntimeError.

SSRF mitigation: custom url_fetcher blocks ALL external resource
loading. Only data: URIs are permitted.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# -- WeasyPrint optional import (BOARD-002) ---------------------------

try:
    import weasyprint

    PDF_AVAILABLE = True
except (ImportError, OSError):
    weasyprint = None  # type: ignore[assignment]
    PDF_AVAILABLE = False

# -- Template setup ---------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "pdf_templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _load_css() -> str:
    """Read the PDF stylesheet as a string."""
    css_path = _TEMPLATE_DIR / "styles.css"
    return css_path.read_text(encoding="utf-8")


# -- SSRF-safe URL fetcher (BOARD-002) --------------------------------


def _safe_url_fetcher(
    url: str,
    timeout: int = 10,
    ssl_context: Any = None,
) -> dict:
    """Block all external resource loading in PDF generation.

    Only data: URIs are permitted. Everything else is blocked.
    """
    if url.startswith("data:"):
        # Parse data URI ourselves to avoid needing weasyprint
        # for the url_fetcher test when weasyprint is not installed
        if "," in url:
            header, data = url.split(",", 1)
            mime = "application/octet-stream"
            if ":" in header and ";" in header:
                mime = header.split(":")[1].split(";")[0]
            return {
                "string": base64.b64decode(data),
                "mime_type": mime,
            }
        return {"string": b"", "mime_type": "application/octet-stream"}
    raise ValueError(
        f"Blocked external resource in PDF template: {url}",
    )


# -- Public API -------------------------------------------------------


def render_html(content: Any) -> str:
    """Render a ReportContent into an HTML string.

    Works regardless of WeasyPrint availability.
    """
    template = _jinja_env.get_template("report.html")
    css = _load_css()
    return template.render(content=content, css=css)


def render_pdf(content: Any) -> bytes:
    """Render a ReportContent into a PDF document.

    Requires WeasyPrint. Raises RuntimeError if not installed.
    """
    if not PDF_AVAILABLE:
        raise RuntimeError(
            "PDF export requires WeasyPrint. Install with:\n"
            "  pip install signalstream[pdf]\n"
            "\n"
            "On macOS, you may also need:\n"
            "  brew install cairo pango gdk-pixbuf libffi\n"
            "\n"
            "Or use Docker, which includes all dependencies:\n"
            "  docker compose up"
        )

    html_string = render_html(content)

    html_doc = weasyprint.HTML(
        string=html_string,
        url_fetcher=_safe_url_fetcher,
    )
    return html_doc.write_pdf()
