# Parallel workstreams — strict ownership

Start with window **00** on `main`. Only after CI is green, fork **separate branches/worktrees** from that commit. Window 00 then serves as integration owner. Merge feature PRs after tests and ownership checks. Never edit the same files concurrently.

| Window | Branch | Owned files in addition to `tests/<slug>/`, `fixtures/<slug>.json`, `scripts/probes/<slug>.py`, `probes/<slug>.md` | Work |
|---|---|---|---|
| 00 | `main` | `conferge/core/`, `pyproject.toml`, `uv.lock`, `.github/`, `Makefile`, `docker-compose.yml`, `.env.example`, shared docs | Schemas, shared Bright Data client, graph writes, CI, coordination |
| 01 | `w01-luma-partiful` | `conferge/events/luma/`, `conferge/events/partiful/` | Pagination, raw events, completeness |
| 02 | `w02-eventbrite-aggregators` | `conferge/events/eventbrite/`, `conferge/events/aggregators/` | Eventbrite windows, conference parties |
| 03 | `w03-official` | `conferge/events/official/` | GitHub Universe program, speakers, sponsors |
| 04 | `w04-discovery` | `conferge/events/discovery/` | Bright Data SERP, URL frontier, Facebook public events |
| 05 | `w05-lodging` | `conferge/lodging/` | Booking, Google Hotels, Airbnb, stay-price verification |
| 06 | `w06-flights` | `conferge/flights/` | Bright Data Flights, SerpApi/fast-flights, route dedup |
| 07 | `w07-people` | `conferge/people/` | Public speaker/organizer enrichment, networking; no private guest lists |
| 08 | `w08-graph` | `conferge/graph/` | Cypher schema/traversal/graph ingestion using `GraphStore` |
| 09 | `w09-planner` | `conferge/agents/planner/`, `conferge/agents/networking/` | Goal parsing and opportunity scoring |
| 10 | `w10-antifomo` | `conferge/agents/antifomo/`, `conferge/agents/replanner/` | Time constraints, trade-offs, replanning |
| 11 | `w11-travel` | `conferge/travel/` | Ground transport, route integration (optional hackathon) |
| 12 | `w12-api` | `conferge/api/`, `static/` | FastAPI and the one-page demo UI |
| 13 | `w13-demo` | `conferge/demo/`, `scripts/gen_fixtures.py`, `demo/` | Deterministic demo and 3-minute script |
| 15 | `w15-integration` | `conferge/integration/`, `tests/integration/` | E2E verification and final backup |
| 16 | `w16-followup` | `conferge/agents/followup/` | Follow-up draft after a MET memory, proposed for validation, never sent |

**Special ownership rule for window 13:** fixture files `fixtures/<slug>.json` belong to the corresponding source window, not to window 13. Window 13 builds its own fixture `fixtures/demo.json`, may *read* other windows' fixtures, and must not edit them.

**Work phases**
1. Window 00 commits to `main`; verify CI.
2. Parallel: 01/02/03/04/05/06/08/12/13 (fakes permitted only when flagged). 07/09/10 can begin on fixtures once their interface dependencies are available.
3. 15 integrates continuously on a separate branch, but final E2E only after merge of core demo components.

For local multi-agent development, use independent `git worktree` directories and one Claude/Codex session per worktree. Branches can be created only after the initial common contract commit.
