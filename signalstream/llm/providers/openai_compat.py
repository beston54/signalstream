"""OpenAI-compatible endpoint provider."""
from __future__ import annotations

import logging
import random
import time

import requests

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(BaseProvider):
    """Generic OpenAI-compatible chat completions provider."""

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        if not provider_config.endpoint:
            raise ValueError(
                "OpenAI-compatible provider requires an endpoint URL"
            )
        self._endpoint = provider_config.endpoint.rstrip("/")
        self._api_key = provider_config.api_key or ""

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()

        payload = {
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self._endpoint}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "OpenAI-compat request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable
