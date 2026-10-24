# Conferge

**Don't just attend conferences. Be in the right place, with the right people, at the right time.**

![Conferge demo overview](docs/demo/screens/0-overview.png)

## Problem

A big conference is two days, hundreds of sessions, dozens of side events and thousands of people.
Agendas are organised by time slot, not by what you came for, so the people who matter to you stay invisible.
Most attendees go home with a few business cards and the feeling they were in the wrong room.

## What it does

1. **Goal first**: turns one sentence ("meet seed investors, AI agent founders, Copilot PMs") into weighted goals.
2. **Event discovery**: collects official sessions and side events (Luma, Partiful, Eventbrite, party aggregators) and links them to the conference.
3. **Who to meet, and why**: ranks people and shows the explainable FalkorDB path from your goal to each person, with sources.
4. **Reverse planning**: builds a day-by-day plan for the days you are in town, with a map of the venues.
5. **Anti-FOMO**: tells you which events to skip (time conflict, travel too long, low score) and what you gain by skipping them.
6. **Live replanning**: when an event sells out, the plan is recomputed and the diff says what was removed, what replaces it and why.
7. **Memory**: "I met this person" is written to the graph and the ranking changes immediately.

## Architecture

```
  Public sources                      Bright Data (when a key is set)
  RainFocus catalog, Luma,            SERP discovery, Web Unlocker,
  Partiful, Eventbrite,               datasets: Google Flights, Booking,
  conference-party aggregators        LinkedIn, Facebook Events
            |                                   |
            +-----------------+-----------------+
                              v
              Connectors (conferge/events, lodging, flights, people)
              every record: source_url, collected_at, source_mode
                              |
                              v
              Assembly + dedup + conference linking (conferge/integration)
                              |
                              v
              FalkorDB graph via GraphStore MERGE only (conferge/graph)
              Conference, Event, Person, Company, Venue, Topic, Goal,
              Opportunity; SPEAKS_AT, HOSTS, WORKS_AT, PART_OF, ABOUT ...
                              |
                              v
              Agents (conferge/agents): planner + networking,
              anti-FOMO optimizer, minimal-change replanner
                              |
                              v
              FastAPI (conferge/api)  ->  one-page UI (static/)
```

- **Bright Data** is the acquisition layer for everything a plain HTTP request cannot reach: long-tail event discovery through SERP, flights and hotels through Web Scraper datasets, LinkedIn profiles for people matching, and unblocking dynamic pages.
- **FalkorDB** is the opportunity graph: every relation carries its evidence, the "why this person" explanation is a real graph path query, and the user's memory (who they met) lives in the same graph.

## Demo case: GitHub Universe 2026

Fort Mason Center, San Francisco, October 28 and 29. Fictional traveller from New York, in town October 27 to 30.

| Measure | Value |
|---|---|
| Live collection, 2026-10-24, public endpoints, no API key | 161 official sessions, 183 speakers, 122 companies, 194 Luma events, 19 Eventbrite events, 11 Partiful events, 7 aggregator parties |
| Demo dataset (snapshot of that collection, deduplicated) | 207 events, 183 people |
| FalkorDB graph | 697 nodes, 2,195 edges (49 HOSTS edges from event organizers), loaded in about 1 s |
| API response times on the demo graph | goal 61 ms, events 8 ms, people 2 ms, graph path 11 ms, plan 8 ms, simulate-change 26 ms, meeting 17 ms, anti-FOMO agent about 1.1 s |
| Tests | 926 passing (`make check`) |

| 1. Goal | 2. Who to meet, and why |
|---|---|
| ![Goal](docs/demo/screens/1-goal.png) | ![Opportunities](docs/demo/screens/2-opps.png) |
| **3. Plan and map** | **4. Anti-FOMO** |
| ![Plan](docs/demo/screens/3-plan.png) | ![Anti-FOMO](docs/demo/screens/4-antifomo.png) |
| **5. Live replanning** | **6. Meeting recorded** |
| ![Simulated change](docs/demo/screens/5-change.png) | ![Meeting](docs/demo/screens/6-met.png) |

## Quickstart

```bash
make up        # FalkorDB in Docker (set FALKORDB_PORT in .env if 6379 is taken)
make install   # Python deps with uv
make demo      # API + UI on http://127.0.0.1:8000, demo data loaded into FalkorDB
```

`uv run python scripts/run_demo.py --mode live` collects from the public sources instead of the snapshot. Copy `.env.example` to `.env` and add `BRIGHTDATA_API_KEY` to enable the Bright Data connectors.

## Tracks

- **FalkorDB**: the graph of record, written only through `GraphStore` MERGE methods, queried for explainable goal to person paths, conflicts, replanning impact and meeting memory.
- **Bright Data**: SERP discovery, Web Unlocker, Google Flights, Booking and LinkedIn datasets are implemented behind one client (`conferge/core/brightdata.py`); without a key they report `missing_credentials` instead of inventing data.
- **Qodo**: planned as the PR review assistant for the 12 workstream PRs; no Qodo review has run on this repository yet.

## Honesty: live vs fixture today

- **Live and working without keys**: official GitHub Universe catalog (RainFocus), Luma, Partiful, Eventbrite, conference-party aggregators, ground travel (BART fares, OSRM routes), and the FalkorDB graph itself.
- **Implemented, waiting for a Bright Data key**: SERP discovery, flights, hotels, LinkedIn enrichment. Today they return `missing_credentials` and the demo shows labelled fixtures for flights and stays.
- **The demo runs on a snapshot** of the live public collection (captured 2026-10-24), labelled `fixture` in every API response and in the UI badge, so it works offline on stage.
- **Simulations are labelled**: the sold-out change in the demo is a simulation, never presented as an observed update.
- **No LLM in the loop yet**: goal parsing and ranking are deterministic; no price, attendance or guest list is ever invented.

## Team

Axel Carron, Ilan Sainte Agathe.
