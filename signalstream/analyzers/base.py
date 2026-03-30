"""Abstract analyzer base with LLM dependency injection.

Analyzers receive a provider instance at construction time. They never import
the LLM router directly. This makes them testable with a mock provider.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from signalstream.llm.config import CompletionConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Type for progress callbacks: (completed, total, current_item_id)
ProgressCallback = Callable[[int, int, str], None]


class BaseAnalyzer(ABC):
    """Abstract base for LLM-powered analyzers.

    Args:
        provider: The LLM provider instance (injected, never imported).
        model: The model identifier to use for completions.
        completion_config: Optional per-call config. Defaults to temperature=0.0.
    """

    def __init__(
        self,
        *,
        provider: BaseProvider,
        model: str,
        completion_config: CompletionConfig | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._completion_config = completion_config or CompletionConfig()

    @abstractmethod
    def analyze(self, *args: Any, **kwargs: Any) -> Any:
        """Run the analysis. Subclasses define their own signatures."""
        ...

    def _complete(self, messages: list[dict]) -> str:
        """Convenience method to call the provider with standard config."""
        return self._provider.complete(
            messages=messages,
            model=self._model,
            config=self._completion_config,
        )
