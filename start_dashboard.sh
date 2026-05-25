#!/usr/bin/env bash
# Start OAuth callback server (blank token page) + Streamlit dashboard, then open the browser.
# Run: ./start_dashboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"
STREAMLIT="$VENV/bin/streamlit"
PORT="${STREAMLIT_PORT:-8501}"
AUTH_PORT="${AUTH_PORT:-8000}"

if [[ ! -x "$STREAMLIT" ]]; then
  echo "Virtualenv not ready. Creating .venv and installing dependencies..."
  python3 -m venv "$VENV"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$ROOT/requirements.txt"
fi

free_port() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    for pid in $(lsof -ti:"$p" 2>/dev/null || true); do
      echo "Stopping process on port $p (PID $pid)..."
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
}

free_port "$AUTH_PORT"
free_port "$PORT"

# FastAPI: /callback shows a minimal page + copyable request_token (does not consume token)
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$AUTH_PORT" &
AUTH_PID=$!
trap 'kill ${AUTH_PID:-0} 2>/dev/null || true' EXIT INT TERM
sleep 1

echo ""
echo "OAuth redirect (blank token page): http://127.0.0.1:${AUTH_PORT}/callback"
echo "Set this URL in https://developers.kite.trade as your app Redirect URL, then restart if you changed .env."
echo ""

(
  sleep 3
  if command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT"
  fi
) &

echo "Starting dashboard on http://localhost:$PORT (Ctrl+C stops dashboard and OAuth server)"
# Run ui/app.py directly (no streamlit_app.py wrapper) — the wrapper was causing render issues.
# XSRF/CORS off for local dev so both localhost and 127.0.0.1 work.
"$STREAMLIT" run ui/dashboard.py \
  --server.port "$PORT" \
  --server.enableXsrfProtection false \
  --server.enableCORS false \
  --server.runOnSave true \
  --browser.gatherUsageStats false \
  --server.headless true
