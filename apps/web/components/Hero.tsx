"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import Reveal from "./Reveal";

const ServiceGraph = dynamic(() => import("./ServiceGraph"), {
  ssr: false,
  loading: () => <p className="visually-hidden">Loading system graph…</p>,
});

const SNIPPETS: Record<string, string> = {
  python: "pip install codexray-sdk",
  node: "npm install @codexray/browser",
  curl: "curl -fsSL https://codexray.dev/install | bash",
};

export default function Hero() {
  const [tab, setTab] = useState<keyof typeof SNIPPETS>("python");
  const [copied, setCopied] = useState(false);

  return (
    <section className="hero" id="top" aria-labelledby="hero-title">
      <div className="hero__inner">
        <div className="hero__grid">
          <Reveal>
            <p className="badge-news">
              <span className="dot" aria-hidden="true" />
              real-time visual debugging &amp; observability
            </p>
            <h1 className="hero__title" id="hero-title">
              Stop reading logs.{" "}
              <span className="grad">Watch your software think.</span>
            </h1>
            <p className="hero__lede">
              Live telemetry as a system graph. Trace failures, find the
              cause, replay incidents.
            </p>
            <div className="hero__ctas">
              <Link className="btn btn-primary" href="/dashboard">
                Get started
              </Link>
              <a className="btn btn-secondary" href="#overview">
                Watch a replay
              </a>
            </div>
            <div>
              <div className="install-tabs" role="tablist" aria-label="Install method">
                {(Object.keys(SNIPPETS) as (keyof typeof SNIPPETS)[]).map((k) => (
                  <button
                    key={k}
                    role="tab"
                    aria-selected={tab === k}
                    onClick={() => {
                      setTab(k);
                      setCopied(false);
                    }}
                  >
                    {k}
                  </button>
                ))}
              </div>
              <div className="install-snippet">
                <code>{SNIPPETS[tab]}</code>
                <button
                  className="copy-btn"
                  type="button"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(SNIPPETS[tab]);
                      setCopied(true);
                    } catch {
                      setCopied(false);
                    }
                  }}
                >
                  {copied ? "copied" : "copy"}
                </button>
              </div>
            </div>
          </Reveal>
          <Reveal className="hero-visual">
            <ServiceGraph />
          </Reveal>
        </div>
      </div>
      <div className="stats-band" aria-label="Product measurements">
        <div className="stats-band__inner">
          <div className="stat">
            <div>
              <div className="stat__value">
                87% <span className="hot">root-cause confidence</span>
              </div>
              <div className="stat__label">deterministic engine, seeded incident</div>
            </div>
          </div>
          <div className="stat">
            <div>
              <div className="stat__value">
                251/s <span className="hot">spans ingested</span>
              </div>
              <div className="stat__label">measured locally — docs/loadtest.md</div>
            </div>
          </div>
          <div className="stat">
            <div>
              <div className="stat__value">
                1 click <span className="hot">to the live graph</span>
              </div>
              <div className="stat__label">6-service demo, no curl, no key</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
