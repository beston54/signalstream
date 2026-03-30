"""Per-post sentiment analysis with retry, validation, and checkpointing.

Processes each post through the LLM provider, parses the structured output,
validates it, and returns results. Supports progress callbacks for UI updates.

Checkpointing (BOARD-008): The caller (pipeline layer) writes each result to
the database immediately after receiving it. This module yields results one
at a time via the analyze() return value.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from signalstream.analyzers.base import BaseAnalyzer, ProgressCallback
from signalstream.analyzers.prompts import (
    build_sentiment_prompt,
    build_sentiment_retry_prompt,
)
from signalstream.analyzers.schemas import ValidationError, validate_sentiment_result
from signalstream.db.models import Post, SentimentResult
from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_CONFIDENCE_MAP = {
    "certain": 0.9,
    "uncertain": 0.5,
    "questioning": 0.3,
}


def parse_sentiment_response(response: str) -> dict | None:
    """Parse the structured LLM response into a raw dict.

    Returns None if the response cannot be parsed into the expected format.
    """
    if not response or not response.strip():
        return None

    response_text = response.strip()

    patterns = {
        "sentiment": r"sentiment:\s*(positive|negative|neutral|mixed)",
        "emotion": r"primary[_\s]?emotion:\s*(\w+)",
        "secondary_emotion": r"secondary[_\s]?emotion:\s*(\w+|none)",
        "emotion_intensity": r"emotion[_\s]?intensity:\s*(strong|moderate|mild)",
        "confidence": r"confidence:\s*(certain|uncertain|questioning)",
        "key_point": r"key[_\s]?point:\s*(.+?)(?:\n|$)",
        "emotional_driver": r"emotional[_\s]?driver:\s*(.+?)(?:\n|$)",
        "sarcasm_detected": r"sarcasm[_\s]?detected:\s*(true|false)",
    }

    result: dict = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            result[field] = value

    if "sentiment" not in result:
        return None

    result["sentiment"] = result["sentiment"].lower()
    result["emotion"] = result.get("emotion", "neutral").lower()
    result["secondary_emotion"] = result.get("secondary_emotion", "none").lower()
    result["emotion_intensity"] = result.get("emotion_intensity", "moderate").lower()

    conf_str = result.get("confidence", "uncertain").lower()
    result["confidence"] = _CONFIDENCE_MAP.get(conf_str, 0.5)

    result["sarcasm_detected"] = result.get("sarcasm_detected", "false").lower() == "true"

    result["key_point"] = result.get("key_point", "Unable to extract key point")[:200]
    result["emotional_driver"] = result.get("emotional_driver", "")[:200]

    return result


class SentimentAnalyzer(BaseAnalyzer):
    """Per-post sentiment analysis with retry on parse failure."""

    def analyze(
        self,
        *,
        posts: list[Post],
        topic: str,
        progress_callback: ProgressCallback | None = None,
    ) -> list[tuple[Post, SentimentResult]]:
        results: list[tuple[Post, SentimentResult]] = []
        total = len(posts)
        skipped = 0

        for i, post in enumerate(posts):
            try:
                result = self._analyze_single(post, topic=topic)
                if result is not None:
                    results.append((post, result))
                else:
                    skipped += 1
                    logger.warning(
                        "Skipped post %s after failed retry (post %d/%d)",
                        post.id, i + 1, total,
                    )
            except Exception as e:
                skipped += 1
                logger.error(
                    "Error analyzing post %s: %s (post %d/%d)",
                    post.id, e, i + 1, total,
                )

            if progress_callback:
                progress_callback(i + 1, total, post.id)

        if skipped > 0:
            logger.info(
                "Sentiment analysis complete: %d/%d posts analyzed, %d skipped",
                len(results), total, skipped,
            )

        return results

    def _analyze_single(self, post: Post, *, topic: str) -> SentimentResult | None:
        """Analyze a single post. Retry once on parse failure."""
        messages = build_sentiment_prompt(post, topic=topic)
        response = self._complete(messages)
        raw = parse_sentiment_response(response)

        if raw is not None:
            try:
                return validate_sentiment_result(raw)
            except ValidationError as e:
                logger.warning(
                    "Validation failed for post %s (attempt 1): %s",
                    post.id, e,
                )

        logger.info("Retrying analysis for post %s with stricter prompt", post.id)
        retry_messages = build_sentiment_retry_prompt(
            original_response=response,
            topic=topic,
        )
        retry_response = self._complete(retry_messages)
        retry_raw = parse_sentiment_response(retry_response)

        if retry_raw is not None:
            try:
                return validate_sentiment_result(retry_raw)
            except ValidationError as e:
                logger.warning(
                    "Validation failed for post %s (attempt 2): %s",
                    post.id, e,
                )

        return None
