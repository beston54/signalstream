"""
Topic -> query expansion helpers for Reddit and X collection.

This module keeps expansion deterministic and local (no API calls) so users can
provide a single topic and automatically derive a broader set of relevant
search terms for collection.
"""

from __future__ import annotations

import argparse
import re
from typing import Any, Dict, Iterable, List, Optional

try:
    from .config_utils import load_config_file
except ImportError:
    from config_utils import load_config_file


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _normalized_topic(topic: str) -> str:
    return " ".join((topic or "").split()).strip()


def _topic_tokens(topic: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9\-]*", (topic or "").lower())


def _looks_like_europe_grid_topic(topic: str) -> bool:
    lowered = (topic or "").lower()
    europe = any(term in lowered for term in ("europe", "european", "eu", "entso-e"))
    grid = any(term in lowered for term in ("grid", "transmission", "interconnector", "hvdc"))
    power = any(term in lowered for term in ("electricity", "power", "energy"))
    growth = any(
        term in lowered
        for term in ("expand", "expansion", "upgrade", "build", "infrastructure", "permitting", "congestion")
    )
    return europe and grid and (power or growth)


def _extract_region_variants(topic: str) -> List[str]:
    lowered = (topic or "").lower()
    if any(term in lowered for term in ("europe", "european", "eu")):
        return ["Europe", "European", "EU"]
    return []


def _expand_reddit_grid_europe(topic: str) -> List[str]:
    topic = _normalized_topic(topic)
    region_terms = _extract_region_variants(topic) or ["Europe", "European"]
    primary_region = region_terms[0]

    queries = [
        topic,
        f"{primary_region} electricity grid expansion",
        f"{primary_region} power grid expansion",
        f"{primary_region} transmission grid expansion",
        f"{primary_region} grid permitting",
        f"{primary_region} grid congestion renewables",
        f"HVDC interconnector {primary_region}",
        f"{primary_region} power grid interconnection",
        f"{primary_region} transmission infrastructure",
        f"ENTSO-E grid expansion",
        f"{primary_region} electricity interconnector projects",
        f"{primary_region} transmission network upgrade",
    ]
    return _ordered_unique(queries)


def _expand_x_grid_europe(topic: str) -> List[str]:
    topic = _normalized_topic(topic)
    # Use `raw:` so x_collector sends platform-native boolean queries rather than quoted exact phrases.
    queries = [
        (
            'raw:(Europe OR European OR EU OR "ENTSO-E") '
            '("power grid" OR "electricity grid" OR "transmission grid" OR interconnector OR HVDC) '
            '(expand OR expansion OR upgrade OR permitting OR congestion OR infrastructure)'
        ),
        (
            'raw:(Europe OR European OR EU) '
            '(interconnector OR HVDC OR transmission) '
            '(grid OR electricity OR power)'
        ),
        (
            'raw:("ENTSO-E" OR TSO) '
            '(grid OR transmission OR interconnector OR HVDC) '
            '(Europe OR EU)'
        ),
        (
            'raw:(Europe OR European) '
            '("grid expansion" OR "transmission expansion" OR "grid permitting") '
            '(electricity OR power OR renewables)'
        ),
        f'raw:{topic}',
    ]
    return _ordered_unique(queries)


def _expand_generic_reddit(topic: str) -> List[str]:
    topic = _normalized_topic(topic)
    tokens = _topic_tokens(topic)
    compact = " ".join(tokens[:6]).strip()

    queries = [topic]
    if compact and compact.lower() != topic.lower():
        queries.append(compact)

    suffixes = [
        "policy",
        "infrastructure",
        "investment",
        "permitting",
        "public opinion",
        "regional strategy",
    ]
    for suffix in suffixes:
        queries.append(f"{topic} {suffix}")

    # If the topic contains a region marker, also try a reordered form.
    if tokens:
        region_markers = {"europe", "european", "eu", "germany", "france", "italy", "spain", "uk", "united", "kingdom"}
        region_tokens = [t for t in tokens if t in region_markers]
        non_region_tokens = [t for t in tokens if t not in region_markers]
        if region_tokens and non_region_tokens:
            queries.append(" ".join(region_tokens + non_region_tokens))
            queries.append(" ".join(non_region_tokens + region_tokens))

    return _ordered_unique(queries)


def _expand_generic_x(topic: str) -> List[str]:
    topic = _normalized_topic(topic)
    tokens = [t for t in _topic_tokens(topic) if len(t) > 1][:8]
    token_expr = " ".join(tokens) if tokens else topic

    queries = [
        f"raw:{topic}",
        f"raw:{token_expr}",
    ]

    # Build one broad boolean from first few tokens for recall.
    if len(tokens) >= 3:
        broad = f'raw:({" OR ".join(tokens[:4])})'
        queries.append(broad)

    return _ordered_unique(queries)


def expand_topic_queries(
    topic: str,
    platform: str = "reddit",
    max_queries: int = 8,
) -> List[str]:
    """
    Expand one topic into platform-appropriate search queries.

    Args:
        topic: Topic/phrase seed provided by the user
        platform: "reddit" or "x"
        max_queries: Max queries to return
    """
    topic = _normalized_topic(topic)
    if not topic:
        return []

    platform_norm = str(platform or "reddit").strip().lower()

    if _looks_like_europe_grid_topic(topic):
        if platform_norm == "x":
            expanded = _expand_x_grid_europe(topic)
        else:
            expanded = _expand_reddit_grid_europe(topic)
    else:
        if platform_norm == "x":
            expanded = _expand_generic_x(topic)
        else:
            expanded = _expand_generic_reddit(topic)

    return _ordered_unique(expanded)[: max(1, int(max_queries or 1))]


def resolve_search_phrases(config: Dict[str, Any], platform: str = "reddit") -> List[str]:
    """
    Resolve the phrase list for a collector from config.

    Supports existing `search.key_phrases`, plus topic-based expansion via:
    - `search.topic`
    - `search.auto_expand`
    - `search.expansion_count`
    - `search.reddit_expansion_count` / `search.x_expansion_count`
    - `search.x_use_raw_queries`
    """
    search = (config or {}).get("search", {}) or {}
    key_phrases_raw = search.get("key_phrases", []) or []
    key_phrases = _ordered_unique(key_phrases_raw if isinstance(key_phrases_raw, list) else [key_phrases_raw])

    topic = _normalized_topic(str(search.get("topic", "") or ""))
    auto_expand = _coerce_bool(search.get("auto_expand", False), False)

    expansion_count_default = _coerce_int(search.get("expansion_count", 8), 8, minimum=1)
    platform_norm = str(platform or "reddit").strip().lower()
    platform_count_key = "x_expansion_count" if platform_norm == "x" else "reddit_expansion_count"
    platform_max = _coerce_int(search.get(platform_count_key, expansion_count_default), expansion_count_default, minimum=1)

    # Backward-compatible behavior: use explicit key phrases if no topic expansion requested.
    if not auto_expand:
        if key_phrases:
            return key_phrases
        if topic:
            return [topic]
        return []

    x_use_raw_queries = _coerce_bool(search.get("x_use_raw_queries", True), True)

    seeds: List[str] = []
    if topic:
        seeds.append(topic)
    seeds.extend(key_phrases)
    seeds = _ordered_unique(seeds)
    if not seeds:
        return []

    resolved: List[str] = []

    # Keep explicitly configured phrases first, unless X raw-query mode is enabled and the
    # user is driving collection from a topic (we prioritize expanded raw queries there).
    if key_phrases and not (platform_norm == "x" and x_use_raw_queries and topic):
        resolved.extend(key_phrases)

    for seed in seeds:
        expanded = expand_topic_queries(seed, platform=platform_norm, max_queries=platform_max)
        if platform_norm == "x" and not x_use_raw_queries:
            expanded = [q[4:].strip() if q.lower().startswith("raw:") else q for q in expanded]
        resolved.extend(expanded)
        resolved = _ordered_unique(resolved)
        if len(resolved) >= platform_max:
            break

    return resolved[:platform_max]


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview auto-expanded search phrases for Reddit or X")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--platform", choices=["reddit", "x"], default="reddit", help="Target platform")
    parser.add_argument("--topic", help="Optional topic override (uses config if omitted)")
    parser.add_argument("--max", type=int, default=10, help="Max queries to print")
    args = parser.parse_args()

    config = load_config_file(args.config)
    if args.topic:
        config.setdefault("search", {})["topic"] = args.topic
        config.setdefault("search", {})["auto_expand"] = True
        config.setdefault("search", {})["expansion_count"] = max(1, args.max)
        if args.platform == "x":
            config.setdefault("search", {})["x_expansion_count"] = max(1, args.max)
        else:
            config.setdefault("search", {})["reddit_expansion_count"] = max(1, args.max)

    queries = resolve_search_phrases(config, platform=args.platform)[: max(1, args.max)]
    if not queries:
        print("No queries resolved. Set search.key_phrases or search.topic (+ search.auto_expand: true).")
        return

    print(f"Resolved {len(queries)} {args.platform} queries:")
    for i, query in enumerate(queries, 1):
        print(f"{i}. {query}")


if __name__ == "__main__":
    main()
