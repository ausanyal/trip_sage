#!/usr/bin/env bash
set -euo pipefail

export TRIPSAGE_DB_PATH="${TRIPSAGE_DB_PATH:-/tmp/tripsage.db}"
export BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://127.0.0.1:8000}"
LISTEN_PORT="${PORT:-8080}"

echo "[TripSage Cloud Run] Starting FastAPI VRPTW & Arbitrage Engine on 127.0.0.1:8000..."
uvicorn main:app --app-dir /app/backend --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Wait up to 15s for FastAPI health readiness before opening public Cloud Run port
for _ in $(seq 1 30); do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1)" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

echo "[TripSage Cloud Run] Starting Next.js Web UI on 0.0.0.0:${LISTEN_PORT}..."
exec node /app/frontend/node_modules/next/dist/bin/next start /app/frontend --hostname 0.0.0.0 --port "${LISTEN_PORT}"
