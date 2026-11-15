#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -d "$ROOT_DIR/.tools/node-v22.14.0-darwin-arm64/bin" ]]; then
  export PATH="$ROOT_DIR/.tools/node-v22.14.0-darwin-arm64/bin:$PATH"
fi

if [[ ! -d "$ROOT_DIR/backend/.venv" ]]; then
  echo "Setting up Python virtual environment in backend/.venv ..."
  python3 -m venv "$ROOT_DIR/backend/.venv"
  "$ROOT_DIR/backend/.venv/bin/pip" install -r "$ROOT_DIR/backend/requirements.txt"
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies ..."
  npm --prefix "$ROOT_DIR/frontend" install
fi

echo "Starting TripSage FastAPI Optimizer on http://127.0.0.1:8000 ..."
"$ROOT_DIR/backend/.venv/bin/uvicorn" main:app --app-dir "$ROOT_DIR/backend" --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

trap "kill $BACKEND_PID 2>/dev/null || true" EXIT

echo "Starting TripSage Next.js Web UI on http://localhost:3000 ..."
npm --prefix "$ROOT_DIR/frontend" run dev
