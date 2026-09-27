"""CodeXRay API — incident replay normalizer (PRD §19).

Sorts a trace's spans chronologically and converts them into replay
actions the frontend animates: START_REQUEST, ENTER_SERVICE,
CALL_DEPENDENCY, RETURN_RESPONSE, ERROR, RETRY, END_REQUEST.
"""

from __future__ import annotations


def build_actions(spans: list[dict]) -> list[dict]:
    ordered = sorted(spans, key=lambda s: (s.get("timestamp", 0), s.get("span_id", "")))
    if not ordered:
        return []
    t0 = ordered[0].get("timestamp", 0) or 0

    def t(s: dict) -> float:
        return round((s.get("timestamp", 0) or 0) - t0, 2)

    by_id = {s["span_id"]: s for s in ordered}
    roots = [s for s in ordered if not s.get("parent_span_id") or s.get("parent_span_id") not in by_id]
    root = roots[0] if roots else ordered[0]

    actions: list[dict] = [
        {
            "time": 0.0,
            "action": "START_REQUEST",
            "service": root["service"],
            "message": root.get("operation") or None,
        }
    ]

    seen_ops: set[tuple[str, str]] = set()
    had_error = False
    for s in ordered:
        op_key = (s["service"], s.get("operation") or "")
        err = s.get("error") or {}
        is_error = (s.get("status") or "").lower() == "error"
        if is_error:
            had_error = True

        parent = by_id.get(s.get("parent_span_id") or "")
        if parent is not None:
            actions.append(
                {
                    "time": t(s),
                    "action": "CALL_DEPENDENCY",
                    "service": parent["service"],
                    "message": f"calls {s['service']}",
                }
            )

        if op_key in seen_ops and (is_error or had_error):
            actions.append(
                {
                    "time": t(s),
                    "action": "RETRY",
                    "service": s["service"],
                    "message": s.get("operation") or None,
                }
            )
        else:
            actions.append(
                {
                    "time": t(s),
                    "action": "ENTER_SERVICE",
                    "service": s["service"],
                    "message": s.get("operation") or None,
                }
            )
        seen_ops.add(op_key)

        if is_error:
            actions.append(
                {
                    "time": t(s),
                    "action": "ERROR",
                    "service": s["service"],
                    "message": err.get("message") or s.get("operation") or "error",
                }
            )

    end = ordered[-1]
    end_time = round(t(end) + (end.get("duration_ms", 0) or 0) / 1000.0, 2)
    status = "error" if any((s.get("status") or "").lower() == "error" for s in ordered) else "success"
    actions.append(
        {
            "time": end_time,
            "action": "RETURN_RESPONSE",
            "service": root["service"],
            "message": status,
        }
    )
    actions.append(
        {"time": end_time, "action": "END_REQUEST", "service": root["service"], "message": status}
    )
    return actions
