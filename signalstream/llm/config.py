"""LLM provider configuration dataclasses.

Per-request configuration — never a singleton. Built from request headers
by middleware, passed to the job as a parameter, discarded on completion.

Board amendments incorporated:
- BOARD-006: CompletionConfig with temperature=0.0 default for deterministic
  classification.
"""
from __future__ import annotations

from dataclasses import dataclass

VALID_PROVIDERS = frozenset({"claude", "ollama", "openai-compat"})


@dataclass
class ProviderConfig:
    """Per-request LLM provider configuration.

    Attributes:
        provider: One of "claude", "ollama", "openai-compat".
        api_key: API key for the provider. None for Ollama.
        model: Model identifier (e.g., "claude-haiku-4-5-20251001", "llama3.1:8b").
        endpoint: Custom endpoint URL for openai-compat providers. None for others.
    """
    provider: str
    model: str
    api_key: str | None = None
    endpoint: str | None = None

    def __post_init__(self) -> None:
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'. "
                f"Must be one of: {', '.join(sorted(VALID_PROVIDERS))}"
            )


@dataclass
class CompletionConfig:
    """Per-call configuration for LLM requests.

    Attributes:
        temperature: Sampling temperature. 0.0 = deterministic (default for
            sentiment classification). Range: [0.0, 2.0].
        max_tokens: Maximum tokens in the response. Must be > 0.
    """
    temperature: float = 0.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError(
                f"temperature must be between 0.0 and 2.0, got {self.temperature}"
            )
        if self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be positive, got {self.max_tokens}"
            )
