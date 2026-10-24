#!/usr/bin/env bash
# Verifies everything needed for an unattended night. Exit non-zero if something is missing.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"; FAIL=0
chk() { if "$@" >/dev/null 2>&1; then echo "ok   $*"; else echo "FAIL $*"; FAIL=1; fi; }
chk command -v claude
chk command -v gh
chk gh auth status
chk command -v uv
chk command -v docker
chk git -C "$ROOT" diff --quiet
chk test -f .claude/settings.json
chk test -f scripts/ops/workers.conf
chk bash -c 'cd "$0" && make check' "$ROOT"
command -v codex >/dev/null 2>&1 && echo "ok   codex available (optional)" || echo "info codex not installed: codex workers fall back to claude"
[[ $FAIL -eq 0 ]] && echo "PREFLIGHT OK" || { echo "PREFLIGHT FAILED"; exit 1; }
