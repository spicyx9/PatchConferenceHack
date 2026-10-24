## CANONICAL STRUCTURE — READ THIS FIRST (updated 2026-10-23 PT)

Window 00 is already completed on the **actual** Python package `conferge/` with green CI.
Authoritative instructions, in order: `CLAUDE.md` → `docs/CONTRACTS.md` → `docs/WORKSTREAMS.md` → `docs/prompts/wNN-<slug>.md`.
The `docs/knowledge/` directory is a research/reference library, **not a source of repo paths or schemas**.
The alternate `docs/prompts/wNN.md` and `docs/prompts/_common.md` were authored for an old `backend/app/` proposal and are **legacy, not executable**. Do not follow their branch names, directory names, signature requirements, or instructions to unzip a starter.
Do not recreate the repository, re-unzip files, rename packages, or change `conferge/core` contracts. Use the exact existing `scripts/create_worktrees.sh`.
The orchestrator's final instructions are `docs/ORCHESTRATOR_CANONICAL.md` and the progress ledger is `STATUS.md`.
Never run unattended with `--dangerously-skip-permissions`. Keep CI, permissions and path ownership enforced. Qodo reviews, if available, are auxiliary; sponsor tracks are Bright Data and FalkorDB.

# Conferge — Claude Code multi-window rules

## Context
Patch the Conference hackathon, 2026-10-24. Demo: GitHub Universe, Oct 28–29, Fort Mason, San Francisco; New York -> SF Oct 27–30; founder seeking seed investors, agentic AI founders and Copilot PMs. Sponsor technologies: **Bright Data + FalkorDB only**.

## Non-negotiable execution rules

1. Every agent starts from latest `main`, makes a separate branch `wNN-<slug>`, and modifies **only** its assigned domain directory, its `tests/<slug>/`, its `fixtures/<slug>.json` and its `scripts/probes/<slug>.py` / `probes/<slug>.md`. Docs/prompts it owns are fine. See `docs/WORKSTREAMS.md`.
2. **Window 0 alone** owns `conferge/core/`, `pyproject.toml`, `.github/`, `.env.example`, `docker-compose.yml`, `Makefile`, `CLAUDE.md`, `AGENTS.md`, `DECISIONS.md`, and shared docs. Never opportunistically edit them from a feature branch.
3. Contracts are in `conferge/core/schemas.py` and `conferge/core/contracts.py`. Implement `async discover(DiscoveryQuery) -> DiscoveryResult` and `async fetch_details(SourceRef) -> SourceRecord` in source windows. Agents implement `async run(AgentContext) -> AgentResult`.
4. FalkorDB writes **only** through `conferge/core/store.py::GraphStore` (MERGE methods). Do not write direct Cypher MERGE anywhere else.
5. Each connector has a probe script; use `make probe-<slug>`; report evidence, completeness and whether each record is live/cached/fixture. **No fake data silently standing in for failed collection.**
6. Never invent prices, schedule times, guest lists, people attendance, venues or relations. Public speaker ≠ confirmed side-event attendee. Preserve source URL and collected-at timestamp. Store timestamps timezone-aware; money decimals or string as documented.
7. Never commit `.env`, tokens, cookies, private attendee info or giant scraped bodies. Handle provider errors visibly with `status=degraded/failed`; fallback fixtures only when explicitly requested.
8. Run `make check`; small commits; open PR against `main`; merge after CI green and a review of owned paths; never force-push or overwrite someone else's worktree.
9. If a shared contract cannot express real payloads, open a small proposal to window 0. Do not modify schemas in the feature PR. Develop with local adapters around existing contracts meanwhile.
10. Work autonomously. If a provider key is missing, finish fixtures + mocks and accurately report unverified live behavior; do not stop the whole stream.

## Window map
See [docs/WORKSTREAMS.md](docs/WORKSTREAMS.md). Window 15 performs end-to-end integration after core paths merge, but integration checks start as soon as the first PR merges.
