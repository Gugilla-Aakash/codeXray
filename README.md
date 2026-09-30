# CodeXRay

[![CI](https://github.com/Gugilla-Aakash/codeXray/actions/workflows/ci.yml/badge.svg)](https://github.com/Gugilla-Aakash/codeXray/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/codexray-sdk.svg)](https://pypi.org/project/codexray-sdk/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Watch your software think.**

CodeXRay is an open-source observability toolkit: live distributed tracing,
incident replay, and a deterministic root-cause engine — with optional
bring-your-own-key AI investigation that quotes engine evidence instead of
inventing it.

## Features

- **Distributed tracing** — SDK spans land over HTTP, grouped into traces
  with a service dependency graph.
- **Incident replay** — step through an incident's timeline event by event.
- **Deterministic root-cause** — a rules engine ranks suspects and cites the
  evidence; confidence is computed, not guessed.
- **Log ingestion** — tail `*.log` / `*.jsonl` files into the dashboard's
  Logs panel (`codexray logs`).
- **Live stream** — a WebSocket feed pushes new traces/incidents to the
  dashboard as they happen.
- **BYOK AI investigation** — optional LLM summaries that quote engine
  evidence (`litellm`; bring your own Groq/OpenAI key).

## Status

Landed in this repo so far: the **API** (`services/api`) and the
**Python SDK** (`sdk/python`, published as
[`codexray-sdk`](https://pypi.org/project/codexray-sdk/)). The **web
dashboard** and the **JS SDK** are landing here next, file by file.

## Quickstart

Run the API (no config needed — it falls back to a local SQLite file):

```bash
git clone https://github.com/Gugilla-Aakash/codeXray.git
cd codeXray/services/api
pip install -r requirements.txt
uvicorn app.main:app --port 3101        # docs at http://127.0.0.1:3101/docs
```

Instrument your app with the SDK:

```bash
pip install codexray-sdk
cd your-project
codexray init                            # creates .codexray.json
codexray serve --app app.main:app        # serve with live tracing
codexray logs path/to/app.log            # tail a log file → dashboard
codexray doctor                          # check API reachability + auth
```

## Stack

- **API** — FastAPI (`services/api`)
- **Web** — Next.js dashboard (`apps/web`)
- **SDKs** — `codexray-sdk` (Python), `@codexray/browser` (JS)

## Repository layout

```
services/api/    FastAPI backend: ingest, traces, replay, root-cause, AI
sdk/python/      codexray-sdk — CLI + tracer middleware (on PyPI)
apps/web/        Next.js dashboard (landing next)
sdk/js/          @codexray/browser SDK (landing next)
```

## SaaS licensing

Set `CODEXRAY_LICENSE_KEY` in `services/api/.env` to a comma/newline-separated
list of valid license keys. `codexray init`, `POST /api/projects`, and
`POST /api/demo/setup` then require a matching key (`X-License-Key` header;
the CLI prompts in a box). Unset = open mode, no gating.

## License

MIT
