# Conferge

**Plan a conference trip in minutes and maximize the professional opportunities you get out of it.**

This file is the single source of truth for the submission. Every number below was read from the running app
(`make demo`, git `7a4dbef`, graph loaded fresh) on 2026-10-24 at 20:12 UTC, through its API, except where the line
says otherwise. `docs/submission/PITCH.md` (stage script) and `slides.html` quote these numbers; change them here first.

## Problem

A big conference is two days, hundreds of sessions, dozens of side events and thousands of people.
Agendas are organised by time slot, not by what you came for, so the people who matter to you stay invisible.
Most attendees go home with a few business cards and the feeling they were in the wrong room.

## What it does

1. **Opportunity Graph**: one sentence ("founder of an AI dev tool, wants seed investors, AI-agent founders, Copilot PMs") becomes weighted goals; official sessions and side events (RainFocus catalog, Luma, Partiful, Eventbrite, conferenceparties) are linked in FalkorDB to people, companies and topics, each edge with its source.
2. **Reverse Planning**: from the goals to a day-by-day plan for the days you are in town, with a map of the venues (straight lines in visit order, labelled as such), stays and flights with their `price_status`, and the trip figures (meetings, qualified contacts, opportunities, known costs).
3. **Smart Networking**: who to meet and why, ranked by FalkorDB traversals, with the goal-to-person path and its sources; "I met this person" is written to the graph, the ranking changes at once, and a follow-up draft built from that path and your note is proposed for you to edit, never sent.
4. **Anti-FOMO**: which events to skip (time conflict, travel too long, low score, outside hours) and what you gain by skipping them.
5. **Live Replanning**: when an event sells out (simulated, and labelled so), the plan is recomputed and the diff says what was removed, what replaces it and why.

## Architecture

```
Bright Data (datasets, Web Unlocker, SERP)   public endpoints (RainFocus, Luma, Partiful, Eventbrite, conferenceparties)
                     \                                  /
                      collection runs, each with a RunReport and provenance (source URL, collected_at, source_mode)
                                         |
                      FalkorDB stores the relationships (GraphStore MERGE only)
                                         |
                      agents: planner, networking, anti-FOMO, replanner, follow-up
                                         |
                      FastAPI  ->  one-page UI (Data pipeline panel shows every run)
```

- **Bright Data collects** what a plain request cannot reach: hotels and Airbnb through datasets, Google Flights through Web Unlocker, LinkedIn profiles through a dataset, SERP for long-tail discovery.
- **FalkorDB stores the relationships**: goal, topic, event, person, company, venue; the "why this person" answer is a real path query, and the user's meetings live in the same graph.
- **Agents never fetch the web at query time**: all reasoning runs on the stored, deduplicated, provenance-tagged graph.

## Real numbers

| Measure | Value | Read from |
|---|---|---|
| Events in the demo dataset | 194: 161 official sessions (RainFocus), 12 Luma, 6 Partiful, 8 Eventbrite, 7 conferenceparties (github26) | `GET /api/v1/events` (`data_source: fixture`, snapshot of the 2026-10-24 public collection) |
| Collection runs | official 210 records, Luma 12, Partiful 6 (`page_cap`, shown as partial), Eventbrite 8, conferenceparties 7 | `GET /api/v1/pipeline` rows (RunReports) |
| Live probe totals (not the demo snapshot) | Partiful 85 unique (11 in window, `page_cap`), Luma 1092 raw (194 in window), conferenceparties/github26 7 | `probes/partiful.md`, `probes/luma.md`, `probes/eventbrite-aggregators.md` |
| People ranked for the goal | 50, computed from FalkorDB traversals | `GET /api/v1/people?limit=100` (`total`) |
| FalkorDB graph | 703 nodes, 2,201 edges | Cypher `count` on the graph the app serves (`/graph` returns a capped sample, not totals) |
| Stays | 21 records through Bright Data datasets (15 Booking `gd_m4bf7a917zfezv9d5`, 6 Airbnb `gd_ld7ll037kqy322v05`), collected 18:41 UTC, 6 shown | `GET /api/v1/pipeline`, `GET /api/v1/stays` (`data_source: cached`) |
| Flights | 34 Google Flights itineraries through Bright Data Web Unlocker (`web_unlocker1`), collected 18:18 UTC, 1 shown | `GET /api/v1/pipeline`, `GET /api/v1/flights` (`data_source: cached`) |
| LinkedIn cards | 9 people cards with a LinkedIn headline and company (10 targets, 9 matched, 1 missing; run `degraded`) | `GET /api/v1/people`, `GET /api/v1/pipeline` |
| Bright Data records | 64 (30 dataset, 34 Web Unlocker); cost about $0.096, an **estimate** (records x 1.5 / 1000) | `GET /api/v1/pipeline` `totals` |
| Reachability (block matrix, 21 sites from the code) | 10 of 21 without Bright Data, 12 of 21 with Web Unlocker alone, 14 of 21 with Web Unlocker or dataset | `GET /api/v1/pipeline` `reachability` (`data/block_matrix.json`, run 19:01 UTC, datasets read 19:16 UTC) |
| Tests | `make check`: 1,175 passed, 25 skipped; `make e2e`: 16 passed against the real API and FalkorDB | local run, 20:12 UTC |

## What is real, what is fixture, what is projected

- **Real, collected through Bright Data**: the 21 stays, the 34 flight itineraries and the 9 LinkedIn profiles above, served from the cache of those runs (`data_source: cached`) with their collection time; nothing is fetched at query time.
- **Fixture**: the events and people are a snapshot of the public collection of 2026-10-24 (RainFocus, Luma, Partiful, Eventbrite, conferenceparties), labelled `fixture` in every response and in the UI badge, so the demo runs offline on stage. The traveller (New York, October 27 to 30, budget $2,500) is the demo persona from `fixtures/api.json`, labelled as such in the UI.
- **Simulated**: the sold-out change; every later response carries a warning until Reset.
- **Projected, not measured**: **18 of 21** sites reachable with Bright Data once the account KYC is approved (Kayak, Hotels.com, Expedia, Marriott are refused by Web Unlocker until then).
- **Never invented**: no price, attendance or guest list. A public speaker is never presented as a confirmed side-event attendee, a missing price stays `unknown` with its `price_status`, and a follow-up draft never claims where you met someone unless you marked that event attended.
- **No LLM in the loop**: goal parsing is rule based, ranking is graph traversals, drafts are templates filled with graph facts.

## How to run

```bash
make up        # FalkorDB 6.0.3 in Docker, Browser on :3000
make install   # Python deps with uv
make demo      # API + UI on http://127.0.0.1:8000, data loaded into FalkorDB
```

Stage material: `docs/submission/PITCH.md` (3-minute script), `docs/submission/CHECKLIST.md` (the 10 minutes before), `docs/submission/slides.html`, backup video `docs/submission/demo-backup.mp4` (22 s, 1280 x 720).

## Team

- Axel Carron
- Ilan Sainte Agathe

Repository: https://github.com/spicyx9/PatchConferenceHack
