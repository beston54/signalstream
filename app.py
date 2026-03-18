#!/usr/bin/env python3
"""
Flask Web GUI for Sentiment Analysis Pipeline

Provides a browser-based interface for:
  - Entering search topics / key phrases
  - Running the full collection -> analysis -> report pipeline
  - Tracking job progress in real time
  - Downloading completed PDF reports
  - Viewing history of past analysis runs
"""

import copy
import io
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
    Response,
)
import hmac as _hmac
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

try:
    from cryptography.fernet import Fernet
    _fernet: Fernet | None = None
    _FERNET_KEY = os.environ.get("SIGNALSTREAM_EMAIL_KEY", "").strip()
    if not _FERNET_KEY:
        # Auto-generate and persist a key if not set (same pattern as .hash_salt)
        _email_key_path = Path(__file__).resolve().parent / ".email_key"
        if _email_key_path.exists():
            _FERNET_KEY = _email_key_path.read_text().strip()
        else:
            _FERNET_KEY = Fernet.generate_key().decode()
            _email_key_path.write_text(_FERNET_KEY)
            logging.getLogger("webapp").info("Generated email encryption key at %s", _email_key_path)
    if _FERNET_KEY:
        _fernet = Fernet(_FERNET_KEY.encode() if isinstance(_FERNET_KEY, str) else _FERNET_KEY)
except ImportError:
    _fernet = None
    _FERNET_KEY = ""

# ---------------------------------------------------------------------------
# Path setup – make sure the scripts package is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from collector import load_config, collect_all_posts, save_raw_posts, deduplicate_posts, filter_irrelevant_posts
from x_collector import collect_all_x_posts
from analyzer import analyze_all_posts, save_analyzed_posts, load_posts_json
from llm_client import LLMClient, reset_provider_lock
from thematic_analyzer import analyze_all_themes, calculate_overall_statistics, save_thematic_analysis
from report_generator import create_report
from db import (
    init_db, save_job as db_save_job, get_job as db_get_job,
    get_all_jobs as db_get_all_jobs, delete_job as db_delete_job,
    save_job_statistics, get_trend_data, migrate_job_history,
)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
logger = logging.getLogger("webapp")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates" / "web"),
    static_folder=str(PROJECT_ROOT / "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    import secrets
    app.secret_key = secrets.token_hex(32)
    logger.warning(
        "FLASK_SECRET_KEY not set — using a random key. "
        "Sessions will not survive restarts. Set FLASK_SECRET_KEY in your environment."
    )

# CSRF protection
csrf = CSRFProtect(app)
# Only exempt the read-only polling endpoint (GET, no state mutation)
csrf.exempt("api_status")
csrf.exempt("api_trends")
csrf.exempt("api_compare_status")

# Rate limiting (Item 11) — prevents API credit abuse
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)

# ---------------------------------------------------------------------------
# Basic authentication (H9) — protects against unauthorized access
# Set SIGNALSTREAM_AUTH_TOKEN env var to enable. When unset, auth is disabled
# (localhost-only development mode).
# ---------------------------------------------------------------------------
_AUTH_TOKEN = os.environ.get("SIGNALSTREAM_AUTH_TOKEN", "").strip()


if _AUTH_TOKEN:
    logger.info("Authentication enabled — SIGNALSTREAM_AUTH_TOKEN is set.")
else:
    logger.warning(
        "No SIGNALSTREAM_AUTH_TOKEN set — web UI is unauthenticated. "
        "Set this env var before deploying beyond localhost."
    )

# ---------------------------------------------------------------------------
# In-memory job store  (dict keyed by job_id)
# ---------------------------------------------------------------------------
MAX_JOBS = 50
jobs: Dict[str, Dict[str, Any]] = {}

# Lock for thread-safe job dict mutation
_jobs_lock = threading.Lock()
# Lock for thread-safe email file writes
_emails_lock = threading.Lock()
# Thread pool for pipeline jobs (prevents orphaned daemon threads)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")

# In-memory store for compare-and-analyze jobs (keyed by compare_id)
_compare_jobs: Dict[str, Dict[str, Any]] = {}
_compare_lock = threading.Lock()


def _purge_old_emails() -> int:
    """Delete email entries older than data_retention_days (GDPR compliance)."""
    emails_path = PROJECT_ROOT / "data" / "emails.json"
    if not emails_path.exists():
        return 0
    try:
        config = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception:
        config = {}
    retention_days = int(config.get("output", {}).get("data_retention_days", 30))
    cutoff = datetime.now() - timedelta(days=retention_days)

    purged = 0
    with _emails_lock:
        try:
            with open(emails_path, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
        except Exception:
            return 0
        original_count = len(entries)
        entries = [
            e for e in entries
            if datetime.fromisoformat(e.get("submitted_at", datetime.now().isoformat())) > cutoff
        ]
        purged = original_count - len(entries)
        if purged > 0:
            with open(emails_path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2)
            logger.info("Purged %d email entries older than %d days", purged, retention_days)
    return purged


def _is_email_gate_enabled() -> bool:
    """Check config for email_gate_enabled. Defaults to False (off)."""
    try:
        config = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception:
        return False
    # Check under 'output' section first, then top-level
    output_cfg = config.get("output", {})
    if isinstance(output_cfg, dict) and "email_gate_enabled" in output_cfg:
        return bool(output_cfg["email_gate_enabled"])
    return bool(config.get("email_gate_enabled", False))


def _evict_old_jobs() -> None:
    """Remove oldest completed/error jobs if the store exceeds MAX_JOBS.

    Must be called while holding _jobs_lock.
    """
    if len(jobs) <= MAX_JOBS:
        return
    # Identify completed or errored jobs eligible for eviction
    evictable = [
        (jid, j)
        for jid, j in jobs.items()
        if j.get("status") in ("complete", "error", "cancelled")
    ]
    # Sort by created_at / started_at ascending (oldest first)
    evictable.sort(key=lambda pair: pair[1].get("started_at", ""))
    # Remove oldest until we're at capacity (or run out of evictable jobs)
    while len(jobs) > MAX_JOBS and evictable:
        oldest_id, _ = evictable.pop(0)
        del jobs[oldest_id]


def _load_history() -> None:
    """Load persisted job history from disk on startup."""
    history_path = PROJECT_ROOT / "data" / "job_history.json"
    if not history_path.exists():
        return
    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        with _jobs_lock:
            for job in saved:
                if job.get("id") and job["id"] not in jobs:
                    jobs[job["id"]] = job
        logger.info("Loaded %d jobs from history", len(saved))
    except Exception as exc:
        logger.warning("Could not load job history: %s", exc)


def _persist_history() -> None:
    """Write completed jobs to disk so they survive restarts."""
    history_path = PROJECT_ROOT / "data" / "job_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with _jobs_lock:
        snapshot = list(jobs.values())
    try:
        with open(history_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, default=str)
    except Exception as exc:
        logger.warning("Could not persist job history: %s", exc)


# ---------------------------------------------------------------------------
# Pipeline runner (executes in a background thread)
# ---------------------------------------------------------------------------

def _update_job(job_id: str, **kwargs: Any) -> None:
    with _jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def _is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled."""
    with _jobs_lock:
        job = jobs.get(job_id)
    return job is not None and job.get("status") == "cancelled"


def _run_pipeline(job_id: str, config: dict, phrases: list, time_range: str) -> None:
    """Execute the full pipeline for *job_id* with the given config overrides."""
    # Deep copy so concurrent jobs don't share mutable config state
    config = copy.deepcopy(config)
    # Create a fresh LLMClient per pipeline run to avoid shared mutable state
    _llm_client = LLMClient()
    _llm_client.reset_provider_lock()
    try:
        # ---- Inject user overrides into config ----
        if phrases:
            config.setdefault("search", {})["key_phrases"] = phrases
        if time_range:
            config.setdefault("search", {})["time_range"] = time_range

        total_phases = 4
        current_phase = 0

        # ---- Phase 1: Collection ----
        if _is_cancelled(job_id):
            return
        current_phase += 1
        _update_job(
            job_id,
            status="collecting",
            phase=f"Phase {current_phase}/{total_phases}: Collecting posts",
            progress_pct=5,
            message=f"Searching for: {', '.join(phrases[:3])}...",
        )

        enabled_sources = config.get("sources", {})
        combined_posts = []

        if enabled_sources.get("reddit", True):
            _update_job(job_id, message=f"Discovering subreddits for {len(phrases)} phrases...")
            reddit_posts = collect_all_posts(config, dry_run=False)
            combined_posts.extend(reddit_posts)
            _update_job(job_id, progress_pct=15, message=f"Found {len(reddit_posts)} Reddit posts...")

        if enabled_sources.get("x", False):
            api_key = os.getenv("GETX_API_KEY")
            bearer = (
                os.getenv("X_API_BEARER_TOKEN")
                or os.getenv("TWITTER_BEARER_TOKEN")
                or api_key
            )
            if bearer:
                _update_job(job_id, message="Collecting posts from X...")
                try:
                    x_posts = collect_all_x_posts(
                        config=config,
                        bearer_token=bearer,
                        api_key_header=api_key or None,
                    )
                    combined_posts.extend(x_posts)
                except Exception as x_exc:
                    logger.warning("X collection failed (continuing with other sources): %s", x_exc)

        if not combined_posts:
            _update_job(job_id, status="error", message="No posts were collected. Try different search phrases.")
            _persist_history()
            with _jobs_lock:
                _job_snapshot = dict(jobs.get(job_id, {}))
            if _job_snapshot:
                db_save_job(_job_snapshot)
            return

        combined_posts = deduplicate_posts(combined_posts)
        # Relevance filter: drop posts where search phrase matched only incidentally
        combined_posts = filter_irrelevant_posts(combined_posts, phrases)
        if not combined_posts:
            _update_job(job_id, status="error", message="No relevant posts found after filtering. Try broader search phrases.")
            _persist_history()
            with _jobs_lock:
                _job_snapshot = dict(jobs.get(job_id, {}))
            if _job_snapshot:
                db_save_job(_job_snapshot)
            return
        posts_path = save_raw_posts(combined_posts, str(PROJECT_ROOT / "data" / "raw"))

        _update_job(
            job_id,
            progress_pct=25,
            message=f"Collected {len(combined_posts)} posts from {len(set(p.get('subreddit','') for p in combined_posts))} communities.",
        )

        # ---- Phase 2: Sentiment Analysis ----
        if _is_cancelled(job_id):
            return
        current_phase += 1
        _update_job(
            job_id,
            status="analyzing",
            phase=f"Phase {current_phase}/{total_phases}: Analyzing sentiment",
            progress_pct=30,
            message="Running sentiment analysis on collected posts...",
        )

        posts = load_posts_json(posts_path)
        total_posts = len(posts)

        def _analysis_progress(current: int, total: int) -> None:
            pct = 30 + int((current / max(total, 1)) * 30)
            title_preview = ""
            if current <= len(posts):
                title_preview = (posts[current - 1].get("title") or "")[:60]
            msg = f"Analyzing post {current}/{total}"
            if title_preview:
                msg += f": {title_preview}..."
            _update_job(
                job_id,
                progress_pct=min(pct, 60),
                message=msg,
            )

        analyzed = analyze_all_posts(posts, config, progress_callback=_analysis_progress, llm_client=_llm_client)
        analyzed_path = save_analyzed_posts(analyzed, str(PROJECT_ROOT / "data" / "analyzed"))

        _update_job(
            job_id,
            progress_pct=60,
            message=f"Analyzed {len(analyzed)} posts.",
        )

        # ---- Phase 3: Thematic Analysis ----
        if _is_cancelled(job_id):
            return
        current_phase += 1
        _update_job(
            job_id,
            status="theming",
            phase=f"Phase {current_phase}/{total_phases}: Identifying themes",
            progress_pct=65,
            message=f"Extracting themes across {len(phrases)} phrases...",
        )

        with open(analyzed_path, "r", encoding="utf-8") as fh:
            analyzed_data = json.load(fh)

        themes = analyze_all_themes(analyzed_data, config, llm_client=_llm_client)
        statistics = calculate_overall_statistics(analyzed_data, themes)
        themes_path = save_thematic_analysis(themes, statistics, str(PROJECT_ROOT / "data" / "analyzed"))

        _update_job(
            job_id,
            progress_pct=80,
            message="Themes identified.",
        )

        # ---- Phase 4: Report Generation ----
        if _is_cancelled(job_id):
            return
        current_phase += 1
        _update_job(
            job_id,
            status="generating",
            phase=f"Phase {current_phase}/{total_phases}: Generating PDF report",
            progress_pct=85,
            message="Generating charts and building PDF layout...",
        )

        pdf_path = create_report(
            analyzed_posts_path=analyzed_path,
            themes_path=themes_path,
            config=config,
            output_dir=str(PROJECT_ROOT / "reports"),
            template_dir=str(PROJECT_ROOT / "templates"),
        )

        # Build preview data for status page
        emotion_dist = statistics.get("emotion_distribution", {})
        top_emotions = sorted(
            [(e, c) for e, c in emotion_dist.items() if e not in ("unknown", "error")],
            key=lambda x: -x[1]
        )[:5]
        dominant_emotion = top_emotions[0][0] if top_emotions else "neutral"
        top_theme_names = []
        for _phrase, tdata in list(themes.items())[:3]:
            for t in tdata.get("major_themes", [])[:1]:
                top_theme_names.append(t.get("theme", ""))
        communities_scanned = len(statistics.get("community_breakdown", statistics.get("subreddit_breakdown", {})))

        # Emotion percentages for preview bars
        total_for_pct = max(len(combined_posts), 1)
        emotion_pcts = {e: round(c / total_for_pct * 100, 1) for e, c in top_emotions}

        _update_job(
            job_id,
            status="complete",
            phase="Complete",
            progress_pct=100,
            message="Report ready for download!",
            pdf_path=pdf_path,
            analyzed_path=analyzed_path,
            themes_path=themes_path,
            completed_at=datetime.now().isoformat(),
            post_count=len(combined_posts),
            preview={
                "total_posts": len(combined_posts),
                "communities_scanned": communities_scanned,
                "dominant_emotion": dominant_emotion,
                "top_emotions": [{"emotion": e, "count": c, "pct": emotion_pcts.get(e, 0)} for e, c in top_emotions],
                "top_themes": [t for t in top_theme_names if t][:3],
            },
        )
        _persist_history()

        # Persist to SQLite
        with _jobs_lock:
            _job_snapshot = dict(jobs.get(job_id, {}))
        if _job_snapshot:
            db_save_job(_job_snapshot)
        save_job_statistics(job_id, statistics)

        # Send email notification if configured for this job
        notify_email = ""
        with _jobs_lock:
            notify_email = jobs.get(job_id, {}).get("notify_email", "")
        if notify_email:
            try:
                from scripts.notifier import send_completion_email
                send_completion_email(
                    to_email=notify_email,
                    job=_job_snapshot,
                    pdf_path=pdf_path,
                    config=config,
                )
            except Exception as mail_exc:
                logger.warning("Email notification failed for job %s: %s", job_id, mail_exc)

    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job_id)
        _update_job(
            job_id,
            status="error",
            message="An internal error occurred. Please check the server logs for details.",
            completed_at=datetime.now().isoformat(),
        )
        _persist_history()

        # Persist error state to SQLite
        with _jobs_lock:
            _job_snapshot = dict(jobs.get(job_id, {}))
        if _job_snapshot:
            db_save_job(_job_snapshot)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.before_request
def _enforce_auth():
    """Enforce authentication on all routes when SIGNALSTREAM_AUTH_TOKEN is set."""
    if not _AUTH_TOKEN:
        return None
    # Allow static assets without auth
    if request.path.startswith("/static/"):
        return None
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("signalstream_token", "").strip()
    if not token or not _hmac.compare_digest(token, _AUTH_TOKEN):
        return Response(
            "Authentication required. Set the SIGNALSTREAM_AUTH_TOKEN environment variable "
            "and provide it via Authorization: Bearer <token> header.",
            401,
            {"WWW-Authenticate": 'Bearer realm="Signalstream"'},
        )
    return None


@app.route("/")
def index():
    """Landing page with the analysis form."""
    # Load config defaults for advanced settings
    try:
        cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception:
        cfg = {}
    filters = cfg.get("filters", {})
    search = cfg.get("search", {})
    defaults = {
        "languages": ", ".join(filters.get("languages", [])),
        "regions": ", ".join(filters.get("regions", [])),
        "max_posts_per_phrase": search.get("max_posts_per_phrase", 100),
    }
    return render_template("index.html", defaults=defaults)


@app.route("/analyze", methods=["POST"])
@limiter.limit("3 per 10 minutes")
def analyze():
    """Start a new analysis job."""
    topic = request.form.get("topic", "").strip()
    time_range = request.form.get("time_range", "week").strip()

    if not topic:
        return redirect(url_for("index"))

    # Build phrase list from comma-separated input
    phrases = [p.strip() for p in topic.split(",") if p.strip()]

    # Advanced settings from the form
    lang_filter = request.form.get("languages", "").strip()
    region_filter = request.form.get("regions", "").strip()
    max_posts_raw = request.form.get("max_posts_per_phrase", "").strip()

    # Load config
    try:
        config = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception as exc:
        logger.exception("Config load error")
        return render_template("index.html", error="Configuration error. Please check config.yaml and server logs.")

    # Apply advanced settings to config
    if lang_filter:
        langs = [l.strip() for l in lang_filter.split(",") if l.strip()]
        config.setdefault("filters", {})["languages"] = langs
    if region_filter:
        regions = [r.strip() for r in region_filter.split(",") if r.strip()]
        config.setdefault("filters", {})["regions"] = regions
    if max_posts_raw:
        try:
            max_posts = int(max_posts_raw)
            if max_posts > 0:
                config.setdefault("search", {})["max_posts_per_phrase"] = max_posts
        except ValueError:
            pass

    # Create job
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    with _jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "topic": topic,
            "phrases": phrases,
            "time_range": time_range,
            "status": "queued",
            "phase": "Queued",
            "progress_pct": 0,
            "message": "Job queued, starting shortly...",
            "pdf_path": None,
            "post_count": 0,
            "started_at": now,
            "completed_at": None,
        }
        _evict_old_jobs()

    # Persist new job to SQLite
    db_save_job({
        "id": job_id, "topic": topic, "time_range": time_range,
        "status": "queued", "phase": "Queued", "progress_pct": 0,
        "message": "Job queued, starting shortly...",
        "created_at": now,
    })

    # Launch in thread pool (non-daemon, so errors are tracked properly)
    _executor.submit(_run_pipeline, job_id, config, phrases, time_range)

    return redirect(url_for("status", job_id=job_id))


@app.route("/status/<job_id>")
def status(job_id: str):
    """Job status page (renders HTML, polled by JS)."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return redirect(url_for("index"))
    return render_template("status.html", job=job)


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    """JSON endpoint polled by the status page."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Include email_gate_enabled so the frontend can skip the gate when disabled
    payload = dict(job)
    payload["email_gate_enabled"] = _is_email_gate_enabled()
    return jsonify(payload)


@app.route('/api/trends/<job_id>')
def api_trends(job_id):
    """Get trend data for a job's topic."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    topic = job.get('topic', '')
    if not topic:
        return jsonify({"trends": [], "deltas": {}})

    try:
        trend_data = get_trend_data(topic, limit=10)

        # Format for the frontend
        trends = []
        for entry in reversed(trend_data):  # oldest first for charting
            total = max(entry.get('total_posts', 1), 1)
            trends.append({
                "date": entry.get('created_at', '')[:10],
                "total_posts": entry.get('total_posts', 0),
                "positive_pct": round(entry.get('sentiment_positive', 0) / total * 100, 1),
                "negative_pct": round(entry.get('sentiment_negative', 0) / total * 100, 1),
                "neutral_pct": round(entry.get('sentiment_neutral', 0) / total * 100, 1),
                "dominant_emotion": entry.get('dominant_emotion', ''),
                "dominant_emotion_pct": entry.get('dominant_emotion_pct', 0),
            })

        # Compute deltas if we have at least 2 data points
        deltas = {}
        if len(trends) >= 2:
            current = trends[-1]
            previous = trends[-2]
            deltas = {
                "positive_delta": round(current["positive_pct"] - previous["positive_pct"], 1),
                "negative_delta": round(current["negative_pct"] - previous["negative_pct"], 1),
                "neutral_delta": round(current["neutral_pct"] - previous["neutral_pct"], 1),
                "posts_delta": current["total_posts"] - previous["total_posts"],
            }

        return jsonify({"trends": trends, "deltas": deltas})
    except Exception as e:
        logger.error(f"Trend data failed: {e}")
        return jsonify({"trends": [], "deltas": {}})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    """Cancel a running job."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    terminal = ("complete", "error", "cancelled")
    if job.get("status") in terminal:
        return jsonify({"error": f"Job already {job['status']}"}), 400
    _update_job(
        job_id,
        status="cancelled",
        phase="Cancelled",
        message="Job was cancelled by the user.",
        completed_at=datetime.now().isoformat(),
    )
    _persist_history()
    # Persist cancellation to SQLite
    with _jobs_lock:
        _job_snapshot = dict(jobs.get(job_id, {}))
    if _job_snapshot:
        db_save_job(_job_snapshot)
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id: str):
    """Delete a job from the store and remove its PDF if present."""
    with _jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Remove associated PDF file
    pdf_path = job.get("pdf_path")
    if pdf_path:
        try:
            p = Path(pdf_path)
            if p.exists():
                p.unlink()
        except Exception as exc:
            logger.warning("Could not delete PDF for job %s: %s", job_id, exc)
    _persist_history()
    # Remove from SQLite as well
    db_delete_job(job_id)
    return jsonify({"ok": True})


@app.route("/api/submit-email/<job_id>", methods=["POST"])
def submit_email(job_id: str):
    """Accept email before allowing download."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    consent = bool(data.get("consent", False))

    if not email or "@" not in email:
        return jsonify({"error": "Valid email required"}), 400

    if not consent:
        return jsonify({"error": "Consent is required"}), 400

    # Store email (thread-safe via lock)
    emails_path = PROJECT_ROOT / "data" / "emails.json"
    emails_path.parent.mkdir(parents=True, exist_ok=True)
    with _emails_lock:
        email_entries = []
        if emails_path.exists():
            try:
                with open(emails_path, "r", encoding="utf-8") as fh:
                    email_entries = json.load(fh)
            except Exception:
                email_entries = []
        stored_email = email
        if _fernet:
            stored_email = _fernet.encrypt(email.encode("utf-8")).decode("utf-8")
        email_entries.append({
            "email": stored_email,
            "encrypted": bool(_fernet),
            "job_id": job_id,
            "topic": job.get("topic", ""),
            "submitted_at": datetime.now().isoformat(),
            "consent_given": consent,
        })
        with open(emails_path, "w", encoding="utf-8") as fh:
            json.dump(email_entries, fh, indent=2)

    # Mark job as email submitted
    _update_job(job_id, email_submitted=True)
    _persist_history()
    # Persist email submission flag to SQLite
    with _jobs_lock:
        _job_snapshot = dict(jobs.get(job_id, {}))
    if _job_snapshot:
        db_save_job(_job_snapshot)

    return jsonify({"ok": True})


@app.route("/download/<job_id>")
def download(job_id: str):
    """Download the generated PDF (requires email submission if gate enabled)."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.get("pdf_path"):
        return redirect(url_for("index"))

    if _is_email_gate_enabled() and not job.get("email_submitted"):
        return redirect(url_for("status", job_id=job_id))

    pdf = Path(job["pdf_path"]).resolve()
    reports_dir = (PROJECT_ROOT / "reports").resolve()
    if not pdf.is_relative_to(reports_dir):
        abort(403, description="Invalid file path.")

    if not pdf.exists():
        return "Report file not found", 404

    return send_file(str(pdf), as_attachment=True, download_name=pdf.name)


@app.route("/export/<job_id>")
def export_data(job_id):
    """Download full data export as ZIP (CSV + JSON + PDF)."""
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    if job.get("status") != "complete":
        abort(400, description="Job not complete")

    try:
        from scripts.exporter import create_export_zip

        analyzed_path = job.get("analyzed_path", "")
        themes_path = job.get("themes_path", "")
        pdf_path = job.get("pdf_path", "")

        if not analyzed_path or not themes_path:
            abort(404, description="Export data not available")

        zip_bytes = create_export_zip(analyzed_path, themes_path, pdf_path)

        return send_file(
            io.BytesIO(zip_bytes),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"signalstream_export_{job_id[:8]}.zip",
        )
    except Exception as e:
        logger.error(f"Export failed for job {job_id}: {e}")
        abort(500, description="Export generation failed")


@app.route("/about")
def about():
    """About page for Eston McKeague."""
    return render_template("about.html")


@app.route("/history")
def history():
    """List past analysis runs."""
    with _jobs_lock:
        all_jobs = sorted(
            jobs.values(),
            key=lambda j: j.get("started_at", ""),
            reverse=True,
        )
    return render_template("history.html", jobs=all_jobs)


@app.route("/profiles", methods=["GET"])
def profiles_page():
    """Show saved profiles."""
    from scripts.db import get_all_profiles
    profiles = get_all_profiles()
    return render_template("profiles.html", profiles=profiles)


@app.route("/profiles", methods=["POST"])
def create_profile():
    """Create a new profile."""
    from scripts.db import save_profile

    branding = {}
    if request.form.get('brand_company'):
        branding['company_name'] = request.form['brand_company']
    if request.form.get('brand_tagline'):
        branding['tagline'] = request.form['brand_tagline']
    if request.form.get('brand_primary'):
        branding['primary_color'] = request.form['brand_primary']
    if request.form.get('brand_footer'):
        branding['footer_text'] = request.form['brand_footer']

    profile = {
        'name': request.form.get('name', '').strip(),
        'topic': request.form.get('topic', '').strip(),
        'time_range': request.form.get('time_range', 'month'),
        'languages': request.form.get('languages', '').strip(),
        'regions': request.form.get('regions', '').strip(),
        'max_posts': int(request.form.get('max_posts', 100)),
        'schedule_cron': request.form.get('schedule_cron', '').strip(),
        'notify_email': request.form.get('notify_email', '').strip(),
        'branding': branding,
    }

    try:
        save_profile(profile)
    except Exception as e:
        logger.error(f"Failed to save profile: {e}")

    return redirect(url_for('profiles_page'))


@app.route("/profiles/<int:profile_id>/run", methods=["POST"])
def run_profile(profile_id):
    """Run an analysis using a saved profile's settings."""
    from scripts.db import get_profile

    profile = get_profile(profile_id)
    if not profile:
        abort(404)

    # Parse phrases from the profile topic
    phrases = [p.strip() for p in profile['topic'].split(',') if p.strip()]
    time_range = profile.get('time_range', 'week')

    # Load and customize config
    try:
        config = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception:
        config = {}

    # Apply profile overrides
    lang_filter = profile.get('languages', '').strip()
    region_filter = profile.get('regions', '').strip()
    max_posts = profile.get('max_posts', 100)

    if lang_filter:
        langs = [l.strip() for l in lang_filter.split(',') if l.strip()]
        config.setdefault('filters', {})['languages'] = langs
    if region_filter:
        regions = [r.strip() for r in region_filter.split(',') if r.strip()]
        config.setdefault('filters', {})['regions'] = regions
    if max_posts:
        config.setdefault('search', {})['max_posts_per_phrase'] = int(max_posts)

    # Apply white-label branding from profile
    branding = profile.get('branding', {})
    if branding:
        cfg_branding = config.setdefault('branding', {})
        if branding.get('company_name'):
            cfg_branding['company_name'] = branding['company_name']
        if branding.get('tagline'):
            cfg_branding['tagline'] = branding['tagline']
        if branding.get('primary_color'):
            config.setdefault('design_system', {}).setdefault('colors', {})['primary'] = branding['primary_color']
        if branding.get('footer_text'):
            cfg_branding['footer_text'] = branding['footer_text']

    # Create job (same pattern as the /analyze route)
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    with _jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "topic": profile['topic'],
            "phrases": phrases,
            "time_range": time_range,
            "status": "queued",
            "phase": "Queued",
            "progress_pct": 0,
            "message": f"Queued from profile: {profile['name']}",
            "pdf_path": None,
            "post_count": 0,
            "started_at": now,
            "completed_at": None,
            "notify_email": profile.get('notify_email', ''),
            "profile_id": profile_id,
        }
        _evict_old_jobs()

    # Persist to SQLite
    db_save_job({
        "id": job_id, "topic": profile['topic'], "time_range": time_range,
        "status": "queued", "phase": "Queued", "progress_pct": 0,
        "message": f"Queued from profile: {profile['name']}",
        "created_at": now,
    })

    # Launch in thread pool
    _executor.submit(_run_pipeline, job_id, config, phrases, time_range)

    return redirect(url_for('status', job_id=job_id))


@app.route("/profiles/<int:profile_id>/delete", methods=["POST"])
def delete_profile_route(profile_id):
    """Delete a saved profile."""
    from scripts.db import delete_profile
    delete_profile(profile_id)
    return redirect(url_for('profiles_page'))


@app.route("/compare", methods=["GET"])
def compare_page():
    """Show comparison form."""
    return render_template("compare.html", comparison=None)


@app.route("/compare", methods=["POST"])
def compare_submit():
    """Run comparison between two topics using existing completed jobs or the database."""
    topic_a = request.form.get("topic_a", "").strip()
    topic_b = request.form.get("topic_b", "").strip()
    time_range = request.form.get("time_range", "month")

    if not topic_a or not topic_b:
        return render_template("compare.html", comparison=None)

    comparison = {"a": None, "b": None, "delta": ""}

    try:
        for side, topic in [("a", topic_a), ("b", topic_b)]:
            # Look for existing completed analysis
            trend = get_trend_data(topic, limit=1)

            if trend:
                entry = trend[0]
                total = max(entry.get("total_posts", 1), 1)
                themes = []
                try:
                    themes_json = entry.get("themes_json", "[]")
                    themes_list = json.loads(themes_json) if isinstance(themes_json, str) else themes_json
                    themes = [t.get("theme", "") for t in themes_list[:3]]
                except Exception:
                    pass

                comparison[side] = {
                    "topic": topic,
                    "job_id": entry.get("id", ""),
                    "post_count": entry.get("total_posts", 0),
                    "community_count": 0,
                    "positive_pct": round(entry.get("sentiment_positive", 0) / total * 100, 1),
                    "negative_pct": round(entry.get("sentiment_negative", 0) / total * 100, 1),
                    "neutral_pct": round(entry.get("sentiment_neutral", 0) / total * 100, 1),
                    "dominant_emotion": entry.get("dominant_emotion", "neutral"),
                    "dominant_emotion_pct": entry.get("dominant_emotion_pct", 0),
                    "themes": themes,
                }
            else:
                comparison[side] = {
                    "topic": topic,
                    "job_id": "",
                    "post_count": 0,
                    "community_count": 0,
                    "positive_pct": 0,
                    "negative_pct": 0,
                    "neutral_pct": 0,
                    "dominant_emotion": "unknown",
                    "dominant_emotion_pct": 0,
                    "themes": [],
                    "no_data": True,
                }

        # Generate comparison delta narrative
        if comparison["a"] and comparison["b"] and not comparison["a"].get("no_data") and not comparison["b"].get("no_data"):
            a, b = comparison["a"], comparison["b"]
            parts = []
            pos_diff = a["positive_pct"] - b["positive_pct"]
            neg_diff = a["negative_pct"] - b["negative_pct"]
            if abs(pos_diff) > 5:
                more_pos = topic_a if pos_diff > 0 else topic_b
                parts.append(f'"{more_pos}" has {abs(pos_diff):.1f}% more positive sentiment')
            if abs(neg_diff) > 5:
                more_neg = topic_a if neg_diff > 0 else topic_b
                parts.append(f'"{more_neg}" has {abs(neg_diff):.1f}% more negative sentiment')
            if a["dominant_emotion"] != b["dominant_emotion"]:
                parts.append(f'"{topic_a}" is predominantly {a["dominant_emotion"]}, while "{topic_b}" is {b["dominant_emotion"]}')
            comparison["delta"] = ". ".join(parts) + "." if parts else "Both topics show similar sentiment patterns."
        elif comparison["a"].get("no_data") or comparison["b"].get("no_data"):
            missing = []
            if comparison["a"].get("no_data"):
                missing.append(topic_a)
            if comparison["b"].get("no_data"):
                missing.append(topic_b)
            comparison["delta"] = f"No prior analysis found for: {', '.join(missing)}."
            comparison["can_analyze"] = True

    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        comparison["delta"] = "Comparison temporarily unavailable."

    return render_template(
        "compare.html",
        comparison=comparison,
        topic_a=topic_a,
        topic_b=topic_b,
        time_range=time_range,
    )


# ---------------------------------------------------------------------------
# Compare & Analyze — live dual-analysis runner
# ---------------------------------------------------------------------------

@app.route("/compare/analyze", methods=["POST"])
@limiter.limit("3 per 10 minutes")
def compare_analyze():
    """Launch fresh analysis for one or both comparison topics."""
    topic_a = request.form.get("topic_a", "").strip()
    topic_b = request.form.get("topic_b", "").strip()
    time_range = request.form.get("time_range", "month").strip()

    if not topic_a or not topic_b:
        return redirect(url_for("compare_page"))

    try:
        config = load_config(str(PROJECT_ROOT / "config.yaml"))
    except Exception:
        logger.exception("Config load error")
        return redirect(url_for("compare_page"))

    compare_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    entry = {"id": compare_id, "time_range": time_range, "created_at": now}

    for side, topic in [("a", topic_a), ("b", topic_b)]:
        # Check if this topic already has data
        trend = get_trend_data(topic, limit=1)
        if trend:
            entry[f"job_{side}"] = {
                "id": None,
                "topic": topic,
                "status": "existing",
                "progress_pct": 100,
            }
            continue

        # Create a real analysis job (same pattern as /analyze)
        phrases = [p.strip() for p in topic.split(",") if p.strip()]
        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "topic": topic,
                "phrases": phrases,
                "time_range": time_range,
                "status": "queued",
                "phase": "Queued",
                "progress_pct": 0,
                "message": "Job queued, starting shortly...",
                "pdf_path": None,
                "post_count": 0,
                "started_at": now,
                "completed_at": None,
            }
            _evict_old_jobs()

        db_save_job({
            "id": job_id, "topic": topic, "time_range": time_range,
            "status": "queued", "phase": "Queued", "progress_pct": 0,
            "message": "Job queued, starting shortly...",
            "created_at": now,
        })

        job_config = copy.deepcopy(config)
        _executor.submit(_run_pipeline, job_id, job_config, phrases, time_range)

        entry[f"job_{side}"] = {
            "id": job_id,
            "topic": topic,
            "status": "queued",
            "progress_pct": 0,
        }

    with _compare_lock:
        _compare_jobs[compare_id] = entry

    return redirect(url_for("compare_status_page", compare_id=compare_id))


@app.route("/compare/status/<compare_id>")
def compare_status_page(compare_id: str):
    """Render the dual-progress comparison status page."""
    with _compare_lock:
        cjob = _compare_jobs.get(compare_id)
    if not cjob:
        return redirect(url_for("compare_page"))
    return render_template("compare_status.html", compare_id=compare_id, cjob=cjob)


@app.route("/api/compare-status/<compare_id>")
def api_compare_status(compare_id: str):
    """JSON endpoint polled by the compare status page."""
    with _compare_lock:
        cjob = _compare_jobs.get(compare_id)
    if not cjob:
        return jsonify({"error": "Comparison not found"}), 404

    result = {
        "status": "running",
        "job_a": dict(cjob.get("job_a", {})),
        "job_b": dict(cjob.get("job_b", {})),
        "comparison": None,
    }

    # Enrich each side with live job status
    all_done = True
    any_error = False
    for side in ("job_a", "job_b"):
        info = cjob.get(side, {})
        job_id = info.get("id")
        if job_id is None:
            # Already had existing data
            result[side]["status"] = "existing"
            result[side]["progress_pct"] = 100
            continue
        with _jobs_lock:
            live = jobs.get(job_id)
        if live:
            result[side]["status"] = live.get("status", "queued")
            result[side]["progress_pct"] = live.get("progress_pct", 0)
            result[side]["phase"] = live.get("phase", "")
            result[side]["message"] = live.get("message", "")
        if result[side].get("status") not in ("complete", "existing"):
            all_done = False
        if result[side].get("status") == "error":
            any_error = True

    if any_error:
        result["status"] = "error"
    elif all_done:
        result["status"] = "complete"
        # Build comparison data using same logic as compare_submit
        comparison = {"a": None, "b": None, "delta": ""}
        for side_key, side_label in [("job_a", "a"), ("job_b", "b")]:
            topic = cjob[side_key]["topic"]
            trend = get_trend_data(topic, limit=1)
            if trend:
                entry = trend[0]
                total = max(entry.get("total_posts", 1), 1)
                themes = []
                try:
                    themes_json = entry.get("themes_json", "[]")
                    themes_list = json.loads(themes_json) if isinstance(themes_json, str) else themes_json
                    themes = [t.get("theme", "") for t in themes_list[:3]]
                except Exception:
                    pass
                comparison[side_label] = {
                    "topic": topic,
                    "job_id": entry.get("id", ""),
                    "post_count": entry.get("total_posts", 0),
                    "community_count": 0,
                    "positive_pct": round(entry.get("sentiment_positive", 0) / total * 100, 1),
                    "negative_pct": round(entry.get("sentiment_negative", 0) / total * 100, 1),
                    "neutral_pct": round(entry.get("sentiment_neutral", 0) / total * 100, 1),
                    "dominant_emotion": entry.get("dominant_emotion", "neutral"),
                    "dominant_emotion_pct": entry.get("dominant_emotion_pct", 0),
                    "themes": themes,
                }
            else:
                comparison[side_label] = {
                    "topic": topic,
                    "post_count": 0,
                    "positive_pct": 0,
                    "negative_pct": 0,
                    "neutral_pct": 0,
                    "dominant_emotion": "unknown",
                    "dominant_emotion_pct": 0,
                    "themes": [],
                }

        a, b = comparison["a"], comparison["b"]
        if a and b and a.get("post_count") and b.get("post_count"):
            parts = []
            pos_diff = a["positive_pct"] - b["positive_pct"]
            neg_diff = a["negative_pct"] - b["negative_pct"]
            topic_a_name = cjob["job_a"]["topic"]
            topic_b_name = cjob["job_b"]["topic"]
            if abs(pos_diff) > 5:
                more_pos = topic_a_name if pos_diff > 0 else topic_b_name
                parts.append(f'"{more_pos}" has {abs(pos_diff):.1f}% more positive sentiment')
            if abs(neg_diff) > 5:
                more_neg = topic_a_name if neg_diff > 0 else topic_b_name
                parts.append(f'"{more_neg}" has {abs(neg_diff):.1f}% more negative sentiment')
            if a["dominant_emotion"] != b["dominant_emotion"]:
                parts.append(f'"{topic_a_name}" is predominantly {a["dominant_emotion"]}, while "{topic_b_name}" is {b["dominant_emotion"]}')
            comparison["delta"] = ". ".join(parts) + "." if parts else "Both topics show similar sentiment patterns."
        result["comparison"] = comparison

    return jsonify(result)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_load_history()

# Initialize SQLite database and migrate legacy JSON history
init_db()
migrate_job_history(str(PROJECT_ROOT / "data" / "job_history.json"))

# GDPR: purge old emails and raw data on startup (Item 4/5)
_purge_old_emails()
try:
    from main import cleanup_old_data as _cli_cleanup
    _cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
    _retention = int(_cfg.get("output", {}).get("data_retention_days", 30))
    _cli_cleanup(str(PROJECT_ROOT / "data" / "raw"), _retention, logger)
    _cli_cleanup(str(PROJECT_ROOT / "data" / "analyzed"), _retention, logger)
except Exception as _exc:
    logger.warning("Startup data retention cleanup skipped: %s", _exc)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Signalstream Web UI")
    print(f"  http://localhost:{port}\n")
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)
