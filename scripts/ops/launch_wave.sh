#!/usr/bin/env bash
# Launches a wave of workers. Usage: launch_wave.sh 1|2|3  (or a list of ids: launch_wave.sh 01 02 08)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF="${ROOT}/scripts/ops/workers.conf"
case "${1:-}" in
  1) IDS="01 02 03 08 12 13" ;;
  2) IDS="04 09 10 11" ;;
  3) IDS="05 06 07" ;;
  *) IDS="$*" ;;
esac
active_count() {
  local count=0 pidfile
  for pidfile in "${ROOT}"/logs/w*.pid; do
    [[ -f "$pidfile" ]] || continue
    kill -0 "$(cat "$pidfile")" 2>/dev/null && count=$((count+1))
  done
  echo "$count"
}
for ID in $IDS; do
  if [[ $(active_count) -ge 6 ]]; then
    echo "Worker limit reached (6). Not launching remaining workers." >&2
    exit 1
  fi
  LINE="$(grep -E "^${ID}\|" "$CONF")"
  SLUG="$(echo "$LINE" | cut -d'|' -f2)"; TOOL="$(echo "$LINE" | cut -d'|' -f3)"
  bash "${ROOT}/scripts/ops/launch_worker.sh" "$ID" "$SLUG" "$TOOL"
  sleep 5
done
