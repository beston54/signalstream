"""Resilient HTTP client with retry, backoff, rate limiting, and size limits.

Shared by collectors and can be used by any component that needs robust HTTP.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque

import requests

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter.

    Args:
        rpm: Maximum requests per minute.
    """

    def __init__(self, rpm: int = 30) -> None:
        self._rpm = rpm
        self._window: deque[float] = deque()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block until a request slot is available."""
        with self._lock:
            now = time.monotonic()
            # Purge requests older than 60 seconds
            while self._window and self._window[0] < now - 60:
                self._window.popleft()

            if len(self._window) >= self._rpm:
                oldest = self._window[0]
                sleep_time = 60 - (now - oldest) + 0.1
                if sleep_time > 0:
                    logger.debug("Rate limiter: sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)

    def record_request(self) -> None:
        """Record that a request was made."""
        with self._lock:
            self._window.append(time.monotonic())

    @property
    def request_count_in_window(self) -> int:
        """Number of requests in the current 60-second window."""
        with self._lock:
            now = time.monotonic()
            while self._window and self._window[0] < now - 60:
                self._window.popleft()
            return len(self._window)


class ResilientClient:
    """HTTP client with automatic retry, exponential backoff, and rate limiting.

    Args:
        user_agent: User-Agent header value.
        retries: Maximum number of retry attempts per request.
        base_delay: Base delay in seconds for exponential backoff.
        connect_timeout: Connection timeout in seconds.
        read_timeout: Read timeout in seconds.
        max_response_bytes: Maximum response size in bytes (0 = unlimited).
        rate_limiter: Optional RateLimiter instance.
    """

    def __init__(
        self,
        user_agent: str = "Signalstream/0.1.0",
        retries: int = 3,
        base_delay: float = 2.0,
        connect_timeout: float = 30.0,
        read_timeout: float = 120.0,
        max_response_bytes: int = 10 * 1024 * 1024,  # 10 MB
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._retries = retries
        self._base_delay = base_delay
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_response_bytes = max_response_bytes
        self._rate_limiter = rate_limiter

    def get(
        self,
        url: str,
        params: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        """Send a GET request with retry and backoff."""
        return self._request("GET", url, params=params, **kwargs)

    def post(
        self,
        url: str,
        json: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        """Send a POST request with retry and backoff."""
        return self._request("POST", url, json=json, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Internal request handler with retry logic."""
        kwargs.setdefault("timeout", (self._connect_timeout, self._read_timeout))

        last_exc: Exception | None = None

        for attempt in range(self._retries + 1):
            try:
                if self._rate_limiter:
                    self._rate_limiter.wait_if_needed()
                    self._rate_limiter.record_request()

                response = self._session.request(method, url, **kwargs)

                # Check response size
                content_length = response.headers.get("Content-Length")
                if (
                    self._max_response_bytes > 0
                    and content_length
                    and int(content_length) > self._max_response_bytes
                ):
                    raise requests.exceptions.ContentDecodingError(
                        f"Response too large: {content_length} bytes "
                        f"(limit: {self._max_response_bytes})"
                    )

                # Handle rate limiting with Retry-After
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and attempt < self._retries:
                        try:
                            delay = float(retry_after)
                        except (ValueError, TypeError):
                            delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "Rate limited (429), retry-after: %.1fs (attempt %d/%d)",
                            delay, attempt + 1, self._retries + 1,
                        )
                        time.sleep(delay)
                        continue

                # Retry on server errors (5xx)
                if response.status_code >= 500 and attempt < self._retries:
                    delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code, delay, attempt + 1, self._retries + 1,
                    )
                    time.sleep(delay)
                    continue

                return response

            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < self._retries:
                    delay = self._base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "%s request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                        method, url, attempt + 1, self._retries + 1, e, delay,
                    )
                    time.sleep(delay)

        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        """Close the underlying session."""
        self._session.close()
