"""CodeXRay CLI — `init`, `serve`, `doctor` (stdlib only)."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DASHBOARD = "http://localhost:3100/dashboard"
CONFIG_FILE = ".codexray.json"


def _api(api_url: str, method: str, path: str, key: str = "", body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode() if body is not None or method == "POST" else None
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json", **({"X-API-Key": key} if key else {})},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode() or "{}")


def _create_project(api_url: str, name: str) -> dict:
    """POST /api/projects (open — no license key required)."""
    data = json.dumps({"name": name, "environment": "local"}).encode()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/projects",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode() or "{}")


def _find_config() -> Path | None:
    probe = Path.cwd()
    for _ in range(5):
        candidate = probe / CONFIG_FILE
        if candidate.exists():
            return candidate
        if probe.parent == probe:
            break
        probe = probe.parent
    return None


def _load_config() -> dict:
    found = _find_config()
    if found is None:
        sys.exit(f"no {CONFIG_FILE} here — run `codexray init` first")
    return json.loads(found.read_text())


def cmd_init(args: argparse.Namespace) -> int:
    existing = _find_config()
    if existing is not None and not args.force:
        try:
            old = json.loads(existing.read_text())
            print(f"already initialized here: project {old.get('project_id')} ({existing})")
        except Exception:
            print(f"{CONFIG_FILE} already exists here")
        print("rerun with --force to replace it (old key keeps working server-side)")
        return 2
    try:
        proj = _create_project(args.api, args.name)
    except urllib.error.HTTPError as exc:
        print(f"cannot reach CodeXRay API at {args.api}: HTTP {exc.code}")
        print("is it running? (services/api → uvicorn on :3101)")
        return 1
    except Exception as exc:
        print(f"cannot reach CodeXRay API at {args.api}: {exc}")
        print("is it running? (services/api → uvicorn on :3101)")
        return 1
    # Keep credentials out of git: nearest .gitignore at or above CWD.
    Path(CONFIG_FILE).write_text(
        json.dumps(
            {
                "api_url": args.api,
                "project_id": proj["id"],
                "api_key": proj["api_key"],
                "dashboard": DASHBOARD,
            },
            indent=2,
        )
    )
    ignored = False
    probe = Path.cwd()
    for _ in range(4):
        gi = probe / ".gitignore"
        if gi.exists():
            lines = gi.read_text().splitlines()
            if CONFIG_FILE not in lines:
                with gi.open("a") as f:
                    f.write(f"\n# CodeXRay project credentials (local only)\n{CONFIG_FILE}\n")
            ignored = True
            break
        if probe.parent == probe:
            break
        probe = probe.parent
    if not ignored:
        print(f"warning: no .gitignore found — add `{CONFIG_FILE}` to one manually")
    print(f"project {proj['id']} created and saved to {CONFIG_FILE}")
    print(f"dashboard: {DASHBOARD}  (project id is prefilled via ?pid=)")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _load_config()
    try:
        with urllib.request.urlopen(f"{cfg['api_url'].rstrip('/')}/health", timeout=5):
            pass
        print("API: reachable")
    except Exception as exc:
        print(f"API: UNREACHABLE ({exc})")
        return 1
    try:
        g = _api(cfg["api_url"], "GET", f"/api/projects/{cfg['project_id']}/graph", key=cfg["api_key"])
        print(f"auth: ok — {g['summary']['services']} services known")
    except Exception as exc:
        print(f"auth: FAILED ({exc}) — rerun `codexray init`")
        return 1
    print(f"dashboard: {DASHBOARD}?pid={cfg['project_id']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = _load_config()
    try:
        import uvicorn  # type: ignore
    except ImportError:
        sys.exit("uvicorn is not installed in this environment")
    from .middleware import CodeXRayMiddleware
    from .tracer import Tracer

    mod_name, _, attr = args.app.partition(":")
    if not attr:
        sys.exit("use --app dotted.path:attr  (e.g. --app app.main:app)")
    sys.path.insert(0, str(Path.cwd()))
    try:
        inner = getattr(importlib.import_module(mod_name), attr)
    except (ImportError, AttributeError) as exc:
        sys.exit(f"cannot import {args.app}: {exc}")

    tracer = Tracer(
        service=args.service,
        api_url=cfg["api_url"],
        api_key=cfg["api_key"],
    )
    wrapped = CodeXRayMiddleware(inner, tracer, service=args.service, split_services=args.split_services)
    print(f"live: {args.service} → project {cfg['project_id']}")
    print(f"dashboard: {DASHBOARD}?pid={cfg['project_id']}")
    print("press Ctrl+C to stop (pending spans flush on exit)")
    try:
        uvicorn.run(wrapped, host="127.0.0.1", port=args.port)
    except KeyboardInterrupt:
        pass
    finally:
        tracer.close()
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from .scan import report, scan

    print(report(scan(args.path)))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Tail a log file/directory and stream lines to the CodeXRay API."""
    from .logtail import LogTailer, ship_lines

    cfg = _load_config()
    path = Path(args.path).expanduser()
    if not path.exists():
        sys.exit(f"{path} does not exist")
    try:
        tailer = LogTailer(
            path,
            service=args.service or "",
            from_start=args.from_start,
            poll=args.poll,
        )
    except PermissionError as exc:
        sys.exit(str(exc))
    print(f"watching: {path}  (service: {tailer.service})")
    print(f"project:  {cfg['project_id']}  api: {cfg['api_url']}")
    print(f"dashboard: {DASHBOARD}?pid={cfg['project_id']}")
    print("Ctrl+C to stop")
    shipped = 0
    dropped = 0
    try:
        while True:
            batch = tailer.poll_once()
            if batch:
                # Ship in chunks so one huge append never exceeds body limits.
                for i in range(0, len(batch), 100):
                    chunk = batch[i : i + 100]
                    if ship_lines(cfg["api_url"], cfg["api_key"], chunk):
                        shipped += len(chunk)
                    else:
                        dropped += len(chunk)
                        print(f"warn: could not ship {len(chunk)} lines (API down?)")
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print(f"\nstopped — shipped {shipped} lines" + (f", dropped {dropped}" if dropped else ""))
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codexray", description="Watch your software think")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create a CodeXRay project here")
    p_init.add_argument("--api", default="http://127.0.0.1:3101")
    p_init.add_argument("--name", default=Path.cwd().name)
    p_init.add_argument("--force", action="store_true", help="replace existing .codexray.json")
    p_init.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="check API + auth").set_defaults(fn=cmd_doctor)

    p_serve = sub.add_parser("serve", help="serve an ASGI app with live tracing")
    p_serve.add_argument("--app", required=True, help="dotted.path:attr, e.g. app.main:app")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--service", default=Path.cwd().name.lower().replace(" ", "-"))
    p_serve.add_argument(
        "--split-services",
        action="store_true",
        help="one graph node per route prefix instead of a single service node",
    )
    p_serve.set_defaults(fn=cmd_serve)

    p_scan = sub.add_parser("scan", help="inventory routes + downstream deps of a codebase")
    p_scan.add_argument("path", nargs="?", default=".")
    p_scan.set_defaults(fn=cmd_scan)

    p_logs = sub.add_parser(
        "logs", help="tail a log file (or directory) and stream it to the dashboard"
    )
    p_logs.add_argument("path", help="log file or directory of *.log/*.jsonl/*.txt")
    p_logs.add_argument("--service", default="", help="service label (default: file/dir name)")
    p_logs.add_argument(
        "--from-start",
        action="store_true",
        help="send existing content first (default: only new lines)",
    )
    p_logs.add_argument("--poll", type=float, default=1.0, help="poll interval seconds")
    p_logs.set_defaults(fn=cmd_logs)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
