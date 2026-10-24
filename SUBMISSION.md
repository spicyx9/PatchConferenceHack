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

Measured on dfca2bf at 15:33 PDT, same values as `STATUS.md`.

Every value below was read by command on this checkout after `make predemo` (fresh demo on a reset graph).

| Measure | Value | Read from |
|---|---|---|
| Events in the demo fixture | 194: 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed `confirmed_side_event`) + 33 external side events (Luma 12, Eventbrite 8, conferenceparties 7, Partiful 6) | `GET /api/v1/events` (`conference_relation`, first evidence provider) |
| FalkorDB `conferge_demo` | 690 nodes, 2184 edges | `GRAPH.RO_QUERY conferge_demo "MATCH (n) RETURN count(n)"` and `"MATCH ()-[r]->() RETURN count(r)"` |
| Agenda items (`GET /api/v1/plan`) | 25 | `GET /api/v1/plan` |
| Sold-out event (labelled simulation) | Agentic engineering past the pilot: An enterprise playbook | `POST /api/v1/simulate-change` (scenario `w15-simulated-sold-out`), then `POST /api/v1/reset` |
| Replacement event | How one open source project turned funding into security at scale | same call, `diff.added` |
| Top 3 before "I met Ryan Hecht" | Ryan Hecht 56, Camila Maia 47, Nick Liffen 40 | `GET /api/v1/people` |
| Top 3 after "I met Ryan Hecht" | Camila Maia 47, Nick Liffen 40, Annamalai Chockalingam 38.5 | `POST /api/v1/met`, `GET /api/v1/people`, then `POST /api/v1/reset` |
| LinkedIn | 13 cards with a Bright Data LinkedIn profile in the top 50 loaded by the page; 17 profiles in `data/cache/linkedin_public.json` | `GET /api/v1/people?limit=100` |
| Stays shown | 12: Airbnb 6, Booking 6 (21 collected through Bright Data datasets) | `GET /api/v1/stays`, `GET /api/v1/pipeline` |
| Flights | 34 shown; 34 itineraries collected through Bright Data Web Unlocker | `GET /api/v1/flights`, `GET /api/v1/pipeline` |
| Bright Data requests / records (cache) | 39 / 81: Airbnb (dataset) 1 / 6; Booking (dataset) 1 / 15; Crunchbase (dataset) 1 / 2; Google Hotels (dataset) 1 / 0; LinkedIn (dataset) 7 / 17; Google Flights (unlocker) 1 / 34; Crunchbase URL search (serp) 10 / 2; LinkedIn URL search (serp) 17 / 5; Google Maps not in this counter | `GET /api/v1/brightdata` |
| Crunchbase | 2/10 companies normalized | `probes/crunchbase.md` |
| Google Maps | 4/9 venues found (snapshot `sd_mvmvwe7c2bqi2xcka6`) | `data/cache/venues.json` |
| Reachability (21 sites, block matrix) | 10 without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data; 18 projected once KYC is approved | `GET /api/v1/pipeline` `reachability` |
| `make check` | 1470 passed, 26 skipped | local run |
| HEAD | `dfca2bf` | `git rev-parse --short HEAD`, `/health` `git_sha` |

## What is real, what is fixture, what is projected

- **Real, collected through Bright Data**: the stays, flight itineraries, LinkedIn profiles and Crunchbase rows above, served from the cache of those runs (`data_source: cached`) with their collection time; nothing is fetched at query time.
- **Fixture**: the events and people are a snapshot of the public collection of 2026-10-24 (RainFocus, Luma, Partiful, Eventbrite, conferenceparties), labelled `fixture` in every response and in the UI badge, so the demo runs offline on stage. The traveller (New York, October 27 to 30, with a budget) is the demo persona from `fixtures/api.json`, labelled as such in the UI.
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
