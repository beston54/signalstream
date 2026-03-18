#!/usr/bin/env python3
"""
X Collector Module

Fetches recent X posts for configured key phrases and maps them into
the same post schema used by the existing analysis pipeline.
"""

import argparse
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

# Reuse existing project helpers and schema writer
from collector import (
    _hash_username,
    _strip_pii_url,
    deduplicate_posts,
    detect_language,
    detect_region,
    load_config,
    save_raw_posts,
)
try:
    from .query_expander import resolve_search_phrases
except ImportError:
    from query_expander import resolve_search_phrases


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


X_SEARCH_ENDPOINTS = [
    "https://api.x.com/2/tweets/search/recent",
    "https://api.twitter.com/2/tweets/search/recent",
]
GETXAPI_ENDPOINT = "https://api.getxapi.com/twitter/tweet/advanced_search"
X_COMMUNITY_LABEL = "Open social feed"


def _is_getxapi_token(token: str) -> bool:
    """Detect whether a bearer token belongs to GetXAPI."""
    return bool(token) and token.startswith("get-x-api-")


def _build_query(phrase: str) -> str:
    """
    Build X recent-search query string for a phrase.

    Generates a broader query that captures hashtag variants and
    common reformulations of the phrase for better coverage.
    """
    raw_prefix = "raw:"
    if phrase.lower().startswith(raw_prefix):
        raw_query = phrase[len(raw_prefix):].strip()
        if not raw_query:
            return "-is:retweet"
        if "-is:retweet" in raw_query:
            return raw_query
        return f"{raw_query} -is:retweet"

    escaped = phrase.replace('"', "")

    # Build hashtag variant: "climate policy" -> "#climatepolicy"
    hashtag = "#" + escaped.replace(" ", "").replace("-", "")

    # Use OR to capture both exact phrase and hashtag variant
    query = f"(\"{escaped}\" OR {hashtag}) -is:retweet"
    return query


def _pick_title(text: str, max_len: int = 120) -> str:
    """Create a short title-like string from tweet text."""
    compact = " ".join((text or "").split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _to_iso_timestamp(value: Optional[str]) -> str:
    """Convert provider timestamp variants to ISO-8601."""
    if not value:
        return ""

    candidates = (
        "%a %b %d %H:%M:%S %z %Y",  # GetXAPI (e.g., Sun Jan 25 13:05:46 +0000 2026)
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    )
    for fmt in candidates:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.astimezone().isoformat()
        except ValueError:
            continue
    return value


def _search_once(
    session: requests.Session,
    headers: Dict[str, str],
    query: str,
    max_results: int,
    timeout: int,
    next_token: Optional[str] = None,
    preferred_endpoint: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Execute one X recent-search request.

    Returns JSON payload and the endpoint that succeeded.
    """
    endpoints = [preferred_endpoint] if preferred_endpoint else []
    endpoints.extend([e for e in X_SEARCH_ENDPOINTS if e != preferred_endpoint])

    errors: List[str] = []
    for endpoint in endpoints:
        if not endpoint:
            continue

        params: Dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "tweet.fields": "created_at,lang,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username,location",
        }
        if next_token:
            params["next_token"] = next_token

        try:
            response = session.get(endpoint, headers=headers, params=params, timeout=timeout)
        except requests.RequestException as exc:
            errors.append(f"{endpoint} request error: {exc}")
            continue

        if response.status_code == 200:
            return response.json(), endpoint

        body = response.text[:300].replace("\n", " ")
        errors.append(f"{endpoint} -> {response.status_code}: {body}")

    raise RuntimeError(" ; ".join(errors))


def _search_getxapi(
    session: requests.Session,
    headers: Dict[str, str],
    query: str,
    timeout: int,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute one GetXAPI advanced search request."""
    params: Dict[str, str] = {"q": query, "product": "Latest"}
    if cursor:
        params["cursor"] = cursor

    try:
        response = session.get(
            GETXAPI_ENDPOINT, headers=headers, params=params, timeout=timeout
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"GetXAPI request error: {exc}") from exc

    if response.status_code != 200:
        body = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"GetXAPI -> {response.status_code}: {body}")

    return response.json()


def _map_getxapi_tweet(
    tweet: Dict[str, Any],
    phrase: str,
    allowed_languages: List[str],
    allowed_regions: List[str],
    min_engagement: int,
) -> Optional[Dict[str, Any]]:
    """Map a GetXAPI tweet object to the internal post schema.

    Returns None if the tweet should be filtered out.
    """
    author_obj = tweet.get("author", {})
    username = author_obj.get("userName", "unknown")
    tweet_id = tweet.get("id", "")
    text = tweet.get("text", "")

    likes = int(tweet.get("likeCount", 0))
    retweets = int(tweet.get("retweetCount", 0))
    engagement = likes + retweets

    if engagement < min_engagement:
        return None

    lang = tweet.get("lang") or detect_language(text)
    if allowed_languages and lang not in allowed_languages and lang != "unknown":
        return None

    location = author_obj.get("location", "")
    region_info = detect_region("twitter_x", location, f"{location} {text}")
    poster_region = region_info["poster_region"]
    topic_region = region_info["topic_region"]
    if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
        return None

    raw_url = tweet.get("url") or tweet.get("twitterUrl") or (
        f"https://x.com/{username}/status/{tweet_id}"
        if username and tweet_id
        else f"https://x.com/i/web/status/{tweet_id}"
    )

    return {
        "post_id": tweet_id,
        "phrase_match": phrase,
        "title": _pick_title(text),
        "text": text,
        "subreddit": "twitter_x",
        "community_name": X_COMMUNITY_LABEL,
        "community_kind": "social",
        "source_platform": "x",
        "author": _hash_username(username),
        "upvotes": engagement,
        "comments": int(tweet.get("replyCount", 0)),
        "url": _strip_pii_url(raw_url),
        "timestamp": _to_iso_timestamp(tweet.get("createdAt")),
        "detected_language": lang,
        "detected_region": poster_region,
        "poster_region": poster_region,
        "topic_region": topic_region,
        "top_comments": [],
    }


def collect_phrase_posts_getxapi(
    session: requests.Session,
    phrase: str,
    headers: Dict[str, str],
    max_posts: int,
    allowed_languages: List[str],
    allowed_regions: List[str],
    timeout: int = 30,
    min_engagement: int = 2,
) -> List[Dict[str, Any]]:
    """Collect tweets for one phrase via GetXAPI and map to report post schema."""
    logger.info("Searching X (GetXAPI) for phrase: '%s'", phrase)

    posts: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    query = _build_query(phrase)

    while len(posts) < max_posts:
        payload = _search_getxapi(
            session=session,
            headers=headers,
            query=query,
            timeout=timeout,
            cursor=cursor,
        )

        tweets = payload.get("tweets", [])
        if not tweets:
            break

        for tweet in tweets:
            mapped = _map_getxapi_tweet(
                tweet, phrase, allowed_languages, allowed_regions, min_engagement
            )
            if mapped:
                posts.append(mapped)
            if len(posts) >= max_posts:
                break

        if not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
        if not cursor:
            break

        time.sleep(1)

    logger.info("Collected %d X posts (GetXAPI) for phrase '%s'", len(posts), phrase)
    return posts


def collect_phrase_posts(
    session: requests.Session,
    phrase: str,
    headers: Dict[str, str],
    max_posts: int,
    allowed_languages: List[str],
    allowed_regions: List[str],
    timeout: int = 30,
    min_engagement: int = 2,
) -> List[Dict[str, Any]]:
    """Collect tweets for one phrase and map them to report post schema.

    Args:
        min_engagement: Minimum likes+retweets to include a post (filters noise).
    """
    logger.info("Searching X for phrase: '%s'", phrase)

    posts: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    query = _build_query(phrase)
    preferred_endpoint: Optional[str] = None

    while len(posts) < max_posts:
        page_size = min(100, max_posts - len(posts))

        payload, preferred_endpoint = _search_once(
            session=session,
            headers=headers,
            query=query,
            max_results=page_size,
            timeout=timeout,
            next_token=next_token,
            preferred_endpoint=preferred_endpoint,
        )

        # Official X API v2
        users = payload.get("includes", {}).get("users", [])
        user_map = {u.get("id"): u for u in users if u.get("id")}
        tweets = payload.get("data", [])

        if not tweets:
            break

        for tweet in tweets:
            tweet_id = tweet.get("id", "")
            text = tweet.get("text", "")
            author_id = tweet.get("author_id", "")
            user_info = user_map.get(author_id, {})
            username = user_info.get("username", f"user_{author_id}" if author_id else "unknown")
            location = user_info.get("location", "")
            metrics = tweet.get("public_metrics", {})

            detected_language = tweet.get("lang") or detect_language(text)
            if (
                allowed_languages
                and detected_language not in allowed_languages
                and detected_language != "unknown"
            ):
                continue

            raw_url = (
                f"https://x.com/{username}/status/{tweet_id}"
                if username and tweet_id
                else f"https://x.com/i/web/status/{tweet_id}"
            )

            engagement = int(metrics.get("like_count", 0)) + int(metrics.get("retweet_count", 0))

            # Skip low-engagement noise
            if engagement < min_engagement:
                continue

            region_info = detect_region("twitter_x", location, f"{location} {text}")
            poster_region = region_info["poster_region"]
            topic_region = region_info["topic_region"]
            if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
                continue

            posts.append(
                {
                    "post_id": tweet_id,
                    "phrase_match": phrase,
                    "title": _pick_title(text),
                    "text": text,
                    "subreddit": "twitter_x",
                    "community_name": X_COMMUNITY_LABEL,
                    "community_kind": "social",
                    "source_platform": "x",
                    "author": _hash_username(username),
                    "upvotes": engagement,
                    "comments": int(metrics.get("reply_count", 0)),
                    "url": _strip_pii_url(raw_url),
                    "timestamp": _to_iso_timestamp(tweet.get("created_at")),
                    "detected_language": detected_language,
                    "detected_region": poster_region,
                    "poster_region": poster_region,
                    "topic_region": topic_region,
                    "top_comments": [],
                }
            )

            if len(posts) >= max_posts:
                break

        next_token = payload.get("meta", {}).get("next_token")
        if not next_token:
            break

        time.sleep(1)

    logger.info("Collected %d X posts for phrase '%s'", len(posts), phrase)
    return posts


def collect_all_x_posts(
    config: Dict[str, Any],
    bearer_token: str,
    phrases_override: Optional[List[str]] = None,
    dry_run: bool = False,
    api_key_header: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Collect tweets for all phrases in config (or provided phrase list).

    Automatically uses GetXAPI when the bearer token has the ``get-x-api-``
    prefix; otherwise falls back to the official X API v2 endpoints.
    """
    search_config = config.get("search", {})
    filter_config = config.get("filters", {})

    phrases = phrases_override or resolve_search_phrases(config, platform="x")
    if not phrases:
        logger.warning("No X search phrases resolved.")
        return []
    logger.info("Resolved %d X search phrase(s)", len(phrases))

    max_posts_per_phrase = int(search_config.get("max_posts_per_phrase", 50))
    allowed_languages = filter_config.get("languages", []) or []
    allowed_regions = filter_config.get("regions", []) or []

    use_getxapi = _is_getxapi_token(bearer_token)
    if use_getxapi:
        allow_gateway = bool(config.get("x", {}).get("allow_unauthorized_gateway", False))
        if not allow_gateway:
            raise RuntimeError(
                "GetXAPI is an unauthorized third-party data reseller and is "
                "blocked by default. To use it, set x.allow_unauthorized_gateway: true "
                "in config.yaml. For production use, obtain official X API credentials."
            )
        logger.warning(
            "Using GetXAPI gateway for X collection. WARNING: GetXAPI is an "
            "unauthorized third-party data reseller and may violate X/Twitter's "
            "Terms of Service. For commercial or production use, obtain official "
            "X API credentials instead."
        )

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "RedditIntelligence-XCollector/1.0",
    }
    if api_key_header:
        headers["x-api-key"] = api_key_header

    session = requests.Session()
    all_posts: List[Dict[str, Any]] = []

    for phrase in phrases:
        if use_getxapi:
            phrase_posts = collect_phrase_posts_getxapi(
                session=session,
                phrase=phrase,
                headers=headers,
                max_posts=max_posts_per_phrase,
                allowed_languages=allowed_languages,
                allowed_regions=allowed_regions,
            )
        else:
            phrase_posts = collect_phrase_posts(
                session=session,
                phrase=phrase,
                headers=headers,
                max_posts=max_posts_per_phrase,
                allowed_languages=allowed_languages,
                allowed_regions=allowed_regions,
            )
        all_posts.extend(phrase_posts)

        if dry_run and len(all_posts) >= 10:
            all_posts = all_posts[:10]
            logger.info("Dry run enabled; stopping at 10 posts total.")
            break

        time.sleep(1)

    all_posts = deduplicate_posts(all_posts)
    logger.info("Total X posts collected: %d", len(all_posts))
    return all_posts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect X posts into pipeline schema")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--output", default="data/raw", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Limit total output to 10 posts")
    parser.add_argument(
        "--bearer-token",
        help="X API bearer token (or set X_API_BEARER_TOKEN / TWITTER_BEARER_TOKEN)",
    )
    parser.add_argument(
        "--api-key",
        help="Optional X API key sent as x-api-key header (some gateways require this)",
    )
    parser.add_argument(
        "--phrase",
        action="append",
        dest="phrases",
        help="Phrase to search (repeat flag for multiple phrases). Defaults to config search.key_phrases.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    bearer_token = (
        args.bearer_token
        or os.getenv("X_API_BEARER_TOKEN")
        or os.getenv("TWITTER_BEARER_TOKEN")
    )
    if not bearer_token:
        raise SystemExit(
            "Missing bearer token. Set X_API_BEARER_TOKEN environment variable "
            "or provide --bearer-token."
        )

    api_key_header = args.api_key or os.getenv("GETX_API_KEY") or None

    posts = collect_all_x_posts(
        config=config,
        bearer_token=bearer_token,
        phrases_override=args.phrases,
        dry_run=args.dry_run,
        api_key_header=api_key_header,
    )

    if not posts:
        raise SystemExit("No posts collected from X. Check credentials, query phrases, and API access.")

    filepath = save_raw_posts(posts, args.output)
    print(f"X collection complete. Saved {len(posts)} posts to: {filepath}")


if __name__ == "__main__":
    main()
