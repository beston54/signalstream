"""Tests for signalstream.llm.safety — SSRF validation."""
from __future__ import annotations

import pytest

from signalstream.llm.safety import SSRFError, validate_endpoint


class TestValidateEndpoint:
    """SSRF validation tests with localhost exemption (BOARD-007)."""

    def test_allows_https_public_endpoint(self) -> None:
        """Standard HTTPS endpoints pass validation."""
        validate_endpoint("https://api.openai.com/v1")

    def test_rejects_http_non_localhost(self) -> None:
        """HTTP is rejected for non-localhost addresses."""
        with pytest.raises(SSRFError, match="HTTPS required"):
            validate_endpoint("http://api.openai.com/v1")

    def test_allows_http_localhost(self) -> None:
        """HTTP is allowed for localhost (BOARD-007 exemption)."""
        validate_endpoint("http://localhost:11434")

    def test_allows_http_127_0_0_1(self) -> None:
        """HTTP is allowed for 127.0.0.1."""
        validate_endpoint("http://127.0.0.1:1234")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(SSRFError, match="scheme"):
            validate_endpoint("file:///etc/passwd")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(SSRFError, match="scheme"):
            validate_endpoint("ftp://example.com/file")

    def test_rejects_cloud_metadata_ip(self) -> None:
        """Block link-local / cloud metadata addresses."""
        with pytest.raises(SSRFError):
            validate_endpoint("https://169.254.169.254/latest/meta-data/")

    def test_rejects_private_10_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://10.0.0.1:8080/v1")

    def test_rejects_private_172_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://172.16.0.1:8080/v1")

    def test_rejects_private_192_168_network(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https://192.168.1.1:8080/v1")

    def test_rejects_raw_ip_non_localhost(self) -> None:
        """Require hostnames for non-localhost (prevents DNS rebinding bypass)."""
        with pytest.raises(SSRFError):
            validate_endpoint("https://93.184.216.34/v1")

    def test_allows_raw_ip_localhost(self) -> None:
        """127.x.x.x IPs are exempt from the hostname requirement."""
        validate_endpoint("http://127.0.0.1:1234/v1")

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("")

    def test_rejects_no_host(self) -> None:
        with pytest.raises(SSRFError):
            validate_endpoint("https:///path")

    def test_localhost_still_has_timeout_protection(self) -> None:
        """Localhost exemption note: this test documents behavior, not enforces it.
        Actual timeout enforcement is in the HTTP client, not in validate_endpoint."""
        # validate_endpoint should pass for localhost
        validate_endpoint("http://localhost:8000")
