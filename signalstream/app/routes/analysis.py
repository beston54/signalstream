"""Analysis routes — start jobs, view progress.

Provides:
- GET /analyze — Analysis page (first-run flow + progress)
- POST /api/jobs — Start a new analysis job
- POST /api/jobs/<job_id>/cancel — Cancel a running job
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, render_template, request

from signalstream.app.errors import ErrorCode, error_response

analysis_bp = Blueprint("analysis", __name__)

# Input validation limits
_MAX_TOPIC_LENGTH = 200
_MAX_POSTS_LIMIT = 500
_DEFAULT_MAX_POSTS = 100
_VALID_TIME_RANGES = {"day", "week", "month", "year", "all"}


@analysis_bp.route("/analyze")
def analyze_page():
    """Render the analysis page.

    Handles the first-run flow: topic input, inline provider selector,
    and progress display.
    """
    return render_template("pages/analyze.html")


@analysis_bp.route("/api/jobs", methods=["POST"])
def start_job():
    """Start a new analysis job.

    Request JSON body:
        topic (str): Search topic (required)
        time_range (str): day|week|month|year|all (default: month)
        max_posts (int): Maximum posts to collect (default: 100, max: 500)

    Provider config comes from X-LLM-* headers (extracted by middleware).

    Returns:
        201 with {job_id, status} on success.
    """
    config = g.get("provider_config")
    if not config:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT,
            detail="No LLM provider configured. Set X-LLM-Provider header.",
        )), 400

    # Parse request body
    data = request.get_json(silent=True) or {}

    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT, detail="Topic is required.",
        )), 400
    if len(topic) > _MAX_TOPIC_LENGTH:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT,
            detail=f"Topic must be {_MAX_TOPIC_LENGTH} characters or fewer.",
        )), 400

    time_range = data.get("time_range", "month")
    if time_range not in _VALID_TIME_RANGES:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT,
            detail=f"time_range must be one of: {', '.join(sorted(_VALID_TIME_RANGES))}",
        )), 400

    max_posts = data.get("max_posts", _DEFAULT_MAX_POSTS)
    try:
        max_posts = int(max_posts)
    except (TypeError, ValueError):
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT, detail="max_posts must be an integer.",
        )), 400
    if max_posts < 1 or max_posts > _MAX_POSTS_LIMIT:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT,
            detail=f"max_posts must be between 1 and {_MAX_POSTS_LIMIT}.",
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

    # Submit job
    from signalstream.jobs.manager import JobManager

    manager = JobManager.get_instance()
    try:
        job_id = manager.submit_job(
            topic=topic,
            time_range=time_range,
            max_posts=max_posts,
            provider_config=config,
        )
    except RuntimeError as e:
        return jsonify(error_response(
            ErrorCode.INVALID_INPUT, detail=str(e),
        )), 400

    return jsonify({"job_id": job_id, "status": "pending"}), 201


@analysis_bp.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    """Cancel a running job.

    Returns:
        200 with {cancelled: true} if job was running and is now cancelled.
        404 if job not found.
    """
    from signalstream.jobs.manager import JobManager

    manager = JobManager.get_instance()
    cancelled = manager.cancel_job(job_id)

    if cancelled:
        return jsonify({"cancelled": True, "job_id": job_id})

    return jsonify(error_response(
        ErrorCode.JOB_NOT_FOUND, job_id=job_id,
    )), 404
