"""Output schemas and validation for LLM analysis results.

Validation functions check that LLM output conforms to expected shapes
and value ranges before the data enters the rest of the system (BOARD-012).
"""
from __future__ import annotations

import logging

from signalstream.db.models import SentimentResult, Theme

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral", "mixed"})

VALID_EMOTIONS = frozenset({
    "enthusiastic", "hopeful", "curious", "neutral",
    "skeptical", "concerned", "frustrated", "angry",
})

VALID_INTENSITIES = frozenset({"strong", "moderate", "mild"})

MAX_KEY_POINT_LENGTH = 200


class ValidationError(Exception):
    """Raised when LLM output fails validation."""


def validate_sentiment_result(raw: dict) -> SentimentResult:
    """Validate and construct a SentimentResult from a raw dict."""
    errors: list[str] = []

    sentiment = raw.get("sentiment", "")
    if sentiment not in VALID_SENTIMENTS:
        errors.append(
            f"sentiment must be one of {sorted(VALID_SENTIMENTS)}, got '{sentiment}'"
        )

    emotion = raw.get("emotion", "")
    if emotion not in VALID_EMOTIONS:
        errors.append(
            f"emotion must be one of {sorted(VALID_EMOTIONS)}, got '{emotion}'"
        )

    confidence = raw.get("confidence")
    if confidence is None:
        errors.append("confidence is required")
    else:
        try:
            confidence = float(confidence)
            if not (0.0 <= confidence <= 1.0):
                errors.append(f"confidence must be in [0.0, 1.0], got {confidence}")
        except (ValueError, TypeError):
            errors.append(f"confidence must be a float, got {type(confidence).__name__}")

    key_point = raw.get("key_point", "")
    if not key_point or not str(key_point).strip():
        errors.append("key_point must be a non-empty string")
    elif len(str(key_point)) > MAX_KEY_POINT_LENGTH:
        errors.append(
            f"key_point must be under {MAX_KEY_POINT_LENGTH} characters, "
            f"got {len(str(key_point))}"
        )

    sarcasm_detected = raw.get("sarcasm_detected")
    if sarcasm_detected is None:
        sarcasm_detected = False

    if errors:
        raise ValidationError("; ".join(errors))

    secondary_emotion = raw.get("secondary_emotion", "none")
    emotion_intensity = raw.get("emotion_intensity", "moderate")
    emotional_driver = raw.get("emotional_driver", "")

    return SentimentResult(
        sentiment=sentiment,
        emotion=emotion,
        confidence=float(confidence),
        key_point=str(key_point).strip(),
        sarcasm_detected=bool(sarcasm_detected),
        secondary_emotion=str(secondary_emotion),
        emotion_intensity=str(emotion_intensity),
        emotional_driver=str(emotional_driver),
    )


def validate_theme(raw: dict) -> Theme:
    """Validate and construct a Theme from a raw dict."""
    errors: list[str] = []

    name = raw.get("name", "")
    if not name or not str(name).strip():
        errors.append("name must be a non-empty string")

    description = raw.get("description", "")

    percentage = raw.get("percentage", 0.0)
    try:
        percentage = float(percentage)
        if not (0.0 <= percentage <= 100.0):
            errors.append(f"percentage must be in [0.0, 100.0], got {percentage}")
    except (ValueError, TypeError):
        errors.append(f"percentage must be a float, got {type(percentage).__name__}")

    post_count = raw.get("post_count", 0)

    sentiment_skew = raw.get("sentiment_skew", "")
    if sentiment_skew not in VALID_SENTIMENTS:
        errors.append(
            f"sentiment_skew must be one of {sorted(VALID_SENTIMENTS)}, "
            f"got '{sentiment_skew}'"
        )

    if errors:
        raise ValidationError("; ".join(errors))

    representative_quotes = raw.get("representative_quotes", [])
    if not isinstance(representative_quotes, list):
        representative_quotes = []

    return Theme(
        name=str(name).strip(),
        description=str(description).strip(),
        percentage=float(percentage),
        post_count=int(post_count),
        sentiment_skew=str(sentiment_skew),
        representative_quotes=[str(q) for q in representative_quotes],
    )
