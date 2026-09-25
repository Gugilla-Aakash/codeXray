"""CodeXRay SDK — tail a file (or directory of logs) and ship lines.

Stdlib only. Byte-offset tail: picks up appends, survives rotation
(shrink resets to 0), buffers partial lines until newline. Directory
mode never reads a file whose resolved path escapes the root — the
enterprise promise: only what you pointed at.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

_LEVEL_RE = re.compile(
    r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b", re.IGNORECASE
)
_LEVEL_MAP = {"warning": "warn", "fatal": "error", "critical": "error"}
_LEVELS = {"debug", "info", "warn", "error"}


def normalize_level(raw: str) -> str:
    s = (raw or "info").strip().lower()
    s = _LEVEL_MAP.get(s, s)
    return s if s in _LEVELS else "info"


def sniff_level(message: str) -> str:
    m = _LEVEL_RE.search(message)
    return normalize_level(m.group(1)) if m else "info"


def parse_line(raw: str, source_file: str, service: str) -> dict | None:
    """One text/JSONL line -> telemetry log dict, or None for blank."""
    raw = raw.rstrip("\n")
    if not raw.strip():
        return None
    if raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                msg = obj.get("msg") or obj.get("message") or obj.get("text")
                if msg is None:
                    msg = raw
                level = normalize_level(str(obj.get("level", "") or ""))
                if str(obj.get("level", "") or "").strip().lower() in ("", "info"):
                    sniffed = sniff_level(str(msg))
                    if sniffed != "info":
                        level = sniffed
                ts = obj.get("ts") or obj.get("time") or obj.get("timestamp")
                svc = str(obj.get("service") or service)
                return {
                    "level": level,
                    "message": str(msg)[:4000],
                    "service": svc[:128],
                    "source_file": source_file,
                    "ts": float(ts) if isinstance(ts, (int, float)) else None,
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # plain-text fallback
    return {
        "level": sniff_level(raw),
        "message": raw[:4000],
        "service": service[:128],
        "source_file": source_file,
        "ts": None,
    }


class _FileTail:
    """Offset tracker for one file. Incomplete last line stays buffered."""

    def __init__(self, path: Path, from_start: bool = False) -> None:
        self.path = path
        self.offset = 0 if from_start else path.stat().st_size
        self._partial = ""

    def read_new(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:
            # Rotation / truncate: start over from the beginning.
            self.offset = 0
            self._partial = ""
        if size == self.offset:
            return []
        with self.path.open("rb") as f:
            f.seek(self.offset)
            chunk = f.read(size - self.offset)
        self.offset = size
        text = self._partial + chunk.decode("utf-8", errors="replace")
        if not text.endswith("\n"):
            # Hold the incomplete tail for the next poll.
            cut = text.rfind("\n")
            if cut == -1:
                self._partial = text
                return []
            self._partial = text[cut + 1 :]
            text = text[: cut + 1]
        else:
            self._partial = ""
        return [ln for ln in text.splitlines() if ln.strip()]


def resolve_targets(path: Path) -> list[Path]:
    """Files to tail in a directory; refuses symlink/traversal escapes."""
    root_res = path.resolve()
    out: list[Path] = []
    for child in sorted(path.iterdir()):
        if not child.is_file():
            continue
        if child.suffix not in (".log", ".jsonl", ".txt"):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(root_res):
            out.append(child)
    return out


class LogTailer:
    """Polls one file or directory, yields parsed log dicts."""

    def __init__(
        self,
        path: Path,
        service: str = "",
        from_start: bool = False,
        poll: float = 1.0,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        self.watch = path
        self.is_file = path.is_file()
        self.service = service or (path.stem if self.is_file else path.name)
        self.from_start = from_start
        self.poll = poll
        self._tails: dict[Path, _FileTail] = {}

    def _targets(self) -> list[Path]:
        if self.is_file:
            return [self.watch]
        return resolve_targets(self.watch)

    def poll_once(self) -> list[dict]:
        lines: list[dict] = []
        for f in self._targets():
            tail = self._tails.get(f)
            if tail is None:
                tail = _FileTail(f, from_start=self.from_start)
                self._tails[f] = tail
            source = str(f)
            for raw in tail.read_new():
                parsed = parse_line(raw, source, self.service)
                if parsed:
                    lines.append(parsed)
        return lines

    def stream(self, stop: Callable[[], bool] | None = None) -> Iterator[list[dict]]:
        """Yield batches forever (or until stop() is true)."""
        while stop is None or not stop():
            batch = self.poll_once()
            if batch:
                yield batch
            time.sleep(self.poll)


def ship_lines(
    api_url: str, api_key: str, lines: list[dict], timeout: float = 3.0
) -> bool:
    """POST a batch to /api/logs. Returns False on network failure (caller
    decides to retry or drop — never raises)."""
    if not lines:
        return True
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/logs",
        data=json.dumps({"lines": lines}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False
