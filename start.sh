#!/usr/bin/env bash
# Start both backend (FastAPI) and frontend (React) in parallel.
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RootCause AI — Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Backend setup ───────────────────────────────────────────────
cd "$ROOT/backend"

PYTHON3="$(which python3 || echo /Library/Developer/CommandLineTools/usr/bin/python3)"

if [ ! -d ".venv" ]; then
  echo "[backend] Creating virtual environment..."
  "$PYTHON3" -m venv .venv
fi

echo "[backend] Installing Python dependencies..."
.venv/bin/pip install -q -r requirements.txt

# Generate scenario data if not present
if [ ! -d "data/scenarios" ] || [ -z "$(ls data/scenarios 2>/dev/null)" ]; then
  echo "[backend] Generating synthetic data..."
  .venv/bin/python3 synthetic_data_generator.py
fi

echo "[backend] Starting FastAPI on http://localhost:8000 ..."
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# ── 2. Frontend setup ──────────────────────────────────────────────
cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
  echo "[frontend] Installing npm dependencies..."
  npm install --silent
fi

echo "[frontend] Starting React on http://localhost:3000 ..."
npm start &
FRONTEND_PID=$!

echo ""
echo "✓ Backend  → http://localhost:8000"
echo "✓ Frontend → http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."

# Wait for either process to exit
trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit' INT TERM
wait $BACKEND_PID $FRONTEND_PID
