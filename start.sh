#!/usr/bin/env bash
# Process launcher. Supports three modes so one image serves all three deployments:
#
#   both (default)   API + UI in one machine          -> fly.toml,        512mb
#   API_ENABLED=0    UI only                          -> deploy/fly.ui.toml,  256mb
#   UI_ENABLED=0     API only                         -> deploy/fly.api.toml, 256mb
#
# Two things this has to get right:
#  1. ONE uvicorn worker. Indexes live in process memory; a second worker holds a
#     different graph and different vectors, and requests hit either nondeterministically.
#     Scaling out means moving state to Neo4j/Chroma first (both implemented).
#  2. Signal handling. Fly sends SIGTERM on deploy and shutdown; without the trap the
#     children survive as zombies and the machine never drains cleanly.
set -euo pipefail

API_PORT="${API_PORT:-8000}"
UI_PORT="${PORT:-8501}"
API_ENABLED="${API_ENABLED:-1}"
UI_ENABLED="${UI_ENABLED:-1}"

API_PID=""
UI_PID=""

cleanup() {
  echo "[start.sh] shutting down..."
  [ -n "$API_PID" ] && kill -TERM "$API_PID" 2>/dev/null || true
  [ -n "$UI_PID" ]  && kill -TERM "$UI_PID"  2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

if [ "$API_ENABLED" = "1" ]; then
  echo "[start.sh] starting API on :${API_PORT}"
  uvicorn app.main:app \
    --host 0.0.0.0 --port "${API_PORT}" \
    --workers 1 --no-access-log --timeout-keep-alive 20 &
  API_PID=$!

  # Streamlit rendering before the API can answer produces a confusing connection error
  # on first paint, so wait on /health rather than sleeping a fixed amount.
  if [ "$UI_ENABLED" = "1" ]; then
    for i in $(seq 1 60); do
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
  fi
fi

if [ "$UI_ENABLED" = "1" ]; then
  # In the split deployment API_BASE points at the other Fly app over .internal;
  # in the combined deployment it is loopback.
  export API_BASE="${API_BASE:-http://127.0.0.1:${API_PORT}}"
  echo "[start.sh] starting UI on :${UI_PORT} (API_BASE=${API_BASE})"
  streamlit run ui/streamlit_app.py \
    --server.port "${UI_PORT}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.fileWatcherType none \
    --browser.gatherUsageStats false &
  UI_PID=$!
fi

if [ -z "$API_PID" ] && [ -z "$UI_PID" ]; then
  echo "[start.sh] nothing to run: API_ENABLED=0 and UI_ENABLED=0" >&2
  exit 1
fi

# Exit if either process dies, so the orchestrator replaces the machine rather than
# leaving a half-dead one serving errors.
wait -n
echo "[start.sh] a child process exited; terminating"
cleanup
exit 1
