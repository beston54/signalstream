"""
Shared LLM client module.

Provides a unified interface for calling LLM providers (Claude, Ollama)
with consistent retry/backoff logic, provider routing, and prompt safety.

All LLM calls in the pipeline should go through LLMClient (or the
backward-compatible call_llm() module function) to ensure:
- Correct provider routing based on config
- System/user message separation (prompt injection defense)
- Per-instance Anthropic client (connection pool reuse, thread-safe)
- Consistent retry and error handling
- Provider tracking for audit/logging
"""

import logging
import os
import random
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider detection (stateless — safe to call from anywhere)
# ---------------------------------------------------------------------------

def get_provider(config: dict) -> str:
    """
    Determine which LLM provider to use based on config.

    Priority:
    1. config.analysis.provider (claude | ollama | auto)
    2. auto: use Claude if API key is available, else Ollama
    """
    analysis = config.get("analysis", {})
    provider = str(analysis.get("provider", "auto")).strip().lower()

    if provider == "claude":
        return "claude"
    if provider == "ollama":
        return "ollama"

    # auto mode: prefer Claude if API key is available via env var
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if api_key:
        return "claude"

    return "ollama"


def _get_claude_config(config: dict) -> dict:
    """Return Claude API configuration with defaults.

    API keys are loaded exclusively from environment variables.
    """
    analysis = config.get("analysis", {})
    claude_cfg = analysis.get("claude", {})

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it with: export ANTHROPIC_API_KEY='your-key-here'"
        )

    return {
        "model": claude_cfg.get("model", "claude-haiku-4-5-20251001"),
        "api_key": api_key,
        "max_tokens": int(claude_cfg.get("max_tokens", 300)),
        "temperature": float(claude_cfg.get("temperature", 0.0)),
    }


# ---------------------------------------------------------------------------
# LLMClient — thread-safe, instance-based
# ---------------------------------------------------------------------------

class LLMClient:
    """Per-pipeline-run LLM client with its own provider lock and Anthropic client.

    Creating one instance per pipeline run eliminates global mutable state and
    makes concurrent pipeline runs safe.
    """

    def __init__(self, *, provider_lock_enabled: bool = True):
        self._lock = threading.Lock()
        self._anthropic_client: Optional[Any] = None
        self._anthropic_api_key: Optional[str] = None
        self._locked_provider: Optional[str] = None
        self._provider_lock_enabled = provider_lock_enabled
        self._providers_used: list = []

    # -- provider lock -------------------------------------------------------

    def reset_provider_lock(self) -> None:
        """Reset the provider lock. Call at the start of each batch."""
        with self._lock:
            self._locked_provider = None

    @property
    def locked_provider(self) -> Optional[str]:
        return self._locked_provider

    @property
    def providers_used(self) -> list:
        return list(self._providers_used)

    def _record_provider_success(self, provider: str) -> None:
        with self._lock:
            if provider not in self._providers_used:
                self._providers_used.append(provider)
            if self._provider_lock_enabled and self._locked_provider is None:
                self._locked_provider = provider
                logger.info("Provider locked to '%s' for this batch.", provider)

    # -- Anthropic client (lazy, thread-safe) --------------------------------

    def _get_anthropic_client(self, api_key: str) -> Any:
        with self._lock:
            if self._anthropic_client is None or self._anthropic_api_key != api_key:
                if anthropic is None:
                    raise RuntimeError(
                        "anthropic package not installed. Run: pip install anthropic"
                    )
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
                self._anthropic_api_key = api_key
            return self._anthropic_client

    # -- Provider-specific calls ---------------------------------------------

    def _call_claude(
        self,
        *,
        system_prompt: str,
        user_content: str,
        config: dict,
        max_tokens: Optional[int] = None,
        retries: int = 3,
    ) -> Optional[str]:
        """Call Claude API with system/user message separation."""
        claude_cfg = _get_claude_config(config)
        api_key = claude_cfg["api_key"]
        if not api_key:
            logger.error(
                "No Anthropic API key configured. "
                "Set ANTHROPIC_API_KEY or analysis.claude.api_key"
            )
            return None

        client = self._get_anthropic_client(api_key)

        base_delay = 2  # seconds

        for attempt in range(retries):
            try:
                kwargs: Dict[str, Any] = {
                    "model": claude_cfg["model"],
                    "max_tokens": max_tokens or claude_cfg["max_tokens"],
                    "temperature": claude_cfg["temperature"],
                    "messages": [{"role": "user", "content": user_content}],
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                message = client.messages.create(**kwargs)

                if message.content and len(message.content) > 0:
                    return message.content[0].text
                return None

            except (
                anthropic.BadRequestError,
                anthropic.AuthenticationError,
                anthropic.PermissionDeniedError,
                anthropic.NotFoundError,
            ) as e:
                logger.error("Claude non-retryable error (HTTP %s): %s", getattr(e, 'status_code', '?'), e)
                raise

            except anthropic.RateLimitError as e:
                retry_after = None
                if hasattr(e, 'response') and e.response is not None:
                    retry_after = e.response.headers.get('retry-after')
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except (ValueError, TypeError):
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Claude rate limit hit (attempt %d/%d), Retry-After: %s s",
                        attempt + 1, retries, delay,
                    )
                else:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Claude rate limit hit (attempt %d/%d), backing off %.1f s",
                        attempt + 1, retries, delay,
                    )
                time.sleep(delay)

            except anthropic.APIError as e:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.error("Claude API error (attempt %d/%d): %s — retrying in %.1f s", attempt + 1, retries, e, delay)
                time.sleep(delay)

            except Exception as e:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.error("Unexpected error calling Claude (attempt %d/%d): %s — retrying in %.1f s", attempt + 1, retries, e, delay)
                time.sleep(delay)

        return None

    def _call_ollama(
        self,
        *,
        system_prompt: str,
        user_content: str,
        config: dict,
        max_tokens: Optional[int] = None,
        retries: int = 3,
    ) -> Optional[str]:
        """Call Ollama API with system/user message separation."""
        ollama_config = config.get("ollama", {})
        base_url = ollama_config.get("base_url", "http://localhost:11434")
        model = ollama_config.get("model", "gemma2:9b")
        timeout = ollama_config.get("timeout", 120)

        num_predict = max_tokens or 200

        base_delay = 2  # seconds

        for attempt in range(retries):
            try:
                payload: Dict[str, Any] = {
                    "model": model,
                    "prompt": user_content,
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                        "num_predict": num_predict,
                    },
                }
                if system_prompt:
                    payload["system"] = system_prompt

                response = requests.post(
                    f"{base_url}/api/generate",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json().get("response", "")

            except requests.exceptions.Timeout:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning("Ollama timeout (attempt %d/%d), backing off %.1f s", attempt + 1, retries, delay)
                time.sleep(delay)
            except requests.exceptions.RequestException as e:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.error("Ollama request failed (attempt %d/%d): %s — retrying in %.1f s", attempt + 1, retries, e, delay)
                time.sleep(delay)

        return None

    # -- Unified entry point -------------------------------------------------

    def call(
        self,
        *,
        user_content: str,
        config: dict,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        retries: int = 3,
        allow_fallback: bool = True,
    ) -> Tuple[Optional[str], str]:
        """
        Call the configured LLM provider and return (response_text, provider_used).

        Args:
            user_content: The user-facing prompt content (untrusted data goes here).
            config: Full pipeline configuration dict.
            system_prompt: System instructions (trusted instructions go here).
            max_tokens: Override max tokens for this call.
            retries: Number of retry attempts per provider.
            allow_fallback: If True and provider is 'auto', fall back to Ollama
                when Claude fails.

        Returns:
            Tuple of (response_text, provider_name).
        """
        provider = get_provider(config)

        if self._locked_provider is not None:
            provider = self._locked_provider

        if provider == "claude":
            response = self._call_claude(
                system_prompt=system_prompt,
                user_content=user_content,
                config=config,
                max_tokens=max_tokens,
                retries=retries,
            )
            if response is not None:
                self._record_provider_success("claude")
                return response, "claude"

            if self._locked_provider == "claude":
                logger.error(
                    "Claude failed and provider is locked to 'claude' for this batch. "
                    "Not falling back to Ollama to preserve data integrity."
                )
                return None, "claude"

            if allow_fallback and self._locked_provider is None:
                logger.warning(
                    "Claude failed on first call — trying Ollama as initial provider."
                )
                response = self._call_ollama(
                    system_prompt=system_prompt,
                    user_content=user_content,
                    config=config,
                    max_tokens=max_tokens,
                    retries=retries,
                )
                if response is not None:
                    self._record_provider_success("ollama")
                    return response, "ollama"

            return None, "claude"

        # Ollama path
        response = self._call_ollama(
            system_prompt=system_prompt,
            user_content=user_content,
            config=config,
            max_tokens=max_tokens,
            retries=retries,
        )
        if response is not None:
            self._record_provider_success("ollama")
            return response, "ollama"

        return None, "ollama"


# ---------------------------------------------------------------------------
# Backward-compatible module-level API
# ---------------------------------------------------------------------------
# A default instance is used by the module-level functions so existing code
# (call_llm(...), reset_provider_lock()) continues to work unchanged.
# New pipeline runs should create their own LLMClient instance instead.
# ---------------------------------------------------------------------------

_default_client = LLMClient()


def reset_provider_lock() -> None:
    """Reset the provider lock on the default (module-level) client."""
    _default_client.reset_provider_lock()


def call_llm(
    *,
    user_content: str,
    config: dict,
    system_prompt: str = "",
    max_tokens: Optional[int] = None,
    retries: int = 3,
    allow_fallback: bool = True,
) -> Tuple[Optional[str], str]:
    """
    Call the configured LLM provider and return (response_text, provider_used).

    This is a backward-compatible wrapper around the default LLMClient instance.
    For thread-safe concurrent runs, create your own LLMClient() instead.
    """
    return _default_client.call(
        user_content=user_content,
        config=config,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        retries=retries,
        allow_fallback=allow_fallback,
    )
