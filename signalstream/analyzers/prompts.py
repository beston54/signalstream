"""LLM prompt templates for sentiment and thematic analysis.

All prompts are version-tagged for reproducibility. Ported from the current
codebase (analyzer.py:201-324, thematic_analyzer.py:122-181).

Prompt injection defense: user content is wrapped in <user_post>...</user_post>
delimiters so the model can distinguish instructions from data.
"""
from __future__ import annotations

from signalstream.db.models import Comment, Post

# ---------------------------------------------------------------------------
# Version-tagged prompt templates
# ---------------------------------------------------------------------------

SENTIMENT_PROMPT_V1 = """You are an expert sentiment and emotion analyst for social media content. \
Analyze the provided post and its context to determine sentiment, emotion, and key points.

You MUST respond in EXACTLY this format (one item per line, no extra text):
PRIMARY_EMOTION: [enthusiastic/hopeful/curious/neutral/skeptical/concerned/frustrated/angry]
SECONDARY_EMOTION: [one of the above, or none]
EMOTION_INTENSITY: [strong/moderate/mild]
SENTIMENT: [positive/negative/neutral/mixed]
CONFIDENCE: [certain/uncertain/questioning]
KEY_POINT: [one sentence summary of the main point or argument]
EMOTIONAL_DRIVER: [one sentence explaining what drives the emotional response]
SARCASM_DETECTED: [true/false]

Pay special attention to sarcasm, irony, and rhetorical inversion. If the text \
appears sarcastic, classify based on the INTENDED meaning, not the literal surface.

Choose only ONE option for each field. Be concise and evidence-based."""


SENTIMENT_RETRY_PROMPT_V1 = """You are an expert sentiment analyst. Your previous response \
could not be parsed. You MUST respond in EXACTLY this format with no extra text, \
preamble, or explanation — just the labeled fields:

PRIMARY_EMOTION: [enthusiastic/hopeful/curious/neutral/skeptical/concerned/frustrated/angry]
SECONDARY_EMOTION: [one of the above, or none]
EMOTION_INTENSITY: [strong/moderate/mild]
SENTIMENT: [positive/negative/neutral/mixed]
CONFIDENCE: [certain/uncertain/questioning]
KEY_POINT: [one sentence]
EMOTIONAL_DRIVER: [one sentence]
SARCASM_DETECTED: [true/false]

Respond ONLY with these 8 lines. No other text."""


THEMATIC_PROMPT_V1 = """You are an expert analyst identifying themes across social media discussions. \
Analyze the provided post summaries and identify cross-cutting themes, patterns, and insights.

Respond in EXACTLY this format:

MAJOR_THEMES:
1. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]
2. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]
3. [Short Theme Label (5-10 words max)] | [One-sentence description of this theme]

POST_THEME_ASSIGNMENTS:
For each post number, list which 1-2 major themes (by number) it belongs to:
1: 1,2
2: 1
3: 3

NOVEL_IDEAS:
- [Unique perspective or idea not commonly discussed]

KEY_CRITIQUES:
- [Common criticism or concern raised] (frequency: frequent/occasional/rare)

REGIONAL_PATTERNS:
- [Region]: [Pattern or trend observed in this region]

SENTIMENT_SUMMARY:
Overall sentiment is [positive/negative/neutral/mixed] with [high/medium/low] confidence.
[One sentence narrative summary of the overall discussion tone]

Be specific and base your analysis only on the provided summaries."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _flatten_comments(comments: list[Comment], max_chars: int = 2000) -> str:
    """Flatten comment tree into a text block for the prompt."""
    lines: list[str] = []
    total_chars = 0

    def _walk(comment_list: list[Comment], indent: int = 0) -> None:
        nonlocal total_chars
        for c in comment_list:
            if total_chars >= max_chars:
                return
            prefix = "  " * indent
            score_str = f"[{c.score:+d}]" if c.score else ""
            line = f"{prefix}{score_str} {c.body[:300]}"
            lines.append(line)
            total_chars += len(line)
            if c.replies:
                _walk(c.replies, indent + 1)

    _walk(comments)
    return "\n".join(lines) if lines else "[No comment/reply context available]"


def build_sentiment_prompt(
    post: Post,
    *,
    topic: str,
) -> list[dict]:
    """Build the message list for sentiment analysis of a single post."""
    thread_block = _flatten_comments(post.comments)

    community = post.community or "unknown"
    region = post.detected_region or "global"
    language = post.detected_language or "unknown"
    title = post.title or ""
    content = post.text or ""

    user_content = f"""Analyze this social/community discussion thread about '{topic}'.

<user_post>
PRIMARY POST TITLE: {title[:600]}

PRIMARY POST CONTENT: {content[:1800]}

SOURCE: {post.platform} | COMMUNITY: {community} | REGION: {region} | LANGUAGE: {language}

THREAD CONTEXT (comments/replies):
{thread_block}
</user_post>

Assess the overall stance and emotional tone. If comments are sparse, rely on the post itself."""

    return [
        {"role": "system", "content": SENTIMENT_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]


def build_sentiment_retry_prompt(
    *,
    original_response: str,
    topic: str,
) -> list[dict]:
    """Build a retry prompt with stricter format instructions."""
    user_content = f"""Your previous analysis of a post about '{topic}' could not be parsed.

Your previous response was:
{original_response[:500]}

Please re-analyze and respond in EXACTLY the required format."""

    return [
        {"role": "system", "content": SENTIMENT_RETRY_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]


def build_thematic_prompt(
    *,
    phrase: str,
    summaries: list[str],
    post_count: int,
) -> list[dict]:
    """Build the message list for thematic analysis of a batch of posts."""
    summary_text = "\n".join(summaries)

    user_content = f"""Analyze {post_count} social posts about "{phrase}".

Here are summaries of each post with their sentiment and region:

{summary_text}

Provide your analysis following the format specified."""

    return [
        {"role": "system", "content": THEMATIC_PROMPT_V1},
        {"role": "user", "content": user_content},
    ]
