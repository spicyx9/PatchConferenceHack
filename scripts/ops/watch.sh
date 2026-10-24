#!/usr/bin/env bash
# Real monitoring loop. Every INTERVAL seconds: worker liveness, PR state, CI, owned paths,
# auto-merge on green + owned paths, relaunch dead workers without PR (max 3 attempts),
# wave progression, STATUS.md rewrite. Usage: watch.sh [interval_seconds]
set -uo pipefail
INTERVAL="${1:-600}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF="${ROOT}/scripts/ops/workers.conf"; LOGS="${ROOT}/logs"; mkdir -p "$LOGS"
MAX_ACTIVE=6; MAX_ATTEMPTS=3
WAVE2="04 09 10 11"; WAVE2_STARTED="$LOGS/.wave2"
alive() { [[ -f "$LOGS/w$1.pid" ]] && kill -0 "$(cat "$LOGS/w$1.pid")" 2>/dev/null; }
pr_number() { gh pr list --repo "$(git -C "$ROOT" remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')" --head "w$1-$2" --state open --json number --jq '.[0].number' 2>/dev/null; }
owned_ok() { # $1 pr number, $2 owned prefixes csv
  local files; files="$(gh pr diff "$1" --name-only 2>/dev/null)"; [[ -z "$files" ]] && return 1
  local ok=0; IFS=',' read -ra P <<< "$2"
  while IFS= read -r f; do local m=1; for p in "${P[@]}"; do [[ "$f" == "$p"* ]] && { m=0; break; }; done; [[ $m -eq 1 ]] && { echo "  out of scope: $f" >> "$LOGS/watch.log"; ok=1; }; done <<< "$files"
  return $ok
}
while true; do
  cd "$ROOT"; git fetch origin --quiet 2>/dev/null
  ACTIVE=0; ROWS=""; MERGED_WAVE1=0
  while IFS='|' read -r ID SLUG TOOL OWNED; do
    [[ -z "$ID" || "$ID" == \#* ]] && continue
    STATE="queued"; PR=""; CI=""; NOTE=""
    LAST="$(git log -1 --format='%h %ar' "origin/w${ID}-${SLUG}" 2>/dev/null || echo '-')"
    PRN="$(pr_number "$ID" "$SLUG")"
    if git merge-base --is-ancestor "origin/w${ID}-${SLUG}" origin/main 2>/dev/null && [[ -n "$(git log -1 --format=%h origin/w${ID}-${SLUG} 2>/dev/null)" ]] && ! alive "$ID" && [[ -z "$PRN" ]] && [[ -f "$LOGS/w${ID}.merged" ]]; then STATE="merged"; fi
    if [[ -n "$PRN" ]]; then
      PR="#$PRN"; STATE="pr_open"
      CHK="$(gh pr checks "$PRN" --json state --jq '[.[].state] | unique | join(",")' 2>/dev/null)"; CI="${CHK:-pending}"
      if [[ "$CI" == "SUCCESS" ]]; then
        if owned_ok "$PRN" "$OWNED"; then
          if gh pr merge "$PRN" --squash --delete-branch=false >> "$LOGS/watch.log" 2>&1; then STATE="merged"; touch "$LOGS/w${ID}.merged"; NOTE="merged $(date -u +%H:%M)"; else NOTE="merge failed, see watch.log"; fi
        else NOTE="CI green but files out of scope: needs integrator"; fi
      elif [[ "$CI" == *FAILURE* ]]; then NOTE="CI red"; if ! alive "$ID" && [[ $(cat "$LOGS/w${ID}.attempts" 2>/dev/null || echo 0) -lt $MAX_ATTEMPTS ]]; then bash "$ROOT/scripts/ops/launch_worker.sh" "$ID" "$SLUG" "$TOOL" >> "$LOGS/watch.log" 2>&1; NOTE="CI red, worker relaunched"; fi; fi
    elif alive "$ID"; then STATE="running"
    elif [[ -f "$LOGS/w${ID}.pid" ]] && [[ ! -f "$LOGS/w${ID}.merged" ]]; then
      ATT=$(cat "$LOGS/w${ID}.attempts" 2>/dev/null || echo 0)
      if [[ $ATT -lt $MAX_ATTEMPTS ]]; then bash "$ROOT/scripts/ops/launch_worker.sh" "$ID" "$SLUG" "$TOOL" >> "$LOGS/watch.log" 2>&1; STATE="running"; NOTE="relaunched (attempt $((ATT+1)))"; else STATE="failed"; NOTE="3 attempts without PR, needs human"; fi
    fi
    [[ -f "$LOGS/w${ID}.merged" ]] && STATE="merged"
    [[ "$STATE" == "running" || "$STATE" == "pr_open" ]] && ACTIVE=$((ACTIVE+1))
    case " 01 02 03 08 12 13 " in *" $ID "*) [[ "$STATE" == "merged" ]] && MERGED_WAVE1=$((MERGED_WAVE1+1)) ;; esac
    ROWS+="| w${ID} | ${SLUG} | ${TOOL} | ${STATE} | ${LAST} | ${PR:--} | ${CI:--} | ${NOTE:--} |\n"
  done < <(grep -v '^#' "$CONF")
  # wave 2 when slots free and at least 3 of wave 1 merged
  if [[ ! -f "$WAVE2_STARTED" && $ACTIVE -le $((MAX_ACTIVE-2)) && $MERGED_WAVE1 -ge 3 ]]; then
    bash "$ROOT/scripts/ops/launch_wave.sh" 2 >> "$LOGS/watch.log" 2>&1; touch "$WAVE2_STARTED"
  fi
  {
    echo "# STATUS (auto, $(date -u +%FT%TZ)) active=${ACTIVE} wave1_merged=${MERGED_WAVE1}/6"
    echo "| window | slug | tool | state | last commit | PR | CI | note |"
    echo "|---|---|---|---|---|---|---|---|"
    printf "%b" "$ROWS"
    echo; echo "Logs: logs/wNN.log, logs/watch.log. Relaunch a worker: bash scripts/ops/launch_worker.sh NN slug. Launch wave 3 (needs keys in .env of each worktree): bash scripts/ops/launch_wave.sh 3"
  } > "$ROOT/STATUS.md"
  cd "$ROOT" && git add STATUS.md >/dev/null 2>&1 && git commit -qm "status: auto $(date -u +%H:%M)" >/dev/null 2>&1 && git pull --rebase --quiet origin main >/dev/null 2>&1 && git push --quiet origin main >/dev/null 2>&1
  sleep "$INTERVAL"
done
