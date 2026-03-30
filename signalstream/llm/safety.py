"""SSRF validation for user-configurable LLM endpoints.

Validates endpoints before any HTTP request is made to prevent:
- Access to internal services via private IPs
- Cloud metadata access (169.254.x.x)
- File system access (file://)
- DNS rebinding attacks (raw IPs)

Localhost exemption (BOARD-007): Endpoints resolving to 127.0.0.0/8 or ::1
are exempt from the HTTPS requirement and private network block, to support
local inference servers (LM Studio, vLLM, llama.cpp, text-generation-webui).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Networks that are blocked for non-localhost endpoints
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),      # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),              # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),             # IPv6 link-local
]

# Localhost ranges — exempt from HTTPS and private network blocks
_LOCALHOST_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]

_LOCALHOST_HOSTNAMES = frozenset({"localhost"})


class SSRFError(Exception):
    """Raised when an endpoint fails SSRF validation."""


def _is_localhost(host: str) -> bool:
    """Check if a host is a localhost address or hostname."""
    if host.lower() in _LOCALHOST_HOSTNAMES:
        return True
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _LOCALHOST_NETWORKS)
    except ValueError:
        return False


def _is_raw_ip(host: str) -> bool:
    """Check if a host string is a raw IP address."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_and_check(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname and return all addresses. Raises SSRFError if blocked."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFError(f"Cannot resolve hostname '{host}': {e}") from e

    addresses = []
    for family, _type, _proto, _canonname, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        addresses.append(addr)

    return addresses


def validate_endpoint(url: str) -> None:
    """Validate a user-provided endpoint URL against SSRF attacks.

    Args:
        url: The endpoint URL to validate.

    Raises:
        SSRFError: If the URL fails any validation check.
    """
    if not url or not url.strip():
        raise SSRFError("Endpoint URL is empty")

    parsed = urlparse(url)

    # 1. Scheme check
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFError(
            f"Invalid URL scheme '{scheme}'. Only http/https allowed."
        )

    # 2. Host check
    host = parsed.hostname
    if not host:
        raise SSRFError("Endpoint URL has no host")

    is_local = _is_localhost(host)

    # 3. HTTPS required for non-localhost
    if scheme == "http" and not is_local:
        raise SSRFError(
            f"HTTPS required for non-localhost endpoints (got http://{host})"
        )

    # 4. Raw IP rejection for non-localhost
    if _is_raw_ip(host) and not is_local:
        raise SSRFError(
            f"Raw IP addresses not allowed for non-localhost endpoints. "
            f"Use a hostname instead of {host}."
        )

    # 5. If localhost, skip network checks (BOARD-007 exemption)
    if is_local:
        logger.debug("Localhost endpoint exempted from SSRF network checks: %s", url)
        return

    # 6. Resolve and check all addresses against blocked networks
    addresses = _resolve_and_check(host)
    for addr in addresses:
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise SSRFError(
                    f"Endpoint '{host}' resolves to blocked network "
                    f"{network} (address: {addr})"
                )

    logger.debug("Endpoint passed SSRF validation: %s", url)
