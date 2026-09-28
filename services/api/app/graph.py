"""CodeXRay API — system graph builder (PRD §8.13, §17).

Infers services (nodes) and dependencies (edges) from observed spans,
with RED-style aggregates per edge. Also produces the health summary
(PRD §8.12).
"""

from __future__ import annotations

import time
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def build_graph(db: Session, project_id: str) -> dict:
    services = db.scalars(
        select(models.Service).where(models.Service.project_id == project_id)
    ).all()

    counts: dict[int, int] = dict(
        db.execute(
            select(models.Span.service_id, func.count())
            .join(models.Trace, models.Span.trace_id == models.Trace.id)
            .where(models.Trace.project_id == project_id)
            .group_by(models.Span.service_id)
        ).all()
    )

    nodes = [
        {
            "id": s.name,
            "name": s.name,
            "type": s.type,
            "status": s.status,
            "request_count": counts.get(s.id, 0),
        }
        for s in services
    ]

    # Edges: parent span service -> child span service.
    spans = db.execute(
        select(
            models.Span.id,
            models.Span.parent_span_id,
            models.Span.service_name,
            models.Span.status,
            models.Span.duration_ms,
        )
        .join(models.Trace, models.Span.trace_id == models.Trace.id)
        .where(models.Trace.project_id == project_id)
    ).all()
    by_id = {s.id: s for s in spans}
    agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "errors": 0, "lat": []}
    )
    for s in spans:
        parent = by_id.get(s.parent_span_id or "")
        if parent is None or parent.service_name == s.service_name:
            continue
        a = agg[(parent.service_name, s.service_name)]
        a["count"] += 1
        if (s.status or "").lower() == "error":
            a["errors"] += 1
        a["lat"].append(s.duration_ms or 0)

    edges = [
        {
            "source": src,
            "target": dst,
            "request_count": a["count"],
            "error_rate": round(a["errors"] / a["count"], 4) if a["count"] else 0.0,
            "avg_latency": round(sum(a["lat"]) / len(a["lat"]), 1) if a["lat"] else 0.0,
        }
        for (src, dst), a in sorted(agg.items())
    ]

    # Summary (§8.12).
    statuses = [s.status for s in services]
    healthy = sum(1 for x in statuses if x == "healthy")
    degraded = sum(1 for x in statuses if x == "degraded")
    failing = sum(1 for x in statuses if x in ("error", "critical"))

    window_start = time.time() - 60
    recent = (
        db.query(models.Span.duration_ms, models.Span.status)
        .join(models.Trace, models.Span.trace_id == models.Trace.id)
        .filter(
            models.Trace.project_id == project_id,
            models.Span.start_time >= window_start,
        )
        .all()
    )
    total = len(recent)
    err = sum(1 for _, st in recent if (st or "").lower() == "error")
    lats = sorted(d for d, _ in recent)
    summary = {
        "services": len(services),
        "healthy": healthy,
        "degraded": degraded,
        "failing": failing,
        "requests_per_min": float(total),
        "error_rate": round(err / total, 4) if total else 0.0,
        "p95_latency": round(_percentile(lats, 95), 1),
    }
    return {"nodes": nodes, "edges": edges, "summary": summary}
