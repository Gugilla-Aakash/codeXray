"use client";

import { useEffect, useState } from "react";
import { API_BASE, licenseRequired, saveAuth } from "@/lib/api";
import { LogoMark } from "@/components/SiteNav";

export default function ApiKeyGate({ onAuthed, initialPid = "" }: { onAuthed: () => void; initialPid?: string }) {
  const [pid, setPid] = useState(initialPid);
  const [key, setKey] = useState("");
  const [license, setLicense] = useState("");
  const [needsLicense, setNeedsLicense] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    licenseRequired()
      .then((required) => {
        if (!cancelled && required) setNeedsLicense(true);
      })
      .catch(() => {
        // ignore — gate behaves as if licensing is off; server still enforces
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    if (!pid.trim() || !key.trim()) {
      setErr("project id and API key are both required");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`${API_BASE}/api/projects/${pid.trim()}/graph`, {
        headers: { "X-API-Key": key.trim() },
      });
      if (!res.ok) throw new Error(res.status === 401 ? "invalid API key" : res.status === 403 ? "key does not match project" : "project not found");
      saveAuth(pid.trim(), key.trim());
      onAuthed();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "connection failed — is the API on :3101?");
    } finally {
      setBusy(false);
    }
  }

  async function loadDemo() {
    if (needsLicense && !license.trim()) {
      setErr("enter your license key to load the demo");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`${API_BASE}/api/demo/setup`, {
        method: "POST",
        headers: license.trim() ? { "X-License-Key": license.trim() } : {},
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = String(((await res.json()) as { detail?: string }).detail ?? "");
        } catch {
          // body not JSON — fall back to status-based messages
        }
        throw new Error(
          res.status === 401
            ? "invalid license key"
            : res.status === 404
              ? "demo setup is disabled on this server"
              : res.status === 429
                ? detail.toLowerCase().includes("license")
                  ? "too many license attempts — try again shortly"
                  : "too many demo setups — try again in a minute"
                : `demo setup failed (${res.status})`
        );
      }
      const body = (await res.json()) as { id: string; api_key: string };
      saveAuth(body.id, body.api_key);
      onAuthed();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "demo setup failed — is the API on :3101?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="gate__card" onSubmit={connect}>
        <LogoMark size={34} />
        <h1>
          CodeXRay <span className="grad">control center</span>
        </h1>
        <p>Watch a real incident in one click — or connect your own project.</p>
        {needsLicense && (
          <>
            <label htmlFor="gate-license">LICENSE KEY</label>
            <input
              id="gate-license"
              type="password"
              value={license}
              onChange={(e) => setLicense(e.target.value)}
              placeholder="cxrl_…"
              autoComplete="off"
            />
          </>
        )}
        <button type="button" className="gate__demo" onClick={() => void loadDemo()} disabled={busy}>
          {busy ? "working…" : "⚡ Load demo project"}
        </button>
        <p className="gate__or">or connect an existing project</p>
        <label htmlFor="gate-pid">PROJECT ID</label>
        <input
          id="gate-pid"
          value={pid}
          onChange={(e) => setPid(e.target.value)}
          placeholder="prj_xxxxxxxx"
          autoComplete="off"
        />
        <label htmlFor="gate-key">API KEY</label>
        <input
          id="gate-key"
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="cxr_…"
          autoComplete="off"
        />
        <button type="submit" disabled={busy}>
          {busy ? "connecting…" : "Connect"}
        </button>
        <p className="gate__err" role="alert">{err}</p>
        <p className="gate__hint">
          Your API key stays in this tab only (sessionStorage) — never leaves your browser.
        </p>
      </form>
    </div>
  );
}
