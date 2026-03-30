"""Ollama local LLM provider."""
from __future__ import annotations

import logging
import random
import time

import requests

from signalstream.llm.config import CompletionConfig, ProviderConfig
from signalstream.llm.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(BaseProvider):
    """Local Ollama provider. Uses the /api/generate endpoint."""

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__(provider_config)
        self._base_url = (provider_config.endpoint or _DEFAULT_OLLAMA_URL).rstrip("/")

    def complete(
        self,
        messages: list[dict],
        model: str,
        config: CompletionConfig | None = None,
    ) -> str:
        cfg = config or CompletionConfig()

        system_prompt = ""
        user_content = ""
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                user_content = msg["content"]

        payload: dict = {
            "model": model,
            "prompt": user_content,
            "stream": False,
            "options": {
                "temperature": cfg.temperature,
                "num_predict": cfg.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        base_delay = 2.0
        retries = 3

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                    timeout=120,
                )
                response.raise_for_status()
                return response.json().get("response", "")

            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Ollama request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries, e, delay,
                )
                time.sleep(delay)

        return ""  # unreachable
