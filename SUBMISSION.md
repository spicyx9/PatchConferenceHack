# Conferge

**Plan a conference trip in minutes and maximize the professional opportunities you get out of it.**

This file is the single source of truth for the submission. Every number below was read from the running app
(`make demo`, git `7a4dbef`, graph loaded fresh) on 2026-10-24 at 20:12 UTC, through its API, except where the line
says otherwise; the graph and test rows were read again on `e6c08e4` at 20:45 UTC. `docs/submission/PITCH.md` (stage script) and `slides.html` quote these numbers; change them here first.

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

- **Bright Data collects** what a plain request cannot reach: Booking and Airbnb stays through datasets, the Google Flights page through Web Unlocker, LinkedIn and Crunchbase profiles through datasets (their URLs found with the SERP API), venues through the Google Maps dataset. The Google Flights dataset, the Google Hotels dataset and SERP event discovery are implemented, no record received yet.
- **Bright Data products used** (records received): SERP API, Web Unlocker, Datasets (Booking, Airbnb, LinkedIn, Crunchbase, Google Maps).
- **FalkorDB stores the relationships**: goal, topic, event, person, company, venue; the "why this person" answer is a real path query, and the user's meetings live in the same graph.
- **Agents never fetch the web at query time**: all reasoning runs on the stored, deduplicated, provenance-tagged graph.

## Real numbers

| Measure | Value (measured 2026-10-24 14:13 PDT) | Read from |
|---|---|---|
| FalkorDB graph | 684 nodes, 2,214 edges: Person 215, Event 194, Company 141, Venue 58, Topic 54, Opportunity 10, Lodging 6, Goal 3, Conference 1, FlightOffer 1, User 1 | `count()` queries on `conferge_demo` after `make predemo` (`GET /api/v1/graph` serves a capped sample: 332 nodes, 400 edges) |
| Events in the demo | 194: RainFocus official catalog 161, Luma 12, Eventbrite 8, conferenceparties/github26 7, Partiful 6 (partial: Partiful not exhausted, `page_cap`) | `GET /api/v1/events`, `GET /api/v1/pipeline` |
| Stays | 21 Bright Data dataset records (Booking 15, Airbnb 6), 6 shown; Google Hotels dataset 0 (`no_peers`) | `GET /api/v1/pipeline`, `GET /api/v1/stays` (`cached`) |
| Flights | 34 Google Flights itineraries from 1 Bright Data Web Unlocker request, 1 shown | `GET /api/v1/pipeline`, `GET /api/v1/flights` (`cached`) |
| Bright Data requests and records | 38 requests, 79 records. Datasets 10 / 38 (Booking 1 / 15, Airbnb 1 / 6, Google Hotels 1 / 0, LinkedIn 6 / 15, Crunchbase 1 / 2); Web Unlocker 1 / 34 (Google Flights); SERP 27 / 7 (LinkedIn URL search 17 / 5, Crunchbase URL search 10 / 2). No USD cost shown: no captured Bright Data response carried one. 0 requests made by the running demo (all from cache); Google Maps not merged | `GET /api/v1/brightdata`, `GET /api/v1/cost` |
| LinkedIn | 10 of the 50 people cards carry a Bright Data LinkedIn profile (9 in the first 10); 15 `Person` nodes with `provider brightdata:linkedin` in the graph, 6 of their URLs found by SERP | `GET /api/v1/people?limit=50`, FalkorDB |
| Crunchbase | funding on 27 of the 50 people cards, from 2 companies (GitHub, Swamp Club); read from the cache by the API, not written to the graph | `GET /api/v1/people?limit=50` |
| People and plan | 50 people ranked from FalkorDB traversals; top 3 Ryan Hecht 56, Camila Maia 47, Nick Liffen 40; 32 items on the agenda | `GET /api/v1/people`, `GET /api/v1/plan` |
| Reachability (block matrix run 2026-10-24 19:01 UTC, 21 sites) | 10 without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data; 18 projected once KYC is approved (Kayak, Hotels.com, Expedia, Marriott) | `GET /api/v1/pipeline` `reachability` |
| Tests | `make check`: 1,355 passed, 27 skipped (main `b12c425`) | local run |
| Live collection totals (probes, not the demo snapshot) | Luma 1,092 raw rows (194 in Oct 27-30); Partiful Explore 85 unique events (11 in the window, `page_cap`, not exhaustive); RainFocus 210 records (156 sessions, 54 exhibitors) | `probes/luma.md`, `probes/partiful.md`, `probes/official.md` |

## What is real, what is fixture, what is projected

- **Real, collected through Bright Data**: the stays, flight itineraries, LinkedIn profiles and Crunchbase rows above, served from the cache of those runs (`data_source: cached`) with their collection time; nothing is fetched at query time.
- **Fixture**: the events and people are a snapshot of the public collection of 2026-10-24 (RainFocus, Luma, Partiful, Eventbrite, conferenceparties), labelled `fixture` in every response and in the UI badge, so the demo runs offline on stage. The traveller (New York, October 27 to 30, budget $2,500) is the demo persona from `fixtures/api.json`, labelled as such in the UI.
- **Implemented, no record received yet**: Google Flights dataset `gd_mhng7wen1rw0a3gvpf` (3 snapshots still `running` after 396 s on 2026-10-24), Google Hotels dataset `gd_mg3gjfmg12tc2n5d4d` (0 records, provider `no_peers` at 18:12 UTC), SERP discovery, Facebook Events. Their record mapping has never met a real row; the demo keeps `--travel cached`.
- **Simulated**: the sold-out change; every later response carries a warning until Reset.
- **Projected, not measured**: the reachability once the account KYC is approved (see the table); Kayak, Hotels.com, Expedia and Marriott are refused by Web Unlocker until then.
- **Never invented**: no price, attendance or guest list. A public speaker is never presented as a confirmed side-event attendee, a missing price stays `unknown` with its `price_status`, and a follow-up draft never claims where you met someone unless you marked that event attended.
- **No LLM in the loop**: goal parsing is rule based, ranking is graph traversals, drafts are templates filled with graph facts.

## How to run

```bash
make up        # FalkorDB 6.0.3 in Docker, Browser on :3000
make install   # Python deps with uv
make demo      # API + UI on http://127.0.0.1:8000, data loaded into FalkorDB
```

Stage material: `docs/submission/PITCH.md` (3-minute script), `docs/submission/CHECKLIST.md` (the 10 minutes before), `docs/submission/slides.html`, backup video `docs/submission/demo-backup.mp4` (35 s, 1280 x 720, recorded on the current interface with `docs/submission/record_demo.py`).

## Team

- Axel Carron
- Ilan Sainte Agathe

Repository: https://github.com/spicyx9/PatchConferenceHack
