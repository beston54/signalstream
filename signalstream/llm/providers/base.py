"""Abstract base for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from signalstream.llm.config import CompletionConfig, ProviderConfig


class BaseProvider(ABC):
    """Abstract LLM provider interface.

    Providers are stateless per-request objects. Each job creates a provider
    instance with credentials from the request. No singletons.
    """

    def __init__(self, provider_config: ProviderConfig) -> None:
        self._provider_config = provider_config

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        """Send a completion request to the LLM provider."""
        ...
