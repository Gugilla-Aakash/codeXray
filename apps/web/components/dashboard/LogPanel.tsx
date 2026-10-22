"use client";

/* Live log panel: lines from `codexray logs` (WS "log" frames + initial
   GET). Level chips filter client-side; sparkline buckets lines/min from
   the last 30 two-second windows. Zero deps, pure markup + inline SVG. */

import { useMemo, useState } from "react";
import type { LogLine } from "@/lib/api";

type Level = LogLine["level"];
const LEVELS: Level[] = ["error", "warn", "info", "debug"];

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
}

function Sparkline({ lines }: { lines: LogLine[] }) {
  // 30 buckets × 2s ending at the newest line (pure — no Date.now in render).
  const bars = useMemo(() => {
    if (!lines.length) return new Array(30).fill(0);
    let newest = 0;
    for (const l of lines) if (l.ts > newest) newest = l.ts;
    const buckets = new Array(30).fill(0);
    for (const l of lines) {
      const age = newest - l.ts;
      if (age < 0 || age >= 60) continue;
      const idx = 29 - Math.floor(age / 2);
      if (idx >= 0 && idx < 30) buckets[idx] += 1;
    }
    return buckets;
  }, [lines]);
  const max = Math.max(1, ...bars);
  return (
    <svg className="logpanel__spark" viewBox="0 0 120 24" aria-hidden="true">
      {bars.map((v, i) => {
        const h = Math.round((v / max) * 20);
        return (
          <rect
            key={i}
            x={i * 4}
            y={22 - h}
            width={3}
            height={Math.max(v > 0 ? 1 : 0, h)}
            fill={v > 0 ? "currentColor" : "transparent"}
            opacity={0.25 + (v / max) * 0.75}
          />
        );
      })}
    </svg>
  );
}

export default function LogPanel({
  items,
  paused,
  onTogglePause,
}: {
  items: LogLine[];
  paused: boolean;
  onTogglePause: () => void;
}) {
  const [enabled, setEnabled] = useState<Record<Level, boolean>>({
    error: true,
    warn: true,
    info: true,
    debug: true,
  });
  const [q, setQ] = useState("");

  const counts = useMemo(() => {
    const c: Record<Level, number> = { error: 0, warn: 0, info: 0, debug: 0 };
    for (const l of items) c[l.level] = (c[l.level] ?? 0) + 1;
    return c;
  }, [items]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter(
      (l) =>
        enabled[l.level] &&
        (!needle ||
          l.message.toLowerCase().includes(needle) ||
          l.service.toLowerCase().includes(needle))
    );
  }, [items, enabled, q]);

  return (
    <div className="logpanel">
      <div className="logpanel__bar">
        <div className="logpanel__levels" role="group" aria-label="Level filters">
          {LEVELS.map((lv) => (
            <button
              key={lv}
              type="button"
              className={`logpanel__chip logpanel__chip--${lv}${enabled[lv] ? "" : " off"}`}
              onClick={() => setEnabled((e) => ({ ...e, [lv]: !e[lv] }))}
              aria-pressed={enabled[lv]}
            >
              {lv} {counts[lv]}
            </button>
          ))}
        </div>
        <input
          className="logpanel__search"
          type="search"
          placeholder="filter…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Filter log messages"
        />
        <Sparkline lines={items} />
        <button type="button" className="dash-link" onClick={onTogglePause}>
          {paused ? "Resume" : "Pause"}
        </button>
      </div>
      {visible.length === 0 ? (
        <div className="empty">
          {items.length === 0
            ? "Run `codexray logs <file>` to stream logs here."
            : "No lines match the current filters."}
        </div>
      ) : (
        <div className="logpanel__list" role="log" aria-label="Live logs" aria-live="off">
          {[...visible].reverse().map((l) => (
            <div key={l.id} className={`logpanel__row logpanel__row--${l.level}`}>
              <span className="logpanel__time">{fmtTime(l.ts)}</span>
              <span className="logpanel__lvl">{l.level}</span>
              {l.service ? <span className="logpanel__svc">{l.service}</span> : null}
              <span className="logpanel__msg">{l.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
