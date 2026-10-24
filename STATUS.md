# Status (2026-10-24)

1. Conferge: goal-first planner for GitHub Universe 2026 (Fort Mason, SF): who to meet, why, where and when.
2. Rankings of people and events come from FalkorDB 6.0.3 traversals; without FalkorDB the API is labelled `degraded_no_graph`. Demo graph: 703 nodes, 2,201 edges (read 2026-10-24 20:12 UTC).
3. Demo dataset (`GET /api/v1/events`, fixture snapshot of 2026-10-24): 194 events, 161 official sessions (RainFocus), 12 Luma, 6 Partiful, 8 Eventbrite, 7 conferenceparties (github26 page only); probe reports in `probes/`. Live probe totals are larger and are not what the demo shows: Partiful Explore returned 85 unique events (11 in Oct 27-30, `page_cap`, not exhaustive), Luma 1092 raw rows (194 kept in the window), conferenceparties/github26 7 (`probes/*.md`).
4. Bright Data travel runs: 21 stays through datasets (15 Booking, 6 Airbnb) and 34 Google Flights itineraries through Web Unlocker, served from cache; fast-flights and pyairbnb as fallbacks.
5. Bright Data LinkedIn: 15 profiles in the graph (9 through the dataset on catalog URLs, 6 found by SERP then the dataset), 10 visible in the top 50 people cards; the dataset returns no headline (the 6 headlines shown come from the SERP title); presence is never inferred from LinkedIn.
6. Reachability (`data/block_matrix.json`): 10 of 21 sites without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data (Web Unlocker or dataset); 18 projected once KYC is approved.
7. Demo (`make demo`): goal, who to meet and why (graph path), plan and map, anti-FOMO, live replanning, meeting memory, follow-up drafts and ROI panel.
8. Memory (MET, SKIPPED) lives in FalkorDB with one id per occurrence, survives restarts and is cleared by `POST /reset`.
9. Tests: `make check` 1,175 passed, 25 skipped; `make e2e` 16 passed against the real API and FalkorDB.
10. Interface: Data pipeline panel and Reachability in "Sources and how it works", provenance badges on stays and travel legs, LinkedIn company (and SERP headline when found) on people cards.
11. Bright Data products used: SERP API, Web Unlocker, Datasets (Booking, Airbnb, LinkedIn, Crunchbase).

Submission numbers and their API sources: [SUBMISSION.md](SUBMISSION.md).
