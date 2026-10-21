"use client";

import type { Trace, TraceSummary } from "@/lib/api";

export default function TraceView({
  trace,
  summaries,
  selectedSpan,
  onSelectTrace,
  onSelectSpan,
}: {
  trace: Trace | null;
  summaries: TraceSummary[];
  selectedSpan: string | null;
  onSelectTrace: (tid: string) => void;
  onSelectSpan: (sid: string | null) => void;
}) {
  if (!trace) {
    return (
      <div>
        <div className="empty">
          {summaries.length
            ? "Pick a trace to inspect its waterfall."
            : "No traces yet — send telemetry first."}
        </div>
        {summaries.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {summaries.slice(0, 8).map((t) => (
              <button key={t.trace_id} type="button" className="dash-link" onClick={() => onSelectTrace(t.trace_id)}>
                {t.trace_id.slice(0, 12)} · {t.span_count} spans · {t.status}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  const t0 = trace.start_time;
  const total = Math.max(trace.duration_ms / 1000, 0.05);
  const rows = [...trace.spans].sort((a, b) => a.timestamp - b.timestamp);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "#9aa3b2" }}>
          {trace.trace_id} · {trace.spans.length} spans · {trace.status}
        </span>
        <select
          aria-label="Select trace"
          value={trace.trace_id}
          onChange={(e) => onSelectTrace(e.target.value)}
          style={{ marginLeft: "auto", background: "rgba(0,0,0,.35)", color: "#fff", border: "1px solid rgba(255,255,255,.16)", borderRadius: 6, padding: "6px 10px", fontSize: 12 }}
        >
          {summaries.map((t) => (
            <option key={t.trace_id} value={t.trace_id}>
              {t.trace_id.slice(0, 14)} · {t.status}
            </option>
          ))}
        </select>
      </div>
      <div className="trace-rows">
        {rows.map((s) => {
          const off = Math.max(0, ((s.timestamp - t0) / total) * 100);
          const w = Math.max(2, ((s.duration_ms / 1000) / total) * 100);
          const err = s.status === "error";
          return (
            <button
              key={s.span_id}
              type="button"
              className={`trace-row${err ? " err" : ""}${selectedSpan === s.span_id ? " sel" : ""}`}
              onClick={() => onSelectSpan(selectedSpan === s.span_id ? null : s.span_id)}
            >
              <span className="trace-row__svc">
                {s.service}
                <small>{s.operation || s.span_id.slice(0, 8)}</small>
              </span>
              <span className="trace-row__bar">
                <i style={{ left: `${Math.min(off, 100)}%`, width: `${Math.min(w, 100 - Math.min(off, 100))}%` }} />
              </span>
              <span className="trace-row__dur">{Math.round(s.duration_ms)}ms</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
