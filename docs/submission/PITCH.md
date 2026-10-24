# Conferge, the 3-minute pitch

Patch the Conference, Bright Data x WeMakeDevs, San Francisco, October 24, 2026.
Stage slot: 2 to 3 minutes per team, judges from Google, OpenAI, Apple, Amazon and Microsoft.
Nobody opens the repo. Everything rests on what the judges see on screen.

Two roles on stage. **Speaker** holds the mic and never touches the laptop. **Driver** clicks and says nothing unless asked.
Default: Ilan speaks, Axel drives. Swap if you prefer, the script does not change.

Written against the interface served by `main` at `e6c08e4` on October 24, 2026 (local `make demo`, graph `conferge_demo` on FalkorDB, Browser v2.6.2 from `make up`).
Every button below is named as it reads on screen. Every number comes from a command listed in "Where each number comes from" at the end.

Companion files: `slides.html` (7 slides, arrow keys), `CHECKLIST.md` (the 10 minutes before), `demo-backup.mp4` (35 s, 1280 x 720, the six demo steps recorded on this interface).

## Two opening hooks, pick one

**Hook A, the business card.**
"Two days, 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed as confirmed side events), plus 33 external side events in our dataset, thousands of people. Most of us fly home with four business cards and the feeling we were in the wrong room. Conferge starts from your goal, not from the agenda."

**Hook B, the question to the jury.**
"Who in this room is going to GitHub Universe next week? If you want to meet seed investors, which of the 52 side events do you pick, and who do you talk to when you get there? Conferge answers that in one sentence, and shows you why."

Hook A is safer and 5 seconds shorter. Hook B works if the room is awake and someone raises a hand.

## Say this to judges

"We collected our travel and profile data earlier today through Bright Data, and we replay the timestamped results on stage. FalkorDB computes the ranked connections and their evidence paths, and it persists who I have met. Our rule-based planner builds the itinerary, taking known scheduling and travel constraints into account. The sold-out event is a labelled simulation: the change of plan is real, but the source status is not live."

On prices: "These are observed prices from a past collection, quoted for 2 adults. We do not guarantee booking availability, and the return flight segment was not fully collected."

## Rules that do not bend

- Never present a fixture as live. The app says it itself in **Sources and how it works** (the round info button in the header): the line **Data provenance** reads **Sample data, cached travel** today (events and people are the snapshot, stays and flights come from an earlier Bright Data collection), **Sample data, live travel** if they came through Bright Data during the demo, **Live data** only when everything was collected during the demo. Say out loud what the dialog says.
- Say "snapshot of the public collection from October 24" rather than "live data". Nothing is fetched while the jury watches.
- Every number you say comes from `SUBMISSION.md` at the repository root (read from the running app). If a number changes, change it there first, then here and in `slides.html`.
- If a click fails, the Driver does not retry more than once. The Speaker keeps talking from the slide while the Driver switches to the backup video.

## What is on screen

The UI is served on http://127.0.0.1:8000 and opens on **Discover**, one long page. From top to bottom: the city banner, **Worth making time for** (side events), **People to connect with** (three cards, each with a **View connection** button), **Your agenda** (day tabs Oct 27 to Oct 30) next to **Your meeting places** (the map), and a folded line **Outside your agenda** with the count of skipped events (anti-FOMO). The right column holds **Your priorities** (the goal sentence, three chips with percentages, **Edit priorities**).

The header has five tabs: **Discover**, **My agenda**, **People**, **Travel**, **Connections**, plus the round info button (**Sources and how it works**) and **Replan**. **View connection** opens the **Connections** tab on **Your next connection**: the person, **Record a conversation**, **The reason to connect**, **A place to start**, then two folded panels, **Why this suggestion? View the sources** (the goal to person path with the evidence of each edge, **Engine: FalkorDB**) and **Explore the relationship map** (the graph, and inside it **Planning details** with the Cypher query, **Copy query** and **Show in FalkorDB Browser**).

**My summary** (footer link **View your progress**) holds the four tiles (Known travel costs, Meetings recorded, Qualified contacts, Opportunities scoring 30+), **What's next**, **Adjust your agenda** with the button **Explore a sold-out scenario**, and **Your latest meeting** with the button **I met Ryan Hecht**.

The FalkorDB Browser (v2.6.2, started by `make up`) is a second browser tab on http://127.0.0.1:3000. The slides are a third tab.

## The script, minute by minute

| Time | Who | Say | Driver clicks | What the jury must see | Track |
|---|---|---|---|---|---|
| 0:00 | Speaker | Hook A or B. "I am Ilan, this is Axel, we built Conferge." | Slides, slide 1 | The problem in one line | both |
| 0:15 | Speaker | "Give it your goal in one sentence. Not a schedule, a goal. Out come three weighted priorities: seed investors, AI agent founders, Copilot product managers." | Switch to the Conferge tab. In the right column, click **Edit priorities**. The sentence is already in the box. Click **Update your agenda**. | The dialog **What would make this trip worthwhile?** closes, toast "Goal updated". Under **Your priorities**, three chips: Meet seed investors (developer tools) 45 %, Meet founders (ai agents) 35 %, Meet product managers (copilot) 20 %. | both |
| 0:30 | Speaker | "Everything on this page is a snapshot of public sources collected this morning: the official catalog, Luma, Partiful, Eventbrite. The app says so: sample data, with the collection time. Stays, flights and the LinkedIn cards came through Bright Data earlier today and are served from that cache. Nothing is fetched while you watch." | Click the round info button in the header. Point at **Data provenance: Sample data, cached travel**, **Last collected**, the **Sample data** and **Cached** labels per domain, then scroll to the Bright Data counter and the **Data pipeline** table. Close the dialog. | The **Sources and how it works** dialog: the provenance line, labels per domain, the counter (requests and records per Bright Data product, no invented cost), the pipeline rows with their collection time. | Bright Data |
| 0:45 | Speaker | "Who should you meet, and why. Each card is a person, and the why is a real path in the graph, not a score from a black box. Goal, topic, event, speaker: four hops, and every edge carries where it came from and when." | Scroll to **People to connect with**. Click **View connection** on the first card (Ryan Hecht). On **Connections**, open **Why this suggestion? View the sources**. | **Your next connection**: Ryan Hecht, Product Manager at GitHub, **The reason to connect**, **A place to start** (his session, Wed, Oct 28, 11:50 AM). Under the sources: **Why this person?** Meet founders (ai agents), ai agents, GitHub Copilot and Windows, Ryan Hecht, then three evidence lines (ABOUT, ABOUT, SPEAKS_AT) with source and observed-at timestamp, **Engine: FalkorDB**. | FalkorDB |
| 1:05 | Speaker | "Same path, in FalkorDB itself. Same graph, same ids for the planner, the replanner and your memory. Four hops, and every edge carries where it came from." | Switch to the FalkorDB Browser tab, graph `conferge_demo`, the prepared query (below) already in the box: click the blue **Run** arrow. | The path lights up in the Browser: Goal, Topic, Event, Person, 4 nodes and 3 edges. Plan B if the Browser fails on stage: on **Connections**, open **Explore the relationship map** then **Planning details**, point at the Cypher line and the **Copy query** button. | FalkorDB |
| 1:25 | Speaker | "From the people and the events, a day by day agenda for the days you are in town, with the venues on a map." | Click **Discover**. Scroll to **Your agenda**. Click the **Wed, Oct 28** day tab. | Oct 28: Opening Keynote 09:00, Agentic engineering past the pilot 10:30, and the map **Your meeting places** next to it. | both |
| 1:40 | Speaker | "Anti-FOMO. Two sessions at 10:30 on the 28th. It picks one, says why, and tells you what you give up." | Scroll to **Outside your agenda**, click the line to unfold it, then **Why it's not in your agenda** under "Shut the context window!". | Four skipped events. Shut the context window! (Wed, Oct 28, 10:30 AM): overlaps 'How one open source project turned funding into security at scale' incl. 20 min travel; utility 36.5 vs 47.0. | planner (Python) |
| 2:00 | Speaker | "Things change. We simulate that the top event of the plan sells out. It is a simulation, and the screen says so. Removed, replaced, and the reason." | Click **View your progress** in the footer (**My summary**). Under **Adjust your agenda**, click **Explore a sold-out scenario**. | **SIMULATION (not observed): the top event of your plan becomes sold out**. REMOVED Agentic engineering past the pilot. ADDED How one open source project turned funding into security at scale (Wed, Oct 28, 10:30 AM). The reason, the path to Gregg Cochran, and the line "Simulated change, not an update from the source." | planner (Python) |
| 2:20 | Speaker | "You met Ryan. One click writes it to the graph. He leaves the ranking, the next person moves up, and the meeting is still there at the next conference." | Under **Your latest meeting**, click **I met Ryan Hecht**. In the dialog **A conversation worth remembering**, click **Save conversation** (the note is optional). | Toast "Meeting with Ryan Hecht recorded. Suggestions updated." The button now reads **I met Camila Maia**. Tiles: Meetings recorded 0 to 1, Qualified contacts 0 to 1. On **Discover**, Ryan Hecht has left **People to connect with**. | FalkorDB |
| 2:40 | Speaker | "690 nodes / 2 184 edges loaded from the catalogue; 691 / 2 213 once the plan is written (1 User node, 25 PLANS edges, 4 SKIPS edges for the anti-FOMO skips); the graph then grows with every meeting you record. Every edge has a source. 1476 tests. What stays after Universe is the graph itself: your memory of who you met, ready for the next conference." | Slides, slide 6 then 7. | Numbers, then what remains. | both |
| 2:55 | Speaker | "Conferge. Be in the right place, with the right people, at the right time. Thank you." | Slide 7 stays up. | | |

Spoken words in the table, Hook A included: 349. At 150 words per minute that is 2 min 20 s of speech; with the eleven clicks (about 5 s of machine time in total, measured), the scrolling and three tab switches, a full pass lands between 2:35 and 2:50. If you are past 2:30 when you reach the sold-out step, skip anti-FOMO (1:40) and go straight to the simulated change.

Note on the 1:25 step: after the sold-out simulation (2:00) the Oct 28 10:30 slot changes, so keep the order above.

### The FalkorDB Browser query, typed in advance

Open http://127.0.0.1:3000, keep the login defaults (localhost, 6379, no user), **Log in**, **Skip Tutorial**, select graph `conferge_demo` (Select Graph, left panel), paste this in the query box before going on stage. Replace the person id by the id of the first card (the Driver reads it from `GET /api/v1/people?limit=1`, field `person_ids`; today it is `person:rainfocus:1699547169825001krXG_1768417809universe26`).

```cypher
MATCH p = (g:Goal {user_id: 'demo-user'})-[:ABOUT]->(:Topic)<-[:ABOUT]-(:Event)<-[:SPEAKS_AT]-(person:Person {id: '<person-id>'})
RETURN p ORDER BY length(p) LIMIT 3
```

The Browser bundled in the FalkorDB 6.0.3 image (2.7.2) fails every query with "An unexpected error occurred"; `make up` now starts Browser v2.6.2 instead on the same port, and its header must read v2.6.2. Verified on October 24 on `e6c08e4`: the query above returns the path, 4 nodes and 3 edges (capture `rehearsal/falkordb-browser-path-v2.6.2.png`). The share link from **Show in FalkorDB Browser** pre-fills the query but does not run it: one click on **Run** is needed. Plan B if it fails on stage: the same path is under **Why this suggestion? View the sources** and the same query under **Planning details** on the **Connections** tab of the app.

What the FalkorDB judge should have seen by 2:40: a multi-hop query, the path shown in their own Browser, the evidence on every edge in the app, the ranking and the evidence paths come from FalkorDB, while the plan and the diff are built by the Python planner, and memory that survives the session (the Meeting node written at 2:20).

### What the Bright Data judge should have seen

What `make demo` shows today (see `SUBMISSION.md`, "What is real"): events and people are the October 24 public snapshot, labelled **Sample data**; stays, flights and the LinkedIn cards came through Bright Data earlier today (datasets and Web Unlocker) and are served from the cache of those runs, labelled **Cached**, with their collection time. Say it that way: "collected through Bright Data this afternoon, stored in the graph, nothing fetched while you watch". Point at the **Data pipeline** table (records per run, Bright Data API, collection time) and at its reachability rows (sites reachable with and without Bright Data). Say the KYC figure only as a projection. Name only what returned records: the Booking, Airbnb and LinkedIn datasets and Web Unlocker. The Google Flights dataset and the Google Hotels dataset are implemented, no record received yet: never present them as used.

## Backup when the laptop is in trouble

The video `demo-backup.mp4` is 35 seconds, 1280 x 720, and shows the six steps on this interface, in order: priorities (dialog, Update your agenda), People to connect with then View connection (the path and sources on Connections), agenda and map, Outside your agenda unfolded, Explore a sold-out scenario and I met Ryan Hecht then Save conversation on My summary. It was recorded with `record_demo.py` against a local server with FalkorDB.

What changes in the script:

1. The Driver opens the video in full screen, paused on the first frame, before the Speaker starts. QuickTime, space to play, arrow keys to step.
2. The Speaker says the same sentences. The Driver plays and pauses at each step so the Speaker's words match the frame. Six pauses, about 5 seconds of video per step.
3. The Sources dialog (0:30) is not in the video: say the sentence over slide 4 (Bright Data).
4. The FalkorDB Browser part at 1:05 becomes slide 3 (the graph that ranks and explains) with the path drawn on the slide. Say: "This is the same path the Browser shows live, our laptop dropped so here it is on the slide."
5. The timings move: the video covers 0:15 to 2:40 in 35 s of play time plus pauses. You gain about a minute. Spend it on slide 6 (numbers) and slide 7 (what stays).

Localhost does not need wifi. If only the venue wifi drops, the demo still runs, since FalkorDB and the API are on the laptop. Use the video only if the laptop itself is in trouble.

## Three questions the jury may ask, and the short answer

- "Is the data real?" The collection is real and public, captured on October 24 from the GitHub Universe catalog, Luma, Partiful and Eventbrite. The demo replays that snapshot so it works offline, and the Sources dialog says so. Stays, flights and LinkedIn cards were collected through Bright Data today and are served from that cache, labelled Cached.
- "Where is the LLM?" There is none in the loop today. Goal parsing and ranking are deterministic, so nothing is invented: no price, no attendance, no guest list.
- "Why a graph and not a table?" Because the answer to "why this person" is a path, and the same graph serves the planner, the replanner and your memory. FalkorDB ranks people and events, remembers meetings and skips, and provides the evidence paths; the rule-based Python planner builds the plan and the diff.

## Where each number comes from

All numbers: `STATUS.md`, section "Measured on dfca2bf at 15:33 PDT", read by command after `make predemo` on that commit.

| Number | Command | Result |
|---|---|---|
| Graph | `redis-cli -p 6380 GRAPH.RO_QUERY conferge_demo "MATCH (n) RETURN count(n)"` and `"MATCH ()-[r]->() RETURN count(r)"` | 690 nodes / 2 184 edges loaded from the catalogue; 691 / 2 213 once the plan is written (1 User node, 25 PLANS edges, 4 SKIPS edges for the anti-FOMO skips); the graph then grows with every meeting you record |
| Tests | `make check` | 1476 passed, 26 skipped |
| Events | `GET /api/v1/events` | 194: 161 catalogue slots (142 official sessions outside Social, 19 catalogue Social items classed `confirmed_side_event`) and 33 external side events (Luma 12, Eventbrite 8, conferenceparties 7, Partiful 6) |
| Agenda | `GET /api/v1/plan` | 25 items |
| Sold-out scenario | `POST /api/v1/simulate-change` | Agentic engineering past the pilot: An enterprise playbook replaced by How one open source project turned funding into security at scale |
| People | `GET /api/v1/people?limit=100` | top 50; top 3 Ryan Hecht 56, Camila Maia 47, Nick Liffen 40; after "I met Ryan Hecht": Camila Maia 47, Nick Liffen 40, Annamalai Chockalingam 38.5 |

`GET /api/v1/graph` returns a capped sample, not the totals; use the Cypher counts above.
