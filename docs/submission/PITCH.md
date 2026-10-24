# Conferge, the 3-minute pitch

Patch the Conference, Bright Data x WeMakeDevs, San Francisco, October 24, 2026.
Stage slot: 2 to 3 minutes per team, judges from Google, OpenAI, Apple, Amazon and Microsoft.
Nobody opens the repo. Everything rests on what the judges see on screen.

Two roles on stage. **Speaker** holds the mic and never touches the laptop. **Driver** clicks and says nothing unless asked.
Default: Ilan speaks, Axel drives. Swap if you prefer, the script does not change.

Companion files: `slides.html` (7 slides, arrow keys), `CHECKLIST.md` (the 10 minutes before), `demo-backup.mp4` (26 s, 1280 x 720, the six demo steps recorded on the snapshot).

## Two opening hooks, pick one

**Hook A, the business card.**
"Two days, 161 sessions, 231 side events, thousands of people. Most of us fly home with four business cards and the feeling we were in the wrong room. Conferge starts from your goal, not from the agenda."

**Hook B, the question to the jury.**
"Who in this room is going to GitHub Universe next week? If you want to meet seed investors, which of the 231 side events do you pick, and who do you talk to when you get there? Conferge answers that in one sentence, and shows you why."

Hook A is safer and 5 seconds shorter. Hook B works if the room is awake and someone raises a hand.

## Rules that do not bend

- Never present a fixture as live. The header badge says `fixture` for the snapshot, `live` only when the data was collected during the demo. Say out loud what the badge says.
- Say "snapshot of the public collection from October 24" rather than "live data" unless the badge reads `live`.
- Every number you say is in `SUBMISSION.md` and was measured. Nothing rounded up.
- If a click fails, the Driver does not retry more than once. The Speaker keeps talking from the slide while the Driver switches to the backup video.

## The script, minute by minute

The UI is served on http://127.0.0.1:8000 and opens on the **Demo** tab, six numbered steps on one page. The FalkorDB Browser is a second tab on http://127.0.0.1:3000. The slides are a third tab.

| Time | Who | Say | Driver clicks | What the jury must see | Track |
|---|---|---|---|---|---|
| 0:00 | Speaker | Hook A or B. "I am Ilan, this is Axel, we built Conferge." | Slides, slide 1 | The problem in one line | both |
| 0:15 | Speaker | "Give it your goal in one sentence. Not a schedule, a goal." | Switch to the Conferge tab. The goal is already in the box: founder of an AI dev tool, wants seed investors, AI agent founders, Copilot PMs. Click **Lancer**. | Step 1: three weighted goals as chips (seed investors 0.45, AI agent founders 0.35, Copilot PMs 0.20). Header badge reads `fixture`, collection date October 24, 2026. | both |
| 0:30 | Speaker | "The badge says fixture. This is a snapshot of what we collected from public sources this morning: official catalog, Luma, Partiful, Eventbrite, party aggregators. Bright Data connectors sit behind the same client for the pages that block plain HTTP: search discovery, flights, hotels, LinkedIn." | Point at the badge and the collection date. Point at the Bright Data counter line at the top of the Demo tab. | Badge, date, counter. | Bright Data |
| 0:45 | Speaker | "Who should you meet, and why. Each card is a person, and the why is a real path in the graph, not a score from a black box." | Scroll to step 2. Click the first card's path. | Step 2: ranked people. Under the card, the chain goal, topic, event, person, with the source URL and timestamp on each hop. | FalkorDB |
| 1:05 | Speaker | "Same path, in FalkorDB. Goal, topic, event, speaker. Four hops, 11 milliseconds, and every edge carries where it came from." | Switch to the FalkorDB Browser tab, graph `conferge_demo`, run the prepared query (see below). | The path lights up in the browser. | FalkorDB |
| 1:25 | Speaker | "From the people and events, a day by day plan for the days you are in town, with the venues on a map." | Back to Conferge. Scroll to step 3. | Step 3: plan per day, map with venues. | both |
| 1:40 | Speaker | "Anti-FOMO. Two events at the same time on the 28th evening. It picks one, explains why, and tells you what you give up." | Scroll to step 4. | Step 4: the conflict, the verdict, the reason, what is lost. | FalkorDB |
| 2:00 | Speaker | "Things change. We simulate that the first event of the plan sells out. It is a simulation, labelled as such." | Scroll to step 5. Click **Simuler : l'evenement n°1 du plan est complet**. | Step 5: the diff. Removed, replacement, and the reason, found through the people who also appear at another event. | FalkorDB |
| 2:20 | Speaker | "You met someone. One click writes it to the graph. The ranking changes now, and it is still there at the next conference." | Scroll to step 6. Click **J'ai rencontré ...**. | Step 6: confirmation line, top 3 before and after. | FalkorDB |
| 2:40 | Speaker | "697 nodes, 2,195 edges, every edge with a source. 984 tests. What stays after Universe is the graph itself: your memory of who you met, ready for the next conference." | Slides, slide 6 then 7. | Numbers, then what remains. | both |
| 2:55 | Speaker | "Conferge. Be in the right place, with the right people, at the right time. Thank you." | Slide 7 stays up. | | |

Total speaking time at normal pace: 2 min 50 s. If you are over 2:30 when you reach step 5, skip step 4 (anti-FOMO) and go straight to the simulated change.

### The FalkorDB Browser query, typed in advance

Open http://127.0.0.1:3000, select graph `conferge_demo`, paste this in the query box before going on stage. Replace the person id by the id of the first card in step 2 (the Driver reads it from the card's path, or from `GET /api/v1/people?limit=1`).

```cypher
MATCH p = (g:Goal {user_id: 'demo-user'})-[:ABOUT]->(:Topic)<-[:ABOUT]-(:Event)<-[:SPEAKS_AT]-(person:Person {id: '<person-id>'})
RETURN p ORDER BY length(p) LIMIT 3
```

What the FalkorDB judge should have seen by 2:40: a multi-hop query, the path shown in their own browser, shared state between the planner and the replanner (same graph, same ids), and memory that survives the session (the Meeting node written at step 6).

### What the Bright Data judge should have seen

Honest version, the default today: the collection comes from public endpoints that a plain request can reach, snapshot labelled `fixture`, and the Bright Data connectors are built behind one client and report `missing_credentials` instead of inventing data. Say it that way. The judge will respect the badge more than a vague "powered by".

If a Bright Data key was added at the morning workshop and `make demo --mode live` worked at rehearsal, add this at 0:30 and drop the sentence about the snapshot:

"The badge says live. The flights and the hotel came through Bright Data datasets during the last minutes, with the collection time on screen. The LinkedIn enrichment on the people cards came the same way."

Then at 0:45, point at a card whose source reads `brightdata`. Do not promise it if rehearsal did not show it.

## Backup when the wifi or the API drops

The video `demo-backup.mp4` is 26 seconds, 1280 x 720, and shows the six steps on the snapshot, in order: goal, who to meet, plan, anti-FOMO, simulated change, meeting recorded. It was recorded with `record_demo.py` against a local server.

What changes in the script:

1. The Driver opens the video in full screen, paused on the first frame, before the Speaker starts. QuickTime, space to play, arrow keys to step.
2. The Speaker says the same sentences. The Driver plays and pauses at each step so the Speaker's words match the frame. Six pauses, about 4 seconds of video per step.
3. The FalkorDB Browser part at 1:05 becomes slide 3 (the graph that decides) with the path drawn on the slide. Say: "This is the same path the browser shows live, our wifi dropped so here it is on the slide."
4. The timings move: the video covers 0:15 to 2:40 in about 1 min 30 s of play time plus pauses. You gain 40 seconds. Spend them on slide 6 (numbers) and slide 7 (what stays).

Localhost does not need wifi. If only the venue wifi drops, the demo still runs, since FalkorDB and the API are on the laptop. Use the video only if the laptop itself is in trouble.

## Three questions the jury may ask, and the short answer

- "Is the data real?" The collection is real and public, captured on October 24 from the GitHub Universe catalog, Luma, Partiful and Eventbrite. The demo replays that snapshot so it works offline, and the badge says so. Flights and hotels are labelled fixtures today because we had no Bright Data key at capture time.
- "Where is the LLM?" There is none in the loop today. Goal parsing and ranking are deterministic, so nothing is invented: no price, no attendance, no guest list.
- "Why a graph and not a table?" Because the answer to "why this person" is a path, and the same graph serves the planner, the replanner and your memory. Replanning after a sold-out event is one traversal: who else is at the event, where else do they appear.
