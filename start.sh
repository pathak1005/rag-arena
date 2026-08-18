#!/usr/bin/env bash
# Runs FastAPI and Streamlit in one container.
#
# Two things this has to get right:
#  1. ONE uvicorn worker. Indexes live in process memory; a second worker would hold a
#     different graph and different vectors, and requests would nondeterministically hit
#     either. Scaling out means moving state to Neo4j/Chroma first (both implemented).
#  2. Signal handling. Fly sends SIGTERM on deploy and shutdown; without the trap the
#     children survive as zombies and the machine never drains cleanly.
set -euo pipefail

API_PORT="${API_PORT:-8000}"
UI_PORT="${PORT:-8501}"

cleanup() {
  echo "[start.sh] shutting down..."
  kill -TERM "${API_PID:-}" "${UI_PID:-}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

echo "[start.sh] starting API on :${API_PORT}"
uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT}" --workers 1 --no-access-log &
API_PID=$!

# Streamlit must not start before the API can answer, or the first render errors out.
for i in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    echo "[start.sh] API healthy after ${i}s"
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[start.sh] API died during startup" >&2
    exit 1
  fi
  sleep 1
done

echo "[start.sh] starting UI on :${UI_PORT}"
API_BASE="http://127.0.0.1:${API_PORT}" streamlit run ui/streamlit_app.py \
  --server.port "${UI_PORT}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false &
UI_PID=$!

# Exit if either process dies, so the orchestrator restarts the machine.
wait -n "$API_PID" "$UI_PID"
echo "[start.sh] a child process exited; terminating"
cleanup
exit 1
