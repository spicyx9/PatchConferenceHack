# Demo script (2 minutes)

Every figure below was read on screen, in headless Chrome at 1440 px width; counts measured 2026-10-24 14:13 PDT on `main` `b12c425`.
Setup for that run: `FALKORDB_PORT=6380 make predemo` (fresh demo on a reset graph, all checks OK),
then **Reset session** clicked in the UI. If any figure on the
day differs, say the figure on screen, not the one written here.

## Before the demo: make predemo

Five minutes before going on stage, from `~/PatchConferenceHack`:

```
FALKORDB_PORT=6380 make predemo
```

It checks FalkorDB answers `GRAPH.LIST` (exit 2 with a clear message otherwise), stops any server
already listening on `DEMO_PORT` (default 8000), starts `make demo DEMO_ARGS=--reset-graph` in the
background (log: `logs/predemo-demo.log`), waits for `/health`, then prints one OK/FAIL line per check:

| Check | Expected |
|---|---|
| FalkorDB graph `conferge_demo` | at least 600 nodes and 2,000 edges |
| Bright Data stays in `/pipeline` | 21 (`PREDEMO_STAYS_BD`) |
| Bright Data flights, Web Unlocker, in `/pipeline` | 34 (`PREDEMO_FLIGHTS_BD`) |
| LinkedIn cards in `/people` | at least 9 (`PREDEMO_LINKEDIN_MIN`) |
| Top 3 people | Ryan Hecht, Camila Maia, Nick Liffen (`PREDEMO_TOP3`, comma separated) |
| `/antifomo`, called after plan, people and pipeline like the page | under 2 s |

Exit code 0 means every line is OK and the server stays up at the printed URL; any FAIL gives a
non-zero exit. Then continue with step 3 below (browser, Reset session).

## Before the demo

1. **Start the demo on a clean graph** from the demo checkout (`~/PatchConferenceHack`):
   `FALKORDB_PORT=6380 uv run python scripts/run_demo.py --reset-graph`
   (same as `make demo`, plus `--reset-graph`). Within a few seconds it prints a
   `linkedin (cached)` line and `stays: cached` / `flights: cached`. No Bright Data call is made
   at startup.
2. **Port.** The UI is at `http://127.0.0.1:8000/`. Check nothing else is listening on 8000
   first (`lsof -iTCP:8000 -sTCP:LISTEN`), or the server will fail to start.
3. **Browser.** Chrome, window about 1440 px wide, zoom 100 %, one tab, no extensions popping up.
   Open `http://127.0.0.1:8000/` and wait for the people cards to load.
4. **Reset session.** Header **Replan** → **Reset session** (under "Start fresh") → confirm
   **Reset session**. Reload the page.
5. **Check the starting state** on **Discover**, "People to connect with":
   **Ryan Hecht 56**, **Camila Maia 47**, **Nick Liffen 40**; right column shows
   **194** events to explore, **32** on your agenda, **0** conversations saved.
   If the top 3 differs, repeat steps 1 and 4.
6. After a rehearsal, repeat step 4: the rehearsal's "I met" is saved in FalkorDB.

## Script

| Time | Say | Do (exact UI) | On screen |
|---|---|---|---|
| 0:00 | "Every conference, you miss the three people who mattered. Conferge finds them before you land." | Stay on **Discover**. | Hero "Your week in **San Francisco**", "GitHub Universe 2026 · Oct 28 — Oct 29". |
| 0:10 | "I tell it why I'm going: I build AI developer tools and I want seed investors, agent founders and Copilot PMs." | Click the **V** avatar (top right). The goal is prefilled. Click **Update your agenda**. | Toast "Goal updated. Your agenda and suggested people have been recalculated." Chips **Meet seed investors (developer tools) · 45 %**, **Meet founders (ai agents) · 35 %**, **Meet product managers (copilot) · 20 %**. |
| 0:20 | "That goal became an agenda." | Point at the right column. | **194** events to explore, **32** on your agenda, **50** suggested connections. |
| 0:25 | "Where does the data come from? The official catalog, Luma, Partiful, and Bright Data for what is hard to reach." | Click **How are suggestions made?** (right column), then scroll to **Data pipeline**. | official **210**, luma **12**, partiful **6**, eventbrite **8**, aggregators **7** records; Sources overall **partial: Partiful not exhausted, 6 events kept**. |
| 0:35 | "Bright Data collected the stays, the flights and the LinkedIn profiles. Here is what it took: no call at query time." | Stay in the dialog; point at the counter and the pipeline rows. | "Bright Data: **38** requests, **79** records", product table (Booking 1 / 15, Airbnb 1 / 6, Google Hotels 1 / 0, LinkedIn 6 / 15, Crunchbase 1 / 2, Google Flights Web Unlocker 1 / 34, SERP 17 / 5 and 10 / 2), "Estimated cost $**0.0570**, list price estimate, not billed", "Stays via Bright Data: **6/6** · Flights via Bright Data: **1/1**". Reachability: **10 of 21** sites without Bright Data, **14 of 21** with. Close the dialog. |
| 0:45 | "My first match is Ryan Hecht. His LinkedIn profile, collected by Bright Data, confirms he works at GitHub." | Tab **People**. Hover the green **brightdata:linkedin** badge on Ryan Hecht's card. | Card **Ryan Hecht**, Product Manager · GitHub, relevance **56**, "LINKEDIN · Not provided · GitHub profile **brightdata:linkedin**". Tooltip: dataset gd_l1viktl72bvl7bjuj0, snapshot sd_mvms2ssrh1bjodbs9, identity_confidence 1. |
| 0:55 | "And this is why he's on my list: a path in the graph, from my goal to the session where he speaks." | Tab **Discover** → **See why** under Ryan Hecht. | Tab **Connections**, "**FalkorDB connected**". Path: Meet founders (ai agents) → ai agents → GitHub Copilot and Windows: Bringing local models into the workflow → Ryan Hecht. |
| 1:05 | "Conferge also tells me what to skip. Anti-FOMO." | Tab **Discover**, scroll to "You don't need to be everywhere." | **4** skips: Outside planning hours, Schedule conflict, Travel time, Lower relevance. |
| 1:15 | "Skipping this oyster bash frees three hours for better meetings." | Point at the last skip. | "Skip: Xebia’s Broad Street Oyster Bash", "What you gain: **180 min** freed for higher-value meetings". |
| 1:25 | "Now an event sells out." | Discover, "An event sold out?" → **Explore a sold-out scenario**. | Panel "Your agenda, adjusted." **Removed (1)**: Agentic engineering past the pilot. **Added (1)**: How one open source project turned funding into security at scale. |
| 1:35 | "It replans on its own, and explains why: the best remaining session in the same time slot." | Point at "Reason" and "Path". | "Simulated change, not an update from the source." Agenda still **32**. |
| 1:45 | "I met Ryan. One click, and the ranking is recomputed from FalkorDB." | Discover, "Keep the connection going." → **I met Ryan Hecht** → **Save conversation**. | Toast "Meeting with Ryan Hecht recorded. Suggestions updated." Top: **Camila Maia 47**, **Nick Liffen 40**, **Annamalai Chockalingam 39**. **1** conversations saved. |
| 1:55 | "Bright Data collects, FalkorDB stores the relationships, our agents never touch the web at query time." | Stay on Discover. | — |

## Notes

- Not shown anywhere in the UI: node and edge counts of the graph. The startup log prints
  "node writes" / "edge writes" (MERGE writes, not counts); do not quote them as graph size.
- The LinkedIn headline shows "Not provided": Bright Data returned no headline for these
  profiles. Do not invent one.
- People tab says **10 suggestions** while Discover says **50** suggested connections: both
  are on screen; quote the one you are pointing at.
- The counter reads the Bright Data cache collected earlier the same day: 0 requests are made by the running demo; times shown are each record's own `collected_at`.
