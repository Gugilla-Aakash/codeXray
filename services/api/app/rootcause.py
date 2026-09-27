"""CodeXRay API — deterministic root-cause engine (PRD §18).

MVP heuristic: traverse the failed trace from the downstream symptom back
toward upstream dependencies. The first failed/anomalous upstream dependency
is the primary root-cause candidate. Always labeled *probable* (§18 rule).
"""

from __future__ import annotations

from collections import Counter
from statistics import median


def _is_error(span: dict) -> bool:
    return (span.get("status") or "").lower() == "error"


def analyze(spans: list[dict], slow_ms: int = 2000) -> dict | None:
    """Return {service, reason, confidence, propagation} or None if healthy."""
    if not spans:
        return None

    by_id = {s["span_id"]: s for s in spans}
    errors = sorted(
        [s for s in spans if _is_error(s)], key=lambda s: s.get("timestamp", 0)
    )

    # Dependency influence: how many spans (transitively) depend on each span.
    dependents: Counter[str] = Counter()
    for s in spans:
        parent = s.get("parent_span_id")
        seen: set[str] = set()
        while parent and parent in by_id and parent not in seen:
            seen.add(parent)
            dependents[parent] += 1
            parent = by_id[parent].get("parent_span_id")

    def score(s: dict, first_error_ts: float | None) -> tuple[int, list[str]]:
        signals: list[str] = []
        pts = 0
        if _is_error(s):
            pts += 2
            signals.append("error")
        if (s.get("duration_ms") or 0) >= slow_ms:
            pts += 1
            signals.append("latency")
        if first_error_ts is not None and s.get("timestamp", 0) <= first_error_ts:
            pts += 1
            signals.append("temporal")
        if dependents.get(s["span_id"], 0) > 0:
            pts += 1
            signals.append("dependency")
        return pts, signals

    candidate: dict | None = None
    signals: list[str] = []
    if errors:
        first_error_ts = errors[0].get("timestamp", 0)
        # Origin of the failure: an error span that no other error span
        # depends on (nothing downstream of it also failed). A parent that
        # errors only because its child errored is a consequence, not the
        # cause. Earliest origin wins.
        with_error_child = set()
        for s in errors:
            p = s.get("parent_span_id")
            if p and p in by_id and _is_error(by_id[p]):
                with_error_child.add(p)
        origins = [s for s in errors if s["span_id"] not in with_error_child]
        candidate = min(
            origins or errors, key=lambda s: (s.get("timestamp", 0), s["span_id"])
        )
        best, signals = score(candidate, first_error_ts)
        confidence = min(95, 60 + 9 * best)
    else:
        # No errors: flag the slowest anomalous span as degraded, low confidence.
        first_error_ts = None
        durs = sorted(s.get("duration_ms", 0) for s in spans)
        threshold = max(slow_ms, (median(durs) * 2) if durs else durs and slow_ms)
        slow = [s for s in spans if s.get("duration_ms", 0) >= threshold]
        if not slow:
            return None
        candidate = max(slow, key=lambda s: s.get("duration_ms", 0))
        best, signals = score(candidate, None)
        confidence = min(70, 45 + 9 * best)

    # Propagation path: root cause up through its ancestors to the visible
    # symptom (e.g. postgres -> order-service -> api-gateway -> frontend).
    propagation = _propagation_path(by_id, candidate)

    err = candidate.get("error") or {}
    if err.get("message"):
        reason = str(err["message"])
    elif (candidate.get("duration_ms") or 0) >= slow_ms:
        reason = (
            f"{candidate.get('operation') or candidate['service']} latency "
            f"{candidate.get('duration_ms')}ms exceeded timeout"
        )
    elif _is_error(candidate):
        reason = f"{candidate.get('operation') or candidate['service']} failed"
    else:
        reason = "Anomalous latency detected"

    return {
        "service": candidate["service"],
        "reason": reason,
        "confidence": int(confidence),
        "propagation": propagation,
        # Evidence for the UI + AI: which span the engine blamed and why
        # (the exact scoring signals that produced the confidence).
        "span_id": candidate.get("span_id"),
        "signals": signals,
    }


def _propagation_path(by_id: dict, root: dict) -> list[str]:
    """Service names from the root cause up to the visible symptom."""
    path = [root["service"]]
    current = root.get("parent_span_id")
    seen = {root["span_id"]}
    while current and current in by_id and current not in seen:
        seen.add(current)
        svc = by_id[current]["service"]
        if svc != path[-1]:
            path.append(svc)
        current = by_id[current].get("parent_span_id")
    return path
