"""CodeXRay API — log-line ingestion from `codexray logs`.

Tolerant like span ingest: one bad line never fails the batch. Every
message is redacted before storage (defense in depth — the CLI also
ships raw lines, secrets must not land in the DB).
"""

from __future__ import annotations

import re
import time

from sqlalchemy import insert
from sqlalchemy.orm import Session

from . import models
from .schemas import LogLineIn

_LEVELS = ("debug", "info", "warning", "warn", "error", "fatal", "critical")
_LEVEL_MAP = {"warning": "warn", "fatal": "error", "critical": "error"}

# Free-text secret masking: key=value / key: value where key looks sensitive.
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|apikey|secret|token|authorization)"
    r"(\s*[=:]\s*)(\S+)"
)
_LEVEL_RE = re.compile(
    r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b", re.IGNORECASE
)


def normalize_level(raw: str) -> str:
    s = (raw or "info").strip().lower()
    s = _LEVEL_MAP.get(s, s)
    return s if s in _LEVELS else "info"


def sniff_level(message: str) -> str | None:
    m = _LEVEL_RE.search(message)
    if not m:
        return None
    return normalize_level(m.group(1))


def redact_message(message: str) -> str:
    """Mask secret-looking key=value pairs in free text, then dict-redact
    is a no-op for strings — the regex is the string-path redaction."""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", message)


def process_logs(
    db: Session, project: models.Project, raw_lines: list[tuple[int, LogLineIn]]
) -> dict:
    """Returns {accepted, rejected, broadcasts}."""
    accepted = 0
    rejected: list[dict] = []
    broadcasts: list[dict] = []
    now = time.time()
    rows: list[dict] = []

    for index, line in raw_lines:
        if not line.message or not line.message.strip():
            rejected.append({"index": index, "reason": "empty message"})
            continue
        level = normalize_level(line.level)
        # If the sender left level at default "info" but the text screams
        # ERROR/WARN, trust the text (plain-text tail source).
        if line.level.strip().lower() in ("", "info"):
            sniffed = sniff_level(line.message)
            if sniffed:
                level = sniffed
        message = redact_message(line.message)[:4000]
        ts = line.ts if isinstance(line.ts, (int, float)) and line.ts > 0 else now
        rows.append(
            {
                "project_id": project.id,
                "ts": float(ts),
                "level": level,
                "service": (line.service or "")[:128],
                "message": message,
                "source_file": (line.source_file or "")[:512],
                "received_at": now,
            }
        )
        accepted += 1
        broadcasts.append(
            {
                "type": "log",
                "project_id": project.id,
                "level": level,
                "service": (line.service or ""),
                "message": message,
                "source_file": (line.source_file or ""),
                "ts": float(ts),
            }
        )

    if rows:
        db.execute(insert(models.LogRecord), rows)
    return {"accepted": accepted, "rejected": rejected, "broadcasts": broadcasts}
