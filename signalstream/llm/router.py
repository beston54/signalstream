"""LLM router — provider selection and pre-flight validation.

No auto-fallback between providers. The user picks their provider explicitly.
Pre-flight check confirms the provider is reachable before the pipeline starts.
"""
from __future__ import annotations

import logging

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider
from signalstream.llm.providers.claude import ClaudeProvider
from signalstream.llm.providers.ollama import OllamaProvider
from signalstream.llm.providers.openai_compat import OpenAICompatProvider
from signalstream.llm.safety import validate_endpoint

logger = logging.getLogger(__name__)

def _get_provider_map() -> dict[str, type[BaseProvider]]:
    """Build provider map at call time so module-level names are resolvable."""
    return {
        "claude": ClaudeProvider,
        "ollama": OllamaProvider,
        "openai-compat": OpenAICompatProvider,
    }


class LLMRouter:
    """Routes LLM requests to the configured provider."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

        # SSRF validation for custom endpoints (before creating the provider)
        if config.provider == "openai-compat" and config.endpoint:
            validate_endpoint(config.endpoint)

        provider_map = _get_provider_map()
        provider_cls = provider_map.get(config.provider)
        if provider_cls is None:
            raise ValueError(f"Unknown provider: {config.provider}")

        self._provider: BaseProvider = provider_cls(config)
        logger.info("LLM router initialized with provider: %s", config.provider)

    @property
    def provider(self) -> BaseProvider:
        """The underlying provider instance."""
        return self._provider

    def preflight_check(self) -> bool:
        """Test that the provider is reachable with a minimal API call."""
        try:
            response = self._provider.complete(
                messages=[{"role": "user", "content": "ping"}],
                model=self._config.model,
                config=CompletionConfig(temperature=0.0, max_tokens=5),
            )
            logger.info(
                "Pre-flight check passed for %s (response length: %d)",
                self._config.provider, len(response),
            )
            return True
        except Exception as e:
            logger.error(
                "Pre-flight check failed for %s: %s",
                self._config.provider, e,
            )
            return False

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        """Delegate a completion request to the provider."""
        return self._provider.complete(messages, model, config)
