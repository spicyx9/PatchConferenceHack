#!/usr/bin/env bash
set -euo pipefail
cd /app
: "${DATABASE_URL:?Spawnpoint database is required}"
: "${TRUEFORGE_API_KEY:?Internal TrueForge key is required}"
: "${OPENAI_API_KEY:?OpenAI key is required}"
export FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 FALKORDB_GRAPH=conferge_demo CONFERGE_NETWORK_ROSTER=1
export TRUEFORGE_BASE_URL=http://127.0.0.1:8790
export CONFERGE_API_URL="http://127.0.0.1:${PORT:-8080}"
graph_dir="${SPAWNPOINT_DATA_DIR:-/data}/conferge-graph"
mkdir -p "$graph_dir"
pids=()
cleanup() { for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done; wait || true; }
trap cleanup EXIT
trap 'exit 0' TERM INT
redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes \
  --loadmodule "${FALKORDB_BIN_PATH:-/var/lib/falkordb/bin}/falkordb.so" --dir "$graph_dir" --appendonly yes &
pids+=($!)
# Separate ephemeral Redis for TrueForge's hosted executor coordination.
redis-server --bind 127.0.0.1 --port 6381 --protected-mode yes --save '' --appendonly no &
pids+=($!)
for ((attempt=0; attempt<60; attempt++)); do
  if redis-cli --raw GRAPH.LIST >/dev/null 2>&1; then break; fi
  sleep 1
done
redis-cli --raw GRAPH.LIST >/dev/null
python -m conferge.api.network_roster
python scripts/run_demo.py --mode fixture --travel cached --host 0.0.0.0 --port "${PORT:-8080}" &
pids+=($!)
python integrations/trueforge/server.py &
pids+=($!)
HOST=127.0.0.1 PORT=8790 STANDALONE=false REDIS_URL=redis://127.0.0.1:6381 \
  OUTBOUND_URL_ALLOWED_HOSTS='["127.0.0.1"]' SENTRY_ENABLED=false \
  node /opt/trueforge/node_modules/@truefoundry/trueforge/dist/cli.js &
pids+=($!)
python - <<'PY'
import time
import httpx
for attempt in range(120):
    try:
        if httpx.get('http://127.0.0.1:8790/api/v1/settings/model-providers',timeout=2).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise SystemExit('TrueForge startup timed out')
PY
python integrations/trueforge/configure.py
wait -n "${pids[@]}"
