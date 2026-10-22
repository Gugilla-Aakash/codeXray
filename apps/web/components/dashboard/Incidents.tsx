"use client";

import type { Incident } from "@/lib/api";

export function rootCauseOf(inc: Incident): { service: string; reason: string; confidence: number } | null {
  const rc = inc.root_cause;
  if (rc && typeof rc === "object" && "service" in rc) {
    return rc as { service: string; reason: string; confidence: number };
  }
  return null;
}

export default function Incidents({
  items,
  selected,
  onSelect,
}: {
  items: Incident[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  if (!items.length) return <div className="empty">No incidents. Healthy systems are quiet systems.</div>;
  return (
    <div className="inc-list">
      {items.map((inc) => {
        const rc = rootCauseOf(inc);
        return (
          <button
            key={inc.incident_id}
            type="button"
            className={`inc${selected === inc.incident_id ? " sel" : ""}`}
            onClick={() => onSelect(selected === inc.incident_id ? null : inc.incident_id)}
          >
            <span className="inc__top">
              <span className={`sev sev--${inc.severity}`}>{inc.severity}</span>
              <span className="inc__id">{inc.incident_id}</span>
            </span>
            <span className="inc__title">{inc.title}</span>
            {rc && (
              <span className="inc__rc">
                likely root cause: <b>{rc.service}</b> · {rc.confidence}%
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
