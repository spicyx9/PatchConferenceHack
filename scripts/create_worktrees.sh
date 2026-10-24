#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || { echo 'commit/stash changes first' >&2; exit 1; }
[[ "$(git -C "$ROOT" branch --show-current)" == 'main' ]] || { echo 'run from main' >&2; exit 1; }
BASE="$ROOT"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"
for SPEC in 01:luma-partiful 02:eventbrite-aggregators 03:official 04:discovery 05:lodging 06:flights 07:people 08:graph 09:planner 10:antifomo 11:travel 12:api 13:demo 15:integration; do
  ID="${SPEC%%:*}"
  SLUG="${SPEC#*:}"
  BRANCH="w${ID}-${SLUG}"
  TARGET="${PARENT}/${NAME}-${BRANCH}"
  if [[ -e "$TARGET" ]]; then
    echo "Already exists: $TARGET"
  elif git -C "$ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$ROOT" worktree add "$TARGET" "$BRANCH"
  else
    git -C "$ROOT" worktree add -b "$BRANCH" "$TARGET" main
  fi
  echo "$BRANCH -> $TARGET"
done
