"""Tests for signalstream.collectors.http — resilient HTTP client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from signalstream.collectors.http import RateLimiter, ResilientClient


class TestRateLimiter:
    def test_allows_first_request(self) -> None:
        limiter = RateLimiter(rpm=30)
        # Should not raise or sleep
        limiter.wait_if_needed()
        limiter.record_request()

    def test_tracks_request_count(self) -> None:
        limiter = RateLimiter(rpm=30)
        for _ in range(5):
            limiter.record_request()
        assert limiter.request_count_in_window >= 5


class TestResilientClient:
    def test_get_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}

        with patch.object(requests.Session, "request", return_value=mock_response):
            client = ResilientClient(user_agent="Test/1.0")
            response = client.get("https://example.com/api")
            assert response.json() == {"data": "test"}

    def test_user_agent_set(self) -> None:
        client = ResilientClient(user_agent="Signalstream/0.1.0")
        assert client._session.headers["User-Agent"] == "Signalstream/0.1.0"

    def test_timeout_defaults(self) -> None:
        client = ResilientClient()
        assert client._connect_timeout > 0
        assert client._read_timeout > 0

    def test_retries_on_server_error(self) -> None:
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=error_response
        )
        error_response.headers = {}

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {"ok": True}
        ok_response.headers = {}

        with patch.object(
            requests.Session, "request",
            side_effect=[error_response, ok_response],
        ), patch("signalstream.collectors.http.time.sleep"):
            client = ResilientClient(retries=2)
            response = client.get("https://example.com/api")
            assert response.json() == {"ok": True}

    def test_respects_response_size_limit(self) -> None:
        client = ResilientClient(max_response_bytes=100)
        assert client._max_response_bytes == 100
