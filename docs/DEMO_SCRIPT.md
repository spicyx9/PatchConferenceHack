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

1. **Run `FALKORDB_PORT=6380 make predemo`** from `~/PatchConferenceHack` (section above). It
   frees port 8000, starts the demo on a reset graph from the Bright Data cache (no Bright Data
   call at startup) and must end with every line OK.
2. **Port.** The UI is at `http://127.0.0.1:8000/` (the URL `make predemo` prints).
3. **Browser.** Chrome, window about 1440 px wide, zoom 100 %, one tab, no extensions popping up.
   Open `http://127.0.0.1:8000/` and wait for the people cards to load.
4. **Reset session.** Header **Replan** → **Reset session** (under "Start fresh") → confirm
   **Reset session**. Reload the page.
5. **Check the starting state** on **Discover**, "People to connect with", in this order:
   **Ryan Hecht**, **Camila Maia**, **Nick Liffen** (scores 56, 47, 40 in `GET /api/v1/people`);
   right column shows **194** events to explore and **25** agenda items (`GET /api/v1/plan`),
   **0** conversations saved. If the top 3 differs, repeat steps 1 and 4.
6. After a rehearsal, repeat step 4: the rehearsal's "I met" is saved in FalkorDB.

## Script

Values measured on `c6c4d7d` at 15:18 PDT (`STATUS.md`); labels as they read in `static/` on that commit.

| Time | Say | Do (exact UI) | On screen |
|---|---|---|---|
| 0:00 | "Every conference, you miss the three people who mattered. Conferge finds them before you land." | Stay on **Discover**. | The city banner and **People to connect with**. |
| 0:10 | "I tell it why I'm going: I build AI developer tools and I want seed investors, agent founders and Copilot PMs." | Right column, **Edit priorities**. The sentence is prefilled. Click **Update your agenda**. | Toast "Goal updated". Three chips under **Your priorities**. |
| 0:20 | "That goal became an agenda." | Point at the right column. | **194** events to explore and **25** agenda items (`GET /api/v1/plan`); people ranked: top **50**. |
| 0:25 | "Where does the data come from? The official catalogue, Luma, Partiful, Eventbrite, and Bright Data for what is hard to reach." | Click the round info button (**Sources and how it works**), scroll to **Data pipeline**. | The pipeline rows with their collection time; events: 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed confirmed_side_event) and 33 external side events (Luma 12, Eventbrite 8, conferenceparties 7, Partiful 6). |
| 0:35 | "Bright Data collected the stays, the flights and the profiles earlier today. We replay the timestamped results." | Stay in the dialog; point at the Bright Data counter. Close the dialog. | **39** requests, **81** records from the cache; 0 requests by the running demo. |
| 0:45 | "My first match is Ryan Hecht, and this is why: a path in the graph, from my goal to the session where he speaks." | Under **People to connect with**, click **View connection** on Ryan Hecht. | Tab **Connections**: **Why this person?** with the goal to person path and its evidence, "Engine: FalkorDB". |
| 1:05 | "Conferge also tells me what to skip." | Click **Discover**, unfold **Outside your agenda**. | The skipped events, each with its reason. |
| 1:25 | "Now an event sells out. This is a labelled simulation." | Open **My summary** (`http://127.0.0.1:8000/#dashboard`; no link to it in the header). Under **Adjust your agenda**, click **Explore a sold-out scenario**. | Removed: **Agentic engineering past the pilot: An enterprise playbook**. Added: **How one open source project turned funding into security at scale**. "Simulated change, not an update from the source." |
| 1:45 | "I met Ryan. One click, and FalkorDB remembers it; the ranking is recomputed." | Still on **My summary**, under **Your latest meeting**, click "I met Ryan Hecht", then **Save conversation**. | Toast "Meeting with Ryan Hecht recorded. Suggestions updated." Top 3: Camila Maia 47, Nick Liffen 40, Annamalai Chockalingam 38.5. |
| 1:55 | "Bright Data collects, FalkorDB ranks and remembers, our planner builds the plan; nothing is fetched while you watch." | Stay on **My summary**. | — |

## Notes

- Not shown anywhere in the UI: node and edge counts of the graph. The startup log prints
  "node writes" / "edge writes" (MERGE writes, not counts); do not quote them as graph size.
- The People tab lists 10 cards while Discover counts the top 50: quote the one you are pointing at.
- The counter reads the Bright Data cache collected earlier the same day: 0 requests are made by the running demo; times shown are each record's own `collected_at`.
