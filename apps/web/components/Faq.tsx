"use client";

import { useState } from "react";

const FAQS = [
  {
    q: "What is CodeXRay?",
    a: "A visual debugging layer: telemetry becomes a live system graph, so you watch requests instead of grepping logs.",
  },
  {
    q: "How is this different from an APM or dashboard?",
    a: "APMs aggregate metrics; CodeXRay preserves causality — every failure keeps its path, chain, and timeline, replayable on demand.",
  },
  {
    q: "How does root-cause analysis work?",
    a: "The engine walks the failed trace backward, scoring candidates by error, latency, timing, and frequency. Always a probable cause, never gospel.",
  },
  {
    q: "What does the demo failure look like?",
    a: "A staged DB latency spike: checkout stalls, payment retries, frontend breaks — then you replay the whole thing.",
  },
  {
    q: "Does CodeXRay replace my logs?",
    a: "No. Logs stay the raw record; CodeXRay is the understanding layer that correlates them into one timeline.",
  },
  {
    q: "How do I instrument my app?",
    a: "Install the SDK, add your API key, stream spans over HTTP. One bad span never breaks ingestion.",
  },
];

export default function Faq() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="faq">
      {FAQS.map((f, i) => {
        const isOpen = open === i;
        return (
          <div className="faq-item" key={f.q}>
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={`faq-panel-${i}`}
              onClick={() => setOpen(isOpen ? null : i)}
            >
              <span aria-hidden="true">{isOpen ? "[-]" : "[+]"}</span>
              <span className="q">{f.q}</span>
            </button>
            {isOpen && (
              <p className="a" id={`faq-panel-${i}`}>
                {f.a}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
