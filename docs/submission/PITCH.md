# Conferge, the 3-minute pitch

Patch the Conference, Bright Data x WeMakeDevs, San Francisco, October 24, 2026.
Stage slot: 2 to 3 minutes per team, judges from Google, OpenAI, Apple, Amazon and Microsoft.
Nobody opens the repo. Everything rests on what the judges see on screen.

Two roles on stage. **Speaker** holds the mic and never touches the laptop. **Driver** clicks and says nothing unless asked.
Default: Ilan speaks, Axel drives. Swap if you prefer, the script does not change.

Written against the interface served by `main` at `df66f45` on October 24, 2026 (local `make demo`, graph `conferge_demo` on FalkorDB).
Every button below is named as it reads on screen. Every number comes from a command listed in "Where each number comes from" at the end.

Companion files: `slides.html` (7 slides, arrow keys), `CHECKLIST.md` (the 10 minutes before), `demo-backup.mp4` (35 s, 1280 x 720, the six demo steps recorded on this interface).

## Two opening hooks, pick one

**Hook A, the business card.**
"Two days, 161 official sessions, 46 side events in our dataset, thousands of people. Most of us fly home with four business cards and the feeling we were in the wrong room. Conferge starts from your goal, not from the agenda."

**Hook B, the question to the jury.**
"Who in this room is going to GitHub Universe next week? If you want to meet seed investors, which of the 46 side events do you pick, and who do you talk to when you get there? Conferge answers that in one sentence, and shows you why."

Hook A is safer and 5 seconds shorter. Hook B works if the room is awake and someone raises a hand.

## Rules that do not bend

- Never present a fixture as live. The app says it itself in **Sources and how it works** (the round info button in the header): events and people are **Sample data**, stays and flights are **Cached**, the header line reads **Mixed sources**. Say out loud what the dialog says.
- Say "snapshot of the public collection from October 24" rather than "live data". Nothing is fetched while the jury watches.
- Every number you say comes from `SUBMISSION.md` at the repository root (read from the running app). If a number changes, change it there first, then here and in `slides.html`.
- If a click fails, the Driver does not retry more than once. The Speaker keeps talking from the slide while the Driver switches to the backup video.

## What is on screen

The UI is served on http://127.0.0.1:8000 and opens on **Discover**, one long page. From top to bottom: the city banner, **Worth making time for** (side events), **People to connect with** (three cards, each with a **See why** button), **Your agenda** (day tabs Oct 27 to Oct 30) next to **Your meeting places** (the map), **You don't need to be everywhere** (anti-FOMO), **An event sold out?** with the button **Explore a sold-out scenario**, **Keep the connection going** with the button **I met Ryan Hecht**, and **Your trip, in perspective** (four tiles: Known travel costs, Meetings recorded, Qualified contacts, Opportunities scoring 30+). The right column holds **Your priorities** (the goal sentence and three chips with percentages) and the counters (207 events, 32 on your agenda, 50 suggested connections, 0 conversations saved).

The header has five tabs: **Discover**, **My agenda**, **People**, **Travel**, **Connections**. The **Connections** tab is the graph view: **Powered by: FalkorDB connected**, the path for the selected person, the evidence of each edge, and the panel **How your planning agents coordinate** with the Cypher query, **Copy query** and **Show in FalkorDB Browser**.

The FalkorDB Browser is a second browser tab on http://127.0.0.1:3000. The slides are a third tab.

## The script, minute by minute

| Time | Who | Say | Driver clicks | What the jury must see | Track |
|---|---|---|---|---|---|
| 0:00 | Speaker | Hook A or B. "I am Ilan, this is Axel, we built Conferge." | Slides, slide 1 | The problem in one line | both |
| 0:15 | Speaker | "Give it your goal in one sentence. Not a schedule, a goal. Out come three weighted priorities: seed investors, AI agent founders, Copilot product managers." | Switch to the Conferge tab. In the right column, click **Edit priorities**. The sentence is already in the box. Click **Update your agenda**. | The dialog **What would make this trip worthwhile?** closes, toast "Goal updated". Under **Your priorities**, three chips: Meet seed investors (developer tools) 45 %, Meet founders (ai agents) 35 %, Meet product managers (copilot) 20 %. | both |
| 0:30 | Speaker | "Everything on this page is a snapshot of public sources collected this morning: the official catalog, Luma, Partiful, Eventbrite. The app says so: sample data, with the collection time. Stays, flights and the LinkedIn cards came through Bright Data earlier today and are served from that cache. Nothing is fetched while you watch." | Click the round info button in the header. Point at **Data provenance: Mixed sources**, **Last collected**, the **Sample data** and **Cached** labels per domain, then scroll to the Bright Data counter and the **Data pipeline** table. Close the dialog. | The **Sources and how it works** dialog: labels per domain, the counter (64 records through Bright Data), the pipeline rows with their collection time. | Bright Data |
| 0:45 | Speaker | "Who should you meet, and why. Each card is a person, and the why is a real path in the graph, not a score from a black box. Goal, topic, event, speaker: four hops, and every edge carries where it came from and when." | Scroll to **People to connect with**. Click **See why** on the first card (Ryan Hecht). | The **Connections** tab opens on **Why this person?**: Meet founders (ai agents) > ai agents > GitHub Copilot and Windows > Ryan Hecht, then three evidence lines (ABOUT, ABOUT, SPEAKS_AT) with source and observed-at timestamp. **Powered by: FalkorDB connected** top right. | FalkorDB |
| 1:05 | Speaker | "This is FalkorDB answering. Same graph, same ids for the planner, the replanner and your memory. Here is the query, you can run it yourself." | Plan A, if the FalkorDB Browser works at rehearsal: switch to the Browser tab, graph `conferge_demo`, run the prepared query (below). Plan B, the default today: stay on **Connections**, open **How your planning agents coordinate**, point at the Cypher line and the **Copy query** button. | Plan A: the path lights up in the Browser. Plan B: the agent table (planner 32 writes, antifomo 4), the query `MATCH (u:User {id: 'demo-user'})-[r:PLANS|SKIPS]->(e:Event) ...`, the buttons **Show in FalkorDB Browser** and **Copy query**. | FalkorDB |
| 1:25 | Speaker | "From the people and the events, a day by day agenda for the days you are in town, with the venues on a map." | Click **Discover**. Scroll to **Your agenda**. Click the **Wed, Oct 28** day tab. | Oct 28: Opening Keynote 09:00, Agentic engineering past the pilot 10:30, and the map **Your meeting places** next to it. | both |
| 1:40 | Speaker | "Anti-FOMO. Two sessions at 10:30 on the 28th. It picks one, says why, and tells you what you give up." | Scroll to **You don't need to be everywhere**. Point at the **Schedule conflict** block. | Skip: Shut the context window! (Wed, Oct 28, 10:30 AM), overlaps 'How one open source project turned funding into security at scale', utility 36.5 vs 47.0, What you gain: you keep that session, where you meet Camila Maia. | FalkorDB |
| 2:00 | Speaker | "Things change. We simulate that the top event of the plan sells out. It is a simulation, and the screen says so. Removed, replaced, and the reason." | Scroll to **An event sold out?**. Click **Explore a sold-out scenario**. | **SIMULATION (not observed): the top event of your plan becomes sold out**. REMOVED Agentic engineering past the pilot. ADDED How one open source project turned funding into security at scale (Wed, Oct 28, 10:30 AM). The reason, the path to Gregg Cochran, and the line "Simulated change, not an update from the source." | FalkorDB |
| 2:20 | Speaker | "You met Ryan. One click writes it to the graph. He leaves the ranking, the next person moves up, and the meeting is still there at the next conference." | Scroll to **Keep the connection going**. Click **I met Ryan Hecht**. In the dialog **A conversation worth remembering**, click **Save conversation** (the note is optional). | Toast "Meeting with Ryan Hecht recorded. Suggestions updated." The button now reads **I met Camila Maia**. Tiles: Meetings recorded 0 to 1, Qualified contacts 0 to 1. Counter: 1 conversation saved. In **People to connect with**, Ryan Hecht is gone, Annamalai Chockalingam enters. | FalkorDB |
| 2:40 | Speaker | "711 nodes, 2,238 edges, every edge with a source. 1,175 tests. What stays after Universe is the graph itself: your memory of who you met, ready for the next conference." | Slides, slide 6 then 7. | Numbers, then what remains. | both |
| 2:55 | Speaker | "Conferge. Be in the right place, with the right people, at the right time. Thank you." | Slide 7 stays up. | | |

Spoken words in the table, Hook A included: 347. At 150 words per minute that is 2 min 19 s of speech; with the eight clicks (about 5 s of machine time in total, measured), the scrolling and two tab switches, a full pass lands between 2:30 and 2:45. If you are past 2:30 when you reach the sold-out step, skip anti-FOMO (1:40) and go straight to the simulated change.

Note on the 1:25 step: the plan read at `/api/v1/plan` is computed from the goals, not from the previous steps; after the sold-out simulation (2:00) the Oct 28 10:30 slot changes, so keep the order above.

### The FalkorDB Browser query, typed in advance (plan A only)

Open http://127.0.0.1:3000, log in (host `localhost`, port `6379`, the port inside the container), close the download popup, select graph `conferge_demo`, paste this in the query box before going on stage. Replace the person id by the id of the first card (the Driver reads it from `GET /api/v1/people?limit=1`, field `person_ids`; today it is `person:rainfocus:1699547169825001krXG_1768417809universe26`).

```cypher
MATCH p = (g:Goal {user_id: 'demo-user'})-[:ABOUT]->(:Topic)<-[:ABOUT]-(:Event)<-[:SPEAKS_AT]-(person:Person {id: '<person-id>'})
RETURN p ORDER BY length(p) LIMIT 3
```

On the rehearsal laptop today every query in the Browser ends with "An unexpected error occurred" (`ERR invalid graph version` in the container log, FalkorDB 6.0.3 and latest, Browser 2.7.2). A separate fix is in progress. Until it lands, plan B is the stage version: the same path and the same query are on the **Connections** tab of the app. The same query through `redis-cli -p 6380 GRAPH.QUERY conferge_demo "..."` returns 3 paths in 0.11 ms, if a judge asks.

What the FalkorDB judge should have seen by 2:40: a multi-hop query with its Cypher on screen, the evidence on every edge, shared state between the planner and the replanner (same graph, same ids, the agent table), and memory that survives the session (the Meeting node written at 2:20).

### What the Bright Data judge should have seen

What `make demo` shows today (see `SUBMISSION.md`, "What is real"): events and people are the October 24 public snapshot, labelled **Sample data**; stays, flights and the LinkedIn cards came through Bright Data earlier today (datasets and Web Unlocker) and are served from the cache of those runs, labelled **Cached**, with their collection time. Say it that way: "collected through Bright Data this afternoon, stored in the graph, nothing fetched while you watch". Point at the **Data pipeline** table (records per run, Bright Data API, collection time) and at its reachability rows (sites reachable with and without Bright Data). Say the KYC figure only as a projection.

## Backup when the laptop is in trouble

The video `demo-backup.mp4` is 35 seconds, 1280 x 720, and shows the six steps on this interface, in order: priorities (dialog, Update your agenda), People to connect with then See why (the path on Connections), agenda and map, anti-FOMO, Explore a sold-out scenario, I met Ryan Hecht then Save conversation. It was recorded with `record_demo.py` against a local server with FalkorDB.

What changes in the script:

1. The Driver opens the video in full screen, paused on the first frame, before the Speaker starts. QuickTime, space to play, arrow keys to step.
2. The Speaker says the same sentences. The Driver plays and pauses at each step so the Speaker's words match the frame. Six pauses, about 5 seconds of video per step.
3. The Sources dialog (0:30) is not in the video: say the sentence over slide 4 (Bright Data).
4. The FalkorDB part at 1:05 becomes slide 3 (the graph that decides) with the path drawn on the slide. Say: "This is the same path the app shows live, our laptop dropped so here it is on the slide."
5. The timings move: the video covers 0:15 to 2:40 in 35 s of play time plus pauses. You gain about a minute. Spend it on slide 6 (numbers) and slide 7 (what stays).

Localhost does not need wifi. If only the venue wifi drops, the demo still runs, since FalkorDB and the API are on the laptop. Use the video only if the laptop itself is in trouble.

## Three questions the jury may ask, and the short answer

- "Is the data real?" The collection is real and public, captured on October 24 from the GitHub Universe catalog, Luma, Partiful and Eventbrite. The demo replays that snapshot so it works offline, and the Sources dialog says so. Stays, flights and LinkedIn cards were collected through Bright Data today and are served from that cache, labelled Cached.
- "Where is the LLM?" There is none in the loop today. Goal parsing and ranking are deterministic, so nothing is invented: no price, no attendance, no guest list.
- "Why a graph and not a table?" Because the answer to "why this person" is a path, and the same graph serves the planner, the replanner and your memory. Replanning after a sold-out event is one traversal: who else is at the event, where else do they appear.

## Where each number comes from

Measured on October 24, 2026 on `main` at `df66f45`, local laptop, `make demo` on http://127.0.0.1:8030 (the stage uses 8000), FalkorDB 6.0.3 on port 6380, graph loaded fresh.

| Number | Command | Result |
|---|---|---|
| 711 nodes | `redis-cli -p 6380 GRAPH.QUERY conferge_demo "MATCH (n) RETURN count(n)"` | 711 (the same after a meeting and a Reset) |
| 2,238 edges | `redis-cli -p 6380 GRAPH.QUERY conferge_demo "MATCH ()-[r]->() RETURN count(r)"` | 2238 |
| 1,175 tests | `uv run pytest -q` | 1175 passed, 25 skipped in 32.45 s |
| 207 events, 32 on the agenda, 50 suggested connections | the counters in the right column of **Discover**; `GET /api/v1/people?limit=100` field `total` = 50 | |
| 161 official sessions, 46 side events, 64 Bright Data records | `SUBMISSION.md`, read from `GET /api/v1/events` and `GET /api/v1/pipeline` | |
| 347 spoken words | word count of the **Say** column, Hook A included | 2 min 19 s at 150 words per minute |
| Startup | `make demo` to the first API answer | 3.3 s with cached travel; 14.6 s with `DEMO_ARGS="--travel live"` (rehearsal) |
| Clicks | Playwright, click to rendered element (rehearsal) | Update your agenda 0.04 s, Explore a sold-out scenario 1.6 s, Save conversation 0.8 s |

`GET /api/v1/graph` returns a capped sample (332 nodes, 400 edges), not the totals; use the Cypher counts above.
