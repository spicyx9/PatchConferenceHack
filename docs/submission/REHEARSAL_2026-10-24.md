# Rehearsal on a real FalkorDB, October 24, 2026

Environment: local laptop, main at 933cc72 at rehearsal time (the UI before PR 7 and the HTest merge; main moved to 50d96db while this was written, with a rewritten `static/`), worktree `docs/rehearsal`. FalkorDB `falkordb/falkordb:6.0.3`
started with `make up` through colima (no Docker Desktop on this machine; `brew install colima docker docker-compose`,
`colima start`), published on 127.0.0.1:6380 because a Homebrew Redis holds 6379. API served by `make demo`
on http://127.0.0.1:8000 in **fixture mode** (no `BRIGHTDATA_API_KEY` anywhere: not in the environment, no `.env`).
Browser: the Claude desktop browser pane and Playwright Chromium, viewport 1280 x 900 and 1600 x 900.

Startup line of `make demo`: `assembled data_mode=fixture: 207 events, 183 people, 10 opportunities in 14.6s`,
then `graph conferge_demo: 701 node writes, 2198 edge writes, 0 skipped, in 0.95s`, `indexes: 14 labels, status ['OPERATIONAL']`.
The 14.6 s are the live stays and flights searches (Airbnb and Google Flights fetched directly, no key needed);
`CHECKLIST.md` says "about one second for the load", which is only the graph write.

Graph measured after load (`redis-cli -p 6380 GRAPH.QUERY conferge_demo`): **702 nodes, 2,234 edges**.
`PITCH.md`, `SUBMISSION.md`, `slides.html` and `README.md` say 697 nodes and 2,195 edges.

## 1. The demo, step by step

| Step (PITCH.md) | Verdict | Proof |
|---|---|---|
| 0:15 Goal: text in the box, click **Run**, three weighted chips | works, but the goal text is **French** on an English UI (`fixtures/api.json:35`) and the chips read "Meet seed investors (developer tools) (0.45)", "Meet founders (ai agents) (0.35)", "Meet product managers (copilot) (0.2)", not the wording in the pitch | `docs/demo/screens/1-goal.png`, click-to-render 0.04 s |
| 0:30 Badge reads `fixture`, collection date | **badge reads `MIXED`, status `DEGRADED`**, not `fixture`: events and people are fixture, stays and flights are `live` (Airbnb and Google Flights direct fetch). The pitch sentence "flights and hotels are labelled fixtures today" is false today, they are labelled LIVE in the Travel tab | `docs/demo/screens/9-home-brightdata-counter.png`, `GET /api/v1/travel` data_source `mixed`, Travel tab shows `PRICE OBSERVED_LIVE LIVE` on both flights and `LIVE` on 5 stays |
| 0:30 Bright Data counter line | works, shows "Records collected via Bright Data: 0, datasets 0 (not configured), Web Unlocker 0 (not configured), SERP API 0 (not configured)" | same screen |
| 0:45 Who to meet, path under the card with source URL and timestamp | works on FalkorDB: top 3 Ryan Hecht, Camila Maia, Nick Liffen, path goal, topic, event, person, line `source: falkordb / mixed / signature: speaker`, buttons "Show in FalkorDB Browser" and "Copy query". The explanation ends with "Sources: user/live, rainfocus:github-universe-2026/fixture": the word "live" is on screen for fixture data (it is the Goal node, written from user input) | `docs/demo/screens/2-opps.png` |
| 1:05 Same path in the FalkorDB Browser (port 3000) | **broken**: every query, even `MATCH (g:Goal) RETURN g LIMIT 5` or a 2-node probe graph, ends with the toast "An unexpected error occurred" and `Error: ERR invalid graph version` in the container log. Tried: fresh page, fresh login (Logout All, log in again), the bundled Browser 2.7.2 of image 6.0.3 and the Browser of `falkordb/falkordb:latest` (digest 0fb85036, built 2026-10-22, also Browser 2.7.2). The same query through `redis-cli` returns 3 paths in 0.11 ms. Not reproduced elsewhere, so it may be this machine (colima arm64), but it is the laptop that goes on stage unless Axel's differs | `docs/submission/rehearsal/falkordb-browser-error-6.0.3.png`, `docker logs pch-rehearsal-falkordb-1` |
| 1:05 CHECKLIST: "graph conferge_demo selected, query pasted" | the Browser first shows a login form (host, port, "Log in") and a "FalkorDB Browser for macOS" download modal, then "Select a graph first". Neither is in `CHECKLIST.md`. The query editor autocompletes and the first attempt with ctrl+Enter accepted a suggestion and corrupted the query (`LIMIT 3LIMI`) | screenshots in the session |
| 1:25 Plan per day with map | works: Oct 27 to 30, Leaflet map with venues. Oct 27 shows "Free Coffee for Devs with Solstice" 08:00 to 14:00 and "cine cue presents: the craft" 21:00, both score 0 | `docs/demo/screens/3-plan.png` |
| 1:40 Anti-FOMO: "two events at the same time on the 28th evening" | works, but not as scripted: the conflict shown is Oct 28 **10:30**, "Shut the context window" skipped. The category labels are **French** on the English surface: HORS PLAGE HORAIRE, CONFLIT HORAIRE, TRAJET TROP LONG, SCORE FAIBLE (`conferge/api/logic.py:567`). And the "Gained" line says "you keep 'How one open source project turned funding into security at scale'", an event that is **not in the plan**: the plan (step 3 and the PLANS edges in the graph) keeps "Agentic engineering past the pilot" at 10:30. Steps 3 and 4 contradict each other on stage | `docs/demo/screens/4-antifomo.png`, `GET /api/v1/plan`, graph query on `PLANS` |
| 2:00 Simulate: event #1 sold out | works on FalkorDB: REMOVED "Agentic engineering past the pilot", ADDED "How one open source project..." (Oct 28 10:30), reason, graph path to Gregg Cochran, "Simulated change, not a real update of the source" line, `simulated change active` warning on every response | `docs/demo/screens/5-change.png`, click-to-render 1.64 s |
| 2:20 I met ... | works on FalkorDB: "Meeting with Ryan Hecht recorded (FalkorDB)", top 3 before Ryan Hecht, Camila Maia, Nick Liffen; after Camila Maia, Nick Liffen, Annamalai Chockalingam. Graph: 1 Meeting node, ROI tiles move 0 to 1 meeting, 0 to 1 qualified contact, 10 to 9 opportunities | `docs/demo/screens/6-met.png`, click-to-render 0.80 s |
| Reset (header button) | works, **risk 4 verified on the real graph**: Meeting nodes 1 to 0, Change nodes 1 to 0, 39 PLANS/SKIPS edges deleted then rewritten by the reload (36), top 3 back to Ryan Hecht, Camila Maia, Nick Liffen. `POST /api/v1/reset` returns `graph_memory_cleared: {nodes_deleted: 0, relationships_deleted: 36}`: the node count is 0 because the Meeting and Change nodes were deleted by `DETACH DELETE` and FalkorDB reports them under relationships in this driver, so the number shown is misleading, the graph is clean | `redis-cli` counts before and after, click-to-render 1.67 s |
| 2:40 Numbers slide: "697 nodes, 2,195 edges, 984 tests" | stale: 702 nodes, 2,234 edges measured; test count below | this file |
| CHECKLIST "FalkorDB not up: red banner mode degrade" | **no banner**: `make demo --no-graph` on port 8008 shows DATA MIXED, STATUS DEGRADED and the "degraded" banner stays hidden because `/plan`, `/people`, `/antifomo` answer `data_source: fixture` (the planner agents rank in memory). Nothing on screen tells the Driver the graph is missing | `docs/demo/screens/8-degraded-no-graph.png` |

Fixture shown as live: none in the strict sense. The LIVE labels on flights and stays are real direct fetches
(Airbnb, Google Flights through fast-flights), collected at 19:38 UTC today. What is wrong is the pitch text, which
promises a `fixture` badge and fixture travel.

## 2. Gated tests on the real FalkorDB

```
CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=6380 uv run pytest -q tests/graph tests/api/test_graph_ranking_live.py
116 passed, 1 warning in 1.60s
```

```
FALKORDB_PORT=6380 make e2e
15 passed in 16.50s   (tests/e2e/test_agent_state.py 5, tests/e2e/test_full_journey.py 10, all PASSED,
                       incl. test_09_met_drops_person_in_ranking and test_10_restart_keeps_ranking)
```

`tests/graph/test_graph_falkordb_live.py` reads `FALKORDB_PORT` from the environment only (default 6379), not from
`.env`: without the explicit variable it would hit the Homebrew Redis. Risk 4 (reset erases MET) is covered above by the
manual graph counts, not by a test: `test_01_reset` runs before any meeting is written.

Full suite on this checkout, no FalkorDB variable: `uv run pytest -q` = **1057 passed, 22 skipped in 33.09s** (pitch files say 984).

## 3. Timing

Machine time measured with Playwright (click to rendered element), on this laptop, FalkorDB on 6380:

| Action | seconds |
|---|---|
| page load until goal, people, plan and anti-FOMO are rendered | 2.57 |
| click Run | 0.04 |
| click Simulate | 1.64 |
| click I met | 0.80 |
| click Reset | 1.67 |
| `GET /api/v1/antifomo` alone | 0.81 |

Total machine time in the 3 minutes: about 5 s. The speaking script is 2 min 50 s by `PITCH.md`, so a full pass fits only
if the Speaker is on script. The step that does not fit is **1:05 FalkorDB Browser (20 s)**: it cannot be shown at all
today. Dropping it brings the pass to about 2 min 30 s plus clicks. I did not time a human reading the script aloud.

## 4. Backup video and screens

`docs/submission/demo-backup.webm` and `.mp4` re-recorded with `docs/submission/record_demo.py` on the English UI
against http://127.0.0.1:8000 with FalkorDB: 22.1 s, 1280 x 720, six steps, log `ok 1 goal ... ok 6 met`.
The mp4 is an H.264 transcode of the webm (ffmpeg, crf 23). The old video showed the French UI
(`docs/submission/rehearsal/old-video-frame-french.png`); a frame of the new one at 20 s is
`docs/submission/rehearsal/new-video-frame-20s.png`. `PITCH.md` still says 26 s.

**Screens**: the captures I regenerated on the 933cc72 UI were dropped at rebase time. Main (50d96db) rewrote
`static/index.html`, `app.js` and `styles.css` (PR 7, HTest merge, PR 13) and regenerated `docs/demo/screens/*.png` on
that new UI, so main's screens are kept untouched here. The step verdicts above describe the 933cc72 UI; the new UI was
not rehearsed in this session.

**Video**: the new `demo-backup.mp4` / `.webm` show the 933cc72 English UI, not the current one. `record_demo.py` clicks
`#story-met-btn`, an id that no longer exists in main's `static/index.html` (the other `#step-*` and `#story-*` ids are
still there), so the recorder needs an update before the video can be re-recorded on the current UI.

## 5. Bugs and mismatches found (no code changed in this session)

1. FalkorDB Browser: every query fails with `ERR invalid graph version` (image 6.0.3 and latest, Browser 2.7.2). Stage step 1:05 and the "Show in FalkorDB Browser" button in step 2 are unusable on this laptop. `docker-compose.yml:3`.
2. French labels on the English UI: anti-FOMO categories `conferge/api/logic.py:567-568`; goal text `fixtures/api.json:35`.
3. Anti-FOMO "Gained" names an event the displayed plan does not keep: `block_item` comes from the agent decisions, not from the displayed plan, `conferge/api/logic.py:596-606`.
4. No visible signal when FalkorDB is missing under `make demo --no-graph`: envelopes say `fixture`, banner hidden, `conferge/api/app.py:116-131` (`_ranking` under `--no-graph` ranks from the planner agents without setting `rank_mode` to `degraded_no_graph`, so the branch at `app.py:167` never fires), banner logic `static/app.js:146-150`.
5. `graph_memory_cleared.nodes_deleted` reports 0 after a reset that did delete 2 nodes, `conferge/core/store.py:91-98` (counts read from the driver's `nodes_deleted`).
6. Header badge reads MIXED, not FIXTURE, as soon as stays or flights are live; `PITCH.md` lines 24, 29, 37 and the "Three questions" answer on flights and hotels are wrong today. Option: `make demo --travel fixture` gives a FIXTURE badge but then the Travel tab is fixture.
7. Stale numbers: 697/2,195 in `PITCH.md:44`, `SUBMISSION.md:23,35`, `slides.html:151`, `README.md:135` (measured 702/2,234); 26 s video in `PITCH.md:9,85` (now 22 s).
8. `PITCH.md` still quotes the French buttons **Lancer**, **Simuler : l'evenement n°1 du plan est complet**, **J'ai rencontré** (lines 28, 41, 42); the UI says Run, "Simulate: event #1 of the plan is sold out", "I met Ryan Hecht". The anti-FOMO line at 1:40 ("two events at the same time on the 28th evening") does not match the 10:30 conflict shown.
9. `CHECKLIST.md`: no login step for the Browser, "about one second" startup is 14.6 s with live travel, "red banner mode degrade" does not exist.
10. Other graphs appeared on the shared FalkorDB during the run (`social-demo`, `social-demo-test`): another session writes to the same instance on 6380.

## 6. Not tested

- The current main UI (50d96db): every verdict above is on 933cc72.

- Live mode (`make demo --mode live`): no Bright Data key on this machine.
- The Browser step on a machine with Docker Desktop instead of colima, and on Axel's laptop.
- A human reading the script aloud with a stopwatch.
- Projector, mirrored display, zoom at 125 percent.
- The FalkorDB Browser `Show in FalkorDB Browser` deep link from step 2 (would hit the same error).
