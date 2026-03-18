"""
Reddit Post Collector Module

Fetches posts from Reddit based on configured key phrases.
Supports either:
- PRAW (official Reddit API; requires credentials)
- Reddit public JSON endpoints (no API keys; less reliable/rate-limited)

Handles rate limiting, language detection, and region inference.
"""

import hashlib
import json
import os
import secrets
import time
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Optional, List, Dict, Any
import xml.etree.ElementTree as ET
import requests
try:
    from .config_utils import load_config_file, PROJECT_ROOT
    from .query_expander import resolve_search_phrases
except ImportError:
    from config_utils import load_config_file, PROJECT_ROOT
    from query_expander import resolve_search_phrases

try:
    import praw
except ImportError:
    praw = None

# Try to import langdetect, provide helpful error if missing
try:
    from langdetect import detect, LangDetectException
except ImportError:
    print("Please install langdetect: pip install langdetect")
    raise


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REDDIT_PUBLIC_BASE_URL = "https://www.reddit.com"
REDDIT_OLD_PUBLIC_BASE_URL = "https://old.reddit.com"
DEFAULT_REDDIT_USER_AGENT = "SentimentAnalyzer/1.0 (public-json collector)"
PUBLIC_JSON_SAFE_RPM_CAP = 30
RSS_SAFE_RESULT_CAP = 100

# Subreddit discovery defaults
DEFAULT_MAX_SUBREDDITS_PER_PHRASE = 8
DEFAULT_MIN_SUBSCRIBERS = 1000


class PublicRedditCollectorError(Exception):
    """Base exception for Reddit public JSON collector failures."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        path: Optional[str] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class PublicRedditRateLimitError(PublicRedditCollectorError):
    """Raised when Reddit public JSON returns repeated HTTP 429 rate limits."""


def _is_placeholder_secret(value: Any) -> bool:
    """Return True for empty or template credential values."""
    if not isinstance(value, str):
        return True

    cleaned = value.strip()
    if not cleaned:
        return True

    return cleaned.upper().startswith("YOUR_")


def has_reddit_api_credentials(config: dict) -> bool:
    """
    Check whether config contains real Reddit API credentials.

    Args:
        config: Full configuration dictionary

    Returns:
        True if both client_id and client_secret are present and not placeholders
    """
    reddit_config = config.get('reddit', {})
    client_id = reddit_config.get('client_id', '')
    client_secret = reddit_config.get('client_secret', '')
    return not _is_placeholder_secret(client_id) and not _is_placeholder_secret(client_secret)


def get_collection_provider(config: dict) -> str:
    """
    Determine which Reddit collection backend to use.

    Priority:
    1. config.collector.provider (public_json | praw | auto)
    2. auto-detect based on whether API credentials are configured
    """
    collector_config = config.get('collector', {})
    configured = str(collector_config.get('provider', 'auto')).strip().lower()

    if configured == 'praw':
        return 'praw'
    if configured == 'public_json':
        return 'public_json'
    if configured not in ('', 'auto'):
        logger.warning(
            "Unknown collector.provider '%s'; falling back to auto selection",
            configured
        )

    if has_reddit_api_credentials(config):
        return 'praw'

    # Check if public_json has been explicitly opted into
    accept_risk = bool(config.get('collector', {}).get('accept_public_json_risk', False))
    has_branding = bool(config.get('branding', {}).get('company_name'))

    if has_branding and not accept_risk:
        raise RuntimeError(
            "No Reddit API credentials found and branding is configured "
            "(indicating commercial use). public_json scraping may violate "
            "Reddit's Terms of Service. Either configure PRAW credentials "
            "(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET) or set "
            "collector.accept_public_json_risk: true in config.yaml."
        )

    if not accept_risk:
        logger.warning(
            "No Reddit API credentials found — falling back to public_json mode. "
            "WARNING: public_json scraping may violate Reddit's Terms of Service. "
            "For commercial or production use, configure PRAW credentials "
            "(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT). "
            "Set collector.accept_public_json_risk: true to suppress this warning."
        )
    return 'public_json'


def get_collection_provider_candidates(config: dict) -> List[str]:
    """
    Return an ordered list of collector backends to try.

    `auto` mode may append a PRAW fallback when enabled and credentials exist.
    Explicit `public_json` remains a strict no-PRAW mode.
    """
    collector_config = config.get('collector', {})
    configured = str(collector_config.get('provider', 'auto')).strip().lower()
    provider = get_collection_provider(config)
    enable_fallback = bool(collector_config.get('fallback_to_praw_on_public_failure', True))

    if provider == 'praw':
        return ['praw']

    candidates = ['public_json']
    # If the user explicitly chose public_json, keep the collector fully
    # unofficial/no-credentials and do not fall back to PRAW.
    if configured == 'public_json':
        logger.warning(
            "public_json mode is explicitly configured. This mode may violate "
            "Reddit's Terms of Service. For commercial use, switch to PRAW."
        )
        return candidates
    if enable_fallback and has_reddit_api_credentials(config):
        candidates.append('praw')
    return candidates


def get_reddit_user_agent(config: dict) -> str:
    """Return configured user agent or a safe default."""
    reddit_config = config.get('reddit', {})
    return reddit_config.get('user_agent') or DEFAULT_REDDIT_USER_AGENT


def get_public_request_timeout(config: dict) -> int:
    """Return timeout (seconds) for public JSON HTTP calls."""
    collector_config = config.get('collector', {})
    timeout = collector_config.get('request_timeout_seconds', 20)
    try:
        timeout_int = int(timeout)
    except (TypeError, ValueError):
        timeout_int = 20
    return max(5, timeout_int)


def get_public_request_retries(config: dict) -> int:
    """Return retry attempts for public JSON calls."""
    collector_config = config.get('collector', {})
    retries = collector_config.get('max_retries', 4)
    try:
        retries_int = int(retries)
    except (TypeError, ValueError):
        retries_int = 4
    return max(0, retries_int)


def get_public_retry_backoff_seconds(config: dict) -> float:
    """Return base backoff (seconds) for public JSON retries."""
    collector_config = config.get('collector', {})
    backoff = collector_config.get('retry_backoff_seconds', 2.0)
    try:
        backoff_float = float(backoff)
    except (TypeError, ValueError):
        backoff_float = 2.0
    return max(0.5, backoff_float)


def get_effective_reddit_rate_limit(config: dict, provider: str) -> int:
    """
    Return effective requests/minute based on provider and config.

    Public JSON mode uses a lower default cap for stability unless an explicit
    `collector.public_json_requests_per_minute` override is provided.
    """
    rate_limit_config = config.get('rate_limits', {})
    configured = rate_limit_config.get('reddit_requests_per_minute', 60)

    try:
        configured_rpm = int(configured)
    except (TypeError, ValueError):
        configured_rpm = 60

    configured_rpm = max(1, configured_rpm)

    if provider != 'public_json':
        return configured_rpm

    collector_config = config.get('collector', {})
    public_override = collector_config.get('public_json_requests_per_minute')
    if public_override is not None:
        try:
            return max(1, int(public_override))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid collector.public_json_requests_per_minute=%r; using fallback defaults",
                public_override,
            )

    effective = min(configured_rpm, PUBLIC_JSON_SAFE_RPM_CAP)
    if configured_rpm > PUBLIC_JSON_SAFE_RPM_CAP:
        logger.info(
            "Clamping public JSON rate limit from %d to %d requests/min for stability. "
            "Override with collector.public_json_requests_per_minute if needed.",
            configured_rpm,
            effective,
        )
    return effective


def load_config(config_path: str = "config.yaml") -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config.yaml file

    Returns:
        Dictionary containing all configuration settings

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    config = load_config_file(config_path)
    logger.info(f"Loaded configuration from {config_path}")
    return config


def create_reddit_client(config: dict) -> Any:
    """
    Initialize authenticated Reddit client using PRAW.

    Args:
        config: Configuration dictionary with reddit credentials

    Returns:
        Authenticated praw.Reddit instance

    Raises:
        praw.exceptions.ResponseException: If credentials invalid
    """
    if praw is None:
        raise ImportError(
            "PRAW is not installed. Install requirements or use collector.provider=public_json"
        )

    if not has_reddit_api_credentials(config):
        raise ValueError(
            "Reddit API credentials are not configured; use collector.provider=public_json "
            "or add client_id/client_secret"
        )

    reddit_config = config.get('reddit', {})

    reddit = praw.Reddit(
        client_id=reddit_config.get('client_id'),
        client_secret=reddit_config.get('client_secret'),
        user_agent=reddit_config.get('user_agent', 'SentimentAnalyzer/1.0')
    )

    # Verify connection works (read-only is fine)
    logger.info("Reddit client initialized successfully")
    return reddit


def create_public_reddit_session(config: dict) -> requests.Session:
    """
    Create a requests session for Reddit public JSON endpoints.

    Args:
        config: Full configuration dictionary

    Returns:
        Configured requests.Session with User-Agent headers
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': get_reddit_user_agent(config),
        'Accept': 'application/json',
        'Referer': 'https://www.reddit.com/',
    })
    logger.info("Reddit public JSON session initialized (no API keys)")
    return session


def detect_language(text: str) -> str:
    """
    Detect language of text using langdetect library.

    Args:
        text: Text content to analyze

    Returns:
        ISO 639-1 language code (e.g., 'en', 'es', 'fr')
        Returns 'unknown' if detection fails
    """
    if not text or len(text.strip()) < 20:
        return 'unknown'

    try:
        return detect(text)
    except LangDetectException:
        return 'unknown'


# Region detection: subreddit-name patterns (checked first, case-insensitive)
_SUBREDDIT_REGION_PATTERNS = {
    'United States': [r'(usa|america|american|uspolitics|askamerica)'],
    'Germany': [r'(germany|german|deutschland|deutsch)'],
    'United Kingdom': [r'(ukpolitics|unitedkingdom|casualuk|britishproblems)'],
    'Canada': [r'(canada|canadapolitics|onguardforthee)'],
    'Australia': [r'(australia|australian|australianpolitics)'],
    'France': [r'(france|french)'],
    'Europe': [r'(europe|eupolitics|europes)'],
    'India': [r'(india|indian|indiaspeaks)'],
    'Japan': [r'(japan|japanese)'],
    'Pakistan': [r'(pakistan|pakistani)'],
    'UAE': [r'(uae|dubai|abudhabi)'],
    'Zimbabwe': [r'(zimbabwe)'],
}

# Region detection: text/flair patterns (require more context)
_TEXT_REGION_PATTERNS = {
    # "us" requires uppercase (US) or longer form to avoid matching the English pronoun
    'United States': [r'\b(usa|america|american|united states|U\.?S\.?A?)\b'],
    'Germany': [r'\b(germany|german|deutschland|deutsch)\b'],
    'United Kingdom': [r'\b(uk|britain|british|england|english|united kingdom)\b'],
    'Canada': [r'\b(canada|canadian)\b'],
    'Australia': [r'\b(australia|australian|aussie)\b'],
    'France': [r'\b(france|french|francais)\b'],
    'Europe': [r'\b(europe|european|eu)\b'],
    'India': [r'\b(india|indian)\b'],
    'Japan': [r'\b(japan|japanese)\b'],
}

# Subreddit-to-region mapping for poster_region inference (highest confidence)
SUBREDDIT_REGION_MAP = {
    # Country-specific subreddits
    'ukpolitics': 'United Kingdom', 'unitedkingdom': 'United Kingdom',
    'casualuk': 'United Kingdom', 'askuk': 'United Kingdom',
    'de': 'Germany', 'germany': 'Germany',
    'france': 'France', 'europe': 'Europe',
    'canada': 'Canada', 'onguardforthee': 'Canada',
    'australia': 'Australia', 'ausnews': 'Australia',
    'india': 'India', 'indiaspeaks': 'India',
    'brasil': 'Brazil', 'mexico': 'Mexico',
    'japan': 'Japan', 'korea': 'South Korea',
    'AskAnAmerican': 'United States',
    'AmericanPolitics': 'United States',
    'politics': 'United States',  # US-centric by default
    'news': 'United States',  # US-centric by default
    'conservative': 'United States',
    'liberal': 'United States',
    'worldnews': 'International',
    'geopolitics': 'International',
    'iran': 'Iran', 'iranian': 'Iran',
}

# Self-identification patterns for poster_region inference
SELF_ID_PATTERNS = [
    re.compile(r'\b(?:I(?:\'m| am) (?:from|in|living in)|Here in|As (?:a|an) [\w]+ (?:from|in))\s+([A-Z][\w\s]{2,20})', re.IGNORECASE),
]


def _detect_topic_region(text: str, flair: str = '') -> str:
    """Detect what region the post is ABOUT based on text content.

    This is the original text-based detection logic (what the post talks about).

    Args:
        text: Combined title and body text
        flair: Flair text if available

    Returns:
        Detected topic region string or 'global' if undetermined
    """
    combined = f"{flair} {text}".strip()

    for region, patterns in _TEXT_REGION_PATTERNS.items():
        for pattern in patterns:
            if region == 'United States':
                if re.search(pattern, combined):
                    return region
            else:
                if re.search(pattern, combined, re.IGNORECASE):
                    return region

    return 'global'


def _detect_poster_region(subreddit: str, flair: str, text: str) -> str:
    """Detect where the poster is FROM using a priority hierarchy.

    Priority:
    1. Subreddit geography (highest confidence)
    2. User flair containing country/region names
    3. Self-identification phrases in text
    4. Default: "Unknown"

    Args:
        subreddit: Subreddit name
        flair: Flair text if available
        text: Combined title and body text

    Returns:
        Detected poster region string or 'Unknown' if undetermined
    """
    # 1. Subreddit geography (highest confidence)
    sub_lower = subreddit.lower()
    # Check exact match in SUBREDDIT_REGION_MAP (case-insensitive)
    for sub_key, region in SUBREDDIT_REGION_MAP.items():
        if sub_lower == sub_key.lower():
            return region

    # Also check legacy subreddit patterns for broader matching
    for region, patterns in _SUBREDDIT_REGION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, sub_lower):
                return region

    # 2. User flair containing country/region names
    if flair:
        flair_text = flair.strip()
        for region, patterns in _TEXT_REGION_PATTERNS.items():
            for pattern in patterns:
                if region == 'United States':
                    if re.search(pattern, flair_text):
                        return region
                else:
                    if re.search(pattern, flair_text, re.IGNORECASE):
                        return region

    # 3. Self-identification phrases in text
    if text:
        for pattern in SELF_ID_PATTERNS:
            match = pattern.search(text)
            if match:
                identified = match.group(1).strip().rstrip('.,;:')
                # Validate against known region names
                identified_lower = identified.lower()
                for region in list(_TEXT_REGION_PATTERNS.keys()) + list(SUBREDDIT_REGION_MAP.values()):
                    if region.lower() == identified_lower or region.lower() in identified_lower:
                        return region
                # Return the raw match if it looks like a proper noun (starts with uppercase)
                if identified[0].isupper() and len(identified) > 2:
                    return identified

    return 'Unknown'


def detect_region(
    subreddit_name: str,
    post_flair: Optional[str],
    post_text: str
) -> dict:
    """Detect both poster region and topic region.

    Separates WHERE the poster is from (poster_region) from WHAT the post
    is about geographically (topic_region). This is critical for political
    and international analysis where a post about "US foreign policy" written
    by someone in the UK should not be tagged as coming from the US.

    Args:
        subreddit_name: Name of the subreddit
        post_flair: Flair text if available
        post_text: Combined title and body text

    Returns:
        {"poster_region": "...", "topic_region": "..."}
    """
    flair = (post_flair or '').strip()
    text = (post_text or '').strip()

    poster_region = _detect_poster_region(subreddit_name or '', flair, text)
    topic_region = _detect_topic_region(text, flair)

    return {
        "poster_region": poster_region,
        "topic_region": topic_region,
    }


def fetch_top_comments(
    submission: Any,
    max_comments: int,
    depth: int
) -> List[Dict[str, Any]]:
    """
    Retrieve top comments from a Reddit submission.

    Args:
        submission: PRAW Submission object
        max_comments: Maximum number of comments to retrieve
        depth: How many reply levels to include (1=top-level only)

    Returns:
        List of comment dictionaries with keys:
        - comment_id, body, author, upvotes, timestamp, depth, replies
    """
    comments = []
    if max_comments <= 0:
        return comments

    try:
        # Replace "more comments" with actual comments (limit loading)
        submission.comments.replace_more(limit=0)

        for i, comment in enumerate(submission.comments[:max_comments]):
            if hasattr(comment, 'body'):
                comment_data = {
                    'comment_id': comment.id,
                    'body': comment.body,
                    'author': str(comment.author) if comment.author else '[deleted]',
                    'upvotes': comment.score,
                    'timestamp': datetime.utcfromtimestamp(comment.created_utc).isoformat(),
                    'depth': 1,
                    'replies': []
                }

                # Get replies if depth > 1
                if depth > 1:
                    for j, reply in enumerate(comment.replies[:3]):  # Max 3 replies per comment
                        if hasattr(reply, 'body'):
                            reply_data = {
                                'comment_id': reply.id,
                                'body': reply.body,
                                'author': str(reply.author) if reply.author else '[deleted]',
                                'upvotes': reply.score,
                                'timestamp': datetime.utcfromtimestamp(reply.created_utc).isoformat(),
                                'depth': 2,
                                'replies': []
                            }
                            comment_data['replies'].append(reply_data)

                comments.append(comment_data)
    except Exception as e:
        logger.warning(f"Error fetching comments: {e}")

    return comments


def public_reddit_get(
    session: requests.Session,
    path: str,
    params: Optional[Dict[str, Any]],
    rate_limiter: "RateLimiter",
    timeout_seconds: int,
    retries: int = 4,
    retry_backoff_seconds: float = 2.0,
) -> Any:
    """
    GET a Reddit public JSON endpoint with rate limiting and sane defaults.

    Args:
        session: Requests session
        path: Relative path (e.g., 'search.json')
        params: Query parameters
        rate_limiter: Rate limiter instance
        timeout_seconds: Request timeout in seconds

    Returns:
        Parsed JSON response
    """
    query = {k: v for k, v in (params or {}).items() if v is not None}
    query.setdefault('raw_json', 1)

    url = f"{REDDIT_PUBLIC_BASE_URL}/{path.lstrip('/')}"

    total_attempts = max(1, retries + 1)
    last_exc: Optional[Exception] = None

    for attempt in range(1, total_attempts + 1):
        try:
            rate_limiter.wait_if_needed()
            rate_limiter.record_request()

            response = session.get(url, params=query, timeout=timeout_seconds)

            if response.status_code == 429:
                retry_after_header = response.headers.get('Retry-After')
                retry_after_seconds: Optional[float] = None
                if retry_after_header:
                    try:
                        retry_after_seconds = float(retry_after_header)
                    except (TypeError, ValueError):
                        retry_after_seconds = None

                if attempt >= total_attempts:
                    message = (
                        f"Reddit public JSON rate-limited (HTTP 429) after {attempt} attempts "
                        f"for {path}. Reduce collector.public_json_requests_per_minute."
                    )
                    raise PublicRedditRateLimitError(
                        message=message,
                        status_code=429,
                        path=path,
                    )

                sleep_seconds = retry_after_seconds or (retry_backoff_seconds * attempt)
                logger.warning(
                    "Reddit public JSON returned HTTP 429 for %s (attempt %d/%d). "
                    "Sleeping %.1fs before retry. Consider lowering "
                    "collector.public_json_requests_per_minute.",
                    path,
                    attempt,
                    total_attempts,
                    sleep_seconds,
                )
                time.sleep(max(0.5, sleep_seconds))
                continue

            if response.status_code in (500, 502, 503, 504):
                if attempt >= total_attempts:
                    raise PublicRedditCollectorError(
                        message=(
                            f"Reddit public JSON server error HTTP {response.status_code} "
                            f"after {attempt} attempts for {path}"
                        ),
                        status_code=response.status_code,
                        path=path,
                    )

                sleep_seconds = retry_backoff_seconds * attempt
                logger.warning(
                    "Reddit public JSON HTTP %d for %s (attempt %d/%d). Retrying in %.1fs.",
                    response.status_code,
                    path,
                    attempt,
                    total_attempts,
                    sleep_seconds,
                )
                time.sleep(max(0.5, sleep_seconds))
                continue

            if response.status_code in (401, 403):
                raise PublicRedditCollectorError(
                    message=(
                        f"Reddit public JSON access blocked (HTTP {response.status_code}) for {path}"
                    ),
                    status_code=response.status_code,
                    path=path,
                )

            response.raise_for_status()
            return response.json()

        except requests.Timeout as e:
            last_exc = e
            if attempt >= total_attempts:
                raise PublicRedditCollectorError(
                    message=f"Timeout fetching Reddit public JSON for {path}",
                    path=path,
                ) from e

            sleep_seconds = retry_backoff_seconds * attempt
            logger.warning(
                "Timeout fetching %s (attempt %d/%d). Retrying in %.1fs.",
                path,
                attempt,
                total_attempts,
                sleep_seconds,
            )
            time.sleep(max(0.5, sleep_seconds))

        except requests.RequestException as e:
            last_exc = e
            if attempt >= total_attempts:
                raise PublicRedditCollectorError(
                    message=f"HTTP error fetching Reddit public JSON for {path}: {e}",
                    path=path,
                ) from e

            sleep_seconds = retry_backoff_seconds * attempt
            logger.warning(
                "HTTP error fetching %s (attempt %d/%d): %s. Retrying in %.1fs.",
                path,
                attempt,
                total_attempts,
                e,
                sleep_seconds,
            )
            time.sleep(max(0.5, sleep_seconds))

        except ValueError as e:
            last_exc = e
            if attempt >= total_attempts:
                raise PublicRedditCollectorError(
                    message=f"Invalid JSON from Reddit public endpoint for {path}",
                    path=path,
                ) from e

            sleep_seconds = retry_backoff_seconds * attempt
            logger.warning(
                "Invalid JSON from %s (attempt %d/%d). Retrying in %.1fs.",
                path,
                attempt,
                total_attempts,
                sleep_seconds,
            )
            time.sleep(max(0.5, sleep_seconds))

    if last_exc:
        raise PublicRedditCollectorError(
            message=f"Unknown Reddit public JSON failure for {path}: {last_exc}",
            path=path,
        ) from last_exc

    raise PublicRedditCollectorError(
        message=f"Unknown Reddit public JSON failure for {path}",
        path=path,
    )


def public_reddit_get_text(
    session: requests.Session,
    path: str,
    params: Optional[Dict[str, Any]],
    rate_limiter: "RateLimiter",
    timeout_seconds: int,
    retries: int = 4,
    retry_backoff_seconds: float = 2.0,
) -> str:
    """
    GET a Reddit public text endpoint (e.g., RSS) with rate limiting + retries.

    Tries www.reddit.com first, then old.reddit.com for 401/403 failures.
    """
    query = {k: v for k, v in (params or {}).items() if v is not None}
    urls = [
        f"{REDDIT_PUBLIC_BASE_URL}/{path.lstrip('/')}",
        f"{REDDIT_OLD_PUBLIC_BASE_URL}/{path.lstrip('/')}",
    ]

    total_attempts = max(1, retries + 1)
    last_exc: Optional[Exception] = None

    for attempt in range(1, total_attempts + 1):
        for url_index, url in enumerate(urls):
            try:
                rate_limiter.wait_if_needed()
                rate_limiter.record_request()

                response = session.get(url, params=query, timeout=timeout_seconds)

                if response.status_code in (401, 403) and url_index < len(urls) - 1:
                    logger.warning(
                        "Reddit public endpoint blocked at %s (HTTP %d) for %s; trying alternate origin.",
                        urls[url_index],
                        response.status_code,
                        path,
                    )
                    continue

                if response.status_code == 429:
                    if attempt >= total_attempts:
                        raise PublicRedditRateLimitError(
                            message=(
                                f"Reddit public endpoint rate-limited (HTTP 429) after {attempt} attempts "
                                f"for {path}"
                            ),
                            status_code=429,
                            path=path,
                        )
                    sleep_seconds = retry_backoff_seconds * attempt
                    logger.warning(
                        "HTTP 429 for %s (attempt %d/%d). Retrying in %.1fs.",
                        path,
                        attempt,
                        total_attempts,
                        sleep_seconds,
                    )
                    time.sleep(max(0.5, sleep_seconds))
                    break

                if response.status_code in (500, 502, 503, 504):
                    if attempt >= total_attempts:
                        raise PublicRedditCollectorError(
                            message=(
                                f"Reddit public endpoint server error HTTP {response.status_code} "
                                f"after {attempt} attempts for {path}"
                            ),
                            status_code=response.status_code,
                            path=path,
                        )
                    sleep_seconds = retry_backoff_seconds * attempt
                    logger.warning(
                        "HTTP %d for %s (attempt %d/%d). Retrying in %.1fs.",
                        response.status_code,
                        path,
                        attempt,
                        total_attempts,
                        sleep_seconds,
                    )
                    time.sleep(max(0.5, sleep_seconds))
                    break

                if response.status_code in (401, 403):
                    raise PublicRedditCollectorError(
                        message=(
                            f"Reddit public endpoint blocked (HTTP {response.status_code}) for {path}"
                        ),
                        status_code=response.status_code,
                        path=path,
                    )

                response.raise_for_status()
                return response.text

            except requests.Timeout as e:
                last_exc = e
                if attempt >= total_attempts and url_index == len(urls) - 1:
                    raise PublicRedditCollectorError(
                        message=f"Timeout fetching Reddit public endpoint for {path}",
                        path=path,
                    ) from e
                if url_index == len(urls) - 1:
                    sleep_seconds = retry_backoff_seconds * attempt
                    logger.warning(
                        "Timeout fetching %s (attempt %d/%d). Retrying in %.1fs.",
                        path,
                        attempt,
                        total_attempts,
                        sleep_seconds,
                    )
                    time.sleep(max(0.5, sleep_seconds))

            except requests.RequestException as e:
                last_exc = e
                if attempt >= total_attempts and url_index == len(urls) - 1:
                    raise PublicRedditCollectorError(
                        message=f"HTTP error fetching Reddit public endpoint for {path}: {e}",
                        path=path,
                    ) from e
                if url_index == len(urls) - 1:
                    sleep_seconds = retry_backoff_seconds * attempt
                    logger.warning(
                        "HTTP error fetching %s (attempt %d/%d): %s. Retrying in %.1fs.",
                        path,
                        attempt,
                        total_attempts,
                        e,
                        sleep_seconds,
                    )
                    time.sleep(max(0.5, sleep_seconds))

    if last_exc:
        raise PublicRedditCollectorError(
            message=f"Unknown Reddit public endpoint failure for {path}: {last_exc}",
            path=path,
        ) from last_exc

    raise PublicRedditCollectorError(
        message=f"Unknown Reddit public endpoint failure for {path}",
        path=path,
    )


def _get_discovery_config(config: dict) -> dict:
    """Return normalized subreddit discovery settings."""
    collector_cfg = config.get('collector', {})
    return {
        'enabled': bool(collector_cfg.get('subreddit_discovery', True)),
        'max_subreddits': max(1, int(collector_cfg.get('max_subreddits_per_phrase', DEFAULT_MAX_SUBREDDITS_PER_PHRASE))),
        'min_subscribers': max(0, int(collector_cfg.get('min_subscribers', DEFAULT_MIN_SUBSCRIBERS))),
    }


def _score_subreddit(
    name: str,
    subscribers: int,
    description: str,
    phrase: str,
) -> float:
    """
    Score a subreddit's relevance to a search phrase.

    Combines subscriber count (log-scaled) with keyword overlap
    between the phrase and the subreddit name/description.
    """
    import math

    phrase_lower = phrase.lower()
    phrase_words = set(phrase_lower.split())
    name_lower = name.lower()
    desc_lower = (description or '').lower()

    score = 0.0

    # Exact phrase in subreddit name is a strong signal
    if phrase_lower.replace(' ', '') in name_lower.replace('_', '').replace('-', ''):
        score += 50.0

    # Word overlap with name
    name_words = set(re.split(r'[\s_\-]+', name_lower))
    name_overlap = len(phrase_words & name_words)
    score += name_overlap * 15.0

    # Word overlap with description
    desc_words = set(re.split(r'[\s_\-.,;:!?]+', desc_lower))
    desc_overlap = len(phrase_words & desc_words)
    score += desc_overlap * 5.0

    # Phrase appears in description
    if phrase_lower in desc_lower:
        score += 20.0

    # Subscriber count (log-scaled, capped)
    if subscribers > 0:
        score += min(20.0, math.log10(subscribers) * 3.0)

    return score


def discover_relevant_subreddits(
    session: requests.Session,
    phrase: str,
    config: dict,
    rate_limiter: "RateLimiter",
) -> List[Dict[str, Any]]:
    """
    Find relevant subreddits for a search phrase using Reddit's public API.

    Hits the subreddit search endpoint and scores results by relevance.

    Args:
        session: Configured requests session
        phrase: Topic phrase to find communities for
        config: Full configuration dictionary
        rate_limiter: Rate limiter instance

    Returns:
        List of dicts with 'name', 'subscribers', 'description', 'score'
        sorted by relevance score (descending)
    """
    discovery_cfg = _get_discovery_config(config)
    timeout_seconds = get_public_request_timeout(config)
    retries = get_public_request_retries(config)
    retry_backoff = get_public_retry_backoff_seconds(config)
    min_subscribers = discovery_cfg['min_subscribers']
    max_subreddits = discovery_cfg['max_subreddits']

    logger.info("Discovering subreddits for phrase: '%s'", phrase)

    subreddits: List[Dict[str, Any]] = []

    try:
        payload = public_reddit_get(
            session=session,
            path="subreddits/search.json",
            params={
                'q': phrase,
                'limit': 25,
                'sort': 'relevance',
                'include_over_18': 'on',
            },
            rate_limiter=rate_limiter,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_backoff_seconds=retry_backoff,
        )

        listing_data = (payload or {}).get('data', {}) if isinstance(payload, dict) else {}
        children = listing_data.get('children', []) or []

        for child in children:
            if not isinstance(child, dict) or child.get('kind') != 't5':
                continue

            data = child.get('data', {}) or {}
            name = data.get('display_name', '') or ''
            subscribers = int(data.get('subscribers', 0) or 0)
            description = data.get('public_description', '') or data.get('title', '') or ''

            if not name:
                continue

            if subscribers < min_subscribers:
                continue

            score = _score_subreddit(name, subscribers, description, phrase)

            subreddits.append({
                'name': name,
                'subscribers': subscribers,
                'description': description[:200],
                'score': score,
            })

        # Sort by relevance score
        subreddits.sort(key=lambda s: s['score'], reverse=True)
        subreddits = subreddits[:max_subreddits]

        if subreddits:
            logger.info(
                "Discovered %d relevant subreddits for '%s': %s",
                len(subreddits),
                phrase,
                ", ".join(f"r/{s['name']}({s['score']:.0f})" for s in subreddits[:5]),
            )
        else:
            logger.warning("No relevant subreddits found for '%s'; will fall back to r/all", phrase)

    except PublicRedditCollectorError as e:
        logger.warning("Subreddit discovery failed for '%s': %s; will use r/all", phrase, e)
    except Exception as e:
        logger.warning("Unexpected error in subreddit discovery for '%s': %s; will use r/all", phrase, e)

    return subreddits


def search_subreddit_posts_public_json(
    session: requests.Session,
    phrase: str,
    subreddit: str,
    config: dict,
    rate_limiter: "RateLimiter",
    max_posts: int = 25,
) -> List[Dict[str, Any]]:
    """
    Search for posts within a specific subreddit using public JSON endpoints.

    Args:
        session: Requests session
        phrase: Search phrase
        subreddit: Subreddit name to search within
        config: Configuration dictionary
        rate_limiter: Rate limiter instance
        max_posts: Maximum posts to collect from this subreddit

    Returns:
        List of post dictionaries
    """
    search_config = config.get('search', {})
    filter_config = config.get('filters', {})

    min_upvotes = search_config.get('min_upvotes', 5)
    time_range = get_time_filter(search_config.get('time_range', 'week'))
    comment_depth = search_config.get('comment_depth', 2)
    max_comments = search_config.get('max_comments_per_post', 10)
    timeout_seconds = get_public_request_timeout(config)
    retries = get_public_request_retries(config)
    retry_backoff = get_public_retry_backoff_seconds(config)

    allowed_languages = filter_config.get('languages', [])
    allowed_regions = filter_config.get('regions', [])

    posts: List[Dict[str, Any]] = []

    try:
        payload = public_reddit_get(
            session=session,
            path=f"r/{subreddit}/search.json",
            params={
                'q': phrase,
                'sort': 'relevance',
                't': time_range,
                'limit': min(100, max(1, max_posts * 2)),
                'type': 'link',
                'restrict_sr': 1,
                'include_over_18': 'on',
            },
            rate_limiter=rate_limiter,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_backoff_seconds=retry_backoff,
        )

        listing_data = (payload or {}).get('data', {}) if isinstance(payload, dict) else {}
        children = listing_data.get('children', []) or []

        for child in children:
            if not isinstance(child, dict) or child.get('kind') != 't3':
                continue

            submission = child.get('data', {}) or {}

            if (submission.get('score') or 0) < min_upvotes:
                continue

            title = submission.get('title', '') or ''
            selftext = submission.get('selftext', '') or ''
            post_text = f"{title} {selftext}".strip()

            detected_language = detect_language(post_text)
            if allowed_languages and detected_language not in allowed_languages:
                if detected_language != 'unknown':
                    continue

            subreddit_name = submission.get('subreddit', subreddit) or subreddit
            flair = submission.get('link_flair_text')
            region_info = detect_region(subreddit_name, flair, post_text)
            poster_region = region_info["poster_region"]
            topic_region = region_info["topic_region"]
            # Filter by region: match if either poster or topic region is in allowed list
            if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
                continue

            post_id = submission.get('id')
            if not post_id:
                continue

            comments = []
            if max_comments > 0:
                comments = fetch_top_comments_public_json(
                    session=session,
                    post_id=post_id,
                    max_comments=max_comments,
                    depth=comment_depth,
                    rate_limiter=rate_limiter,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    retry_backoff_seconds=retry_backoff,
                )

            permalink = submission.get('permalink', '') or ''
            url = permalink if permalink.startswith('http') else f"https://reddit.com{permalink}"

            created_utc = submission.get('created_utc')
            post_age_hours = 0
            if created_utc:
                try:
                    post_age_hours = round((time.time() - float(created_utc)) / 3600, 1)
                except (TypeError, ValueError):
                    pass

            num_comments = submission.get('num_comments', 0) or 0
            score = submission.get('score', 0) or 0
            comment_to_upvote_ratio = round(num_comments / max(score, 1), 3)

            posts.append({
                'post_id': post_id,
                'phrase_match': phrase,
                'title': title,
                'text': selftext,
                'subreddit': subreddit_name,
                'community_name': subreddit_name,
                'community_kind': 'forum',
                'source_platform': 'reddit',
                'author': submission.get('author') or '[deleted]',
                'upvotes': score,
                'comments': num_comments,
                'url': url,
                'timestamp': _isoformat_from_utc(created_utc),
                'detected_language': detected_language,
                'detected_region': poster_region,
                'poster_region': poster_region,
                'topic_region': topic_region,
                'top_comments': comments,
                'upvote_ratio': submission.get('upvote_ratio', 0),
                'total_awards': submission.get('total_awards_received', 0) or 0,
                'link_flair_text': flair or '',
                'is_crosspost': bool(submission.get('crosspost_parent')),
                'crosspost_subreddit': (submission.get('crosspost_parent_list', [{}]) or [{}])[0].get('subreddit', '') if submission.get('crosspost_parent') else '',
                'post_age_hours': post_age_hours,
                'comment_to_upvote_ratio': comment_to_upvote_ratio,
            })

            if len(posts) >= max_posts:
                break

    except PublicRedditCollectorError as e:
        logger.warning("Error searching r/%s for '%s': %s", subreddit, phrase, e)
    except Exception as e:
        logger.warning("Unexpected error searching r/%s for '%s': %s", subreddit, phrase, e)

    return posts


def _isoformat_from_utc(timestamp_value: Any) -> str:
    """Convert Reddit UTC timestamp to ISO8601 string."""
    try:
        return datetime.utcfromtimestamp(float(timestamp_value)).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.utcnow().isoformat()


def _strip_html_to_text(value: str) -> str:
    """Convert a small HTML fragment into plain text for fallback collection."""
    if not value:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", value)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _parse_public_timestamp(value: str) -> str:
    """Parse common Reddit RSS timestamp formats into ISO8601."""
    if not value:
        return datetime.utcnow().isoformat()

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return datetime.utcnow().isoformat()


def _extract_post_id_from_reddit_link(entry_id: str, link: str) -> Optional[str]:
    """Extract Reddit post id from an Atom entry id or comments permalink."""
    match = re.search(r"\bt3_([a-z0-9]+)\b", entry_id or "", re.IGNORECASE)
    if match:
        return match.group(1).lower()

    match = re.search(r"/comments/([a-z0-9]+)/", link or "", re.IGNORECASE)
    if match:
        return match.group(1).lower()

    return None


def _extract_subreddit_from_link(link: str) -> str:
    """Extract subreddit/community label from a Reddit permalink."""
    match = re.search(r"/r/([^/]+)/", link or "", re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown"


def parse_reddit_search_rss(feed_xml: str) -> List[Dict[str, Any]]:
    """
    Parse Reddit search RSS/Atom feed into a lightweight post list.

    Returned rows intentionally match the collector's downstream schema as
    closely as possible, but engagement metrics/comments may be unavailable.
    """
    if not feed_xml or not feed_xml.strip():
        return []

    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as e:
        raise PublicRedditCollectorError("Invalid RSS/Atom feed received from Reddit public search") from e

    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries: List[Dict[str, Any]] = []

    for entry in root.findall("atom:entry", atom_ns):
        title = (entry.findtext("atom:title", default="", namespaces=atom_ns) or "").strip()
        entry_id = (entry.findtext("atom:id", default="", namespaces=atom_ns) or "").strip()
        updated = (entry.findtext("atom:updated", default="", namespaces=atom_ns) or "").strip()

        link_url = ""
        for link_node in entry.findall("atom:link", atom_ns):
            href = (link_node.attrib.get("href") or "").strip()
            rel = (link_node.attrib.get("rel") or "alternate").strip()
            if href and rel in ("alternate", ""):
                link_url = href
                break
        if not link_url:
            link_url = (entry.findtext("atom:link", default="", namespaces=atom_ns) or "").strip()

        summary_html = (
            entry.findtext("atom:content", default="", namespaces=atom_ns)
            or entry.findtext("atom:summary", default="", namespaces=atom_ns)
            or ""
        )
        author_name = (
            entry.findtext("atom:author/atom:name", default="", namespaces=atom_ns)
            or "[deleted]"
        )

        post_id = _extract_post_id_from_reddit_link(entry_id, link_url)
        if not post_id or not link_url:
            continue

        # Remove common Reddit prefixes for cleaner display / anonymization later.
        author_name = re.sub(r"^/u/", "", author_name.strip(), flags=re.IGNORECASE) or "[deleted]"

        entries.append({
            "post_id": post_id,
            "title": title or "Untitled post",
            "text": _strip_html_to_text(summary_html),
            "url": link_url,
            "author": author_name,
            "timestamp": _parse_public_timestamp(updated),
            "subreddit": _extract_subreddit_from_link(link_url),
        })

    return entries


def _parse_public_comment_node(
    node: Dict[str, Any],
    current_depth: int,
    max_depth: int
) -> Optional[Dict[str, Any]]:
    """
    Convert a Reddit public JSON comment node to the collector comment schema.

    Args:
        node: A listing child node
        current_depth: Current nesting depth (1 = top-level)
        max_depth: Maximum nesting depth to include

    Returns:
        Parsed comment dict or None if node is not a comment
    """
    if not isinstance(node, dict) or node.get('kind') != 't1':
        return None

    data = node.get('data', {}) or {}
    comment_data = {
        'comment_id': data.get('id', ''),
        'body': data.get('body', '') or '',
        'author': data.get('author') or '[deleted]',
        'upvotes': data.get('score', 0) or 0,
        'timestamp': _isoformat_from_utc(data.get('created_utc')),
        'depth': current_depth,
        'replies': []
    }

    if current_depth >= max_depth:
        return comment_data

    replies = data.get('replies')
    if isinstance(replies, dict):
        reply_children = replies.get('data', {}).get('children', []) or []
        for child in reply_children:
            if len(comment_data['replies']) >= 3:
                break
            parsed_reply = _parse_public_comment_node(child, current_depth + 1, max_depth)
            if parsed_reply:
                comment_data['replies'].append(parsed_reply)

    return comment_data


def fetch_top_comments_public_json(
    session: requests.Session,
    post_id: str,
    max_comments: int,
    depth: int,
    rate_limiter: "RateLimiter",
    timeout_seconds: int,
    retries: int = 4,
    retry_backoff_seconds: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Retrieve top comments from a Reddit post using public JSON endpoints.

    Args:
        session: Requests session
        post_id: Reddit post base36 id
        max_comments: Maximum number of top-level comments to include
        depth: Reply depth to include (1=top-level only)
        rate_limiter: Rate limiter instance
        timeout_seconds: Request timeout in seconds

    Returns:
        List of comment dictionaries matching the collector schema
    """
    comments: List[Dict[str, Any]] = []
    if max_comments <= 0:
        return comments

    try:
        payload = public_reddit_get(
            session=session,
            path=f"comments/{post_id}.json",
            params={
                'sort': 'top',
                'limit': max_comments,
                'depth': max(1, depth),
            },
            rate_limiter=rate_limiter,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )

        if not isinstance(payload, list) or len(payload) < 2:
            return comments

        comment_listing = payload[1]
        children = comment_listing.get('data', {}).get('children', []) or []

        for child in children:
            if len(comments) >= max_comments:
                break
            parsed_comment = _parse_public_comment_node(
                child,
                current_depth=1,
                max_depth=max(1, depth),
            )
            if parsed_comment:
                comments.append(parsed_comment)

    except PublicRedditRateLimitError as e:
        logger.warning("Rate-limited fetching comments for %s via public JSON: %s", post_id, e)
    except PublicRedditCollectorError as e:
        logger.warning("Error fetching comments via public JSON for %s: %s", post_id, e)

    return comments


class RateLimiter:
    """
    Enforces rate limiting for Reddit API calls.

    Tracks request timestamps and sleeps when necessary
    to stay under the configured requests per minute.
    """

    def __init__(self, requests_per_minute: int = 60):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum allowed requests per minute
        """
        self.requests_per_minute = requests_per_minute
        self.request_times: List[float] = []
        self.window_seconds = 60.0

    def wait_if_needed(self) -> None:
        """
        Block if necessary to comply with rate limits.
        Calculates time since oldest request in window and sleeps
        if we would exceed the limit.
        """
        now = time.time()

        # Remove requests older than the window
        self.request_times = [
            t for t in self.request_times
            if now - t < self.window_seconds
        ]

        # If we're at the limit, wait until oldest request expires
        if len(self.request_times) >= self.requests_per_minute:
            oldest = min(self.request_times)
            sleep_time = self.window_seconds - (now - oldest) + 0.1
            if sleep_time > 0:
                logger.info(f"Rate limit reached, waiting {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)

    def record_request(self) -> None:
        """Record that a request was made at current time."""
        self.request_times.append(time.time())


def get_time_filter(time_range: str) -> str:
    """
    Convert time_range config to Reddit API time filter.

    Args:
        time_range: One of 'day', 'week', 'month', 'year', 'all'

    Returns:
        Valid Reddit time filter string
    """
    valid_filters = ['hour', 'day', 'week', 'month', 'year', 'all']
    if time_range.lower() in valid_filters:
        return time_range.lower()
    return 'week'


def search_posts_for_phrase(
    reddit: Any,
    phrase: str,
    config: dict,
    rate_limiter: RateLimiter
) -> List[Dict[str, Any]]:
    """
    Search Reddit for posts matching a key phrase.

    Args:
        reddit: Authenticated PRAW Reddit client
        phrase: Search phrase to find
        config: Search configuration parameters
        rate_limiter: RateLimiter instance for API compliance

    Returns:
        List of post dictionaries matching criteria
    """
    search_config = config.get('search', {})
    filter_config = config.get('filters', {})

    max_posts = search_config.get('max_posts_per_phrase', 50)
    min_upvotes = search_config.get('min_upvotes', 5)
    time_range = get_time_filter(search_config.get('time_range', 'week'))
    comment_depth = search_config.get('comment_depth', 2)
    max_comments = search_config.get('max_comments_per_post', 10)

    allowed_languages = filter_config.get('languages', [])
    allowed_regions = filter_config.get('regions', [])

    posts = []

    logger.info(f"Searching for phrase: '{phrase}'")

    try:
        # Wait for rate limit
        rate_limiter.wait_if_needed()
        rate_limiter.record_request()

        # Search all of Reddit
        search_results = reddit.subreddit('all').search(
            phrase,
            sort='relevance',
            time_filter=time_range,
            limit=max_posts * 2  # Fetch extra to account for filtering
        )

        for submission in search_results:
            # Rate limit each submission access
            rate_limiter.wait_if_needed()
            rate_limiter.record_request()

            # Filter by upvotes
            if submission.score < min_upvotes:
                continue

            # Combine title and text for analysis
            post_text = f"{submission.title} {submission.selftext or ''}"

            # Detect language
            detected_language = detect_language(post_text)

            # Filter by language if specified
            if allowed_languages and detected_language not in allowed_languages:
                if detected_language != 'unknown':  # Allow unknown through
                    continue

            # Detect region
            flair = submission.link_flair_text if hasattr(submission, 'link_flair_text') else None
            region_info = detect_region(submission.subreddit.display_name, flair, post_text)
            poster_region = region_info["poster_region"]
            topic_region = region_info["topic_region"]

            # Filter by region if specified
            if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
                continue

            # Fetch comments
            comments = (
                fetch_top_comments(submission, max_comments, comment_depth)
                if max_comments > 0 else []
            )

            # Build post data
            post_age_hours = round((time.time() - submission.created_utc) / 3600, 1)
            comment_to_upvote_ratio = round(submission.num_comments / max(submission.score, 1), 3)

            # Author karma (PRAW only)
            author_karma = 0
            try:
                if submission.author:
                    author_karma = submission.author.link_karma + submission.author.comment_karma
            except Exception:
                pass

            post_data = {
                'post_id': submission.id,
                'phrase_match': phrase,
                'title': submission.title,
                'text': submission.selftext or '',
                'subreddit': submission.subreddit.display_name,
                'community_name': submission.subreddit.display_name,
                'community_kind': 'forum',
                'source_platform': 'reddit',
                'author': str(submission.author) if submission.author else '[deleted]',
                'upvotes': submission.score,
                'comments': submission.num_comments,
                'url': f"https://reddit.com{submission.permalink}",
                'timestamp': datetime.utcfromtimestamp(submission.created_utc).isoformat(),
                'detected_language': detected_language,
                'detected_region': poster_region,
                'poster_region': poster_region,
                'topic_region': topic_region,
                'top_comments': comments,
                'upvote_ratio': getattr(submission, 'upvote_ratio', 0),
                'total_awards': getattr(submission, 'total_awards_received', 0) or 0,
                'link_flair_text': flair or '',
                'is_crosspost': bool(getattr(submission, 'crosspost_parent', None)),
                'crosspost_subreddit': submission.crosspost_parent_list[0].subreddit.display_name if getattr(submission, 'crosspost_parent_list', None) else '',
                'post_age_hours': post_age_hours,
                'comment_to_upvote_ratio': comment_to_upvote_ratio,
                'author_karma': author_karma,
            }

            posts.append(post_data)
            logger.debug(f"Collected post: {submission.id} from r/{submission.subreddit.display_name}")

            # Stop if we have enough posts
            if len(posts) >= max_posts:
                break

        logger.info(f"Collected {len(posts)} posts for phrase: '{phrase}'")

    except Exception as e:
        logger.error(f"Error searching for phrase '{phrase}': {e}")

    return posts


def search_posts_for_phrase_public_rss(
    session: requests.Session,
    phrase: str,
    config: dict,
    rate_limiter: "RateLimiter",
) -> List[Dict[str, Any]]:
    """
    RSS/Atom fallback for Reddit collection when `search.json` is blocked.

    This mode keeps the pipeline working without official API credentials, but
    Reddit RSS does not consistently expose vote/comment counts or top comments.
    """
    search_config = config.get('search', {})
    filter_config = config.get('filters', {})

    max_posts = search_config.get('max_posts_per_phrase', 50)
    min_upvotes = search_config.get('min_upvotes', 5)
    time_range = get_time_filter(search_config.get('time_range', 'week'))
    timeout_seconds = get_public_request_timeout(config)
    retries = get_public_request_retries(config)
    retry_backoff_seconds = get_public_retry_backoff_seconds(config)

    allowed_languages = filter_config.get('languages', [])
    allowed_regions = filter_config.get('regions', [])

    logger.info("Searching (RSS fallback) for phrase: '%s'", phrase)

    feed_xml = public_reddit_get_text(
        session=session,
        path="search.rss",
        params={
            'q': phrase,
            'sort': 'relevance',
            't': time_range,
            'limit': min(RSS_SAFE_RESULT_CAP, max(1, max_posts * 2)),
        },
        rate_limiter=rate_limiter,
        timeout_seconds=timeout_seconds,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )

    rss_rows = parse_reddit_search_rss(feed_xml)
    posts: List[Dict[str, Any]] = []

    if min_upvotes > 0 and rss_rows:
        logger.warning(
            "RSS fallback does not expose reliable vote counts; skipping min_upvotes=%d filter for phrase '%s'.",
            min_upvotes,
            phrase,
        )

    for submission in rss_rows:
        title = submission.get('title', '') or ''
        selftext = submission.get('text', '') or ''
        post_text = f"{title} {selftext}".strip()

        detected_language = detect_language(post_text)
        if allowed_languages and detected_language not in allowed_languages:
            if detected_language != 'unknown':
                continue

        subreddit_name = submission.get('subreddit', 'unknown') or 'unknown'
        region_info = detect_region(subreddit_name, None, post_text)
        poster_region = region_info["poster_region"]
        topic_region = region_info["topic_region"]
        if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
            continue

        posts.append({
            'post_id': submission.get('post_id', ''),
            'phrase_match': phrase,
            'title': title,
            'text': selftext,
            'subreddit': subreddit_name,
            'community_name': subreddit_name,
            'community_kind': 'forum',
            'source_platform': 'reddit',
            'author': submission.get('author') or '[deleted]',
            'upvotes': 0,   # unavailable in RSS search feed
            'comments': 0,  # unavailable in RSS search feed
            'url': submission.get('url', ''),
            'timestamp': submission.get('timestamp') or datetime.utcnow().isoformat(),
            'detected_language': detected_language,
            'detected_region': poster_region,
            'poster_region': poster_region,
            'topic_region': topic_region,
            'top_comments': [],
        })

        if len(posts) >= max_posts:
            break

    logger.info("Collected %d posts for phrase (RSS fallback): '%s'", len(posts), phrase)
    return posts


def search_posts_for_phrase_public_json(
    session: requests.Session,
    phrase: str,
    config: dict,
    rate_limiter: "RateLimiter",
    raise_on_error: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search Reddit posts using public JSON endpoints (no API keys).

    Args:
        session: Requests session configured for Reddit
        phrase: Search phrase to find
        config: Search configuration parameters
        rate_limiter: RateLimiter instance for request throttling

    Returns:
        List of post dictionaries matching the collector schema
    """
    search_config = config.get('search', {})
    filter_config = config.get('filters', {})

    max_posts = search_config.get('max_posts_per_phrase', 50)
    min_upvotes = search_config.get('min_upvotes', 5)
    time_range = get_time_filter(search_config.get('time_range', 'week'))
    comment_depth = search_config.get('comment_depth', 2)
    max_comments = search_config.get('max_comments_per_post', 10)
    timeout_seconds = get_public_request_timeout(config)
    retries = get_public_request_retries(config)
    retry_backoff_seconds = get_public_retry_backoff_seconds(config)

    allowed_languages = filter_config.get('languages', [])
    allowed_regions = filter_config.get('regions', [])

    posts: List[Dict[str, Any]] = []
    logger.info("Searching (public JSON) for phrase: '%s'", phrase)

    try:
        target_fetch = max(1, max_posts * 2)
        fetched_children: List[Dict[str, Any]] = []
        after: Optional[str] = None

        while len(fetched_children) < target_fetch:
            remaining = target_fetch - len(fetched_children)
            batch_limit = min(100, max(1, remaining))

            payload = public_reddit_get(
                session=session,
                path="search.json",
                params={
                    'q': phrase,
                    'sort': 'relevance',
                    't': time_range,
                    'limit': batch_limit,
                    'type': 'link',
                    'after': after,
                    'include_over_18': 'on',
                    'restrict_sr': 0,
                },
                rate_limiter=rate_limiter,
                timeout_seconds=timeout_seconds,
                retries=retries,
                retry_backoff_seconds=retry_backoff_seconds,
            )

            listing_data = (payload or {}).get('data', {}) if isinstance(payload, dict) else {}
            children = listing_data.get('children', []) or []

            if not children:
                break

            fetched_children.extend(children)
            after = listing_data.get('after')
            if not after:
                break

        for child in fetched_children:
            if not isinstance(child, dict) or child.get('kind') != 't3':
                continue

            submission = child.get('data', {}) or {}

            # Filter by upvotes
            if (submission.get('score') or 0) < min_upvotes:
                continue

            title = submission.get('title', '') or ''
            selftext = submission.get('selftext', '') or ''
            post_text = f"{title} {selftext}".strip()

            detected_language = detect_language(post_text)

            # Filter by language if specified
            if allowed_languages and detected_language not in allowed_languages:
                if detected_language != 'unknown':  # Allow unknown through
                    continue

            subreddit_name = submission.get('subreddit', 'unknown') or 'unknown'
            flair = submission.get('link_flair_text')
            region_info = detect_region(subreddit_name, flair, post_text)
            poster_region = region_info["poster_region"]
            topic_region = region_info["topic_region"]
            if allowed_regions and poster_region not in allowed_regions and topic_region not in allowed_regions:
                continue

            post_id = submission.get('id')
            if not post_id:
                continue

            comments = []
            if max_comments > 0:
                comments = fetch_top_comments_public_json(
                    session=session,
                    post_id=post_id,
                    max_comments=max_comments,
                    depth=comment_depth,
                    rate_limiter=rate_limiter,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                )

            permalink = submission.get('permalink', '') or ''
            url = permalink if permalink.startswith('http') else f"https://reddit.com{permalink}"

            created_utc_disc = submission.get('created_utc')
            post_age_hours_disc = 0
            if created_utc_disc:
                try:
                    post_age_hours_disc = round((time.time() - float(created_utc_disc)) / 3600, 1)
                except (TypeError, ValueError):
                    pass

            num_comments_disc = submission.get('num_comments', 0) or 0
            score_disc = submission.get('score', 0) or 0
            comment_to_upvote_ratio_disc = round(num_comments_disc / max(score_disc, 1), 3)

            post_data = {
                'post_id': post_id,
                'phrase_match': phrase,
                'title': title,
                'text': selftext,
                'subreddit': subreddit_name,
                'community_name': subreddit_name,
                'community_kind': 'forum',
                'source_platform': 'reddit',
                'author': submission.get('author') or '[deleted]',
                'upvotes': score_disc,
                'comments': num_comments_disc,
                'url': url,
                'timestamp': _isoformat_from_utc(created_utc_disc),
                'detected_language': detected_language,
                'detected_region': poster_region,
                'poster_region': poster_region,
                'topic_region': topic_region,
                'top_comments': comments,
                'upvote_ratio': submission.get('upvote_ratio', 0),
                'total_awards': submission.get('total_awards_received', 0) or 0,
                'link_flair_text': flair or '',
                'is_crosspost': bool(submission.get('crosspost_parent')),
                'crosspost_subreddit': (submission.get('crosspost_parent_list', [{}]) or [{}])[0].get('subreddit', '') if submission.get('crosspost_parent') else '',
                'post_age_hours': post_age_hours_disc,
                'comment_to_upvote_ratio': comment_to_upvote_ratio_disc,
            }

            posts.append(post_data)
            logger.debug("Collected post (public JSON): %s from r/%s", post_id, subreddit_name)

            if len(posts) >= max_posts:
                break

        logger.info("Collected %d posts for phrase (public JSON): '%s'", len(posts), phrase)

    except PublicRedditRateLimitError as e:
        logger.error("Rate-limited searching for phrase '%s' via public JSON: %s", phrase, e)
        try:
            rss_posts = search_posts_for_phrase_public_rss(session, phrase, config, rate_limiter)
            if rss_posts:
                logger.info(
                    "Recovered phrase '%s' via RSS fallback after public JSON rate limit (%d posts)",
                    phrase,
                    len(rss_posts),
                )
                return rss_posts
        except Exception as rss_error:
            logger.error("RSS fallback also failed for phrase '%s': %s", phrase, rss_error)
        if raise_on_error:
            raise
    except PublicRedditCollectorError as e:
        logger.error("Public JSON search failed for phrase '%s': %s", phrase, e)
        try:
            rss_posts = search_posts_for_phrase_public_rss(session, phrase, config, rate_limiter)
            if rss_posts:
                logger.info(
                    "Recovered phrase '%s' via RSS fallback after public JSON failure (%d posts)",
                    phrase,
                    len(rss_posts),
                )
                return rss_posts
        except Exception as rss_error:
            logger.error("RSS fallback also failed for phrase '%s': %s", phrase, rss_error)
        if raise_on_error:
            raise
    except Exception as e:
        logger.error("Error searching for phrase '%s' via public JSON: %s", phrase, e)
        try:
            rss_posts = search_posts_for_phrase_public_rss(session, phrase, config, rate_limiter)
            if rss_posts:
                logger.info(
                    "Recovered phrase '%s' via RSS fallback after unexpected public JSON error (%d posts)",
                    phrase,
                    len(rss_posts),
                )
                return rss_posts
        except Exception as rss_error:
            logger.error("RSS fallback also failed for phrase '%s': %s", phrase, rss_error)
        if raise_on_error:
            raise

    return posts


def _phrase_list_from_post(post: Dict[str, Any]) -> List[str]:
    """Return normalized ordered list of matched phrases from a post record."""
    phrases: List[str] = []
    raw_list = post.get('phrase_matches')
    if isinstance(raw_list, list):
        for phrase in raw_list:
            if isinstance(phrase, str):
                cleaned = phrase.strip()
                if cleaned and cleaned not in phrases:
                    phrases.append(cleaned)

    primary = post.get('phrase_match')
    if isinstance(primary, str):
        cleaned = primary.strip()
        if cleaned and cleaned not in phrases:
            phrases.insert(0, cleaned)

    return phrases


def _get_post_source_platform(post: Dict[str, Any]) -> str:
    """
    Infer source platform for a post record.

    Prefers explicit `source_platform`, with a fallback for legacy X data that
    used `subreddit=twitter_x`.
    """
    source = post.get('source_platform')
    if isinstance(source, str) and source.strip():
        return source.strip().lower()

    subreddit = str(post.get('subreddit', '') or '').strip().lower()
    if subreddit == 'twitter_x':
        return 'x'

    return 'reddit'


def _dedupe_key_for_post(post: Dict[str, Any]) -> str:
    """
    Build a dedupe key that is safe across multiple platforms.

    Uses `source_platform + post_id` so Reddit and X ids cannot collide.
    """
    post_id = str(post.get('post_id', '') or '').strip()
    if not post_id:
        return ''
    source = _get_post_source_platform(post)
    return f"{source}:{post_id}"


def _merge_phrase_matches(existing: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """Merge phrase attribution from duplicate post records."""
    merged_phrases: List[str] = []
    for post in (existing, incoming):
        for phrase in _phrase_list_from_post(post):
            if phrase not in merged_phrases:
                merged_phrases.append(phrase)

    if merged_phrases:
        existing['phrase_match'] = merged_phrases[0]
        existing['phrase_matches'] = merged_phrases


def _merge_comments(existing_comments: List[Dict[str, Any]], new_comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge comment lists by comment_id while preserving first-seen order."""
    merged: List[Dict[str, Any]] = []
    seen_ids = set()

    for comment in (existing_comments or []) + (new_comments or []):
        if not isinstance(comment, dict):
            continue
        comment_id = comment.get('comment_id')
        key = str(comment_id) if comment_id else None
        if key and key in seen_ids:
            continue
        if key:
            seen_ids.add(key)
        merged.append(comment)

    return merged


def merge_duplicate_post_records(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge duplicate records for the same Reddit post id.

    Preserves schema compatibility while tracking multiple matched phrases.
    """
    _merge_phrase_matches(existing, incoming)

    for key in ('upvotes', 'comments'):
        try:
            existing[key] = max(int(existing.get(key, 0) or 0), int(incoming.get(key, 0) or 0))
        except (TypeError, ValueError):
            pass

    for key in ('title', 'text', 'author', 'url', 'timestamp', 'subreddit',
                'detected_language', 'detected_region', 'poster_region',
                'topic_region', 'source_platform',
                'community_name', 'community_kind'):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]

    existing['top_comments'] = _merge_comments(
        existing.get('top_comments', []),
        incoming.get('top_comments', []),
    )

    return existing


def deduplicate_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate collected posts by `post_id` and merge phrase attribution.

    Args:
        posts: Raw collected post list (may contain duplicates across phrases)

    Returns:
        Deduplicated post list preserving original order of first occurrence
    """
    deduped: List[Dict[str, Any]] = []
    index_by_post_id: Dict[str, int] = {}
    duplicate_count = 0

    for post in posts:
        if not isinstance(post, dict):
            continue

        key = _dedupe_key_for_post(post)
        if not key:
            deduped.append(post)
            continue

        if key not in index_by_post_id:
            # Normalize phrase_matches for downstream use (while keeping phrase_match)
            normalized_phrases = _phrase_list_from_post(post)
            if normalized_phrases:
                post['phrase_match'] = normalized_phrases[0]
                post['phrase_matches'] = normalized_phrases
            if not post.get('source_platform'):
                post['source_platform'] = _get_post_source_platform(post)
            if not post.get('community_name'):
                post['community_name'] = post.get('subreddit', 'unknown')
            if not post.get('community_kind'):
                post['community_kind'] = 'forum' if post.get('source_platform') == 'reddit' else 'social'
            index_by_post_id[key] = len(deduped)
            deduped.append(post)
            continue

        duplicate_count += 1
        existing = deduped[index_by_post_id[key]]
        merge_duplicate_post_records(existing, post)

    if duplicate_count:
        logger.info(
            "Deduplicated %d duplicate post records (%d -> %d unique posts)",
            duplicate_count,
            len(posts),
            len(deduped),
        )

    return deduped


def filter_irrelevant_posts(
    posts: List[Dict[str, Any]],
    phrases: List[str],
    min_keyword_density: float = 0.35,
) -> List[Dict[str, Any]]:
    """
    Drop posts where the search phrase matched only incidentally.

    Uses a simple keyword-density heuristic: at least one of the search
    phrase words must appear in the title or body with a minimum frequency
    relative to total word count. This removes conspiracy theories,
    fan-fiction, and gaming posts that happen to contain a matching term.

    Args:
        posts: Deduplicated post list.
        phrases: The original search phrases.
        min_keyword_density: Minimum fraction of phrase-words that must
            appear in the post text (0-1). Default 0.35 = at least 35%
            of phrase keywords found (raised from 0.15 to reduce noise).

    Returns:
        Filtered post list.
    """
    if not phrases:
        return posts

    # Build a set of canonical keyword tokens from all phrases
    phrase_keywords: set = set()
    for phrase in phrases:
        for word in re.split(r'\W+', phrase.lower()):
            if len(word) >= 3:  # skip tiny words like "of", "in"
                phrase_keywords.add(word)

    if not phrase_keywords:
        return posts

    kept: List[Dict[str, Any]] = []
    dropped = 0
    for post in posts:
        if not isinstance(post, dict):
            kept.append(post)
            continue

        # Combine title + body for matching
        text = (
            (post.get('title') or '') + ' ' + (post.get('text') or '')
        ).lower()
        text_words = set(re.split(r'\W+', text))

        hits = phrase_keywords & text_words
        density = len(hits) / len(phrase_keywords) if phrase_keywords else 0

        # For multi-word phrases, require at least 2 keyword matches
        min_hits = 2 if len(phrase_keywords) >= 3 else 1
        if density >= min_keyword_density and len(hits) >= min_hits:
            kept.append(post)
        else:
            dropped += 1

    if dropped:
        logger.info(
            "Relevance filter dropped %d/%d posts (keyword density < %.0f%%)",
            dropped, len(posts), min_keyword_density * 100,
        )

    return kept


def collect_all_posts(config: dict, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Main collection function - fetches posts for all configured phrases.

    Args:
        config: Full configuration dictionary
        dry_run: If True, limit to 10 posts total for testing

    Returns:
        List of all collected posts with full metadata
    """
    provider_candidates = get_collection_provider_candidates(config)
    primary_provider = provider_candidates[0]
    logger.info("Reddit collection providers (in order): %s", " -> ".join(provider_candidates))

    reddit = None
    session = None

    # Initialize rate limiter
    rate_limit = get_effective_reddit_rate_limit(config, primary_provider)
    rate_limiter = RateLimiter(rate_limit)

    # Get search phrases
    phrases = resolve_search_phrases(config, platform='reddit')
    if not phrases:
        logger.warning("No search phrases resolved. Configure search.key_phrases or search.topic (+ search.auto_expand).")
        return []
    logger.info("Resolved %d Reddit search phrase(s)", len(phrases))

    all_posts = []

    def _ensure_provider_client(provider_name: str) -> None:
        nonlocal reddit, session
        if provider_name == 'praw' and reddit is None:
            reddit = create_reddit_client(config)
        if provider_name == 'public_json' and session is None:
            session = create_public_reddit_session(config)

    discovery_cfg = _get_discovery_config(config)
    use_discovery = discovery_cfg['enabled'] and primary_provider == 'public_json'

    def _search_phrase_with_provider(phrase_value: str, provider_name: str) -> List[Dict[str, Any]]:
        _ensure_provider_client(provider_name)

        if provider_name == 'praw':
            return search_posts_for_phrase(reddit, phrase_value, config, rate_limiter)

        # Smart subreddit discovery: search targeted communities first
        if use_discovery:
            _ensure_provider_client('public_json')
            discovered = discover_relevant_subreddits(session, phrase_value, config, rate_limiter)

            if discovered:
                search_cfg = config.get('search', {})
                max_total = search_cfg.get('max_posts_per_phrase', 50)
                # Distribute posts across discovered subreddits
                per_sub = max(5, max_total // len(discovered))

                targeted_posts: List[Dict[str, Any]] = []
                for sub_info in discovered:
                    sub_posts = search_subreddit_posts_public_json(
                        session, phrase_value, sub_info['name'],
                        config, rate_limiter, max_posts=per_sub,
                    )
                    targeted_posts.extend(sub_posts)
                    logger.info(
                        "r/%s: found %d posts for '%s'",
                        sub_info['name'], len(sub_posts), phrase_value,
                    )

                # Also do a supplementary r/all search for breadth (smaller limit)
                all_posts_supplement = search_posts_for_phrase_public_json(
                    session, phrase_value, config, rate_limiter,
                    raise_on_error=False,
                )

                combined = targeted_posts + all_posts_supplement
                combined = deduplicate_posts(combined)

                logger.info(
                    "Discovery collection for '%s': %d targeted + %d r/all = %d unique posts",
                    phrase_value, len(targeted_posts), len(all_posts_supplement), len(combined),
                )
                return combined[:max_total]

        should_raise = len(provider_candidates) > 1
        return search_posts_for_phrase_public_json(
            session,
            phrase_value,
            config,
            rate_limiter,
            raise_on_error=should_raise,
        )

    try:
        for phrase in phrases:
            posts: List[Dict[str, Any]] = []
            last_error: Optional[Exception] = None

            for provider_name in provider_candidates:
                try:
                    posts = _search_phrase_with_provider(phrase, provider_name)
                    if provider_name != primary_provider:
                        logger.info(
                            "Fallback collector '%s' succeeded for phrase '%s' (%d posts)",
                            provider_name,
                            phrase,
                            len(posts),
                        )
                    break
                except PublicRedditCollectorError as e:
                    last_error = e
                    if provider_name != provider_candidates[-1]:
                        logger.warning(
                            "Collector '%s' failed for phrase '%s' (%s). Falling back to '%s'.",
                            provider_name,
                            phrase,
                            e,
                            provider_candidates[provider_candidates.index(provider_name) + 1],
                        )
                        continue
                    raise
                except Exception as e:
                    last_error = e
                    if provider_name != provider_candidates[-1]:
                        logger.warning(
                            "Collector '%s' error for phrase '%s': %s. Trying '%s'.",
                            provider_name,
                            phrase,
                            e,
                            provider_candidates[provider_candidates.index(provider_name) + 1],
                        )
                        continue
                    raise

            if last_error and not posts:
                logger.warning("No posts collected for phrase '%s' after error: %s", phrase, last_error)

            all_posts.extend(posts)
            all_posts = deduplicate_posts(all_posts)

            # Dry run limit
            if dry_run and len(all_posts) >= 10:
                logger.info("Dry run: stopping at 10 posts")
                all_posts = all_posts[:10]
                break
    finally:
        if session is not None:
            session.close()

    # Filter out posts from excluded subreddits (fiction, satire, gaming, etc.)
    exclude_subs = config.get('filters', {}).get('exclude_subreddits', [])
    if exclude_subs:
        exclude_lower = {s.lower() for s in exclude_subs if isinstance(s, str)}
        before_count = len(all_posts)
        all_posts = [
            p for p in all_posts
            if str(p.get('subreddit', '')).lower() not in exclude_lower
        ]
        filtered_count = before_count - len(all_posts)
        if filtered_count > 0:
            logger.info(
                "Subreddit relevance filter removed %d posts from excluded subreddits",
                filtered_count,
            )

    logger.info(f"Total posts collected: {len(all_posts)}")
    return all_posts


def _get_hash_salt() -> str:
    """Return a per-instance salt for username hashing.

    Loaded from the ``SIGNALSTREAM_HASH_SALT`` environment variable.
    If not set, a random salt is generated once and persisted to
    ``<PROJECT_ROOT>/.hash_salt`` (outside the data directory and
    excluded from version control).
    """
    env_salt = os.environ.get("SIGNALSTREAM_HASH_SALT", "").strip()
    if env_salt:
        return env_salt
    salt_path = PROJECT_ROOT / ".hash_salt"
    if salt_path.exists():
        return salt_path.read_text(encoding="utf-8").strip()
    salt = secrets.token_hex(32)
    salt_path.write_text(salt, encoding="utf-8")
    logger.info("Generated new hash salt at %s", salt_path)
    return salt


_HASH_SALT: Optional[str] = None


def _hash_username(username: str) -> str:
    """Hash a username with a per-instance salt for GDPR compliance.

    Preserves [deleted] as-is.
    """
    global _HASH_SALT
    if not username or username == "[deleted]":
        return username
    if _HASH_SALT is None:
        _HASH_SALT = _get_hash_salt()
    return "user_" + hashlib.sha256((_HASH_SALT + username).encode()).hexdigest()[:12]


def _strip_pii_url(url: str) -> str:
    """Remove identifiable URLs from posts for GDPR compliance.

    Keeps the domain for source-attribution but strips the path that could
    identify specific users or posts.
    """
    if not url or not isinstance(url, str):
        return ""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        # Keep scheme + netloc (e.g. "https://reddit.com") for source context
        return f"{parsed.scheme}://{parsed.netloc}/[redacted]"
    except Exception:
        return "[redacted]"


def _anonymize_post_authors(post: Dict[str, Any]) -> Dict[str, Any]:
    """Hash all author fields and strip identifiable URLs at collection time."""
    post["author"] = _hash_username(post.get("author", ""))
    # Strip direct URLs to posts/comments (GDPR: prevents re-identification)
    if "url" in post:
        post["url"] = _strip_pii_url(post.get("url", ""))
    if "permalink" in post:
        post["permalink"] = _strip_pii_url(post.get("permalink", ""))

    for comment in post.get("top_comments", []):
        if isinstance(comment, dict):
            comment["author"] = _hash_username(comment.get("author", ""))
            if "permalink" in comment:
                comment["permalink"] = _strip_pii_url(comment.get("permalink", ""))
            for reply in comment.get("replies", []):
                if isinstance(reply, dict):
                    reply["author"] = _hash_username(reply.get("author", ""))
                    if "permalink" in reply:
                        reply["permalink"] = _strip_pii_url(reply.get("permalink", ""))
    return post


def save_raw_posts(posts: List[Dict[str, Any]], output_dir: str = "data/raw") -> str:
    """
    Save collected posts to JSON file with timestamp.

    Anonymizes usernames (SHA-256 hash) at save time for GDPR compliance,
    and adds a collected_at timestamp to each post for reliable data retention.

    Args:
        posts: List of post dictionaries to save
        output_dir: Directory for output files

    Returns:
        Path to saved JSON file

    File naming: posts_YYYY-MM-DD_HHMMSS.json
    """
    # Ensure directory exists
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f"posts_{timestamp}.json"
    filepath = output_path / filename

    def _clean_text(value: Any) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode('utf-8', errors='replace').decode('utf-8')

    collection_timestamp = datetime.now().isoformat()
    sanitized_posts: List[Dict[str, Any]] = []
    for post in posts:
        if not isinstance(post, dict):
            sanitized_posts.append(post)
            continue

        post_copy = post.copy()
        post_copy['title'] = _clean_text(post_copy.get('title', ''))
        post_copy['text'] = _clean_text(post_copy.get('text', ''))
        post_copy['collected_at'] = collection_timestamp
        _anonymize_post_authors(post_copy)

        top_comments = post_copy.get('top_comments', [])
        if isinstance(top_comments, list):
            cleaned_comments = []
            for comment in top_comments:
                if not isinstance(comment, dict):
                    cleaned_comments.append(comment)
                    continue
                comment_copy = comment.copy()
                comment_copy['body'] = _clean_text(comment_copy.get('body', ''))

                replies = comment_copy.get('replies', [])
                if isinstance(replies, list):
                    cleaned_replies = []
                    for reply in replies:
                        if not isinstance(reply, dict):
                            cleaned_replies.append(reply)
                            continue
                        reply_copy = reply.copy()
                        reply_copy['body'] = _clean_text(reply_copy.get('body', ''))
                        cleaned_replies.append(reply_copy)
                    comment_copy['replies'] = cleaned_replies

                cleaned_comments.append(comment_copy)
            post_copy['top_comments'] = cleaned_comments

        sanitized_posts.append(post_copy)

    # Save to JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(sanitized_posts, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Saved {len(sanitized_posts)} posts to {filepath}")
    return str(filepath)


def main():
    """
    Entry point for standalone collection runs.
    Loads config, collects posts, saves to JSON.
    """
    import argparse

    parser = argparse.ArgumentParser(description='Collect Reddit posts')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--dry-run', action='store_true', help='Limit to 10 posts for testing')
    parser.add_argument('--output', default='data/raw', help='Output directory')
    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config)

        # Collect posts
        posts = collect_all_posts(config, dry_run=args.dry_run)

        if posts:
            # Save to JSON
            filepath = save_raw_posts(posts, args.output)
            print(f"\nCollection complete! Saved to: {filepath}")
        else:
            print("\nNo posts collected. Check your configuration and try again.")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure config.yaml exists. Reddit API credentials are optional in public_json mode.")
    except ValueError as e:
        print(f"Error: Invalid configuration values: {e}")
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        raise


if __name__ == "__main__":
    main()
