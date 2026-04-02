"""JSON API routes — job status, results, exports, data management.

All routes under /api/ prefix (set in app factory blueprint registration).

Provides:
- GET /api/jobs — List all jobs
- GET /api/jobs/<job_id>/status — Poll job status (for progress)
- GET /api/jobs/<job_id>/results — Get full analysis results
- GET /api/jobs/<job_id>/export/json — Download JSON export
- GET /api/jobs/<job_id>/export/pdf — Download PDF report
- DELETE /api/data — Delete all data
"""

from __future__ import annotations

import io

from flask import Blueprint, jsonify, send_file

from signalstream.app.errors import ErrorCode, error_response

api_bp = Blueprint("api", __name__)


@api_bp.route("/jobs")
def list_jobs():
    """List all jobs with summary info."""
    from signalstream.db.repositories import get_all_jobs

    jobs = get_all_jobs()
    return jsonify({"jobs": jobs})


@api_bp.route("/jobs/<job_id>/status")
def job_status(job_id: str):
    """Poll job status for progress updates.

    Returns current stage, progress counts, elapsed time, and status.
    Polled by the frontend every 2s (doubling after 60s and 5min).
    """
    from signalstream.jobs.manager import JobManager

    manager = JobManager.get_instance()
    status = manager.get_status(job_id)

    if status is None:
        return jsonify(error_response(ErrorCode.JOB_NOT_FOUND, job_id=job_id)), 404

    return jsonify({
        "job_id": status.job_id,
        "stage": status.stage,
        "items_completed": status.items_completed,
        "items_total": status.items_total,
        "message": status.message,
        "elapsed_seconds": status.elapsed_seconds,
        "status": status.status,
        "error": status.error,
    })


@api_bp.route("/jobs/<job_id>/results")
def job_results(job_id: str):
    """Get full analysis results for a completed job.

    Returns sentiment breakdown, themes, statistics, and chart data.
    Used by the dashboard to render Chart.js visualizations.
    """
    from signalstream.db.repositories import get_job, get_job_statistics

    job = get_job(job_id)
    if job is None:
        return jsonify(error_response(ErrorCode.JOB_NOT_FOUND, job_id=job_id)), 404

    stats = get_job_statistics(job_id)

    return jsonify({
        "job": job,
        "statistics": stats,
    })


@api_bp.route("/jobs/<job_id>/export/json")
def export_json(job_id: str):
    """Download JSON export of analysis results."""
    from signalstream.db.repositories import get_job
    from signalstream.reports.exports import export_json as do_export

    job = get_job(job_id)
    if job is None:
        return jsonify(error_response(ErrorCode.JOB_NOT_FOUND, job_id=job_id)), 404

    data = do_export(job_id)
    response = jsonify(data)
    response.headers["Content-Disposition"] = f"attachment; filename=signalstream-{job_id}.json"
    return response


@api_bp.route("/jobs/<job_id>/export/pdf")
def export_pdf(job_id: str):
    """Download PDF report.

    Returns 501 if WeasyPrint is not installed, with install instructions.
    """
    from signalstream.db.repositories import get_job

    job = get_job(job_id)
    if job is None:
        return jsonify(error_response(ErrorCode.JOB_NOT_FOUND, job_id=job_id)), 404

    # Check WeasyPrint availability
    try:
        from signalstream.reports.renderer import PDF_AVAILABLE
    except ImportError:
        PDF_AVAILABLE = False  # noqa: N806

    if not PDF_AVAILABLE:
        return jsonify(error_response(ErrorCode.REPORT_PDF_UNAVAILABLE)), 501

    from signalstream.reports.renderer import render_pdf

    pdf_bytes = render_pdf(job_id)
    if pdf_bytes is None:
        return jsonify(error_response(ErrorCode.JOB_NOT_FOUND, job_id=job_id)), 404

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"signalstream-{job_id}.pdf",
    )


@api_bp.route("/data", methods=["DELETE"])
def delete_all_data():
    """Delete all analysis data.

    This is a destructive operation — all jobs, results, and exports are removed.
    """
    from signalstream.db.repositories import delete_all_data as do_delete

    do_delete()
    return jsonify({"deleted": True})
