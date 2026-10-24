#!/usr/bin/env bash
# Launches ONE real worker process in its own worktree, detached, with logs.
# Usage: launch_worker.sh 01 luma-partiful [claude|codex]
set -euo pipefail
ID="$1"; SLUG="$2"; TOOL="${3:-claude}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PARENT="$(dirname "$ROOT")"; NAME="$(basename "$ROOT")"
BRANCH="w${ID}-${SLUG}"; WT="${PARENT}/${NAME}-${BRANCH}"
LOGS="${ROOT}/logs"; mkdir -p "$LOGS"
# Idempotent: never create a second process for a worker already running.
if [[ -f "$LOGS/w${ID}.pid" ]] && kill -0 "$(cat "$LOGS/w${ID}.pid")" 2>/dev/null; then
  echo "w${ID}: already running, pid $(cat "$LOGS/w${ID}.pid")"
  exit 0
fi
if [[ ! -d "$WT" ]]; then git -C "$ROOT" worktree add -b "$BRANCH" "$WT" main 2>/dev/null || git -C "$ROOT" worktree add "$WT" "$BRANCH"; fi
if [[ "$(git -C "$WT" branch --show-current)" != "$BRANCH" ]]; then
  echo "w${ID}: wrong branch in $WT; refusing to launch" >&2
  exit 1
fi
# Do not automatically rebase a paused worker with uncommitted changes.
git -C "$WT" fetch origin main --quiet
PROMPT="$(bash "${ROOT}/scripts/ops/worker_prompt.sh" "$ID" "$SLUG")"
ATTEMPT_FILE="$LOGS/w${ID}.attempts"; ATT=$(( $(cat "$ATTEMPT_FILE" 2>/dev/null || echo 0) + 1 )); echo "$ATT" > "$ATTEMPT_FILE"
if [[ "$ATT" -gt 1 ]]; then PROMPT="Reprise numero ${ATT} : reprends depuis l'etat actuel de la branche (git log, git status), lis STATUS.md a la racine du repo principal si present, ne refais pas ce qui est commite. ${PROMPT}"; fi
echo "=== launch w${ID} ${SLUG} tool=${TOOL} attempt=${ATT} $(date -u +%FT%TZ) ===" >> "$LOGS/w${ID}.log"
cd "$WT"
if [[ "$TOOL" == "codex" ]] && command -v codex >/dev/null 2>&1; then
  nohup codex exec --cd "$WT" --full-auto "$PROMPT" >> "$LOGS/w${ID}.log" 2>&1 &
else
  nohup claude -p "$PROMPT" --output-format text >> "$LOGS/w${ID}.log" 2>&1 &
fi
echo $! > "$LOGS/w${ID}.pid"
echo "w${ID}-${SLUG} launched pid $(cat "$LOGS/w${ID}.pid") in $WT (log: logs/w${ID}.log)"
