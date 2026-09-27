"""CodeXRay API — keys, redaction, rate limiting, license gate (PRD §28)."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from .config import TELEMETRY_RATE_LIMIT_PER_MIN

# PRD §28: never store these in raw form (matched case-insensitively, substring).
SENSITIVE_SUBSTRINGS = (
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "credit_card",
    "creditcard",
    "card_number",
    "ssn",
)

REDACTED = "[REDACTED]"


def generate_api_key() -> tuple[str, str]:
    """Return (plaintext_key, sha256_hash). Plaintext is shown once."""
    plain = "cxr_" + secrets.token_urlsafe(32)
    return plain, hashlib.sha256(plain.encode()).hexdigest()


def hash_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def license_authorized(provided: str | None, valid: Iterable[str]) -> bool:
    """SaaS license gate: empty `valid` set => open mode (everyone passes).

    Otherwise the supplied key must match one of the configured keys.
    Comparison is constant-time per key (hmac.compare_digest) so response
    timing never leaks how close a guess was.
    """
    keys = tuple(valid)
    if not keys:
        return True
    if not provided:
        return False
    return any(hmac.compare_digest(provided, k) for k in keys)


class BaseUrlError(ValueError):
    """User-supplied base URL failed the SSRF policy. Message is user-safe."""


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Literal IP -> itself; hostname -> every address it resolves to.

    Fail-closed: unresolvable hosts raise (callers treat as invalid).
    Exposed for tests to monkeypatch the DNS step.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def validate_base_url(url: str) -> str:
    """SSRF guard for user-supplied BYOK base URLs.

    Policy:
    - scheme must be https (http only when the host is loopback, so local
      gateways like Ollama/LM-Studio keep working);
    - no credentials embedded in the URL;
    - every destination IP — literal or DNS-resolved — must be loopback or
      globally routable: private (RFC1918), link-local (169.254/16 incl.
      cloud metadata), CGNAT, reserved, multicast and unspecified addresses
      are rejected.

    Note: DNS is re-resolved by the HTTP client afterwards, so a hostile
    resolver could still rebind (TOCTOU) — acceptable residual risk here;
    the common cases (metadata IPs, intranet hosts) are caught up front.
    """
    raw = (url or "").strip()
    if not raw:
        raise BaseUrlError("A base URL is required.")
    try:
        parsed = urlparse(raw)
        host = parsed.hostname
    except ValueError as exc:
        raise BaseUrlError("Malformed base URL.") from exc
    if parsed.scheme not in ("http", "https"):
        raise BaseUrlError("Base URL must use http or https.")
    if parsed.username is not None or parsed.password is not None:
        raise BaseUrlError("Base URL must not contain embedded credentials.")
    if not host:
        raise BaseUrlError("Base URL must include a host.")

    try:
        ips = _resolve_host_ips(host)
    except (ValueError, socket.gaierror, OSError) as exc:
        raise BaseUrlError("Base URL host could not be resolved.") from exc
    if not ips:
        raise BaseUrlError("Base URL host could not be resolved.")

    loopback_only = all(ip.is_loopback for ip in ips)
    if parsed.scheme == "http" and not loopback_only:
        raise BaseUrlError("Base URL must use https (http is allowed for localhost only).")
    for ip in ips:
        if not (ip.is_loopback or ip.is_global):
            raise BaseUrlError(
                "Base URL must point at a public host or localhost — "
                "private network addresses are not allowed."
            )
    return raw


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in SENSITIVE_SUBSTRINGS)


def redact(obj: Any) -> Any:
    """Recursively redact sensitive values in dicts/lists."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def infer_service_type(name: str) -> str:
    n = name.lower()
    if any(s in n for s in ("postgres", "mysql", "mongo", "sqlite", "db", "sql", "database")):
        return "database"
    if any(s in n for s in ("redis", "cache", "memcached")):
        return "cache"
    if any(s in n for s in ("kafka", "queue", "rabbit", "nats", "sqs", "worker")):
        return "queue"
    if any(s in n for s in ("gateway", "api-gateway", "ingress")):
        return "api"
    if any(s in n for s in ("stripe", "external", "third-party", "provider")):
        return "external"
    if any(s in n for s in ("browser", "frontend", "web", "client", "mobile")):
        return "frontend"
    if any(s in n for s in ("auth",)):
        return "auth"
    return "service"


class RateLimiter:
    """In-memory rolling-window limiter (per API key)."""

    def __init__(self, per_minute: int = TELEMETRY_RATE_LIMIT_PER_MIN) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allowed(self, key: str) -> bool:
        now = time.time()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


rate_limiter = RateLimiter()
