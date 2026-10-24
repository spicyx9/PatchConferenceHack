# Status (2026-10-24)

1. Conferge: goal-first planner for GitHub Universe 2026 (Fort Mason, SF): who to meet, why, where and when.
2. Rankings of people and events come from FalkorDB 6.0.3 traversals; without FalkorDB the API is labelled `degraded_no_graph`.
3. Demo (`make demo`): goal, who to meet and why (graph path), plan and map, anti-FOMO, live replanning, meeting memory, follow-up drafts and ROI panel.
4. Memory (MET, SKIPPED) lives in FalkorDB with one id per occurrence, survives restarts and is cleared by `POST /reset`.
5. Interface: Data pipeline panel and Reachability in "Sources and how it works", provenance badges on stays and travel legs, LinkedIn company (and SERP headline when found) on people cards.
6. Bright Data products used: SERP API, Web Unlocker, Datasets (Booking, Airbnb, LinkedIn, Crunchbase).

## Numbers

| Measure | Value (measured 2026-10-24 14:13 PDT) | Read from |
|---|---|---|
| FalkorDB graph | 684 nodes, 2,214 edges: Person 215, Event 194, Company 141, Venue 58, Topic 54, Opportunity 10, Lodging 6, Goal 3, Conference 1, FlightOffer 1, User 1 | `count()` queries on `conferge_demo` after `make predemo` (`GET /api/v1/graph` serves a capped sample: 332 nodes, 400 edges) |
| Events in the demo | 194: RainFocus official catalog 161, Luma 12, Eventbrite 8, conferenceparties/github26 7, Partiful 6 (partial: Partiful not exhausted, `page_cap`) | `GET /api/v1/events`, `GET /api/v1/pipeline` |
| Stays | 21 Bright Data dataset records (Booking 15, Airbnb 6), 6 shown; Google Hotels dataset 0 (`no_peers`) | `GET /api/v1/pipeline`, `GET /api/v1/stays` (`cached`) |
| Flights | 34 Google Flights itineraries from 1 Bright Data Web Unlocker request, 1 shown | `GET /api/v1/pipeline`, `GET /api/v1/flights` (`cached`) |
| Bright Data requests and records | 38 requests, 79 records. Datasets 10 / 38 (Booking 1 / 15, Airbnb 1 / 6, Google Hotels 1 / 0, LinkedIn 6 / 15, Crunchbase 1 / 2); Web Unlocker 1 / 34 (Google Flights); SERP 27 / 7 (LinkedIn URL search 17 / 5, Crunchbase URL search 10 / 2). Cost $0.0570 on dataset records only, list price estimate, not billed. 0 requests made by the running demo (all from cache); Google Maps not merged | `GET /api/v1/brightdata`, `GET /api/v1/cost` |
| LinkedIn | 10 of the 50 people cards carry a Bright Data LinkedIn profile (9 in the first 10); 15 `Person` nodes with `provider brightdata:linkedin` in the graph, 6 of their URLs found by SERP | `GET /api/v1/people?limit=50`, FalkorDB |
| Crunchbase | funding on 27 of the 50 people cards, from 2 companies (GitHub, Swamp Club); read from the cache by the API, not written to the graph | `GET /api/v1/people?limit=50` |
| People and plan | 50 people ranked from FalkorDB traversals; top 3 Ryan Hecht 56, Camila Maia 47, Nick Liffen 40; 32 items on the agenda | `GET /api/v1/people`, `GET /api/v1/plan` |
| Reachability (block matrix run 2026-10-24 19:01 UTC, 21 sites) | 10 without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data; 18 projected once KYC is approved (Kayak, Hotels.com, Expedia, Marriott) | `GET /api/v1/pipeline` `reachability` |
| Tests | `make check`: 1,355 passed, 27 skipped (main `b12c425`) | local run |
| Live collection totals (probes, not the demo snapshot) | Luma 1,092 raw rows (194 in Oct 27-30); Partiful Explore 85 unique events (11 in the window, `page_cap`, not exhaustive); RainFocus 210 records (156 sessions, 54 exhibitors) | `probes/luma.md`, `probes/partiful.md`, `probes/official.md` |

Same table in [SUBMISSION.md](SUBMISSION.md).
