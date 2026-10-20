"use client";

/* Live telemetry feed: every WebSocket frame, newest first, capped upstream.
   Generic — works for every project; rows are just frames. */

export type FeedEvent = {
  id: number;
  time: string;
  kind: "new_event" | "error" | "service_status" | "incident";
  service: string;
  detail: string;
};

export default function LiveFeed({ items }: { items: FeedEvent[] }) {
  if (!items.length) {
    return <div className="empty">Listening for live events… send traffic to see it here.</div>;
  }
  return (
    <div className="feed" role="log" aria-label="Live telemetry events" aria-live="off">
      {[...items].reverse().map((e) => (
        <div key={e.id} className={`feed__row feed__row--${e.kind}`}>
          <span className="feed__time">{e.time}</span>
          <span className="feed__svc">{e.service}</span>
          <span className="feed__detail">{e.detail}</span>
        </div>
      ))}
    </div>
  );
}
