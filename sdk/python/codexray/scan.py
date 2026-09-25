"""CodeXRay SDK — static codebase understanding (stdlib `ast` only).

Walks a project and reports what the runtime auto-instrumentation will
see live: framework routes (FastAPI/Flask/Django, best effort) and
downstream-dependency usage per file. Informational: it never modifies
code and never needs to be complete — dynamic routes can hide from
static analysis; the live graph still catches them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".eggs", "*.egg-info",
}

ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

KNOWN_DEPS: tuple[tuple[str, str], ...] = (
    ("httpx", "http"),
    ("requests", "http"),
    ("urllib3", "http"),
    ("groq", "groq"),
    ("openai", "openai"),
    ("anthropic", "anthropic"),
    ("google.generativeai", "gemini"),
    ("google.genai", "gemini"),
    ("sqlalchemy", "database"),
    ("sqlmodel", "database"),
    ("redis", "cache"),
    ("kafka", "queue"),
    ("celery", "queue"),
    ("stripe", "stripe"),
    ("boto3", "aws"),
)


@dataclass
class Route:
    file: str
    line: int
    method: str
    path: str


@dataclass
class ScanResult:
    root: str
    files_scanned: int = 0
    routes: list[Route] = field(default_factory=list)
    deps: dict[str, list[str]] = field(default_factory=dict)


def _route_from_decorator(dec: ast.expr) -> tuple[str, str] | None:
    """Return (method, path) for framework route decorators, else None."""
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    method = dec.func.attr.lower()
    if method not in ROUTE_METHODS and method != "route":
        return None
    if not dec.args or not isinstance(dec.args[0], ast.Constant):
        return None
    path = dec.args[0].value
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    if method == "route":
        methods = {"GET"}
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                methods = {
                    str(e.value).upper()
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                } or methods
        method = sorted(methods)[0].lower()
    return method.upper(), path


def _django_path(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name) and call.func.id in ("path", "re_path"):
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            return call.args[0].value
    return None


def scan_file(path: Path, rel: str, result: ScanResult) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError, OSError):
        return
    result.files_scanned += 1
    found_deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                if node.module:
                    names = [node.module]
            for name in names:
                for mod, label in KNOWN_DEPS:
                    if name == mod or name.startswith(mod + "."):
                        found_deps.add(label)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                route = _route_from_decorator(dec)
                if route:
                    method, route_path = route
                    result.routes.append(Route(file=rel, line=node.lineno, method=method, path=route_path))
        elif isinstance(node, ast.Call):
            dj = _django_path(node)
            if dj:
                result.routes.append(Route(file=rel, line=node.lineno, method="*", path=dj))
    for dep in found_deps:
        result.deps.setdefault(dep, []).append(rel)


def scan(root: str | Path) -> ScanResult:
    base = Path(root).resolve()
    result = ScanResult(root=str(base))
    for path in sorted(base.rglob("*.py")):
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        scan_file(path, str(path.relative_to(base)), result)
    result.routes.sort(key=lambda r: (r.path, r.method))
    return result


def report(result: ScanResult) -> str:
    lines = [
        f"scanned {result.files_scanned} python files under {result.root}",
        "",
        f"routes: {len(result.routes)}",
    ]
    for r in result.routes[:50]:
        lines.append(f"  {r.method:6} {r.path}  ({r.file}:{r.line})")
    if len(result.routes) > 50:
        lines.append(f"  … and {len(result.routes) - 50} more")
    lines += ["", "downstream dependencies:"]
    if not result.deps:
        lines.append("  (none detected)")
    for dep in sorted(result.deps):
        files = result.deps[dep]
        lines.append(f"  {dep}: {len(files)} file(s), e.g. {files[0]}")
    return "\n".join(lines)
