#!/usr/bin/env bash
# CodeXRay — one-command demo.
# Starts the API (:3101) and web app (:3100), reusing anything already up,
# then prints the dashboard URL. Ctrl-C stops whatever this script started.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
API_URL="http://127.0.0.1:3101"
WEB_URL="http://127.0.0.1:3100"
STARTED_API=0
STARTED_WEB=0
PIDS=()

cleanup() {
  echo ""
  echo "Stopping CodeXRay…"
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

up() { curl -sf -o /dev/null -m 2 "$1" 2>/dev/null; }

# --- API ---
if up "$API_URL/health"; then
  echo "✓ API already running on :3101"
else
  echo "Starting API on :3101…"
  (cd "$ROOT/services/api" && exec ./.venv/bin/python -m uvicorn app.main:app --port 3101) &
  STARTED_API=$!
  PIDS+=("$STARTED_API")
  for _ in $(seq 1 30); do
    up "$API_URL/health" && break
    sleep 1
  done
  up "$API_URL/health" || { echo "✗ API failed to start — check services/api/.venv exists"; exit 1; }
  echo "✓ API ready on :3101"
fi

# --- Web ---
if up "$WEB_URL"; then
  echo "✓ Web already running on :3100"
else
  echo "Starting web on :3100…"
  (cd "$ROOT/apps/web" && exec npm run dev -- --port 3100) &
  STARTED_WEB=$!
  PIDS+=("$STARTED_WEB")
  for _ in $(seq 1 40); do
    up "$WEB_URL" && break
    sleep 1
  done
  up "$WEB_URL" || { echo "✗ Web failed to start on :3100"; exit 1; }
  echo "✓ Web ready on :3100"
fi

echo ""
echo "══════════════════════════════════════════"
echo "  CodeXRay is live"
echo "  Landing:  $WEB_URL/"
echo "  Demo:     $WEB_URL/dashboard"
echo "  API:      $API_URL  (docs at /docs)"
echo ""
echo "  New here? Open the dashboard and click"
echo "  “⚡ Load demo project” — one click, no curl."
echo "══════════════════════════════════════════"
echo ""
echo "Running… Ctrl-C to stop what this script started."

# Wait on whichever children we own (reused servers stay untouched).
WAIT_SET=()
[ "$STARTED_API" -ne 0 ] && WAIT_SET+=("$STARTED_API")
[ "$STARTED_WEB" -ne 0 ] && WAIT_SET+=("$STARTED_WEB")
if [ "${#WAIT_SET[@]}" -gt 0 ]; then
  wait "${WAIT_SET[@]}"
fi
