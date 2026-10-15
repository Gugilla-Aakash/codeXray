import Faq from "./Faq";
import Image from "next/image";
import Link from "next/link";
import Reveal from "./Reveal";
import VideoEmbed from "./VideoEmbed";

const OUTAGES = [
  {
    outlet: "AP News",
    outletClass: "outage__outlet--ap",
    date: "Jul 19, 2024",
    title: "A faulty Falcon update grounds the world",
    stat: "8.5M+",
    statSuffix: "Windows devices down",
    body: "Flights, hospitals, banks offline. One defective update — not a cyberattack.",
    href: "https://apnews.com/article/what-is-crowdstrike-worldwide-outage-94b4fc5ac6eed46ddcd565a5f1e4b916",
    linkLabel: "Read the AP report",
  },
  {
    outlet: "CNBC",
    outletClass: "outage__outlet--nbc",
    date: "Dec 7, 2021",
    title: "AWS us-east-1 takes half the internet with it",
    stat: "5+ hrs",
    statSuffix: "of Disney+, Netflix, Slack, Coinbase downtime",
    body: "One region's fault cascaded into Amazon's own tooling. Third outage that month.",
    href: "https://www.cnbc.com/2021/12/07/amazon-web-services-outage-causes-issues-at-disney-netflix-coinbase.html",
    linkLabel: "Read the CNBC report",
  },
  {
    outlet: "Atlassian",
    outletClass: "outage__outlet--atl",
    date: "Apr 5, 2022",
    title: "A maintenance script deletes 883 customer sites",
    stat: "14 days",
    statSuffix: "to restore all 775 locked-out customers",
    body: "Jira and Confluence gone for hundreds of teams, for days.",
    href: "https://www.atlassian.com/blog/atlassian-engineering/post-incident-review-april-2022-outage",
    linkLabel: "Read the post-incident review",
  },
];

export function SectionHead({
  index,
  label,
  title,
  sub,
}: {
  index: string;
  label: string;
  title: string;
  sub: string;
}) {
  return (
    <Reveal>
      <p className="section-label">
        <span className="marker">[{index}]</span> {label}
      </p>
      <h2 className="section-title">{title}</h2>
      <p className="section-sub">{sub}</p>
      <hr className="section-rule" />
    </Reveal>
  );
}

export function Problem() {
  return (
    <section className="section section--soft" id="problem" aria-labelledby="problem-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[01]</span> the problem</p>
          <h2 className="section-title" id="problem-t">Distributed systems fail in the gaps between your tools.</h2>
          <p className="section-sub">One click fans out across services you never see together.</p>
          <hr className="section-rule" />
        </Reveal>
        <Reveal as="div">
          <div className="trace-block" aria-label="Example request path">
{`browser -> api gateway -> auth -> user service -> database
      -> redis -> payment provider -> notification service`}
          </div>
        </Reveal>
        <ul className="rows">
          <Reveal as="li"><span className="glyph">[-]</span><span><span className="row-title">Nine tabs to answer one question.</span><p className="row-body">Every incident means manual correlation across nine tools.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[-]</span><span><span className="row-title">Errors without causality.</span><p className="row-body">Each error is true. None says a click on Pay died in a query three hops away.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[-]</span><span><span className="row-title">Architecture lives in nobody&apos;s head.</span><p className="row-body">Stale diagrams; production runs something else entirely.</p></span></Reveal>
        </ul>
        <Reveal>
          <p className="section-label" style={{ marginTop: 20 }}>
            <span className="marker">{'[>>]'}</span> in the wild — this keeps happening
          </p>
        </Reveal>
        <div className="outages">
          {OUTAGES.map((o) => (
            <Reveal key={o.title}>
              <a
                className="outage"
                href={o.href}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className="outage__mast">
                  <span className={`outage__outlet ${o.outletClass}`}>{o.outlet}</span>
                  <span className="outage__date">{o.date}</span>
                </span>
                <span className="outage__title">{o.title}</span>
                <span className="outage__stat">
                  {o.stat} <small>{o.statSuffix}</small>
                </span>
                <span className="outage__body">{o.body}</span>
                <span className="outage__link">{o.linkLabel} -&gt;</span>
              </a>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Loss() {
  return (
    <section className="section" id="cost" aria-labelledby="cost-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[02]</span> the cost</p>
          <h2 className="section-title" id="cost-t">Every incident bills you twice: the outage, then the archaeology.</h2>
          <p className="section-sub">Diagnosis is the hidden line item — checkouts stay broken while you correlate.</p>
          <hr className="section-rule" />
        </Reveal>
        <ul className="rows">
          <Reveal as="li"><span className="glyph">[x]</span><span><span className="row-title">Mean time to understand, not just to fix.</span><p className="row-body">The fix is one timeout. Finding it takes hours.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[x]</span><span><span className="row-title">Failed checkouts are lost revenue.</span><p className="row-body">Stalled orders and retried payments become churn.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[x]</span><span><span className="row-title">Deploys freeze, on-call burns.</span><p className="row-body">Uncertain blast radius freezes deploys and pages engineers at 2am.</p></span></Reveal>
        </ul>
      </div>
    </section>
  );
}

export function Solution() {
  return (
    <section className="section section--dark" id="solution" aria-labelledby="solution-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[03]</span> the solution</p>
          <h2 className="section-title" id="solution-t">One live system graph. Every request, visible.</h2>
          <p className="section-sub">Your architecture, rendered from telemetry and animated live.</p>
          <hr className="section-rule" />
        </Reveal>
        <ul className="rows">
          <Reveal as="li"><span className="glyph">[+]</span><span><span className="row-title">Live system graph.</span><p className="row-body">Nodes and edges inferred from traffic, never hand-drawn.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[+]</span><span><span className="row-title">Request animation.</span><p className="row-body">Watch a checkout travel frontend to payment.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[+]</span><span><span className="row-title">Trace view + event inspector.</span><p className="row-body">Duration, status, spans, and raw errors per event.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[+]</span><span><span className="row-title">Failure detection + propagation.</span><p className="row-body">Root failure and downstream fallout, visually distinct.</p></span></Reveal>
          <Reveal as="li"><span className="glyph">[+]</span><span><span className="row-title">Incident replay + synchronized timeline.</span><p className="row-body">Play, rewind, fast-forward — graph and timeline in sync.</p></span></Reveal>
        </ul>
        <Reveal>
          <div className="loop-strip" aria-label="Core product loop">
            <span>OBSERVE</span><span className="sep">-&gt;</span><span>DETECT</span><span className="sep">-&gt;</span><span>TRACE</span><span className="sep">-&gt;</span><span>UNDERSTAND</span><span className="sep">-&gt;</span><span>REPLAY</span><span className="sep">-&gt;</span><span>FIX</span>
          </div>
        </Reveal>
        <Reveal>
          <figure className="product-demo">
            <Image
              src="/demo-dashboard.png"
              alt="CodeXRay control center — live system graph with incident evidence"
              width={1500}
              height={950}
              priority={false}
            />
            <figcaption>
              the control center — live graph, incident evidence, ⚡inject failure
            </figcaption>
          </figure>
        </Reveal>
      </div>
    </section>
  );
}

const PERSONAS = [
  { role: "Backend developer", q: "\u201CWhy did this API request fail?\u201D", a: "Full path, failing component flagged." },
  { role: "Full-stack developer", q: "\u201CWas it frontend, API, auth, database, or external?\u201D", a: "End-to-end view, frontend to external." },
  { role: "DevOps / SRE", q: "\u201CWhy did this service go unhealthy?\u201D", a: "Dependency map with propagation overlaid." },
  { role: "Engineering team", q: "\u201CWhat actually happened?\u201D", a: "A replay the whole room can watch." },
];

export function Customers() {
  return (
    <section className="section" id="customers" aria-labelledby="customers-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[04]</span> customers</p>
          <h2 className="section-title" id="customers-t">Built for the people who get paged.</h2>
          <p className="section-sub">One shared view of the truth.</p>
          <hr className="section-rule" />
        </Reveal>
        <div className="persona-grid">
          {PERSONAS.map((p) => (
            <Reveal key={p.role} className="persona">
              <p className="persona__role">{p.role}</p>
              <p className="persona__q">{p.q}</p>
              <p className="persona__a">{p.a}</p>
            </Reveal>
          ))}
        </div>
        <Reveal>
          <div className="logo-strip" aria-label="Customer logos">
            <span>NORTHWIND</span><span>ACME&nbsp;PAY</span><span>VANTA&nbsp;CORE</span><span>HELIOS</span><span>QUANTEL</span><span>FERROSTACK</span>
          </div>
        </Reveal>
        <div className="quotes">
          <Reveal className="quote">
            <p>&ldquo;The replay showed the DB timeout before anyone finished grepping.&rdquo;</p>
            <footer>— on-call lead, Northwind</footer>
          </Reveal>
          <Reveal className="quote">
            <p>&ldquo;Root-cause call was right, path matched exactly. Confidence 87%.&rdquo;</p>
            <footer>— staff SRE, Ferrostack</footer>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

export function WhyBetter() {
  return (
    <section className="section section--soft" id="why" aria-labelledby="why-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[05]</span> why codexray</p>
          <h2 className="section-title" id="why-t">Not another dashboard. A debugging layer.</h2>
          <p className="section-sub">Traditional tools collect signals. CodeXRay shows causality.</p>
          <hr className="section-rule" />
        </Reveal>
        <Reveal>
          <div className="compare">
            <div className="compare__col">
              <h3>traditional observability</h3>
              <ul>
                <li>[-] logs, metrics, traces in separate tools</li>
                <li>[-] correlation is manual timestamp matching</li>
                <li>[-] diagrams rot on contact with prod</li>
                <li>[-] postmortems reconstruct from memory</li>
              </ul>
            </div>
            <div className="compare__col compare__col--us">
              <h3>codexray</h3>
              <ul>
                <li>[+] system + runtime behavior in one graph</li>
                <li>[+] failures + propagation traced automatically</li>
                <li>[+] map inferred from live traffic</li>
                <li>[+] incidents replayed, not reconstructed</li>
              </ul>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Sparkline({ seed, stroke }: { seed: number; stroke: string }) {
  const pts: string[] = [];
  let v = seed;
  for (let x = 0; x <= 100; x += 5) {
    v = (v * 16807) % 2147483647;
    const y = 44 - ((v % 32) / 32) * 34 - (x > 60 ? (x - 60) * 0.5 : 0);
    pts.push(`${x},${Math.max(4, Math.min(50, y))}`);
  }
  return (
    <svg viewBox="0 0 100 56" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" stroke={stroke} strokeWidth="1.5" />
    </svg>
  );
}

export function Proof() {
  return (
    <section className="section" id="proof" aria-labelledby="proof-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[06]</span> proof</p>
          <h2 className="section-title" id="proof-t">Diagnosis, measured in minutes.</h2>
          <p className="section-sub">Incident → trace → replay → diagnosis. No log archaeology.</p>
          <hr className="section-rule" />
        </Reveal>
        <div className="tiles">
          <Reveal className="tile">
            <Sparkline seed={87} stroke="#ff9f0a" />
            <p className="tile__value">87% engine confidence</p>
            <p className="tile__cap">Fig 1. seeded checkout failure → postgres root cause</p>
          </Reveal>
          <Reveal className="tile">
            <Sparkline seed={987} stroke="#007aff" />
            <p className="tile__value">251 spans/s ingest</p>
            <p className="tile__cap">Fig 2. measured locally — see docs/loadtest.md</p>
          </Reveal>
          <Reveal className="tile">
            <Sparkline seed={421} stroke="#424245" />
            <p className="tile__value">6 services · 1 click</p>
            <p className="tile__cap">Fig 3. one-click demo, WebSocket-pulsed live</p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

export function Overview() {
  return (
    <section className="section section--paper" id="overview" aria-labelledby="overview-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[07]</span> overview</p>
          <h2 className="section-title" id="overview-t">Tour the control center.</h2>
          <p className="section-sub">Graph, timeline, inspector — one incident clock.</p>
          <hr className="section-rule" />
        </Reveal>
        <Reveal>
          <div className="tui" role="img" aria-label="Terminal mockup of incident INC-1024 replay: database timeout propagating to checkout">
            <p className="tui__wordmark">C O D E X R A Y</p>
            <div className="tui__screen">
{`$ codexray replay INC-1024 --speed 2x
`}
<span className="t-ok">{`00.0s  user clicks pay                      frontend        ok`}</span>{`
`}
<span className="t-ok">{`00.2s  POST /checkout                      gateway         200`}</span>{`
`}
<span className="t-ok">{`00.4s  jwt validation                      auth            ok`}</span>{`
`}
<span className="t-warn">{`01.1s  SELECT orders WHERE id = ?           postgres        2840ms ... slow`}</span>{`
`}
<span className="t-err">{`02.9s  query timeout                       postgres        x ERROR`}</span>{`
`}
<span className="t-err">{`03.0s  order request fails                 order-service   x`}</span>{`
`}
<span className="t-acc">{`likely root cause: postgres query timeout (confidence 87%)`}</span>
            </div>
            <div className="tui-prompt"><span>|</span><span>build — replay paused at failure</span></div>
            <div className="tui__hints"><span>tab switch service</span><span>ctrl-p commands</span><span>j jump to failure</span></div>
          </div>
        </Reveal>
        <Reveal>
          <div className="replay-bar" aria-label="Replay controls">
            <Link href="/dashboard" title="Open dashboard replay">play</Link>
            <Link href="/dashboard" title="Open dashboard replay">pause</Link>
            <Link href="/dashboard" title="Open dashboard replay">restart</Link>
            <Link href="/dashboard" title="Open dashboard replay">rewind</Link>
            <Link href="/dashboard" title="Open dashboard replay">fast-forward</Link>
            <span aria-hidden="true">0.5x 1x 2x 5x 10x</span>
            <Link href="/dashboard" title="Open dashboard replay">jump to failure</Link>
          </div>
        </Reveal>
        <ul className="api-list">
          <Reveal as="li"><code>POST /api/telemetry</code> — stream spans in</Reveal>
          <Reveal as="li"><code>WS /api/projects/:id/stream</code> — live events out</Reveal>
          <Reveal as="li"><code>GET /api/incidents/:id/replay</code> — replay-ready timelines</Reveal>
        </ul>
        <Reveal>
          <div className="media-block media-block--wide">
            <VideoEmbed
              id="2nTJSsBngao"
              title="Observability, Distributed Tracing & the Complex World"
              channel="Dave McAllister · GOTO Chicago 2019 · 37:26"
              duration="37:26"
            />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function FaqSection() {
  return (
    <section className="section" id="faq" aria-labelledby="faq-t">
      <div className="section__inner">
        <Reveal>
          <p className="section-label"><span className="marker">[08]</span> faq</p>
          <h2 className="section-title" id="faq-t">Questions, answered plainly.</h2>
          <p className="section-sub">The honest version — including what CodeXRay is not.</p>
          <hr className="section-rule" />
        </Reveal>
        <Reveal><Faq /></Reveal>
      </div>
    </section>
  );
}

export function ClosingCta() {
  return (
    <section className="cta-block" aria-labelledby="cta-t">
      <div className="cta-block__inner">
        <Reveal>
          <h2 id="cta-t">
            Stop reading logs. <span className="grad">Start watching.</span>
          </h2>
          <p>
            Install the SDK, stream your first trace, and replay your next
            incident instead of reconstructing it.
          </p>
          <div className="hero__ctas">
            <Link className="btn btn-primary" href="/dashboard">
              Get started
            </Link>
            <a className="btn btn-secondary" href="#overview">
              Watch a replay
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="footer" aria-label="Footer">
      <div className="footer__inner">
        <div className="footer__grid">
          <Link href="/">codexray</Link>
          <a href="#solution">solution</a>
          <Link href="/dashboard">dashboard</Link>
          <a href="#proof">proof</a>
          <a href="#faq">faq</a>
        </div>
        <div className="footer__base">
          <span>(c) 2026 codexray — stop reading logs.</span>
          <span>brand · privacy · terms · english</span>
        </div>
      </div>
    </footer>
  );
}
