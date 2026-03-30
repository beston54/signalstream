"""Tests for signalstream.analyzers.schemas — output validation (BOARD-012)."""
from __future__ import annotations

import pytest

from signalstream.analyzers.schemas import (
    ValidationError,
    validate_sentiment_result,
    validate_theme,
)
from signalstream.db.models import SentimentResult, Theme


class TestValidateSentimentResult:
    def test_valid_result(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "Users love this feature",
            "sarcasm_detected": False,
        }
        result = validate_sentiment_result(raw)
        assert isinstance(result, SentimentResult)
        assert result.sentiment == "positive"
        assert result.confidence == 0.9

    def test_invalid_sentiment_value(self) -> None:
        raw = {
            "sentiment": "happy",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="sentiment"):
            validate_sentiment_result(raw)

    def test_invalid_emotion_value(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "flabbergasted",
            "confidence": 0.9,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="emotion"):
            validate_sentiment_result(raw)

    def test_confidence_out_of_range_high(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 1.5,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_confidence_out_of_range_low(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": -0.1,
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_key_point_too_long(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "x" * 201,
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="key_point"):
            validate_sentiment_result(raw)

    def test_key_point_empty(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            "confidence": 0.9,
            "key_point": "",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="key_point"):
            validate_sentiment_result(raw)

    def test_missing_required_field(self) -> None:
        raw = {
            "sentiment": "positive",
            "emotion": "enthusiastic",
            # missing confidence
            "key_point": "Good stuff",
            "sarcasm_detected": False,
        }
        with pytest.raises(ValidationError, match="confidence"):
            validate_sentiment_result(raw)

    def test_optional_fields_have_defaults(self) -> None:
        raw = {
            "sentiment": "neutral",
            "emotion": "curious",
            "confidence": 0.7,
            "key_point": "Interesting topic",
            "sarcasm_detected": False,
        }
        result = validate_sentiment_result(raw)
        assert result.secondary_emotion == "none"
        assert result.emotion_intensity == "moderate"
        assert result.emotional_driver == ""

    def test_with_optional_fields(self) -> None:
        raw = {
            "sentiment": "mixed",
            "emotion": "skeptical",
            "secondary_emotion": "curious",
            "emotion_intensity": "strong",
            "confidence": 0.6,
            "key_point": "Mixed feelings about this",
            "emotional_driver": "Uncertainty about outcomes",
            "sarcasm_detected": True,
        }
        result = validate_sentiment_result(raw)
        assert result.secondary_emotion == "curious"
        assert result.emotion_intensity == "strong"
        assert result.emotional_driver == "Uncertainty about outcomes"
        assert result.sarcasm_detected is True


class TestValidateTheme:
    def test_valid_theme(self) -> None:
        raw = {
            "name": "Battery Life Complaints",
            "description": "Users report rapid battery drain",
            "percentage": 45.0,
            "post_count": 18,
            "sentiment_skew": "negative",
            "representative_quotes": ["Battery dies in 2 hours"],
        }
        theme = validate_theme(raw)
        assert isinstance(theme, Theme)
        assert theme.name == "Battery Life Complaints"

    def test_invalid_sentiment_skew(self) -> None:
        raw = {
            "name": "Theme",
            "description": "Desc",
            "percentage": 10.0,
            "post_count": 5,
            "sentiment_skew": "very_negative",
        }
        with pytest.raises(ValidationError, match="sentiment_skew"):
            validate_theme(raw)

    def test_percentage_out_of_range(self) -> None:
        raw = {
            "name": "Theme",
            "description": "Desc",
            "percentage": 150.0,
            "post_count": 5,
            "sentiment_skew": "positive",
        }
        with pytest.raises(ValidationError, match="percentage"):
            validate_theme(raw)
