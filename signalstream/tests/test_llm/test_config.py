"""Tests for signalstream.llm.config."""
from __future__ import annotations

import pytest

from signalstream.llm.config import CompletionConfig, ProviderConfig


class TestProviderConfig:
    def test_claude_config(self) -> None:
        cfg = ProviderConfig(
            provider="claude", api_key="sk-ant-test",
            model="claude-haiku-4-5-20251001",
        )
        assert cfg.provider == "claude"
        assert cfg.endpoint is None

    def test_ollama_config(self) -> None:
        cfg = ProviderConfig(provider="ollama", model="llama3.1:8b")
        assert cfg.api_key is None
        assert cfg.endpoint is None

    def test_openai_compat_config(self) -> None:
        cfg = ProviderConfig(
            provider="openai-compat",
            api_key="sk-test",
            model="gpt-4o",
            endpoint="https://api.openai.com/v1",
        )
        assert cfg.endpoint == "https://api.openai.com/v1"

    def test_provider_must_be_valid(self) -> None:
        with pytest.raises(ValueError, match="Invalid provider"):
            ProviderConfig(provider="invalid", model="x")


class TestCompletionConfig:
    def test_defaults(self) -> None:
        cfg = CompletionConfig()
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 1024

    def test_custom_values(self) -> None:
        cfg = CompletionConfig(temperature=0.7, max_tokens=300)
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 300

    def test_temperature_bounds(self) -> None:
        with pytest.raises(ValueError, match="temperature"):
            CompletionConfig(temperature=-0.1)
        with pytest.raises(ValueError, match="temperature"):
            CompletionConfig(temperature=2.1)

    def test_max_tokens_positive(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            CompletionConfig(max_tokens=0)
