"""Dashboard routes — home page and results view.

Provides:
- GET / — Home page (search box, first-run flow)
- GET /results/<job_id> — Results dashboard for a completed job
"""

from __future__ import annotations

from flask import Blueprint, render_template

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def home():
    """Home page with search box.

    This is the first-run entry point. Shows:
    - Search box for topic input
    - Inline provider selector (if no provider configured in localStorage)
    - Recent analyses (if any exist)
    """
    return render_template("pages/home.html")


@dashboard_bp.route("/results/<job_id>")
def results(job_id: str):
    """Results dashboard for a specific job.

    The page itself is a shell — all data is loaded client-side via
    GET /api/jobs/<job_id>/results and rendered with Chart.js.

    Template handles 4 states:
    1. Empty — job completed but no results (unlikely but handled)
    2. Loading — skeleton/spinner while API call is in flight
    3. Error — job failed, show error message with retry action
    4. Populated — charts, themes, statistics, export buttons
    """
    return render_template("pages/results.html", job_id=job_id)
