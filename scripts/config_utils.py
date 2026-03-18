"""
Configuration loading and normalization helpers.

Keeps CLI scripts resilient to user-provided YAML types (e.g. quoted numbers)
and supports running scripts from outside the project root.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_path(value: Any, base_dir: Path) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _coerce_float(value: Any, default: float, minimum: Optional[float] = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def _ensure_dict(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    value = {}
    parent[key] = value
    return value


def normalize_config(config: Optional[Dict[str, Any]], config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Normalize and coerce user configuration into predictable runtime types.

    Args:
        config: Parsed YAML root
        config_dir: Base directory for resolving relative config file paths
    """
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML mapping/object at the top level")

    normalized: Dict[str, Any] = copy.deepcopy(config)
    base_dir = Path(config_dir or PROJECT_ROOT).resolve()

    sources = _ensure_dict(normalized, "sources")
    sources["reddit"] = _coerce_bool(sources.get("reddit", True), True)
    sources["x"] = _coerce_bool(sources.get("x", False), False)

    collector = _ensure_dict(normalized, "collector")
    if "provider" in collector and collector["provider"] is not None:
        collector["provider"] = str(collector["provider"]).strip().lower()
    collector["public_json_requests_per_minute"] = _coerce_int(
        collector.get("public_json_requests_per_minute", 20), 20, minimum=1
    )
    collector["request_timeout_seconds"] = _coerce_int(
        collector.get("request_timeout_seconds", 20), 20, minimum=5
    )
    collector["max_retries"] = _coerce_int(collector.get("max_retries", 4), 4, minimum=0)
    collector["retry_backoff_seconds"] = _coerce_float(
        collector.get("retry_backoff_seconds", 2.0), 2.0, minimum=0.5
    )
    collector["fallback_to_praw_on_public_failure"] = _coerce_bool(
        collector.get("fallback_to_praw_on_public_failure", True), True
    )

    search = _ensure_dict(normalized, "search")
    if search.get("topic") is None:
        search["topic"] = ""
    else:
        search["topic"] = str(search.get("topic", "")).strip()
    search["auto_expand"] = _coerce_bool(search.get("auto_expand", False), False)
    search["expansion_count"] = _coerce_int(search.get("expansion_count", 8), 8, minimum=1)
    search["reddit_expansion_count"] = _coerce_int(
        search.get("reddit_expansion_count", search["expansion_count"]),
        search["expansion_count"],
        minimum=1,
    )
    search["x_expansion_count"] = _coerce_int(
        search.get("x_expansion_count", search["expansion_count"]),
        search["expansion_count"],
        minimum=1,
    )
    search["x_use_raw_queries"] = _coerce_bool(search.get("x_use_raw_queries", True), True)
    search["key_phrases"] = _coerce_str_list(search.get("key_phrases", []))
    search["max_posts_per_phrase"] = _coerce_int(search.get("max_posts_per_phrase", 100), 100, minimum=1)
    search["min_upvotes"] = _coerce_int(search.get("min_upvotes", 0), 0, minimum=0)
    search["comment_depth"] = _coerce_int(search.get("comment_depth", 1), 1, minimum=1)
    search["max_comments_per_post"] = _coerce_int(search.get("max_comments_per_post", 10), 10, minimum=0)

    analysis_cfg = _ensure_dict(normalized, "analysis")
    unit_value = str(analysis_cfg.get("unit", "thread") or "thread").strip().lower()
    analysis_cfg["unit"] = unit_value if unit_value in {"thread", "post"} else "thread"
    analysis_cfg["include_thread_context"] = _coerce_bool(
        analysis_cfg.get("include_thread_context", True), True
    )
    analysis_cfg["max_comments_in_prompt"] = _coerce_int(
        analysis_cfg.get("max_comments_in_prompt", 6), 6, minimum=0
    )
    analysis_cfg["max_replies_per_comment_in_prompt"] = _coerce_int(
        analysis_cfg.get("max_replies_per_comment_in_prompt", 2), 2, minimum=0
    )
    analysis_cfg["max_comment_chars"] = _coerce_int(
        analysis_cfg.get("max_comment_chars", 280), 280, minimum=40
    )
    analysis_cfg["max_thread_context_chars"] = _coerce_int(
        analysis_cfg.get("max_thread_context_chars", 1600), 1600, minimum=120
    )
    analysis_cfg["include_engagement_context"] = _coerce_bool(
        analysis_cfg.get("include_engagement_context", True), True
    )

    filters = _ensure_dict(normalized, "filters")
    filters["languages"] = _coerce_str_list(filters.get("languages", []))
    filters["regions"] = _coerce_str_list(filters.get("regions", []))

    ollama = _ensure_dict(normalized, "ollama")
    ollama["timeout"] = _coerce_int(ollama.get("timeout", 120), 120, minimum=1)
    ollama["max_retries"] = _coerce_int(ollama.get("max_retries", 3), 3, minimum=0)

    output = _ensure_dict(normalized, "output")
    output["anonymize_usernames"] = _coerce_bool(output.get("anonymize_usernames", True), True)
    output["data_retention_days"] = _coerce_int(output.get("data_retention_days", 30), 30, minimum=1)

    rate_limits = _ensure_dict(normalized, "rate_limits")
    rate_limits["reddit_requests_per_minute"] = _coerce_int(
        rate_limits.get("reddit_requests_per_minute", 60), 60, minimum=1
    )

    logging_cfg = _ensure_dict(normalized, "logging")
    if logging_cfg.get("level") is not None:
        logging_cfg["level"] = str(logging_cfg["level"]).upper()
    if logging_cfg.get("file"):
        logging_cfg["file"] = _resolve_path(logging_cfg["file"], base_dir)

    design = _ensure_dict(normalized, "design_system")
    typography = _ensure_dict(design, "typography")
    if typography.get("font_dir"):
        typography["font_dir"] = _resolve_path(typography["font_dir"], base_dir)

    report_cfg = _ensure_dict(design, "report")
    report_cfg["max_photos"] = _coerce_int(report_cfg.get("max_photos", 5), 5, minimum=0)
    report_cfg["chart_dpi"] = _coerce_int(report_cfg.get("chart_dpi", 150), 150, minimum=50)
    report_cfg["chart_width_inches"] = _coerce_float(
        report_cfg.get("chart_width_inches", 6.5), 6.5, minimum=1.0
    )
    report_cfg["chart_height_inches"] = _coerce_float(
        report_cfg.get("chart_height_inches", 3.5), 3.5, minimum=1.0
    )

    image_apis = _ensure_dict(normalized, "image_apis")
    for provider_key in ("unsplash", "pexels"):
        provider = _ensure_dict(image_apis, provider_key)
        provider["enabled"] = _coerce_bool(provider.get("enabled", True), True)

    cache_cfg = _ensure_dict(image_apis, "cache")
    if cache_cfg.get("directory"):
        cache_cfg["directory"] = _resolve_path(cache_cfg["directory"], base_dir)
    if cache_cfg.get("manifest_file"):
        cache_cfg["manifest_file"] = _resolve_path(cache_cfg["manifest_file"], base_dir)
    cache_cfg["max_cache_age_days"] = _coerce_int(cache_cfg.get("max_cache_age_days", 30), 30, minimum=1)

    return normalized


def load_config_file(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Load config YAML and normalize values.

    Relative paths are resolved from the current working directory first; if the
    file is not found there, the project root is used as a fallback.
    """
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        cwd_candidate = Path.cwd() / path
        project_candidate = PROJECT_ROOT / path
        if cwd_candidate.exists():
            path = cwd_candidate
        elif project_candidate.exists():
            path = project_candidate

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return normalize_config(raw, config_dir=path.parent)
