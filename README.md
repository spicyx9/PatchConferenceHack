# Conferge

**Plan a conference trip in minutes and maximize the professional opportunities you get out of it.**

![Conferge demo overview](docs/demo/screens/0-overview.png)

## Problem

A big conference is two days, hundreds of sessions, dozens of side events and thousands of people.
Agendas are organised by time slot, not by what you came for, so the people who matter to you stay invisible.
Most attendees go home with a few business cards and the feeling they were in the wrong room.

## What it does

1. **Opportunity Graph**: one sentence ("meet seed investors, AI agent founders, Copilot PMs") becomes weighted goals, and official sessions plus side events (Luma, Partiful, Eventbrite, conferenceparties) are linked in FalkorDB to people, companies and topics.
2. **Reverse Planning**: starts from the goals to build a day-by-day plan for the days you are in town, with a map of the venues.
3. **Smart Networking**: who to meet and why, ranked against your goals with the explainable FalkorDB path and its sources; "I met this person" is written to the graph and the ranking changes immediately.
4. **Anti-FOMO**: tells you which events to skip (time conflict, travel too long, low score, outside hours) and what you gain by skipping them.
5. **Live Replanning**: when an event sells out, the plan is recomputed and the diff says what was removed, what replaces it and why.
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

## Graph model and Cypher queries

Rankings are computed from FalkorDB traversals; without FalkorDB the API runs in an explicitly degraded mode.

FalkorDB `6.0.3` (pinned in `docker-compose.yml`), client `falkordb==1.8.0`. Labels and relationship types come from an allowlist in `conferge/core/store.py`; every value is a `$parameter`.

**Nodes**: `Conference`, `Event {event_type, start_at, end_at, status}`, `Person {name, title, roles, participation}`, `Company`, `Venue {latitude, longitude}`, `Topic`, `Goal {user_id, priority}`, `Opportunity`, `Lodging`, `FlightOffer`, `Meeting {user_id, kind, at_ms, target_id, reason}`.

**Edges** (each carries `source`, `source_url`, `source_mode`, `confidence`, `observed_at`, `verification`):

```
(Event)-[:PART_OF {relation, relation_score}]->(Conference)
(Event|Person|Goal|Conference)-[:ABOUT]->(Topic)
(Event|Conference)-[:LOCATED_AT]->(Venue)
(Person)-[:SPEAKS_AT]->(Event)
(Person|Company)-[:HOSTS]->(Event)
(Person)-[:WORKS_AT {role, title}]->(Company)
(Person)-[:ATTENDS_CONFIRMED]->(Event)          only with evidence
(Company)-[:EXHIBITS_AT {role}]->(Conference)
(Opportunity)-[:SERVES_GOAL]->(Goal)
(Opportunity)-[:INVOLVES]->(Person|Company|Event)
(Lodging)-[:NEAR {distance_m}]->(Venue)
(Meeting)-[:MET]->(Person)                      one Meeting node per occurrence
(Meeting)-[:INVOLVES]->(Person|Event)           ATTENDED, SKIPPED (with reason), CONTACTED
```

**The 6 main queries, as executed** (`conferge/core/store.py`, `conferge/graph/queries.py`):

```cypher
// 1. Ingestion: the only write path, MERGE on the stable id then SET (GraphStore)
MERGE (n:Person {id: $id}) SET n.name = $prop_0, n.source = $prop_1, ... RETURN n.id
MATCH (a:Person {id: $from_id}), (b:Event {id: $to_id})
MERGE (a)-[r:SPEAKS_AT]->(b) SET r.confidence = $prop_0, ... RETURN a.id, b.id

// 2. People for a goal (one of the bounded signatures; evidence grouped by root source, noisy-OR)
MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)<-[:ABOUT]-(:Event)
          <-[:SPEAKS_AT]-(person:Person) RETURN person.id, p LIMIT $cap

// 3. Why this person: explicit signatures tried in order (speaker, confirmed attendee,
//    host company, company topic, ...), never a generic shortestPath
MATCH p = (g:Goal {user_id: $user_id})-[:ABOUT]->(:Topic)<-[:ABOUT]-(:Event)
          <-[:SPEAKS_AT]-(person:Person {id: $person_id})
RETURN g.id, length(p), p ORDER BY length(p) LIMIT $cap

// 4. Anti-FOMO conflicts: overlapping events of the conference, with venues
MATCH (a:Event)-[:PART_OF]->(c:Conference {id: $conference_id})<-[:PART_OF]-(b:Event)
WHERE a.id < b.id AND a.start_ts < b.end_ts AND a.end_ts > b.start_ts
OPTIONAL MATCH (a)-[:LOCATED_AT]->(va:Venue) OPTIONAL MATCH (b)-[:LOCATED_AT]->(vb:Venue)
RETURN a.id, a.title, b.id, b.title, va.name, va.latitude, va.longitude, vb.name, vb.latitude, vb.longitude

// 5. Replanning: where else can I meet the people of a cancelled or sold-out event
MATCH p = (e:Event {id: $event_id})<-[:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]-(:Person)
          -[:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]->(alt:Event)
WHERE alt.id <> e.id AND (alt.status IS NULL OR NOT alt.status IN ['cancelled', 'sold_out'])
RETURN alt.id, alt.title, p LIMIT $cap

// 6. Full-text search (GET /api/v1/search?q=)
CALL db.idx.fulltext.queryNodes('Person', $q) YIELD node, score
RETURN node.id, node.name, node.title, score ORDER BY score DESC LIMIT $limit
```

Query 4 is shortened here (the code also checks that start and end timestamps are not null).

**Indexes** (created at store init, DDL syntax, all `OPERATIONAL` in `CALL db.indexes()`):

```cypher
CREATE INDEX FOR (n:<Label>) ON (n.id)      // one per label: Company, Conference, Event, FlightOffer,
                                            // Goal, Lodging, Meeting, Opportunity, Person, Session, Topic, Venue
CREATE FULLTEXT INDEX FOR (p:Person) ON (p.name, p.bio)
CREATE FULLTEXT INDEX FOR (e:Event) ON (e.title)
```

## Demo case: GitHub Universe 2026

Fort Mason Center, San Francisco, October 28 and 29. Fictional traveller from New York, in town October 27 to 30.

| Measure | Value |
|---|---|
| Live collection, 2026-10-24, public endpoints, no API key | 161 official sessions, 183 speakers, 122 companies, 194 Luma events, 19 Eventbrite events, 11 Partiful events, 7 aggregator parties |
| Demo dataset (snapshot of that collection, deduplicated) | 207 events, 183 people |
| FalkorDB graph | 697 nodes, 2,195 edges (49 HOSTS edges from event organizers), loaded in about 1 s |
| API response times on the demo graph | goal 61 ms, events 8 ms, people 2 ms, graph path 11 ms, plan 8 ms, simulate-change 26 ms, meeting 17 ms, anti-FOMO agent about 1.1 s |
| Tests | 957 passing (`make check`) |

| 1. Goal | 2. Who to meet, and why |
|---|---|
| ![Goal](docs/demo/screens/1-goal.png) | ![Opportunities](docs/demo/screens/2-opps.png) |
| **3. Plan and map** | **4. Anti-FOMO** |
| ![Plan](docs/demo/screens/3-plan.png) | ![Anti-FOMO](docs/demo/screens/4-antifomo.png) |
| **5. Live replanning** | **6. Meeting recorded** |
| ![Simulated change](docs/demo/screens/5-change.png) | ![Meeting](docs/demo/screens/6-met.png) |

## Quickstart

```bash
make up        # FalkorDB in Docker on 127.0.0.1:6379, Browser on :3000
make install   # Python deps with uv
make demo      # API + UI on http://127.0.0.1:8000, demo data loaded into FalkorDB
```

No `.env` is needed. Port: if 6379 is already taken by a local Redis, run `FALKORDB_PORT=6380 make up` and `FALKORDB_PORT=6380 make demo` (or put `FALKORDB_PORT=6380` in `.env`); `make demo` stops with "port 6379 is a plain Redis, set FALKORDB_PORT to the FalkorDB port" when it finds a Redis without the FalkorDB module.

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
