# CodeXRay

**Watch your software think.**

CodeXRay is an open-source observability toolkit: live distributed tracing,
incident replay, and a deterministic root-cause engine — with optional
bring-your-own-key AI investigation that quotes engine evidence instead of
inventing it.

## Stack

- **API** — FastAPI (`services/api`)
- **Web** — Next.js dashboard (`apps/web`)
- **SDKs** — `codexray-sdk` (Python), `@codexray/browser` (JS)

## SaaS licensing

Set `CODEXRAY_LICENSE_KEY` in `services/api/.env` to a comma/newline-separated
list of valid license keys. `codexray init`, `POST /api/projects`, and
`POST /api/demo/setup` then require a matching key (`X-License-Key` header;
the CLI prompts in a box). Unset = open mode, no gating.

## License

MIT
