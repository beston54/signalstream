"""Batch thematic analysis with chunking for large collections.

Processes analyzed posts to identify cross-cutting themes, regional patterns,
and novel ideas. For collections exceeding 50 posts, chunks the input and
runs a consolidation pass (BOARD-011).
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any

from signalstream.analyzers.base import BaseAnalyzer
from signalstream.analyzers.prompts import build_thematic_prompt
from signalstream.db.models import Post, SentimentResult, Theme
from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 50
_CHARS_PER_TOKEN = 4


def create_aggregation_summary(
    analyzed_posts: list[tuple[Post, SentimentResult]],
) -> list[str]:
    """Create numbered summaries of analyzed posts for thematic analysis.

    Samples up to 50 posts with a deterministic seed for reproducibility.
    """
    sample = analyzed_posts
    if len(analyzed_posts) > _CHUNK_SIZE:
        seed = hash(tuple(p.id for p, _ in analyzed_posts))
        rng = random.Random(seed)
        sample = rng.sample(analyzed_posts, _CHUNK_SIZE)

    summaries: list[str] = []
    for i, (post, result) in enumerate(sample, 1):
        region = post.detected_region or "global"
        line = f"{i}. [{result.sentiment}] [{region}] {result.key_point}"
        summaries.append(line)

    return summaries


def parse_theme_response(response: str) -> dict[str, Any]:
    """Parse the structured thematic analysis response into a dict."""
    result: dict[str, Any] = {
        "major_themes": [],
        "novel_ideas": [],
        "key_critiques": [],
        "regional_patterns": {},
        "sentiment_summary": {
            "overall": "unknown",
            "confidence": "unknown",
            "narrative": "",
        },
    }

    if not response or not response.strip():
        return result

    # Parse major themes
    themes_match = re.search(
        r'MAJOR[_\s]?THEMES?:?\s*\n((?:[\d\.\-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if themes_match:
        themes_text = themes_match.group(1)
        theme_lines = re.findall(r'[\d\.\-\*]\s*(.+?)(?:\n|$)', themes_text)
        for line in theme_lines[:5]:
            theme_name = re.sub(r'^\d+\.\s*', '', line).strip()
            theme_name = re.sub(r'^[\.\-\*\)\s]+', '', theme_name).strip()

            if '|' in theme_name:
                parts = theme_name.split('|', 1)
                label = parts[0].strip()
                description = parts[1].strip()
            else:
                parts = theme_name.split(' - ', 1)
                label = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else ""

            pct_match = re.search(r'(\d+)\s*%', line)
            percentage = int(pct_match.group(1)) if pct_match else 0

            if label:
                result["major_themes"].append({
                    "theme": label,
                    "description": description,
                    "percentage": percentage,
                })

    # Parse novel ideas
    novel_match = re.search(
        r'NOVEL[_\s]?IDEAS?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if novel_match:
        ideas_text = novel_match.group(1)
        ideas = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', ideas_text)
        result["novel_ideas"] = [idea.strip() for idea in ideas if idea.strip()]

    # Parse key critiques
    critiques_match = re.search(
        r'KEY[_\s]?CRITIQUES?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if critiques_match:
        critiques_text = critiques_match.group(1)
        critiques = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', critiques_text)
        for c in critiques:
            freq_pat = r'\((?:frequency:?\s*)?(frequent|occasional|rare)\)'
            freq_match = re.search(freq_pat, c, re.IGNORECASE)
            strip_pat = r'\s*\((?:frequency:?\s*)?(?:frequent|occasional|rare)\)'
            critique_text = re.sub(strip_pat, '', c).strip()
            result["key_critiques"].append({
                "critique": critique_text,
                "frequency": freq_match.group(1).lower() if freq_match else "unknown",
            })

    # Parse regional patterns
    regional_match = re.search(
        r'REGIONAL[_\s]?PATTERNS?:?\s*\n((?:[-\*].*\n?)+)',
        response, re.IGNORECASE,
    )
    if regional_match:
        regional_text = regional_match.group(1)
        patterns = re.findall(r'[-\*]\s*(.+?)(?:\n|$)', regional_text)
        for p in patterns:
            if ':' in p:
                region, pattern = p.split(':', 1)
                result["regional_patterns"][region.strip()] = pattern.strip()

    # Parse sentiment summary
    sentiment_match = re.search(
        r'SENTIMENT[_\s]?SUMMARY:?\s*\n(.+?)(?:\n\n|\Z)',
        response, re.IGNORECASE | re.DOTALL,
    )
    if sentiment_match:
        summary_text = sentiment_match.group(1).strip()
        overall_match = re.search(
            r'is\s+(positive|negative|neutral|mixed)', summary_text, re.IGNORECASE,
        )
        conf_match = re.search(
            r'(high|medium|low)\s+confidence', summary_text, re.IGNORECASE,
        )
        if overall_match:
            result["sentiment_summary"]["overall"] = overall_match.group(1).lower()
        if conf_match:
            result["sentiment_summary"]["confidence"] = conf_match.group(1).lower()

        lines = summary_text.split('\n')
        if len(lines) > 1:
            result["sentiment_summary"]["narrative"] = lines[-1].strip()
        else:
            result["sentiment_summary"]["narrative"] = summary_text

    return result


class ThematicAnalyzer(BaseAnalyzer):
    """Batch theme extraction with chunking for large collections."""

    def __init__(
        self,
        *,
        provider: BaseProvider,
        model: str,
        completion_config: CompletionConfig | None = None,
        chunk_size: int = _CHUNK_SIZE,
    ) -> None:
        super().__init__(
            provider=provider, model=model,
            completion_config=completion_config or CompletionConfig(max_tokens=2048),
        )
        self._chunk_size = chunk_size

    def analyze(
        self,
        *,
        analyzed_posts: list[tuple[Post, SentimentResult]],
        phrase: str,
    ) -> list[Theme]:
        if len(analyzed_posts) <= self._chunk_size:
            return self._analyze_chunk(analyzed_posts, phrase=phrase)

        logger.info(
            "Chunking %d posts into groups of %d for thematic analysis",
            len(analyzed_posts), self._chunk_size,
        )
        all_chunk_themes: list[dict] = []
        for i in range(0, len(analyzed_posts), self._chunk_size):
            chunk = analyzed_posts[i:i + self._chunk_size]
            chunk_themes = self._analyze_chunk_raw(chunk, phrase=phrase)
            all_chunk_themes.extend(chunk_themes)

        return self._consolidate_themes(all_chunk_themes, total_posts=len(analyzed_posts))

    def _analyze_chunk(
        self,
        chunk: list[tuple[Post, SentimentResult]],
        *,
        phrase: str,
    ) -> list[Theme]:
        raw_themes = self._analyze_chunk_raw(chunk, phrase=phrase)
        total = len(chunk)
        themes: list[Theme] = []

        for t in raw_themes:
            pct = t.get("percentage", 0)
            post_count = max(1, round(pct / 100 * total)) if pct > 0 else 0

            themes.append(Theme(
                name=t.get("theme", "Unknown"),
                description=t.get("description", ""),
                percentage=float(pct),
                post_count=post_count,
                sentiment_skew="neutral",
                representative_quotes=[],
            ))

        themes.sort(key=lambda th: th.post_count, reverse=True)
        return themes

    def _analyze_chunk_raw(
        self,
        chunk: list[tuple[Post, SentimentResult]],
        *,
        phrase: str,
    ) -> list[dict]:
        summaries = create_aggregation_summary(chunk)
        messages = build_thematic_prompt(
            phrase=phrase, summaries=summaries, post_count=len(chunk),
        )
        response = self._complete(messages)
        parsed = parse_theme_response(response)
        return parsed.get("major_themes", [])

    def _consolidate_themes(
        self,
        all_themes: list[dict],
        *,
        total_posts: int,
    ) -> list[Theme]:
        if not all_themes:
            return []

        theme_list = "\n".join(
            f"{i+1}. {t.get('theme', 'Unknown')} | {t.get('description', '')}"
            for i, t in enumerate(all_themes)
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert analyst. Merge the following theme lists from "
                    "multiple chunks into a single consolidated list. Combine duplicates, "
                    "keep the most representative label, and recalculate approximate "
                    "percentages based on the total.\n\n"
                    "Respond in EXACTLY this format:\n"
                    "MAJOR_THEMES:\n"
                    "1. [Theme Label] | [Description]\n"
                    "2. [Theme Label] | [Description]\n"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Consolidate these {len(all_themes)} themes from "
                    f"{total_posts} total posts:\n\n{theme_list}"
                ),
            },
        ]

        response = self._complete(messages)
        parsed = parse_theme_response(response)
        consolidated = parsed.get("major_themes", [])

        themes: list[Theme] = []
        for t in consolidated:
            pct = t.get("percentage", 0)
            if pct == 0 and consolidated:
                pct = round(100 / len(consolidated), 1)
            post_count = max(1, round(pct / 100 * total_posts)) if pct > 0 else 0

            themes.append(Theme(
                name=t.get("theme", "Unknown"),
                description=t.get("description", ""),
                percentage=float(pct),
                post_count=post_count,
                sentiment_skew="neutral",
                representative_quotes=[],
            ))

        themes.sort(key=lambda th: th.post_count, reverse=True)
        return themes
