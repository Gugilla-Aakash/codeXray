"""CodeXRay SDK — service naming engine (generic, zero per-project config).

Two mappings:
1. Outbound host -> service (for auto-instrumented HTTP calls).
2. Request path -> service (opt-in route split for request spans).
"""

from __future__ import annotations

import re

# Explicit host recognitions, checked as suffixes (subdomains included).
HOST_SERVICES: tuple[tuple[str, str], ...] = (
    ("api.github.com", "github-api"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("api.groq.com", "groq"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("overpass-api.de", "overpass"),
    ("overpass.kumi.systems", "overpass"),
    ("api.stripe.com", "stripe"),
    ("api.twilio.com", "twilio"),
    ("api.sendgrid.com", "sendgrid"),
    ("nominatim.openstreetmap.org", "nominatim"),
    ("tile.openstreetmap.org", "osm-tiles"),
)

_STRIP_PREFIXES = ("api", "www", "rest", "gateway")
_VERSION_RE = re.compile(r"^v\d+$")
_ID_RE = re.compile(r"^(\d+|[0-9a-f-]{8,}|[0-9a-z]{20,})$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _NON_ALNUM_RE.sub("-", text.lower()).strip("-")


def service_for_host(host: str) -> str:
    """Map an outbound HTTP host to a service name."""
    h = (host or "").lower().split(":")[0].strip().strip(".")
    if not h:
        return "http"
    for suffix, name in HOST_SERVICES:
        if h == suffix or h.endswith("." + suffix):
            return name
    labels = [p for p in h.split(".") if p]
    while labels and labels[0] in _STRIP_PREFIXES:
        labels.pop(0)
    core = labels[0] if labels else h.split(".")[0]
    if _VERSION_RE.match(core) and len(labels) > 1:
        core = labels[1]
    return _slug(core) or "http"


def service_for_path(base: str, path: str) -> str:
    """Derive a service name from a request path for route-split mode.

    /api/v1/search        -> <base>-search   (api prefix + version skipped)
    /assistant/datasets/x -> <base>-assistant-datasets
    /health               -> <base>
    """
    parts = [p for p in (path or "").split("/") if p and p != "*"]
    parts = [p for p in parts if not _VERSION_RE.match(p) and not _ID_RE.match(p)]
    if parts and parts[0].lower() == "api":
        parts = parts[1:]
    if not parts:
        return base
    name = _slug("-".join(parts[:2]))
    return f"{base}-{name}" if name else base
