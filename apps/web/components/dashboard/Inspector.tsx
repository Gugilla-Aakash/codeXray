"use client";

import type { Incident, RootCause, Span } from "@/lib/api";
import { rootCauseOf } from "./Incidents";

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") {
    const s = JSON.stringify(v);
    return s.length > 220 ? s.slice(0, 220) + "…" : s;
  }
  return String(v);
}

export default function Inspector({
  span,
  incident,
}: {
  span: Span | null;
  incident: Incident | null;
}) {
  const rc = incident ? (rootCauseOf(incident) as RootCause | null) : null;
  const prop =
    incident && typeof incident.root_cause === "object" && incident.root_cause
      ? ((incident.root_cause as Record<string, unknown>).propagation as string[] | undefined)
      : undefined;

  if (!span && !incident) {
    return <div className="empty">Select a node, span, or incident to inspect it.</div>;
  }

  return (
    <div>
      {span && (
        <dl className="kv">
          <dt>service</dt>
          <dd className="mono">{span.service}</dd>
          <dt>operation</dt>
          <dd className="mono">{fmt(span.operation)}</dd>
          <dt>status</dt>
          <dd>
            <span className={`pill pill--${span.status === "error" ? "error" : "success"}`}>
              {span.status.toUpperCase()}
            </span>
          </dd>
          <dt>duration</dt>
          <dd className="mono">{Math.round(span.duration_ms)} ms</dd>
          <dt>span</dt>
          <dd className="mono">{span.span_id}</dd>
          <dt>parent</dt>
          <dd className="mono">{fmt(span.parent_span_id)}</dd>
          {span.error && (
            <>
              <dt>error</dt>
              <dd className="mono">{fmt(span.error.message ?? span.error.type)}</dd>
            </>
          )}
          <dt>request</dt>
          <dd className="mono">{fmt(span.request)}</dd>
          <dt>response</dt>
          <dd className="mono">{fmt(span.response)}</dd>
        </dl>
      )}
      {incident && (
        <div className="rc-box" style={{ marginTop: span ? 12 : 0 }}>
          <div>
            probable root cause: <b>{rc ? rc.service : "analyzing…"}</b>{" "}
            {rc && <span className="conf">{rc.confidence}% confidence</span>}
          </div>
          {rc && <div style={{ marginTop: 4 }}>{rc.reason}</div>}
          {rc && (rc.signals?.length ?? 0) > 0 && (
            <div className="rc-sigs" aria-label="Evidence signals">
              {rc.signals!.map((s) => (
                <span key={s} className="rc-sig">
                  {s}
                </span>
              ))}
              {rc.span_id && <span className="rc-sig rc-sig--span">{rc.span_id}</span>}
            </div>
          )}
          {prop && prop.length > 0 && (
            <div className="prop" aria-label="Failure propagation">
              {prop.map((s, i) => (
                <span key={`${s}-${i}`}>
                  {s}
                  {i < prop.length - 1 ? " ↓" : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
