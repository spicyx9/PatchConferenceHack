# Judging guide: criterion → what to click

Every figure below comes from [STATUS.md](../STATUS.md) (measured on dfca2bf at 15:33 PDT); nothing here is new.
Start the demo with `make demo` and open http://127.0.0.1:8000.

Every recommendation carries its evidence path or an explicit fallback rationale: people matched on role alone, without a complete event path, stay ranked with that fallback reason shown.

## FalkorDB

| Criterion | What to click to prove it | What you see |
|---|---|---|
| The graph is at the core | **People** tab, any card → **View connection** | The ranking comes from FalkorDB traversals (STATUS: "Rankings of people and events come from FalkorDB 6.0.3 traversals"); the graph holds 690 nodes / 2 184 edges loaded from the catalogue; 691 / 2 213 once the plan is written (1 User node, 25 PLANS edges, 4 SKIPS edges for the anti-FOMO skips); the graph then grows with every meeting you record. |
| Answers are explainable (every recommendation carries its evidence path or an explicit fallback rationale) | **Connections** tab after **View connection** → **Show in FalkorDB Browser** | The goal → topic → event → person path, the literal Cypher, and each edge with its source. |
| Gaps are shown, not hidden | **Connections** tab → block **No path in our graph** | "No recorded path found, and that's the answer: the graph has no evidence linking this goal to anyone at the conference. It does not prove the person or event is absent." It lists goals without a recorded path, companies of the goals with no presence at an event, goal topics no event is about, each with its copyable Cypher and the graph's source mode ("No gaps for these goals" when there is none). |
| How the score is computed | Footer → **How scoring works** | The formula written from the constants of the code: path weights, weakest-edge confidence, noisy-OR corroboration across sources, goal priority, cap at 100, presence labels, marked uncalibrated. |
| A real problem | **Discover** tab | One goal sentence becomes an agenda of 25 items and the top 50 people ranked from FalkorDB traversals (top 3 Ryan Hecht 56, Camila Maia 47, Nick Liffen 40). |
| The demo runs | **Discover** → **Explore a sold-out scenario**, then **I met …** | The agenda is replanned with the reason and the path; the meeting is written to the graph (MET memory survives restarts, `POST /reset` clears it). |
| Provenance | **Sources and how it works** (header) → **Data pipeline** | One row per collection run from its RunReport: provider, Bright Data API, records, collected_at, outcome. Events: 194: 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed `confirmed_side_event`) and 33 external side events (Luma 12, Eventbrite 8, conferenceparties 7, Partiful 6). |
| A judge can run it | `make up`, `make install`, `make demo` | Same screens on the judge's machine; `make check`: 1476 passed, 26 skipped. |

## Bright Data

Every call below appears as a row of the **Data pipeline** panel (**Sources and how it works** → **Data pipeline**), with its API and record count. STATUS totals: 39 requests, 81 records; 0 requests made by the running demo (all from cache).

| Product | What to click | What you see (STATUS figures) |
|---|---|---|
| SERP API (`brd_json`) | Data pipeline rows for LinkedIn URL search and Crunchbase URL search | SERP 27 requests / 7 results: LinkedIn URL search 17 / 5, Crunchbase URL search 10 / 2. |
| Web Unlocker | **Travel** tab, flight leg, and its Data pipeline row | Google Flights: 1 request / 34 itineraries, 1 shown. |
| Datasets: LinkedIn | **People** tab, green `brightdata:linkedin` badge on a card (hover for dataset and snapshot) | LinkedIn 6 requests / 15 records; 13 of the top 50 people cards carry a Bright Data LinkedIn profile. |
| Datasets: Booking | **Travel** tab, stays, and the Data pipeline row | Booking 1 / 15 records. |
| Datasets: Airbnb | **Travel** tab, stays, and the Data pipeline row | Airbnb 1 / 6 records. |
| Datasets: Crunchbase | **People** cards with funding | Crunchbase 1 / 2 records; funding on 28 of the top 50 people cards, from 2 companies. |
| Datasets: Google Maps | Data pipeline row `venues` | 4/9 venues found (snapshot `sd_mvmvwe7c2bqi2xcka6`); not in the requests / records counter. |
| Reachability | Data pipeline → **Reachability: plain fetch vs Bright Data** | 21 sites: 10 without Bright Data, 12 with Web Unlocker alone, 14 with Bright Data; 18 projected once KYC is approved. |
