# codexray-sdk

Watch your software think. Zero-dependency Python telemetry for CodeXRay.

```bash
pip install codexray-sdk
cd your-project
codexray init                        # creates the CodeXRay project
codexray serve --app app.main:app    # serve with live tracing
codexray logs path/to/app.log        # tail a log file → dashboard Logs panel
codexray logs path/to/logs/          # or a whole directory of *.log/*.jsonl
# → open the printed dashboard link
```

Local development (from this repo):

```bash
pip install -e /path/to/sdk/python
```

Manual spans for deeper causality (DB calls, LLM calls, jobs):

```python
from codexray import Tracer

tracer = Tracer(service="my-api", api_url="http://127.0.0.1:3101", api_key="cxr_...")

with tracer.span("groq chat", service="groq", metadata={"model": "llama-3.1-8b-instant"}):
    answer = chat(...)
```

`codexray doctor` checks API reachability + auth. Telemetry failures never
raise into your app.
