"use client";

/* BYOK investigation connection dialog.
   Provider + key + model + optional base URL. The key is validated
   server-side, swapped for an opaque connectionId, then dropped from
   component state — it is never stored in the browser. */

import { useEffect, useState } from "react";
import { ApiError, endpoints, type AiProvider, type ConnectionInfo } from "@/lib/api";

/* Where to mint a key for each provider. Custom/base-URL providers have
   no single canonical console, so no link is shown for those. */
const KEY_LINKS: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  groq: "https://console.groq.com/keys",
  anthropic: "https://console.anthropic.com/settings/keys",
  gemini: "https://aistudio.google.com/apikey",
  openrouter: "https://openrouter.ai/settings/keys",
};

export default function InvestigateDialog({
  onClose,
  pid,
  onConnected,
}: {
  onClose: () => void;
  pid: string;
  onConnected: (conn: ConnectionInfo) => void;
}) {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [providerId, setProviderId] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ model: string; provider: string } | null>(null);
  const [error, setError] = useState("");

  const provider = providers.find((p) => p.id === providerId) ?? null;

  useEffect(() => {
    let alive = true;
    endpoints
      .aiProviders(pid)
      .then((res) => {
        if (!alive) return;
        setProviders(res.providers);
        const first = res.providers[0];
        if (first) {
          setProviderId(first.id);
          setModel(first.models[0] ?? "");
          setBaseUrl(first.defaultBaseUrl ?? "");
        }
      })
      .catch(() => {
        if (alive) setError("Could not load providers — is the API on :3101?");
      });
    return () => {
      alive = false;
    };
  }, [pid]);

  function pickProvider(id: string) {
    setProviderId(id);
    const p = providers.find((x) => x.id === id);
    setModel(p?.models[0] ?? "");
    setBaseUrl(p?.defaultBaseUrl ?? "");
    setDone(null);
    setError("");
  }

  function validate(): string {
    if (!model.trim()) return "Select or enter a model.";
    if (!apiKey.trim()) return "Enter your API key.";
    if (provider?.requiresBaseUrl && !baseUrl.trim()) return "A base URL is required for this provider.";
    return "";
  }

  function errMsg(e: unknown): string {
    if (e instanceof ApiError) return e.message;
    return "Connection failed — check your network and try again.";
  }

  async function test() {
    const v = validate();
    if (v) return setError(v);
    setBusy(true);
    setError("");
    setDone(null);
    try {
      const res = await endpoints.aiTestProvider(pid, {
        provider: providerId,
        model: model.trim(),
        apiKey,
        baseUrl: baseUrl.trim() || null,
      });
      setDone({ model: res.model, provider: provider?.label ?? providerId });
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    const v = validate();
    if (v) return setError(v);
    setBusy(true);
    setError("");
    try {
      const conn = await endpoints.aiConnect(pid, {
        provider: providerId,
        model: model.trim(),
        apiKey,
        baseUrl: baseUrl.trim() || null,
      });
      setApiKey(""); // key has been exchanged for a server-side connection id
      onConnected(conn);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inv-modal" role="dialog" aria-modal="true" aria-label="Investigate with AI">
      <div className="inv-modal__scrim" onClick={onClose} aria-hidden="true" />
      <div className="inv-card">
        <div className="inv-card__head">
          <div>
            <span className="panel__eyebrow">[byok]</span>
            <h2 className="panel__title">Investigate with AI</h2>
          </div>
          <button type="button" className="dash-link" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="inv-hint">
          Connect your own provider. The automatic summary above is on CodeXRay&apos;s budget —
          deep investigation runs on <b>your key</b> and is billed by your provider.
        </p>

        <label className="inv-field">
          <span>Provider</span>
          <select value={providerId} onChange={(e) => pickProvider(e.target.value)}>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="inv-field">
          <span>API key</span>
          <input
            type="password"
            value={apiKey}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Your provider key"
          />
          <span className="inv-keyrow">
            {KEY_LINKS[providerId] ? (
              <a href={KEY_LINKS[providerId]} target="_blank" rel="noopener noreferrer">
                Get a key →
              </a>
            ) : (
              <span>Create one in your provider&apos;s console</span>
            )}
            {providerId === "groq" && <span className="inv-keyrow__note">Free tier · ~30s</span>}
          </span>
        </label>

        <label className="inv-field">
          <span>Model</span>
          <input
            list="inv-models"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="Select or type a model"
          />
          <datalist id="inv-models">
            {provider?.models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>

        {provider?.baseUrlEditable && (
          <label className="inv-field">
            <span>Base URL {provider.requiresBaseUrl ? "(required)" : "(optional)"}</span>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={provider.defaultBaseUrl ?? "https://…/v1"}
            />
          </label>
        )}

        {provider?.note && <p className="inv-note">{provider.note}</p>}

        {done && (
          <div className="inv-ok" role="status">
            ✓ Connected to {done.provider}
            <div className="inv-ok__sub">Model: {done.model}</div>
          </div>
        )}
        {error && (
          <div className="ai-err" role="alert">
            {error}
          </div>
        )}

        <div className="inv-actions replay">
          <button type="button" onClick={test} disabled={busy}>
            {busy ? "Checking…" : "Test Connection"}
          </button>
          <button type="button" className="primary" onClick={connect} disabled={busy}>
            Start investigation
          </button>
        </div>
      </div>
    </div>
  );
}
