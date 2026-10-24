# Product and UX audit — 2026-10-24

## Scope

Read the repository contracts, component inventory, source integrations, agents,
FastAPI routes, demo assembly, existing frontend and API/E2E tests. This is a
product/interface audit, not a security certification or a fresh live-provider audit.

## What the product actually supports

| Layer             | Existing capability                                                        | Implication for the interface                                         |
| ----------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Core contracts    | Typed records, provenance, timestamps, unknown values                      | Never fabricate dates, prices, attendance or affiliation              |
| Event sources     | Official programs, Luma, Partiful, Eventbrite, aggregators, discovery      | Browse by day and format; keep original source links                  |
| People            | Public profiles, role matching, enrichment and identity evidence           | Show the reason, presence qualification and evidence                  |
| Flights and stays | Provider adapters, normalization, deduplication and verification status    | Unknown and unverified prices remain explicit                         |
| Integration       | Collects and assembles source slices into the API dataset                  | Distinguish default synthetic fixture from assembled captured sources |
| Graph             | Relationship ingestion, bounded explanation queries, ranking and memory    | Show a usable explanation alongside the visualization                 |
| Agents            | Planner, networking, Anti-FOMO and replanner implementations               | Expose useful decisions; do not imply unsupported autonomy            |
| API/UI            | Goal, program, people, map, graph, participation, meeting, simulation, ROI | Preserve the complete user journey across five destinations           |

Primary files: `conferge/core/schemas.py`, `conferge/integration/components.py`,
`conferge/integration/assemble.py`, `conferge/graph/queries.py`,
`conferge/graph/ranking.py`, `conferge/agents/**`, `conferge/api/app.py`,
`conferge/api/logic.py`, `scripts/run_demo.py`, `static/app.js`.

## Changes implemented for this interface

- Replaced the technical demo-first page with event discovery and contextual goal,
  program, people, travel and explanation views, all in English.
- Inspected Luma public HTML/CSS and computed layout; recorded the resulting design
  rules in `DESIGN.md`. Created a destination cover and preserved source-matched artwork.
- Added event search/format filters, program day selection and people search.
- Added explicit empty states, loading feedback, retry and native dialogs.
- Unified refresh after goal, meeting, participation, skip, proposal and simulation
  actions. Previously some overview or non-overview panels remained stale.
- Separated content provenance from Bright Data readiness/usage metadata. Previously
  the global indicator could display MIXED for an entirely fixture-backed dataset.
- Added permanently available textual graph and location alternatives. Explanation
  requests cannot overwrite a newer selection; missing sampled path nodes can be
  included in the visual explanation.
- Corrected fallback graph affiliation: only official or confirmed side events with
  a matching conference ID receive a PART_OF relationship.
- Associated public Luma artwork by exact event ID, only for fixture-backed records.
  Missing, invalid, non-public or non-Luma artwork is omitted without invented replacements.

## Important product limits retained and explained

- Goal parsing is deterministic and recognizes a limited set of target roles.
  A free-form conversational assistant is not implemented.
- The API program currently uses its own greedy schedule builder; it does not consume
  all optimized decisions produced by the planning agent.
- The BART/OSRM ground-travel subsystem is not wired to the displayed API map.
  Displayed lines are straight-line visit order, not navigable routes.
- Saving a travel proposal does not book it, and budget is indicative.
- Simulations modify the demo dataset; they are not source-observed updates.
- The demo state is shared per application process, without multi-user isolation.
- Resetting the API scenario does not erase persistent FalkorDB meeting memory.
- No account, checkout, travel-date editing or external RSVP flow was added.

## Validation environment

Local API started with assembled fixture sources and fixture travel:

```sh
FALKORDB_PORT=16379 uv run python scripts/run_demo.py \
  --mode fixture --travel fixture --no-graph --port 8042
```

Docker/FalkorDB is unavailable on this machine. The interface exposes fallback
ranking; live collection, external reservations and persistent graph behavior are
not verified by the browser run. Before/after captures use the same fixture sources,
conference, goal, viewport and initial scenario.

Baseline `make check`: 984 passed, 22 skipped, Ruff clean.
Final `make check`: 1029 passed, 22 skipped, Ruff clean. Browser journey: 14 checks passed, including all five views at 320/390/768/1440 px, actual API mutations, accessible dialogs, partial-network retry, unavailable visualization CDNs, and no uncaught JavaScript errors. Automated WCAG checks found no violations on the five views and event detail.

A repeatable browser probe is in `tests/api/browser_flow.cjs`. It requires Playwright,
a local fixture server and `BASE_URL`; optional `EVIDENCE_DIR` saves captures and
`AXE_PATH` enables the automated accessibility audit. It verifies the actual local API,
not mocked HTTP responses, for the main journey.
