# Status (2026-10-24)

1. Conferge: goal-first planner for GitHub Universe 2026 (Fort Mason, SF): who to meet, why, where and when.
2. Rankings of people and events come from FalkorDB 6.0.3 traversals; without FalkorDB the API is labelled `degraded_no_graph`.
3. Demo (`make demo`): goal, who to meet and why (graph path), plan and map, anti-FOMO, live replanning, meeting memory, follow-up drafts and ROI panel.
4. Memory (MET, SKIPPED) lives in FalkorDB with one id per occurrence, survives restarts and is cleared by `POST /reset`.
5. Interface: Data pipeline panel and Reachability in "Sources and how it works", provenance badges on stays and travel legs, LinkedIn company (and SERP headline when found) on people cards.
6. Bright Data products used: SERP API, Web Unlocker, Datasets (Booking, Airbnb, LinkedIn, Crunchbase).

## Measured on dfca2bf at 15:33 PDT

Every value below was read by command on this checkout after `make predemo` (fresh demo on a reset graph).

| Measure | Value | Read from |
|---|---|---|
| Events in the demo fixture | 194: 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed `confirmed_side_event`) + 33 external side events (Luma 12, Eventbrite 8, conferenceparties 7, Partiful 6) | `GET /api/v1/events` (`conference_relation`, first evidence provider) |
| FalkorDB `conferge_demo` | 690 nodes / 2 184 edges loaded from the catalogue; 691 / 2 213 once the plan is written (1 User node, 25 PLANS edges, 4 SKIPS edges for the anti-FOMO skips); the graph then grows with every meeting you record | `GRAPH.RO_QUERY conferge_demo "MATCH (n) RETURN count(n)"` and `"MATCH ()-[r]->() RETURN count(r)"` |
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
| `make check` | 1476 passed, 26 skipped | local run |
| HEAD | `dfca2bf` | `git rev-parse --short HEAD`, `/health` `git_sha` |
