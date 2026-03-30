"""Tests for signalstream.llm.router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from signalstream.llm.config import ProviderConfig
from signalstream.llm.router import LLMRouter


class TestLLMRouter:
    def test_creates_claude_provider(self) -> None:
        config = ProviderConfig(
            provider="claude", api_key="sk-ant-test",
            model="claude-haiku-4-5-20251001",
        )
        with patch("signalstream.llm.router.ClaudeProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            router = LLMRouter(config)
            assert router.provider is not None
            mock_cls.assert_called_once_with(config)

    def test_creates_ollama_provider(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        with patch("signalstream.llm.router.OllamaProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            router = LLMRouter(config)
            assert router.provider is not None

    def test_creates_openai_compat_with_ssrf_check(self) -> None:
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test",
            model="gpt-4o", endpoint="https://api.openai.com/v1",
        )
        with patch("signalstream.llm.router.OpenAICompatProvider") as mock_cls, \
             patch("signalstream.llm.router.validate_endpoint") as mock_validate:
            mock_cls.return_value = MagicMock()
            LLMRouter(config)
            mock_validate.assert_called_once_with("https://api.openai.com/v1")

    def test_openai_compat_ssrf_failure_raises(self) -> None:
        from signalstream.llm.safety import SSRFError
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test",
            model="gpt-4o", endpoint="http://10.0.0.1:8080/v1",
        )
        with (
            patch("signalstream.llm.router.validate_endpoint", side_effect=SSRFError("blocked")),
            pytest.raises(SSRFError),
        ):
            LLMRouter(config)

    def test_preflight_check_success(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "pong"

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.preflight_check()
            assert result is True

    def test_preflight_check_failure(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = ConnectionError("refused")

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.preflight_check()
            assert result is False

    def test_complete_delegates_to_provider(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "result text"

        with patch("signalstream.llm.router.OllamaProvider", return_value=mock_provider):
            router = LLMRouter(config)
            result = router.complete(
                messages=[{"role": "user", "content": "test"}],
                model="gemma2:9b",
            )
            assert result == "result text"
