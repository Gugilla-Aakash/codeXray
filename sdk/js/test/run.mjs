import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

const mod = await import("../src/index.js");

function installDom() {
  const posted = [];
  const calls = [];
  globalThis.window = {
    fetch: async (input, init = {}) => {
      calls.push({ input, init });
      return { status: 200 };
    },
  };
  globalThis.fetch = async (url, init = {}) => {
    posted.push({ url, init });
    return { status: 200 };
  };
  globalThis.document = { addEventListener: () => {} };
  globalThis.location = { pathname: "/scan" };
  return { posted, calls };
}

async function tick() {
  await new Promise((r) => setTimeout(r, 10));
}

describe("browser sdk", () => {
  beforeEach(() => {
    mod.__reset();
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.location;
    delete globalThis.fetch;
  });

  it("fetch wrapper attaches trace headers and emits a span", async () => {
    const { posted, calls } = installDom();
    mod.init({ apiUrl: "http://api:3101", apiKey: "k", service: "web" });
    await globalThis.window.fetch("http://app/api/items?page=2", { method: "POST" });
    await tick();
    assert.equal(calls.length, 1);
    const headers = calls[0].init.headers;
    const traceId = headers.get("X-CodeXRay-Trace");
    const parentId = headers.get("X-CodeXRay-Parent");
    assert.match(traceId, /^[0-9a-f]{16}$/);
    assert.match(parentId, /^[0-9a-f]{16}$/);
    // pageview (init) + fetch span, same trace
    const bodies = posted.map((p) => JSON.parse(p.init.body));
    const ops = bodies.flatMap((b) => b.events.map((ev) => ev.operation));
    assert.ok(ops.some((o) => o.startsWith("POST http://app/api/items")));
    const fetchEv = bodies
      .flatMap((b) => b.events)
      .find((ev) => ev.service === "web" && ev.span_id === parentId);
    assert.ok(fetchEv);
    assert.equal(fetchEv.trace_id, traceId);
    assert.equal(posted[0].init.headers["X-API-Key"], "k");
  });

  it("failed fetch still emits an error span and rethrows", async () => {
    const { posted } = installDom();
    globalThis.window.fetch = async () => {
      throw new TypeError("network down");
    };
    mod.init({ apiUrl: "http://api:3101", apiKey: "k" });
    await assert.rejects(globalThis.window.fetch("http://app/x"), /network down/);
    await tick();
    const errs = posted
      .flatMap((p) => JSON.parse(p.init.body).events)
      .filter((ev) => ev.status === "error");
    assert.equal(errs.length, 1);
    assert.equal(errs[0].error.type, "FetchError");
  });

  it("sends the api key on every post", async () => {
    const { posted } = installDom();
    mod.init({ apiUrl: "http://api:3101", apiKey: "secret-k" });
    mod.traceAction("scan-url", { text: "Scan" });
    await tick();
    assert.ok(posted.length >= 1);
    for (const p of posted) {
      assert.equal(p.init.headers["X-API-Key"], "secret-k");
      assert.equal("keepalive" in p.init, false);
    }
    const ops = posted.flatMap((p) => JSON.parse(p.init.body).events.map((ev) => ev.operation));
    assert.ok(ops.some((o) => o.startsWith("click: scan-url")));
  });

  it("does nothing without config and never throws", async () => {
    installDom();
    mod.init({});
    mod.traceAction("x");
    mod.pageview();
    await tick();
    assert.ok(true);
  });

  it("never traces its own telemetry posts", async () => {
    const { posted } = installDom();
    mod.init({ apiUrl: "http://api:3101", apiKey: "k" });
    await tick();
    const before = posted.length;
    // a wrapped fetch aimed at the telemetry endpoint itself must pass
    // through untouched: no span, no headers, no recursion.
    await globalThis.window.fetch("http://api:3101/api/telemetry", { method: "POST", body: "{}" });
    await tick();
    const ops = posted
      .slice(before)
      .flatMap((p) => JSON.parse(p.init.body).events.map((ev) => ev.operation));
    assert.ok(!ops.some((o) => o.includes("/api/telemetry")));
  });
});
