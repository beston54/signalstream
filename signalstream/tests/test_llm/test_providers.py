"""Tests for signalstream.llm.providers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, Mock

import pytest

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider
from signalstream.llm.providers.claude import ClaudeProvider
from signalstream.llm.providers.ollama import OllamaProvider
from signalstream.llm.providers.openai_compat import OpenAICompatProvider


class TestBaseProvider:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseProvider(ProviderConfig(provider="claude", model="x", api_key="k"))


class TestClaudeProvider:
    def test_complete_calls_anthropic(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Positive sentiment")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            result = provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
            )

        assert result == "Positive sentiment"
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_system_prompt_as_top_level_param(self) -> None:
        """Claude's system prompt goes as a top-level kwarg, not in messages."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            provider.complete(
                messages=[
                    {"role": "system", "content": "You are an analyst."},
                    {"role": "user", "content": "Analyze this."},
                ],
                model="claude-haiku-4-5-20251001",
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are an analyst."
        # Messages should only contain non-system messages
        assert all(m["role"] != "system" for m in call_kwargs["messages"])

    def test_custom_completion_config(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        with patch("signalstream.llm.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            config = ProviderConfig(provider="claude", api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            provider = ClaudeProvider(config)
            provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                config=CompletionConfig(temperature=0.5, max_tokens=300),
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 300


class TestOllamaProvider:
    def test_complete_sends_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Neutral analysis"}
        mock_response.raise_for_status = MagicMock()

        with patch("signalstream.llm.providers.ollama.requests.post", return_value=mock_response) as mock_post:
            config = ProviderConfig(provider="ollama", model="gemma2:9b")
            provider = OllamaProvider(config)
            result = provider.complete(
                messages=[
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "Analyze this."},
                ],
                model="gemma2:9b",
            )

        assert result == "Neutral analysis"
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["model"] == "gemma2:9b"
        assert payload["system"] == "Be concise."
        assert payload["prompt"] == "Analyze this."
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.0

    def test_default_endpoint(self) -> None:
        config = ProviderConfig(provider="ollama", model="gemma2:9b")
        provider = OllamaProvider(config)
        assert provider._base_url == "http://localhost:11434"

    def test_custom_endpoint(self) -> None:
        config = ProviderConfig(
            provider="ollama", model="gemma2:9b",
            endpoint="http://localhost:11435",
        )
        provider = OllamaProvider(config)
        assert provider._base_url == "http://localhost:11435"


class TestOpenAICompatProvider:
    def test_complete_sends_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OpenAI result"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("signalstream.llm.providers.openai_compat.requests.post", return_value=mock_response) as mock_post:
            config = ProviderConfig(
                provider="openai-compat",
                api_key="sk-test",
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
            )
            provider = OpenAICompatProvider(config)
            result = provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="gpt-4o",
            )

        assert result == "OpenAI result"
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["model"] == "gpt-4o"
        assert payload["temperature"] == 0.0
        headers = call_kwargs[1]["headers"]
        assert "Bearer sk-test" in headers["Authorization"]

    def test_requires_endpoint(self) -> None:
        config = ProviderConfig(
            provider="openai-compat", api_key="sk-test", model="gpt-4o",
        )
        with pytest.raises(ValueError, match="endpoint"):
            OpenAICompatProvider(config)
