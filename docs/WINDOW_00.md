# Window 00 — Conferge foundation (sequential, before parallel work)

The repo is for Conferge, a Python 3.11+ hackathon prototype for **Bright Data** + **FalkorDB**. Demo: GitHub Universe 2026, Fort Mason, October 28–29, user arriving from NYC October 27 and leaving October 30. Goals: seed investors, AI agent founders, Copilot PMs.

## Non-negotiable foundation

1. Set up `pyproject.toml` with uv, pytest, ruff, FastAPI, httpx, Pydantic 2 and FalkorDB; `docker-compose.yml`; `Makefile`; `.env.example`; CI on PR and main (ruff + pytest). Never put credentials in Git.
2. `conferge/core/schemas.py`: Event, Conference, Venue, SourceRecord, SourceRef, DiscoveryQuery, DiscoveryResult, RunReport (explicit termination reason), Person, Company, Lodging (exact-stay price status), FlightOffer (amount as decimal **string** and timezone-aware collected_at), Goal, Opportunity, AgentContext, AgentResult, plus generic DataEnvelope. Source provenance must always distinguish `live`, `cached`, and `fixture`.
3. `conferge/core/contracts.py`: async `Source.discover(query) -> DiscoveryResult`, async `Source.fetch_details(ref) -> SourceRecord`, async `Agent.run(ctx) -> AgentResult`.
4. `conferge/core/brightdata.py`: a single REST client supporting Web Scraper API sync and async trigger/progress/snapshot, SERP and Unlocker; bounded retries, sanitized logs; fixtures only by explicit opt-in and labelled.
5. `conferge/core/store.py`: only graph write gateway using typed, parameterized FalkorDB MERGE node/edge operations.
6. `fixtures/README.md`, `CLAUDE.md`, `AGENTS.md`, `DECISIONS.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, `scripts/create_worktrees.sh` and `scripts/run_probe.py`.
7. Add offline contract tests: malformed dates, partially paginated collect, unverified lodging, invalid flight prices, fixture fallback, Bright Data 202 snapshots and parameterized graph writes.

## Collaboration after step 00

Assign one branch/worktree and directory per independent agent. No agent may alter `core/` or CI while editing a feature. Window 00 alone reviews core changes and integrates PRs after green CI. Other windows write their own `tests/<slug>/`, `fixtures/<slug>.json` and `scripts/probes/<slug>.py`.

Initial parallel windows: w01 luma-partiful; w02 eventbrite-aggregators; w03 official program; w04 discovery/serp; w05 lodging; w06 flights; w08 graph; w12 api/demo UI; w13 fixtures/demo. More advanced w07 networking, w09 planner, w10 antifomo follow using fixtures. w11 ground travel is optional, w15 final integration.

**Definition of done:** tests green, core contracts frozen, no invented prices or attendees, labels for fixtures, explicit source/collection timestamps, README setup instructions, and one stable commit in main before any other window begins.
