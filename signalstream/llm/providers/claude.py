"""Claude (Anthropic) LLM provider."""
from __future__ import annotations

import logging
import random
import time

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)


def _get_non_retryable() -> tuple:
    if anthropic is None:
        return ()
    return (
        anthropic.BadRequestError,
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
    )


class ClaudeProvider(BaseProvider):
    """Anthropic Claude API provider."""

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        if anthropic is None:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self._client = anthropic.Anthropic(api_key=provider_config.api_key)

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()
        non_retryable = _get_non_retryable()

        # Extract system message — Claude takes it as a top-level param
        system_prompt = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                user_messages.append(msg)

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                kwargs: dict = {
                    "model": model,
                    "max_tokens": cfg.max_tokens,
                    "temperature": cfg.temperature,
                    "messages": user_messages,
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                response = self._client.messages.create(**kwargs)

                if response.content and len(response.content) > 0:
                    return response.content[0].text
                return ""

            except non_retryable:
                raise

            except Exception as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Claude API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable, but satisfies type checker
