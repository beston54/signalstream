"""
PDF Report Generator Module

Creates professional 9-page branded intelligence reports using
WeasyPrint with Jinja2 HTML templates, matplotlib charts, and
optional photography from Unsplash/Pexels.
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import string
import re

# Try to import dependencies, provide helpful errors if missing
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("Please install jinja2: pip install jinja2")
    raise

try:
    from weasyprint import HTML, CSS
except ImportError:
    print("Please install weasyprint: pip install weasyprint")
    print("On macOS, you may also need: brew install cairo pango gdk-pixbuf libffi")
    raise

# Add script directory to path for sibling imports
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from .config_utils import load_config_file
except ImportError:
    from config_utils import load_config_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _resolve_project_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


class UsernameAnonymizer:
    """
    Replaces Reddit usernames with anonymous identifiers.
    Maintains consistent mapping within a report.
    """

    def __init__(self):
        self.mapping: Dict[str, str] = {}
        self.counter = 0

    def anonymize(self, username: str) -> str:
        """
        Replace username with anonymous identifier.

        Args:
            username: Original Reddit username

        Returns:
            Anonymous identifier like "User A", "User B", etc.
        """
        if not username or username in ['[deleted]', 'deleted', 'AutoModerator']:
            return username

        if username not in self.mapping:
            letter = self._get_letter(self.counter)
            self.mapping[username] = f"User {letter}"
            self.counter += 1

        return self.mapping[username]

    def _get_letter(self, index: int) -> str:
        """Convert index to letter sequence (A, B, ... Z, AA, AB, ...)"""
        letters = string.ascii_uppercase
        result = ""
        index += 1
        while index > 0:
            index -= 1
            result = letters[index % 26] + result
            index //= 26
        return result


def anonymize_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Anonymize all usernames in a list of posts.

    Args:
        posts: List of post dictionaries

    Returns:
        Posts with anonymized usernames
    """
    anonymizer = UsernameAnonymizer()
    anonymized = []

    for post in posts:
        anon_post = post.copy()
        anon_post['author'] = anonymizer.anonymize(post.get('author', ''))

        if 'top_comments' in anon_post:
            anon_comments = []
            for comment in anon_post['top_comments']:
                anon_comment = comment.copy()
                anon_comment['author'] = anonymizer.anonymize(
                    comment.get('author', ''))

                if 'replies' in anon_comment:
                    anon_replies = []
                    for reply in anon_comment['replies']:
                        anon_reply = reply.copy()
                        anon_reply['author'] = anonymizer.anonymize(
                            reply.get('author', ''))
                        anon_replies.append(anon_reply)
                    anon_comment['replies'] = anon_replies

                anon_comments.append(anon_comment)
            anon_post['top_comments'] = anon_comments

        anonymized.append(anon_post)

    return anonymized


def _sanitize_phrase(phrase: str) -> str:
    """Strip raw boolean query syntax from a phrase for client-facing display.

    Converts e.g. ``raw:(Europe OR European OR EU) (interconnector OR HVDC)``
    into a clean readable label like ``Europe European EU interconnector HVDC``.
    """
    text = str(phrase or "")
    # Remove "raw:" prefix
    text = re.sub(r"^raw:\s*", "", text, flags=re.IGNORECASE)
    # Remove boolean operators
    text = re.sub(r"\b(OR|AND|NOT)\b", " ", text)
    # Remove parentheses and quotes
    text = re.sub(r"[()\"']", " ", text)
    # Remove Twitter/X search operators like -is:retweet, from:, min_faves:, etc.
    text = re.sub(r"-?\w+:\w+", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Title-case the result for readability
    if text:
        text = text.title()
    return text or phrase


def _format_date_human(iso_str: str) -> str:
    """Convert ISO date string to human-readable format: 'Feb 6, 2026'."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str[:10])
        return dt.strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return iso_str[:10]


def _sanitize_llm_output(text: str) -> str:
    """Clean common LLM output artifacts from text before rendering.

    Strips trailing numbers, stray punctuation sequences, and normalizes whitespace.
    """
    if not text:
        return text
    # Strip trailing bare numbers (e.g. "Theme Name - 84.")
    text = re.sub(r'\s*[-–]\s*\d+\.?\s*$', '', text).strip()
    # Strip trailing stray punctuation (.,  ;,  etc.)
    text = re.sub(r'[.,;:\s]+$', '', text).strip()
    # Strip leading stray punctuation
    text = re.sub(r'^[.,;:\-\*\s]+', '', text).strip()
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    return text


def _compact_text(value: Any, max_len: int = 150) -> str:
    """Normalize whitespace and trim text for compact visual overlays.

    Prefers cutting at sentence/clause boundaries (. ! ? ; ,) to avoid
    mid-word or mid-sentence truncation.
    """
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text

    # Try to find the last sentence boundary (. ! ?) before the limit
    search_region = text[:max_len]
    sentence_boundary = None
    clause_boundary = None
    for match in re.finditer(r'[.!?]\s', search_region):
        if match.end() > max_len * 0.4:
            sentence_boundary = match.start() + 1  # include the punctuation
    # Fall back to clause boundary (; ,) only if no sentence boundary found
    if not sentence_boundary:
        for match in re.finditer(r'[;,]\s', search_region):
            if match.end() > max_len * 0.4:
                clause_boundary = match.start() + 1

    boundary = sentence_boundary or clause_boundary
    if boundary and boundary > max_len * 0.4:
        return text[:boundary].strip()

    # Fall back to word boundary
    clipped = text[:max_len].rsplit(" ", 1)
    if len(clipped) > 1 and len(clipped[0]) > max_len * 0.6:
        result = clipped[0].strip()
    else:
        result = text[:max_len].strip()
    return result.rstrip(" ,.;:") + "..."


def _first_sentence(value: Any, max_len: int = 180) -> str:
    """Return the first sentence-like segment, trimmed to max_len."""
    text = _compact_text(value, max_len=max_len * 2)
    if not text:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", text)
    if match:
        return _compact_text(match.group(1), max_len=max_len)
    return _compact_text(text, max_len=max_len)


def _short_theme_name(name: str) -> str:
    """Return the clean label before the first ' - ' in an LLM theme string.

    e.g. 'US Military Intervention - Concerns about...' → 'US Military Intervention'
    """
    if not name:
        return name
    return name.split(" - ")[0].strip()


def _dominant_sentiment_label(statistics: Dict[str, Any]) -> str:
    sentiment = statistics.get("sentiment_distribution", {}) or {}
    if not sentiment:
        return "Mixed"
    dominant = max(sentiment, key=sentiment.get)
    return str(dominant).capitalize()


def _top_region_label(statistics: Dict[str, Any]) -> str:
    regions = statistics.get("region_breakdown", {}) or {}
    if not regions:
        return ""
    return str(max(regions, key=regions.get))


def _top_theme_entry(themes_by_phrase: Dict[str, Dict[str, Any]]) -> Optional[tuple]:
    if not themes_by_phrase:
        return None

    items = list(themes_by_phrase.items())

    def _score(item: tuple) -> int:
        _phrase, theme_data = item
        try:
            return int(theme_data.get("post_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    items.sort(key=_score, reverse=True)
    return items[0]


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _humanize_community(name: str) -> str:
    """Convert raw subreddit/community names to human-readable labels.

    'neoliberal' -> 'r/neoliberal'
    'twitter_x' -> 'X (Twitter)'
    'PopularCultureZone' -> 'r/PopularCultureZone'
    """
    if not name:
        return name
    if name == "twitter_x":
        return "X (Twitter)"
    if name.startswith("r/"):
        return name
    # CamelCase or snake_case -> add r/ prefix for Reddit communities
    return f"r/{name}"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_suitable_quote(text: str) -> bool:
    """Filter out quotes that are inflammatory, conspiratorial, or unprofessional.

    Returns True if the quote is suitable for a client-facing report.
    """
    if not text or len(text) < 20:
        return False
    lowered = text.lower()
    # Reject text containing common conspiracy/inflammatory markers
    disqualifying_patterns = [
        'conspiracy theor', 'false flag', 'deep state', 'new world order',
        'plandemic', 'wake up sheeple', 'they don\'t want you to know',
        'kill ', 'death to ', 'exterminate',
        'soros', 'illuminati', 'qanon', 'psyop', 'controlled opposition',
        'f**k', 'fuck', 'shit', 'stfu', 'gtfo',
        'retard', 'libtard', 'cuck',
    ]
    for pattern in disqualifying_patterns:
        if pattern in lowered:
            return False
    # Reject ALL CAPS text (shouting)
    alpha_chars = [c for c in text if c.isalpha()]
    if len(alpha_chars) > 20 and sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.7:
        return False
    return True


# Subreddits that should never supply a featured quote
_FRINGE_SUBREDDITS = frozenset({
    'conspiracy', 'conspiracytheories', 'conspiracycommons',
    'conspiracynopol', 'highstrangeness', 'aliens', 'ufos',
    'tankiethedeprogram', 'wayofthebern', 'worldbuilding',
    'hoi4modding', 'gundamfanfic', 'starwarstheories',
})


def _is_suitable_quote_source(post: Dict[str, Any]) -> bool:
    """Check that a post's community is acceptable for a featured quote."""
    community = (post.get('subreddit') or post.get('community', '')).lower()
    return community not in _FRINGE_SUBREDDITS


def _engagement_sort_key(post: Dict[str, Any]) -> tuple:
    """Rank posts by a simple engagement proxy and confidence quality."""
    upvotes = _safe_int(post.get("upvotes", 0))
    comments = _safe_int(post.get("comments", 0))
    raw_signal = upvotes + int(round(0.5 * comments))

    analysis = post.get("sentiment_analysis", {}) or {}
    confidence = str(analysis.get("confidence", "") or "").strip().lower()
    confidence_rank = {"certain": 2, "questioning": 1, "uncertain": 0}.get(confidence, 0)

    return (raw_signal, confidence_rank, upvotes, comments)


def _valid_key_point_from_post(post: Dict[str, Any]) -> str:
    """Return a usable post-level KEY_POINT sentence, or empty string."""
    analysis = post.get("sentiment_analysis", {}) or {}
    key_point = analysis.get("key_point")
    if not isinstance(key_point, str):
        return ""

    text = key_point.strip()
    if len(text) < 12:
        return ""

    lowered = text.lower()
    invalid_prefixes = (
        "analysis failed",
        "analysis error",
        "unable to extract key point",
    )
    if lowered.startswith(invalid_prefixes):
        return ""

    # KEY_POINT is expected to be one sentence; we keep the exact text content.
    return text


def _post_matches_phrase(post: Dict[str, Any], phrase: str) -> bool:
    if not phrase:
        return False

    target = phrase.strip().lower()
    if not target:
        return False

    primary = str(post.get("phrase_match", "") or "").strip().lower()
    if primary == target:
        return True

    phrase_matches = post.get("phrase_matches")
    if isinstance(phrase_matches, list):
        for item in phrase_matches:
            if isinstance(item, str) and item.strip().lower() == target:
                return True

    return False


def _build_quote_meta(post: Dict[str, Any]) -> str:
    """Build a short, non-identifying attribution line for overlay quotes."""
    parts: List[str] = []

    community = str(post.get("community_name") or post.get("subreddit") or "").strip()
    if community:
        parts.append(f"r/{community}")

    analysis = post.get("sentiment_analysis", {}) or {}
    sentiment = str(analysis.get("sentiment", "") or "").strip().lower()
    if sentiment and sentiment not in {"unknown", "error"}:
        parts.append(f"{sentiment} sentiment")

    confidence = str(analysis.get("confidence", "") or "").strip().lower()
    if confidence and confidence not in {"unknown", "error"}:
        parts.append(f"{confidence} confidence")

    source = str(post.get("source_platform", "") or "").strip().lower()
    if source and source != "reddit":
        parts.append(source.upper() if source == "x" else source.title())

    return " | ".join(parts)


def _select_key_point_quote(
    posts: List[Dict[str, Any]],
    *,
    exclude_post_ids: Optional[set] = None,
    preferred_phrase: Optional[str] = None,
    preferred_sentiments: Optional[tuple] = None,
    required_confidences: Optional[tuple] = None,
    max_length: int = 170,
) -> Optional[Dict[str, str]]:
    """
    Pick an exact post KEY_POINT sentence for image overlays.

    Prefers high-engagement posts and tries to keep quotes short enough to
    remain readable inside fixed-height image overlays.
    """
    exclude_post_ids = exclude_post_ids or set()
    preferred_sentiments_norm = {
        str(s).strip().lower() for s in (preferred_sentiments or tuple()) if str(s).strip()
    }
    required_confidences_norm = {
        str(c).strip().lower() for c in (required_confidences or tuple()) if str(c).strip()
    }

    candidates: List[Dict[str, Any]] = []
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("post_id", "") or "").strip()
        if post_id and post_id in exclude_post_ids:
            continue

        quote = _valid_key_point_from_post(post)
        if not quote:
            continue

        if preferred_phrase and not _post_matches_phrase(post, preferred_phrase):
            continue

        if preferred_sentiments_norm:
            sentiment = str((post.get("sentiment_analysis", {}) or {}).get("sentiment", "") or "").strip().lower()
            if sentiment not in preferred_sentiments_norm:
                continue

        if required_confidences_norm:
            confidence = str((post.get("sentiment_analysis", {}) or {}).get("confidence", "") or "").strip().lower()
            if confidence not in required_confidences_norm:
                continue

        candidates.append(post)

    if not candidates:
        return None

    candidates.sort(key=_engagement_sort_key, reverse=True)

    best_any = None
    for post in candidates:
        quote = _valid_key_point_from_post(post)
        meta = _build_quote_meta(post)
        payload = {
            "post_id": str(post.get("post_id", "") or "").strip(),
            "quote": quote,
            "quote_meta": meta,
        }
        if best_any is None:
            best_any = payload
        if len(quote) <= max_length:
            return payload

    return best_any


def _attach_overlay_quote(
    overlay: Dict[str, Any],
    posts: List[Dict[str, Any]],
    *,
    used_post_ids: set,
    preferred_phrase: Optional[str] = None,
    preferred_sentiments: Optional[tuple] = None,
    required_confidences: Optional[tuple] = None,
    max_length: int = 170,
) -> None:
    """Attach a selected exact KEY_POINT quote to an overlay payload."""
    selected = _select_key_point_quote(
        posts,
        exclude_post_ids=used_post_ids,
        preferred_phrase=preferred_phrase,
        preferred_sentiments=preferred_sentiments,
        required_confidences=required_confidences,
        max_length=max_length,
    )
    if not selected:
        return

    quote = selected.get("quote", "")
    if not quote:
        return

    overlay["quote"] = quote
    overlay["quote_meta"] = selected.get("quote_meta", "")
    post_id = selected.get("post_id", "")
    if post_id:
        used_post_ids.add(post_id)


def prepare_photo_overlays(
    posts: List[Dict[str, Any]],
    statistics: Dict[str, Any],
    themes_by_phrase: Dict[str, Dict[str, Any]],
    executive_narrative: str,
    methodology: Dict[str, Any],
    recommendations: Dict[str, Any],
    next_steps: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Build compact overlay copy for photo-first report panels.

    The goal is short, readable language over images (headline + chips + one
    distilled sentence) sourced from actual analysis output.
    """
    overlays: Dict[str, Dict[str, Any]] = {}
    used_quote_post_ids: set = set()

    total_posts = statistics.get("total_posts", 0)
    phrase_count = statistics.get("phrase_count") or len(statistics.get("phrases_analyzed", []) or [])
    venue_count = len(statistics.get("community_breakdown", {}) or statistics.get("subreddit_breakdown", {}) or {})
    dominant_sentiment = _dominant_sentiment_label(statistics)
    top_region = _top_region_label(statistics)

    cover_chips = [
        f"{total_posts} posts" if total_posts else "",
        f"{phrase_count} topics" if phrase_count else "",
        f"{venue_count} venues" if venue_count else "",
        f"{dominant_sentiment} sentiment" if dominant_sentiment else "",
        f"Top region: {top_region}" if top_region else "",
    ]
    top_theme = _top_theme_entry(themes_by_phrase)
    top_theme_names: List[str] = []
    if top_theme:
        _, top_theme_data = top_theme
        _sorted_themes = sorted(
            top_theme_data.get("major_themes", []),
            key=lambda t: t.get("post_count", t.get("percentage", 0)) or 0,
            reverse=True,
        )
        for theme in _sorted_themes[:2]:
            theme_name = _compact_text(theme.get("theme", ""), max_len=34)
            if theme_name:
                top_theme_names.append(theme_name)

    cover_summary = _first_sentence(executive_narrative, max_len=180)
    if not cover_summary and top_theme_names:
        cover_summary = "Key themes center on " + " and ".join(top_theme_names) + "."

    overlays["cover"] = {
        "kicker": "Executive Snapshot",
        "headline": _compact_text(
            f"{dominant_sentiment} conversation across {phrase_count or 'multiple'} topics",
            max_len=74,
        ),
        "summary": cover_summary,
        "chips": [chip for chip in cover_chips if chip][:4],
    }
    _attach_overlay_quote(
        overlays["cover"],
        posts,
        used_post_ids=used_quote_post_ids,
        required_confidences=("certain",),
        max_length=170,
    )

    methodology_steps = [step.get("name", "") for step in (methodology.get("steps", []) or []) if step.get("name")]
    method_notes = methodology.get("notes", []) or []
    method_summary = _first_sentence(method_notes[0] if method_notes else "", max_len=160)
    if not method_summary:
        method_summary = "Public conversations were collected, analyzed locally, and summarized into comparable themes."

    method_chips = methodology_steps[:4]
    model_used = ((methodology.get("scope") or {}).get("model_used") or "").strip()
    source_count = (methodology.get("scope") or {}).get("source_count")
    if source_count:
        method_chips.append(f"{source_count} sources")
    if model_used:
        method_chips.append(_compact_text(model_used, max_len=26))

    overlays["methodology"] = {
        "kicker": "Collection + Analysis Workflow",
        "headline": "Public discussion -> local AI analysis -> theme distillation",
        "summary": method_summary,
        "chips": [_compact_text(chip, max_len=24) for chip in method_chips if chip][:5],
    }
    _attach_overlay_quote(
        overlays["methodology"],
        posts,
        used_post_ids=used_quote_post_ids,
        preferred_sentiments=("positive", "mixed", "neutral"),
        required_confidences=("certain",),
        max_length=120,
    )

    primary_theme_item = _top_theme_entry(themes_by_phrase)
    if primary_theme_item:
        phrase, theme_data = primary_theme_item
        theme_summary = (theme_data.get("sentiment_summary") or {}).get("narrative", "")
        theme_overall = (theme_data.get("sentiment_summary") or {}).get("overall", "")
        major_themes = theme_data.get("major_themes", []) or []
        key_critiques = theme_data.get("key_critiques", []) or []
        regional_patterns = theme_data.get("regional_patterns", {}) or {}

        headline = _first_sentence(theme_summary, max_len=92)
        if not headline:
            top_labels = [t.get("theme", "") for t in major_themes[:2] if t.get("theme")]
            if top_labels:
                headline = _compact_text("Themes focus on " + " and ".join(top_labels), max_len=92)
            else:
                headline = _compact_text(f"Conversation around {phrase} clusters into a few recurring ideas", max_len=92)

        summary_parts: List[str] = []
        if key_critiques:
            summary_parts.append("Critique: " + _compact_text(key_critiques[0].get("critique", ""), max_len=85))
        if regional_patterns:
            region, pattern = next(iter(regional_patterns.items()))
            summary_parts.append(f"{region}: " + _compact_text(pattern, max_len=80))

        chips: List[str] = []
        if phrase:
            chips.append(_compact_text(phrase, max_len=26))
        if theme_overall:
            chips.append(f"{str(theme_overall).capitalize()} sentiment")
        post_count = theme_data.get("post_count")
        if post_count:
            chips.append(f"{post_count} posts")
        for theme in major_themes[:3]:
            label = _compact_text(theme.get("theme", ""), max_len=22)
            pct = theme.get("percentage")
            if label:
                chips.append(f"{label} ({pct}%)" if pct is not None else label)

        overlays["themes"] = {
            "kicker": "Theme Distillate",
            "headline": headline,
            "summary": _compact_text(" | ".join(summary_parts), max_len=190),
            "chips": chips[:5],
        }
        _attach_overlay_quote(
            overlays["themes"],
            posts,
            used_post_ids=used_quote_post_ids,
            preferred_phrase=phrase,
            required_confidences=("certain",),
            max_length=145,
        )

    rec_entries = recommendations.get("entries", []) or []
    next_action = (next_steps[0] if next_steps else {}) or {}
    rec_headline = _compact_text(
        next_action.get("action") or (rec_entries[0].get("title") if rec_entries else "") or "Action priorities derived from recurring community signals",
        max_len=90,
    )
    rec_summary = _first_sentence(
        next_action.get("rationale") or (rec_entries[0].get("description") if rec_entries else ""),
        max_len=170,
    )
    rec_chips = []
    for rec in rec_entries[:3]:
        title = _compact_text(rec.get("title", ""), max_len=30)
        if title:
            rec_chips.append(title)
    if next_action.get("priority"):
        rec_chips.append(f"{str(next_action['priority']).capitalize()} priority")

    overlays["next_steps"] = {
        "kicker": "Action Priority",
        "headline": rec_headline,
        "summary": rec_summary,
        "chips": rec_chips[:4],
    }
    _attach_overlay_quote(
        overlays["next_steps"],
        posts,
        used_post_ids=used_quote_post_ids,
        preferred_sentiments=("negative", "mixed", "neutral"),
        required_confidences=("certain",),
        max_length=120,
    )

    return overlays


def prepare_community_lens_data(statistics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare community-level sentiment view for report rendering.

    Uses the confidence-aware matrices produced by thematic_analyzer to answer:
    "How do different communities feel about this topic?"
    """
    matrix = statistics.get("community_sentiment_matrix", {}) or {}
    analysis_ctx = statistics.get("analysis_context_summary", {}) or {}

    rows: List[Dict[str, Any]] = []
    highlight_quotes: List[Dict[str, Any]] = []
    seen_quote_keys = set()

    for community_name, row in matrix.items():
        total_posts = _safe_int(row.get("total_posts", 0))
        # Suppress communities with fewer than 2 posts — one-off noise
        # communities should never appear in the report
        if total_posts < 2:
            continue

        dominant = str(row.get("dominant_sentiment", "unknown") or "unknown").strip().lower()
        certain_dominant = str(row.get("certain_dominant_sentiment", "unknown") or "unknown").strip().lower()
        source_mix = row.get("source_mix", {}) or {}
        source_mix_str = ", ".join(f"{src}:{count}" for src, count in source_mix.items()) if source_mix else ""

        row_payload = {
            "community": community_name,
            "total_posts": total_posts,
            "dominant_sentiment": dominant,
            "dominant_share_pct": _safe_float(row.get("dominant_sentiment_share_pct", 0.0)),
            "certain_posts": _safe_int(row.get("certain_posts", 0)),
            "certain_share_pct": _safe_float(row.get("certain_share_pct", 0.0)),
            "certain_dominant_sentiment": certain_dominant,
            "certain_dominant_share_pct": _safe_float(row.get("certain_dominant_share_pct", 0.0)),
            "sample_strength": str(row.get("sample_strength", "low") or "low").strip().lower(),
            "source_mix_summary": source_mix_str,
            "sentiment_percentages": row.get("sentiment_percentages", {}) or {},
            "top_key_points": row.get("top_key_points", []) or [],
        }
        rows.append(row_payload)

        for quote in row_payload["top_key_points"][:1]:
            quote_text = _compact_text(quote.get("quote", ""), max_len=170)
            if not quote_text:
                continue
            quote_key = quote_text.lower()
            if quote_key in seen_quote_keys:
                continue
            seen_quote_keys.add(quote_key)
            highlight_quotes.append(
                {
                    "community": community_name,
                    "quote": quote_text,
                    "sentiment": str(quote.get("sentiment", "unknown") or "unknown").lower(),
                    "confidence": str(quote.get("confidence", "unknown") or "unknown").lower(),
                    "engagement_raw": _safe_int(quote.get("engagement_raw", 0)),
                    "source_platform": str(quote.get("source_platform", "") or "").lower(),
                }
            )
            break

    rows.sort(key=lambda item: (-item["total_posts"], item["community"].lower()))
    highlight_quotes = highlight_quotes[:3]

    thread_share = _safe_float(analysis_ctx.get("thread_context_enabled_share_pct", 0.0))
    avg_thread_comments = _safe_float(analysis_ctx.get("avg_thread_comments_used", 0.0))

    certain_posts_total = sum(row["certain_posts"] for row in rows)
    total_posts_total = sum(row["total_posts"] for row in rows)
    certain_share_overall = round((certain_posts_total / total_posts_total) * 100, 1) if total_posts_total > 0 else 0.0

    top_community = rows[0]["community"] if rows else "the largest communities"
    top_community_sent = rows[0]["dominant_sentiment"] if rows else "unknown"
    intro = (
        f"This community lens groups posts by venue and compares overall sentiment with a "
        f"higher-confidence subset (`certain` only). The largest tracked community is {top_community}, "
        f"where the dominant sentiment is {top_community_sent}."
        if rows else
        "This community lens groups posts by venue and compares overall sentiment with a higher-confidence subset (`certain` only)."
    )

    coverage_notes = [
        "Dominant sentiment uses all analyzed posts in each community.",
        "Certain-only sentiment uses only posts where the model confidence was marked `certain`.",
        "Sample strength reflects both total posts and certain-only coverage.",
    ]
    if thread_share > 0:
        coverage_notes.append(
            f"Thread-aware analysis was used for {thread_share}% of posts (avg. {avg_thread_comments} comment snippets included when available)."
        )

    return {
        "intro_narrative": intro,
        "rows": rows,
        "highlight_quotes": highlight_quotes,
        "summary_metrics": {
            "community_count": len(rows),
            "certain_share_overall": certain_share_overall,
            "thread_context_share_pct": thread_share,
        },
        "coverage_notes": coverage_notes,
    }


# ---------------------------------------------------------------------------
# Section data preparation functions
# ---------------------------------------------------------------------------

def prepare_executive_narrative(
    statistics: Dict[str, Any],
    themes: Dict[str, Dict[str, Any]]
) -> str:
    """
    Synthesize a 2-3 paragraph executive summary narrative from the data.

    Derives key insights from sentiment distribution, top themes,
    and regional patterns.
    """
    total = statistics.get('total_posts', 0)
    phrases = statistics.get('phrases_analyzed', [])
    sentiment = statistics.get('sentiment_distribution', {})
    emotion_dist = statistics.get('emotion_distribution', {}) or {}
    community_breakdown = (
        statistics.get('community_breakdown', {})
        or statistics.get('subreddit_breakdown', {})
        or {}
    )

    # Determine dominant sentiment and runner-up
    if sentiment:
        sorted_sentiments = sorted(sentiment.items(), key=lambda x: x[1], reverse=True)
        dominant = sorted_sentiments[0][0]
        dominant_pct = round(sorted_sentiments[0][1] / total * 100) if total > 0 else 0
        runner_up = sorted_sentiments[1] if len(sorted_sentiments) > 1 else None
        runner_up_pct = round(runner_up[1] / total * 100) if runner_up and total > 0 else 0
    else:
        dominant = "mixed"
        dominant_pct = 0
        runner_up = None
        runner_up_pct = 0

    # Determine dominant emotion
    dominant_emotion = None
    dominant_emotion_pct = 0
    if emotion_dist:
        sorted_emotions = sorted(emotion_dist.items(), key=lambda x: x[1], reverse=True)
        dominant_emotion = sorted_emotions[0][0]
        dominant_emotion_pct = round(sorted_emotions[0][1] / total * 100, 1) if total > 0 else 0

    # Collect top themes with their percentages
    top_themes = []
    for phrase, data in themes.items():
        for theme in data.get('major_themes', []):
            theme_name = theme.get('theme', 'general discussion')
            theme_pct = theme.get('percentage', 0)
            top_themes.append((theme_name, theme_pct))
    top_themes.sort(key=lambda x: x[1], reverse=True)

    # Find the most active community
    top_community = None
    if community_breakdown:
        top_community = max(community_breakdown, key=community_breakdown.get)

    # --- Build an insight-driven narrative ---

    # Lead sentence: highlight the dominant theme or emotional signal
    if top_themes:
        lead_theme_name = _short_theme_name(top_themes[0][0])
        lead_theme_pct = top_themes[0][1]
        lead = (
            f"The conversation is anchored by \"{lead_theme_name},\" which surfaces "
            f"in {lead_theme_pct}% of analyzed posts"
        )
        if dominant_emotion and dominant_emotion_pct > 0:
            lead += (
                f" and carries a predominantly {dominant_emotion} emotional tone "
                f"({dominant_emotion_pct}% of all content)."
            )
        else:
            lead += "."
    elif dominant_emotion and dominant_emotion_pct > 0:
        lead = (
            f"Across the community, {dominant_emotion} is the prevailing emotion, "
            f"detected in {dominant_emotion_pct}% of posts."
        )
    else:
        topics_str = (
            ", ".join(_sanitize_phrase(p) for p in phrases[:3])
            if phrases else "the analyzed topics"
        )
        lead = (
            f"Community discussion around {topics_str} shows a predominantly "
            f"{dominant} tone ({dominant_pct}% of posts)."
        )

    # Second sentence: sentiment contrast or community highlight
    parts = []
    if runner_up and runner_up_pct >= 15 and dominant != runner_up[0]:
        parts.append(
            f"While {dominant} sentiment dominates at {dominant_pct}%, "
            f"a notable {runner_up[0]} undercurrent ({runner_up_pct}%) "
            f"signals divided opinion worth monitoring."
        )
    elif dominant_pct >= 60:
        parts.append(
            f"Sentiment is remarkably unified\u2014{dominant_pct}% {dominant}\u2014"
            f"suggesting strong community consensus on these topics."
        )

    if top_community and not parts:
        comm_count = community_breakdown[top_community]
        comm_pct = round(comm_count / total * 100) if total > 0 else 0
        parts.append(
            f"{top_community} leads the conversation with {comm_pct}% of all posts, "
            f"making it the primary venue shaping public perception."
        )

    # Third sentence: secondary theme or regional nuance
    regions = statistics.get('region_breakdown', {})
    if len(top_themes) >= 2 and not parts:
        second_theme = _short_theme_name(top_themes[1][0])
        second_pct = top_themes[1][1]
        parts.append(
            f"\"{second_theme}\" ({second_pct}%) emerges as a secondary thread, "
            f"offering an additional angle for strategic engagement."
        )
    elif regions:
        top_region = max(regions, key=regions.get) if regions else None
        if top_region:
            parts.append(
                f"Geographically, the {top_region} region drives the bulk of discussion, "
                f"presenting a focused opportunity for targeted outreach."
            )

    narrative = lead
    if parts:
        narrative += " " + " ".join(parts)

    return narrative


def prepare_methodology_data(
    statistics: Dict[str, Any],
    config: dict
) -> Dict[str, Any]:
    """
    Prepare methodology section data.

    Returns dict with pipeline steps and data scope information.
    """
    model = "AI sentiment model"

    source_mix = statistics.get('source_mix', {}) or {}
    source_count = len([s for s, count in source_mix.items() if count])
    collection_desc = (
        "Public social discussion sources (combined)"
        if source_count > 1 else "Public social discussion source"
    )

    collection_note = (
        "Data collected from multiple public social discussion sources and combined into a unified analysis dataset"
        if source_count > 1 else
        "Data collected from public social discussion sources and prepared in a unified analysis dataset"
    )

    notes = [
        collection_note,
        "Sentiment analysis performed using local AI model for privacy",
        "Language detection via langdetect library",
        "Region inference based on community labels, metadata, and content analysis",
        "All usernames anonymized for privacy compliance",
        "Source-specific engagement metrics normalized into a single engagement signal for fair ranking",
        "Posts filtered by minimum engagement threshold",
    ]

    # Mixed-provider warning (Item 10)
    providers_used = statistics.get("providers_used", [])
    mixed_provider = statistics.get("mixed_provider_warning", False)
    if mixed_provider:
        notes.append(
            f"WARNING: Multiple AI providers ({', '.join(providers_used)}) were used "
            "during analysis due to provider failover. Results may reflect different "
            "classification biases between models."
        )

    return {
        "steps": [
            {"name": "Collection", "desc": collection_desc},
            {"name": "Analysis", "desc": f"Sentiment via {model}"},
            {"name": "Themes", "desc": "Pattern extraction"},
            {"name": "Report", "desc": "Insights & strategy"},
        ],
        "notes": notes,
        "scope": {
            "phrases": [_sanitize_phrase(p) for p in (statistics.get('phrases_analyzed', []) or [])],
            "total_posts": statistics.get('total_posts', 0),
            "community_count": len(statistics.get('community_breakdown', {})),
            "source_count": source_count,
            "date_range": statistics.get('date_range', {}),
            "model_used": model,
            "providers_used": providers_used,
            "mixed_provider_warning": mixed_provider,
        }
    }


EMOTION_MESSAGING_PLAYBOOK = {
    "enthusiastic": {
        "strategy": "Momentum Building",
        "approach": "Channel existing enthusiasm into advocacy. Share success stories, provide shareable content, and create ways for enthusiastic voices to amplify your message.",
        "tone": "Energetic, celebratory, empowering",
        "example_phrases": [
            "You're already leading the way...",
            "Here's how to take this further...",
            "Share your story with others who care...",
        ],
    },
    "hopeful": {
        "strategy": "Vision Reinforcement",
        "approach": "Strengthen hope with concrete progress updates and roadmaps. Show that optimism is well-founded by highlighting tangible milestones and near-term wins.",
        "tone": "Warm, forward-looking, grounded",
        "example_phrases": [
            "Here's what's already working...",
            "The next milestone we're aiming for...",
            "Your support is making this possible...",
        ],
    },
    "curious": {
        "strategy": "Educational Engagement",
        "approach": "Meet curiosity with depth. Provide explainers, AMAs, data visualizations, and behind-the-scenes content that rewards genuine interest.",
        "tone": "Informative, open, inviting",
        "example_phrases": [
            "Great question — here's what we know...",
            "Dive deeper into the data...",
            "We explored this, and here's what we found...",
        ],
    },
    "neutral": {
        "strategy": "Activation & Relevance",
        "approach": "Convert neutrality into engagement by making the topic personally relevant. Use local examples, relatable stories, and clear calls to action.",
        "tone": "Direct, relatable, no-hype",
        "example_phrases": [
            "Here's why this matters to you...",
            "What this means in practice...",
            "One thing you can do today...",
        ],
    },
    "skeptical": {
        "strategy": "Evidence-Led Persuasion",
        "approach": "Address skepticism with transparency and data. Acknowledge valid concerns, provide third-party validation, and avoid over-promising.",
        "tone": "Respectful, evidence-based, transparent",
        "example_phrases": [
            "We hear your concerns — here's the evidence...",
            "Let's look at what the data actually shows...",
            "Fair point — here's how we're addressing it...",
        ],
    },
    "concerned": {
        "strategy": "Reassurance & Action",
        "approach": "Validate concerns before offering solutions. Show that you understand the stakes and are taking concrete steps to address worries.",
        "tone": "Empathetic, serious, solution-oriented",
        "example_phrases": [
            "We understand why this matters...",
            "Here's what we're doing about it...",
            "Your concern is valid, and here's our plan...",
        ],
    },
    "frustrated": {
        "strategy": "Empathetic Acknowledgment",
        "approach": "Lead with acknowledgment, not defensiveness. Show you've heard the frustration, explain root causes honestly, and present a clear path forward.",
        "tone": "Patient, direct, solution-oriented",
        "example_phrases": [
            "We hear you, and we know this isn't good enough...",
            "Here's what went wrong and what we're fixing...",
            "No excuses — here's our action plan...",
        ],
    },
    "angry": {
        "strategy": "De-escalation & Accountability",
        "approach": "Prioritize listening and accountability. Avoid corporate jargon. Be specific about what you're changing and set clear timelines for follow-up.",
        "tone": "Humble, direct, accountable",
        "example_phrases": [
            "We take this seriously...",
            "Here's exactly what's changing, and by when...",
            "We owe you better, and here's how...",
        ],
    },
}


def prepare_recommendations(
    themes: Dict[str, Dict[str, Any]],
    statistics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate emotion-driven messaging recommendations from analysis data.

    Uses EMOTION_MESSAGING_PLAYBOOK as structural framework, but populates
    descriptions with actual emotional drivers, key critiques, themes, and
    community data from this specific analysis.
    """
    emotion_dist = statistics.get('emotion_distribution', {}) or {}
    emotional_drivers = statistics.get('emotional_drivers', []) or []
    total_posts = max(statistics.get('total_posts', 1), 1)

    # Rank emotions by frequency, exclude unknowns
    ranked_emotions = sorted(
        [(e, c) for e, c in emotion_dist.items() if e not in ('unknown', 'error') and c > 0],
        key=lambda x: -x[1]
    )

    # Gather top theme names and communities for data-specific descriptions
    top_theme_names = []
    all_critiques = []
    for _phrase, tdata in themes.items():
        _all_themes = sorted(
            (tdata.get('major_themes', []) or []),
            key=lambda t: t.get("post_count", t.get("percentage", 0)) or 0,
            reverse=True,
        )
        for t in _all_themes[:2]:
            name = _short_theme_name(t.get('theme', ''))
            if name and name not in top_theme_names:
                top_theme_names.append(name)
        for c in tdata.get('key_critiques', []) or []:
            critique_text = c.get('critique', '') if isinstance(c, dict) else str(c)
            if critique_text:
                all_critiques.append(critique_text)

    _cb = statistics.get('community_breakdown', {}) or {}
    top_communities = sorted(_cb, key=_cb.get, reverse=True)[:3]

    # Build a driver lookup: map emotional driver text to count
    driver_texts = [d.get("driver", "") for d in emotional_drivers if d.get("driver")]

    items = []
    for idx, (emotion, count) in enumerate(ranked_emotions[:4]):
        playbook = EMOTION_MESSAGING_PLAYBOOK.get(emotion)
        if not playbook:
            continue

        pct = round(count / total_posts * 100, 1)

        # Build a data-driven description that references actual findings
        # instead of just repeating the static approach text
        specific_parts = []

        # Reference the most relevant emotional driver
        if driver_texts:
            # Use a different driver for each emotion entry to avoid repetition
            driver_idx = min(idx, len(driver_texts) - 1)
            specific_parts.append(
                f"posts cite \"{_compact_text(driver_texts[driver_idx], max_len=80)}\" as a key driver"
            )

        # Reference relevant theme
        theme_idx = min(idx, len(top_theme_names) - 1) if top_theme_names else -1
        if theme_idx >= 0:
            specific_parts.append(
                f"concentrated around \"{top_theme_names[theme_idx]}\""
            )

        # Reference relevant community
        comm_idx = min(idx, len(top_communities) - 1) if top_communities else -1
        if comm_idx >= 0:
            specific_parts.append(f"especially in {top_communities[comm_idx]}")

        # Reference relevant critique for negative emotions
        if emotion in ('frustrated', 'angry', 'concerned', 'skeptical') and all_critiques:
            critique_idx = min(idx, len(all_critiques) - 1)
            specific_parts.append(
                f"key critique: \"{_compact_text(all_critiques[critique_idx], max_len=70)}\""
            )

        # Combine strategy approach with data-specific context
        base_strategy = playbook["strategy"]
        base_approach = playbook["approach"]

        if specific_parts:
            data_context = "; ".join(specific_parts)
            description = (
                f"{pct}% of posts express {emotion} — {data_context}. "
                f"{base_approach}"
            )
        else:
            description = f"{base_approach} ({pct}% of posts express {emotion}.)"

        items.append({
            "title": base_strategy,
            "emotion": emotion,
            "prevalence_pct": pct,
            "description": description,
            "tone": playbook["tone"],
            "example_phrases": playbook["example_phrases"],
            "evidence": (
                driver_texts[min(idx, len(driver_texts) - 1)]
                if driver_texts
                else f"{count} posts ({pct}%) express {emotion} emotion"
            ),
        })

    # Data-specific intro referencing actual findings
    top_emotion = ranked_emotions[0][0] if ranked_emotions else "mixed"
    intro = ""
    if ranked_emotions:
        intro = (
            f"The dominant emotional tone is {top_emotion} "
            f"({ranked_emotions[0][1]} of {total_posts} posts). "
        )
        if top_theme_names:
            intro += f"Key themes driving this response include \"{top_theme_names[0]}\""
            if len(top_theme_names) > 1:
                intro += f" and \"{top_theme_names[1]}\""
            intro += ". "
        if all_critiques:
            intro += f"The most prominent critique: \"{_compact_text(all_critiques[0], max_len=90)}.\""
    else:
        intro = (
            "These messaging strategies are tailored to the emotional landscape "
            "of your audience."
        )

    return {"intro_narrative": intro, "entries": items}


def prepare_transparency_data(
    themes: Dict[str, Dict[str, Any]],
    statistics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Derive "What's Working / What's Not" from analysis data.

    Working: positive sentiment themes, high-engagement topics
    Not Working: negative sentiment, frequent critiques
    """
    working = []
    needs_attention = []

    for phrase, data in themes.items():
        summary = data.get('sentiment_summary', {})
        overall = summary.get('overall', 'neutral')

        # Working items from positive themes
        if overall in ('positive',):
            for theme in data.get('major_themes', [])[:1]:
                working.append({
                    "finding": (
                        f"Positive sentiment around \"{theme.get('theme', phrase)}\" "
                        f"in {phrase} discussions ({theme.get('percentage', 0)}% prevalence)."
                    ),
                    "evidence": summary.get('narrative', '')[:100],
                })

        # Needs attention from negative themes
        if overall in ('negative',):
            working_note = summary.get('narrative', '')
            needs_attention.append({
                "finding": (
                    f"Negative overall sentiment detected in {phrase} discussions."
                ),
                "evidence": working_note[:100] if working_note else "Sentiment analysis",
            })

        # Needs attention from frequent critiques
        for critique in data.get('key_critiques', []):
            if critique.get('frequency') == 'frequent':
                needs_attention.append({
                    "finding": f"Frequent critique: {critique['critique']}",
                    "evidence": f"Identified in {phrase} thematic analysis",
                })

    # If we have no positive items, add a general one
    if not working:
        total = statistics.get('total_posts', 0)
        positive = statistics.get('sentiment_distribution', {}).get('positive', 0)
        if positive > 0:
            pct = round(positive / total * 100) if total > 0 else 0
            working.append({
                "finding": (
                    f"{pct}% of community posts reflect positive sentiment."
                ),
                "evidence": "Overall sentiment distribution",
            })

    return {
        "working": working[:4],
        "needs_attention": needs_attention[:4],
    }


def prepare_next_steps(
    recommendations: Dict[str, Any],
    statistics: Dict[str, Any],
    themes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate concrete, time-bound action items distinct from playbook strategies.

    Actions are derived from actual data findings: specific emotions, communities,
    critiques, and themes — not generic templates.
    """
    themes = themes or {}
    steps = []
    total_posts = max(statistics.get('total_posts', 1), 1)
    emotion_dist = statistics.get('emotion_distribution', {}) or {}
    sentiment_dist = statistics.get('sentiment_distribution', {}) or {}
    emotional_drivers = statistics.get('emotional_drivers', []) or []
    community_breakdown = (
        statistics.get('community_breakdown', {})
        or statistics.get('subreddit_breakdown', {})
        or {}
    )
    top_community = max(community_breakdown, key=community_breakdown.get) if community_breakdown else None

    # Collect actual critiques and themes for data-specific actions
    all_critiques = []
    top_theme_names = []
    for _phrase, tdata in themes.items():
        for c in tdata.get('key_critiques', []) or []:
            critique_text = c.get('critique', '') if isinstance(c, dict) else str(c)
            if critique_text:
                all_critiques.append(critique_text)
        for t in (tdata.get('major_themes', []) or [])[:2]:
            name = _short_theme_name(t.get('theme', ''))
            if name and name not in top_theme_names:
                top_theme_names.append(name)

    # Action 1: Address the dominant emotion with specific driver context
    if emotion_dist:
        top_emotion = max(emotion_dist, key=emotion_dist.get)
        top_emo_pct = round(emotion_dist[top_emotion] / total_posts * 100, 1)
        driver_context = ""
        if emotional_drivers:
            driver_context = f" — driven by \"{_compact_text(emotional_drivers[0].get('driver', ''), max_len=60)}\""
        steps.append({
            "action": f"Address {top_emotion} sentiment ({top_emo_pct}% of posts){driver_context}",
            "rationale": (
                f"Develop targeted messaging for the {top_emotion} audience"
                + (f", focusing on \"{top_theme_names[0]}\"" if top_theme_names else "")
                + "."
            ),
            "priority": "high",
        })

    # Action 2: Engage the top community with specific context
    if top_community:
        comm_count = community_breakdown[top_community]
        steps.append({
            "action": f"Engage {top_community} ({comm_count} posts) with tailored outreach",
            "rationale": (
                f"This community drives {round(comm_count / total_posts * 100)}% of conversation"
                + (f" and surfaces key critique: \"{_compact_text(all_critiques[0], max_len=60)}\"" if all_critiques else "")
                + "."
            ),
            "priority": "high",
        })

    # Action 3: Address negative sentiment with specific critiques
    neg_count = sentiment_dist.get('negative', 0)
    neg_pct = round(neg_count / total_posts * 100)
    if neg_pct >= 15:
        critique_detail = ""
        if all_critiques:
            critique_detail = f": \"{_compact_text(all_critiques[0], max_len=50)}\""
        steps.append({
            "action": f"Respond to {neg_pct}% negative sentiment{critique_detail}",
            "rationale": "Timely acknowledgment of specific concerns prevents narrative escalation.",
            "priority": "high",
        })

    # Action 4: Monitor for trend changes
    steps.append({
        "action": "Schedule follow-up analysis in 2 weeks to track sentiment trajectory",
        "rationale": "Measure whether responses shift the emotional landscape and identify emerging themes.",
        "priority": "medium",
    })

    return steps[:4]


def prepare_progress_data(
    config: dict,
    current_statistics: Dict[str, Any],
    data_dir: str = "data/analyzed"
) -> Optional[Dict[str, Any]]:
    """
    Load historical report data for progress tracking.

    Checks for previous themes files to compare sentiment shifts.
    Returns None if this is the first report.
    """
    themes_dir = _resolve_project_path(data_dir)
    if not themes_dir.exists():
        return None

    themes_files = sorted(themes_dir.glob("themes_*.json"))
    if len(themes_files) < 2:
        return None

    historical = []
    for tf in themes_files[-5:]:  # Last 5 reports
        try:
            with open(tf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            stats = data.get('statistics', {})
            sentiment = stats.get('sentiment_distribution', {})
            date_str = tf.stem.split('_', 1)[1] if '_' in tf.stem else tf.stem
            historical.append({
                "date": date_str[:10],
                "positive": sentiment.get('positive', 0),
                "negative": sentiment.get('negative', 0),
                "neutral": sentiment.get('neutral', 0),
                "mixed": sentiment.get('mixed', 0),
            })
        except Exception as e:
            logger.warning(f"Could not load historical data from {tf}: {e}")

    if len(historical) < 2:
        return None

    # Calculate change metrics
    prev = historical[-2]
    curr = historical[-1]
    metrics = []

    for key, label in [
        ("positive", "Positive"),
        ("negative", "Negative"),
        ("neutral", "Neutral")
    ]:
        prev_val = prev.get(key, 0)
        curr_val = curr.get(key, 0)
        diff = curr_val - prev_val
        direction = "up" if diff > 0 else ("down" if diff < 0 else "flat")
        change_str = f"+{diff}" if diff > 0 else str(diff)
        metrics.append({
            "name": label,
            "current": str(curr_val),
            "change": change_str,
            "direction": direction,
        })

    return {
        "historical": historical,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Template loading and rendering
# ---------------------------------------------------------------------------

def load_template(template_dir: str = "templates") -> Environment:
    """
    Load Jinja2 environment with templates.

    Args:
        template_dir: Directory containing templates

    Returns:
        Configured Jinja2 Environment
    """
    template_path = _resolve_project_path(template_dir)
    env = Environment(
        loader=FileSystemLoader(str(template_path)),
        autoescape=select_autoescape(['html', 'xml'])
    )
    return env


def render_html_report(
    template_env: Environment,
    data: Dict[str, Any],
    base_dir: str = ".",
    template_name: str = "report_template.html"
) -> str:
    """
    Render the HTML report from template and data.

    Args:
        template_env: Jinja2 environment
        data: Complete report data dictionary
        base_dir: Project root for resolving font paths
        template_name: Template filename to render

    Returns:
        Rendered HTML string
    """
    template = template_env.get_template(template_name)
    html = template.render(**data)

    # Resolve relative font paths to absolute for WeasyPrint
    # WeasyPrint resolves CSS url() relative to the CSS file location,
    # but we ensure absolute paths work as a fallback
    abs_assets = str(Path(base_dir).resolve() / 'assets')
    html = html.replace('../assets/', abs_assets + '/')

    return html


def generate_pdf_report(
    html_content: str,
    css_path: str,
    output_path: str,
    base_dir: str = "."
) -> str:
    """
    Generate PDF from HTML using WeasyPrint.

    Args:
        html_content: Rendered HTML string
        css_path: Path to CSS file
        output_path: Path for output PDF file
        base_dir: Project root for resolving paths

    Returns:
        Path to generated PDF file
    """
    css = CSS(filename=str(_resolve_project_path(css_path)))

    # Use base_url so WeasyPrint resolves relative paths correctly
    base_url = str(Path(base_dir).resolve()) + '/'
    html = HTML(string=html_content, base_url=base_url)
    html.write_pdf(str(_resolve_project_path(output_path)), stylesheets=[css])

    logger.info(f"Generated PDF report: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Card format data preparation
# ---------------------------------------------------------------------------

def _first_sentence(text: str, max_len: int = 120) -> str:
    """Extract the first sentence from a string, capped at max_len."""
    if not text:
        return ""
    # Find sentence boundary
    for end in ['. ', '! ', '? ']:
        idx = text.find(end)
        if 0 < idx < max_len:
            return text[:idx + 1]
    return text[:max_len].rsplit(' ', 1)[0] + '...' if len(text) > max_len else text


def prepare_card_data(
    statistics: Dict[str, Any],
    themes_by_phrase: Dict[str, Dict[str, Any]],
    executive_narrative: str,
    recommendations: Dict[str, Any],
    community_lens: Dict[str, Any],
    next_steps: List[Dict[str, Any]],
    methodology: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reshape existing report data into card-specific structures.
    Each card gets exactly the data it needs for the 4:5 template.
    """
    try:
        from design_system import EMOTION_COLORS, SENTIMENT_COLORS, get_emotion_color, get_sentiment_color
    except ImportError:
        from .design_system import EMOTION_COLORS, SENTIMENT_COLORS, get_emotion_color, get_sentiment_color

    total_posts = max(statistics.get('total_posts', 1), 1)
    emotion_dist = statistics.get('emotion_distribution', {}) or {}
    sentiment_dist = statistics.get('sentiment_distribution', {}) or {}
    sentiment_ci = statistics.get('sentiment_confidence_intervals', {}) or {}
    emotion_ci = statistics.get('emotion_confidence_intervals', {}) or {}
    community_breakdown = statistics.get('community_breakdown', {}) or statistics.get('subreddit_breakdown', {}) or {}

    # --- Card 1: Cover ---
    dominant_emotion = max(emotion_dist, key=emotion_dist.get) if emotion_dist else "neutral"
    dominant_emotion_pct = round(
        emotion_dist.get(dominant_emotion, 0) / total_posts * 100, 1
    ) if emotion_dist and total_posts else 0

    # Build a punchy editorial headline for the cover card.
    # Aggregate actual post_count across all phrases to find the dominant theme.
    # We use post_count (computed from data) rather than percentage (which may
    # be per-phrase and not comparable across phrases with different totals).
    theme_post_totals: Dict[str, int] = {}
    for _phrase, tdata in themes_by_phrase.items():
        for _t in (tdata.get('major_themes', []) or tdata.get('themes', [])):
            t_name = _t.get('theme', '') or _t.get('theme_name', '')
            t_count = _t.get('post_count') if _t.get('post_count') is not None else (_t.get('percentage') or 0)
            if t_name:
                theme_post_totals[t_name] = theme_post_totals.get(t_name, 0) + t_count
    top_theme_name = max(theme_post_totals, key=theme_post_totals.get) if theme_post_totals else ""

    dominant_sent = max(sentiment_dist, key=sentiment_dist.get) if sentiment_dist else "mixed"
    if top_theme_name:
        headline = _compact_text(_short_theme_name(top_theme_name), max_len=70)
    else:
        headline = _first_sentence(executive_narrative, max_len=90)

    # Sample size confidence indicator
    low_confidence = total_posts < 30

    cover = {
        "headline": headline,
        "community_count": len(community_breakdown),
        "dominant_emotion": dominant_emotion,
        "dominant_emotion_pct": dominant_emotion_pct,
        "total_posts": total_posts,
        "low_confidence": low_confidence,
    }

    # --- Card 2: Emotional Landscape ---
    ranked_emotions = sorted(
        [(e, c) for e, c in emotion_dist.items() if e not in ('unknown', 'error') and c > 0],
        key=lambda x: -x[1]
    )
    dominant_name = ranked_emotions[0][0] if ranked_emotions else "neutral"
    dominant_pct = round(ranked_emotions[0][1] / total_posts * 100, 1) if ranked_emotions else 0
    dominant_color = get_emotion_color(dominant_name)

    emotion_bars = []
    for emo, count in ranked_emotions:
        pct = round(count / total_posts * 100, 1)
        emo_ci = emotion_ci.get(emo, {})
        emotion_bars.append({
            "name": emo,
            "count": count,
            "pct": pct,
            "color": get_emotion_color(emo),
            "ci_lower": emo_ci.get("lower"),
            "ci_upper": emo_ci.get("upper"),
        })

    # Short narrative for emotion card
    emotion_narrative = _first_sentence(executive_narrative, max_len=180)

    emotion_card = {
        "dominant_name": dominant_name,
        "dominant_pct": dominant_pct,
        "dominant_color": dominant_color,
        "bars": emotion_bars,
        "narrative": emotion_narrative,
    }

    # --- Card 3: Sentiment Split ---
    # Always include all four categories so displayed percentages sum to 100%.
    sentiment_blocks = []
    for sent_name in ['positive', 'neutral', 'negative', 'mixed']:
        count = sentiment_dist.get(sent_name, 0)
        pct = round(count / total_posts * 100, 1)
        s_ci = sentiment_ci.get(sent_name, {})
        sentiment_blocks.append({
            "name": sent_name.capitalize(),
            "count": count,
            "pct": pct,
            "color": get_sentiment_color(sent_name),
            "ci_lower": s_ci.get("lower"),
            "ci_upper": s_ci.get("upper"),
        })

    date_range = statistics.get('date_range', {})
    date_range_str = ""
    if date_range:
        start = date_range.get('start', '')
        end = date_range.get('end', '')
        if start and end:
            date_range_str = f"{_format_date_human(start)} – {_format_date_human(end)}"

    # Build a short sentiment narrative
    sent_narrative = ""
    dominant_sent = max(sentiment_dist, key=sentiment_dist.get) if sentiment_dist else "neutral"
    sent_pct = round(sentiment_dist.get(dominant_sent, 0) / total_posts * 100, 1) if sentiment_dist else 0
    sent_narrative = (
        f"The overall tone is predominantly {dominant_sent} "
        f"({sent_pct}%), based on {total_posts} analyzed posts."
    )

    # --- Engagement-weighted sentiment ---
    weighted_blocks = []
    weighted_dist = statistics.get('weighted_sentiment_distribution', {})
    if weighted_dist:
        total_weight = sum(weighted_dist.values()) or 1
        for sent_name in ['positive', 'neutral', 'negative', 'mixed']:
            w = weighted_dist.get(sent_name, 0)
            wpct = round(w / total_weight * 100, 1)
            weighted_blocks.append({
                "name": sent_name.capitalize(),
                "pct": wpct,
                "color": get_sentiment_color(sent_name),
            })

    sentiment_card = {
        "blocks": sentiment_blocks,  # Include all categories (positive, neutral, negative, mixed)
        "weighted_blocks": weighted_blocks,
        "community_count": len(community_breakdown),
        "phrase_count": _safe_int(statistics.get('phrase_count', 0)) or len(statistics.get('phrases_analyzed', []) or []),
        "date_range": date_range_str,
        "narrative": sent_narrative,
    }

    # --- Card 4: Key Themes ---
    # Use actual post_count (computed from data in thematic_analyzer) rather
    # than LLM-guessed percentages. Recalculate pct from counts.
    all_themes = []
    for phrase, data in themes_by_phrase.items():
        phrase_total = max(data.get('post_count', 1), 1)
        for theme in data.get('major_themes', []):
            post_count = theme.get('post_count', 0)
            if post_count > 0:
                pct = round(post_count / phrase_total * 100, 1)
            else:
                pct = round(theme.get('percentage', 0), 1)
            all_themes.append({
                "name": _sanitize_llm_output(_short_theme_name(theme.get('theme', 'General'))),
                "description": _sanitize_llm_output(theme.get('description', '')),
                "pct": pct,
                "count": post_count,
                "phrase": phrase,
            })
    all_themes.sort(key=lambda x: (-x['count'], -x['pct']))
    top_themes = all_themes[:8]

    # Pick a quote from top engagement posts, filtering for quality
    top_posts = statistics.get('top_posts_by_engagement', [])
    theme_quote = None
    for post in top_posts[:10]:
        body = post.get('body', '') or post.get('title', '') or ''
        if len(body) > 30 and _is_suitable_quote(body) and _is_suitable_quote_source(post):
            community = post.get('subreddit', post.get('community', ''))
            theme_quote = {
                "text": _compact_text(body, max_len=160),
                "meta": _humanize_community(community) if community else "",
            }
            break

    # Collect phrase names as chips
    theme_chips = [_sanitize_phrase(p) for p in list(themes_by_phrase.keys())[:6]]

    themes_card = {
        "top_theme_name": f"{len(top_themes)} Key Themes" if top_themes else "Key Themes",
        "bars": top_themes,
        "quote": theme_quote,
        "chips": theme_chips,
    }

    # --- Card 5: Community Lens ---
    # Suppress card when insufficient community diversity exists
    MIN_COMMUNITIES_FOR_CARD = 3
    MIN_POSTS_PER_COMMUNITY = 3

    community_rows = []
    for row in community_lens.get('rows', [])[:7]:
        sent_pcts = row.get('sentiment_percentages', {}) or {}
        community_rows.append({
            "community": _humanize_community(row['community']),
            "total": row['total_posts'],
            "positive_pct": round(sent_pcts.get('positive', 0), 1),
            "neutral_pct": round(sent_pcts.get('neutral', 0), 1),
            "mixed_pct": round(sent_pcts.get('mixed', 0), 1),
            "negative_pct": round(sent_pcts.get('negative', 0), 1),
        })

    # Filter to communities with enough data, then suppress card if too few remain
    qualifying_rows = [r for r in community_rows if r['total'] >= MIN_POSTS_PER_COMMUNITY]
    suppress_community_card = len(qualifying_rows) < MIN_COMMUNITIES_FOR_CARD
    if suppress_community_card:
        community_rows = []  # Empty rows will cause template to skip the card

    # Pick a highlight quote, filtering for quality
    community_quote = None
    for q in community_lens.get('highlight_quotes', [])[:5]:
        quote_text = q.get('quote', '')
        if _is_suitable_quote(quote_text) and q.get('community', '').lower() not in _FRINGE_SUBREDDITS:
            community_quote = {
                "text": _compact_text(quote_text, max_len=170),
                "community": _humanize_community(q.get('community', '')),
                "sentiment": q.get('sentiment', 'neutral'),
                "sentiment_color": get_sentiment_color(q.get('sentiment', 'neutral')),
            }
            break

    # Find most negative/polarized community (highest negative %)
    most_polarized = None
    if community_rows:
        polarized = max(community_rows, key=lambda r: r.get('negative_pct', 0))
        neg_pct = polarized.get('negative_pct', 0)
        if neg_pct > 10:
            pos_pct = polarized.get('positive_pct', 0)
            is_unanimous = neg_pct >= 70 and pos_pct < 15
            most_polarized = {
                "community": polarized['community'],
                "negative_pct": neg_pct,
                "total": polarized['total'],
                "label": "Most negative" if is_unanimous else "Most polarized",
            }

    community_card = {
        "rows": community_rows,
        "quote": community_quote,
        "most_polarized": most_polarized,
    }

    # --- Card 6: Messaging Playbook ---
    playbook_entries = []
    for entry in recommendations.get('entries', [])[:4]:
        example = entry.get('example_phrases', [''])[0] if entry.get('example_phrases') else ''
        playbook_entries.append({
            "emotion": entry['emotion'],
            "title": entry['title'],
            "description": _compact_text(entry['description'], max_len=160),
            "example": example,
            "color": get_emotion_color(entry['emotion']),
        })

    playbook_card = {
        "intro": _compact_text(recommendations.get('intro_narrative', ''), max_len=250),
        "entries": playbook_entries,
    }

    # --- Card 7: Next Steps + Methodology ---
    next_steps_card = {
        "action_list": next_steps[:4],
        "novel_ideas": [],
    }
    # Collect novel ideas across phrases, filtering fiction/off-topic
    _fiction_markers = {'alternate history', 'worldbuilding', 'sci-fi', 'fan fiction', 'mod ', 'fanfic'}
    for phrase, data in themes_by_phrase.items():
        for idea in data.get('novel_ideas', [])[:4]:
            if isinstance(idea, str) and len(idea) > 10:
                if not any(m in idea.lower() for m in _fiction_markers):
                    next_steps_card["novel_ideas"].append(idea)

    methodology_card = {
        "steps": methodology.get('steps', [
            {"name": "Collection", "desc": "Gather posts"},
            {"name": "Analysis", "desc": "AI sentiment"},
            {"name": "Themes", "desc": "Extract themes"},
            {"name": "Report", "desc": "Generate cards"},
        ]),
    }

    return {
        "cover": cover,
        "emotion": emotion_card,
        "sentiment": sentiment_card,
        "themes": themes_card,
        "community": community_card,
        "playbook": playbook_card,
        "next_steps": next_steps_card,
        "methodology": methodology_card,
    }


# ---------------------------------------------------------------------------
# Main report creation orchestrator
# ---------------------------------------------------------------------------

def create_report(
    analyzed_posts_path: str,
    themes_path: str,
    config: dict,
    output_dir: str = "reports",
    template_dir: str = "templates",
    report_format: str = "auto",
) -> str:
    """
    Main report generation function.

    Orchestrates the full report creation process:
    1. Load analyzed data
    2. Anonymize usernames if configured
    3. Generate branded charts (pages format) or skip (cards format)
    4. Fetch contextual photography
    5. Prepare all section data
    6. Render HTML template
    7. Generate PDF

    Args:
        analyzed_posts_path: Path to analyzed posts JSON
        themes_path: Path to thematic analysis JSON
        config: Full configuration dictionary
        output_dir: Directory for PDF output
        template_dir: Directory containing HTML templates
        report_format: "cards" (4:5 Signalstream cards), "pages" (legacy letter),
                       or "auto" (reads from config)

    Returns:
        Path to generated PDF report
    """
    # Determine project root (parent of scripts/)
    base_dir = str(PROJECT_ROOT)
    analyzed_posts_file = _resolve_project_path(analyzed_posts_path)
    themes_file = _resolve_project_path(themes_path)
    template_dir_path = _resolve_project_path(template_dir)
    output_dir_path = _resolve_project_path(output_dir)

    # Resolve format
    if report_format == "auto":
        report_format = config.get('design_system', {}).get('report', {}).get('format', 'cards')
    use_cards = report_format == "cards"

    # ---- 1. Load data ----
    with open(analyzed_posts_file, 'r', encoding='utf-8') as f:
        posts = json.load(f)

    with open(themes_file, 'r', encoding='utf-8') as f:
        themes_data = json.load(f)

    statistics = themes_data.get('statistics', {})
    themes_by_phrase = themes_data.get('themes_by_phrase', {})

    branding = config.get('branding', {
        'company_name': 'Signalstream',
        'tagline': 'Social Intelligence, Distilled.',
        'footer_text': ''
    })
    # Default footer_text to empty (N19: "Confidential" off by default for self-hosted)
    if 'footer_text' not in branding:
        branding['footer_text'] = ''

    anonymize = config.get('output', {}).get('anonymize_usernames', True)

    # ---- 2. Anonymize ----
    if anonymize and statistics.get('top_posts_by_engagement'):
        anonymizer = UsernameAnonymizer()
        for post in statistics['top_posts_by_engagement']:
            if 'author' in post:
                post['author'] = anonymizer.anonymize(post['author'])

    # ---- 3. Generate charts (skip for cards — they use CSS bars) ----
    charts = {}
    if not use_cards:
        try:
            from chart_generator import generate_all_charts

            charts = generate_all_charts(
                statistics, themes_by_phrase, config,
                base_dir=base_dir,
                historical_data=None
            )
        except ImportError:
            logger.warning("chart_generator not available; skipping charts")
        except Exception as e:
            logger.error(f"Chart generation failed: {e}")

    # ---- 4. Fetch images ----
    photos = {}
    try:
        from image_fetcher import ImageFetcher

        design_config = config.get('design_system', {}).get('report', {})
        max_photos = design_config.get('max_photos', 2 if use_cards else 5)

        fetcher = ImageFetcher(config, base_dir=base_dir)
        topics = [_sanitize_phrase(p) for p in (statistics.get('phrases_analyzed', []) or [])]
        photos = fetcher.fetch_report_images(topics, max_photos)
    except ImportError:
        logger.warning("image_fetcher not available; skipping photos")
    except Exception as e:
        logger.error(f"Image fetching failed: {e}")

    # ---- 5. Prepare section data ----
    executive_narrative = prepare_executive_narrative(statistics, themes_by_phrase)
    # Guarantee a narrative exists even if the generation logic returned empty
    if not executive_narrative or not executive_narrative.strip():
        phrases_str = ", ".join(
            _sanitize_phrase(p) for p in (statistics.get('phrases_analyzed', []) or [])[:3]
        ) or "the analyzed topics"
        executive_narrative = (
            f"This report analyzes {statistics.get('total_posts', 0)} posts "
            f"about {phrases_str} across "
            f"{len(statistics.get('community_breakdown', {}))} communities."
        )
    methodology = prepare_methodology_data(statistics, config)
    recommendations = prepare_recommendations(themes_by_phrase, statistics)
    transparency = prepare_transparency_data(themes_by_phrase, statistics)
    community_lens = prepare_community_lens_data(statistics)
    next_steps = prepare_next_steps(recommendations, statistics, themes=themes_by_phrase)
    photo_overlays = prepare_photo_overlays(
        posts=posts,
        statistics=statistics,
        themes_by_phrase=themes_by_phrase,
        executive_narrative=executive_narrative,
        methodology=methodology,
        recommendations=recommendations,
        next_steps=next_steps,
    )

    # Photo attributions (deduplicated by photographer)
    all_photo_attributions = []
    seen_photographers = set()
    for section, photo in photos.items():
        if photo:
            photographer = photo["photographer"]
            if photographer in seen_photographers:
                continue
            seen_photographers.add(photographer)
            all_photo_attributions.append({
                "description": section.replace("_", " ").title(),
                "photographer": photographer,
                "source": photo["source"],
            })

    # ---- 5b. Trend data (if prior analyses exist) ----
    trend_data = []
    try:
        from db import get_trend_data
        topic = statistics.get('phrases_analyzed', [''])[0] if statistics.get('phrases_analyzed') else ''
        if topic:
            trend_data = get_trend_data(topic, limit=5)
    except Exception:
        pass

    closing_narrative = (
        f"This report was prepared by {branding.get('company_name', 'the analysis team')}. "
        f"The insights and recommendations are based on publicly available "
        f"online social discussion data and are intended to inform "
        f"communication strategy. For questions or follow-up analysis, "
        f"please contact your account representative."
    )

    # ---- 6. Build template data ----
    try:
        from design_system import EMOTION_COLORS
    except ImportError:
        EMOTION_COLORS = {}

    report_data = {
        'report_date': datetime.now().strftime('%B %d, %Y'),
        'branding': branding,
        'statistics': statistics,
        'themes_by_phrase': themes_by_phrase,
        'charts': charts,
        'photos': photos,
        'photo_overlays': photo_overlays,
        'executive_summary': {'narrative': executive_narrative},
        'methodology': methodology,
        'recommendations': recommendations,
        'transparency': transparency,
        'community_lens': community_lens,
        'next_steps': next_steps,
        'closing_narrative': closing_narrative,
        'all_photo_attributions': all_photo_attributions,
        'emotion_colors': EMOTION_COLORS,
        'trend_data': trend_data,
    }

    # For card format, add card-specific data
    if use_cards:
        report_data['card_data'] = prepare_card_data(
            statistics=statistics,
            themes_by_phrase=themes_by_phrase,
            executive_narrative=executive_narrative,
            recommendations=recommendations,
            community_lens=community_lens,
            next_steps=next_steps,
            methodology=methodology,
        )

    # ---- 7. Render and generate PDF ----
    template_env = load_template(str(template_dir_path))

    if use_cards:
        template_name = 'card_template.html'
        css_path = template_dir_path / 'card_styles.css'
    else:
        template_name = 'report_template.html'
        css_path = template_dir_path / 'report_styles.css'

    html_content = render_html_report(template_env, report_data, base_dir, template_name)

    output_path = output_dir_path
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    pdf_filename = f"intel_report_{timestamp}.pdf"
    pdf_path = output_path / pdf_filename

    generate_pdf_report(html_content, str(css_path), str(pdf_path), base_dir)

    return str(pdf_path)


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def get_latest_analyzed_file(
    data_dir: str = "data/analyzed", prefix: str = "analyzed_"
) -> Optional[str]:
    """Find the most recent file with given prefix."""
    path = _resolve_project_path(data_dir)
    if not path.exists():
        return None

    files = list(path.glob(f"{prefix}*.json"))
    if not files:
        return None

    return str(max(files, key=lambda p: p.stat().st_mtime))


def get_latest_themes_file(data_dir: str = "data/analyzed") -> Optional[str]:
    """Find the most recent themes file."""
    return get_latest_analyzed_file(data_dir, "themes_")


def main():
    """Entry point for standalone report generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate PDF intelligence report')
    parser.add_argument(
        '--config', default='config.yaml', help='Path to config file')
    parser.add_argument(
        '--analyzed', help='Path to analyzed posts JSON')
    parser.add_argument(
        '--themes', help='Path to themes JSON')
    parser.add_argument(
        '--output', default='reports', help='Output directory')
    parser.add_argument(
        '--templates', default='templates', help='Templates directory')
    args = parser.parse_args()

    try:
        config = load_config_file(args.config)

        analyzed_path = args.analyzed or get_latest_analyzed_file(
            'data/analyzed', 'analyzed_')
        themes_path = args.themes or get_latest_themes_file('data/analyzed')

        if not analyzed_path:
            print("Error: No analyzed posts file found. "
                  "Run analyzer.py first or specify --analyzed")
            return

        if not themes_path:
            print("Error: No themes file found. "
                  "Run thematic_analyzer.py first or specify --themes")
            return

        print(f"Loading analyzed posts from: {analyzed_path}")
        print(f"Loading themes from: {themes_path}")

        pdf_path = create_report(
            analyzed_posts_path=analyzed_path,
            themes_path=themes_path,
            config=config,
            output_dir=args.output,
            template_dir=args.templates
        )

        print(f"\nReport generated successfully!")
        print(f"Output: {pdf_path}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: Invalid configuration values: {e}")
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise


if __name__ == "__main__":
    main()
