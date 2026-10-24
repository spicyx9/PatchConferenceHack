# Status (2026-10-24)

1. Conferge: goal-first planner for GitHub Universe 2026 (Fort Mason, SF): who to meet, why, where and when.
2. Rankings of people and events come from FalkorDB 6.0.3 traversals; without FalkorDB the API is labelled `degraded_no_graph`. Demo graph: 697 nodes, 2,195 edges.
3. Sources (probe reports in `probes/`): 161 official sessions (RainFocus), 1,092 Luma events (194 kept after filters), 85 Partiful events.
4. Bright Data travel run: 21 stays and 34 Google Flights itineraries through Web Unlocker (`probes/brightdata-travel.md`); fast-flights and Airbnb as fallbacks.
5. Bright Data LinkedIn: 10 speaker profiles saved, 9 matched by name (identity_confidence 1.0 for 6, 0.7 for 3); presence is never inferred from LinkedIn.
6. Reachability (`data/block_matrix.json`): 10 of 21 sites without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data (Web Unlocker or dataset).
7. Demo (`make demo`): goal, who to meet and why (graph path), plan and map, anti-FOMO, live replanning, meeting memory, follow-up drafts and ROI panel.
8. Memory (MET, SKIPPED) lives in FalkorDB with one id per occurrence, survives restarts and is cleared by `POST /reset`.
9. Tests: `make check` 1,147 passed; `make e2e` 16 passed against the real API and FalkorDB.
10. Interface: Data pipeline panel and Reachability in "Sources and how it works", provenance badges on stays and travel legs, LinkedIn headline and company on people cards.
