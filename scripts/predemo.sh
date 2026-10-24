#!/usr/bin/env bash
# Run 5 minutes before the demo: FalkorDB up, previous demo server stopped, fresh demo started
# on a reset graph, then the API checked line by line. Leaves the demo running.
# Usage: make predemo   (DEMO_PORT, FALKORDB_PORT, PREDEMO_* overrides honoured)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DEMO_PORT="${DEMO_PORT:-8000}"
HEALTH_TIMEOUT="${PREDEMO_HEALTH_TIMEOUT:-60}"
LOG="$ROOT/logs/predemo-demo.log"
URL="http://127.0.0.1:${DEMO_PORT}/"

echo "== 1. FalkorDB"
uv run python scripts/predemo_check.py falkordb || exit 2

echo "== 2. Previous demo server on port ${DEMO_PORT}"
listeners() { lsof -nP -tiTCP:"${DEMO_PORT}" -sTCP:LISTEN 2>/dev/null || true; }
PIDS="$(listeners)"
if [[ -n "$PIDS" ]]; then
  echo "stopping pid(s) ${PIDS//$'\n'/ }"
  kill $PIDS 2>/dev/null || true
  for _ in $(seq 1 100); do [[ -z "$(listeners)" ]] && break; sleep 0.1; done
  if [[ -n "$(listeners)" ]]; then  # still bound after 10 s: force it
    kill -9 $(listeners) 2>/dev/null || true
    sleep 0.5
  fi
  if [[ -n "$(listeners)" ]]; then
    echo "FAIL  port ${DEMO_PORT} is still in use; free it or run DEMO_PORT=$((DEMO_PORT + 1)) make predemo"
    exit 4
  fi
else
  echo "none"
fi

echo "== 3. Demo on a reset graph (log: logs/predemo-demo.log)"
mkdir -p "$ROOT/logs"
nohup make demo DEMO_PORT="${DEMO_PORT}" DEMO_ARGS=--reset-graph >"$LOG" 2>&1 &
DEMO_PID=$!
started=$(date +%s)
until curl -sf -o /dev/null "http://127.0.0.1:${DEMO_PORT}/health"; do
  if ! kill -0 "$DEMO_PID" 2>/dev/null; then
    echo "FAIL  make demo exited before answering /health; last log lines:"
    tail -n 15 "$LOG"
    exit 3
  fi
  if (( $(date +%s) - started >= HEALTH_TIMEOUT )); then
    echo "FAIL  demo did not answer /health within ${HEALTH_TIMEOUT} s; last log lines:"
    tail -n 15 "$LOG"
    exit 3
  fi
  sleep 0.2
done
echo "up in $(( $(date +%s) - started )) s"

echo "== 4. Checks"
uv run python scripts/predemo_check.py api "http://127.0.0.1:${DEMO_PORT}"
status=$?
echo
echo "Open: ${URL}"
exit $status
