# Canonical orchestrator — Window 00, Conferge
**Last verified:** foundation CI green, schemas v0.2; actual HEAD and CI are checked by the orchestrator on start.
**For:** an operator launching a local Claude Code/Codex session in `~/HTest` on macOS.

> IMPORTANT: This is an execution playbook, not a command that automatically launches any background worker. The user must start their own local coding-agent sessions. Do not claim work is running unless local process/PR evidence confirms it.

## Scope and authoritative files
- The actual package and schemas v0.2 are `conferge/` and `conferge/core/{schemas,contracts,brightdata,store}.py`; **not** `backend/app/`.
- Read in precedence order: `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, `docs/prompts/README.md`, `docs/START_PARALLEL.md`. Mission is `wNN-<slug>.md` and technical detail is `wNN.md`; see mapping in the prompts README.
- Use `docs/knowledge/` for domain research. You **may prefix** the corrected `docs/prompts/_common.md` and must have each agent read its `docs/prompts/wNN.md` as a technical reference for source-specific endpoints, tests and edge cases. The old paths in those technical specs are illustrative only and must be mapped to the canonical `conferge/` layout. Never execute `wNN.md` *alone* as a standalone mission.
- Execute the **canonical mission** `docs/prompts/wNN-<slug>.md` from its worktree, using the exact branch names in `docs/WORKSTREAMS.md`; consult its detailed `docs/prompts/wNN.md` but never follow conflicting paths, signatures or direct MERGE instructions.
- Do not unzip another starter, alter core contracts from feature branches, push credentials, or silently turn failures into fixture successes.
- Target technologies: **Bright Data and FalkorDB**. Qodo is optional supplemental PR review only and must not obstruct progress if not installed.

## First commands in the already-cloned repo
```bash
cd ~/HTest
git switch main
git pull --ff-only origin main
make check
bash scripts/create_worktrees.sh
git worktree list
```
The script creates `~/HTest-wNN-slug` directories with branches `wNN-slug`. Do not clone the repo again and do not invent `../conferge-wNN` folders.

## Launch order (at most six concurrently ACTIVE coding-agent sessions total, not six per window)
**Wave 1:** w01-luma-partiful (Codex), w02-eventbrite-aggregators (Codex), w03-official (Codex), w08-graph (Claude Code), w12-api (Codex), w13-demo (Codex).
**Wave 2, when slots free:** w04-discovery (Codex, mock/no secrets), w09-planner (Claude Code), w10-antifomo (Claude Code).
**Wave 3, when provider credentials are available:** w05-lodging (Codex), w06-flights (Codex), w07-people (Claude Code), and w04 live probe.
**Optional only if the demo works:** w11-travel (Codex); w15-integration (Claude Code) integrates and tests all modules, and should start smoke-checking after early merges.

Every agent must run in **its own existing worktree**, first verify `pwd` and `git branch --show-current`, own only the paths defined in `docs/WORKSTREAMS.md`, run `make check`, generate a probe/report when applicable, commit, push its own branch and open a PR. Agents do not merge their own PRs. Claude Code subagents and Codex CLI processes are **different runtimes**: don't call a Claude-only subagent a Codex run. Launch a real Codex CLI process in a specific worktree when that tool is available; otherwise use a scoped coding agent with the same canonical mission.

## Window 00 integrator loop, when locally invoked
1. Before launching each wave, confirm `main` CI green, confirm both `claude` and `codex` CLI installations if splitting providers, update `STATUS.md` with actual branch/PR status.
2. Review PR changed file paths for workstream ownership and validate CI/test evidence. Review small relevant code hunks for risks (dates, prices, provenance, graph writes), not just CI.
3. Do not merge conflicts or stale/failing CI blindly. Request correction or isolate tiny core changes as a separate integrator-owned PR. Never assume green CI alone proves correctness; inspect risk-bearing patches.
4. Merge only after acceptable review; log merge SHA, mode (live/cached/fixture) and open blockers in `STATUS.md`. Never force push, never rewrite another worktree's uncommitted changes.
5. Do not auto-rebase a worktree while its coding agent is running. Ask it to sync with `main` when appropriate. The six-active-agent limit covers all nested subagents and external CLI processes together.
6. Keep `main` deployable; test a minimal GitHub Universe → candidates → FalkorDB path → planning → UI scenario early. Full travel data must not block the core judge-facing demo.
7. Any live provider failure must remain explicitly failed/degraded or explicitly fixture, with preserved `source_url`, `collected_at`, `termination` and reason.
8. Record only verified facts in `STATUS.md`, and architecture decisions in `DECISIONS.md`. If the local session stops, restart it using these files; avoid claiming automatic ongoing supervision.

## Demo acceptance
- GitHub Universe 2026, Fort Mason, 28–29 Oct; NYC → SF 27–30 Oct; objectives seed investors, founders of AI agents, Copilot PMs.
- Demonstrate Bright Data in a real observed source when credentials permit, otherwise show a prominent **fixture** badge and say live remains unverified.
- Demonstrate real FalkorDB graph traversal with **explainable, source-backed edges**; public speaker listing is not proof of third-party event attendance.
- Explain one ranked opportunity and one conflict/replanning decision in a working UI; preserve an offline fixture rehearsal.
- Verify screenshots/runbook and submission requirements separately; do not assume that a green unit-test workflow proves the full product.

## Human operator checklist
1. Read `STATUS.md` and confirm the actual GitHub CI run.
2. Only start local agents with the normal approvals/sandbox controls; **do not use `claude --dangerously-skip-permissions` unattended**. The Mac must remain awake and the terminal session running for overnight work, but neither is guaranteed by this document.
3. Provider keys belong only in local `.env` (gitignored), not PRs, docs, fixtures, stdout or screenshots.
4. Check live-probe outputs and PR summaries before enabling merges. Keep a short feature-freeze period before the jury demo.
