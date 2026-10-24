# Conferge — Window 08 / FalkorDB Opportunity Graph

**Repo:** spicyx9/HTest. **Branch:** `w08-graph`. **Owner:** `conferge/graph/` plus matching `tests/graph/`, `scripts/probes/graph.py`, `fixtures/graph.json` and `probes/graph.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Build canonical node-edge mapping for Conference, Event, Person, Company, Goal, Venue and Opportunity using existing `core.store.GraphStore` write API exclusively. Implement read-only Cypher path queries and reusable explanations: goal→topic→event→speaker/company, or person→host→side event. Track source evidence, relation type and verification. Graph can ingest fixture model instances before real sources arrive.

## Deliverables

- Ingestion functions using `GraphStore.merge_node/merge_edge` and read-only named path queries.
- Unit tests with mocked `GraphQuery`; optional FalkorDB integration test behind opt-in.
- Probe: sample graph traversal with source reasons.

## Acceptance

- Every asserted attendance edge has explicit evidence.
- Do not invent a `GraphStore` write method or modify `core.store`.
- No direct MERGE Cypher outside the shared store module.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-graph` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
