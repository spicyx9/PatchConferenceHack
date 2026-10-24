# Conferge: engineering rules

## Context
Patch the Conference hackathon, 2026-10-24. Demo: GitHub Universe, Oct 28-29, Fort Mason, San Francisco; New York -> SF Oct 27-30; a founder looking for seed investors, agentic AI founders and Copilot PMs. Sponsor technologies: **Bright Data + FalkorDB**.

The package is `conferge/`; shared contracts live in `conferge/core/` (`schemas.py`, `contracts.py`). `docs/knowledge/` is a research library: where it conflicts with the code, the code wins.

## Rules

1. Keep changes small and scoped: one feature per branch, with its tests (`tests/<area>/`), fixture (`fixtures/<area>.json`) and probe (`scripts/probes/<area>.py`, `probes/<area>.md`).
2. Changes to `conferge/core/` (schemas, store, Bright Data client, settings) are deliberate, additive when possible, and covered by tests.
3. Contracts are in `conferge/core/schemas.py` and `conferge/core/contracts.py`. Sources implement `async discover(DiscoveryQuery) -> DiscoveryResult` and `async fetch_details(SourceRef) -> SourceRecord`. Agents implement `async run(AgentContext) -> AgentResult`.
4. FalkorDB writes go **only** through `conferge/core/store.py::GraphStore` (MERGE methods). No direct Cypher MERGE elsewhere; reads use parameterized, read-only queries.
5. Each connector has a probe script (`make probe-<name>`) that reports evidence, completeness and whether each record is live, cached or fixture. **No fake data silently standing in for a failed collection.**
6. Never invent prices, schedule times, guest lists, attendance, venues or relations. A public speaker is not a confirmed side-event attendee. Keep the source URL and collected-at timestamp; timestamps are timezone-aware; money is a decimal or a string as documented.
7. Never commit `.env`, tokens, cookies, private attendee information or large scraped bodies. Provider errors stay visible (`status=degraded/failed`); fixtures are used only when explicitly requested and are labelled `fixture`.
8. Run `make check` before pushing; small commits; pull requests against `main`, merged once CI is green.
9. If a provider key is missing, finish fixtures and mocks and report the live behaviour as unverified; do not block the rest of the work.
