"""CodeXRay API — demo checkout scenario (PRD §24, §25).

Builds the hackathon failure story: a healthy baseline plus one checkout
trace where a PostgreSQL latency spike times out and the failure
propagates back to the frontend.
"""

from __future__ import annotations

import time
from random import randint


def build_demo_events(
    base_ts: float | None = None, tag: str = "demo", *, incident_only: bool = False
) -> list[dict]:
    t = base_ts if base_ts is not None else time.time() - 20

    def ev(trace, span, parent, service, op, dt, dur, status="success", err=None, **kw):
        d: dict = {
            "trace_id": f"{tag}-{trace}",
            "span_id": f"{tag}-{span}",
            "parent_span_id": f"{tag}-{parent}" if parent else None,
            "service": service,
            "operation": op,
            "timestamp": t + dt,
            "duration_ms": dur,
            "status": status,
        }
        if err:
            d["error"] = err
        d.update(kw)
        return d

    healthy = [
        ev("demo-ok-1", "ok-f", None, "frontend", "click Pay", 0.0, 900),
        ev("demo-ok-1", "ok-g", "ok-f", "api-gateway", "POST /checkout", 0.05, 800),
        ev("demo-ok-1", "ok-a", "ok-g", "auth-service", "verify jwt", 0.08, 12),
        ev("demo-ok-1", "ok-o", "ok-g", "order-service", "create order", 0.12, 300),
        ev("demo-ok-1", "ok-d", "ok-o", "postgres", "SELECT orders", 0.15, 38),
        ev("demo-ok-1", "ok-p", "ok-o", "payment-service", "charge", 0.5, 410),
    ]
    # The incident: INC demo trace (PRD §25).
    incident = [
        ev("a92fd1", "s100", None, "frontend", "click Pay", 10.0, 3500, "error",
           {"type": "CheckoutFailed", "message": "Checkout failed"}),
        ev("a92fd1", "s101", "s100", "api-gateway", "POST /checkout", 10.03, 3400, "error",
           {"type": "UpstreamTimeout", "message": "Upstream timeout"}),
        ev("a92fd1", "s102", "s101", "auth-service", "verify jwt", 10.04, 18),
        ev("a92fd1", "s103", "s101", "order-service", "create order", 10.06, 3000, "error",
           {"type": "OrderFailed", "message": "Order creation exceeded timeout"}),
        ev("a92fd1", "s104", "s103", "postgres", "SELECT orders WHERE id = ?",
           10.48, 2840, "error",
           {"type": "DatabaseTimeout", "message": "Query exceeded 2000ms"}),
        ev("a92fd1", "s105", "s103", "payment-service", "charge retry",
           13.10, 300, "error",
           {"type": "PaymentFailed", "message": "Payment failed after retry"}),
    ]
    if incident_only:
        return incident
    return healthy + incident


def build_pulse_events(tag: str, base_ts: float | None = None) -> list[dict]:
    """One tiny healthy request for the demo heartbeat (all-success, so it
    never creates incidents — it just keeps req/min, feed, and graph alive)."""
    t = base_ts if base_ts is not None else time.time() - 0.4

    def ev(span, parent, service, op, dur):
        return {
            "trace_id": f"{tag}",
            "span_id": f"{tag}-{span}",
            "parent_span_id": f"{tag}-{parent}" if parent else None,
            "service": service,
            "operation": op,
            "timestamp": t,
            "duration_ms": dur,
            "status": "success",
        }

    return [
        ev("f", None, "frontend", "click Pay", randint(180, 420)),
        ev("g", "f", "api-gateway", "POST /checkout", randint(150, 380)),
        ev("a", "g", "auth-service", "verify jwt", randint(8, 24)),
        ev("o", "g", "order-service", "create order", randint(60, 220)),
        ev("p", "o", "payment-service", "charge", randint(90, 260)),
    ]
